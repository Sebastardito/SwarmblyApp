/* Swarm Monitor: honest live observability.
   Phase 1: system facts + live local request events (no invented swarm data).
   Phase 2: mDNS discovery, node graph, distributed pipeline stages. */
"use strict";

const Monitor = (() => {
  const MAX_STAGES = 40;

  function el(id) { return document.getElementById(id); }

  function init() {
    renderSystem();
    const pipeline = el("pipeline");
    pipeline.innerHTML = "";
    App.onEvent((event) => noteEvent(event));
    // Periodic light refresh of uptime (event-driven where possible)
    setInterval(() => {
      if (App.state.activePanel === "monitor") refreshUptime();
    }, 5000);
  }

  function renderSystem() {
    const sys = App.state.system;
    if (!sys) return;
    const box = el("monitor-system");
    box.innerHTML = "";
    const rows = [];
    if (sys.os) {
      const os = sys.os.value || {};
      rows.push(["OS", `${os.system || "?"} ${os.release || ""} (${os.machine || "?"})`, sys.os.confidence]);
      rows.push(["Python", os.python || "?", "measured"]);
    }
    if (sys.cpu) {
      const cpu = sys.cpu.value || {};
      rows.push(["CPU", `${cpu.brand || "unknown"} — ${cpu.cores_logical ?? "?"} logical cores`, sys.cpu.confidence]);
    }
    if (sys.memory) {
      const mem = sys.memory.value || {};
      if (mem.total_bytes) {
        rows.push(["RAM", `${(mem.total_bytes / 1024 ** 3).toFixed(1)} GB total · ${(mem.available_bytes / 1024 ** 3).toFixed(1)} GB available`, sys.memory.confidence]);
      }
    }
    if (sys.gpu) {
      const gpus = sys.gpu.value.gpus || [];
      rows.push(["GPU", gpus.length ? gpus.map((g) => g.name).join(", ") : "none detected", sys.gpu.confidence]);
    }
    for (const [label, value, confidence] of rows) {
      const div = document.createElement("div");
      div.className = "check-row";
      div.innerHTML = `<span>${label}</span><span class="val ${confidence === "unknown" ? "unknown" : ""}">${value}</span>`;
      box.appendChild(div);
    }
  }

  function refreshUptime() {
    const up = App.state.health?.uptime_s ?? 0;
    el("metric-uptime").textContent = fmtUptime(up);
  }

  function fmtUptime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  function noteEvent(event) {
    const pipeline = el("pipeline");
    if (!pipeline) return;
    const { type, ts, payload } = event;
    const row = document.createElement("div");
    row.className = "stage";
    const t = new Date(ts * 1000).toLocaleTimeString();
    let text = type;
    let cls = "running";
    if (type === "request.started") {
      text = `REQUEST RECEIVED — mode=${payload.mode}, model=${payload.model || "auto"}`;
      cls = "running";
    } else if (type === "chat.delta") {
      text = "GENERATING — stream in progress";
    } else if (type === "chat.done") {
      const status = payload.status;
      text = `FINAL RESPONSE — ${status}` +
        (payload.meta && payload.meta.total_ms != null ? ` · ${(payload.meta.total_ms / 1000).toFixed(1)} s` : "");
      cls = status === "done" ? "done" : "failed";
    }
    row.innerHTML = `<span class="t">${t}</span><span>${text}</span>`;
    row.className = `stage ${cls}`;
    pipeline.appendChild(row);
    while (pipeline.children.length > MAX_STAGES) pipeline.removeChild(pipeline.firstChild);
    pipeline.scrollTop = pipeline.scrollHeight;
  }

  return { init, noteEvent };
})();
