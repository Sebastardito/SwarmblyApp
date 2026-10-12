/* LCE panel: C0 active / C1 prepared, sources list, honest status notes. */
"use strict";

const Lce = (() => {
  function el(id) { return document.getElementById(id); }

  async function init() {
    render();
    el("lce-activate").addEventListener("click", async () => {
      await Api.post("/api/lce/activate", { level: "C1" });
      await App.refreshConfig();
      render();
    });
    el("lce-deactivate").addEventListener("click", async () => {
      await Api.post("/api/lce/deactivate", {});
      await App.refreshConfig();
      render();
    });
  }

  async function render() {
    let status;
    try { status = await Api.get("/api/lce/status"); } catch (_) { return; }
    el("lce-state").textContent = status.enabled
      ? `${I18n.t("lce.enabled")} · ${status.level} (${status.state})`
      : I18n.t("lce.disabled");
    el("lce-note").textContent = status.note;
    el("lce-activate").style.display = status.enabled ? "none" : "inline-block";
    el("lce-deactivate").style.display = status.enabled ? "inline-block" : "none";
    if (status.package && status.package.installed) {
      el("lce-package").textContent =
        `swarmbly_lce ${status.package.version} · spec ${status.package.spec_version}` +
        (status.package.crypto ? " · Ed25519 ready" : " · crypto extra missing");
    }
    // sources
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
