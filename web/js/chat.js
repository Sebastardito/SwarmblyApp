/* Chat panel: conversations, streaming messages, modes, stop/retry/export. */
"use strict";

const Chat = (() => {
  let activeConv = null;
  let streaming = {};  // messageId -> element

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
      modeSel.appendChild(opt);
    });
    modeSel.value = App.state.config?.swarm?.mode || "local";
    if (App.state.config && App.state.config.swarm && App.state.config.swarm.mode !== "local") {
      // LAN/Internet modes are Phase 2: honest fallback to local
      modeSel.value = "local";
    }
    refreshConversations();
    refreshModels();
    refreshMetaInfo();

    App.onEvent(handleEvent);
  }

  function handleEvent(event) {
    const { type, payload } = event;
    if (type === "chat.delta" && streaming[payload.message_id]) {
      appendDelta(payload.message_id, payload.delta);
    }
    if (type === "chat.done") {
      finishMessage(payload);
    }
    if (type === "request.started" || type === "request.stage") {
      Monitor.noteEvent(event);
    }
  }

  function appendDelta(messageId, delta) {
    const elt = streaming[messageId];
    elt.lastChild.textContent += delta;
    elt.scrollIntoView({ block: "end", behavior: "auto" });
  }

  function finishMessage(payload) {
    const elt = streaming[payload.message_id];
    if (elt) {
      elt.lastChild.textContent = payload.content || "";
      elt.classList.remove("error");
      delete streaming[payload.message_id];
      const meta = payload.meta || {};
      const status = meta.status || payload.status;
      if (status === "failed") {
        elt.classList.add("error");
        const line = document.createElement("span");
        line.className = "meta-line";
        line.textContent = `${I18n.t("chat.failed")}: ${payload.error || ""}`;
        elt.appendChild(line);
      } else if (status === "stopped") {
        const line = document.createElement("span");
        line.className = "meta-line";
        line.textContent = I18n.t("chat.interrupted");
        elt.appendChild(line);
      } else if (meta.text || meta.model) {
        attachMeta(elt, meta);
      }
    }
    el("chat-stop").disabled = Object.keys(streaming).length === 0;
  }

  function attachMeta(elt, meta) {
    const line = document.createElement("span");
    line.className = "meta-line";
    const parts = [];
    if (meta.model) parts.push(meta.model);
    if (meta.completion_tokens != null) parts.push(`${meta.completion_tokens} tok`);
    if (meta.total_ms != null) parts.push(`${(meta.total_ms / 1000).toFixed(1)} s`);
    line.textContent = parts.join(" · ");
    elt.appendChild(line);
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
    for (const m of messages) {
      const div = document.createElement("div");
      div.className = `msg ${m.role}`;
      div.textContent = m.content;
      if (m.role === "assistant" && m.meta && Object.keys(m.meta).length) {
        attachMeta(div, m.meta);
      }
      box.appendChild(div);
    }
    box.scrollTop = box.scrollHeight;
    refreshConversations();
    el("chat-delete").style.display = "inline-block";
  }

  async function newConversation() {
    const conv = await Api.post("/api/conversations", {});
    await refreshConversations();
    openConversation(conv.id);
    el("chat-input").focus();
  }

  function currentMode() {
    const value = el("chat-mode").value;
    return value === "local" ? "local" : "local"; // Phase 2 unlocks lan/internet/auto
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
      const textEl = document.createElement("span");
      textEl.className = "cursor";
      div.appendChild(textEl);
      box.appendChild(div);
      streaming[a.id] = div;
      el("chat-stop").disabled = false;
      box.scrollTop = box.scrollHeight;
    } catch (err) {
      const div = document.createElement("div");
      div.className = "msg assistant error";
      div.textContent = `${I18n.t("chat.failed")}: ${err.message}`;
      box.appendChild(div);
    }
  }

  async function stop() {
    // stop the newest active stream known to this panel
    const ids = Object.keys(streaming);
    if (ids.length) {
      const messageId = ids[ids.length - 1];
      // find request id via message element mapping is unavailable; use API:
      // the backend exposes active requests; simplest: ask the server
      try {
        await Api.post("/api/requests/_stop_last", {});
      } catch (_) {
        try { await Api.post(`/api/requests/${messageId}/stop`, {}); } catch (_) {}
      }
    }
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
    const mode = App.state.config?.swarm?.mode || "local";
    span.textContent = `${I18n.t(`chat.${mode}`, mode)} · ${el("chat-model").value || I18n.t("chat.noModel")}`;
  }

  function exportConversation() {
    if (!activeConv) return;
    const fmt = prompt(I18n.t("chat.exportFormats"), "markdown");
    if (!fmt) return;
    window.open(`/api/conversations/${activeConv}/export?format=${fmt}`, "_blank");
  }

  return { init, openConversation, exportConversation, refreshModels };
})();
