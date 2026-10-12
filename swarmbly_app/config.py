"""Persistent configuration (JSON in the data directory).

Defaults prioritize safety and stability: LOCAL tier, LAN and internet off,
no worker participation, LCE C0, nothing trains. The three general profiles
(Automatic / Custom / Advanced) select presets; every value stays user-editable
and reversible.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from .paths import DataDirs

DEFAULTS: dict[str, Any] = {
    "language": "en",                 # en | es (UI default language)
    "theme": "dark",
    "data_dir": None,                 # None -> platform default
    "output_dir": None,               # None -> <data_dir>/output
    "autostart": False,
    "log_retention_days": 30,
    "reduce_motion": False,
    "setup_completed": False,
    "api": {
        "host": "127.0.0.1",           # local-only admin interface
        "port": 8765,
    },
    "model": {
        "backend": "auto",            # auto | ollama | openai_compat
        "backend_url": "",            # e.g. http://127.0.0.1:11434 (ollama) or .../v1
        "api_key": "",                # only for OpenAI-compatible servers that need it
        "model_name": "",             # empty -> auto pick
        "max_tokens": 1024,
        "temperature": 0.2,
        "embedder": "hash",           # hash | server | sentence_transformers
    },
    "swarm": {
        "mode": "local",              # local | lan | internet | auto
        "lan_enabled": False,
        "internet_enabled": False,
        "discovery_enabled": True,
        "worker_enabled": False,
        "worker_allow_lan": True,
        "worker_allow_internet": False,
        "worker_max_concurrent": 1,
        "worker_only_idle": False,
        "worker_max_tokens_per_task": 800,
        "max_concurrency": 2,         # simultaneous tasks admitted
        "k_min": 1,                   # redundancy floor (explicit)
        "k_max": 2,                   # redundancy ceiling (explicit)
        "n_fragments_max": 4,
        "rho_target": 1.5,
        "timeout_ms": 60000,
        "max_retries": 1,
        "rendezvous": [],             # rendezvous endpoints (Phase 3)
    },
    "privacy": {
        "tier": "LOCAL",              # GLOBAL | TRUSTED | LOCAL
        "manual_tier": None,          # authoritative manual override, never downgraded
        "trusted_nodes": [],          # node_id whitelist for TRUSTED
        "trusted_networks": [],       # CIDR list (informational; LAN != trust)
    },
    "lce": {
        "enabled": False,
        "level": "C0",                # C0..C4; v0.1 ships C0, prepares C1
        "sources_dirs": [],           # extra source folders
        "learning_enabled": False,    # I8: nothing trains without permission
        "capsules_enabled": False,
    },
    "results": {
        "export_dir": None,
        "export_format": "markdown",  # markdown | json | html
        "keep_stats": True,
        "report_detail": "standard",  # minimal | standard | full
    },
    "profile": "automatic",           # automatic | custom | advanced
}

_SENTINEL = object()


def _deep_merge(base: dict, update: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    """Thread-safe JSON config with defaults and deep-merge updates."""

    def __init__(self, dirs: DataDirs):
        self._dirs = dirs
        self._lock = threading.Lock()
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        path = self._dirs.config_path()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                with self._lock:
                    self._data = _deep_merge(DEFAULTS, raw)
            except (json.JSONDecodeError, OSError) as exc:  # corrupt file -> defaults
                path.rename(path.with_suffix(".json.bak"))
                self.save()
                with self._lock:
                    self._data = copy.deepcopy(DEFAULTS)
                self._last_error = str(exc)

    def save(self) -> None:
        self._dirs.ensure()
        with self._lock:
            payload = json.dumps(self._data, indent=2, ensure_ascii=False)
            self._dirs.config_path().write_text(payload, encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, changes: dict[str, Any], save: bool = True) -> dict[str, Any]:
        """Deep-merge ``changes`` (dot keys or nested dicts) and persist."""
        nested: dict[str, Any] = {}
        for key, value in changes.items():
            if "." in key:
                top, _, rest = key.partition(".")
                nested.setdefault(top, {})[rest] = value
            else:
                nested[key] = value
        with self._lock:
            self._data = _deep_merge(self._data, nested)
            merged = copy.deepcopy(self._data)
        if save:
            self.save()
        return merged

    def reset(self, section: str | None = None) -> None:
        with self._lock:
            if section is None:
                self._data = copy.deepcopy(DEFAULTS)
            elif section in DEFAULTS and isinstance(DEFAULTS[section], dict):
                self._data[section] = copy.deepcopy(DEFAULTS[section])
        self.save()
