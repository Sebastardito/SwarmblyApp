# Swarmbly App

**An integrated decentralized AI client and network dashboard for
[SwarmblyAI](https://github.com/Sebastardito/SwarmblyAI) and
[SwarmblyLCE](https://github.com/Sebastardito/SwarmblyLCE).**

*Swarmbly fragments the **problem**, not the **model**. Swarmbly App puts that
protocol on your desktop: chat with local models, join a LAN swarm of worker
nodes, and watch exactly how your requests are processed — with honest
reporting of what is measured, estimated, or not available.*

> **Status: v0.1 alpha — Fase 1 (local app) functional; Fase 2 (P2P LAN) in
> development.** Nothing here claims performance it has not measured.

*Lea este documento en [español](#español).*

---

## What v0.1 does today

| Capability | Status |
|---|---|
| Local app: backend + lightweight web UI (no build step) | ✅ |
| Hardware & environment detection (honest, per-OS) | ✅ |
| Model detection: Ollama, OpenAI-compatible servers (llama.cpp, vLLM) | ✅ |
| Chat with real local inference, streaming, stop/retry, history, export (MD/JSON/HTML) | ✅ |
| Bilingual UI (English default, Español switchable) | ✅ |
| User data control: sources, wiki, outputs, identity in a per-OS data directory | ✅ |
| LCE level C0 active; C1 (local sources, conservative policy) prepared | ✅ |
| mDNS LAN discovery, node handshake, distributed micro-task execution | 🚧 Phase 2 |
| Swarm Monitor with the full distributed pipeline | 🚧 Phase 2 |
| Rendezvous / internet swarms | ⏸ Phase 3 (experimental) |
| LCE C2–C4 | ⏸ Phases 4–5 (experimental) |

## Quick start

Requirements: Python ≥ 3.10 (tested on 3.11), and for real inference an
inference backend — **Ollama** is the default.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# start Ollama (separate project) with at least one model, e.g.:
#   ollama serve
#   ollama pull llama3.2:3b        # the app never downloads models itself

swarmbly-app                       # serves the UI and opens your browser
swarmbly-app headless              # node without a window (worker-friendly)
swarmbly-app init                  # print data directory and node identity
```

The admin interface listens on `127.0.0.1:8765` by default.

## Repository map

| Path | What lives there |
|---|---|
| `swarmbly_app/` | Python backend: config, SQLite, hardware, models, inference, chat, LCE adapter, FastAPI + WebSocket, CLI |
| `web/` | Vanilla HTML/CSS/JS UI (no framework, no build step), EN/ES i18n |
| `tests/` | pytest suite (unit + API integration; P2P tests arrive with Phase 2) |
| `scripts/` | Development helpers (two-node demo arrives with Phase 2) |
| `docs/` | Installation, architecture, limitations (bilingual) |
| `audit/` | Phase 0 audit of the integrated repositories (this repo's own `swarmbly/` audit folder in the workspace) |

**User data never lives in the repository.** On first run the app creates a
data directory per OS:

- macOS: `~/Library/Application Support/Swarmbly`
- Linux: `~/.local/share/swarmbly`
- Windows: `%APPDATA%\Swarmbly`

containing `sources/` (your documents), `wiki/` (LCE memory), `output/`
(exports and reports), `identity/` (your node's Ed25519 key), `logs/` and the
SQLite database.

## Architecture

Swarmbly App is a thin integrator: it **never copies** the implementations of
SwarmblyAI or SwarmblyLCE — it depends on them, pinned to exact commits, and
adds only what those projects do not contain: the network layer, the local
API, the UI, and persistence. Full details in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the Phase 0 audit.

## Honesty is a feature

- The protocol's go/no-go coherence criterion was **not met** in SwarmblyAI's
  published measurements; this app surfaces coherence metadata, it does not
  hide it.
- Inter-model agreement is reported as **agreement**, never as truth.
- The Layer-1 verification commitment has no normative construction yet: the
  monitor reports it as *not available*, never as simulated.
- Mock results validate instruments, never models.

## License & attribution

AGPL-3.0-or-later. Integrates SwarmblyAI (`51eb44e`) and SwarmblyLCE
(`fd8d97d`) as pinned dependencies; see [`NOTICE`](NOTICE) and
[`CITATION.cff`](CITATION.cff).

---

## Español

**Un cliente descentralizado de IA y panel de red integrado para
[SwarmblyAI](https://github.com/Sebastardito/SwarmblyAI) y
[SwarmblyLCE](https://github.com/Sebastardito/SwarmblyLCE).**

Swarmbly fragmenta **el problema**, no **el modelo**. Swarmbly App lleva ese
protocolo a tu escritorio: chatea con modelos locales, participa en un enjambre
LAN de nodos y observa exactamente cómo se procesan tus solicitudes — con
reportes honestos de lo medido, lo estimado y lo no disponible.

> **Estado: v0.1 alpha — Fase 1 (app local) funcional; Fase 2 (P2P LAN) en
> desarrollo.** Nada aquí afirma rendimiento que no haya medido.

| Capacidad | Estado |
|---|---|
| App local: backend + interfaz web ligera (sin build) | ✅ |
| Detección de hardware y entorno (honesta, por SO) | ✅ |
| Detección de modelos: Ollama, servidores compatibles con OpenAI (llama.cpp, vLLM) | ✅ |
| Chat con inferencia local real, streaming, detener/reintentar, historial, exportación (MD/JSON/HTML) | ✅ |
| Interfaz bilingüe (inglés por defecto, español conmutable) | ✅ |
| Control de datos del usuario: fuentes, wiki, salidas, identidad en un directorio por SO | ✅ |
| LCE nivel C0 activo; C1 (fuentes locales, política conservadora) preparado | ✅ |
| Descubrimiento mDNS, handshake, ejecución distribuida de microtareas | 🚧 Fase 2 |
| Swarm Monitor con el pipeline distribuido completo | 🚧 Fase 2 |
| Rendezvous / enjambres por internet | ⏸ Fase 3 (experimental) |
| LCE C2–C4 | ⏸ Fases 4–5 (experimental) |

La interfaz administrativa escucha en `127.0.0.1:8765` por defecto. Los datos
del usuario viven en el directorio de datos por sistema operativo
(`sources/`, `wiki/`, `output/`, `identity/`…) y **nunca** en el repositorio.

Licencia AGPL-3.0-or-later. Véase [`NOTICE`](NOTICE) y
[`CITATION.cff`](CITATION.cff).

Copyright © 2026 Sebastián A. Espinoza-Ulloa.
