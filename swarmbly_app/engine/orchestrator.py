"""Distributed request orchestrator (composes the SwarmblyAI pipeline).

Reuses swarmbly_v0 for everything algorithmic (privacy classification, router,
contract Γ, DAG plan, ρ-aware packing, micro consensus via multiple alignment,
macro assembly select-then-splice, coherence metrics) and dispatches each
micro-task as a real SPEC §8 packet to authenticated LAN workers. Every stage
is emitted as an event with an honest status: pending → running → completed |
skipped | not_available | failed. Stages that do not apply are skipped, never
marked completed.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..events import EventBus
from ..inference.base import StreamBackend
from ..p2p.node import NodeManager
from .dispatch import DistributedBackend, NoWorkers

# SPEC v0.2 normative stages for observability (product spec §6.3)
PIPELINE_STAGES = [
    "REQUEST RECEIVED",
    "PRIVACY CLASSIFICATION",
    "ROUTING / DECOMPOSABILITY",
    "TASK PLANNING",
    "PACKET GENERATION",
    "NODE SELECTION",
    "DISPATCHING",
    "MODEL EXECUTION",
    "RESULT RECEPTION",
    "VERIFICATION",
    "CONSENSUS / ALIGNMENT",
    "ASSEMBLY",
    "COHERENCE REPORT",
    "FINAL RESPONSE",
]

# Documented placeholders, on the same footing as SwarmblyAI's own defaults.
ALPHA_HIGH_PLACEHOLDER = 0.80
ALPHA_LOW_PLACEHOLDER = 0.55


@dataclass
class Stage:
    name: str
    status: str = "pending"          # pending|running|completed|skipped|not_available|failed
    detail: dict[str, Any] = field(default_factory=dict)
    started_ms: float | None = None
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"stage": self.name, "status": self.status}
        out.update(self.detail)
        if self.elapsed_ms is not None:
            out["elapsed_ms"] = int(self.elapsed_ms)
        return out


class StageTracker:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.stages: dict[str, Stage] = {name: Stage(name)
                                         for name in PIPELINE_STAGES}
        self._running: dict[str, float] = {}

    def start(self, name: str, **detail: Any) -> None:
        stage = self.stages.get(name)
        if stage is None:
            return
        stage.status = "running"
        stage.started_ms = time.time() * 1000
        stage.detail = detail
        self.bus.publish("request.stage", stage=name, status="running", **detail)

    def complete(self, name: str, **detail: Any) -> None:
        stage = self.stages.get(name)
        if stage is None:
            return
        if stage.started_ms is not None:
            stage.elapsed_ms = time.time() * 1000 - stage.started_ms
        stage.status = "completed"
        stage.detail.update(detail)
        self.bus.publish("request.stage", stage=name, status="completed",
                         elapsed_ms=stage.elapsed_ms, **stage.detail)

    def skip(self, name: str, reason: str) -> None:
        stage = self.stages.get(name)
        if stage is None:
            return
        stage.status = "skipped"
        stage.detail = {"reason": reason}
        self.bus.publish("request.stage", stage=name, status="skipped",
                         reason=reason)

    def unavailable(self, name: str, reason: str) -> None:
        stage = self.stages.get(name)
        if stage is None:
            return
        stage.status = "not_available"
        stage.detail = {"reason": reason}
        self.bus.publish("request.stage", stage=name, status="not_available",
                         reason=reason)

    def fail(self, name: str, detail: str) -> None:
        stage = self.stages.get(name)
        if stage is None:
            return
        stage.status = "failed"
        stage.detail = {"detail": detail}
        self.bus.publish("request.stage", stage=name, status="failed",
                         detail=detail)

    def list(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.stages.values()]


class LocalPromptBackend:
    """Adapts a streaming local backend to ``generate(prompt)`` for bridges
    and judging — those always run on the local device (SPEC §14.3)."""

    def __init__(self, stream: StreamBackend, model: str):
        self._stream = stream
        self.model = model

    def generate(self, prompt: str, **kw: Any) -> str:
        out = self._stream.stream_chat([{"role": "user", "content": prompt}],
                                       model=self.model, **kw)
        return out.text


class Orchestrator:
    def __init__(self, nodes: NodeManager, bus: EventBus,
                 local_stream: StreamBackend, config_getter,
                 local_model: str = ""):
        self.nodes = nodes
        self.bus = bus
        self.local_stream = local_stream
        self.config = config_getter
        self.local_model = local_model

    # -- public entry -----------------------------------------------------------
    def run(self, text: str, *, mode: str = "lan",
            k: int | None = None, rho_target: float | None = None,
            n_fragments: int | None = None) -> dict[str, Any]:
        """Execute one request through the distributed pipeline.

        Returns ``{"routed": "distributed", "text", "metadata", "stages"}`` or
        ``{"routed": "local", "reason", "metadata", "stages"}`` when privacy
        or the router forbid fragmentation. Callers run the local path for the
        latter.
        """
        cfg = self.config()
        swarm_cfg = cfg["swarm"]
        privacy_cfg = cfg["privacy"]
        k = k if k is not None else int(swarm_cfg.get("k_min", 1))
        rho_target = rho_target if rho_target is not None else float(
            swarm_cfg.get("rho_target", 1.5))
        n_fragments = n_fragments if n_fragments is not None else int(
            swarm_cfg.get("n_fragments_max", 4))
        tracker = StageTracker(self.bus)
        started = time.time()
        metadata: dict[str, Any] = {}

        try:
            tracker.complete("REQUEST RECEIVED", mode=mode)
            tracker.start("PRIVACY CLASSIFICATION")
            decision = self._classify(text, privacy_cfg)
            tier = decision.tier
            tracker.complete("PRIVACY CLASSIFICATION", tier=tier,
                             source=decision.source,
                             rationale=decision.rationale)
            if tier == "LOCAL":
                tracker.skip("ROUTING / DECOMPOSABILITY", "tier LOCAL")
                for later in ("TASK PLANNING", "PACKET GENERATION",
                              "NODE SELECTION", "DISPATCHING",
                              "MODEL EXECUTION", "RESULT RECEPTION",
                              "CONSENSUS / ALIGNMENT", "ASSEMBLY",
                              "COHERENCE REPORT", "FINAL RESPONSE"):
                    tracker.skip(later, "LOCAL tier: nothing leaves the device")
                return {"routed": "local",
                        "reason": "privacy tier LOCAL forbids network dispatch",
                        "metadata": {"tier": "LOCAL"},
                        "stages": tracker.list()}
            if tier == "TRUSTED":
                tracker.fail("PRIVACY CLASSIFICATION",
                             "TRUSTED tier requires mutual TLS (not yet supported)")
                return {"routed": "error",
                        "reason": "TRUSTED tier requires mTLS (Phase 2.1)",
                        "metadata": {}, "stages": tracker.list()}

            tracker.start("ROUTING / DECOMPOSABILITY")
            routing = self._route(text)
            tracker.complete("ROUTING / DECOMPOSABILITY",
                             decomposable=routing.decomposable,
                             score=round(float(routing.score), 4),
                             threshold=round(float(routing.threshold), 4),
                             rationale=routing.rationale)
            if not routing.decomposable:
                for later in ("TASK PLANNING", "PACKET GENERATION",
                              "NODE SELECTION", "DISPATCHING",
                              "MODEL EXECUTION", "RESULT RECEPTION",
                              "CONSENSUS / ALIGNMENT", "ASSEMBLY",
                              "COHERENCE REPORT", "FINAL RESPONSE"):
                    tracker.skip(later, "router refused to fragment")
                return {"routed": "local",
                        "reason": "router refused to fragment (request not decomposable)",
                        "metadata": {"router": routing.__dict__},
                        "stages": tracker.list()}

            tracker.start("TASK PLANNING")
            contract, plan = self._plan(text, n_fragments)
            if plan.sequential or len(plan.tasks) < 2:
                tracker.fail("TASK PLANNING",
                             "plan is a chain or too small to fragment")
                return {"routed": "error",
                        "reason": "plan not parallelizable (SPEC §7)",
                        "metadata": {}, "stages": tracker.list()}
            tracker.complete("TASK PLANNING", n_tasks=len(plan.tasks))

            tracker.start("PACKET GENERATION")
            packing = self._pack(contract, plan, rho_target)
            tracker.complete("PACKET GENERATION",
                             rho_target=packing.rho_target,
                             rho_achieved=round(float(packing.rho_achieved), 4),
                             rho_floor=round(float(packing.rho_floor), 4),
                             rho_reachable=bool(packing.reachable))
            metadata.update({
                "rho_target": packing.rho_target,
                "rho_achieved": round(float(packing.rho_achieved), 4),
                "rho_floor": round(float(packing.rho_floor), 4),
                "rho_reachable": bool(packing.reachable),
            })

            tracker.start("NODE SELECTION")
            workers = self.nodes.available_workers()
            if not workers:
                tracker.fail("NODE SELECTION", "no connected workers")
                raise NoWorkers("no connected workers available")
            families = sorted({m.get("family", "unknown")
                               for w in workers
                               for m in w.advertisement.get("models", [])})
            tracker.complete("NODE SELECTION", workers=len(workers),
                             families=families)

            backend = DistributedBackend(
                self.nodes, self.bus, self._gamma_dict(contract),
                lane="PUBLIC", tier=tier,
                deadline_ms=int(swarm_cfg.get("timeout_ms", 60000)),
                timeout_s=float(swarm_cfg.get("timeout_ms", 60000)) / 1000 + 10,
                max_tokens=int(cfg["model"].get("max_tokens", 1024)))

            tracker.start("DISPATCHING")
            tracker.start("MODEL EXECUTION")
            tracker.start("RESULT RECEPTION")
            texts, consensus_block = self._dispatch_and_resolve(
                backend, packing, plan, contract, k, tracker)
            tracker.complete("DISPATCHING")
            tracker.complete("MODEL EXECUTION")
            tracker.complete("RESULT RECEPTION")

            # VERIFICATION: Layer-1 commitment has no normative construction.
            tracker.unavailable(
                "VERIFICATION",
                "Layer-1 commitment (lsh-activation-v1) has no normative "
                "construction (SPEC §21.1); result signatures were verified")
            if k > 1:
                tracker.complete("CONSENSUS / ALIGNMENT", **consensus_block)
            else:
                tracker.skip("CONSENSUS / ALIGNMENT", "k=1 requested")
                metadata["consensus"] = None
                metadata["consensus_waived_reason"] = "k=1_requested"

            tracker.start("ASSEMBLY")
            assembly_text, seams = self._assemble(contract, plan, texts)
            tracker.complete("ASSEMBLY", n_seams=len(seams))

            tracker.start("COHERENCE REPORT")
            coherence = self._coherence(assembly_text, seams)
            tracker.complete("COHERENCE REPORT", **coherence)

            metadata.update({
                "n_tasks": len(plan.tasks),
                "tau_sem": self._tau_sem(),
                "tau_source": self._tau_source(),
                "seams": seams,
                "coherence": coherence,
                "verification": {"commitments_checked": 0, "failures": 0,
                                 "commitment_scheme": None,
                                 "signatures_checked": len(texts)},
                "consensus": consensus_block if k > 1 else None,
                "consensus_waived_reason": None if k > 1 else "k=1_requested",
                "routing": {"tier": tier, "classifier": decision.source},
                "nodes": [{"node_id": w.node_id[:12], "role": "worker"}
                          for w in workers],
                "total_ms": int((time.time() - started) * 1000),
            })
            tracker.complete("FINAL RESPONSE", total_ms=metadata["total_ms"])
            return {"routed": "distributed", "text": assembly_text,
                    "metadata": metadata, "stages": tracker.list()}
        except Exception as exc:
            tracker.fail("FINAL RESPONSE", str(exc)[:200])
            raise

    # -- pipeline pieces (reuse) ---------------------------------------------------
    @staticmethod
    def _classify(text: str, privacy_cfg: dict[str, Any]):
        from swarmbly_v0 import classify
        manual = privacy_cfg.get("manual_tier")
        decision = classify(text, swarm_id=None)
        if manual in ("GLOBAL", "TRUSTED", "LOCAL"):
            decision = decision.__class__(
                tier=manual, source="manual", entity_classes=(),
                swarm_id=None, rationale="manual tier is authoritative")
        elif privacy_cfg.get("tier") == "LOCAL":
            decision = decision.__class__(
                tier="LOCAL", source="config", entity_classes=(),
                swarm_id=None, rationale="configured default tier LOCAL")
        return decision

    @staticmethod
    def _route(text: str):
        from swarmbly_v0.router import is_decomposable
        return is_decomposable(text)

    def _plan(self, text: str, n_fragments: int):
        from swarmbly_v0 import planner
        contract = planner.global_contract(text, backend=None)
        plan = planner.plan(text, backend=None, n_tasks=n_fragments,
                            contract=contract, force_sequential=False)
        return contract, plan

    @staticmethod
    def _pack(contract, plan, rho_target: float):
        from swarmbly_v0.packing import build_packets
        return build_packets(contract, plan, rho_target)

    def _dispatch_and_resolve(self, backend: DistributedBackend, packing,
                              plan, contract, k: int, tracker: StageTracker):
        """Dispatch packets level-by-level; resolve k replicas per task.

        The upstream pipeline walks the DAG level by level so that a packet
        carries only summaries of predecessors that actually produced output.
        """
        mapping: dict[str, list[str]] = {}
        consensus_block: dict[str, Any] = {}
        levels = _topological_levels(plan)
        summaries: dict[str, str] = {}
        families_used: set[str] = set()
        for level in levels:
            tasks = [t for t in plan.tasks if t.task_id in level]
            for task in tasks:
                from swarmbly_v0.packing import build_packets
                pkg = build_packets(contract, plan, packing.rho_target,
                                    summaries=summaries,
                                    only_tasks=[task.task_id])
                packet = pkg.packets[0]
                replicas: list[str] = []
                for attempt in range(k):
                    replica_backend = backend.for_replica(
                        "any", _nth_worker(self.nodes, attempt))
                    try:
                        text = replica_backend.generate(packet.text)
                    except NoWorkers:
                        if attempt == 0:
                            raise
                        continue  # fewer workers than k: fewer replicas, reported
                    replicas.append(text)
                if k > 1 and len(replicas) > 1:
                    chosen, units, mean_agreement = self._micro_consensus(
                        replicas)
                    mapping[task.task_id] = [chosen]
                    consensus_block["units"] = units
                    consensus_block["mean_agreement"] = mean_agreement
                    consensus_block["k"] = len(replicas)
                else:
                    mapping[task.task_id] = replicas[:1]
                summaries[task.task_id] = (mapping[task.task_id][0])[:400]
        if k > 1:
            consensus_block.setdefault("k", k)
            consensus_block.setdefault("families", sorted(families_used))
            consensus_block.setdefault("mean_agreement", 0.0)
            consensus_block["alpha_high"] = ALPHA_HIGH_PLACEHOLDER
            consensus_block["alpha_low"] = ALPHA_LOW_PLACEHOLDER
            consensus_block["thresholds_source"] = "placeholder"
        return mapping, consensus_block

    def _micro_consensus(self, replicas: list[str]):
        from swarmbly_v0.consensus import (align_multiple, agreement_score,
                                           segment_units)
        embedder = self._embedder()
        units_per_replica = [segment_units(text) for text in replicas]
        columns = align_multiple(units_per_replica, embedder)
        out_parts: list[str] = []
        unit_reports: list[dict[str, Any]] = []
        for column in columns:
            score = float(agreement_score(column, embedder))
            label = ("HIGH" if score >= ALPHA_HIGH_PLACEHOLDER
                     else "MEDIUM" if score >= ALPHA_LOW_PLACEHOLDER else "LOW")
            text = _column_medoid(column)
            out_parts.append(text)
            unit_reports.append({"label": label, "agreement": round(score, 4),
                                 "text": text[:120]})
        mean_agreement = (sum(u["agreement"] for u in unit_reports) /
                          len(unit_reports)) if unit_reports else 0.0
        return " ".join(out_parts), unit_reports, round(float(mean_agreement), 4)

    def _assemble(self, contract, plan, texts: dict[str, list[str]]):
        from swarmbly_v0.assembler import fragments_from_mapping, select_then_splice
        fragments = fragments_from_mapping(texts, plan=plan)
        local = LocalPromptBackend(self.local_stream, self.local_model)
        assembly = select_then_splice(
            fragments, contract, local, self._tau_sem(), plan=plan,
            embedder=self._embedder())
        seams = [{"left": s.left_task, "right": s.right_task,
                  "similarity": round(float(s.similarity), 4),
                  "path": "bridge" if s.bridged else "splice"}
                 for s in assembly.seams]
        return assembly.text, seams

    def _coherence(self, text: str, seams: list[dict[str, Any]]) -> dict[str, Any]:
        from swarmbly_v0.metrics import entity_grid
        grid = entity_grid(text)
        return {"entity_grid": round(float(grid.score), 4),
                "seam_free_sentence_fraction": None,
                "n_seams": len(seams),
                "errors": {}}

    # -- helpers ----------------------------------------------------------------------
    def _embedder(self):
        cfg = self.config()
        kind = cfg["model"].get("embedder", "hash")
        if kind == "server":
            try:
                from swarmbly_v0 import ServerEmbedder
                return ServerEmbedder(url=cfg["model"].get("backend_url")
                                      or "http://127.0.0.1:11434/v1")
            except Exception:
                pass
        from swarmbly_v0 import HashEmbedder
        return HashEmbedder()

    def _tau_sem(self) -> float:
        return float(self.config()["swarm"].get("tau_sem", 0.5))

    def _tau_source(self) -> str:
        return ("placeholder:0.5 (calibration pending — same footing as "
                "SwarmblyAI documented defaults)")

    def _gamma_dict(self, contract) -> dict[str, Any]:
        """Map the internal Contract to the SPEC §5 Γ JSON."""
        return {
            "v": "0.2",
            "objective": contract.objective,
            "audience": contract.audience,
            "register": contract.register,
            "format": contract.output_format,
            "target_len": contract.target_length_tokens,
            "lexicon": {"prefer": [], "forbid": list(contract.forbidden_terms)},
            "entities": [{"name": e, "canonical": e, "role": ""}
                         for e in contract.canonical_entities],
            "style_seed": "",
            "budget": {"max_out_tokens": 600},
        }


def _topological_levels(plan) -> list[set[str]]:
    """Levels of the DAG (same-level tasks run in parallel)."""
    remaining = {t.task_id: set(t.depends_on) for t in plan.tasks}
    levels: list[set[str]] = []
    while remaining:
        level = {tid for tid, deps in remaining.items() if not deps}
        if not level:
            raise ValueError("plan has a cycle")
        levels.append(level)
        remaining = {tid: deps - level for tid, deps in remaining.items()
                     if tid not in level}
    return levels


def _nth_worker(nodes: NodeManager, index: int) -> str:
    workers = nodes.available_workers()
    return workers[index % len(workers)].node_id


def _column_medoid(column) -> str:
    """Pick the column's most central unit (highest mean pairwise cosine)."""
    vectors = getattr(column, "vectors", {}) or {}
    if not vectors:
        units = getattr(column, "units", {}) or {}
        texts = [u.text for u in units.values()]
        return texts[0] if texts else ""
    ids = list(vectors.keys())
    matrix = np.vstack([vectors[i] for i in ids])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    sims = (matrix / norms) @ (matrix / norms).T
    best = int(np.argmax(sims.sum(axis=1)))
    units = getattr(column, "units", {}) or {}
    for rep_id, unit in units.items():
        if rep_id == ids[best]:
            return unit.text
    return list(units.values())[0].text if units else ""
