# Swarmbly App — Architecture

*[Español](#español) below.*

## 1. Positioning

Swarmbly App is a **thin integrator** and, by decision, **only one way to
participate in Swarmbly**. The protocol never depends on this application:

```
Swarmbly Ecosystem
├── SwarmblyAI   → distributed inference protocol (evolves independently)
├── SwarmblyLCE  → local cognitive extension (evolves independently)
└── SwarmblyApp  → UX + network: UI, local API, P2P, scheduler, observability
```

The app depends on `swarmbly-v0` and `swarmbly-lce` as pip packages pinned to
exact commits and never copies their code. It adds only what those projects do
not contain.

| Concern | Source |
|---|---|
| Tier classification, router, contract Γ, planner, typed carries, consensus (§14b), select-then-splice assembly (§14), entity-grid coherence | `swarmbly_v0` (reused as-is) |
| Lane classifier, `WorkerGuard` (I2), source space, policy, wiki | `swarmbly_lce` (reused as-is) |
| Plan admission, wire packets from fields, async scheduler, local model pool (`directory.py`) | **new** — `swarmbly_app/engine/` |
| Launcher: checks and consented setup before start (`scripts/launch.py`, standard library only) | **new** |
| Recommended configuration (`advisor.py`, `catalog.py`), system check and consented installs (`doctor.py`), Ollama downloads (`model_manager.py`) | **new** |
| mDNS discovery, TLS 1.3 + channel-bound Ed25519 handshake, node manager, worker | **new** — `swarmbly_app/p2p/` |
| Local API (REST + WS), security guard, UI, SQLite, hardware/model detection | **new** |

## 2. Processes and boundaries

```
┌──────────────────────────── one process ────────────────────────────┐
│ UI thread (uvicorn)    127.0.0.1:8765  REST + WS + web UI           │
│   └─ ApiGuard: Host allowlist · Origin check · session token · CSP  │
│ chat threads           one per request                              │
│ P2P loop (thread)      0.0.0.0:9765/TCP  TLS 1.3 · mDNS 5353/UDP    │
│   └─ node manager · discovery · scheduler · worker (executor pool)  │
└─────────────────────────────────────────────────────────────────────┘
```

The admin interface and the P2P service have independent sockets and access
rules. `swarmbly-app headless` runs the node without the UI.

## 3. A distributed request

```
chat → Orchestrator.run (chat thread)
  PRIVACY        tier (swarmbly_v0.classify) + lane (LCE classifier) — on device
  ROUTING        router (swarmbly_v0) + admission (structural partition only)
  PLANNING       swarmbly_v0.planner on the admitted prompt
  PACKETS        Γ minimal + task + consumed carry; privacy self-check
  NODE SELECTION family diversity → distinct machines → load → RTT
  DISPATCH       scheduler on the P2P loop: parallel by readiness,
                 k_min up front, hedges/retries up to k_max, per-node capacity
  VERIFICATION   signature + attempt id + schema (Layer-1: not available)
  CONSENSUS      swarmbly_v0.consensus when ≥2 replicas
  ASSEMBLY       swarmbly_v0.select_then_splice (lists: spliced, no bridges)
  COHERENCE      entity grid + seam statistics
  → SPEC §19 metadata + stage log → SQLite → WebSocket → monitor
```

Every stage reports `completed`, `partial`, `skipped` or `failed`; stages that
do not apply are skipped, never completed.

**Local pool.** With multi-model on, the scheduler sees a `Directory`: the
authenticated remote workers plus a `LocalPool` pseudo-peer that runs packets
on this computer's other models (`execute_local`, never counted as serving
others). Requests that may not leave the device use the pool alone; requests
that cannot be fragmented can still get whole-request replicas from several
local families, aligned by the same consensus.

**Node roles versus model roles (3.5, D-018).** These are two different ideas
and the code names them separately:

- **Model roles** (`swarmbly_app/roles.py`: `writer`, `search_terms`,
  `fusion`, `verifier`, `embeddings`) choose *which model does which job
  inside one answer*. They are local settings and never travel on the wire.
- **Node roles** (`swarmbly_app/node_roles.py`: `large_model`, `reasoner`,
  `search`, `corpus`) describe *what a worker machine can run*. They ride in
  the signed advertisement (`roles`) and, for a role task, in the packet as
  `constraints.role` / `constraints.think`, both MINOR-safe. In WP4a a node
  advertises only `large_model` (a shared model at or above
  `node_roles.large_model_min_b`, 7 B by default) and `reasoner` (a shared
  model the user marked in `node_roles.reasoner_models`), and only while the
  worker role is on. The local pool derives the same roles from its own
  models without the "shared" condition, so a role-aware plan can run on one
  node.

Placement sends a role task only to workers that advertise the role; the
models considered are the ones the role names (for `reasoner`, the worker
also honours `think: true`). Roles are self-declared and never trust the
advertiser: the requester records per-role outcomes per node (`RoleStats`) and
deprioritises a node whose role failed recently. A role never widens circle
admission, egress, lane/tier or model-size rules. If no worker advertises a
`large_model`/`reasoner` role the task may run on the best generic worker,
and the metadata, the attempt and the receipt say «role X unavailable, ran on
Y»; `search`/`corpus` have no truthful substitute, so the task fails honestly
until WP4b adds their executors.

## 4. Security model (summary)

- **Identity:** Ed25519 per node (`node_id` = public key), never the IP.
- **Channel:** TLS 1.3; the responder signs its certificate fingerprint and the
  initiator verifies it against the certificate received, then signs it back
  (detects a man in the middle). Replay protection by fresh nonces; per-peer
  attempt-id window; frame size cap; peer cap; keepalive.
- **Admission of peers:** a handshake authenticates; circle admission then
  authorises. In the default circle-only mode a peer must be listed by a
  valid, unexpired signed membership manifest that lists both nodes. It is
  checked at the handshake and again at the worker gate, so revocation takes
  effect. The explicit *my own devices* mode keeps the 3.4 LAN rule
  (any authenticated peer in the LAN). A valid invitation opens a
  control-only bootstrap session to send the signed join request; it never
  receives tasks. Worker gates (role, pause, kinds, budget, deadline,
  concurrency, lane/tier, idle) run in code for every packet.
- **Local API:** loopback by default; Host allowlist; Origin check on
  mutations and WebSocket; per-launch token; CSP; untrusted strings escaped.
- **Privacy:** LOCAL tier and SANITISABLE/SENSITIVE lanes never leave the
  device; packets never carry the session id or the complete request.
- **Peer sends and passages (D-017).** Every task packet passes
  `egress.check_call` with purpose `FRAGMENT` before it is written. Its
  destination class comes from the circle service, not the address:
  `CIRCLE` when the peer is listed by a valid shared manifest (the receipt
  names the circle and the member), `OWN_NETWORK` only in the explicit
  *my own devices* mode, and refused when neither holds, so an unclassified
  peer is never labelled. Document passages reach a peer only when the
  sender's per-circle `circle_passages` switch is on (off by default) or, in
  *my own devices* mode, when `circle.own_devices_passages` is on. These are
  separate from `privacy.third_party_passages`, which is about model
  services; enabling that flag never enables circle passages.

## 5. Data directory

```
sources/  wiki/  adapters/  capsules/   LCE planes (local only)
output/   exports/ reports/             logical default output location
identity/ node_key (0600)               cache/tls/ node.crt, node.key (0600)
circles/ manifests, invitations, joins  api_token (0600)   logs/   app.db (SQLite)
```

macOS `~/Library/Application Support/Swarmbly` · Linux `~/.local/share/swarmbly`
· Windows `%LOCALAPPDATA%\Swarmbly`. Override with `--data-dir`.

## 6. Decisions

| # | Decision | Date |
|---|---|---|
| Q1 | Local-first repository; the author publishes when ready | 2026-10-11 |
| Q2 | Upstream as pip dependencies pinned to audited commits | 2026-10-11 |
| Q3 | English UI by default, Spanish switchable | 2026-10-11 |
| Q4→D12 | Models downloaded only through Ollama (`/api/pull`), after explicit consent showing size, origin and licence | 2026-10-12 |
| Q5 | User data in the per-OS data directory | 2026-10-11 |
| D1 | Plan admission: structural partitions only | 2026-10-12 |
| D2 | Wire packets built from fields; Γ minimised | 2026-10-12 |
| D3 | Async scheduler; `k_min` (epistemic) / `k_max` (ceiling) | 2026-10-12 |
| D4 | Channel-bound handshake (SSH host-key model) | 2026-10-12 |
| D5 | API guard (Host/Origin/token/CSP) | 2026-10-12 |
| D11 | `constraints.model_family` extension + SWIP draft | 2026-10-12 |
| D8 | Rendezvous: VPS primary + Raspberry Pi secondary (Phase 3) | 2026-10-12 |
| D13 | Recommendations never enable the network, sharing or a tier; applying keeps a backup | 2026-10-12 |
| D14 | Installer limited to known Python packages in the app venv | 2026-10-12 |
| D-018 | Node roles (`large_model`, `reasoner`, `search`, `corpus`) are self-declared in the signed advertisement with validated metadata; placement tracks per-role success and roles never widen permissions | 2026-11-21 |
| D-021 | Task plane stays wire 0.2; control and role extensions are MINOR-safe and ignored by older nodes | 2026-11-21 |

---

## Español

Swarmbly App es un integrador delgado y solo una de las maneras de participar
en Swarmbly. Reutiliza `swarmbly_v0` (clasificación de tier, router, Γ, plan,
consenso, ensamblaje, coherencia) y `swarmbly_lce` (clasificador de carril,
WorkerGuard) sin copiarlos, y añade la admisión de planes, los paquetes desde
campos, el planificador asíncrono, la red P2P, la API local protegida y la
interfaz. Cada etapa del pipeline informa completada, parcial, omitida o
fallida. La identidad del nodo es su clave Ed25519; el handshake liga esa
identidad al certificado TLS y detecta intermediarios. La API local valida
Host, Origin y un token por arranque. Cada paquete de tarea pasa por la puerta
de salida con clase `CIRCLE` (miembro de un círculo de confianza, nombrando
círculo y miembro), `OWN_NETWORK` solo en el modo explícito «mis propios
dispositivos», o se rechaza: un par fuera de todo círculo no se etiqueta. Los
pasajes de tus documentos solo llegan a un par con el interruptor por círculo
`circle_passages` encendido (apagado por defecto), o con
`circle.own_devices_passages` en el modo de dispositivos propios; nunca
reutilizan `privacy.third_party_passages`. Los **roles de nodo** (3.5, D-018:
`large_model`, `reasoner`, `search`, `corpus`) no son los roles de modelo por
respuesta de `roles.py` (writer, search_terms, fusion, verifier, embeddings):
describen lo que una máquina ofrece como worker, viajan en el anuncio firmado
(`roles`) y en el paquete (`constraints.role`/`constraints.think`), ambos
MINOR-safe, y solo sirven para colocación. En WP4a se anuncian `large_model`
(modelos compartidos con al menos `node_roles.large_model_min_b`, 7 B por
defecto) y `reasoner` (modelos compartidos marcados por el usuario); el pool
local deriva los mismos roles sin la condición de «compartido». El solicitante
solo envía una tarea con rol a un worker que lo anuncie, aprende por rol y por
nodo (`RoleStats`) y desprioriza a quien falló; un rol nunca amplía permisos.
Sin worker para `large_model`/`reasoner` se puede usar el mejor worker genérico
y el intento, los metadatos y el recibo dicen «rol X no disponible, ejecutado
en Y»; `search`/`corpus` fallan honestamente hasta WP4b. Las decisiones Q1–Q5,
D1–D14 y D-018/D-021 están en la tabla anterior.
