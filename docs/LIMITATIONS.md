# Known limitations (v0.2.x)

Limitations are documented, never hidden. *[Español](#español) below.*

## Swarmbly App

1. **Only structured requests are fragmented.** A request is distributed only
   when it has a structural partition: an enumerated batch (labelled items, or
   an inline list the app rewrites losslessly into labelled items) or questions
   linked to the material that answers them. Free prose is answered locally,
   with the reason shown. This is deliberate: the alternative is slicing text,
   which SPEC §14b.7 forbids (see `AUDIT_FASE0_ES.md`, H3).
2. **Distributed requests are single-turn.** The last user message is
   fragmented; earlier turns are not packed into the plan.
3. **No internet swarms yet.** Rendezvous, relay and NAT traversal are Phase 3
   (experimental). Mode `internet` is refused honestly.
4. **TRUSTED tier needs mutual TLS** (SPEC §15c) and is not implemented; such
   requests are answered locally and nothing is sent. Automatic triage that
   raises a request to TRUSTED with no trusted swarm configured also stays local
   (`E_SWARM_UNKNOWN`: never fall back to GLOBAL).
5. **SANITISABLE content stays local.** Pseudonymisation is not implemented;
   content the lane classifier marks SANITISABLE or SENSITIVE never leaves the
   device. The lane classifier is the LCE regex baseline: it *raises* a lane, it
   never certifies that content is safe.
6. **Verification is partial.** Result signatures (Ed25519), attempt ids and
   result schema are checked before anything enters assembly. The Layer-1
   commitment (`lsh-activation-v1`) has no normative construction (SPEC §21.1)
   and sampled audit (Layer 2) is not implemented: both are reported as *not
   available*, never simulated. The stage shows **partial**.
7. **Consensus is agreement, not truth.** With `k_min ≥ 2` replicas go to
   distinct model families and are aligned with SwarmblyAI's own `consensus()`.
   Agreement is convergence: errors are correlated across families (SwarmblyAI
   L13, L23). α thresholds are upstream provisional defaults, uncalibrated.
8. **ρ is derived, not targeted.** Packets carry mandatory content only (task,
   minimal Γ, consumed carry). Following whitepaper v2 §9.7, ρ is measured on
   what workers receive and reported; no ρ target is pursued, so
   `rho_target`/`rho_reachable` are `null` with the reason.
9. **Seam similarity is lexical by default.** The default embedder hashes
   words; switch to `model.embedder = server` (Ollama `/embeddings`, e.g.
   `nomic-embed-text`) for embedding cosines. τ_sem is a placeholder in both
   cases until calibrated (SPEC §14).
10. **Hedging starts from a declared fallback.** The hedge timer is the
    observed p95 per (kind, budget) once 8 samples exist; before that it is the
    configured `hedge_fallback_ms`, and the report says which was used.
11. **Channel binding is not mutual TLS.** The handshake binds each node's
    Ed25519 identity to the TLS certificate it presents (SSH host-key model):
    a man in the middle is detected. It is not the mutual TLS that TRUSTED
    requires.
12. **mDNS can be blocked** by routers, guest Wi-Fi or client isolation.
    Manual `host:port` connection always remains available. On macOS the OS
    asks for *Local Network* permission the first time.
13. **The idle-only worker mode is a CPU heuristic** (< 50 % over 0.5 s). The
    "only when plugged in" option relies on the battery state the OS reports;
    desktops without a battery count as plugged in.
14. **No user accounts.** Identity is the node's Ed25519 key (per the product
    spec, first version).
15. **GPU detection is best-effort**; unknown values are reported as unknown.
16. **App protocol extensions** (all MINOR-safe, ignored by implementations
    that do not know them, SPEC §3): handshake fields `hs`/`tls_fp`, message
    `advertisement_update`, advertisement fields `endpoint` and
    `policy.max_concurrent`, advertisement field `roles` (node roles, D-018),
    packet fields `constraints.model_family` (SWIP draft in
    `docs/SWIP-DRAFT-model-family-hint.md`), `constraints.role`,
    `constraints.think` and `constraints.carries_passages`, result fields
    `executor` and `sources`, error codes `E_POLICY`, `E_EXECUTION`,
    `E_DUPLICATE`, `E_DISCONNECTED`, `E_ROLE_UNAVAILABLE`. All four node roles
    are in the wire schema; WP4b executes `search` and `corpus` only when the
    owner opts in.
17. **Several local models share one machine.** In multi-model mode replicas
    run on different model families but the same hardware; unless the
    recommendation allows parallel generation they take turns. Their agreement
    is still agreement, not accuracy (L23).
18. **The recommended configuration is an estimate.** It combines measured
    hardware with model sizes from a catalog verified on 2026-10-12 (sizes and
    licences can change upstream). Real memory use appears once models run.
19. **Installs are narrow by design.** The app installs only the Python
    packages it knows, into its own virtual environment. It never installs
    Ollama or system software; it shows the official instructions.
20. **Downloads need a running Ollama.** Cancelling stops the stream; partial
    files are Ollama's to clean up.
21. **Memory: C1 feeds answers made on this device; C2–C4 are described, not
    selectable.** Retrieval over your sources (hybrid: keywords and local
    embeddings) is used only for answers computed on this computer, or on a
    third-party model service you authorised for passages. It has been measured
    on one person's material and on two sealed benchmark banks (baseline of
    7 November 2026), not across many users.
22. **The interface preview is fake.** `scripts/ui_preview.py` serves canned
    answers from loopback-only workers; it measures nothing.
23. **The Windows launcher is the least tested.** `launch.bat` and the
    Windows paths of `scripts/launch.py` have not run on a real Windows
    machine yet; continuous integration covers Linux and macOS.
24. **Projects are folders, not accounts.** Two apps that open the same
    project folder at the same time can overwrite each other's copy of a
    chat; there is no locking or merging. The cloud-sync warning is detected
    from the folder's path (and, on macOS, iCloud's Desktop and Documents),
    so a sync service mounted elsewhere is not detected. A citation stops
    resolving when its file changes; the app says so and does not guess.
25. **Consent is asked after the answer, not before.** A personal or
    sensitive question that would need a public lookup is answered without
    it, and the answer offers to repeat it with the lookup; the yes covers
    that question only.
26. **Answers about documents can still contain invented details.** The
    passages come with an instruction to answer only from them, a short
    document is given whole, and labels keep their meaning across turns;
    a small model (3B) still adds facts, names and table rows that are not in
    the sources. Long documents are read as their best paragraphs, never
    whole. Grounded composition (a fact sheet, tables built by code, a
    verifier) is planned for 3.2; until then, check the labels in *Explore
    processing*.

27. **The requester cannot verify a member's search engine.** A search result
    says which member and circle ran the query and that the requester cannot
    verify the engine; the worker's own ledger is local and is not signed or
    sent back. A corpus result is labelled from the destination the requester
    sent to, not from the worker's self-description, and the passages may be
    incomplete or irrelevant: retrieval is keyword/BM25 over the shared project
    only.
28. **Corpus sharing is one project at a time.** Every admitted peer of a
    circle the owner selects sees the corpus display name and size bucket,
    even if it never asks for a passage. The owner cannot revoke a single
    passage already returned; revoking the member or removing the circle from
    the share stops new retrievals.

29. **The coordinator is a single point.** The requester plans, dispatches
    and assembles. If it goes away (stop, crash, lost machine) its run ends;
    3.5 has no plan migration, replication or hand-over. A worker that goes
    away only costs its own steps, which is what the partial answer reports.
30. **Teams are templates, not agents.** A team is a fixed list of at most 12
    steps with dependencies only on earlier steps. It cannot replan, choose
    a destination, inspect intermediate results or delegate recursively, and
    it never adds a permission. Built-in examples are read-only (duplicate
    them to edit). Teams are stored on this computer (per user, and per
    project inside a project folder): there is no account, sync or sharing of
    team definitions in 3.5.
31. **A partial answer is honest about steps, not about quality.** `complete`
    means every step returned a usable result; it does not mean the answer is
    correct. A missing step is named with its stable reason and its dependents
    are marked blocked and not retried. Recipe 4's per-item `failed` status
    carries the wave reason, but a failure of the *local* list path still
    fails that request (the per-wave continuation applies to distributed
    waves).

## Upstream (audited repositories)

- SwarmblyAI: `swarmbly_v0` is a measurement harness; no networking, no
  verification, no lane classifier; the go/no-go coherence criterion was not
  met in its published measurement; SPEC v0.2 lags whitepaper v2 (§9, v0.3).
- SwarmblyLCE: raw retrieval beats the digested wiki (R13, −0.146); digestion
  is not run-to-run reproducible; layer 2 (C4) has no verdict (R11 refused).

---

## Español

1. Solo se fragmentan solicitudes con estructura (lote enumerado o preguntas
   ligadas a su material); la prosa libre se responde localmente con la razón
   visible. 2. Un solo turno. 3. Sin enjambres por internet (Fase 3). 4. TRUSTED
   requiere mTLS: se responde localmente sin enviar nada; si el triaje sube a
   TRUSTED sin enjambre confiable, también local. 5. Contenido SANITISABLE o
   SENSITIVE nunca sale del equipo (sin seudonimización aún). 6. Verificación
   **parcial**: firmas, ids y esquema sí; compromiso de capa 1 y auditoría no
   disponibles, nunca simulados. 7. Consenso = acuerdo, no verdad (L13, L23);
   umbrales α provisionales. 8. ρ se deriva y se reporta; no se persigue un
   objetivo. 9. Similitud de costuras léxica por defecto; τ_sem placeholder.
   10. El *hedge* usa el p95 observado tras 8 muestras; antes, un respaldo
   declarado. 11. El binding de canal no es mTLS. 12. mDNS puede estar
   bloqueado: la conexión manual sigue disponible; macOS pide permiso de *Red
   local*. 13. Modo "solo inactivo" heurístico por CPU. 14. Sin cuentas de
   usuario. 15. GPU por mejor esfuerzo. 16. Extensiones de la app compatibles
   MINOR, documentadas. 17. Varios modelos locales comparten la misma máquina
   y, salvo que el hardware lo permita, se turnan; su acuerdo sigue siendo
   acuerdo. 18. La configuración recomendada es una estimación (catálogo
   verificado el 2026-10-12). 19. Solo se instalan paquetes Python conocidos en
   el entorno de la app; nunca Ollama ni software del sistema. 20. Las
   descargas requieren Ollama en ejecución. 21. C1 alimenta las respuestas hechas en
   este equipo (o en un servicio de terceros autorizado para pasajes); se ha
   medido con el material de una persona y con dos bancos sellados; C2–C4 solo
   se describen. 22. La vista
   previa de la interfaz es ficticia y solo usa loopback. 23. El lanzador de
   Windows es el menos probado (la integración continua cubre Linux y macOS).
   24. Los proyectos son carpetas, no cuentas: dos apps que abren la misma
   carpeta a la vez pueden pisarse la copia de un chat (no hay bloqueo ni
   fusión); el aviso de nube se detecta por la ruta (y en macOS, por
   Escritorio y Documentos en iCloud); una cita deja de resolverse si su
   archivo cambia, y se dice. 25. El consentimiento se pide después de la
   respuesta: una pregunta personal o sensible que necesitaría una consulta
   pública se responde sin ella y ofrece repetirla con la consulta; el sí
   vale solo para esa pregunta. 26. Las respuestas sobre documentos aún pueden
   contener detalles inventados: los párrafos llegan con la instrucción de
   responder solo con ellos, un documento corto va completo y las etiquetas
   conservan su sentido entre turnos, pero un modelo pequeño (3B) sigue
   añadiendo datos, nombres y filas que no están en las fuentes; los
   documentos largos se leen por sus mejores párrafos. La composición
   fundamentada llega en 3.2. 27. Una aprobación de herramienta pendiente vive
   en memoria, no en disco: recargar la página vuelve a mostrar la tarjeta
   porque forma parte del mensaje del asistente, pero reiniciar la app detiene
   la ejecución (no se guarda ningún token ni ejecución pendiente). Vuelve a
   enviar la pregunta después de reiniciar.

27. El solicitante no puede verificar qué motor usó un miembro: el recibo
    dice el miembro, el círculo y que no es verificable; el ledger del worker
    es local y no se firma ni se devuelve. Los pasajes del corpus se etiquetan
    según el destino al que el solicitante envió la tarea, no según lo que el
    worker diga, y pueden ser incompletos o irrelevantes (recuperación BM25
    solo sobre el proyecto compartido). 28. El corpus se comparte de un
    proyecto a la vez. Todos los pares admitidos de un círculo elegido ven el
    nombre visible y el tamaño, aunque nunca pidan un pasaje; el dueño no
    puede revocar un pasaje ya devuelto, pero quitar el círculo de la
    compartición detiene las nuevas recuperaciones. 29. El coordinador es un
    único punto: el solicitante planifica, despacha y ensambla; si desaparece
    (parada, caída, equipo perdido) su ejecución termina. 3.5 no tiene
    migración de plan, replicación ni traspaso. Un worker que se va solo
    cuesta sus propios pasos, y eso es lo que informa la respuesta parcial.
    30. Los equipos son plantillas, no agentes: una lista fija de como mucho
    12 pasos con dependencias solo de pasos anteriores. No replanifican, no
    eligen destino, no inspeccionan resultados intermedios ni delegan
    recursivamente, y nunca agregan un permiso. Los ejemplos incorporados son
    de solo lectura (duplícalos para editar). Se guardan en este equipo (por
    usuario y, dentro de un proyecto, por proyecto): en 3.5 no hay cuenta,
    sincronización ni compartición de definiciones de equipos. 31. Una
    respuesta parcial es honesta sobre los pasos, no sobre la calidad:
    `complete` significa que todos los pasos devolvieron un resultado
    utilizable, no que la respuesta sea correcta. Un paso faltante se nombra
    con su razón estable y sus dependientes quedan bloqueados y no se
    reintentan. El estado `failed` por elemento de la receta 4 lleva la razón
    de la ola, pero un fallo del camino local de listas todavía hace fallar
    esa solicitud (la continuación por olas aplica a olas distribuidas).
