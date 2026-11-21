"""Trusted circles (D-015): admission, join flow, revocation and API."""

from __future__ import annotations

import asyncio
import itertools
import time

import pytest

from swarmbly_app.p2p.circles import E_CIRCLE_REQUIRED
from swarmbly_app.p2p.messages import packet, WIRE_VERSION
from swarmbly_app.state import AppState

from conftest import FakeBackend

_ports = itertools.count(19950)
TEST_PROMPT = (
    "Extract one key fact per item from the following list of five items: "
    "apples, bridges, comets, drums, electrons. List 5 bullet points, one per "
    "item, separately."
)


def wait_for(predicate, timeout=10.0, step=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def make_node(tmp_path, name, *, worker=False, mode="circle", port=None):
    state = AppState(str(tmp_path / name))
    state.config.update({
        "swarm": {"p2p_port": port or next(_ports), "p2p_host": "127.0.0.1",
                  "lan_enabled": False, "worker_enabled": worker,
                  "worker_max_concurrent": 2, "timeout_ms": 8000},
        "circle": {"admission_mode": mode, "node_name": name},
        "privacy": {"tier": "GLOBAL"},
        "model": {"model_name": "fake-model:1b"},
    })
    fake = FakeBackend("Apples are fruit. Bridges span rivers.")
    state.backends.resolve = lambda cfg=None: fake  # type: ignore[method-assign]
    state.start_p2p()
    return state, fake



def connect(client, worker):
    peer = client.nodes.connect_manual("127.0.0.1", worker.nodes.listen_port,
                                       wait=True)
    return peer


def task_message(attempt="t:0"):
    return packet(
        attempt_id=attempt,
        contract={"v": WIRE_VERSION, "objective": "o", "audience": "a",
                  "register": "neutral", "format": "prose", "target_len": 100,
                  "lexicon": {}, "entities": [], "style_seed": "",
                  "budget": {"max_out_tokens": 300}},
        predecessors=[],
        task={"instruction": "answer", "kind": "generate",
              "expects": {"format": "prose", "max_tokens": 300}},
        deadline_ms=60000, lane="PUBLIC", tier="GLOBAL")


@pytest.fixture()
def nodes(tmp_path):
    created = []

    def factory(*args, **kw):
        state, fake = make_node(tmp_path, *args, **kw)
        created.append(state)
        return state, fake

    yield factory
    for state in created:
        state.stop()


class TestJoinAndAdmission:
    def _pair(self, nodes):
        owner, _ = nodes("owner", worker=True)
        newcomer, _ = nodes("newcomer")
        circle = owner.circles.create_circle("Familia")
        invite = owner.circles.invite(
            circle["circle_id"],
            endpoints=[f"127.0.0.1:{owner.nodes.listen_port}"])
        return owner, newcomer, circle, invite

    def test_join_flow_and_manifest_version(self, nodes):
        owner, newcomer, circle, invite = self._pair(nodes)
        result = newcomer.circles.accept_invitation(
            invite["code"],
            endpoints=[f"127.0.0.1:{newcomer.nodes.listen_port}"])
        assert result["status"] in ("sent", "pending")
        assert wait_for(lambda: owner.circles.list_payload()["circles"][0]
                        ["pending_joins"])
        owner.circles.approve(circle["circle_id"], newcomer.identity.node_id)
        assert wait_for(lambda: newcomer.circles.list_payload()["circles"])
        member_view = newcomer.circles.list_payload()["circles"][0]
        assert member_view["version"] == 2
        assert {m["node_id"] for m in member_view["members"]} == {
            owner.identity.node_id, newcomer.identity.node_id}
        assert wait_for(lambda: len(newcomer.nodes.available_workers()) == 1)
        assert wait_for(lambda: all(
            p["admitted"] for p in owner.nodes.status()["peers"]))

    def test_member_can_run_a_task(self, nodes):
        owner, newcomer, circle, invite = self._pair(nodes)
        newcomer.circles.accept_invitation(
            invite["code"],
            endpoints=[f"127.0.0.1:{newcomer.nodes.listen_port}"])
        assert wait_for(lambda: owner.circles.list_payload()["circles"][0]
                        ["pending_joins"])
        owner.circles.approve(circle["circle_id"], newcomer.identity.node_id)
        assert wait_for(lambda: newcomer.nodes.available_workers())
        conv = newcomer.chat.create_conversation(mode="lan")
        newcomer.chat.send(conv["id"], TEST_PROMPT, mode="lan", run_async=False)
        final = newcomer.chat.get_messages(conv["id"])[-1]
        assert final["meta"]["status"] == "done", final["meta"]
        assert final["meta"]["executed"] == "distributed"

    def test_peers_fetch_a_newer_manifest(self, nodes):
        owner, member_a, circle, invite_a = self._pair(nodes)
        member_a.circles.accept_invitation(
            invite_a["code"],
            endpoints=[f"127.0.0.1:{member_a.nodes.listen_port}"])
        assert wait_for(lambda: owner.circles.list_payload()["circles"][0]
                        ["pending_joins"])
        owner.circles.approve(circle["circle_id"], member_a.identity.node_id)
        def a_has_v2():
            items = member_a.circles.list_payload()["circles"]
            return bool(items) and items[0]["version"] == 2

        assert wait_for(a_has_v2)
        member_b, _ = nodes("member_b")
        invite_b = owner.circles.invite(
            circle["circle_id"],
            endpoints=[f"127.0.0.1:{owner.nodes.listen_port}"])
        member_b.circles.accept_invitation(
            invite_b["code"],
            endpoints=[f"127.0.0.1:{member_b.nodes.listen_port}"])
        assert wait_for(lambda: any(
            r["node_id"] == member_b.identity.node_id
            for r in owner.circles.list_payload()["circles"][0]["pending_joins"]))
        # A is offline while the owner signs version 3.
        owner.nodes.drop_peer(member_a.identity.node_id, "test offline")

        def a_is_off():
            peer = owner.nodes.peers.get(member_a.identity.node_id)
            return peer is None or not peer.connected

        assert wait_for(a_is_off)
        owner.circles.approve(circle["circle_id"], member_b.identity.node_id)
        assert owner.circles.list_payload()["circles"][0]["version"] == 3
        # On reconnecting, A asks for the current manifest and stores it.
        assert connect(member_a, owner) is not None
        assert wait_for(lambda: member_a.circles.list_payload()["circles"][0]
                        ["version"] == 3, timeout=5)
        members = {m["node_id"] for m in
                   member_a.circles.list_payload()["circles"][0]["members"]}
        assert member_b.identity.node_id in members
        # The owner only admits A for tasks after A acknowledged the version.
        assert wait_for(lambda: bool(
            owner.nodes.peers.get(member_a.identity.node_id)
            and owner.nodes.peers[member_a.identity.node_id].admitted))

    def test_non_member_refused_at_handshake(self, nodes):
        owner, _, _, _ = self._pair(nodes)
        stranger, _ = nodes("stranger")
        assert connect(stranger, owner) is None
        assert not wait_for(lambda: owner.nodes.status()["peers"], timeout=1.0)
        rejected = [e for e in owner.bus.recent(50)
                    if e["type"] == "node.rejected"]
        assert rejected and E_CIRCLE_REQUIRED in rejected[-1]["payload"]["reason"]

    def test_non_member_refused_at_worker_gate(self, nodes, tmp_path):
        owner, _, _, _ = self._pair(nodes)
        stranger, _ = nodes("stranger")
        reply = asyncio.run(owner.worker.handle(
            stranger.identity.node_id, task_message()))
        assert reply["type"] == "error"
        assert reply["code"] == E_CIRCLE_REQUIRED

    def test_revocation_takes_effect(self, nodes):
        owner, newcomer, circle, invite = self._pair(nodes)
        newcomer.circles.accept_invitation(
            invite["code"],
            endpoints=[f"127.0.0.1:{newcomer.nodes.listen_port}"])
        assert wait_for(lambda: owner.circles.list_payload()["circles"][0]
                        ["pending_joins"])
        owner.circles.approve(circle["circle_id"], newcomer.identity.node_id)
        assert wait_for(lambda: newcomer.circles.list_payload()["circles"])
        revoked = owner.circles.revoke(circle["circle_id"],
                                       newcomer.identity.node_id)
        assert revoked["version"] == 3
        assert newcomer.identity.node_id not in {
            m["node_id"] for m in revoked["members"]}
        assert wait_for(lambda: not any(
            p["connected"] for p in owner.nodes.status()["peers"]), timeout=5)
        # A revoked node cannot get back in with the old manifest: the owner
        # refuses the handshake (the dialer may see a brief bootstrap-shaped
        # session before the owner's rejection arrives, then it drops).
        connect(newcomer, owner)
        assert wait_for(lambda: not any(
            p["connected"] for p in owner.nodes.status()["peers"]), timeout=5)
        assert wait_for(lambda: not any(
            p["connected"] for p in newcomer.nodes.status()["peers"]), timeout=5)
        rejected = [e for e in owner.bus.recent(50)
                    if e["type"] == "node.rejected"]
        assert rejected and E_CIRCLE_REQUIRED in rejected[-1]["payload"]["reason"]
        reply = asyncio.run(owner.worker.handle(
            newcomer.identity.node_id, task_message("revoked:0")))
        assert reply["code"] == E_CIRCLE_REQUIRED

    def test_own_devices_keeps_lan_admission(self, nodes):
        owner, _ = nodes("owner", worker=True, mode="own_devices")
        client, _ = nodes("client", mode="own_devices")
        assert connect(client, owner) is not None
        assert client.nodes.available_workers()
        reply = asyncio.run(owner.worker.handle(
            client.identity.node_id, task_message("own:0")))
        assert reply["type"] == "result"
        # Switching to circle-only drops the LAN peer that is not in a circle.
        owner.config.update({"circle": {"admission_mode": "circle"}})
        owner.on_config_changed()
        assert wait_for(lambda: not any(
            p["connected"] for p in owner.nodes.status()["peers"]))

    def test_circle_only_default_refuses_without_circle(self, nodes):
        owner, _ = nodes("owner", worker=True, mode="circle")
        client, _ = nodes("client", mode="circle")
        assert connect(client, owner) is None
        assert not owner.nodes.available_workers()


class TestCircleAPI:
    def test_routes_are_guarded_and_work(self, tmp_path, app_state):
        from fastapi.testclient import TestClient
        from swarmbly_app.api import create_app
        app = create_app(app_state)
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        assert client.get("/api/circles").status_code == 401
        client.headers["X-Swarmbly-Token"] = app.state.guard.token
        listed = client.get("/api/circles")
        assert listed.status_code == 200
        assert listed.json()["admission_mode"] == "circle"
        created = client.post("/api/circles", json={"name": "Familia"})
        assert created.status_code == 200, created.text
        circle = created.json()
        invited = client.post(f"/api/circles/{circle['circle_id']}/invite",
                              json={"endpoints": ["127.0.0.1:9765"]})
        assert invited.status_code == 200, invited.text
        body = invited.json()
        assert body["code"].startswith("SWC1.")
        assert body["qr_svg"].startswith("<svg")
        assert client.post("/api/circles/notice/ack").status_code == 200

