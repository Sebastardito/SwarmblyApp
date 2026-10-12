"""Two-node distributed execution test: the v0.1 acceptance criterion.

Two AppStates on loopback, different ports: TLS 1.3 channel, Ed25519
handshake, SPEC v0.2 wire packets, real (fake-backend) micro-task execution,
assembly and SPEC §19 metadata. This is the reproducible proof that a request
can be fragmented and served by another node without manual IP-free discovery.
"""

from __future__ import annotations

import time

import pytest

from swarmbly_app.state import AppState

from conftest import FakeBackend

TEST_PROMPT = (
    "Extract one key fact per item from the following list of five items: "
    "apples, bridges, comets, drums, electrons. List 5 bullet points, one per "
    "item, separately."
)


@pytest.fixture()
def two_nodes(tmp_path):
    state_a = AppState(str(tmp_path / "A"))
    state_b = AppState(str(tmp_path / "B"))
    # B is the worker; A is the orchestrator.
    state_b.config.update({"swarm": {"worker_enabled": True, "lan_enabled": True,
                                     "p2p_port": 9771, "worker_allow_lan": True}})
    state_a.config.update({"swarm": {"lan_enabled": True, "p2p_port": 9772},
                           "privacy": {"tier": "GLOBAL"},
                           "model": {"model_name": "fake-model:1b"}})
    state_b.config.update({"model": {"model_name": "fake-model:1b"}})
    fake_a = FakeBackend("alpha beta gamma delta epsilon zeta eta theta.")
    fake_b = FakeBackend("worker fragment answer with key facts.")
    state_a.backends.resolve = lambda cfg=None: fake_a  # type: ignore[method-assign]
    state_b.backends.resolve = lambda cfg=None: fake_b  # type: ignore[method-assign]
    state_a.start_p2p()
    state_b.start_p2p()
    time.sleep(0.8)  # event loops boot
    state_a.nodes.connect_manual("127.0.0.1", 9771)
    deadline = time.time() + 8
    while time.time() < deadline:
        if state_a.nodes.status()["connected_count"] >= 1:
            break
        time.sleep(0.15)
    assert state_a.nodes.status()["connected_count"] >= 1, "handshake failed"
    yield state_a, state_b
    state_a.stop()
    state_b.stop()
    time.sleep(0.3)


class TestTwoNodeDistributed:
    def test_handshake_connected_and_verified(self, two_nodes):
        state_a, _ = two_nodes
        status = state_a.nodes.status()
        assert status["connected_count"] == 1
        assert status["verified_count"] == 1
        peer = status["peers"][0]
        assert peer["node_id"]  # full Ed25519 id after handshake

    def test_distributed_request_end_to_end(self, two_nodes):
        state_a, state_b = two_nodes
        conv = state_a.chat.create_conversation(title="dist", mode="lan",
                                                model="fake-model:1b")
        user, assistant = state_a.chat.send(conv["id"], TEST_PROMPT,
                                            mode="lan", run_async=False)
        rows = state_a.chat.get_messages(conv["id"])
        final = rows[-1]
        assert final["meta"]["status"] == "done", final["meta"]
        swarm = final["meta"].get("swarm", {})
        # SPEC §19 essentials
        assert swarm["n_tasks"] >= 2
        assert swarm["rho_target"] > 0
        assert "rho_achieved" in swarm
        assert swarm["verification"]["commitments_checked"] == 0  # honest
        assert swarm["consensus"] is None  # k=1 → null with waiver
        assert swarm["consensus_waived_reason"] == "k=1_requested"
        assert swarm["nodes"]  # participating worker recorded
        assert final["content"].strip()  # assembled answer present
        # stage log: verification marked not available, never completed
        stages = {s["stage"]: s["status"] for s in final["stages"]}
        assert stages["VERIFICATION"] == "not_available"
        assert stages["CONSENSUS / ALIGNMENT"] == "skipped"
        assert stages["FINAL RESPONSE"] == "completed"
        assert stages["PRIVACY CLASSIFICATION"] == "completed"
        # the worker actually served tasks
        served = state_b.worker.status()["tasks_served_today"]
        assert served >= 2, "worker should have served the micro-tasks"

    def test_privacy_local_never_egresses(self, two_nodes):
        state_a, state_b = two_nodes
        state_a.config.update({"privacy": {"tier": "LOCAL"}})
        served_before = state_b.worker.status()["tasks_served_today"]
        conv = state_a.chat.create_conversation(mode="lan")
        user, assistant = state_a.chat.send(
            conv["id"], TEST_PROMPT, mode="lan", run_async=False)
        rows = state_a.chat.get_messages(conv["id"])
        final = rows[-1]
        # routed locally: status done via local backend, no swarm metadata
        assert final["meta"]["status"] == "done"
        assert not final["meta"].get("swarm")
        assert state_b.worker.status()["tasks_served_today"] == served_before

    def test_no_workers_fails_honestly(self, tmp_path):
        state = AppState(str(tmp_path / "solo"))
        state.config.update({"privacy": {"tier": "GLOBAL"},
                             "model": {"model_name": "fake-model:1b"},
                             "swarm": {"p2p_port": 9781}})
        fake = FakeBackend("solo answer.")
        state.backends.resolve = lambda cfg=None: fake  # type: ignore[method-assign]
        state.start_p2p()
        time.sleep(0.6)
        conv = state.chat.create_conversation(mode="lan")
        user, assistant = state.chat.send(conv["id"], TEST_PROMPT,
                                          mode="lan", run_async=False)
        rows = state.chat.get_messages(conv["id"])
        final = rows[-1]
        assert final["meta"]["status"] == "failed"
        assert "no connected workers" in final["meta"].get("error", "")
        state.stop()


class TestMicroConsensus:
    def test_replica_ids_and_consensus(self, app_state):
        """Regression: micro-consensus must assign distinct replica ids
        (previously raised KeyError('') inside swarmbly_v0.consensus)."""
        from swarmbly_app.engine.orchestrator import Orchestrator
        from conftest import FakeBackend
        fake = FakeBackend("alpha beta gamma delta epsilon.")
        orch = Orchestrator(app_state.nodes, app_state.bus, fake,
                            app_state.config.all, local_model="fake-model:1b")
        chosen, units, mean_agreement = orch._micro_consensus(
            ["alpha beta gamma delta epsilon.",
             "alpha beta gamma delta epsilon."])
        assert chosen.strip()
        assert len(units) >= 1
        assert isinstance(mean_agreement, float)
        assert units[0]["label"] in ("HIGH", "MEDIUM", "LOW")
