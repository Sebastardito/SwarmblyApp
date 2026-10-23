"""Speed-aware routing (P3b.3'', 22 Oct 2026: llama3.1:8b on CPU timed out)."""

from __future__ import annotations

from types import SimpleNamespace

from swarmbly_app.engine.scheduler import LatencyStats, Scheduler, SpeedStats


def test_speed_is_learned_and_timeouts_bound_it():
    s = SpeedStats()
    s.observe("n", "m", tokens=200, gen_ms=10000)          # 20 tok/s
    assert s.tokens_per_s("n", "m") == 20
    s.observe_timeout("n", "big", max_tokens=600, timeout_s=60)
    assert s.tokens_per_s("n", "big") == 10
    assert s.estimate_s("n", "big", 600) == 60
    assert s.estimate_s("n", "unknown", 600) is None


class _Bus:
    def publish(self, *a, **k):
        pass


def _peer(node_id, models):
    return SimpleNamespace(node_id=node_id, tasks_inflight=0, rtt_ms=10.0,
                           advertisement={"models": [{"family": f, "version": v}
                                                     for f, v in models],
                                          "policy": {"max_concurrent": 1}})


class _Nodes:
    def __init__(self, peers):
        self.peers = {p.node_id: p for p in peers}

    def available_workers(self, kind="generate"):
        return list(self.peers.values())


def test_a_model_known_to_miss_the_deadline_loses_to_a_smaller_one():
    server = _peer("server", [("llama", "llama3.1:8b")])
    laptop = _peer("laptop", [("phi3", "phi3.5:3.8b")])
    speed = SpeedStats()
    speed.observe_timeout("server", "llama3.1:8b", max_tokens=600, timeout_s=60)
    speed.observe("laptop", "phi3.5:3.8b", tokens=300, gen_ms=15000)   # 20 tok/s
    s = Scheduler(_Nodes([server, laptop]), _Bus(), "r", k_min=1, k_max=2,
                  max_concurrency=4, timeout_s=60, hedge_fallback_s=30,
                  latency=LatencyStats(), speed=speed)
    peer, family, model = s._select(set(), set(), set(), max_tokens=600)
    assert model == "phi3.5:3.8b"
    # with no speed data the larger model still wins
    s2 = Scheduler(_Nodes([server, laptop]), _Bus(), "r", k_min=1, k_max=2,
                   max_concurrency=4, timeout_s=60, hedge_fallback_s=30,
                   latency=LatencyStats())
    assert s2._select(set(), set(), set(), max_tokens=600)[2] == "llama3.1:8b"


def test_app_keeps_speed_across_orchestrator_rebuilds(app_state):
    first = app_state.get_orchestrator()
    first.speed.observe("n", "m", 100, 1000)
    app_state.orchestrator = None
    assert app_state.get_orchestrator().speed.tokens_per_s("n", "m") == 100


def test_a_node_that_just_failed_ranks_below_healthy_ones():
    a = _peer("a", [("phi3", "phi3.5:3.8b")])
    b = _peer("b", [("phi3", "phi3.5:3.8b")])
    speed = SpeedStats()
    speed.record_failure("a")
    s = Scheduler(_Nodes([a, b]), _Bus(), "r", k_min=1, k_max=2, max_concurrency=4,
                  timeout_s=60, hedge_fallback_s=30, latency=LatencyStats(), speed=speed)
    assert s._select(set(), set(), set(), max_tokens=300)[0].node_id == "b"
    speed.record_success("a")
    assert not speed.recently_failed("a")
