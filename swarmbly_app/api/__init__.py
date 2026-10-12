"""FastAPI application: REST routes + WebSocket events + static web UI."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..state import AppState

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


def create_app(state: AppState) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The WebSocket bridge lives on this loop; chat/P2P publish from other
        # threads, so capture the loop for run_coroutine_threadsafe dispatch.
        state.bus.set_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="Swarmbly App", version="0.1.0",
                  docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=lifespan)
    app.state.swarmbly = state
    state.bus.subscribe_async(_on_event_factory(app))

    # ---- health / system ------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        return state.health()

    @app.get("/api/system")
    def system() -> dict:
        return state.system_report()

    @app.get("/api/identity")
    def identity() -> dict:
        return {"node_id": state.identity.node_id,
                "short_id": state.identity.short_id(12)}

    # ---- models ----------------------------------------------------------------
    @app.get("/api/models")
    def models() -> dict:
        cfg = state.config.all()
        model_cfg = cfg["model"]
        infos = state.model_manager.detect_cached(
            model_cfg.get("backend", "auto"), model_cfg.get("backend_url", ""))
        hardware = state.system_report()
        return {
            "backends": [i.to_dict() for i in infos],
            "recommendations": state.model_manager.recommend(hardware),
            "configured": {
                "backend": model_cfg.get("backend", "auto"),
                "url": model_cfg.get("backend_url", ""),
                "model": model_cfg.get("model_name", ""),
            },
        }

    # ---- config -----------------------------------------------------------------
    @app.get("/api/config")
    def get_config() -> dict:
        return state.config.all()

    @app.put("/api/config")
    def put_config(body: dict[str, Any]) -> dict:
        try:
            return state.config.update(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/reset")
    def reset_config(body: dict[str, Any] | None = None) -> dict:
        section = (body or {}).get("section")
        state.config.reset(section)
        return state.config.all()

    # ---- conversations -----------------------------------------------------------
    @app.get("/api/conversations")
    def list_conversations() -> list[dict]:
        return state.chat.list_conversations()

    @app.post("/api/conversations")
    def create_conversation(body: dict[str, Any] | None = None) -> dict:
        body = body or {}
        return state.chat.create_conversation(
            title=body.get("title", ""),
            mode=body.get("mode", ""),
            model=body.get("model", ""))

    @app.get("/api/conversations/{conv_id}")
    def get_conversation(conv_id: str) -> dict:
        conv = state.chat.get_conversation(conv_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return conv

    @app.get("/api/conversations/{conv_id}/messages")
    def get_messages(conv_id: str) -> list[dict]:
        if state.chat.get_conversation(conv_id) is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return state.chat.get_messages(conv_id)

    @app.delete("/api/conversations/{conv_id}")
    def delete_conversation(conv_id: str) -> dict:
        state.chat.delete_conversation(conv_id)
        return {"deleted": conv_id}

    @app.post("/api/conversations/{conv_id}/messages", status_code=202)
    def send_message(conv_id: str, body: dict[str, Any]) -> dict:
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="empty message")
        try:
            user_msg, assistant_msg = state.chat.send(
                conv_id, text,
                mode=body.get("mode") or None,
                model=body.get("model") or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"user_message": user_msg, "assistant_message": assistant_msg}

    @app.post("/api/conversations/{conv_id}/messages/{message_id}/retry")
    def retry_message(conv_id: str, message_id: str) -> dict:
        result = state.chat.retry(conv_id, message_id)
        if result is None:
            raise HTTPException(status_code=400, detail="nothing to retry")
        user_msg, assistant_msg = result
        return {"user_message": user_msg, "assistant_message": assistant_msg}

    @app.post("/api/requests/{request_id}/stop")
    def stop_request(request_id: str) -> dict:
        stopped = state.chat.interrupt(request_id)
        return {"stopped": stopped}

    @app.post("/api/requests/_stop_last")
    def stop_last_request() -> dict:
        active = state.chat.active_requests()
        if not active:
            return {"stopped": False}
        last = active[-1]["request_id"]
        return {"stopped": state.chat.interrupt(last), "request_id": last}

    @app.get("/api/conversations/{conv_id}/export")
    def export_conversation(conv_id: str, format: str = "markdown") -> Any:
        if format not in ("json", "markdown", "html"):
            raise HTTPException(status_code=400, detail="format must be json|markdown|html")
        try:
            content = state.chat.export(conv_id, fmt=format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media = {"json": "application/json", "markdown": "text/markdown",
                 "html": "text/html"}[format]
        if format == "json":
            return JSONResponse(content=json.loads(content))
        return Response(
            content=content, media_type=media,
            headers={"Content-Disposition":
                     f'attachment; filename="conversation-{conv_id}.{format if format != "markdown" else "md"}"'})

    # ---- LCE ----------------------------------------------------------------------
    @app.get("/api/lce/status")
    def lce_status() -> dict:
        cfg = state.config.all()["lce"]
        return state.lce.status(bool(cfg["enabled"]), cfg["level"])

    @app.post("/api/lce/activate")
    def lce_activate(body: dict[str, Any]) -> dict:
        level = str(body.get("level", "C0")).upper()
        if level not in ("C0", "C1"):
            raise HTTPException(status_code=400,
                                detail=f"level {level} not available in v0.1 (C0 active, C1 prepared)")
        try:
            status = state.lce.activate(level)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.config.update({"lce": {"enabled": True, "level": level}})
        return status

    @app.post("/api/lce/deactivate")
    def lce_deactivate() -> dict:
        state.config.update({"lce": {"enabled": False}})
        cfg = state.config.all()["lce"]
        return state.lce.status(False, cfg["level"])

    @app.get("/api/lce/sources")
    def lce_sources() -> list[dict]:
        return state.lce.list_sources()

    # ---- swarm (Phase 2) --------------------------------------------------------------
    @app.get("/api/swarm")
    def swarm_status() -> dict:
        cfg = state.config.all()["swarm"]
        return {
            **state.nodes.status(),
            "config": {k: cfg.get(k) for k in
                       ("mode", "lan_enabled", "internet_enabled",
                        "worker_enabled", "worker_allow_lan",
                        "worker_allow_internet", "worker_max_concurrent",
                        "worker_only_idle", "k_min", "k_max", "rho_target",
                        "n_fragments_max", "discovery_enabled")},
            "worker": state.worker.status() if state.worker else None,
        }

    @app.get("/api/swarm/nodes")
    def swarm_nodes() -> dict:
        return {"peers": state.nodes.status()["peers"],
                "discovered": state.nodes.status()["discovered"]}

    @app.post("/api/swarm/connect")
    def swarm_connect(body: dict) -> dict:
        host = str(body.get("host", "")).strip()
        try:
            port = int(body.get("port", 9765))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="port must be an integer")
        if not host:
            raise HTTPException(status_code=400, detail="host is required")
        state.nodes.connect_manual(host, port)
        return {"connecting": f"{host}:{port}"}

    @app.post("/api/swarm/rescan")
    def swarm_rescan() -> dict:
        if state.nodes.discovery is not None:
            state.nodes.discovery.rescan()
        return {"rescanned": True}

    @app.post("/api/swarm/worker")
    def swarm_worker(body: dict) -> dict:
        enabled = bool(body.get("enabled", False))
        state.config.update({"swarm": {"worker_enabled": enabled,
                                       "lan_enabled": enabled}})
        return state.worker.status() if state.worker else {"policy": {}}

    @app.get("/api/requests/{request_id}")
    def request_detail(request_id: str) -> dict:
        req = state.db.get_request(request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="request not found")
        return req

    @app.get("/api/requests/{request_id}/report")
    def request_report(request_id: str, format: str = "markdown") -> Any:
        req = state.db.get_request(request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="request not found")
        from ..reports import render_report
        content = render_report(req, fmt=format)
        media = {"json": "application/json", "markdown": "text/markdown",
                 "html": "text/html"}[format]
        return Response(content=content, media_type=media)

    @app.get("/api/monitor")
    def monitor_summary() -> dict:
        from ..monitor import swarm_health, contribution
        swarm = state.nodes.status()
        stats = state.db.get_stats(days=30)
        return {
            "health": swarm_health(swarm),
            "contribution": contribution(stats),
            "swarm": {
                "nodes_discovered": len(swarm["discovered"]),
                "nodes_connected": swarm["connected_count"],
                "workers_available": len(state.nodes.available_workers()),
                "uptime_s": int(__import__("time").time() - state.started_at),
            },
            "tasks": {"completed": sum(s["tasks_requested"] for s in stats),
                      "served": sum(s["tasks_served"] for s in stats)},
        }

    # ---- websocket -----------------------------------------------------------------
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        state.bus.set_loop(asyncio.get_running_loop())
        await ws.accept()
        hub = getattr(app.state, "ws_hub", None)
        if hub is not None:
            await hub.handle(ws)

    # ---- static web UI ---------------------------------------------------------------
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


class WsHub:
    """Broadcasts bus events to every connected WebSocket client."""

    def __init__(self):
        self._clients: list[WebSocket] = []

    async def handle(self, ws: WebSocket) -> None:
        self._clients.append(ws)
        try:
            while True:
                await ws.receive_text()  # keep-alive; client messages ignored for now
        except WebSocketDisconnect:
            pass
        finally:
            if ws in self._clients:
                self._clients.remove(ws)

    async def broadcast(self, event: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)


def _on_event_factory(app: FastAPI):
    """Attach a bus→WS bridge; hub is created lazily on first connection."""
    hub = WsHub()
    app.state.ws_hub = hub

    async def _on_event(event: dict) -> None:
        await hub.broadcast(event)

    return _on_event
