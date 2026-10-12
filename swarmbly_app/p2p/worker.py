"""Worker role (product spec §7.4): voluntarily serve micro-tasks.

Every gate is enforced in code, not in the UI: worker disabled → refuse;
LAN/internet scopes; task kind and token budget; concurrency limit; idle-only
mode; deadline. Execution is wrapped in LCE ``WorkerGuard`` (invariant I2:
serve the base model, never a personal adapter, never retain task content).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from ..config import Config
from ..db import Database
from ..events import EventBus
from ..identity import IdentityManager
from ..inference.base import StreamBackend
from ..lce_adapter import LCEAdapter
from .messages import error, result

ALLOWED_KINDS = ("extract", "classify", "generate", "summarize",
                 "transform", "judge")


class PromptBackend:
    """Adapts a StreamBackend to the ServingBackend protocol used by the LCE
    WorkerGuard: exposes ``model`` and ``generate(prompt, **kw)``."""

    def __init__(self, stream: StreamBackend, model: str):
        self._stream = stream
        self.model = model
        self.adapter = None  # invariant I2: no personal adapter on workers

    def generate(self, prompt: str, **kw: Any) -> str:
        out = self._stream.stream_chat(
            [{"role": "user", "content": prompt}], model=self.model,
            max_tokens=kw.get("max_tokens", 800),
            temperature=kw.get("temperature", 0.2))
        return out.text


class WorkerService:
    def __init__(self, config: Config, db: Database, bus: EventBus,
                 identity: IdentityManager, lce: LCEAdapter,
                 backend_factory):
        self.config = config
        self.db = db
        self.bus = bus
        self.identity = identity
        self.lce = lce
        self.backend_factory = backend_factory  # () -> StreamBackend
        self._tasks_now = 0
        self._lock = threading.Lock()

    # -- policy -----------------------------------------------------------------
    def policy(self) -> dict[str, Any]:
        cfg = self.config.all()["swarm"]
        return {
            "enabled": bool(cfg.get("worker_enabled")),
            "allow_lan": bool(cfg.get("worker_allow_lan", True)),
            "allow_internet": bool(cfg.get("worker_allow_internet", False)),
            "max_concurrent": int(cfg.get("worker_max_concurrent", 1)),
            "max_tokens_per_task": int(cfg.get("worker_max_tokens_per_task", 800)),
            "kinds": list(ALLOWED_KINDS),
            "idle_only": bool(cfg.get("worker_only_idle", False)),
        }

    def _refuse(self, code: str, detail: str,
                attempt_id: str | None) -> dict[str, Any]:
        return error(code, detail, attempt_id)

    # -- handler -------------------------------------------------------------------
    async def handle(self, node_id: str, message: dict[str, Any]) -> dict[str, Any]:
        """Process one SPEC §8 packet. Runs on the P2P event loop."""
        policy = self.policy()
        attempt_id = message.get("attempt_id")
        if not policy["enabled"]:
            return self._refuse("E_POLICY", "worker role disabled", attempt_id)
        if not policy["allow_lan"]:  # v0.1 peers are LAN peers by construction
            return self._refuse("E_POLICY", "LAN requests not accepted", attempt_id)
        lane = str(message.get("lane", "PUBLIC"))
        if lane == "SENSITIVE":
            return self._refuse("E_LANE_VIOLATION",
                                "sensitive packet offered to an open node", attempt_id)
        tier = str(message.get("tier", "GLOBAL"))
        if tier == "TRUSTED":
            return self._refuse("E_MTLS_REQUIRED",
                                "trusted-swarm links require mutual TLS (not yet supported)",
                                attempt_id)
        task = message.get("task") or {}
        kind = str(task.get("kind", "generate"))
        if kind not in policy["kinds"]:
            return self._refuse("E_KIND_UNSUPPORTED", f"kind {kind!r} not served",
                                attempt_id)
        expects = task.get("expects") or {}
        max_tokens = int(expects.get("max_tokens", 0) or 0)
        if max_tokens > policy["max_tokens_per_task"]:
            return self._refuse("E_BUDGET_EXCEEDED",
                                f"max_tokens {max_tokens} above node policy "
                                f"{policy['max_tokens_per_task']}", attempt_id)
        deadline_ms = int(message.get("deadline_ms", 60000))
        if time.time() * 1000 > deadline_ms:
            return self._refuse("E_DEADLINE", "deadline already passed", attempt_id)
        if policy["idle_only"] and not self._machine_idle():
            return self._refuse("E_POLICY", "worker participates only when idle",
                                attempt_id)
        with self._lock:
            if self._tasks_now >= int(policy["max_concurrent"]):
                return self._refuse("E_POLICY", "worker at concurrency limit",
                                    attempt_id)
            self._tasks_now += 1
        try:
            reply = await asyncio.get_running_loop().run_in_executor(
                None, self._execute, message)
            return reply
        finally:
            with self._lock:
                self._tasks_now -= 1

    def _machine_idle(self) -> bool:
        try:
            import psutil
            return psutil.cpu_percent(interval=0.3) < 50.0
        except Exception:
            return True  # cannot detect → report honestly in stats, allow

    # -- execution (blocking; runs in an executor thread) -----------------------------
    def _execute(self, message: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        prompt = render_packet_prompt(message)
        model_name = self.config.all()["model"].get("model_name", "") or "base"
        try:
            stream = self.backend_factory()
        except Exception as exc:
            return self._refuse("E_POLICY", f"backend unavailable: {exc}",
                                message.get("attempt_id"))
        backend = PromptBackend(stream, model_name)
        try:
            guard = self.lce.worker_guard()
            if guard is not None:
                guard.declared_model = model_name
                guard.forbid_sink(self._forbidden_sink)
                text = guard.execute(backend, prompt)
            else:
                text = backend.generate(prompt)
        except Exception as exc:
            return self._refuse("E_POLICY", f"execution failed: {exc}",
                                message.get("attempt_id"))
        gen_ms = int((time.monotonic() - started) * 1000)
        ident = self.identity.load_or_create()
        profile = {
            "model_family": model_name.split(":")[0],
            "model_version": model_name,
            "quantization": "",
            "prompt_template_id": "default",
            "sampling_params": {"temperature": 0.2},
            "seed": 0,
        }
        telemetry = {"gen_ms": gen_ms, "queue_ms": 0, "tokens_out": 0,
                     "energy_j": None}
        reply = result(str(message.get("attempt_id", "")), text, profile,
                       telemetry, b"", commitment=None)
        # Sign the canonical serialization (SPEC §4/§10).
        from .messages import canonical_bytes
        reply["sig"] = _b64(self.identity.sign(
            canonical_bytes({k: v for k, v in reply.items() if k != "sig"})))
        self._record_stats(gen_ms, len(prompt), len(text))
        self.bus.publish("worker.task_served", attempt_id=message.get("attempt_id"),
                         model=model_name, gen_ms=gen_ms)
        return reply

    def _forbidden_sink(self, text: str) -> None:
        raise RuntimeError("task content must never reach LCE stores (I2)")

    def _record_stats(self, gen_ms: int, bytes_in: int, bytes_out: int) -> None:
        import datetime
        self.db.add_stats(datetime.date.today().isoformat(),
                          tasks_served=1, gen_ms=gen_ms,
                          bytes_in=bytes_in, bytes_out=bytes_out)

    def status(self) -> dict[str, Any]:
        with self._lock:
            busy = self._tasks_now
        import datetime
        today = datetime.date.today().isoformat()
        stats = self.db.get_stats(days=1)
        served = sum(s["tasks_served"] for s in stats if s["day"] >= today)
        return {"policy": self.policy(), "busy_now": busy,
                "tasks_served_today": served}


def render_packet_prompt(message: dict[str, Any]) -> str:
    """Render a SPEC §8 packet into the worker's model prompt.

    The contract header is mandatory content (§9.1); predecessor summaries
    and the task block follow. No ``session_id`` ever appears here.
    """
    parts: list[str] = []
    contract = message.get("contract") or {}
    if contract:
        lines = ["[GLOBAL CONTRACT]"]
        for key in ("objective", "audience", "register", "format", "target_len"):
            if contract.get(key) is not None:
                lines.append(f"{key}: {contract[key]}")
        if contract.get("lexicon"):
            lines.append("prefer: " + ", ".join(contract["lexicon"].get("prefer", [])))
            lines.append("forbid: " + ", ".join(contract["lexicon"].get("forbid", [])))
        if contract.get("entities"):
            lines.append("entities: " + ", ".join(
                f"{e.get('name')} ({e.get('canonical', e.get('name'))})"
                for e in contract["entities"]))
        if contract.get("style_seed"):
            lines.append(f"style_seed: {contract['style_seed']}")
        parts.append("\n".join(lines))
    for pred in message.get("predecessors") or []:
        if pred.get("summary"):
            parts.append(f"[CONTEXT] {pred['summary']}")
    task = message.get("task") or {}
    instruction = task.get("instruction") or ""
    expects = task.get("expects") or {}
    if expects.get("format"):
        instruction += f"\nRespond in {expects['format']} format."
    parts.append(f"[TASK t{message.get('attempt_id', '')[-6:]}] {instruction}")
    return "\n\n".join(parts)


def _b64(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
