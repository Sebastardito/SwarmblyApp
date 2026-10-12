# Swarmbly App — Architecture

*[Español](#español) below.*

## 1. Positioning

Swarmbly App is a **thin integrator**. It does not copy the implementations of
SwarmblyAI or SwarmblyLCE; it depends on them as pip packages pinned to exact
commits and adds only what those repositories do not contain:

| Component | Where it comes from |
|---|---|
| Protocol engine (privacy tiers, router, DAG planning, Γ/ρ packing, micro consensus, macro assembly, metrics) | `swarmbly_v0` — SwarmblyAI, reused as-is |
| LCE (wiki, claims, policy, projection, WorkerGuard, capsules) | `swarmbly_lce` — SwarmblyLCE, reused as-is |
| Inference backends (Ollama / OpenAI-compatible streaming) | **new** in Swarmbly App (adapters) |
| P2P transport (mDNS, TLS 1.3, Ed25519 handshake, SPEC v0.2 wire messages) | **new** — SwarmblyAI explicitly has *no networking* (Phase 2) |
| Local API, WebSocket events, UI, SQLite, hardware detection | **new** in Swarmbly App |

## 2. Process & access boundaries

```
┌───────────────────────────── localhost only ─────────────────────────────┐
│  swarmbly-app (one Python process)                                       │
│   FastAPI  →  127.0.0.1:8765  (REST + WebSocket + static web UI)         │
│   P2P service → separate port/interface (Phase 2)                        │
└──────────────────────────────────────────────────────────────────────────┘
```

- The admin interface binds to `127.0.0.1` by default. The P2P service has
  independent access limits (Phase 2).
- `swarmbly-app headless` runs the node without a UI; the engine and the
  interface are separate (user requirement E).

## 3. Data flow (local request, Phase 1)

```
UI (web) → POST /api/conversations/{id}/messages
        → ChatService (thread) → BackendRegistry → Ollama/OpenAI-compat (stream)
        → events: request.started → chat.delta* → chat.done
        → SQLite: conversations, messages, requests, stats
        → WebSocket /ws → UI renders stream + monitor activity
```

## 4. User data directory

Code lives in the repository; **user data lives in the per-OS data directory**
created on first run:

```
sources/    raw user documents (LCE layer 0, immutable)
wiki/       LCE wiki state + conservative policy ("nothing trains")
adapters/   LCE layer 2 (later phase; never shared)
capsules/   signed capsules (later phase; pull-only)
output/     exports/ and reports/ (logical default output location)
identity/   Ed25519 node key (0600)
logs/       rotating logs
app.db      SQLite: conversations, messages, requests, node cache, stats
```

Copying `sources/ + wiki/ + identity/ + app.db` migrates a node.

## 5. Protocol conformance

- Node identity: Ed25519; `node_id` = public key, base64url unpadded
  (SPEC v0.2 §4). Phase 2 adds the signed handshake and TLS 1.3 links
  (mutual TLS for TRUSTED tiers).
- Privacy: tier classification runs locally and before anything else; the
  manual tier is authoritative and never downgraded (SPEC §15c). Phase 1
  default is `LOCAL` — nothing leaves the device.
- The wire codec (Phase 2) will implement the SPEC v0.2 message formats and
  **omit `session_id` on the wire**, fixing the discrepancy found in the
  audit (`swarmbly_v0` includes it in packed prompts; SPEC §4 forbids
  transmitting it to workers).
- Verification (Layer-1 commitment `lsh-activation-v1`) has no normative
  construction yet: reported as *not available*, never simulated.
- Consensus is reported only when `k > 1` actually ran; agreement is reported
  as agreement, never as truth (SPEC §21.7).

## 6. Decisions (Phase 0, user-confirmed)

1. Repository: local-first development; published by the user when ready.
2. Dependencies: pip git URLs pinned to audited commits.
3. UI language: English by default, Spanish switchable, persisted.
4. Models: never downloaded by the app; use an existing backend.
5. User data: per-OS data directory, configurable; `output/` is the logical
   default location (never inside read-only packages).

---

## Español

Swarmbly App es un **integrador delgado**: no copia las implementaciones de
SwarmblyAI ni de SwarmblyLCE; depende de ellas como paquetes pip anclados a
commits exactos y añade solo lo que esos repositorios no contienen: la capa de
red, la API local, la interfaz y la persistencia.

La interfaz administrativa escucha en `127.0.0.1:8765`; el servicio P2P tiene
límites de acceso independientes (Fase 2). `swarmbly-app headless` ejecuta el
nodo sin ventana. Los datos del usuario viven en el directorio de datos por
sistema operativo (`sources/`, `wiki/`, `output/`, `identity/`…) y nunca en el
repositorio.

Conformidad con el protocolo: identidad Ed25519 (`node_id` = clave pública,
base64url sin padding); clasificación de privacidad local y previa a todo; el
tier manual es autoritativo y nunca se rebaja. La verificación Layer-1 no
tiene construcción normativa aún: se reporta como *no disponible*, nunca
simulada. El acuerdo entre modelos se reporta como acuerdo, nunca como verdad.
