# Changelog

## 0.2.0 — Phase 2.5: guided setup and new interface (2026-10-12)

Software DOI: [10.5281/zenodo.23322639](https://doi.org/10.5281/zenodo.23322639)
(all versions: [10.5281/zenodo.23322638](https://doi.org/10.5281/zenodo.23322638)).

**Setup that explains itself**
- Recommended configuration from measured hardware: a memory budget
  (unified memory, VRAM or RAM, with its derivation), chat model, local
  parallelism, multi-model, worker limits and LCE level. Every value says why
  and whether it is measured or estimated; applying it keeps a backup and can
  be reverted. It never turns on the network, sharing or a privacy tier.
- First-run assistant: welcome, system check, recommended configuration,
  models, permissions, memory, ready. Each step can be skipped.
- Explicit permissions for local-network discovery and model downloads,
  recorded with their date; internet swarms stay off until Phase 3.
- System check ("doctor"): Python packages (including the pinned upstream
  commits), Ollama, ports. Missing Python packages can be installed into the
  app's own virtual environment after consent; nothing system-wide.
- Model downloads through Ollama only, after the download permission and a
  per-model confirmation showing size and licence (catalog verified
  2026-10-12); progress streamed, cancellable.

**One-command launcher**
- `./launch.sh` (macOS / Linux), `Swarmbly.command` (macOS double-click) and
  `launch.bat` (Windows) run `scripts/launch.py`: Python, git, `.venv`,
  packages, Ollama and port, asking before every change; installs only inside
  `.venv`, never installs Ollama, reinstalls when requirements change, opens
  an already-running app instead of starting a second one. `--check`,
  `--setup-only`, `--headless`, `--yes`, `--port` and more.
- `scripts/dev_setup.sh` now uses the launcher.

**Fixes found by the first macOS CI run**
- mDNS announcements failed on computers whose name does not fit a DNS label
  (longer than 63 bytes, or with spaces, apostrophes or accents, e.g.
  "Sebastián's MacBook Pro"): zeroconf refused the host record and the node
  was never discovered. The host label is now sanitised and capped; identity
  is unaffected (it is the node key). Regression tests added.

**Documentation and repository**
- README rewritten with screenshots; new user guide (`docs/USER_GUIDE.md`),
  `CONTRIBUTING.md`, `SECURITY.md`, issue and pull-request templates, and a
  test workflow (Linux, Python 3.10–3.13; macOS).
- Installation guide rebuilt around the launcher (ports, data locations,
  updating, uninstalling, troubleshooting).

**Several local models**
- Multi-model mode: replicas of a request can run on different local model
  families (a local pool alongside remote workers), with the same consensus
  and reporting as the swarm. Whole requests that cannot be fragmented can
  still be answered by several local models and aligned.
- `constraints.model_family` honoured by workers when they have that family.

**Interface**
- New interface: conversation list, streaming chat with text attachments,
  mode and model per message, "How this answer was made" (pipeline as a DNA
  strand, attempts, consensus units, seams, caveats, reports), swarm map with
  real dispatch pulses, health and contribution, memory levels, settings by
  topic with profiles, light and dark themes, phone layout.
- Every readout is labelled measured, estimated or unknown.
- `scripts/ui_preview.py`: interface preview with a fake swarm on loopback
  (canned answers, never announced on the network).


## 0.1.1 — Phase 1.5 hardening (2026-10-12)

Fixes the findings of `docs/AUDIT_FASE0_ES.md`.

**Network**
- mDNS discovery rewritten on zeroconf's asyncio API: it now discovers peers
  (it never did), filters its own announcement, handles goodbyes, keeps a TTL
  cache with first-seen / last-verified / expiry, and runs an active query per
  request. Discovery starts and stops at runtime (H1, H2, H14, H15, H19, H23).
- Handshake revision 2: Ed25519 identities bound to the TLS certificate
  fingerprint; initiator advertisement authenticated; signed advertisement
  updates on live sessions (H9).
- One session per peer (deterministic tie-break); tasks served outside the
  read loop; keepalive with RTT; per-peer replay window and queue cap;
  graceful shutdown in < 1 s (H6, H26).
- TLS private key written 0600 (H27).

**Engine**
- Plan admission: only structural partitions are fragmented; inline lists are
  normalised losslessly into labelled items (H3).
- Wire packets built from fields: no session id, no complete request, minimal
  Γ; privacy self-check blocks dispatch on any leak (H4, H5).
- Asynchronous scheduler: parallel dispatch by readiness (statement edges do
  not wait), family-diverse replicas, `k_min` up front, hedges/retries up to
  `k_max`, per-worker capacity respected, results verified before assembly
  (H6, H12, H13).
- Upstream `consensus()` reused; lane classification (LCE) before dispatch;
  E_SWARM_UNKNOWN never falls back to GLOBAL; relative deadlines; worker cuts
  generation at its deadline (H11, H24, H25).
- Enumerated answers are spliced without transition bridges.

**Local API and UI**
- Host allowlist, Origin checks, per-launch session token, CSP and security
  headers; config changes validated (`api.*` is CLI-only) (H7).
- Every remote or model-provided string escaped; remote images never
  auto-loaded (H8).
- Events from the P2P thread reach the UI (H16).
- Processing reports fixed (they crashed) with minimal/standard/full detail;
  saved only on request.

**Packaging and metrics**
- The UI ships inside the Python package (wheel installs had no UI) (H17).
- CLI shutdown fixed (H18); orchestrator rebuilt on configuration changes (H20).
- Contribution separates served-to-others from consumed-locally (H22).

## 0.1.0 — Phases 1–2 (2026-10-11)

Initial local app, LAN prototype and monitor.
