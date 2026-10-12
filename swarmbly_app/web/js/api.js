/* Thin API client: REST helpers + a WebSocket event subscription. */
"use strict";

const Api = (() => {
  /* Per-launch session token injected by the server into this page. */
  const tokenMeta = document.querySelector('meta[name="swarmbly-token"]');
  const TOKEN = tokenMeta ? tokenMeta.getAttribute("content") : "";

  /* Escape any value before it goes into innerHTML. Remote peers control
     some strings (model families, error details): never trust them. */
  function esc(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function request(method, path, body) {
    const opts = { method, headers: { "X-Swarmbly-Token": TOKEN } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    if (!resp.ok) {
      let detail = resp.statusText;
      try { detail = (await resp.json()).detail || detail; } catch (_) {}
      throw new Error(`${resp.status} ${detail}`);
    }
    const text = await resp.text();
    return text ? JSON.parse(text) : null;
  }

  const get = (p) => request("GET", p);
  const post = (p, b) => request("POST", p, b);
  const put = (p, b) => request("PUT", p, b);
  const del = (p) => request("DELETE", p);

  /* WebSocket: one connection, many typed handlers. */
  function subscribe(onEvent) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`);
    ws.onmessage = (msg) => {
      try { onEvent(JSON.parse(msg.data)); } catch (_) {}
    };
    ws.onclose = () => setTimeout(() => subscribe(onEvent), 2000);
    return ws;
  }

  /* Authenticated download (export/report links cannot carry the header). */
  async function download(path, filename) {
    const resp = await fetch(path, { headers: { "X-Swarmbly-Token": TOKEN } });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  return { request, get, post, put, del, subscribe, download, esc, TOKEN };
})();
