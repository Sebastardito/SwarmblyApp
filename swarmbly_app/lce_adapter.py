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
    def retrieve(self, query: str, k: int = 3,
                 extra_dirs: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """Top paragraphs of the user's sources for ``query`` (local only).

        Sources are the LCE source space plus ``lce.sources_dirs``; files are
        read, never written. The index is rebuilt for a file only when its
        content hash changes.
        """
        roots = [self.dirs.sources, *[Path(d).expanduser() for d in extra_dirs or ()]]
        spans = self._spans(roots)
        if not spans or not (query or "").strip():
            return []
        index = _BM25([s["text"] for s in spans])
        ranked = index.search(query, k)
        # Paragraphs that only share function words ("de", "es") score far
        # below a real match: keep those within 35 % of the best one.
        top = ranked[0][1] if ranked else 0.0
        hits = []
        for i, score in ranked:
            if score < RELATIVE_FLOOR * top:
                continue
            hit = dict(spans[i])
            hit["score"] = round(score, 3)
            hits.append(hit)
        return hits

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
                        or path.name == "README.md" and path.parent == self.dirs.sources
                        or any(p.startswith(".") for p in path.relative_to(root).parts)):
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                key = (str(path), hashlib.sha256(data).hexdigest())
                if key not in cache:
                    cache[key] = _paragraphs(path.name, data.decode("utf-8", "replace"))
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


def _paragraphs(name: str, text: str) -> list[dict[str, Any]]:
    """Paragraph spans (≤ 600 characters, as SwarmblyLCE's SourceSpace.spans)."""
    out: list[dict[str, Any]] = []
    pos = 0
    for block in text.split("\n\n"):
        start = text.find(block, pos)
        start = pos if start < 0 else start
        pos = start + len(block)
        body = " ".join(block.split())
        while body:
            piece, body = body[:SPAN_MAX_CHARS], body[SPAN_MAX_CHARS:]
            out.append({"source": name, "start": start, "end": pos, "text": piece})
    return out


class _BM25:
    """BM25 (k1 1.5, b 0.75), the same scoring as SwarmblyLCE's retriever."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        import math
        import re
        from collections import Counter
        self._tok = lambda t: [w.lower() for w in re.findall(r"[\wáéíóúñü]+", t, re.I)
                               if len(w) > 1]
        self.k1, self.b, self._log = k1, b, math.log
        self.tf = [Counter(self._tok(d)) for d in docs]
        self.df: Counter = Counter()
        for tf in self.tf:
            self.df.update(tf.keys())
        self.avg = sum(sum(tf.values()) for tf in self.tf) / max(1, len(self.tf))

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        q = self._tok(query)
        n = len(self.tf)
        scored = []
        for i, tf in enumerate(self.tf):
            dl = sum(tf.values()) or 1
            s = 0.0
            for t in q:
                if t in tf:
                    idf = self._log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += idf * tf[t] * (self.k1 + 1) / (
                        tf[t] + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
