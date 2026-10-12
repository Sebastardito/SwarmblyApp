#!/usr/bin/env python3
"""Two-node demo: real distributed inference on one machine (reproducible).

Node B (worker) serves micro-tasks with its base model over TLS 1.3 + Ed25519;
node A (client/orchestrator) fragments a request, dispatches SPEC v0.2 packets,
assembles with its local model and prints the full pipeline plus the SPEC §19
metadata. Requires Ollama running with the two models (never downloaded here).

Usage:
    python scripts/two_nodes_demo.py \
        --worker-model llama3.2:3b --client-model gemma2:2b [--k 1]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarmbly_app.state import AppState  # noqa: E402

DEFAULT_PROMPT = (
    "Extract one key fact per item from the following list of five items: "
    "apples, bridges, comets, drums, electrons. List 5 bullet points, one per "
    "item, separately."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-model", default="llama3.2:3b")
    parser.add_argument("--client-model", default="gemma2:2b")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--k", type=int, default=1,
                        help="redundancy (replicas per micro-task)")
    args = parser.parse_args()

    base = Path(tempfile.mkdtemp(prefix="swarmbly-demo-"))
    state_b = AppState(str(base / "worker"))
    state_a = AppState(str(base / "client"))
    state_b.config.update({
        "swarm": {"worker_enabled": True, "lan_enabled": True,
                  "p2p_port": 9791},
        "model": {"model_name": args.worker_model}})
    state_a.config.update({
        "swarm": {"lan_enabled": True, "p2p_port": 9792, "k_min": args.k},
        "privacy": {"tier": "GLOBAL"},
        "model": {"model_name": args.client_model, "embedder": "server"}})

    state_a.start_p2p()
    state_b.start_p2p()
    time.sleep(1.2)
    state_a.nodes.connect_manual("127.0.0.1", 9791)
    deadline = time.time() + 10
    while time.time() < deadline and state_a.nodes.status()["connected_count"] < 1:
        time.sleep(0.2)
    connected = state_a.nodes.status()["connected_count"]
    print(f"[nodes] worker  {state_b.identity.node_id[:12]} "
          f"({args.worker_model})")
    print(f"[nodes] client  {state_a.identity.node_id[:12]} "
          f"({args.client_model})")
    print(f"[nodes] authenticated connections: {connected}")
    if connected < 1:
        print("[nodes] handshake FAILED — is port 9791 free?")
        return 1

    conv = state_a.chat.create_conversation(title="Demo", mode="lan",
                                            model=args.client_model)
    print(f"[demo]  dispatching: {args.prompt[:70]}…")
    started = time.time()
    state_a.chat.send(conv["id"], args.prompt, mode="lan", run_async=False)
    elapsed = time.time() - started
    messages = state_a.chat.get_messages(conv["id"])
    final = messages[-1]

    print(f"\n=== PIPELINE (elapsed {elapsed:.1f} s) ===")
    for stage in final.get("stages", []):
        extra = "  ".join(f"{k}={v}" for k, v in stage.items()
                          if k not in ("stage", "status"))
        print(f"  {stage['stage']:28} {stage['status']:15} {extra}")

    print("\n=== METADATA (SPEC §19 subset) ===")
    print(json.dumps(final["meta"].get("swarm", {}), indent=2,
                     ensure_ascii=False)[:2400])

    print("\n=== FINAL RESPONSE ===")
    print(final["content"])

    state_a.stop()
    state_b.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
