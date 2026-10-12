"""Processing reports (product spec §11): JSON / Markdown / HTML.

A report includes the request id, timing, mode/model, privacy classification,
router decision, plan size, ρ accounting, seams, coherence, verification
status, consensus (or its waiver), participating nodes, stage log and the
final response. Values are labelled measured / estimated / not available; no
personal or sensitive content is added to diagnostic reports by default.
"""

from __future__ import annotations

import json
import time
from typing import Any


def build_report(db, request_id: str) -> dict[str, Any]:
    req = db.get_request(request_id)
    if req is None:
        raise KeyError(f"unknown request {request_id}")
    assistant_meta: dict[str, Any] = {}
    stages: list[dict[str, Any]] = []
    final_text = ""
    if req.get("conversation_id"):
        messages = db.get_messages(req["conversation_id"])
        assistant = next(
            (m for m in reversed(messages)
             if m["role"] == "assistant"
             and (m["id"] == req.get("message_id") or True)), None)
        if assistant is not None:
            assistant_meta = assistant.get("meta") or {}
            stages = assistant.get("stages") or []
            final_text = assistant.get("content") or ""
    swarm = assistant_meta.get("swarm") or {}
    return {
        "request_id": request_id,
        "started_at": _iso(req["started_at"]),
        "finished_at": _iso(req["finished_at"]),
        "duration_ms": int((req["finished_at"] - req["started_at"]) * 1000)
        if req["finished_at"] else None,
        "mode": req["mode"],
        "model": req["model"],
        "status": req["status"],
        "privacy": {
            "tier": swarm.get("routing", {}).get("tier"),
            "classifier": swarm.get("routing", {}).get("classifier"),
        },
        "plan": {"n_tasks": swarm.get("n_tasks"),
                 "rho_target": swarm.get("rho_target"),
                 "rho_achieved": swarm.get("rho_achieved"),
                 "rho_floor": swarm.get("rho_floor"),
                 "rho_reachable": swarm.get("rho_reachable"),
                 "tau_sem": swarm.get("tau_sem"),
                 "tau_source": swarm.get("tau_source")},
        "assembly": {"seams": swarm.get("seams", []),
                     "coherence": swarm.get("coherence", {})},
        "verification": swarm.get("verification", {"commitments_checked": 0}),
        "consensus": swarm.get("consensus"),
        "consensus_waived_reason": swarm.get("consensus_waived_reason"),
        "nodes": swarm.get("nodes", []),
        "stages": stages,
        "final_response": final_text,
        "notes": {"honesty": [
            "Layer-1 verification commitments are not available (no normative "
            "construction, SPEC §21.1); result signatures were verified.",
            "Inter-model agreement is agreement, never a truth guarantee.",
            "tau_sem may be a documented placeholder until calibrated.",
        ]},
    }


def render_report(db, request_id: str, fmt: str = "markdown") -> str:
    data = build_report(db, request_id)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    if fmt == "html":
        import html as h
        rows = "".join(
            f"<tr><th>{h.escape(k)}</th><td>{h.escape(str(v))}</td></tr>"
            for k, v in _flat(data).items())
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>Swarmbly report {request_id}</title></head><body>"
                f"<h1>Processing report — {request_id}</h1>"
                f"<table border='1' cellpadding='6'>{rows}</table>"
                "<pre>" + h.escape(_stages_text(data["stages"])) + "</pre>"
                "</body></html>")
    return _markdown(data)


def _iso(ts: float | None) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _flat(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flat(value, name))
        elif isinstance(value, list):
            out[name] = json.dumps(value, ensure_ascii=False)[:500]
        elif value is not None:
            out[name] = str(value)
    return out


def _stages_text(stages: list[dict[str, Any]]) -> str:
    lines = []
    for stage in stages:
        lines.append(f"{stage['stage']:30} {stage['status']}")
    return "\n".join(lines)


def _markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# Swarmbly processing report — `{data['request_id']}`",
        "",
        f"- **Started:** {data['started_at']} · **Duration:** {data['duration_ms']} ms",
        f"- **Mode:** {data['mode']} · **Model:** {data['model'] or '-'} · **Status:** {data['status']}",
        "",
        "## Privacy",
        f"- Tier: `{data['privacy']['tier']}` (classifier: {data['privacy']['classifier']})",
        "",
        "## Plan & context budget (ρ)",
        f"- Tasks: {data['plan']['n_tasks']} · ρ target {data['plan']['rho_target']} → "
        f"achieved {data['plan']['rho_achieved']} (floor {data['plan']['rho_floor']}, "
        f"reachable {data['plan']['rho_reachable']})",
        f"- τ_sem: {data['plan']['tau_sem']} — {data['plan']['tau_source']}",
        "",
        "## Assembly & coherence",
        f"- Seams: {len(data['assembly']['seams'])} · Coherence: "
        f"{data['assembly']['coherence']}",
        "",
        "## Verification & consensus",
        f"- Verification: {data['verification']}",
        f"- Consensus: {data['consensus']} (waiver: {data['consensus_waived_reason']})",
        "",
        "## Nodes",
        ", ".join(n.get("node_id", "?") for n in data["nodes"]) or "-",
        "",
        "## Pipeline",
        "```",
        _stages_text(data["stages"]),
        "```",
        "",
        "## Final response",
        "",
        data["final_response"] or "",
        "",
        "> Honesty notes: verification commitments not available (no normative "
        "construction); agreement is not truth; τ may be a documented placeholder.",
    ]
    return "\n".join(lines)
