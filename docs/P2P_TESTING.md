# Physical P2P test — 2 and 5 computers

This is the reproducible procedure for the physical acceptance test of Phase 2:
two or more computers on the **same LAN** discover each other (mDNS), perform an
Ed25519-authenticated TLS 1.3 handshake, and complete a real distributed
micro-task. *[Español](#español) below.*

> The multi-node engine is already validated on one machine (loopback) with up
> to 5 distinct model families, including cross-family consensus (k=2). This
> procedure adds the physical ethernet/Wi-Fi hop.

## Preparation (every PC)

1. Install Swarmbly App: `bash scripts/dev_setup.sh` (see `INSTALL.md`).
2. Have a model available, e.g. `ollama pull llama3.2:3b` (the app never downloads).
3. Note the **P2P port** `9765` (TCP) and mDNS multicast (UDP 5353). On macOS,
   approve the firewall prompt the first time the app starts.

## Test A — two PCs (client + worker)

**Worker PC** (headless, no window):

```bash
swarmbly-app config set swarm.worker_enabled true
swarmbly-app config set swarm.lan_enabled true
swarmbly-app config set model.model_name llama3.2:3b
swarmbly-app headless
```

**Client PC** (the one that sends the request):

```bash
swarmbly-app config set swarm.lan_enabled true
swarmbly-app config set swarm.mode lan
swarmbly-app config set privacy.tier GLOBAL
swarmbly-app config set model.model_name gemma2:2b
swarmbly-app              # open the UI
```

In the UI: Chat → mode "Swarm LAN" → send a decomposable request, e.g.:

> Extract one key fact per item from the following list of five items: apples,
> bridges, comets, drums, electrons. List 5 bullet points, one per item,
> separately.

Then open **Swarm Monitor** and confirm: 1 node discovered/connected/verified,
the full pipeline completes, and the worker's contribution increases.

## Test B — five PCs (1 client + 4 workers)

Give each worker a **different model family** so the swarm is heterogeneous:

| Role | Model |
|---|---|
| Worker 1 | `llama3.2:3b` |
| Worker 2 | `qwen2.5:3b` |
| Worker 3 | `phi3.5:3.8b` |
| Worker 4 | `granite3.1-dense:2b` |
| Client (orchestrator) | `gemma2:2b` |

On each worker (headless):

```bash
swarmbly-app config set swarm.worker_enabled true
swarmbly-app config set swarm.lan_enabled true
swarmbly-app config set model.model_name <its model>
swarmbly-app headless
```

On the client:

```bash
swarmbly-app config set swarm.lan_enabled true
swarmbly-app config set swarm.mode lan
swarmbly-app config set privacy.tier GLOBAL
swarmbly-app config set swarm.k_min 2        # optional: cross-family consensus
swarmbly-app config set swarm.k_max 2
swarmbly-app config set model.model_name gemma2:2b
swarmbly-app
```

Send the same decomposable request. In **Swarm Monitor** verify:

- 4 nodes discovered/connected/**verified**.
- Swarm Health → model diversity shows 4+ families.
- The pipeline shows NODE SELECTION with 4 workers, and (with k=2) a
  CONSENSUS / ALIGNMENT step with `mean_agreement` and a per-unit
  HIGH/MEDIUM/LOW map (agreement is *agreement*, never truth).
- Each worker's "Tasks served" increases.

## If discovery fails (mDNS blocked)

Some routers/APs block multicast. Fall back to a manual connection from the
client to each worker's IP and port 9765:

```bash
swarmbly-app          # client UI
```

and in the UI: Settings → Swarm, then add the peer — or use the API:

```bash
curl -X POST http://127.0.0.1:8765/api/swarm/connect \
  -H 'Content-Type: application/json' -d '{"host":"192.168.1.20","port":9765}'
```

## What this validates (and what it does not)

- ✅ Discovery, handshake (Ed25519 over TLS 1.3), capability exchange, packet
  dispatch, result signature verification, assembly, coherence report.
- ✅ Heterogeneous workers and cross-family consensus.
- ⚠️ Loopback already validated; the physical run adds real LAN latency and
  firewall/multicast conditions.
- ❌ Internet swarms / NAT traversal (Phase 3, not implemented).

---

## Español

Procedimiento reproducible para la prueba física de Fase 2: dos o más
computadoras en la **misma LAN** se descubren (mDNS), realizan el handshake
(Ed25519 sobre TLS 1.3) y completan una microtarea distribuida real. El motor
ya está validado en una sola máquina (loopback) con hasta 5 familias de
modelos, incluido el consenso entre familias (k=2); este procedimiento añade el
salto físico ethernet/Wi-Fi.

En cada PC: instala con `bash scripts/dev_setup.sh`, ten un modelo
(`ollama pull llama3.2:3b`), y permite el puerto P2P **9765/TCP** y el
multicast mDNS (UDP 5353) en el firewall.

**Dos PCs:** en el worker ejecuta (headless) los `config set` de
`swarm.worker_enabled true`, `swarm.lan_enabled true` y `model.model_name`, y
luego `swarmbly-app headless`. En el cliente: `swarm.lan_enabled true`,
`swarm.mode lan`, `privacy.tier GLOBAL`, `model.model_name`, y `swarmbly-app`.
En el chat, modo "Swarm LAN", envía la solicitud descomponible de los cinco
ítems y verifica en el Swarm Monitor: nodo descubierto/conectado/verificado y
pipeline completo.

**Cinco PCs:** un cliente + cuatro workers, cada worker con una familia
distinta (llama3.2:3b, qwen2.5:3b, phi3.5:3.8b, granite3.1-dense:2b) y el
cliente con gemma2:2b. Opcionalmente `swarm.k_min 2` / `swarm.k_max 2` para
consenso entre familias. Verifica en el monitor: 4 nodos verificados, 4
familias, y (con k=2) el paso CONSENSUS/ALIGNMENT con su mapa de acuerdo
(acuerdo = acuerdo, nunca verdad).

Si el mDNS está bloqueado, conecta manualmente con
`POST /api/swarm/connect {"host":"IP","port":9765}`.
