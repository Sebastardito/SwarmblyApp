"""Recipes: the "¿Qué quieres hacer?" entry (3.3/3.4).

A recipe is a way of working the user picks before writing: it fills the
request with a template the user completes, and it turns on what that kind of
work needs. The answer then goes through the same chat as any other message;
what the recipe changed is recorded in the answer (``meta.recipe``) and in its
receipt. A recipe never widens what may leave the computer: research with
public sources still sends only the query the user approves, word for word.

- ``documents`` · ask your documents: the user's sources only, no public lookup
  offered for that answer.
- ``table`` · compare documents in a table: the table built by code (recipe 2),
  even when the request does not use the word "tabla".
- ``research`` · research with public sources: the query proposed before the
  answer and approved by the user; the documents and the results, the
  comparison by code, the disagreements and the claim verifier (recipe 3).
- ``list`` · process a list on the swarm: the user pastes items or picks a CSV
  column, writes an operation, sees exactly what would leave, and gets a table
  built by code (recipe 4).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

RECIPES = ("documents", "table", "research", "list")
AVAILABLE = ("documents", "table", "research", "list")

# A list is user-authored data, not a document: these are validation limits,
# not retrieval limits. The CSV reader deliberately does not reuse C1's
# 400-row paragraph cap; it reads real CSV records (quoted multi-line fields
# included) up to the configured list ceiling.
MAX_ITEM_CHARS = 500
MAX_OPERATION_CHARS = 2000
LANE_ORDER = {"PUBLIC": 0, "SANITISABLE": 1, "SENSITIVE": 2}
_TIER_ORDER = {"GLOBAL": 0, "TRUSTED": 1, "LOCAL": 2}


class ListJobError(ValueError):
    """A list job the server cannot accept; the message says why."""


@dataclass
class ListJob:
    items: list[str]
    operation: str
    where: str = "local"                  # swarm | local
    source: dict[str, Any] = field(default_factory=lambda: {"kind": "pasted"})

    def to_dict(self) -> dict[str, Any]:
        return {"items": list(self.items), "operation": self.operation,
                "where": self.where, "source": dict(self.source)}


def valid(recipe: str | None) -> str:
    """The recipe's id when it can run, otherwise ""."""
    recipe = str(recipe or "").strip().lower()
    return recipe if recipe in AVAILABLE else ""


def listing() -> list[dict[str, Any]]:
    """The recipes and whether each can run (the names and templates are the
    interface's, in its language)."""
    return [{"id": r, "available": r in AVAILABLE} for r in RECIPES]


def _clean_item(value: Any, row: int) -> str:
    if not isinstance(value, str):
        raise ListJobError(f"item {row} must be text")
    item = " ".join(value.split())         # quoted CSV fields may span lines
    if not item:
        raise ListJobError(f"item {row} is empty")
    if len(item) > MAX_ITEM_CHARS:
        raise ListJobError(f"item {row} is longer than {MAX_ITEM_CHARS} characters")
    return item


def _items_from(value: Any, max_items: int) -> list[str]:
    raw: list[Any]
    if isinstance(value, str):
        raw = value.splitlines()
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    elif value is None:
        raw = []
    else:
        raise ListJobError("items must be pasted text or a list")
    items: list[str] = []
    for row, item in enumerate(raw, 1):
        if isinstance(item, str) and not item.strip():
            continue                       # empty lines are dropped
        items.append(_clean_item(item, row))
    if not items:
        raise ListJobError("the list has no items")
    if len(items) > max_items:
        raise ListJobError(f"the list has {len(items)} items; the maximum is {max_items}")
    return items


def _resolve_csv(roots: Iterable[Path | str], rel: str) -> Path:
    if not rel or Path(rel).is_absolute():
        raise ListJobError("the CSV file must be inside the project's sources")
    for root in roots or []:
        base = Path(root).expanduser().resolve()
        candidate = (base / rel).resolve()
        if candidate == base or base not in candidate.parents:
            continue
        if candidate.is_file() and candidate.suffix.lower() == ".csv":
            return candidate
    raise ListJobError(f"CSV file {rel!r} is not in the project's sources")


def read_csv_column(path: Path | str, column: str, max_items: int) -> list[str]:
    """The named column of a real CSV file, in order.

    Uses :mod:`csv`, so a quoted field may contain commas and line breaks.
    Empty values are dropped (they are empty lines for this recipe); more
    than ``max_items`` non-empty values is an error, never a silent cut.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    except OSError as exc:
        raise ListJobError(f"cannot read {path.name}: {exc}") from exc
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise ListJobError(f"invalid CSV: {exc}") from exc
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        raise ListJobError("the CSV file is empty")
    header = [str(cell).strip() for cell in rows[0]]
    wanted = str(column or "").strip()
    index = next((i for i, name in enumerate(header) if name == wanted), None)
    if index is None:
        index = next((i for i, name in enumerate(header)
                      if name.casefold() == wanted.casefold()), None)
    if index is None:
        raise ListJobError(f"the CSV has no column {wanted!r}")
    out: list[str] = []
    for row in rows[1:]:
        value = row[index] if index < len(row) else ""
        if not str(value).strip():
            continue
        out.append(_clean_item(value, len(out) + 2))
        if len(out) > max_items:
            raise ListJobError(f"the CSV has more than {max_items} items")
    if not out:
        raise ListJobError(f"the column {wanted!r} has no values")
    return out


def duplicate_rows(items: list[str]) -> list[dict[str, int]]:
    """Positions that repeat an earlier item. Duplicates are kept, never merged."""
    seen: dict[str, int] = {}
    out: list[dict[str, int]] = []
    for n, item in enumerate(items, 1):
        key = item.casefold()
        if key in seen:
            out.append({"n": n, "of": seen[key]})
        else:
            seen[key] = n
    return out


def normalise_list_job(payload: Any, *, max_items: int = 200,
                       roots: Iterable[Path | str] | None = None,
                       read_source: bool | None = None) -> ListJob:
    """Validate a pasted or CSV list job. ``read_source`` defaults to true
    when roots are given (the preview), false when the client sent items."""
    if isinstance(payload, ListJob):
        items = _items_from(payload.items, max_items)
        operation = payload.operation
        where = payload.where
        source = dict(payload.source or {"kind": "pasted"})
    elif isinstance(payload, dict):
        items_value = payload.get("items")
        operation = str(payload.get("operation") or "")
        where = str(payload.get("where") or "local")
        source = payload.get("source") or {"kind": "pasted"}
    else:
        raise ListJobError("a list job must be an object")
    operation = operation.strip()
    if not operation:
        raise ListJobError("the operation is empty")
    if len(operation) > MAX_OPERATION_CHARS:
        raise ListJobError(f"the operation is longer than {MAX_OPERATION_CHARS} characters")
    where = where.strip().lower()
    if where not in ("swarm", "local"):
        raise ListJobError("where must be 'swarm' or 'local'")
    if not isinstance(source, dict):
        raise ListJobError("source must be an object")
    kind = str(source.get("kind") or "pasted").strip().lower()
    if kind not in ("pasted", "csv"):
        raise ListJobError("source.kind must be 'pasted' or 'csv'")
    source = {"kind": kind, **{k: v for k, v in source.items() if k != "kind"}}
    if kind == "csv":
        source["file"] = str(source.get("file") or "").strip()
        source["column"] = str(source.get("column") or "").strip()
        if not source["file"] or not source["column"]:
            raise ListJobError("a CSV source needs a file and a column")
        if read_source is None:
            read_source = roots is not None
        if read_source:
            if roots is None:
                raise ListJobError("a CSV source needs readable project sources")
            items = read_csv_column(_resolve_csv(roots, source["file"]),
                                    source["column"], max_items)
        else:
            items = _items_from(items_value, max_items)
    else:
        items = _items_from(items_value, max_items)
        source = {"kind": "pasted"}
    return ListJob(items=items, operation=operation, where=where, source=source)


def list_wave_size(cfg: dict[str, Any]) -> int:
    """Items per wave: one plan's capacity.

    ``n_fragments_max`` fragments per plan × ``min_items_per_fragment`` items
    per fragment (default 4 × 3 = 12). A long list is processed in sequential
    waves of this size; every wave is admitted and voted by the existing
    batch path unchanged.
    """
    swarm = (cfg or {}).get("swarm") or {}
    try:
        fragments = max(1, int(swarm.get("n_fragments_max", 4)))
    except (TypeError, ValueError):
        fragments = 4
    try:
        per_fragment = max(1, int(swarm.get("min_items_per_fragment", 3)))
    except (TypeError, ValueError):
        per_fragment = 3
    return max(1, fragments * per_fragment)


def list_language(operation: str) -> str:
    from .lang import detect_language
    try:
        return "es" if detect_language(operation or "") == "es" else "en"
    except Exception:
        return "en"


def build_list_prompt(operation: str, items: list[str]) -> str:
    """The enumerated prompt the existing admission/orchestrator path expects.

    The operation is the user's text; the app adds only the per-item cue and
    the structural ``Items:`` heading. Every wave uses this same shape with
    its own slice of items.
    """
    lang = list_language(operation)
    if lang == "es":
        cue = ("Para cada elemento numerado, responde solo ese elemento. "
               "Escribe una línea por elemento: «número. respuesta».")
        heading = "Elementos:"
    else:
        cue = ("For each numbered item, answer only that item. "
               "Write one line per item: \"number. answer\".")
        heading = "Items:"
    numbered = "\n".join(f"{n}. {item}" for n, item in enumerate(items, 1))
    return f"{operation.strip()}\n\n{cue}\n{heading}\n{numbered}"


def summary_line(count: int, answered: int, missing: int, disagreement: int,
                 lang: str = "en") -> str:
    if lang == "es":
        return (f"{count} elementos: {answered} respondidos, {missing} faltantes, "
                f"{disagreement} en desacuerdo.")
    return (f"{count} items: {answered} answered, {missing} missing, "
            f"{disagreement} disagreement.")


def _tier_for(text: str, privacy_cfg: dict[str, Any]) -> dict[str, Any]:
    """Tier classification with the same precedence as the orchestrator.

    ``auto_tier`` is what local triage found, separately from the configured
    default and a manual flag: the preview uses it to say which item is
    personal, without calling every item personal merely because the user's
    policy is LOCAL.
    """
    from swarmbly_v0 import classify
    try:
        auto = classify(text, manual=None)
        auto_tier, auto_rationale = auto.tier, auto.rationale
    except ValueError as exc:
        auto_tier, auto_rationale = "TRUSTED", (
            "regulated entities detected; no trusted swarm configured "
            f"(E_SWARM_UNKNOWN): {str(exc)[:120]}")
    manual = (privacy_cfg or {}).get("manual_tier")
    if manual in ("GLOBAL", "TRUSTED", "LOCAL"):
        try:
            d = classify(text, manual=str(manual).lower())
            return {"tier": d.tier, "auto_tier": auto_tier, "source": "manual",
                    "rationale": d.rationale}
        except ValueError as exc:
            return {"tier": "TRUSTED", "auto_tier": auto_tier, "source": "manual",
                    "rationale": f"{exc} — kept on this device"}
    default = str((privacy_cfg or {}).get("tier") or "LOCAL").upper()
    tier = max((default, auto_tier), key=lambda t: _TIER_ORDER.get(t, 2))
    return {"tier": tier, "auto_tier": auto_tier,
            "source": "auto" if tier == auto_tier and tier != default else "config",
            "rationale": auto_rationale if tier == auto_tier and tier != default
            else f"configured default tier {default}"}


def _lane_for(text: str) -> str:
    from .engine.lane import classify
    try:
        return classify(text)
    except Exception:
        return "SENSITIVE"


def classify_list_job(job: ListJob, cfg: dict[str, Any]) -> dict[str, Any]:
    """Tier and lane over the operation and every item, never the combined
    text alone: one personal item is enough to make the default local."""
    privacy_cfg = (cfg or {}).get("privacy") or {}
    operation_tier = _tier_for(job.operation, privacy_cfg)
    operation_lane = _lane_for(job.operation)
    items: list[dict[str, Any]] = []
    top_tier = operation_tier["tier"]
    top_lane = operation_lane
    for n, item in enumerate(job.items, 1):
        decision = _tier_for(item, privacy_cfg)
        tier, lane = decision["tier"], _lane_for(item)
        items.append({"n": n, "tier": tier, "auto_tier": decision["auto_tier"],
                      "lane": lane})
        if _TIER_ORDER.get(tier, 2) > _TIER_ORDER.get(top_tier, 2):
            top_tier = tier
        if LANE_ORDER.get(lane, 0) > LANE_ORDER.get(top_lane, 0):
            top_lane = lane
    sensitive = top_tier in ("LOCAL", "TRUSTED") or top_lane in ("SENSITIVE", "SANITISABLE")
    flagged = [x for x in items
               if x["auto_tier"] != "GLOBAL" or x["lane"] in ("SENSITIVE", "SANITISABLE")]
    if operation_tier["auto_tier"] != "GLOBAL" or operation_lane in ("SENSITIVE", "SANITISABLE"):
        flagged.insert(0, {"n": 0, "tier": operation_tier["auto_tier"], "lane": operation_lane})
    if top_lane == "SENSITIVE":
        reason = "personal or sensitive content classified SENSITIVE: local execution only"
    elif top_lane == "SANITISABLE":
        reason = ("content classified SANITISABLE: pseudonymisation is not implemented, "
                  "so it stays local")
    elif top_tier == "LOCAL":
        reason = "privacy tier LOCAL: nothing leaves the device"
    elif top_tier == "TRUSTED":
        reason = "tier TRUSTED needs mutual TLS, not implemented: stays local"
    else:
        reason = ""
    return {"tier": top_tier, "lane": top_lane, "sensitive": sensitive,
            "rationale": operation_tier.get("rationale", ""),
            "operation": {"tier": operation_tier["tier"], "lane": operation_lane},
            "items_flagged": flagged, "local_reason": reason}


def preview_list(job: ListJob, *, cfg: dict[str, Any], nodes_available: int = 0,
                 nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What would leave, plus the privacy result. Sends nothing."""
    privacy = classify_list_job(job, cfg)
    duplicates = duplicate_rows(job.items)
    nodes_available = max(0, int(nodes_available or 0))
    if privacy["sensitive"]:
        default_where = "local"
        reason = privacy["local_reason"] or "personal or sensitive content: local by default"
    elif not nodes_available:
        default_where = "local"
        reason = "no connected worker is available"
    else:
        default_where = "swarm"
        reason = ""
    return {
        "items": list(job.items),
        "count": len(job.items),
        "duplicates": len(duplicates),
        "duplicate_rows": duplicates,
        "operation": job.operation,
        "what_leaves": {
            "operation": job.operation,
            "items": list(job.items),
            "count": len(job.items),
            "prompt": build_list_prompt(job.operation, job.items),
        },
        "nodes_available": nodes_available,
        "nodes": list(nodes or []),
        "privacy": privacy,
        "default_where": default_where,
        "local_only_reason": reason,
        "wave_size": list_wave_size(cfg),
        "waves": max(1, -(-len(job.items) // list_wave_size(cfg))),
    }


# what the research template says around the user's words
_TOPIC = re.compile(r"(?:fuentes\s+p[uú]blicas|public\s+sources)\s+(?:dicen\s+|say\s+)?(?:sobre|acerca\s+de|de|about|on)\s+"
                    r"(.+?)(?:,|\s+y\s+di\b|\s+and\s+say\b|[.?!]|$)", re.I)
_NAME = re.compile(r"(?<=[^\W\d_])[\s,;:(«\"']+([A-ZÁÉÍÓÚÑ][\wáéíóúñü-]{2,})")


def propose_query(text: str, glossary: list[tuple[str, str]] | None = None) -> str:
    """The query offered to the user before a research answer: nothing is sent
    until the user approves it (and may edit it). The template's own words
    ("Compara … con lo que dicen las fuentes públicas sobre …") are not the
    topic: the query is what follows "sobre", and the names the request gives
    ("la variedad Kanela")."""
    from .web_search import propose_query as propose, strip_private
    m = _TOPIC.search(text or "")
    if m:
        # only the topic the user wrote for the public sources: the rest of
        # the request is about their documents ("el rendimiento del lote AB2"), and a
        # lot code or a name from it does not belong in a public query
        return strip_private(propose(m.group(1), "", glossary or []), text or "")[:200]
    query = propose(text or "", "", glossary or [])
    words = {w.lower() for w in query.split()}
    names = [n for n in _NAME.findall(text or "") if n.lower() not in words]
    # the names go through the same filter as the rest: a plot ("la Parcela
    # Sur"), a person ("la Dra. Ana Pérez") or a code is the user's, not a topic
    # (sealed bank v3.2: a plot name was proposed and, approved, sent)
    return strip_private(" ".join([query, *names]), text or "").strip()[:200]
