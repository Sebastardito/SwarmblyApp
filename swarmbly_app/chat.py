"""Chat engine: conversations, local inference with streaming, history, export.

Execution metadata (mode, model, timing, tokens, stages) is stored per message
so the monitor and the reports can always be reconstructed. Modes other than
``local`` arrive with the Phase 2 engine; the engine already records mode and
model per conversation as required.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .db import Database
from .events import EventBus
from .inference.base import BackendError, GenerationResult, Interrupted
from .inference.registry import BackendRegistry, IncompleteSettings

MAX_CONTEXT_MESSAGES = 12


@dataclass
class ActiveRequest:
    request_id: str
    conversation_id: str
    message_id: str
    mode: str = "local"
    model: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.time)


class ChatService:
    def __init__(self, db: Database, bus: EventBus,
                 registry: BackendRegistry, config_getter: Callable[[], dict[str, Any]],
                 orchestrator_getter: Callable[[], Any] | None = None):
        self.db = db
        self.bus = bus
        self.registry = registry
        self.config = config_getter
        self.orchestrator = orchestrator_getter  # distributed engine (Phase 2)
        self._active: dict[str, ActiveRequest] = {}
        self.report_sink: Callable[[str], None] | None = None  # set by AppState
        # LCE C1: local retrieval over the user's sources (set by AppState);
        # used only for answers produced on this device.
        self.retriever: Callable[..., list[dict[str, Any]]] | None = None
        self.retrieval_active: Callable[[], bool] = lambda: self.retriever is not None
        # P2e: the public provider for local answers (injectable for tests).
        self.public_provider: Any = None
        self.glossary: Callable[[str], str] | None = None
        self._lock = threading.Lock()

    # -- conversations -------------------------------------------------------
    def list_conversations(self) -> list[dict[str, Any]]:
        return self.db.list_conversations()

    def create_conversation(self, title: str = "", mode: str = "",
                            model: str = "") -> dict[str, Any]:
        cfg = self.config()
        return self.db.create_conversation(
            title=title or "New conversation",
            mode=mode or cfg["swarm"]["mode"] or "local",
            model=model or cfg["model"]["model_name"] or "")

    def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        return self.db.get_conversation(conv_id)

    def get_messages(self, conv_id: str) -> list[dict[str, Any]]:
        return self.db.get_messages(conv_id)

    def delete_conversation(self, conv_id: str) -> None:
        self.db.delete_conversation(conv_id)

    # -- sending -------------------------------------------------------------
    def send(self, conversation_id: str, text: str, *,
             mode: str | None = None, model: str | None = None,
             run_async: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        """Store the user message and start generation.

        Returns ``(user_message, assistant_message)``; when ``run_async`` the
        assistant message is a placeholder being filled as deltas arrive.
        """
        conv = self.db.get_conversation(conversation_id)
        if conv is None:
            raise KeyError(f"unknown conversation {conversation_id}")
        cfg = self.config()
        mode = mode or conv["mode"] or cfg["swarm"]["mode"]
        model = model or conv["model"] or cfg["model"]["model_name"] or ""

        user_msg = self.db.add_message(conversation_id, "user", text)
        if conv.get("title") in ("", "New conversation"):
            first_line = " ".join(text.strip().split())
            self.db.update_conversation(conversation_id,
                                        title=(first_line[:56] + "…") if len(first_line) > 56
                                        else first_line)
        assistant_msg = self.db.add_message(conversation_id, "assistant", "",
                                            meta={"mode": mode, "model": model,
                                                  "status": "running"})
        self.db.touch_conversation(conversation_id)

        request = ActiveRequest(
            request_id=uuid.uuid4().hex[:16],
            conversation_id=conversation_id,
            message_id=assistant_msg["id"],
            mode=mode, model=model)
        with self._lock:
            self._active[request.request_id] = request
        self.db.add_request(request.request_id, conversation_id,
                            user_msg["id"], mode, model)
        self.bus.publish("request.started", request_id=request.request_id,
                         conversation_id=conversation_id,
                         message_id=assistant_msg["id"], mode=mode, model=model)

        if run_async:
            thread = threading.Thread(
                target=self._run_generation, args=(request, mode, model),
                name=f"chat-{request.request_id[:8]}", daemon=True)
            thread.start()
        else:
            self._run_generation(request, mode, model)
        return user_msg, assistant_msg

    def _run_generation(self, request: ActiveRequest, mode: str, model: str) -> None:
        conv_id = request.conversation_id
        try:
            history = self.db.get_messages(conv_id)
            prior = [m for m in history if m["id"] != request.message_id]
            context = [{"role": m["role"], "content": m["content"]}
                       for m in prior if m["role"] in ("user", "assistant")]
            context = context[-MAX_CONTEXT_MESSAGES:]
            if not context:
                return self._fail(request, "no user message in context")
            user_text = context[-1]["content"]

            # Distributed modes route through the swarm engine.
            local_reason = ""
            routing_stages: list[dict[str, Any]] | None = None
            routing_meta: dict[str, Any] = {}
            multi_local = mode == "local" and bool(self.config()["model"].get("multi_model"))
            if (mode in ("lan", "internet", "auto") or multi_local) \
                    and self.orchestrator is not None:
                if mode == "internet":
                    return self._fail(
                        request, "Internet swarms are Phase 3 (rendezvous not implemented)")
                try:
                    # The conversation stays on this device: the orchestrator
                    # rewrites a follow-up locally into a standalone request.
                    outcome = self.orchestrator().run(
                        user_text, mode=mode, request_id=request.request_id,
                        cancel=request.stop_event, history=context[:-1])
                except Exception as exc:
                    return self._fail(request, f"swarm execution failed: {exc}")
                routed = outcome.get("routed")
                if routed == "distributed":
                    self._finish_distributed(request, outcome["text"],
                                             outcome["metadata"], outcome["stages"])
                    return
                if routed == "error":
                    if outcome.get("status") == "stopped":
                        return self._finish(request, None, status="stopped",
                                            note="interrupted by user",
                                            stages=outcome.get("stages"))
                    return self._fail(request, outcome.get("reason", "swarm error"),
                                      stages=outcome.get("stages"),
                                      swarm=outcome.get("metadata"))
                # routed == "local": privacy, router, admission or no workers.
                local_reason = outcome.get("reason", "")
                routing_stages = outcome.get("stages")
                routing_meta = outcome.get("metadata") or {}
                self.bus.publish("chat.notice", request_id=request.request_id,
                                 conversation_id=conv_id,
                                 message_id=request.message_id,
                                 note=local_reason)

            backend = self.registry.resolve(self.config())
            model = model or (backend.list_models() or [""])[0]
            if not model:
                raise IncompleteSettings("no model selected")

            def on_delta(delta: str) -> None:
                self.bus.publish("chat.delta", request_id=request.request_id,
                                 conversation_id=conv_id,
                                 message_id=request.message_id, delta=delta)

            from .engine.contract import answer_budget
            cfg = self.config()
            sources: list[dict[str, Any]] = []
            expansion = None
            ev_cfg = cfg.get("evidence") or {}
            want_public = bool(ev_cfg.get("enabled")) and bool(ev_cfg.get("local_answers", True))
            lce_on = self.retriever is not None and self.retrieval_active()
            if (lce_on and (cfg.get("lce") or {}).get("query_expansion", True)) or want_public:
                from .local_context import expand_query
                expansion = expand_query(backend, model, user_text)
            if lce_on:
                try:
                    sources = self.retriever(
                        user_text, expansion.keywords if expansion else "") or []
                except Exception:
                    sources = []
            public_hits: list[dict[str, Any]] = []
            public_report: dict[str, Any] | None = None
            if want_public and expansion is not None:
                from .local_context import public_entities, public_evidence
                known = ""
                if self.glossary is not None:
                    try:
                        known = self.glossary(f"{user_text} {expansion.keywords}")
                    except Exception:
                        known = ""
                entities = public_entities(user_text, expansion, sources,
                                           int(ev_cfg.get("local_max_entities", 3)), known)
                if entities:
                    provider = self.public_provider
                    if provider is None:
                        from .engine.evidence import WikipediaEvidence
                        provider = WikipediaEvidence(
                            lang=str(ev_cfg.get("local_lang", "en")),
                            timeout_s=float(ev_cfg.get("timeout_s", 4.0)))
                    public_hits, public_report = public_evidence(entities, expansion, provider)
            if public_hits:
                from .lang import detect_language
                from .local_context import render_public
                context = [{"role": "system",
                            "content": render_public(public_hits, detect_language(user_text))},
                           *context]
            if sources:
                context = [{"role": "system", "content": _sources_block(sources, user_text)},
                           *context]
            result = backend.stream_chat(
                context, model=model,
                max_tokens=answer_budget(
                    user_text, int(self.config()["model"].get("max_tokens", 1024))),
                temperature=float(self.config()["model"].get("temperature", 0.2)),
                on_delta=on_delta,
                interrupt=request.stop_event.is_set)
            extra = {}
            if local_reason:
                extra = {"executed": "local", "local_reason": local_reason,
                         "swarm": routing_meta}
            if sources:
                extra["lce"] = {"level": "C1", "sources": [
                    {"n": i, "source": s["source"], "start": s["start"], "end": s["end"],
                     "score": s.get("score")} for i, s in enumerate(sources, 1)]}
            if expansion is not None:
                extra.setdefault("lce", {})["expansion"] = expansion.to_dict()
            if public_report is not None:
                extra["evidence"] = public_report
            self._finish(request, result, note=local_reason, stages=routing_stages,
                         extra=extra)
        except Interrupted:
            self._finish(request, None, status="stopped",
                         note="interrupted by user")
        except (BackendError, IncompleteSettings, KeyError) as exc:
            self._fail(request, str(exc))
        except Exception as exc:  # never leave a request hanging in "running"
            self._fail(request, f"unexpected error: {exc}")

    def _finish_distributed(self, request: ActiveRequest, text: str,
                            metadata: dict[str, Any],
                            stages: list[dict[str, Any]]) -> None:
        """Complete a distributed request: assembled text + SPEC §19 metadata."""
        truncated = metadata.get("truncated_tasks") or []
        note = (f"output reached its token budget in {len(truncated)} task(s); the "
                "answer may be incomplete" if truncated else "")
        meta: dict[str, Any] = {"status": "done", "note": note,
                                "mode": request.mode, "model": request.model,
                                "request_id": request.request_id,
                                "executed": "distributed", "swarm": metadata}
        try:
            self.db.update_message(request.message_id, content=text,
                                   meta=meta, stages=stages)
            self.db.finish_request(request.request_id, "done", meta)
            self.db.touch_conversation(request.conversation_id)
        except Exception:  # database may be closing during shutdown
            pass
        with self._lock:
            self._active.pop(request.request_id, None)
        if self.config().get("results", {}).get("auto_report") and self.report_sink:
            try:
                self.report_sink(request.request_id)
            except Exception:
                pass  # a report failure never affects the answer
        self.bus.publish("chat.done", request_id=request.request_id,
                         conversation_id=request.conversation_id,
                         message_id=request.message_id, status="done",
                         content=text, meta=meta)

    def _finish(self, request: ActiveRequest, result: GenerationResult | None,
                status: str = "done", note: str = "",
                stages: list[dict[str, Any]] | None = None,
                extra: dict[str, Any] | None = None) -> None:
        meta: dict[str, Any] = {"status": status, "note": note,
                                "mode": request.mode, "model": request.model,
                                "request_id": request.request_id,
                                "executed": "local"}
        meta.update(extra or {})
        content = ""
        if result is not None:
            content = result.text
            meta.update(result.to_dict())
        try:
            if result is not None:
                self._record_stats(result)
            self.db.update_message(request.message_id, content=content, meta=meta,
                                   **({"stages": stages} if stages else {}))
            self.db.finish_request(request.request_id, status, meta)
            self.db.touch_conversation(request.conversation_id)
        except Exception:  # database may be closing during shutdown
            pass
        with self._lock:
            self._active.pop(request.request_id, None)
        self.bus.publish("chat.done", request_id=request.request_id,
                         conversation_id=request.conversation_id,
                         message_id=request.message_id, status=status,
                         content=content, meta=meta)

    def _fail(self, request: ActiveRequest, error: str,
              stages: list[dict[str, Any]] | None = None,
              swarm: dict[str, Any] | None = None) -> None:
        meta: dict[str, Any] = {"status": "failed", "error": error,
                                "mode": request.mode, "model": request.model,
                                "request_id": request.request_id}
        if swarm:
            meta["swarm"] = swarm
        try:
            self.db.update_message(request.message_id,
                                   content=f"[Error] {error}", meta=meta,
                                   **({"stages": stages} if stages else {}))
            self.db.finish_request(request.request_id, "failed", meta)
            self.db.touch_conversation(request.conversation_id)
        except Exception:  # database may be closing during shutdown
            pass
        with self._lock:
            self._active.pop(request.request_id, None)
        self.bus.publish("chat.done", request_id=request.request_id,
                         conversation_id=request.conversation_id,
                         message_id=request.message_id, status="failed",
                         error=error, meta=meta)

    def _record_stats(self, result: GenerationResult) -> None:
        import datetime
        day = datetime.date.today().isoformat()
        # Local (consumed) work only; served-to-others lives in served_* columns.
        self.db.add_stats(day,
                          tasks_requested=1,
                          tokens_out=result.completion_tokens or 0,
                          gen_ms=result.total_ms or 0)

    def interrupt(self, request_id: str) -> bool:
        with self._lock:
            request = self._active.get(request_id)
        if request is None:
            return False
        request.stop_event.set()
        return True

    def active_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"request_id": r.request_id, "conversation_id": r.conversation_id,
                     "message_id": r.message_id, "started_at": r.started_at}
                    for r in self._active.values()]

    def retry(self, conversation_id: str, message_id: str) -> tuple[dict, dict] | None:
        """Re-send the last user message before ``message_id`` (spec: retry)."""
        messages = self.db.get_messages(conversation_id)
        index = next((i for i, m in enumerate(messages) if m["id"] == message_id), None)
        if index is None or index == 0:
            return None
        user_msg = messages[index - 1]
        if user_msg["role"] != "user":
            return None
        return self.send(conversation_id, user_msg["content"])

    # -- export ---------------------------------------------------------------
    def export(self, conversation_id: str, fmt: str = "markdown",
               out_dir: Path | None = None) -> str:
        conv = self.db.get_conversation(conversation_id)
        if conv is None:
            raise KeyError(f"unknown conversation {conversation_id}")
        messages = self.db.get_messages(conversation_id)
        if fmt == "json":
            content = json.dumps({"conversation": conv, "messages": messages},
                                 indent=2, ensure_ascii=False)
            suffix = ".json"
        elif fmt == "html":
            content = self._as_html(conv, messages)
            suffix = ".html"
        else:
            content = self._as_markdown(conv, messages)
            suffix = ".md"
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"conversation-{conversation_id}{suffix}"
            path.write_text(content, encoding="utf-8")
            return str(path)
        return content

    @staticmethod
    def _as_markdown(conv: dict[str, Any], messages: list[dict[str, Any]]) -> str:
        lines = [f"# {conv['title']}", "",
                 f"- conversation: `{conv['id']}`",
                 f"- mode: {conv['mode']} · model: {conv['model'] or '-'}",
                 f"- exported: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for m in messages:
            if m["role"] == "system":
                continue
            who = "**User**" if m["role"] == "user" else "**Swarmbly**"
            lines += [f"## {who}", "", m["content"], ""]
        return "\n".join(lines)

    @staticmethod
    def _as_html(conv: dict[str, Any], messages: list[dict[str, Any]]) -> str:
        import html
        parts = [f"<h1>{html.escape(conv['title'])}</h1>",
                 f"<p><code>{conv['id']}</code> · mode: {conv['mode']} · "
                 f"model: {conv['model'] or '-'}</p>"]
        for m in messages:
            if m["role"] == "system":
                continue
            who = "User" if m["role"] == "user" else "Swarmbly"
            parts.append(
                f"<h3>{who}</h3><div>{html.escape(m['content']).replace(chr(10), '<br>')}</div>")
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Swarmbly export</title></head><body>"
                + "".join(parts) + "</body></html>")


_SOURCES_HEAD = {
    "es": ("Fuentes locales del usuario (no salen de este equipo). Úsalas solo si son "
           "pertinentes y cita la que uses como [1], [2]…:"),
    "en": ("The user's local sources (they never leave this device). Use them only if "
           "relevant and cite the one you use as [1], [2]…:"),
}


def _sources_block(sources: list[dict[str, Any]], user_text: str) -> str:
    """LCE C1: retrieved paragraphs for a local answer, with their origin."""
    from .lang import detect_language
    head = _SOURCES_HEAD.get(detect_language(user_text), _SOURCES_HEAD["en"])
    lines = [head]
    for i, s in enumerate(sources, 1):
        lines.append(f"[{i}] ({s['source']}) {s['text']}")
    return "\n".join(lines)
