"""Handshake (SPEC-guided, 8 steps of the product spec §7.3).

Steps 1 (endpoint discovery) and 2 (encrypted channel) live in discovery.py
and transport.py. This module implements steps 3–8 on top of the TLS channel:

  3. identity authentication (Ed25519 over the transcript)
  4. version negotiation (MAJOR checked in the codec)
  5. capability exchange (SPEC §12 advertisement)
  6. compatibility check
  7. participation policy application
  8. connection state confirmation

An unknown node is never automatically authorized for anything: a completed
handshake only records an *authenticated* peer; the worker role applies its
own participation policies before accepting any task.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from ..identity import IdentityManager
from .messages import canonical_bytes, hello, hello_ack, verify_signed, WireError


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class HandshakeResult:
    node_id: str
    advertisement: dict[str, Any]
    version: str
    inbound: bool


class Handshake:
    def __init__(self, identity: IdentityManager, advertisement: dict[str, Any]):
        self.identity = identity
        self.advertisement = advertisement

    # -- initiator side --------------------------------------------------------
    def build_hello(self) -> tuple[dict[str, Any], bytes]:
        nonce = os.urandom(16)
        ident = self.identity.load_or_create()
        return hello(ident.node_id, nonce, self.advertisement), nonce

    def verify_ack(self, ack_message: dict[str, Any], my_nonce: bytes) -> HandshakeResult:
        if ack_message.get("type") != "hello_ack":
            raise WireError("expected hello_ack")
        peer_id = str(ack_message.get("node_id", ""))
        if not peer_id:
            raise WireError("hello_ack missing node_id")
        # Replay protection: the ack must echo our nonce.
        if ack_message.get("peer_nonce") != _b64(my_nonce):
            raise WireError("hello_ack nonce mismatch (possible replay)")
        if not verify_over_fields(peer_id, ack_message,
                                  ("v", "node_id", "peer_nonce", "nonce",
                                   "advertisement")):
            raise WireError("hello_ack signature invalid")
        return HandshakeResult(
            node_id=peer_id,
            advertisement=ack_message.get("advertisement") or {},
            version=str(ack_message.get("v", "")), inbound=False)

    def build_final_ack(self, peer_id: str, peer_nonce: bytes) -> dict[str, Any]:
        ident = self.identity.load_or_create()
        unsigned = {"v": "0.2", "node_id": ident.node_id, "nonce": _b64(peer_nonce)}
        sig = self.identity.sign(canonical_bytes(unsigned))
        from .messages import ack as ack_msg
        return ack_msg(ident.node_id, peer_nonce, sig)

    # -- responder side ---------------------------------------------------------
    def build_hello_ack(self, hello_message: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """Verify the hello and produce the signed hello_ack (steps 3–6)."""
        peer_id = str(hello_message.get("node_id", ""))
        if not peer_id:
            raise WireError("hello missing node_id")
        nonce_field = hello_message.get("nonce", "")
        peer_nonce = _b64d(str(nonce_field)) if nonce_field else b""
        if len(peer_nonce) != 16:
            raise WireError("hello nonce malformed")
        own_nonce = os.urandom(16)
        ident = self.identity.load_or_create()
        # The signature covers the advertised capabilities too: a tampered
        # advertisement must fail authentication, not pass with a valid sig.
        unsigned = {"v": "0.2", "node_id": ident.node_id,
                    "peer_nonce": _b64(peer_nonce), "nonce": _b64(own_nonce),
                    "advertisement": self.advertisement}
        sig = self.identity.sign(canonical_bytes(unsigned))
        message = hello_ack(ident.node_id, peer_nonce, own_nonce,
                            self.advertisement, sig)
        # The caller must echo OUR nonce in the final ack: return own_nonce.
        return message, own_nonce

    def verify_final_ack(self, ack_message: dict[str, Any],
                         expected_peer_id: str, own_nonce: bytes) -> HandshakeResult:
        if ack_message.get("type") != "ack":
            raise WireError("expected ack")
        if ack_message.get("node_id") != expected_peer_id:
            raise WireError("ack node_id mismatch")
        if ack_message.get("nonce") != _b64(own_nonce):
            raise WireError("ack nonce mismatch (possible replay)")
        if not verify_over_fields(expected_peer_id, ack_message,
                                  ("v", "node_id", "nonce")):
            raise WireError("ack signature invalid")
        return HandshakeResult(node_id=expected_peer_id,
                               advertisement={}, version=str(ack_message.get("v", "")),
                               inbound=True)


def verify_over_fields(node_id: str, message: dict[str, Any],
                       fields: tuple[str, ...]) -> bool:
    """Verify a signature over an explicit subset of message fields."""
    sig = message.get("sig")
    if not isinstance(sig, str):
        return False
    subset = {field: message[field] for field in fields if field in message}
    return _verify_subset(node_id, subset, sig)


def _verify_subset(node_id: str, subset: dict[str, Any], sig: str) -> bool:
    from ..identity import b64url_decode, verify_signature
    try:
        raw_sig = b64url_decode(sig)
    except Exception:
        return False
    return verify_signature(node_id, canonical_bytes(subset), raw_sig)


def validate_advertisement(adv: dict[str, Any]) -> list[str]:
    """Compatibility check (step 6): structural validation only.

    Returns a list of problems; empty means structurally acceptable.
    A self-declared ``swarm_id`` confers nothing (SPEC §12).
    """
    problems: list[str] = []
    if not isinstance(adv, dict):
        return ["advertisement must be an object"]
    node_id = adv.get("node_id", "")
    if not isinstance(node_id, str) or not node_id:
        problems.append("missing node_id")
    models = adv.get("models", [])
    if not isinstance(models, list):
        problems.append("models must be a list")
    for model in models:
        if not isinstance(model, dict) or "family" not in model:
            problems.append("each model entry needs a family")
    policy = adv.get("policy")
    if policy is not None and not isinstance(policy, dict):
        problems.append("policy must be an object")
    return problems
