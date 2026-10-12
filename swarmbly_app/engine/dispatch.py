"""Distributed execution engine (Phase 2): SPEC wire packets over the P2P LAN.

Reuses the SwarmblyAI pipeline (privacy → router → contract → plan → packing →
assembly → metrics) and adds what that repository does not contain: real
dispatch. Each micro-task becomes a SPEC §8 packet sent to an authenticated
LAN worker; results are SPEC §10 messages whose Ed25519 signature is verified
before the text enters assembly. Verification (Layer-1 commitments) and the
consensus confidence map are reported exactly as available — never simulated.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..events import EventBus
from ..p2p.messages import (WIRE_VERSION, new_session_id, task_id_for,
                            attempt_id_for, packet as wire_packet,
                            verify_signed)
from ..p2p.node import NodeManager

MAX_IN_FLIGHT = 4


class NoWorkers(RuntimeError):
    pass


class DistributedBackend:
    """Implements swarmbly_v0's ``Backend`` protocol over connected workers.

    ``generate(prompt)`` receives the packed prompt (SwarmblyAI packing
    output, plain text with its own markers) and dispatches it inside a
    conformant SPEC §8 packet. ``family_pool``/``for_replica`` let the
    upstream ``replica_backends`` helper pick family-diverse workers for k>1.
    """

    name = "swarm_lan"

    def __init__(self, nodes: NodeManager, bus: EventBus,
                 contract: dict[str, Any], *, session_id: bytes | None = None,
                 bound_node: str | None = None, lane: str = "PUBLIC",
                 tier: str = "GLOBAL", deadline_ms: int = 60000,
                 timeout_s: float = 120.0, max_tokens: int = 420):
        self.nodes = nodes
        self.bus = bus
        self.contract = contract
        self.session_id = session_id or new_session_id()
        self.bound_node = bound_node
        self.lane = lane
        self.tier = tier
        self.deadline_ms = deadline_ms
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self._counter = 0
        self._counter_lock = threading.Lock()

    # -- family diversity hooks (used by swarmbly_v0.replica_backends) ----------
    @property
    def family_pool(self) -> list[tuple[str, str]]:
        """(family, node_id) per connected worker with a declared model."""
        out = []
        for peer in self.nodes.available_workers():
            for model in peer.advertisement.get("models", []):
                family = model.get("family") or model.get("version") or "unknown"
                out.append((family, peer.node_id))
        return out

    def for_replica(self, family: str, model: str) -> "DistributedBackend":
        """Bind this backend to one worker (``model`` carries the node_id)."""
        return DistributedBackend(
            self.nodes, self.bus, self.contract,
            session_id=self.session_id, bound_node=model,
            lane=self.lane, tier=self.tier, deadline_ms=self.deadline_ms,
            timeout_s=self.timeout_s, max_tokens=self.max_tokens)

    # -- the Backend protocol ---------------------------------------------------
    def generate(self, prompt: str, **kw: Any) -> str:
        with self._counter_lock:
            self._counter += 1
            index = self._counter
        task_id = task_id_for(self.session_id, 0, index)
        attempt_id = attempt_id_for(task_id, 0)
        node_id = self._select_node()
        if node_id is None:
            raise NoWorkers("no connected workers available")
        # Respect the selected node's declared policy (SPEC §12: a node MUST
        # NOT accept a task above policy.max_tokens_per_task).
        max_tokens = self._clamp_tokens(node_id, self.max_tokens)
        message = wire_packet(
            attempt_id=attempt_id,
            contract=self.contract,
            predecessors=[],
            task={"instruction": prompt, "kind": "generate",
                  "expects": {"format": "prose",
                              "max_tokens": max_tokens}},
            deadline_ms=int(time.time() * 1000) + int(self.deadline_ms),
            lane=self.lane, tier=self.tier,
            commitment_request=None,  # no normative scheme yet (SPEC §21.1)
        )
        self.bus.publish("request.stage", stage="DISPATCHING", attempt_id=attempt_id,
                         node_id=node_id[:12], status="running")
        started = time.monotonic()
        try:
            result = self.nodes.dispatch(node_id, message, self.timeout_s)
        except Exception as exc:
            self.bus.publish("request.stage", stage="DISPATCHING",
                             attempt_id=attempt_id, status="failed",
                             detail=str(exc)[:140])
            raise RuntimeError(f"worker {node_id[:12]} failed: {exc}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # SPEC §10: results MUST be signed. Verify before the text enters assembly.
        if not verify_signed(node_id, result):
            self.bus.publish("request.stage", stage="VERIFICATION",
                             attempt_id=attempt_id, status="failed",
                             detail="result signature invalid")
            raise RuntimeError("result signature verification failed")
        self.bus.publish("request.stage", stage="RESULT RECEPTION",
                         attempt_id=attempt_id, node_id=node_id[:12],
                         status="completed", elapsed_ms=elapsed_ms)
        return str(result.get("text", ""))

    def _select_node(self) -> str | None:
        if self.bound_node:
            return self.bound_node
        workers = self.nodes.available_workers()
        if not workers:
            return None
        # Least recently used heuristic: round-robin on the registry order.
        return workers[0].node_id

    def _clamp_tokens(self, node_id: str, requested: int) -> int:
        """Clamp the output budget to the peer's declared policy (SPEC §12)."""
        peer = self.nodes.peers.get(node_id)
        limit = None
        if peer is not None:
            limit = (peer.advertisement.get("policy") or {}).get(
                "max_tokens_per_task")
        try:
            limit = int(limit) if limit else None
        except (TypeError, ValueError):
            limit = None
        return min(requested, limit) if limit else requested

    def embed(self, texts: list[str]):
        """Embedding is local-only; the engine injects its own embedder."""
        raise NotImplementedError("use the engine's local embedder")


def stage_event(bus: EventBus, stage: str, status: str, **detail: Any) -> None:
    bus.publish("request.stage", stage=stage, status=status, **detail)
