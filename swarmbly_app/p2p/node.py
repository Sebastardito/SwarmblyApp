"""Node manager: P2P lifecycle, peer registry, message routing.

Runs its own asyncio event loop in a background thread so the synchronous
chat/engine threads can dispatch via ``run_coroutine_threadsafe``. Ties
together discovery (mDNS), transport (TLS 1.3) and the Ed25519 handshake.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..db import Database
from ..events import EventBus
from ..identity import IdentityManager
from .discovery import DiscoveredNode, DiscoveryService
from .handshake import Handshake, HandshakeResult, validate_advertisement
from .messages import (WIRE_VERSION, error)
from .transport import (PeerSession, TLSServer, dial, generate_cert,
                        read_frame_with_timeout, write_frame)

DEFAULT_P2P_PORT = 9765


@dataclass
class Peer:
    node_id: str
    address: str
    port: int
    advertisement: dict[str, Any] = field(default_factory=dict)
    connected: bool = False
    verified: bool = False
    source: str = "manual"           # mdns | manual
    last_seen: float = field(default_factory=time.time)
    session: PeerSession | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "short_id": self.node_id[:12],
            "address": self.address,
            "port": self.port,
            "connected": self.connected,
            "verified": self.verified,
            "source": self.source,
            "models": self.advertisement.get("models", []),
            "policy": self.advertisement.get("policy", {}),
            "resources": self.advertisement.get("resources", {}),
            "last_seen": self.last_seen,
        }


class NodeManager:
    def __init__(self, identity: IdentityManager, config: Config, db: Database,
                 bus: EventBus, advertisement_builder, dirs=None):
        self.identity_manager = identity
        self.config = config
        self.db = db
        self.bus = bus
        self.build_advertisement = advertisement_builder
        self._dirs = dirs
        self.handshake = Handshake(identity, {})  # advertisement refreshed per use
        self.peers: dict[str, Peer] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._read_tasks: set = set()
        self.server: TLSServer | None = None
        self.discovery: DiscoveryService | None = None
        self._task_handler = None  # worker handler, injected
        self._started = False

    # -- lifecycle ---------------------------------------------------------------
    def start(self, task_handler=None) -> None:
        if self._started:
            return
        self._started = True
        self._task_handler = task_handler
        self._thread = threading.Thread(target=self._run_loop,
                                        name="swarmbly-p2p", daemon=True)
        self._thread.start()
        # wait until the loop is ready
        deadline = time.time() + 10
        while self._loop is None and time.time() < deadline:
            time.sleep(0.02)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_start())
            self._loop.run_forever()
        except RuntimeError:
            pass  # loop stopped during shutdown

    async def _async_start(self) -> None:
        cfg = self.config.all()["swarm"]
        port = cfg.get("p2p_port") or DEFAULT_P2P_PORT
        host = cfg.get("p2p_host") or "0.0.0.0"
        cert_dir = self._data_dirs().cache / "tls"
        generate_cert(cert_dir / "node.crt", cert_dir / "node.key")
        self.server = TLSServer(host, port, cert_dir / "node.crt",
                                cert_dir / "node.key", self._on_session)
        await self.server.start()
        ident = self.identity_manager.load_or_create()
        self.discovery = DiscoveryService(ident.node_id, port, WIRE_VERSION,
                                          on_discovered=self._on_discovered)
        if cfg.get("lan_enabled") or cfg.get("discovery_enabled"):
            await self.discovery.start_announcing()
            await self.discovery.start_browsing()
        self.bus.publish("node.listening", port=port)

    def _data_dirs(self):
        """The app's data directory (injected) or the platform default."""
        if self._dirs is not None:
            return self._dirs
        from ..paths import DataDirs
        return DataDirs(self.config.get("data_dir") or None)

    def stop(self) -> None:
        """Graceful shutdown: close the server and sessions, then stop the loop.

        The wait makes teardown deterministic so a following process (or test)
        can rebind the same port immediately.
        """
        self._started = False
        if self._loop is None:
            return

        async def _shutdown() -> None:
            if self.server is not None:
                await self.server.stop()
            if self.discovery is not None:
                await self.discovery.stop()
            for task in list(self._read_tasks):
                task.cancel()
            for peer in list(self.peers.values()):
                if peer.session is not None:
                    peer.session.close()
            self._loop.stop()

        try:
            future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            future.result(timeout=5)
        except Exception:
            pass

    # -- advertisement --------------------------------------------------------------
    def _advertisement(self) -> dict[str, Any]:
        adv = self.build_advertisement()
        adv["v"] = WIRE_VERSION
        return adv

    # -- discovery callbacks (may arrive on the zeroconf thread) ----------------------
    def _on_discovered(self, node: DiscoveredNode) -> None:
        self.bus.publish("node.discovered", address=node.address, port=node.port,
                         source=node.source)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._connect(node.address, node.port)))

    # -- connections -----------------------------------------------------------------
    async def _connect(self, host: str, port: int) -> Peer | None:
        ident = self.identity_manager.load_or_create()
        if host in ("127.0.0.1", "localhost") and port == (self.config.all()["swarm"].get("p2p_port") or DEFAULT_P2P_PORT):
            return None  # never connect to ourselves
        self.handshake.advertisement = self._advertisement()
        hello_msg, nonce = self.handshake.build_hello()
        try:
            session, ack_message = await dial(host, port, hello_msg)
        except Exception:
            self.bus.publish("node.handshake_failed", address=host, port=port)
            return None
        try:
            result = self.handshake.verify_ack(ack_message, nonce)
            final_ack = self.handshake.build_final_ack(
                result.node_id, _nonce_bytes(ack_message.get("nonce", "")))
            await write_frame(session.writer, final_ack)
        except Exception:
            session.close()
            self.bus.publish("node.handshake_failed", address=host, port=port,
                             reason="signature")
            return None
        await self._register(result, session, inbound=False)
        return self.peers.get(result.node_id)

    def connect_manual(self, host: str, port: int) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._connect(host, port), self._loop)

    # -- inbound session (called by TLSServer on the loop thread) ----------------------
    async def _on_session(self, session: PeerSession,
                          hello_message: dict[str, Any]) -> None:
        try:
            # The hello frame was already consumed by the transport; continue
            # the handshake from hello_ack (steps 3–8). Sign OUR advertisement.
            self.handshake.advertisement = self._advertisement()
            ack_message, _ = self.handshake.build_hello_ack(hello_message)
            await write_frame(session.writer, ack_message)
            final_ack = await read_frame_with_timeout(session.reader, 10.0)
            result = self.handshake.verify_final_ack(
                final_ack, str(hello_message.get("node_id", "")),
                _nonce_bytes(ack_message.get("nonce", "")))
            peer_adv = hello_message.get("advertisement") or {}
            result.advertisement = peer_adv
            await self._register(result, session, inbound=True)
        except Exception as exc:
            session.close()
            self.bus.publish("node.handshake_failed", reason=str(exc)[:120])

    async def _register(self, result: HandshakeResult | None,
                        session: PeerSession, inbound: bool) -> None:
        if result is not None:
            node_id = result.node_id
            advertisement = result.advertisement
        else:
            node_id = session.node_id
            advertisement = session.advertisement
        problems = validate_advertisement(advertisement)
        if problems:
            session.close()
            self.bus.publish("node.rejected", node_id=node_id[:12],
                             reason="; ".join(problems[:2]))
            return
        peer = self.peers.get(node_id)
        if peer is None:
            peer = Peer(node_id=node_id, address=session.address,
                        port=session.port, advertisement=advertisement,
                        verified=True, source="mdns" if not inbound else "mdns")
            self.peers[node_id] = peer
        peer.address = session.address
        peer.port = session.port
        peer.advertisement = advertisement
        peer.connected = True
        peer.verified = True
        peer.last_seen = time.time()
        peer.session = session
        self.db.upsert_node(node_id, session.address, session.port,
                            verified=True, profile=advertisement)
        self.bus.publish("node.connected", node_id=node_id,
                         short_id=node_id[:12], address=session.address)
        task = asyncio.ensure_future(self._read_loop(session, node_id))
        self._read_tasks.add(task)
        task.add_done_callback(self._read_tasks.discard)

    async def _read_loop(self, session: PeerSession, node_id: str) -> None:
        from .transport import read_frame
        try:
            while True:
                message = await read_frame(session.reader)
                await self._dispatch(node_id, session, message)
        except Exception:
            pass
        finally:
            peer = self.peers.get(node_id)
            if peer and peer.session is session:
                peer.connected = False
                peer.session = None
                self.bus.publish("node.disconnected", node_id=node_id,
                                 short_id=node_id[:12])
            session.close()

    async def _dispatch(self, node_id: str, session: PeerSession,
                        message: dict[str, Any]) -> None:
        mtype = message.get("type")
        if mtype == "task":
            await self._handle_task(node_id, session, message)
        elif mtype == "result":
            attempt_id = str(message.get("attempt_id", ""))
            with self._pending_lock:
                future = self._pending.pop(attempt_id, None)
            if future is not None and not future.done():
                future.set_result(message)
        elif mtype == "error":
            attempt_id = str(message.get("attempt_id", ""))
            with self._pending_lock:
                future = self._pending.pop(attempt_id, None)
            if future is not None and not future.done():
                future.set_exception(
                    RuntimeError(f"{message.get('code')}: {message.get('detail')}"))
        elif mtype == "ping":
            await write_frame(session.writer,
                              {"v": WIRE_VERSION, "type": "pong",
                               "ts": time.time()})

    async def _handle_task(self, node_id: str, session: PeerSession,
                           message: dict[str, Any]) -> None:
        handler = self._task_handler
        if handler is None:
            await write_frame(session.writer, error(
                "E_POLICY", "worker role disabled", message.get("attempt_id")))
            return
        reply = await handler(node_id, message)
        await write_frame(session.writer, reply)

    # -- dispatch API (used by the DistributedBackend from other threads) -------------
    def dispatch(self, node_id: str, packet_message: dict[str, Any],
                 timeout_s: float = 120.0) -> dict[str, Any]:
        if self._loop is None:
            raise RuntimeError("P2P node not started")
        future = asyncio.run_coroutine_threadsafe(
            self._dispatch_async(node_id, packet_message, timeout_s), self._loop)
        return future.result(timeout=timeout_s + 10)

    async def _dispatch_async(self, node_id: str, packet_message: dict[str, Any],
                              timeout_s: float) -> dict[str, Any]:
        peer = self.peers.get(node_id)
        if peer is None or not peer.connected or peer.session is None:
            raise RuntimeError(f"node {node_id[:12]} not connected")
        attempt_id = str(packet_message.get("attempt_id", ""))
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        with self._pending_lock:
            self._pending[attempt_id] = future
        self.bus.publish("task.dispatched", node_id=node_id,
                         short_id=node_id[:12], attempt_id=attempt_id)
        try:
            await write_frame(peer.session.writer, packet_message)
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            with self._pending_lock:
                self._pending.pop(attempt_id, None)
            self.bus.publish("task.timeout", node_id=node_id,
                             short_id=node_id[:12], attempt_id=attempt_id)
            raise RuntimeError("worker timeout")
        finally:
            self.bus.publish("task.received_result", node_id=node_id,
                             short_id=node_id[:12], attempt_id=attempt_id)

    # -- introspection ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "port": self.config.all()["swarm"].get("p2p_port") or DEFAULT_P2P_PORT,
            "peers": [p.to_dict() for p in self.peers.values()],
            "discovered": [{"address": n.address, "port": n.port,
                            "node_hint": n.node_id[:16], "source": n.source,
                            "verified": n.verified}
                           for n in (self.discovery.entries() if self.discovery else [])],
            "connected_count": sum(1 for p in self.peers.values() if p.connected),
            "verified_count": sum(1 for p in self.peers.values() if p.verified),
        }

    def available_workers(self, kind: str = "generate") -> list[Peer]:
        out = []
        for peer in self.peers.values():
            if not peer.connected:
                continue
            kinds = peer.advertisement.get("policy", {}).get("kinds", [])
            if kinds and kind not in kinds:
                continue
            out.append(peer)
        return out


def _nonce_bytes(text: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
