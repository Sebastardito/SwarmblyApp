/* Chat panel: conversations, live streaming (buffered against WS race),
   Markdown rendering, modes, stop/retry/export, full re-render on language. */
"use strict";

const Chat = (() => {
  let activeConv = null;
  let streaming = {};   // message_id -> {content, partial, cursor}
  let buffers = {};     // message_id -> {partial, done, content, meta, status, error}

  function el(id) { return document.getElementById(id); }

  function init() {
    el("chat-new").addEventListener("click", newConversation);
    el("chat-send").addEventListener("click", send);
    el("chat-stop").addEventListener("click", stop);
    el("chat-delete").addEventListener("click", deleteConversation);
    el("chat-export").addEventListener("click", exportConversation);
    el("chat-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    });
    const modeSel = el("chat-mode");
    ["local", "lan", "internet", "auto"].forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = I18n.t(`chat.${m}`, m);
      if (m === "internet") opt.disabled = true; // Phase 3 (rendezvous)
      modeSel.appendChild(opt);
    });
    modeSel.addEventListener("change", refreshMetaInfo);
    App.onRender(render);
    App.onEvent(handleEvent);
  }

  async function render() {
    await refreshConversations();
    await refreshModels();
    refreshMetaInfo();
    if (activeConv) await openConversation(activeConv);
  }

  function handleEvent(event) {
    const { type, payload } = event;
    if (type === "chat.delta") {
      const mid = payload.message_id;
      if (streaming[mid]) {
        streaming[mid].partial += payload.delta;
        streaming[mid].content.textContent = streaming[mid].partial;
        scrollBottom();
      } else {
        buffers[mid] = buffers[mid] || { partial: "", done: false };
        buffers[mid].partial += payload.delta;
      }
    } else if (type === "chat.done") {
      const mid = payload.message_id;
      if (streaming[mid]) {
        finalize(mid, payload);
      } else {
        buffers[mid] = buffers[mid] || { partial: "", done: false };
        buffers[mid].done = true;
        buffers[mid].content = payload.content;
        buffers[mid].meta = payload.meta;
        buffers[mid].status = payload.status;
        buffers[mid].error = payload.error;
      }
    }
  }

  function scrollBottom() {
    const box = el("chat-messages");
    box.scrollTop = box.scrollHeight;
  }

  function finalize(mid, payload) {
    const entry = streaming[mid];
    if (!entry) return;
    entry.content.innerHTML = Markdown.render(payload.content || entry.partial || "");
    if (window.MermaidRender) MermaidRender.process(entry.content);
    if (entry.cursor) entry.cursor.remove();
    delete streaming[mid];
    const div = entry.content.closest(".msg");
    const meta = payload.meta || {};
    if (payload.status === "failed") {
      div.classList.add("error");
      attachMetaLine(div, `${I18n.t("chat.failed")}: ${payload.error || ""}`);
    } else if (payload.status === "stopped") {
      attachMetaLine(div, I18n.t("chat.interrupted"));
    } else {
      attachMeta(div, meta);
    }
    el("chat-stop").disabled = Object.keys(streaming).length === 0;
  }

  function attachMeta(div, meta) {
    const parts = [];
    if (meta.model) parts.push(meta.model);
    if (meta.swarm) {
      const s = meta.swarm;
      parts.push(`ρ=${s.rho_achieved ?? "?"} · ${s.n_tasks ?? 0} tasks`);
      parts.push(s.consensus ? `k=${s.consensus.k}` : "k=1");
    }
    if (meta.completion_tokens != null) parts.push(`${meta.completion_tokens} tok`);
    if (meta.total_ms != null) parts.push(`${(meta.total_ms / 1000).toFixed(1)} s`);
    attachMetaLine(div, parts.join(" · "));
  }

  function attachMetaLine(div, text) {
    const line = document.createElement("span");
    line.className = "meta-line";
    line.textContent = text;
    div.appendChild(line);
  }

  function messageElement(m) {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    if (m.role === "assistant") {
      const content = document.createElement("div");
      content.className = "md";
      content.innerHTML = Markdown.render(m.content || "");
      div.appendChild(content);
      if (m.meta && Object.keys(m.meta).length) attachMeta(div, m.meta);
    } else {
      div.textContent = m.content;
    }
    return div;
  }

  async function refreshConversations() {
    const strip = el("chat-history");
    strip.innerHTML = "";
    const convs = await Api.get("/api/conversations");
    for (const conv of convs) {
      const item = document.createElement("div");
      item.className = "history-item";
      item.textContent = conv.title;
      item.dataset.id = conv.id;
      item.addEventListener("click", () => openConversation(conv.id));
      if (activeConv === conv.id) item.classList.add("active");
      strip.appendChild(item);
    }
  }

  async function openConversation(id) {
    activeConv = id;
    const box = el("chat-messages");
    box.innerHTML = "";
    const messages = await Api.get(`/api/conversations/${id}/messages`);
    for (const m of messages) box.appendChild(messageElement(m));
    if (window.MermaidRender) MermaidRender.process(box);
    box.scrollTop = box.scrollHeight;
    refreshConversations();
    el("chat-delete").style.display = "inline-block";
    el("chat-export").style.display = "inline-block";
  }

  async function newConversation() {
    const conv = await Api.post("/api/conversations", {});
    await refreshConversations();
    openConversation(conv.id);
    el("chat-input").focus();
  }

  function currentMode() {
    return el("chat-mode").value;
  }

  async function send() {
    const input = el("chat-input");
    const text = input.value.trim();
    if (!text) return;
    if (!activeConv) { await newConversation(); }
    input.value = "";
    const box = el("chat-messages");
    const userDiv = document.createElement("div");
    userDiv.className = "msg user";
    userDiv.textContent = text;
    box.appendChild(userDiv);

    try {
      const resp = await Api.post(`/api/conversations/${activeConv}/messages`, {
        text, mode: currentMode(),
        model: el("chat-model").value || null,
      });
      const a = resp.assistant_message;
      const div = document.createElement("div");
      div.className = "msg assistant";
      const content = document.createElement("div");
      content.className = "md";
      const cursor = document.createElement("span");
      cursor.className = "cursor";
      div.appendChild(content);
      div.appendChild(cursor);
      box.appendChild(div);
      streaming[a.id] = { content, cursor, partial: "" };
      el("chat-stop").disabled = false;

      // Replay any deltas / final result that arrived before the bubble existed.
      const buffered = buffers[a.id];
      if (buffered) {
        if (buffered.partial) {
          streaming[a.id].partial = buffered.partial;
          content.textContent = buffered.partial;
        }
        if (buffered.done) {
          finalize(a.id, {
            message_id: a.id, content: buffered.content, meta: buffered.meta,
            status: buffered.status, error: buffered.error,
          });
        }
        delete buffers[a.id];
      }
      box.scrollTop = box.scrollHeight;
    } catch (err) {
      const div = document.createElement("div");
      div.className = "msg assistant error";
      div.textContent = `${I18n.t("chat.failed")}: ${err.message}`;
      box.appendChild(div);
    }
  }

  async function stop() {
    await Api.post("/api/requests/_stop_last", {});
  }

  async function deleteConversation() {
    if (!activeConv) return;
    if (!confirm(I18n.t("chat.confirmDelete"))) return;
    await Api.del(`/api/conversations/${activeConv}`);
    activeConv = null;
    el("chat-messages").innerHTML = "";
    el("chat-delete").style.display = "none";
    refreshConversations();
  }

  async function refreshModels() {
    const sel = el("chat-model");
    sel.innerHTML = "";
    const data = App.state.models || await Api.get("/api/models");
    App.state.models = data;
    const available = (data.backends || [])
      .filter((b) => b.available)
      .flatMap((b) => (b.models || []).map((m) => ({ name: m.name, backend: b.name })));
    if (!available.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = I18n.t("chat.noModel");
      sel.appendChild(opt);
    }
    for (const m of available) {
      const opt = document.createElement("option");
      opt.value = m.name;
      opt.textContent = m.name;
      sel.appendChild(opt);
    }
    if (App.state.config?.model?.model_name) sel.value = App.state.config.model.model_name;
    refreshMetaInfo();
  }

  function refreshMetaInfo() {
    const span = el("chat-meta-info");
    if (!span) return;
    const mode = currentMode() || App.state.config?.swarm?.mode || "local";
    span.textContent = `${I18n.t(`chat.${mode}`, mode)} · ${el("chat-model").value || I18n.t("chat.noModel")}`;
  }

  function exportConversation() {
    if (!activeConv) return;
    const fmt = prompt(I18n.t("chat.exportFormats"), "markdown");
    if (!fmt) return;
    window.open(`/api/conversations/${activeConv}/export?format=${fmt}`, "_blank");
  }

  return { init, render, openConversation, exportConversation, refreshModels };
})();
