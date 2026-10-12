/* First-run setup assistant: system checks, models, privacy, LCE. */
"use strict";

const Wizard = (() => {
  let stepIndex = 0;
  const steps = ["system", "models", "privacy", "lce"];

  function el(id) { return document.getElementById(id); }

  function show() {
    if (document.getElementById("wizard")) return;
    const div = document.createElement("div");
    div.id = "wizard";
    div.className = "wizard";
    div.innerHTML = `
      <div class="wizard-card">
        <h1 data-i18n="wizard.title">Swarmbly</h1>
        <p data-i18n="wizard.intro"></p>
        <div id="wizard-body"></div>
        <div class="wizard-actions">
          <button class="btn" id="wizard-skip" data-i18n="wizard.skip"></button>
          <button class="btn primary" id="wizard-next"></button>
        </div>
      </div>`;
    document.body.appendChild(div);
    I18n.applyAll(div);
    el("wizard-next").addEventListener("click", next);
    el("wizard-skip").addEventListener("click", finish);
    renderStep();
  }

  function renderStep() {
    const key = steps[stepIndex];
    const body = el("wizard-body");
    const next = el("wizard-next");
    next.textContent = stepIndex === steps.length - 1 ? I18n.t("wizard.finish") : "→";
    if (key === "system") renderSystem(body);
    if (key === "models") renderModels(body);
    if (key === "privacy") renderPrivacy(body);
    if (key === "lce") renderLce(body);
  }

  function renderSystem(body) {
    const sys = App.state.system || {};
    body.innerHTML = `<h3 data-i18n="wizard.system"></h3><p data-i18n="wizard.systemHint"></p>`;
    const rows = [];
    if (sys.os) {
      const os = sys.os.value || {};
      rows.push(["OS", `${os.system} ${os.release}`, sys.os.confidence]);
      rows.push(["Python", os.python, "measured"]);
    }
    if (sys.cpu) rows.push(["CPU", `${(sys.cpu.value || {}).brand || "unknown"} (${(sys.cpu.value || {}).cores_logical ?? "?"} cores)`, sys.cpu.confidence]);
    if (sys.memory) {
      const m = sys.memory.value || {};
      rows.push(["RAM", m.total_bytes ? `${(m.total_bytes / 1024 ** 3).toFixed(1)} GB` : "unknown", sys.memory.confidence]);
    }
    if (sys.gpu) rows.push(["GPU", ((sys.gpu.value.gpus || []).map((g) => g.name).join(", ") || "none"), sys.gpu.confidence]);
    if (sys.python_deps) {
      const deps = sys.python_deps.value || {};
      const missing = Object.entries(deps).filter(([, v]) => v === "missing");
      rows.push(["swarmbly_v0 / swarmbly_lce",
        missing.length ? `${missing.length} missing` : "installed",
        missing.length ? "unknown" : "measured"]);
    }
    for (const [label, value, confidence] of rows) {
      const div = document.createElement("div");
      div.className = "check-row";
      div.innerHTML = `<span>${label}</span><span class="val ${confidence === "unknown" ? "unknown" : ""}">${value}</span>`;
      body.appendChild(div);
    }
    I18n.applyAll(body);
  }

  function renderModels(body) {
    const data = App.state.models || {};
    body.innerHTML = `<h3 data-i18n="wizard.modelsStep"></h3><p data-i18n="wizard.modelsHint"></p>
      <ul class="model-list" id="wizard-models"></ul>`;
    const list = el("wizard-models");
    const available = (data.backends || []).filter((b) => b.available);
    if (!available.length) {
      const li = document.createElement("li");
      li.textContent = I18n.t("chat.noBackend");
      list.appendChild(li);
    }
    for (const b of available) {
      for (const m of b.models || []) {
        const li = document.createElement("li");
        li.innerHTML = `${m.name}<span class="tag">${b.name}</span>`;
        list.appendChild(li);
      }
    }
    const recos = data.recommendations || [];
    if (recos.length) {
      const h = document.createElement("h3");
      h.textContent = I18n.t("settings.recommendations");
      body.appendChild(h);
      for (const r of recos.slice(0, 2)) {
        const div = document.createElement("div");
        div.className = "check-row";
        div.innerHTML = `<span>${r.model} (~${r.size_gb} GB)</span><span class="val"><code>${r.install}</code></span>`;
        body.appendChild(div);
      }
    }
    I18n.applyAll(body);
  }

  function renderPrivacy(body) {
    body.innerHTML = `
      <h3 data-i18n="wizard.privacyStep"></h3>
      <p data-i18n="wizard.privacyHint"></p>
      <div class="check-row"><span data-i18n="settings.tier"></span><span class="val">LOCAL</span></div>
      <div class="check-row"><span data-i18n="status.lan"></span><span class="val unknown">off</span></div>
      <div class="check-row"><span data-i18n="status.internet"></span><span class="val unknown">off</span></div>`;
    I18n.applyAll(body);
  }

  function renderLce(body) {
    body.innerHTML = `
      <h3 data-i18n="wizard.lceStep"></h3>
      <p data-i18n="wizard.lceHint"></p>
      <div class="check-row"><span>C0</span><span class="val">active</span></div>
      <div class="check-row"><span>C1</span><span class="val">prepared</span></div>
      <div class="check-row"><span>C2–C4</span><span class="val unknown">later phases</span></div>`;
    I18n.applyAll(body);
  }

  function next() {
    if (stepIndex < steps.length - 1) {
      stepIndex += 1;
      renderStep();
    } else {
      finish();
    }
  }

  async function finish() {
    await Api.put("/api/config", { setup_completed: true });
    const wiz = document.getElementById("wizard");
    if (wiz) wiz.remove();
    App.refreshConfig();
  }

  return { show };
})();
