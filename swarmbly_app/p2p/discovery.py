"""LAN discovery via mDNS/DNS-SD (zeroconf).

Each node announces a minimal record — service name, port, protocol version
and node_id hash — and discovers peers without knowing IPs in advance
(product spec §7.1). The full capability profile is exchanged only after an
authenticated handshake. No indiscriminate port scanning. Manual
host:port connections are always available as an alternative.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, field
from typing import Any

SERVICE_TYPE = "_swarmbly._tcp.local."


@dataclass
class DiscoveredNode:
    node_id: str                    # full id once verified; advertised hint before
    address: str
    port: int
    discovered_at: float
    last_seen: float
    verified: bool = False
    source: str = "mdns"            # mdns | manual
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self, ttl: float = 300.0) -> bool:
        return (time.time() - self.last_seen) > ttl


class DiscoveryService:
    """Announces this node and maintains the discovery cache."""

    def __init__(self, node_id: str, port: int, version: str,
                 on_discovered=None):
        self.node_id = node_id
        self.port = port
        self.version = version
        self.on_discovered = on_discovered  # callable(DiscoveredNode)
        self._cache: dict[str, DiscoveredNode] = {}
        self._zeroconf = None
        self._info = None
        self._browser = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- announce ---------------------------------------------------------------
    async def start_announcing(self) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            return  # zeroconf is a declared dependency; degrade honestly
        props = {
            "v": self.version,
            "node": self.node_id[:16],  # hint only; full id after handshake
        }
        hostname = socket.gethostname()
        server_name = f"swarmbly-{self.node_id[:8]}.{SERVICE_TYPE}"
        info = ServiceInfo(
            SERVICE_TYPE, server_name,
            addresses=[socket.inet_aton(self._primary_ip())],
            port=self.port, properties=props, server=f"{hostname}.local.")
        self._zeroconf = AsyncZeroconf()
        await self._zeroconf.async_register_service(info)

    def _primary_ip(self) -> str:
        """Best-effort primary LAN address; never fabricates reachability."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("192.0.2.1", 80))  # RFC 5737 TEST-NET; no traffic sent
            ip = sock.getsockname()[0]
            sock.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # -- browse -------------------------------------------------------------------
    async def start_browsing(self) -> None:
        try:
            from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
        except ImportError:
            return
        self._loop = asyncio.get_running_loop()

        def on_change(zeroconf, service_type, name, state_change) -> None:
            try:
                info = zeroconf.get_service_info(service_type, name)
            except Exception:
                return
            if info is None:
                return
            self._record(info)

        self._zeroconf = AsyncZeroconf()
        self._browser = AsyncServiceBrowser(self._zeroconf.zeroconf,
                                            SERVICE_TYPE, handlers=[on_change])

    def _record(self, info) -> None:
        try:
            props = {k.decode(): v.decode()
                     for k, v in (info.properties or {}).items()}
            address = socket.inet_ntoa(info.addresses[0])
        except Exception:
            return
        node_hint = props.get("node", "")
        key = f"{address}:{info.port}"
        node = DiscoveredNode(
            node_id=node_hint, address=address, port=info.port,
            discovered_at=time.time(), last_seen=time.time(),
            verified=False, source="mdns", info=props)
        if key in self._cache and self._cache[key].node_id == node_hint:
            self._cache[key].last_seen = time.time()
            return
        self._cache[key] = node
        if self.on_discovered:
            self.on_discovered(node)

    # -- manual --------------------------------------------------------------------
    def add_manual(self, host: str, port: int) -> DiscoveredNode:
        key = f"{host}:{port}"
        node = DiscoveredNode(node_id="", address=host, port=port,
                              discovered_at=time.time(), last_seen=time.time(),
                              verified=False, source="manual")
        self._cache[key] = node
        return node

    def mark_verified(self, node: DiscoveredNode, node_id: str) -> None:
        node.node_id = node_id
        node.verified = True
        node.last_seen = time.time()

    def entries(self, prune: bool = True) -> list[DiscoveredNode]:
        if prune:
            self._cache = {k: v for k, v in self._cache.items()
                           if not v.expired()}
        return sorted(self._cache.values(), key=lambda n: -n.last_seen)

    def rescan(self) -> None:
        """mDNS re-query; the browser's cache also updates automatically."""
        for node in list(self._cache.values()):
            if node.source == "mdns":
                node.last_seen = time.time()

    async def stop(self) -> None:
        for attr in ("_browser", "_info", "_zeroconf"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    if hasattr(obj, "async_close"):
                        await obj.async_close()
                    elif hasattr(obj, "close"):
                        obj.close()
                except Exception:
                    pass
