/* LCE panel: editable enable + level (C0 active, C1 prepared, C2+ later phases).
   Owns LCE persistence via /api/lce endpoints and mirrors into Settings. */
"use strict";

const Lce = (() => {
  const LEVELS = ["C0", "C1", "C2", "C3", "C4"];
  const ENABLED_LEVELS = ["C0", "C1"];
  let populated = false;

  function el(id) { return document.getElementById(id); }

  function init() {
    populateLevels();
    el("lce-enabled").addEventListener("change", onToggle);
    el("lce-level").addEventListener("change", onLevel);
    el("set-lce-enabled").addEventListener("change", onToggle);
    el("set-lce-level").addEventListener("change", onLevel);
    App.onRender(render);
  }

  function populateLevels() {
    if (populated) return;
    for (const sel of [el("lce-level"), el("set-lce-level")]) {
      LEVELS.forEach((lv) => {
        const opt = document.createElement("option");
        opt.value = lv;
        opt.textContent = `${lv} — ${I18n.t(`lce.levels.${lv}`, lv)}`;
        opt.disabled = !ENABLED_LEVELS.includes(lv);
        sel.appendChild(opt);
      });
    }
    populated = true;
  }

  async function onToggle(e) {
    const enabled = !!e.target.checked;
    const level = el("lce-level").value;
    if (enabled) {
      await Api.post("/api/lce/activate", { level });
    } else {
      await Api.post("/api/lce/deactivate", {});
    }
    await App.refreshConfig();
    App.renderAll();
  }

  async function onLevel(e) {
    const level = e.target.value;
    const enabled = el("lce-enabled").checked;
    // Persist the chosen level always; activate only when LCE is on.
    await Api.put("/api/config", { lce: { level } });
    if (enabled) {
      await Api.post("/api/lce/activate", { level });
    }
    await App.refreshConfig();
    App.renderAll();
  }

  async function render() {
    populateLevels();
    let status;
    try { status = await Api.get("/api/lce/status"); } catch (_) { return; }
    const enabled = !!status.enabled;
    el("lce-enabled").checked = enabled;
    el("lce-level").value = status.level;
    el("set-lce-enabled").checked = enabled;
    el("set-lce-level").value = status.level;
    el("lce-state").textContent = enabled
      ? `${I18n.t("lce.enabled")} · ${status.level} (${status.state})`
      : I18n.t("lce.disabled");
    el("lce-note").textContent = status.note || "";
    el("lce-package").textContent = (status.package && status.package.installed)
      ? `swarmbly_lce ${status.package.version}`
      : I18n.t("lce.notInstalled");

    const sources = await Api.get("/api/lce/sources");
    const list = el("lce-sources");
    list.innerHTML = "";
    if (!sources.length) {
      const li = document.createElement("li");
      li.textContent = I18n.t("lce.noSources");
      list.appendChild(li);
    }
    for (const s of sources) {
      const li = document.createElement("li");
      li.textContent = `${s.name} (${(s.size_bytes / 1024).toFixed(0)} KB)`;
      list.appendChild(li);
    }
  }

  return { init, render };
})();
