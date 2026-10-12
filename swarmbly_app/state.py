"""Application state: wires every module together (composition root).

Phase 2 adds the P2P node manager, the worker service and the distributed
orchestrator. The P2P listener starts with the app (independent access
limits); discovery and the worker role follow the configuration.
"""

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
from .p2p.node import NodeManager
from .p2p.worker import WorkerService


def _build_advertisement(state: "AppState") -> dict:
    """SPEC §12 node profile from live state (models, resources, policy)."""
    import psutil
    cfg = state.config.all()
    model_cfg = cfg["model"]
    model_name = model_cfg.get("model_name", "")
    models = []
    if model_name:
        models.append({"family": model_name.split(":")[0],
                       "version": model_name,
                       "quantization": "",
                       "ctx": 8192, "tok_per_s_est": None})
    worker_policy = state.worker.policy() if state.worker else {}
    vm = psutil.virtual_memory()
    return {
        "node_id": state.identity.node_id,
        "models": models,
        "capabilities": {"tee": False, "attestation": None},
        "swarm": None,
        "resources": {"vram_mb": None, "ram_mb": int(vm.total // (1024 ** 2))},
        "policy": {"max_tokens_per_task":
                   int(cfg["swarm"].get("worker_max_tokens_per_task", 800)),
                   "kinds": list(worker_policy.get("kinds", []))},
        "reputation": None,  # self-reported reputation is never trusted (SPEC §12)
    }


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
        self.lce = LCEAdapter(self.dirs)
        self.nodes = NodeManager(self.identity_manager, self.config, self.db,
                                 self.bus, lambda: _build_advertisement(self),
                                 dirs=self.dirs)
        self.worker: WorkerService | None = None
        self.orchestrator = None  # built lazily with a live local backend
        self.chat = ChatService(self.db, self.bus, self.backends,
                                self.config.all, self.get_orchestrator)

    # -- P2P lifecycle -----------------------------------------------------------
    def start_p2p(self) -> None:
        if self.worker is None:
            self.worker = WorkerService(
                self.config, self.db, self.bus, self.identity_manager,
                self.lce, lambda: self.backends.resolve(self.config.all()))
            self.nodes.start(task_handler=self.worker.handle)

    def stop(self) -> None:
        self.nodes.stop()
        self.db.close()

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

    def get_orchestrator(self):
        from .engine.orchestrator import Orchestrator
        if self.orchestrator is None:
            model_name = self.config.all()["model"].get("model_name", "")
            self.orchestrator = Orchestrator(
                self.nodes, self.bus,
                self.backends.resolve(self.config.all()),
                self.config.all, local_model=model_name)
        return self.orchestrator
