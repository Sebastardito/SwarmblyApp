"""Routing on a heterogeneous swarm (P3b, 21 October 2026)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from swarmbly_app.engine.capability import eligible, model_params_b, rank_params
from swarmbly_app.engine.scheduler import LatencyStats, Scheduler


@pytest.mark.parametrize("tag,size", [
    ("qwen2.5:7b", 7.0), ("phi3.5:3.8b", 3.8), ("llama3.1:8b-instruct-q4_K_M", 8.0),
    ("granite3.1-dense:2b", 2.0), ("qwen2.5:0.5b", 0.5), ("mistral:latest", None),
])
def test_params_from_tag(tag, size):
    assert model_params_b(tag) == size


def test_eligibility_and_rank():
    assert not eligible("qwen2.5:0.5b", 1.5) and eligible("qwen2.5:3b", 1.5)
    assert eligible("mistral:latest", 1.5)               # unknown size: owner's choice
    assert rank_params("llama3.1:8b") > rank_params("llama3.2:1b")


class _Bus:
    def publish(self, *a, **k):
        pass


def _peer(node_id, models, cap=1):
    return SimpleNamespace(node_id=node_id, tasks_inflight=0, rtt_ms=10.0,
                           advertisement={"models": [{"family": f, "version": v}
                                                     for f, v in models],
                                          "policy": {"max_concurrent": cap}})


class _Nodes:
    def __init__(self, peers, replies):
        self.peers = {p.node_id: p for p in peers}
        self.replies = replies            # node_id -> text
        self.sent = []

    def available_workers(self, kind="generate"):
        return list(self.peers.values())

    async def dispatch_async(self, node_id, message, timeout_s):
        self.sent.append((node_id, message))
        return {"type": "result", "attempt_id": message["attempt_id"],
                "text": self.replies[node_id], "profile": {}, "telemetry": {}}


def _scheduler(nodes, k_min=1, k_max=3, min_b=1.5):
    return Scheduler(nodes, _Bus(), "r", k_min=k_min, k_max=k_max, max_concurrency=4,
                     timeout_s=5, hedge_fallback_s=5, latency=LatencyStats(),
                     min_params_b=min_b)


SERVER = _peer("server", [("llama", "llama3.2:1b"), ("llama", "llama3.1:8b"),
                          ("qwen2", "qwen2.5:0.5b"), ("qwen2", "qwen2.5:7b")])
LAPTOP = _peer("laptop", [("qwen2", "qwen2.5:0.5b"), ("qwen2", "qwen2.5:1.5b")])


def test_candidates_take_the_largest_eligible_model_per_family():
    cands = {(p.node_id, f): m for p, f, m in _scheduler(_Nodes([SERVER, LAPTOP], {}))._candidates()}
    assert cands == {("server", "llama"): "llama3.1:8b", ("server", "qwen2"): "qwen2.5:7b",
                     ("laptop", "qwen2"): "qwen2.5:1.5b"}


def test_tiny_only_swarm_still_answers():
    tiny = _peer("tiny", [("qwen2", "qwen2.5:0.5b")])
    cands = _scheduler(_Nodes([tiny], {}))._candidates()
    assert [m for _, _, m in cands] == ["qwen2.5:0.5b"]


def test_echo_is_rejected_and_retried_elsewhere(monkeypatch):
    import swarmbly_app.engine.scheduler as sched
    monkeypatch.setattr(sched, "verify_result", lambda *a: "")
    nodes = _Nodes([SERVER, LAPTOP], {"server": "1. dog\n2. cat", "laptop": "1. perro\n2. gato"})
    s = _scheduler(nodes, k_min=1, k_max=3)
    # make the laptop look best so it is tried first
    s._load["server"] = 5

    def build(n, family, model=None):
        return {"attempt_id": f"a{n}", "constraints": {"model": model}}

    def valid(text):
        return "dog" in text
    replicas = asyncio.run(s.run_task("t0", build, 100, validate=valid))
    assert [r.text for r in replicas] == ["1. dog\n2. cat"]
    assert [a.status for a in s.attempts] == ["rejected", "accepted"]
    assert s.attempts[0].code == "E_QUALITY"
    assert nodes.sent[0][1]["constraints"]["model"] == "qwen2.5:1.5b"


def test_all_rejected_returns_the_degraded_answer(monkeypatch):
    import swarmbly_app.engine.scheduler as sched
    monkeypatch.setattr(sched, "verify_result", lambda *a: "")
    nodes = _Nodes([LAPTOP], {"laptop": "1. perro"})
    s = _scheduler(nodes, k_min=1, k_max=1)
    out = asyncio.run(s.run_task("t0", lambda n, f, m=None: {"attempt_id": f"a{n}"}, 100,
                                 validate=lambda text: False))
    assert [r.text for r in out] == ["1. perro"]


def test_worker_picks_exact_model_then_largest_of_family(app_state, fake_chat):
    from test_worker_policy import make_worker, task_message
    app_state.config.update({"swarm": {"worker_enabled": True,
                                       "worker_models": ["llama3.2:1b", "llama3.1:8b",
                                                         "qwen2.5:3b"]}})
    _, fake = fake_chat
    worker = make_worker(app_state, fake)
    assert worker._pick_model({"constraints": {"model_family": "llama3.2"}}) in (
        "llama3.1:8b", "llama3.2:1b")
    assert worker._pick_model({"constraints": {"model": "qwen2.5:3b"}}) == "qwen2.5:3b"
    assert worker._pick_model({"constraints": {"model_family": "llama"}}) == "llama3.1:8b"


def test_admission_keeps_several_items_per_fragment():
    from swarmbly_app.engine.admission import admit
    prompt = "Para cada país, indica su capital:\n" + "\n".join(
        f"{i}. País {i}" for i in range(1, 9))
    assert admit(prompt, n_max=16, n_workers=8, min_items_per_fragment=3).n_tasks == 3
    assert admit(prompt, n_max=16, n_workers=8).n_tasks >= 3


def test_items_are_normalised_one_per_line():
    from swarmbly_app.engine.orchestrator import _normalise_items
    items = {5: "Pinzón de Darwin", 6: "Tiburón martillo", 7: "Pingüino", 8: "Rana"}
    raw = "```markdown\n5. Ave 6. Pez\n- 7. Ave\n*   #8: anfibio\n```"
    out = _normalise_items(raw, items)
    assert out.splitlines()[:2] == ["5. Ave", "6. Pez"]
