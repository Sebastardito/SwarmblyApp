"""LCE adapter — C0 active, C1 retrieval over sources for local answers.

C0 is "Swarmbly unchanged": the app works without any LCE component. When LCE
is enabled, the adapter prepares the local plane (source space, conservative
learning policy) with ``swarmbly_lce`` itself, and provides the WorkerGuard
that keeps the worker role conformant with invariant I2 (workers serve the
base model; personal adapters never travel). Digestion, retrieval-over-sources
and projection (C1 productive) are wired in later phases; the UI marks them as
prepared/experimental, never as done.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import DataDirs

LEVELS = {
    "C0": {"active": True, "status": "active",
           "note": "Swarmbly unchanged; no LCE components applied."},
    "C1": {"active": True, "status": "active (local answers)",
           "note": "Retrieval over your raw sources (BM25 over paragraphs) is added "
                  "to answers produced on this device, with the source cited. "
                  "Passages never leave the device; projection into Γ needs "
                  "digested claims (C2) and stays empty at C1."},
    "C2": {"active": False, "status": "disabled",
           "note": "Automatic digestion — later phase (digester exists in SwarmblyLCE)."},
    "C3": {"active": False, "status": "disabled",
           "note": "Social capsules — implemented upstream but not validated on a real "
                  "network; not exposed as a product feature."},
    "C4": {"active": False, "status": "disabled",
           "note": "LoRA fine-tuning — experimental, no verdict (R11). Training stays off "
                  "by default (invariant I8)."},
}

# Conservative default per invariant I8: what is not declared does not train.
# Format follows swarmbly_lce.policy.LearningPolicy.from_mapping (v0.1):
# a mapping with "v", "defaults" (SourceRule fields) and "sources" (prefix rules).
DEFAULT_POLICY = {
    "v": "0.1",
    "defaults": {"reference_only": True, "train": True},
    "sources": {},
}


class LCEAdapter:
    def __init__(self, dirs: DataDirs):
        self.dirs = dirs

    # -- package availability -------------------------------------------------
    def package_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"installed": False, "version": None,
                                "crypto": False}
        try:
            import swarmbly_lce
            info["installed"] = True
            info["version"] = swarmbly_lce.__version__
            info["spec_version"] = swarmbly_lce.SPEC_VERSION
            info["capsule_version"] = swarmbly_lce.CAPSULE_VERSION
        except Exception:
            pass
        try:
            from swarmbly_lce.crypto import crypto_available
            info["crypto"] = crypto_available()
        except Exception:
            pass
        return info

    # -- lifecycle -------------------------------------------------------------
    def status(self, enabled: bool, level: str) -> dict[str, Any]:
        meta = LEVELS.get(level, LEVELS["C0"])
        return {
            "enabled": enabled,
            "level": level,
            "active": enabled and bool(meta["active"]),
            "state": meta["status"] if enabled else "disabled",
            "note": meta["note"],
            "levels": LEVELS,
            "package": self.package_info(),
            "paths": {"sources": str(self.dirs.sources),
                      "wiki": str(self.dirs.wiki),
                      "adapters": str(self.dirs.adapters),
                      "capsules": str(self.dirs.capsules)},
        }

    def activate(self, level: str = "C1") -> dict[str, Any]:
        """Prepare the local plane for the chosen level (C0/C1 in v0.1)."""
        if level not in LEVELS:
            raise ValueError(f"unknown LCE level {level!r} (allowed: {', '.join(LEVELS)})")
        if level not in ("C0", "C1"):
            raise ValueError(
                f"level {level} is not available in this version; "
                f"see its documented status: {LEVELS[level]['note']}")
        self.dirs.ensure()
        (self.dirs.sources / "README.md").write_text(
            "# Swarmbly LCE — sources\n\n"
            "Place your documents here (or add folders in Settings → LCE).\n"
            "Sources are immutable: the app only reads them. Removing a source "
            "from LCE is done with the *forget* action, never by editing files.\n",
            encoding="utf-8")
        policy_path = self.dirs.wiki / "policy.json"
        if not policy_path.exists():
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_text(json.dumps(DEFAULT_POLICY, indent=2),
                                   encoding="utf-8")
        if level == "C1":
            self._init_source_space()
        return self.status(True, level)

    def _init_source_space(self) -> None:
        """Validate the LCE SourceSpace / policy through swarmbly_lce itself."""
        try:
            from swarmbly_lce.sources import SourceSpace
            from swarmbly_lce.policy import LearningPolicy
            space = SourceSpace(root=str(self.dirs.sources))
            policy = LearningPolicy.from_mapping(DEFAULT_POLICY)
            # Probe-only: nothing is digested yet.
            _ = space.files()
            _ = policy.fingerprint("probe")
        except Exception as exc:  # upstream package is a dependency; report honestly
            raise RuntimeError(f"could not initialize LCE C1: {exc}") from exc

    def list_sources(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.dirs.sources.exists():
            return out
        suffixes = {".txt", ".md", ".pdf", ".docx", ".html"}
        for path in sorted(self.dirs.sources.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                out.append({"name": path.name, "path": str(path),
                            "size_bytes": size})
        return out

    # -- C1: retrieval over raw sources (WP LCE v0.2 §11.7–11.8, R13) ---------
    def retrieve(self, query: str, k: int = 4,
                 extra_dirs: list[str] | tuple[str, ...] = (),
                 expansion: str = "") -> list[dict[str, Any]]:
        """Top paragraphs of the user's sources for ``query`` (local only).

        Sources are the LCE source space plus ``lce.sources_dirs``; files are
        read, never written. The index is rebuilt for a file only when its
        content hash changes. ``expansion`` holds extra query terms (P2e: the
        local model's keywords in another language, so a Spanish question
        reaches an English thesis); it is produced and used on this device.
        Each paragraph is indexed with its file name and document title, so
        "mi artículo de 2024 sobre el rascón" reaches that file's paragraphs.
        """
        roots = [self.dirs.sources, *[Path(d).expanduser() for d in extra_dirs or ()]]
        spans = self._spans(roots)
        if not spans or not (query or "").strip():
            return []
        key = tuple(id(s) for s in spans)
        cached = getattr(self, "_index_cache", None)
        if cached is None or cached[0] != key:
            cached = self._index_cache = (key, _BM25([s.get("index") or s["text"] for s in spans]))
        index = cached[1]
        extra = f"{expansion} {self.glossary_terms(f'{query} {expansion}', extra_dirs)}"
        # The user's own words weigh fully; added terms (model keywords,
        # glossary equivalents) weigh half, so they widen without taking over.
        ranked = index.search(query, k * 4, extra=extra, extra_weight=EXTRA_WEIGHT)
        # Paragraphs that only share function words ("de", "es") score far
        # below a real match: keep those within 35 % of the best one.
        top = ranked[0][1] if ranked else 0.0
        hits, seen = [], set()
        per_file: dict[str, int] = {}
        for i, score in ranked:
            if score < RELATIVE_FLOOR * top or len(hits) >= k:
                continue
            if per_file.get(spans[i]["source"], 0) >= MAX_PER_FILE:
                continue          # one long file (a thesis chapter) must not fill every slot
            same = " ".join(_tokens(spans[i]["text"]))[:200]
            if same in seen:          # the same paragraph in two files (ES/EN copies)
                continue
            seen.add(same)
            per_file[spans[i]["source"]] = per_file.get(spans[i]["source"], 0) + 1
            hit = {key: v for key, v in spans[i].items() if key != "index"}
            hit["score"] = round(score, 3)
            hits.append(hit)
        return hits

    # -- personal glossary (P2e) ------------------------------------------------
    def glossary_terms(self, text: str,
                       extra_dirs: list[str] | tuple[str, ...] = ()) -> str:
        """Equivalents from the user's glossary for terms present in ``text``.

        A glossary is any source file named ``glosario*`` / ``glossary*`` with
        lines ``term = equivalent, equivalent`` (also ``→`` or ``->``). It is the
        user's own vocabulary ("cucuve = mockingbird, Mimus"), applied in both
        directions; it bridges languages and local names that a small model does
        not know. Glossary files are not retrieved as passages.
        """
        roots = [self.dirs.sources, *[Path(d).expanduser() for d in extra_dirs or ()]]
        entries = self._glossary(roots)
        if not entries:
            return ""
        have = set(_tokens(text))

        def present(tok: str) -> bool:
            # single long terms also match inflections: "muestrear" ~ "muestrearon"
            if tok in have or (len(tok) >= 6 and any(h.startswith(tok) for h in have)):
                return True
            # Spanish gender: "extinto" ~ "extinta", "público" ~ "pública"
            return len(tok) >= 5 and tok[-1] in "oa" and any(
                len(h) == len(tok) and h[:-1] == tok[:-1] and h[-1] in "oa" for h in have)
        added: list[str] = []
        for side_a, side_b in entries:
            for left, right in ((side_a, side_b), (side_b, side_a)):
                toks = _tokens(left)
                if toks and all(present(t) for t in toks) and right not in added:
                    added.append(right)
        return " ".join(added)

    def glossary_entries(self, extra_dirs: list[str] | tuple[str, ...] = ()
                         ) -> list[tuple[str, str]]:
        roots = [self.dirs.sources, *[Path(d).expanduser() for d in extra_dirs or ()]]
        return self._glossary(roots)

    def _glossary(self, roots: list[Path]) -> list[tuple[str, str]]:
        import hashlib
        cache = getattr(self, "_glossary_cache", None)
        if cache is None:
            cache = self._glossary_cache = {}
        out: list[tuple[str, str]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not (path.is_file() and _is_glossary(path)):
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                key = (str(path), hashlib.sha256(data).hexdigest())
                if key not in cache:
                    pairs = []
                    for line in data.decode("utf-8", "replace").splitlines():
                        m = _GLOSS_LINE.match(line)
                        if m:
                            pairs.append((m.group(1).strip(), m.group(2).strip()))
                    cache[key] = pairs
                out.extend(cache[key])
        return out

    def _spans(self, roots: list[Path]) -> list[dict[str, Any]]:
        import hashlib
        cache = getattr(self, "_span_cache", None)
        if cache is None:
            cache = self._span_cache = {}
        out: list[dict[str, Any]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if (not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES
                        or _is_glossary(path)
                        or path.name == "README.md" and path.parent == self.dirs.sources
                        or any(p.startswith(".") for p in path.relative_to(root).parts)):
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                key = (str(path), hashlib.sha256(data).hexdigest())
                if key not in cache:
                    cache[key] = _paragraphs(path.name, data.decode("utf-8", "replace"),
                                             label=str(path.relative_to(root)))
                out.extend(cache[key])
        return out

    def worker_guard(self, declared_model: str):
        """WorkerGuard (invariant I2) bound to the base model this node
        advertises; it refuses to run if the serving backend differs or carries
        a personal adapter. None only if swarmbly_lce is missing."""
        try:
            from swarmbly_lce.worker import WorkerGuard
            return WorkerGuard(declared_model=declared_model)
        except Exception:
            return None


SOURCE_SUFFIXES = frozenset({".md", ".txt", ".markdown", ".rst", ".org", ".csv"})
SPAN_MAX_CHARS = 600
RELATIVE_FLOOR = 0.35
SHORT_BLOCK_CHARS = 60   # shorter blocks are headings ("NRGene Canada Inc.", "Methods")
EXTRA_WEIGHT = 0.5       # weight of added query terms (model keywords, glossary)
MAX_PER_FILE = 3         # passages per file in one answer (2 cut a needed third, round 4)
_GLOSS_LINE = re.compile(r"^\s*[-*]?\s*([^=→#<>|]{2,80}?)\s*(?:=|→|->)\s*([^=→]{2,200})$")


def _is_glossary(path: Path) -> bool:
    return (path.suffix.lower() in SOURCE_SUFFIXES
            and path.stem.lower().startswith(("glosario", "glossary", "glossaire", "glossário")))


_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def _paragraphs(name: str, text: str, label: str = "") -> list[dict[str, Any]]:
    """Paragraph spans (≤ 600 characters, as SwarmblyLCE's SourceSpace.spans).

    Long paragraphs are cut at sentence ends rather than mid-word. Each span
    carries an ``index`` text: the file's path words and its title (first
    Markdown heading) followed by the paragraph, so a question that names the
    document ("mi tesis", "artículo de 2024 sobre el rascón") finds it.
    """
    title = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                  if ln.startswith("# ")), "")
    header = " ".join(re.split(r"[\W_]+", re.sub(r"\.\w+$", "", label or name)) + [title])
    # "M. melanotis" is indexed as "Mimus melanotis" when the file spells the
    # genus out somewhere, so a question with the full name finds it.
    genus_of = {}
    for g, e in re.findall(r"\b([A-Z][a-z]{3,})\s([a-z]{4,})\b", text):
        genus_of.setdefault((g[0], e), g)

    def unabbreviate(piece: str) -> str:
        return re.sub(r"\b([A-Z])\.\s([a-z]{4,})\b",
                      lambda m: f"{genus_of.get((m.group(1), m.group(2)), m.group(1))} {m.group(2)}",
                      piece)
    out: list[dict[str, Any]] = []
    pos = 0
    heading = ""
    for block in text.split("\n\n"):
        start = text.find(block, pos)
        start = pos if start < 0 else start
        pos = start + len(block)
        body = " ".join(block.split())
        if not body or body.startswith("<!--"):
            continue
        if len(body) < SHORT_BLOCK_CHARS and (not body.endswith((".", "?", "!"))
                                              or len(body.split()) <= 4):
            heading = body.lstrip("#").strip()     # a heading: context for what follows
            continue
        while body:
            if len(body) <= SPAN_MAX_CHARS:
                piece, body = body, ""
            else:
                cuts = [m.start() for m in _SENTENCE_END.finditer(body, 0, SPAN_MAX_CHARS)]
                cut = cuts[-1] if cuts and cuts[-1] > SPAN_MAX_CHARS // 3 else body.rfind(" ", 0, SPAN_MAX_CHARS)
                cut = cut if cut > 0 else SPAN_MAX_CHARS
                piece, body = body[:cut].rstrip(), body[cut:].lstrip()
            full = unabbreviate(piece)
            # The passage shown to the model also spells the genus out: a 3B
            # model read "M. trifasciatus (IUCN: Critical Endangered)" as saying
            # nothing about Mimus trifasciatus (round 4).
            out.append({"source": name, "start": start, "end": pos, "text": full,
                        "index": f"{header} {heading} {full}"})
    return out


# Function words (es/en/pt/fr) carry no topic; folded, as the tokens are.
_STOPWORDS = frozenset("""
a al algo ante antes asi aun cada como con contra cual cuales cuando cuanto cuantos de del desde donde
dos durante e el ella ellas ellos en entre era eran es esa ese eso esta estaba este esto estos fue fueron
ha han hasta hay la las le les lo los mas me mi mis muy ni no nos o os otra otro para pero poco por porque
que quien se segun ser si sin sobre son su sus tambien tan tanto te tiene tienen todo todos tu un una uno
unos y ya yo usted cual
an and are as at be been but by can could did do does for from had has have how i if in into is it its
may more most my no not of on or our she should so such than that the their them then there these they
this those to was we were what when where which while who why will with would you your
um uma os as ao aos da das do dos em na nas no nos pelo pela ou
au aux ce ces dans des du est et il ils je la le les leur mais ne nous ou par pas pour qu que qui sa se ses son sur un une vous
""".split())


def _fold(word: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", word.lower())
                   if not unicodedata.combining(c))


def _stem(word: str) -> str:
    """Light plural folding shared by Spanish and English ("cucuves" → "cucuve")."""
    if len(word) > 4 and word.endswith("es") and word[-3] in "lnrdzj":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[^\W_]+(?:[+-][^\W_]+)*", text):
        f = _fold(w)
        if len(f) > 1 and f not in _STOPWORDS:
            out.append(_stem(f))
    return out


class _BM25:
    """BM25 (k1 1.5, b 0.75), the same scoring as SwarmblyLCE's retriever,
    over folded, stop-word-free, plural-folded tokens."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        import math
        from collections import Counter
        self._tok = _tokens
        self.k1, self.b, self._log = k1, b, math.log
        self.tf = [Counter(self._tok(d)) for d in docs]
        self.df: Counter = Counter()
        for tf in self.tf:
            self.df.update(tf.keys())
        self.avg = sum(sum(tf.values()) for tf in self.tf) / max(1, len(self.tf))

    def search(self, query: str, k: int, extra: str = "",
               extra_weight: float = 0.5) -> list[tuple[int, float]]:
        weights = {t: 1.0 for t in self._tok(query)}
        for t in self._tok(extra):
            weights.setdefault(t, extra_weight)
        n = len(self.tf)
        scored = []
        for i, tf in enumerate(self.tf):
            dl = sum(tf.values()) or 1
            s = 0.0
            for t, w in weights.items():
                if t in tf:
                    idf = self._log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += w * idf * tf[t] * (self.k1 + 1) / (
                        tf[t] + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
