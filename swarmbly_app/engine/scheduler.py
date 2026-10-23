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


class SpeedStats:
    """Observed generation speed per (node, model), shared across requests.

    On the heterogeneous network a node's largest model is not always the
    best choice: llama3.1:8b on the CPU of a 512 GB server needed more than
    60 s for one section and timed out (P3b.3'', 22 Oct 2026) while a
    3.8 B model on another node took 20–36 s. Speed is learned from accepted
    results (tokens / generation time); a timeout records an upper bound.
    """

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self._tps: dict[tuple[str, str], float] = {}

    def observe(self, node_id: str, model: str, tokens: Any, gen_ms: Any) -> None:
        try:
            tokens, gen_ms = float(tokens), float(gen_ms)
        except (TypeError, ValueError):
            return
        if tokens <= 0 or gen_ms <= 0:
            return
        self._update((node_id, model), tokens / (gen_ms / 1000.0))

    def observe_timeout(self, node_id: str, model: str, max_tokens: int,
                        timeout_s: float) -> None:
        """It could not produce ``max_tokens`` in ``timeout_s``: at most that rate."""
        if timeout_s > 0 and max_tokens > 0:
            bound = max_tokens / timeout_s
            key = (node_id, model)
            self._tps[key] = min(self._tps.get(key, bound), bound)

    def _update(self, key: tuple[str, str], value: float) -> None:
        old = self._tps.get(key)
        self._tps[key] = value if old is None else (1 - self.alpha) * old + self.alpha * value

    def tokens_per_s(self, node_id: str, model: str) -> float | None:
        return self._tps.get((node_id, model))

    def estimate_s(self, node_id: str, model: str, max_tokens: int) -> float | None:
        tps = self.tokens_per_s(node_id, model)
        return None if not tps else max_tokens / tps


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


CANCEL_GRACE_S = 2.0   # seconds a worker keeps its slot after a timeout/cancel


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
    note: str = ""                    # e.g. the start of a rejected replica

    def to_dict(self) -> dict[str, Any]:
        out = self._base()
        if self.note:
            out["note"] = self.note
        return out

    def _base(self) -> dict[str, Any]:
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
                 latency: LatencyStats, kind: str = "generate",
                 min_params_b: float = 0.0, queue_retries: bool = True,
                 speed: SpeedStats | None = None):
        self.nodes = nodes
        # Models below this size are not used (tags without a size always are).
        self.min_params_b = float(min_params_b)
        self.rejected = 0
        # False when the requester has its own model: a retry that would wait
        # behind busy workers fails fast instead, and the task runs locally
        # (P3b.3': queued retries waited 50 s and then timed out anyway).
        self.queue_retries = bool(queue_retries)
        self.speed = speed or SpeedStats()
        self._max_tokens = 0          # budget of the task being dispatched
        # After a timeout or a cancelled hedge the worker may still be
        # finishing (older workers ignore "cancel"): keep its slot for a
        # short grace period instead of sending it work it would refuse.
        self._busy_until: dict[str, float] = {}
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
        """(peer, family, model): per worker and family, its largest eligible model.

        Capability (parameter count from the tag) decides *which* model of a
        family a node runs; models below ``min_params_b`` are skipped. If that
        filter would leave no candidate at all, every model is allowed again
        (a small swarm must still answer).
        """
        from .capability import eligible, rank_params

        def collect(min_b: float) -> list[tuple[Any, str, str]]:
            out = []
            for peer in self.nodes.available_workers(self.kind):
                best: dict[str, str] = {}
                for model in (peer.advertisement.get("models") or [{"family": "unknown"}]):
                    family = str(model.get("family") or "unknown")
                    version = str(model.get("version") or "")
                    if version and not eligible(version, min_b):
                        continue
                    if family not in best or rank_params(version) > rank_params(best[family]):
                        best[family] = version
                out.extend((peer, family, version) for family, version in best.items())
            return out

        return collect(self.min_params_b) or collect(0.0)

    def _capacity(self, peer) -> int:
        try:
            return max(1, int((peer.advertisement.get("policy") or {})
                              .get("max_concurrent") or 1))
        except (TypeError, ValueError):
            return 1

    def _select(self, used_pairs: set[tuple[str, str]], used_families: set[str],
                used_nodes: set[str], free_only: bool = False,
                max_tokens: int | None = None):
        """Best (peer, family, model). ``free_only``: only workers with a free
        slot — a hedge queued behind a busy worker adds load and saves no
        time (P3b.3, 22 Oct 2026: after the server left, hedges queued on the
        two remaining single-slot workers and every task missed its deadline)."""
        best = None
        best_key = None
        for peer, family, model in self._candidates():
            if (peer.node_id, family) in used_pairs:
                continue
            if free_only and self._load[peer.node_id] >= self._capacity(peer):
                continue
            from .capability import rank_params
            estimate = self.speed.estimate_s(
                peer.node_id, model, max_tokens if max_tokens is not None else self._max_tokens)
            too_slow = estimate is not None and estimate > 0.9 * self.timeout_s
            key = (family in used_families,           # diversity first (MUST)
                   peer.node_id in used_nodes,         # then distinct machines
                   self._load[peer.node_id] + peer.tasks_inflight,
                   too_slow,                           # then: can it finish in time?
                   -rank_params(model),                # then the most capable model
                   self._pair_load[(peer.node_id, family)],
                   self._pair_used[(peer.node_id, family)],  # spread across models
                   peer.rtt_ms if peer.rtt_ms is not None else 1e9,
                   peer.node_id, family)
            if best_key is None or key < best_key:
                best, best_key = (peer, family, model), key
        return best

    # -- one task ---------------------------------------------------------------
    async def run_task(self, task_id: str, build: Callable[..., dict],
                       max_tokens: int,
                       validate: Callable[[str], bool] | None = None) -> list[Replica]:
        """Dispatch replicas of one task; return ≥1 verified replica or raise.

        ``validate`` rejects a signed, well-formed replica whose content is
        unusable (e.g. a batch answered by echoing its items): the attempt is
        recorded as ``rejected`` (``E_QUALITY``) and another node is tried,
        within ``k_max``. If every replica is rejected, the rejected ones are
        returned rather than failing the request (the monitor shows it).
        """
        rejected: list[tuple[Replica, Attempt]] = []
        used_pairs: set[tuple[str, str]] = set()
        used_families: set[str] = set()
        used_nodes: set[str] = set()
        accepted: list[Replica] = []
        inflight: dict[asyncio.Task, Attempt] = {}
        number = 0
        latency_key = LatencyStats.key(self.kind, max_tokens)
        self._max_tokens = int(max_tokens)

        def launch(reason: str, free_only: bool = False) -> bool:
            nonlocal number
            if number >= self.k_max:
                return False
            choice = self._select(used_pairs, used_families, used_nodes,
                                  free_only=free_only or reason == "hedge",
                                  max_tokens=max_tokens)
            if choice is None:
                return False
            peer, family, model = choice
            used_pairs.add((peer.node_id, family))
            used_families.add(family)
            used_nodes.add(peer.node_id)
            multi = len(peer.advertisement.get("models") or []) > 1
            message = build(number, family if multi else None, model if multi else None)
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
                if replica is not None and validate is not None:
                    try:
                        usable = bool(validate(replica.text))
                    except Exception:
                        usable = True
                    if not usable:
                        attempt.status, attempt.code = "rejected", "E_QUALITY"
                        attempt.note = " ".join(replica.text.split())[:160]
                        self.rejected += 1
                        rejected.append((replica, attempt))
                        self._event(attempt, "rejected")
                        if len(accepted) + len(inflight) < self.k_min and launch("retry", free_only=not self.queue_retries):
                            self.retries += 1
                        continue
                if replica is not None:
                    attempt.status = "accepted"
                    accepted.append(replica)
                    self.latency.add(latency_key, replica.elapsed_ms / 1000.0)
                    self._event(attempt, "accepted")
                else:
                    self._event(attempt, "failed")
                    if len(accepted) + len(inflight) < self.k_min and launch("retry", free_only=not self.queue_retries):
                        self.retries += 1

        for task, attempt in inflight.items():
            task.cancel()
            self._load[attempt.node_id] -= 1
            self._pair_load[(attempt.node_id, attempt.family)] -= 1
            attempt.status = "cancelled_slow"   # slow, not dishonest (SPEC §11.4)
            self._event(attempt, "cancelled_slow")
        if not accepted and rejected:
            # Degraded, but an answer: the attempts say so ("degraded").
            for _, attempt in rejected:
                attempt.status = "degraded"
            return [replica for replica, _ in rejected]
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
            wait = self._busy_until.get(node_id, 0.0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                result = await self.nodes.dispatch_async(node_id, message,
                                                         self.timeout_s)
            except asyncio.CancelledError:
                self._busy_until[node_id] = time.monotonic() + CANCEL_GRACE_S
                raise
            except Exception as exc:
                attempt.status = "failed"
                attempt.code = getattr(exc, "code", "") or "E_TRANSPORT"
                attempt.note = str(getattr(exc, "detail", "") or exc)[:160]
                if attempt.code == "E_DEADLINE":
                    self._busy_until[node_id] = time.monotonic() + CANCEL_GRACE_S
                    self.timeouts += 1
                    self.speed.observe_timeout(node_id, attempt.model,
                                               self._max_tokens, self.timeout_s)
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
        self.speed.observe(node_id, str(profile.get("model_version") or attempt.model),
                           telemetry.get("tokens_out"), telemetry.get("gen_ms"))
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
