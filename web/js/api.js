/* Thin API client: REST helpers + a WebSocket event subscription. */
"use strict";

const Api = (() => {
  async function request(method, path, body) {
    const opts = { method, headers: {} };
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
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (msg) => {
      try { onEvent(JSON.parse(msg.data)); } catch (_) {}
    };
    ws.onclose = () => setTimeout(() => subscribe(onEvent), 2000);
    return ws;
  }

  return { request, get, post, put, del, subscribe };
})();
