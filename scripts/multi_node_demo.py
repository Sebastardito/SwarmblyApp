#!/usr/bin/env python3
"""Multi-node demo: N worker nodes + 1 orchestrator on one machine.

Spawns N independent Swarmbly nodes (distinct identities, distinct models),
authenticates them with the orchestrator (TLS 1.3 + Ed25519 handshake), and
runs one real distributed request across them — optionally with k>1 so each
fragment is served by several different model families and resolved by
multiple-alignment consensus. Exercises exactly what runs on N physical
machines, except the ethernet/Wi-Fi hop (loopback here).

Usage:
    python scripts/multi_node_demo.py --nodes 4 --k 1   # 5 nodes total
    python scripts/multi_node_demo.py --nodes 1         # 2 nodes total
    python scripts/multi_node_demo.py --nodes 4 --k 2   # cross-family consensus

Models must exist in Ollama (never downloaded here).
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

DEFAULT_MODELS = ["llama3.2:3b", "qwen2.5:3b", "phi3.5:3.8b", "granite3.1-dense:2b"]
ORCH_MODEL = "gemma2:2b"
PROMPT = (
    "Extract one key fact per item from the following list of five items: "
    "apples, bridges, comets, drums, electrons. List 5 bullet points, one per "
    "item, separately."
)
WORKER_BASE_PORT = 9800
ORCH_PORT = 9899


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=4,
                        help="number of worker nodes (default 4; 1 == two-PC test)")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="comma-separated worker models")
    parser.add_argument("--orchestrator-model", default=ORCH_MODEL)
    parser.add_argument("--k", type=int, default=1, help="redundancy (replicas)")
    parser.add_argument("--prompt", default=PROMPT)
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    n = args.nodes
    if n < 1:
        n = 1
    if len(models) < n:
        models = (models * ((n // len(models)) + 1))[:n]
    print(f"[swarm] {n} worker(s) + 1 orchestrator = {n + 1} nodes, k={args.k}")

    base = Path(tempfile.mkdtemp(prefix="swarmbly-multi-"))
    states = []

    # ---- worker nodes ---------------------------------------------------------
    for i in range(n):
        st = AppState(str(base / f"w{i}"))
        st.config.update({
            "swarm": {"worker_enabled": True, "lan_enabled": True,
                      "p2p_port": WORKER_BASE_PORT + i,
                      "worker_max_tokens_per_task": 800},
            "model": {"model_name": models[i]},
        })
        st.start_p2p()
        states.append(st)

    # ---- orchestrator ----------------------------------------------------------
    orch = AppState(str(base / "orchestrator"))
    orch.config.update({
        "swarm": {"p2p_port": ORCH_PORT, "k_min": args.k, "k_max": max(args.k, 2)},
        "privacy": {"tier": "GLOBAL"},
        "model": {"model_name": args.orchestrator_model, "embedder": "server"},
    })
    orch.start_p2p()
    states.append(orch)

    time.sleep(1.2)

    print(f"\n[nodes] worker identities + models:")
    for i, st in enumerate(states[:n]):
        print(f"  w{i}  {st.identity.node_id[:12]}  {models[i]}")
    print(f"  orch {orch.identity.node_id[:12]}  {args.orchestrator_model}")

    # ---- connect orchestrator -> every worker -----------------------------------
    for i in range(n):
        orch.nodes.connect_manual("127.0.0.1", WORKER_BASE_PORT + i)
    deadline = time.time() + 15
    while time.time() < deadline:
        if orch.nodes.status()["connected_count"] >= n:
            break
        time.sleep(0.2)
    connected = orch.nodes.status()["connected_count"]
    print(f"\n[handshake] authenticated connections: {connected}/{n}")
    if connected < n:
        print("[handshake] FAILED to connect all workers")
        for st in states:
            st.stop()
        return 1

    # ---- run the distributed request ---------------------------------------------
    conv = orch.chat.create_conversation(title="multi-node", mode="lan",
                                         model=args.orchestrator_model)
    started = time.time()
    orch.chat.send(conv["id"], args.prompt, mode="lan", run_async=False)
    elapsed = time.time() - started
    final = orch.chat.get_messages(conv["id"])[-1]

    print(f"\n=== PIPELINE (elapsed {elapsed:.1f} s) ===")
    for stage in final.get("stages", []):
        extra = "  ".join(f"{k}={v}" for k, v in stage.items()
                          if k not in ("stage", "status"))
        print(f"  {stage['stage']:28} {stage['status']:15} {extra}")

    swarm = final["meta"].get("swarm", {})
    print("\n=== SPEC §19 metadata ===")
    keys = ("n_tasks", "rho_target", "rho_achieved", "rho_floor", "rho_reachable",
            "consensus", "consensus_waived_reason", "tau_sem")
    print(json.dumps({k: swarm[k] for k in keys if k in swarm}, indent=2))
    if swarm.get("consensus"):
        c = swarm["consensus"]
        print(f"\n=== CONSENSUS (k={c.get('k')}) ===")
        print("  families:", c.get("families"))
        print("  mean_agreement:", c.get("mean_agreement"))
        print("  thresholds:", c.get("alpha_high"), "/", c.get("alpha_low"),
              "(", c.get("thresholds_source"), ")")
        labels = [u["label"] for u in c.get("units", [])]
        print("  unit labels:", labels)

    # ---- prove each worker actually served tasks --------------------------------
    print("\n=== WORKER CONTRIBUTION ===")
    for i, st in enumerate(states[:n]):
        served = st.worker.status()["tasks_served_today"]
        print(f"  w{i} ({models[i]}): served {served} task(s)")

    print("\n=== FINAL RESPONSE ===")
    print(final["content"][:1500])

    for st in states:
        st.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
