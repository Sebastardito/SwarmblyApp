"""Application state: wires every module together (composition root)."""

from __future__ import annotations

import time

from .chat import ChatService
from .config import Config
from .db import Database
from .events import EventBus
from .identity import IdentityManager, NodeIdentity
from .inference.registry import BackendRegistry
from .lce_adapter import LCEAdapter
from .models import ModelManager
from .paths import DataDirs


class AppState:
    """One instance per process; built once at startup."""

    def __init__(self, data_dir: str | None = None):
        self.started_at = time.time()
        # 1. Boot dirs (CLI/env) → 2. config may override data_dir → 3. effective dirs
        boot_dirs = DataDirs(data_dir)
        self.config = Config(boot_dirs)
        configured = self.config.get("data_dir")
        self.dirs = DataDirs(configured) if configured else boot_dirs
        self.dirs.ensure()
        if str(self.dirs.root) != str(boot_dirs.root):
            self.config = Config(self.dirs)  # re-read from the effective location
        self.db = Database(self.dirs.db_path())
        self.bus = EventBus()
        self.identity_manager = IdentityManager(self.dirs.identity_key_path())
        self.identity: NodeIdentity = self.identity_manager.load_or_create()
        self.model_manager = ModelManager()
        self.backends = BackendRegistry()
        self.chat = ChatService(self.db, self.bus, self.backends,
                                self.config.all)
        self.lce = LCEAdapter(self.dirs)

    # -- one-shot helpers ------------------------------------------------------
    def system_report(self) -> dict:
        from . import hardware
        return hardware.detect_all(str(self.dirs.root))

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": __import__("swarmbly_app").__version__,
            "protocol_spec": __import__("swarmbly_app").PROTOCOL_SPEC_VERSION,
            "lce_spec": __import__("swarmbly_app").LCE_SPEC_VERSION,
            "node_id": self.identity.short_id(12),
            "uptime_s": int(time.time() - self.started_at),
            "data_dir": str(self.dirs.root),
        }

    def close(self) -> None:
        self.db.close()
