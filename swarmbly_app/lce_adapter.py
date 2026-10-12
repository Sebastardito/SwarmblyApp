"""LCE adapter — C0 active, C1 prepared (v0.1 scope).

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
    "C1": {"active": False, "status": "prepared",
           "note": "Source space + conservative policy ready; answering retrieval "
                  "(raw sources) arrives with the full LCE integration phase."},
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

    def worker_guard(self):
        """WorkerGuard (invariant I2) for the worker role; None without LCE."""
        try:
            from swarmbly_lce.worker import WorkerGuard
            return WorkerGuard(declared_model="base")
        except Exception:
            return None
