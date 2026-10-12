/* App shell: boot, navigation, global state, live event fan-out. */
"use strict";

const App = (() => {
  const state = {
    config: null,
    system: null,
    models: null,
    health: null,
    activePanel: "chat",
    eventHandlers: [],
  };

  function onEvent(handler) { state.eventHandlers.push(handler); }

  async function boot() {
    try {
      state.config = await Api.get("/api/config");
      state.health = await Api.get("/api/health");
      state.system = await Api.get("/api/system");
      state.models = await Api.get("/api/models");
    } catch (err) {
      console.error("boot failed", err);
    }

    await I18n.load(state.config?.language || "en");
    I18n.applyAll(document);

    Api.subscribe((event) => {
      state.eventHandlers.forEach((h) => { try { h(event); } catch (_) {} });
    });

    if (!state.config || !state.config.setup_completed) {
      Wizard.show();
    }
    updateStatusBar();
    Chat.init();
    Monitor.init();
    Lce.init();
    Settings.init();
  }

  function navigate(panel) {
    state.activePanel = panel;
    document.querySelectorAll(".nav-btn").forEach((btn) =>
      btn.classList.toggle("active", btn.dataset.panel === panel));
    document.querySelectorAll(".panel").forEach((el) =>
      el.classList.toggle("active", el.id === `panel-${panel}`));
  }

  function updateStatusBar() {
    const dot = document.getElementById("status-dot");
    const mode = state.config?.swarm?.mode || "local";
    const txt = document.getElementById("status-mode");
    txt.textContent = I18n.t(`chat.${mode}`, mode);
    dot.className = "status-dot" + (mode === "local" ? " off" : "");
    const nodeEl = document.getElementById("status-node");
    nodeEl.textContent = `${I18n.t("status.nodeId")} ${state.health?.node_id || "—"}`;
  }

  function refreshConfig() {
    return Api.get("/api/config").then((cfg) => {
      state.config = cfg;
      updateStatusBar();
      return cfg;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".nav-btn").forEach((btn) =>
      btn.addEventListener("click", () => navigate(btn.dataset.panel)));
    boot();
  });

  return { state, onEvent, navigate, refreshConfig, updateStatusBar };
})();
