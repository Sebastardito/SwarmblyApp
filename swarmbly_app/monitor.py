"""Swarm Monitor: health and contribution (user additions A and B).

Swarm Health is NOT an arbitrary score: it exposes independent, labelled
metrics (availability, family diversity, verified vs announced capacity,
latency where measured). Swarm Contribution aggregates what this node has
actually served and transferred — real counters, never estimates disguised as
measurements.
"""

from __future__ import annotations

from typing import Any


def swarm_health(swarm: dict[str, Any]) -> dict[str, Any]:
    """Independent health indicators for the current swarm view."""
    peers = swarm.get("peers", [])
    discovered = swarm.get("discovered", [])
    connected = [p for p in peers if p.get("connected")]
    verified = [p for p in peers if p.get("verified")]
    families: set[str] = set()
    announced_models = 0
    verified_models = 0
    for peer in peers:
        for model in peer.get("models", []):
            announced_models += 1
            family = model.get("family") or "unknown"
            families.add(family)
            if peer.get("verified"):
                verified_models += 1
    return {
        "availability": {
            "discovered": len(discovered),
            "connected": len(connected),
            "verified": len(verified),
            # announced ≠ reachable; only handshake-verified nodes count as usable
            "value": f"{len(verified)} verified / {len(discovered)} discovered",
            "source": "handshake-verified peers (mDNS + Ed25519)",
        },
        "model_diversity": {
            "families": sorted(families),
            "distinct_families": len(families),
            "value": f"{len(families)} model families",
            "source": "peer advertisements after authenticated handshake",
        },
        "capacity": {
            "announced_models": announced_models,
            "verified_models": verified_models,
            "value": f"{verified_models} verified / {announced_models} announced models",
            "source": "verified by handshake only, not by task completion",
        },
        "stability": {
            "value": "not yet measured (uptime of links arrives with Phase 2.1)",
            "source": "no simulated values",
        },
    }


def contribution(stats: list[dict[str, Any]]) -> dict[str, Any]:
    """What this node has contributed (worker role) and consumed (client)."""
    served = sum(s.get("tasks_served", 0) for s in stats)
    gen_ms = sum(s.get("gen_ms", 0) for s in stats)
    tokens_out = sum(s.get("tokens_out", 0) for s in stats)
    bytes_in = sum(s.get("bytes_in", 0) for s in stats)
    bytes_out = sum(s.get("bytes_out", 0) for s in stats)
    requested = sum(s.get("tasks_requested", 0) for s in stats)
    return {
        "tasks_served": served,
        "processing_time_ms": gen_ms,
        "tokens_generated": tokens_out,
        "bytes_transferred": {"in": bytes_in, "out": bytes_out},
        "tasks_requested": requested,
        "source": "local SQLite counters (measured)",
    }
