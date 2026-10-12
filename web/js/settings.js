/* Settings panel: general, models, swarm, privacy, results, profile.
   LCE is owned by Lce (immediate persist); language applies immediately;
   theme previews immediately and persists on Save. */
"use strict";

const Settings = (() => {
  function el(id) { return document.getElementById(id); }

  function init() {
    el("settings-save").addEventListener("click", save);
    el("settings-reset").addEventListener("click", reset);
    el("set-language").addEventListener("change", async (e) => {
      await App.setLanguage(e.target.value);
    });
    el("set-theme").addEventListener("change", (e) => {
      App.applyTheme(e.target.value);
    });
    App.onRender(render);
  }

  function render() {
    const cfg = App.state.config || {};
    el("set-language").value = cfg.language || "en";
    el("set-theme").value = cfg.theme || "dark";
    el("set-reduce-motion").checked = !!cfg.reduce_motion;
    el("set-data-dir").textContent = App.state.health?.data_dir || cfg.data_dir || "—";
    el("set-data-dir-hint").textContent = I18n.t("settings.dataDirHint");

    const m = cfg.model || {};
    el("set-backend").value = m.backend || "auto";
    el("set-backend-url").value = m.backend_url || "";
    el("set-api-key").value = m.api_key || "";
    el("set-model-name").value = m.model_name || "";
    el("set-max-tokens").value = m.max_tokens ?? 1024;
    el("set-temperature").value = m.temperature ?? 0.2;

    const s = cfg.swarm || {};
    el("set-swarm-mode").value = s.mode || "local";
    el("set-lan-enabled").checked = !!s.lan_enabled;
    el("set-worker-enabled").checked = !!s.worker_enabled;
    el("set-worker-idle").checked = !!s.worker_only_idle;
    el("set-worker-concurrent").value = s.worker_max_concurrent ?? 1;
    el("set-k-min").value = s.k_min ?? 1;
    el("set-k-max").value = s.k_max ?? 2;
    el("set-rho").value = s.rho_target ?? 1.5;

    const p = cfg.privacy || {};
    el("set-tier").value = p.tier || "LOCAL";

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
      swarm: {
        mode: el("set-swarm-mode").value,
        lan_enabled: el("set-lan-enabled").checked,
        worker_enabled: el("set-worker-enabled").checked,
        worker_only_idle: el("set-worker-idle").checked,
        worker_max_concurrent: parseInt(el("set-worker-concurrent").value, 10) || 1,
        k_min: parseInt(el("set-k-min").value, 10) || 1,
        k_max: parseInt(el("set-k-max").value, 10) || 2,
        rho_target: parseFloat(el("set-rho").value) || 1.5,
      },
      privacy: { tier: el("set-tier").value },
      results: {
        export_format: el("set-export-format").value,
        report_detail: el("set-report-detail").value,
      },
      profile: el("set-profile").value,
    };
    await Api.put("/api/config", body);
    await App.refreshConfig();
    App.renderAll();
    Chat.refreshModels();
    const note = el("settings-saved");
    note.textContent = I18n.t("settings.saved");
    note.style.display = "block";
    setTimeout(() => { note.style.display = "none"; }, 2500);
  }

  async function reset() {
    await Api.post("/api/config/reset", {});
    await App.refreshConfig();
    App.renderAll();
  }

  return { init, render };
})();
