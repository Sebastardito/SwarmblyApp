/* Swarm Monitor: live observability, honest by construction.
   Renders real events only: request stages (pending/running/completed/
   skipped/not_available/failed), node discovery/connection, swarm health and
   contribution from the API. Phase 2 adds the distributed pipeline. */
"use strict";

const Monitor = (() => {
  const MAX_STAGES = 60;
  let currentRequest = null;

  function el(id) { return document.getElementById(id); }

  function init() {
    renderSystem();
    const pipeline = el("pipeline");
    pipeline.innerHTML = "";
    App.onEvent(noteEvent);
    App.onRender(() => { renderSystem(); refreshLive(); });
    setInterval(() => {
      if (App.state.activePanel === "monitor") refreshLive();
    }, 4000);
    refreshLive();
  }

  function renderSystem() {
    const sys = App.state.system;
    if (!sys) return;
    const box = el("monitor-system");
    box.innerHTML = "";
    const rows = [];
    if (sys.os) {
      const os = sys.os.value || {};
      rows.push([I18n.t("monitor.sys.os"), `${os.system || "?"} ${os.release || ""} (${os.machine || "?"})`, sys.os.confidence]);
      rows.push([I18n.t("monitor.sys.python"), os.python || "?", "measured"]);
    }
    if (sys.cpu) {
      const cpu = sys.cpu.value || {};
      rows.push([I18n.t("monitor.sys.cpu"), `${cpu.brand || "unknown"} — ${cpu.cores_logical ?? "?"} ${I18n.t("monitor.sys.cores")}`, sys.cpu.confidence]);
    }
    if (sys.memory) {
      const mem = sys.memory.value || {};
      if (mem.total_bytes) {
        rows.push([I18n.t("monitor.sys.ram"), `${(mem.total_bytes / 1024 ** 3).toFixed(1)} GB · ${(mem.available_bytes / 1024 ** 3).toFixed(1)} GB ${I18n.t("monitor.sys.available")}`, sys.memory.confidence]);
      }
    }
    if (sys.gpu) {
      const gpus = sys.gpu.value.gpus || [];
      rows.push([I18n.t("monitor.sys.gpu"), gpus.length ? gpus.map((g) => g.name).join(", ") : I18n.t("monitor.sys.none"), sys.gpu.confidence]);
    }
    for (const [label, value, confidence] of rows) {
      const div = document.createElement("div");
      div.className = "check-row";
      div.innerHTML = `<span>${label}</span><span class="val ${confidence === "unknown" ? "unknown" : ""}">${value}</span>`;
      box.appendChild(div);
    }
  }

  async function refreshLive() {
    try {
      const monitor = await Api.get("/api/monitor");
      el("metric-nodes").textContent = monitor.swarm.nodes_discovered;
      el("metric-connected").textContent = monitor.swarm.nodes_connected;
      el("metric-workers").textContent = monitor.swarm.workers_available;
      const up = App.state.health?.uptime_s ?? 0;
      el("metric-uptime").textContent = fmtUptime(up);
      renderHealth(monitor.health);
      renderContribution(monitor.contribution);
      renderNodes(await Api.get("/api/swarm/nodes"));
    } catch (_) {}
  }

  function renderHealth(health) {
    const box = el("monitor-health");
    if (!box) return;
    box.innerHTML = "";
    for (const [name, metric] of Object.entries(health || {})) {
      const div = document.createElement("div");
      div.className = "metric";
      div.innerHTML = `<div class="value">${String(metric.value)}</div>
        <div class="label">${I18n.t(`monitor.healthMetrics.${name}`, name)}</div>
        <div style="font-size:0.65rem;color:var(--text-dim)">${I18n.t(`monitor.healthMetrics.${name}.src`, metric.source || "")}</div>`;
      box.appendChild(div);
    }
  }

  function renderContribution(cont) {
    const box = el("monitor-contribution");
    if (!box) return;
    const rows = [
      [I18n.t("monitor.c.tasksServed"), cont.tasks_served],
      [I18n.t("monitor.c.processingTime"), `${(cont.processing_time_ms / 1000).toFixed(1)} s`],
      [I18n.t("monitor.c.tokens"), cont.tokens_generated],
      [I18n.t("monitor.c.bytes"), `${cont.bytes_transferred.in} / ${cont.bytes_transferred.out}`],
      [I18n.t("monitor.c.requests"), cont.tasks_requested],
    ];
    box.innerHTML = "";
    for (const [label, value] of rows) {
      const div = document.createElement("div");
      div.className = "check-row";
      div.innerHTML = `<span>${label}</span><span class="val">${value}</span>`;
      box.appendChild(div);
    }
  }

  function renderNodes(data) {
    const box = el("monitor-nodes");
    if (!box) return;
    const peers = data.peers || [];
    box.innerHTML = "";
    if (!peers.length) {
      const li = document.createElement("li");
      li.textContent = I18n.t("monitor.noPeers");
      box.appendChild(li);
    }
    for (const p of peers) {
      const li = document.createElement("li");
      const models = (p.models || []).map((m) => m.family || m.version).join(", ");
      li.innerHTML = `<code>${p.short_id || p.node_id.slice(0, 12)}</code> @ ${p.address}:${p.port}
        <span class="tag">${p.verified ? I18n.t("monitor.verified") : I18n.t("monitor.unverified")}</span>
        ${models ? `<span class="tag">${models}</span>` : ""}`;
      box.appendChild(li);
    }
  }

  function fmtUptime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  function noteEvent(event) {
    const { type, ts, payload } = event;
    if (type === "request.started") {
      currentRequest = payload.request_id;
      const pipeline = el("pipeline");
      pipeline.innerHTML = "";
      addStage(pipeline, "REQUEST RECEIVED", "running", "", ts);
    } else if (type === "request.stage") {
      const pipeline = el("pipeline");
      if (!pipeline) return;
      const status = payload.status || "pending";
      const extra = Object.entries(payload)
        .filter(([k]) => !["stage", "status", "elapsed_ms"].includes(k))
        .map(([k, v]) => `${k}=${String(v).slice(0, 60)}`).join(" ");
      addStage(pipeline, payload.stage, status, extra, ts);
    } else if (type === "node.discovered") {
      addStage(el("pipeline"), "NODE DISCOVERED", "completed",
               `${payload.address}:${payload.port} (${payload.source})`, ts);
    } else if (type === "node.connected") {
      addStage(el("pipeline"), "NODE CONNECTED", "completed",
               `${payload.short_id} @ ${payload.address}`, ts);
    } else if (type === "node.handshake_failed") {
      addStage(el("pipeline"), "HANDSHAKE FAILED", "failed",
               `${payload.address || ""} ${payload.reason || ""}`, ts);
    } else if (type === "chat.done" && payload.status === "done") {
      const pipeline = el("pipeline");
      const meta = payload.meta || {};
      if (meta.swarm) {
        const m = meta.swarm;
        addStage(pipeline, "FINAL RESPONSE", "completed",
                 `ρ=${m.rho_achieved} · seams=${(m.seams || []).length} · ` +
                 `consensus=${m.consensus ? "k=" + m.consensus.k : "null (k=1)"}`, ts);
      } else if (meta.total_ms != null) {
        addStage(pipeline, "FINAL RESPONSE (local)", "completed",
                 `${(meta.total_ms / 1000).toFixed(1)} s · ${meta.completion_tokens || 0} tok`, ts);
      }
    }
  }

  function addStage(container, name, status, extra, ts) {
    if (!container) return;
    if (container.children.length >= MAX_STAGES) {
      container.removeChild(container.firstChild);
    }
    if (container.firstChild && container.firstChild.textContent.includes("No events")) {
      container.innerHTML = "";
    }
    const row = document.createElement("div");
    row.className = `stage ${status}`;
    const t = new Date(ts * 1000).toLocaleTimeString();
    row.innerHTML = `<span class="t">${t}</span><span>${name}</span>` +
      (extra ? `<span class="t" style="margin-left:auto">${extra}</span>` : "");
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
  }

  return { init, noteEvent };
})();
