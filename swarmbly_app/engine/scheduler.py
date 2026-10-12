"""Asynchronous micro-task scheduler (SPEC §7, §11, §13).

Runs on the P2P event loop. Responsibilities:

- **Parallel dispatch.** Every task whose *consumed* predecessors are done is
  dispatched at once (bounded by ``max_concurrency``). Edges a task does not
  consume are ``statement`` edges and do not delay it (SPEC §7).
- **Family diversity.** Replicas of one task go to distinct (node, family)
  pairs, preferring families not yet used for that task, then the least
  loaded node (SPEC §11.2 MUST).
- **Redundancy bounds.** ``k_min`` replicas are dispatched up front (the
  epistemic redundancy that feeds the divergence map); hedges and retries add
  attempts up to the ceiling ``k_max`` (availability). This is the
  ``k_epist`` / ``k_avail`` split of whitepaper v2 §12.4.
- **Hedging.** The hedge timer is the observed p95 for (kind, budget) once
  enough samples exist (SPEC §11.3); until then a declared fallback is used
  and reported as such.
- **Verification before acceptance.** A result enters assembly only after its
  Ed25519 signature, attempt id and schema check pass (SPEC §10, §13). Layer-1
  commitments are not available and never simulated.
- **Cancellation semantics.** Replicas cancelled after acceptance are recorded
  as *slow*, never as *dishonest* (SPEC §11.4).
"""

from __future__ import annotations

import asyncio
import collections
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..events import EventBus
from ..p2p.messages import verify_signed

MAX_RESULT_CHARS = 64_000
MIN_SAMPLES_FOR_P95 = 8


class LatencyStats:
    """Per (kind, budget-bucket) latency history for the p95 hedge timer."""

    def __init__(self, maxlen: int = 200):
        self._data: dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=maxlen))

    @staticmethod
    def key(kind: str, max_tokens: int) -> str:
        bucket = 128
        while bucket < max_tokens:
            bucket *= 2
        return f"{kind}:{bucket}"

    def add(self, key: str, seconds: float) -> None:
        self._data[key].append(float(seconds))

    def p95(self, key: str) -> float | None:
        values = sorted(self._data.get(key, ()))
        if len(values) < MIN_SAMPLES_FOR_P95:
            return None
        return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]

    def samples(self, key: str) -> int:
        return len(self._data.get(key, ()))


@dataclass
class Attempt:
    task_id: str
    number: int
    node_id: str
    family: str
    reason: str                       # initial | hedge | retry
    status: str = "dispatched"        # dispatched|accepted|extra|failed|cancelled_slow
    code: str = ""
    elapsed_ms: int | None = None
    tokens_out: int | None = None
    bytes_out: int = 0
    bytes_in: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"task": self.task_id, "attempt": self.number,
                "node": self.node_id[:12], "family": self.family,
                "model": self.model, "reason": self.reason,
                "status": self.status, "code": self.code,
                "elapsed_ms": self.elapsed_ms, "tokens_out": self.tokens_out,
                "bytes_out": self.bytes_out, "bytes_in": self.bytes_in}


@dataclass
class Replica:
    text: str
    node_id: str
    family: str
    model: str
    elapsed_ms: int
    telemetry: dict[str, Any] = field(default_factory=dict)


class TaskFailed(RuntimeError):
    pass


class Scheduler:
    def __init__(self, nodes, bus: EventBus, request_id: str, *,
                 k_min: int, k_max: int, max_concurrency: int,
                 timeout_s: float, hedge_fallback_s: float,
                 latency: LatencyStats, kind: str = "generate"):
        self.nodes = nodes
        self.bus = bus
        self.request_id = request_id
        self.k_min = max(1, int(k_min))
        self.k_max = max(self.k_min, int(k_max))
        self.timeout_s = float(timeout_s)
        self.hedge_fallback_s = float(hedge_fallback_s)
        self.latency = latency
        self.kind = kind
        self._sem = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._slots: dict[str, asyncio.Semaphore] = {}
        self.attempts: list[Attempt] = []
        self.hedges = 0
        self.retries = 0
        self.timeouts = 0
        self.hedge_timer_source: set[str] = set()
        self._load: collections.Counter = collections.Counter()
        self._pair_load: collections.Counter = collections.Counter()  # (node, family)
        self._pair_used: collections.Counter = collections.Counter()  # spread over time

    # -- worker selection -------------------------------------------------------
    def _candidates(self) -> list[tuple[Any, str, str]]:
        """(peer, family, model) for every model each connected worker serves."""
        out = []
        for peer in self.nodes.available_workers(self.kind):
            models = peer.advertisement.get("models") or [{"family": "unknown"}]
            for model in models:
                out.append((peer, str(model.get("family") or "unknown"),
                            str(model.get("version") or "")))
        return out

    def _select(self, used_pairs: set[tuple[str, str]], used_families: set[str],
                used_nodes: set[str]):
        best = None
        best_key = None
        for peer, family, model in self._candidates():
            if (peer.node_id, family) in used_pairs:
                continue
            key = (family in used_families,           # diversity first (MUST)
                   peer.node_id in used_nodes,         # then distinct machines
                   self._load[peer.node_id] + peer.tasks_inflight,
                   self._pair_load[(peer.node_id, family)],
                   self._pair_used[(peer.node_id, family)],  # spread across models
                   peer.rtt_ms if peer.rtt_ms is not None else 1e9,
                   peer.node_id, family)
            if best_key is None or key < best_key:
                best, best_key = (peer, family, model), key
        return best

    # -- one task ---------------------------------------------------------------
    async def run_task(self, task_id: str, build: Callable[[int, str | None], dict],
                       max_tokens: int) -> list[Replica]:
        """Dispatch replicas of one task; return ≥1 verified replica or raise."""
        used_pairs: set[tuple[str, str]] = set()
        used_families: set[str] = set()
        used_nodes: set[str] = set()
        accepted: list[Replica] = []
        inflight: dict[asyncio.Task, Attempt] = {}
        number = 0
        latency_key = LatencyStats.key(self.kind, max_tokens)

        def launch(reason: str) -> bool:
            nonlocal number
            if number >= self.k_max:
                return False
            choice = self._select(used_pairs, used_families, used_nodes)
            if choice is None:
                return False
            peer, family, model = choice
            used_pairs.add((peer.node_id, family))
            used_families.add(family)
            used_nodes.add(peer.node_id)
            multi = len(peer.advertisement.get("models") or []) > 1
            message = build(number, family if multi else None)
            attempt = Attempt(task_id, number, peer.node_id, family, reason,
                              model=model,
                              bytes_out=len(str(message)))
            number += 1
            self.attempts.append(attempt)
            self._load[peer.node_id] += 1
            self._pair_load[(peer.node_id, family)] += 1
            self._pair_used[(peer.node_id, family)] += 1
            task = asyncio.ensure_future(self._dispatch_one(peer.node_id, message,
                                                            attempt))
            inflight[task] = attempt
            self._event(attempt, "dispatched")
            return True

        for _ in range(self.k_min):
            if not launch("initial"):
                break
        if not inflight:
            raise TaskFailed(f"{task_id}: no connected worker available")

        while inflight and len(accepted) < self.k_min:
            p95 = self.latency.p95(latency_key)
            self.hedge_timer_source.add("p95" if p95 is not None else "fallback")
            hedge_after = p95 if p95 is not None else self.hedge_fallback_s
            can_hedge = number < self.k_max
            done, _ = await asyncio.wait(
                set(inflight), timeout=hedge_after if can_hedge else None,
                return_when=asyncio.FIRST_COMPLETED)
            if not done:
                if launch("hedge"):
                    self.hedges += 1
                continue
            for finished in done:
                attempt = inflight.pop(finished)
                self._load[attempt.node_id] -= 1
                self._pair_load[(attempt.node_id, attempt.family)] -= 1
                replica = finished.result()
                if replica is not None:
                    attempt.status = "accepted"
                    accepted.append(replica)
                    self.latency.add(latency_key, replica.elapsed_ms / 1000.0)
                    self._event(attempt, "accepted")
                else:
                    self._event(attempt, "failed")
                    if len(accepted) + len(inflight) < self.k_min and launch("retry"):
                        self.retries += 1

        for task, attempt in inflight.items():
            task.cancel()
            self._load[attempt.node_id] -= 1
            self._pair_load[(attempt.node_id, attempt.family)] -= 1
            attempt.status = "cancelled_slow"   # slow, not dishonest (SPEC §11.4)
            self._event(attempt, "cancelled_slow")
        if not accepted:
            codes = ", ".join(sorted({a.code for a in self.attempts
                                      if a.task_id == task_id and a.code}))
            raise TaskFailed(f"{task_id}: all {number} attempt(s) failed ({codes})")
        return accepted

    def _slot(self, node_id: str) -> asyncio.Semaphore:
        """Respect each worker's advertised capacity: queue here rather than
        send a task the worker would refuse as over its limit."""
        if node_id not in self._slots:
            peer = self.nodes.peers.get(node_id)
            try:
                cap = int(((peer.advertisement if peer else {}).get("policy") or {})
                          .get("max_concurrent") or 1)
            except (TypeError, ValueError):
                cap = 1
            self._slots[node_id] = asyncio.Semaphore(max(1, cap))
        return self._slots[node_id]

    async def _dispatch_one(self, node_id: str, message: dict[str, Any],
                            attempt: Attempt) -> Replica | None:
        started = time.monotonic()
        async with self._slot(node_id), self._sem:
            try:
                result = await self.nodes.dispatch_async(node_id, message,
                                                         self.timeout_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt.status = "failed"
                attempt.code = getattr(exc, "code", "") or "E_TRANSPORT"
                if attempt.code == "E_DEADLINE":
                    self.timeouts += 1
                attempt.elapsed_ms = int((time.monotonic() - started) * 1000)
                return None
        attempt.elapsed_ms = int((time.monotonic() - started) * 1000)
        attempt.bytes_in = len(str(result))
        problem = verify_result(node_id, message, result)
        if problem:
            attempt.status = "failed"
            attempt.code = problem
            return None
        profile = result.get("profile") or {}
        telemetry = result.get("telemetry") or {}
        attempt.tokens_out = telemetry.get("tokens_out")
        attempt.model = str(profile.get("model_version") or attempt.model)
        family = str(profile.get("model_family") or attempt.family)
        return Replica(text=str(result["text"]), node_id=node_id, family=family,
                       model=attempt.model, elapsed_ms=attempt.elapsed_ms,
                       telemetry=telemetry)

    def _event(self, attempt: Attempt, status: str) -> None:
        self.bus.publish("swarm.attempt", request_id=self.request_id,
                         **attempt.to_dict(), event=status)


def verify_result(node_id: str, packet: dict[str, Any], result: dict[str, Any]) -> str:
    """Return an error code if the result must not enter assembly, else ''."""
    if result.get("type") != "result":
        return "E_SCHEMA"
    if result.get("attempt_id") != packet.get("attempt_id"):
        return "E_SCHEMA"
    if not verify_signed(node_id, result):
        return "E_VERIFY_FAILED"
    text = result.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_RESULT_CHARS:
        return "E_SCHEMA"
    return ""


async def run_levels(scheduler: Scheduler, order: list[str],
                     consumed_deps: dict[str, tuple[str, ...]],
                     run_one: Callable[[str], Awaitable[Any]]) -> dict[str, Any]:
    """Run tasks as soon as their consumed predecessors are done."""
    results: dict[str, Any] = {}
    remaining = list(order)
    running: dict[asyncio.Task, str] = {}
    try:
        while remaining or running:
            ready = [t for t in remaining
                     if all(d in results for d in consumed_deps.get(t, ()))]
            for task_id in ready:
                remaining.remove(task_id)
                running[asyncio.ensure_future(run_one(task_id))] = task_id
            if not running:
                raise TaskFailed("plan has unsatisfiable dependencies")
            done, _ = await asyncio.wait(set(running),
                                         return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                task_id = running.pop(finished)
                results[task_id] = finished.result()   # re-raises TaskFailed
    finally:
        for task in running:
            task.cancel()
    return results
