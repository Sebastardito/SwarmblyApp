"""Handshake tests: happy path plus replay and signature attacks."""

from __future__ import annotations

import base64

import pytest

from swarmbly_app.identity import IdentityManager
from swarmbly_app.p2p.handshake import Handshake, validate_advertisement
from swarmbly_app.p2p.messages import WireError

ADV_A = {"node_id": "nodeA", "models": [{"family": "llama", "version": "3b"}],
         "policy": {"kinds": ["generate"]}, "resources": {}, "capabilities": {}}
ADV_B = {"node_id": "nodeB", "models": [{"family": "qwen", "version": "3b"}],
         "policy": {"kinds": ["generate"]}, "resources": {}, "capabilities": {}}


@pytest.fixture()
def pair(tmp_path):
    a = IdentityManager(tmp_path / "a" / "node_key")
    b = IdentityManager(tmp_path / "b" / "node_key")
    return Handshake(a, ADV_A), Handshake(b, ADV_B), a, b


class TestHandshake:
    def test_full_exchange(self, pair):
        initiator, responder, ida, idb = pair
        hello, nonce = initiator.build_hello()
        ack_message, peer_nonce = responder.build_hello_ack(hello)
        result = initiator.verify_ack(ack_message, nonce)
        assert result.node_id == idb.load_or_create().node_id
        assert result.advertisement == ADV_B
        final = initiator.build_final_ack(result.node_id, peer_nonce)
        # The responder expects the *initiator's* signed final ack.
        confirmed = responder.verify_final_ack(
            final, ida.load_or_create().node_id, _nonce(ack_message["nonce"]))
        assert confirmed.node_id == ida.load_or_create().node_id

    def test_replay_old_ack_rejected(self, pair):
        initiator, responder, ida, idb = pair
        hello, nonce = initiator.build_hello()
        ack_message, _ = responder.build_hello_ack(hello)
        # A second handshake attempt must not be confirmable with the old ack.
        hello2, nonce2 = initiator.build_hello()
        with pytest.raises(WireError):
            initiator.verify_ack(ack_message, nonce2)

    def test_tampered_ack_rejected(self, pair):
        initiator, responder, ida, idb = pair
        hello, nonce = initiator.build_hello()
        ack_message, _ = responder.build_hello_ack(hello)
        ack_message["advertisement"] = {"node_id": "attacker"}
        with pytest.raises(WireError):
            initiator.verify_ack(ack_message, nonce)

    def test_forged_signature_rejected(self, pair):
        initiator, responder, ida, idb = pair
        hello, nonce = initiator.build_hello()
        ack_message, peer_nonce = responder.build_hello_ack(hello)
        # Replace the responder's signature with the initiator's own.
        unsigned = {k: v for k, v in ack_message.items() if k != "sig"}
        from swarmbly_app.p2p.messages import canonical_bytes
        sig = ida.sign(canonical_bytes(unsigned))
        ack_message["sig"] = _b64(sig)
        with pytest.raises(WireError):
            initiator.verify_ack(ack_message, nonce)

    def test_short_nonce_rejected(self, pair):
        initiator, responder, ida, idb = pair
        hello, _ = initiator.build_hello()
        hello["nonce"] = _b64(b"short")
        with pytest.raises(WireError):
            responder.build_hello_ack(hello)


class TestAdvertisement:
    def test_valid(self):
        assert validate_advertisement(ADV_A) == []

    def test_missing_node_id(self):
        problems = validate_advertisement({"models": []})
        assert any("node_id" in p for p in problems)

    def test_model_without_family(self):
        problems = validate_advertisement(
            {"node_id": "x", "models": [{"version": "1"}]})
        assert any("family" in p for p in problems)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _nonce(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
