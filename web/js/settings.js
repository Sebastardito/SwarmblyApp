/* Settings panel: general, models, swarm (Phase 2 notice), privacy, LCE, results. */
"use strict";

const Settings = (() => {
  function el(id) { return document.getElementById(id); }

  function init() {
    render();
    el("settings-save").addEventListener("click", save);
    el("settings-reset").addEventListener("click", reset);
  }

  function render() {
    const cfg = App.state.config || {};
    el("set-language").value = cfg.language || "en";
    el("set-theme").value = cfg.theme || "dark";
    el("set-reduce-motion").checked = !!cfg.reduce_motion;
    el("set-data-dir").textContent = cfg.data_dir || "";
    el("set-data-dir-hint").textContent = `${I18n.t("settings.dataDirHint")} (${App.state.health?.data_dir || "—"})`;

    const m = cfg.model || {};
    el("set-backend").value = m.backend || "auto";
    el("set-backend-url").value = m.backend_url || "";
    el("set-api-key").value = m.api_key || "";
    el("set-model-name").value = m.model_name || "";
    el("set-max-tokens").value = m.max_tokens ?? 1024;
    el("set-temperature").value = m.temperature ?? 0.2;

    const p = cfg.privacy || {};
    el("set-tier").textContent = p.tier || "LOCAL";

    const l = cfg.lce || {};
    el("set-lce-enabled").checked = !!l.enabled;
    el("set-lce-level").textContent = l.level || "C0";

    const r = cfg.results || {};
    el("set-export-format").value = r.export_format || "markdown";
    el("set-report-detail").value = r.report_detail || "standard";
    el("set-profile").value = cfg.profile || "automatic";

    renderDetectedModels();
  }

  async function renderDetectedModels() {
    const data = App.state.models || await Api.get("/api/models");
    App.state.models = data;
    const list = el("settings-detected");
    list.innerHTML = "";
    const models = (data.backends || [])
      .filter((b) => b.available)
      .flatMap((b) => (b.models || []).map((m) => ({ ...m, backend: b.name })));
    if (!models.length) {
      const li = document.createElement("li");
      li.textContent = I18n.t("settings.none");
      list.appendChild(li);
    }
    for (const m of models) {
      const li = document.createElement("li");
      li.innerHTML = `${m.name}<span class="tag">${m.backend}</span>`;
      if (m.family) li.innerHTML += `<span class="tag">${m.family}</span>`;
      list.appendChild(li);
    }
    const reco = el("settings-reco");
    reco.innerHTML = "";
    for (const r of data.recommendations || []) {
      const li = document.createElement("li");
      li.innerHTML = `<code>${r.model}</code> (~${r.size_gb} GB) — ${r.why}<br><code>${r.install}</code>`;
      reco.appendChild(li);
    }
  }

  async function save() {
    const body = {
      language: el("set-language").value,
      theme: el("set-theme").value,
      reduce_motion: el("set-reduce-motion").checked,
      model: {
        backend: el("set-backend").value,
        backend_url: el("set-backend-url").value.trim(),
        api_key: el("set-api-key").value.trim(),
        model_name: el("set-model-name").value.trim(),
        max_tokens: parseInt(el("set-max-tokens").value, 10) || 1024,
        temperature: parseFloat(el("set-temperature").value) || 0.2,
      },
      results: {
        export_format: el("set-export-format").value,
        report_detail: el("set-report-detail").value,
      },
      profile: el("set-profile").value,
    };
    await Api.put("/api/config", body);
    await App.refreshConfig();
    await I18n.load(el("set-language").value);
    I18n.applyAll(document);
    const note = el("settings-saved");
    note.textContent = I18n.t("settings.saved");
    note.style.display = "block";
    setTimeout(() => { note.style.display = "none"; }, 2500);
  }

  async function reset() {
    await Api.post("/api/config/reset", {});
    await App.refreshConfig();
    render();
  }

  return { init, render };
})();
