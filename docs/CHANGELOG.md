# Changelog

## 0.3.0 — Composition planner (unreleased)

**Heterogeneous swarms** (21 October 2026, from P3b on four machines: macOS,
Windows, Debian; 0.5 B to 8 B models)
- Capability-aware routing: per node and family the scheduler now picks the
  largest model (parameter count from the tag) and sends it as
  `constraints.model`; workers honour it and otherwise run the largest shared
  model of the wanted family (the first one listed was taken, e.g.
  llama3.2:1b instead of llama3.1:8b). Models below
  `swarm.min_model_params_b` (1.5) are skipped while larger ones exist.
- Quality check before acceptance: a batch replica that answers fewer than
  half of its items (e.g. echoes the Spanish words it should translate) or a
  composition section far below its length is `rejected` (`E_QUALITY`) and
  retried on another node within `k_max`; if every replica is rejected the
  best is used and marked `degraded`.
- Batches keep at least `swarm.min_items_per_fragment` (3) items per
  fragment; answers are normalised to one `n. value` line per item (no code
  fences, bullets or added periods).
- The composition outline gets back an explicit requirement of the request
  that the local model dropped (the presenter, in the Galápagos request).
- Resilience (P3b.3, 22 October 2026: the largest node was shut down
  mid-request): a task whose remote attempts all fail is run on this
  device's model instead of failing the whole answer
  (`local_fallback_tasks` in the metadata); hedges only go to workers with a
  free slot (queued hedges made every remaining task miss its deadline).
  Rejected replicas keep a 160-character preview for auditing.
- Cancellation: when the requester gives up on an attempt (its timeout, a
  hedge that won, the user stopping) it sends a `cancel` message; the worker
  stops generating between tokens. Only the node that sent a task can cancel
  it; older nodes ignore the message. The requester also keeps that worker's
  slot for 2 s, so it does not send work the worker would refuse as "at
  concurrency limit" — the actual cause of the `E_POLICY` refusals in P3b,
  not the idle-only setting. Failure details are kept in the attempt's note.
- With a local model available, a retry that would wait behind busy workers
  fails fast and the task runs locally (P3b.3': queued retries waited about
  50 s and then timed out anyway). A fence's language tag left alone on a
  section's first line ("markdown") is removed.
- Speed-aware routing: tokens per second are learned per node and model from
  accepted results (a timeout records an upper bound) and kept across
  requests; a model expected to miss the deadline for the task's budget
  ranks below one that can finish, even if smaller (P3b.3'': llama3.1:8b on
  a server CPU timed out on a section that phi3.5 finished in 21–36 s).
- From P3c (five machines, 22 October 2026), audited with the new rejection
  previews:
  - batch answers without numbers ("Reptil / Ave / Pez") are read in item
    order when the line count matches, and answers renumbered from 1 for
    items 19–24 are mapped to their items when the labels are exactly 1..k;
    both were correct answers rejected by the quality check;
  - a node that just failed (backend unreachable, execution error,
    deadline) ranks below healthy ones for five minutes;
  - when every remote replica of a task is rejected, this device's model is
    tried before accepting a degraded answer.
- From P3d (same five machines, 22 October 2026):
  - a label left inside an answer ("1. 7. libro", "7.* Asunción") is
    removed before the answer is read, so a renumbered echo is rejected
    instead of accepted as a translation;
  - answers are read by position only when no line carries a label (a
    labelled echo plus "En formato markdown…" had become an answer);
  - an item without an answer is shown as "(sin respuesta verificada)" (in
    the request's language), and the raw text of a rejected replica is
    never shown;
  - the local rescue tries the bare task after the packet: the same 3B
    model echoed a fragment wrapped in the contract header and answered it
    without; `local_fallback_rejected` lists tasks where both failed;
  - composition sections prefer a replica within ±30 % of the section's
    word target (after language, requirements and completeness);
  - the outline keeps the number of sections the request asks for ("una
    introducción, tres secciones y una conclusión" → 5): the local model is
    told, and the outline is corrected (extra middle sections folded into
    the previous one, missing ones added before the closing).
- From P3e (same network, 22 October 2026):
  - hedges use the learned time of each attempt's node and model for this
    kind of task: an attempt is hedged once it runs past twice that time
    (plus 1 s, never sooner than 2 s), when that comes before the p95 or the
    30 s fallback (`speed` in `hedge_timer`); each attempt triggers at most
    one such hedge;
  - a worker that missed a deadline or refused a task as "at concurrency
    limit" is marked busy for 15 s, across requests: hedges skip it and
    other choices rank it last (the old Mac refused five tries in a row, one
    per model family);
  - a retry after a quality rejection may wait for a busy worker (two echoes
    with no free worker used to end in a degraded answer);
  - the upstream suffix glued to the last item ("8. 7000 m Close the
    answer; …") is removed from the item list;
  - a table section the request did not ask for is removed from the
    outline.
- From P3f (same network, 22 October 2026):
  - a worker that answers "backend unavailable" (its Ollama is down) is a
    last resort for a minute, before diversity of machines and families;
  - an attempt cancelled as slow teaches a floor for its node and model and
    marks the node busy for 8 s (a slow CPU may not stop mid-prompt); a
    model whose learned time reaches the hedge fallback counts as too slow;
  - composition: outside the ±30 % band the replica closest to the
    section's target wins (195 and 83 words for 144: the 83 was chosen);
    table sections have no word target.
- From P3g (same network with the old Mac healthy, 23 October 2026):
  - when the two replicas of a batch fragment disagree on an item, one more
    replica on another family breaks the tie (`swarm.tie_break`, on;
    `tie_breaks` in the metadata): "carro / leite / vermelho" had won over
    "car / milk / red" as the better-ranked replica;
  - in the item vote, numbered answers win ties over answers read by
    position (a model listed "6. Pez / 5. Aves / 4. Reptil"; without the
    numbers that order maps to the wrong items);
  - composition selection: required names first, then length within the
    band, then the other requirement words (they favoured the longest
    replica: +37 % and +41 % texts); short sections are asked for fewer
    words (×0.75–1.0 below 200 words, provisional);
  - a rejected batch replica's note starts with what the check read
    ("items 4-6: read [5], need 2").
- From P3h (23 October 2026):
  - "respond in Spanish" is no longer added to a task that names the
    language of the answer ("traducción al inglés"): with it qwen2.5:3b
    echoed the Spanish words, without it translated them — the main source
    of echo rejections since P3b;
  - votes compare numbers by value and one-word answers by their singular
    ("1.5" = "1.5 km", "Aves" = "ave"): every fragment of the length batch
    had gone to a tie-break over units;
  - an answer on the line after its repeated item ("4. Iguana marina /
    - reptil") is read;
  - format words the request did not ask for (tables, lists, headings) are
    removed from the outline's style line, and prose sections are told to
    write paragraphs without tables (and without lists unless requested);
  - tie-break attempts are labelled `tie_break`; an unreadable rejected
    replica's note keeps its first characters escaped.
- From P3i (23 October 2026), the echo traced to the packet itself:
  - the batch directive is reworded in all four languages ("For each item,
    write one line with its number and your answer (for example: “1.
    answer”). Do not repeat the item."): with "answer only the numbered
    items …, keeping each item's number", phi3.5 and qwen2.5:3b re-listed
    the Spanish words; with the new wording both translated them (n = 1 per
    model and wording). Batch ρ figures change slightly;
  - lower-case words returned by the upstream entity extractor are no
    longer sent as names ("usa exactamente estos nombres: para, cada, una"
    in every batch packet);
  - a style line copied from the outline schema's placeholder is dropped.
- From P3j (23 October 2026):
  - the batch directive loses its example line ("1. answer"): workers
    renumbered from 1 or wrote "respuesta: table". Compared on this Mac
    (4 models × 2 fragments, n = 1 each), the plain wording "For each item,
    write one line with its number and your answer. Do not repeat the item."
    was the only one read and translated in all eight cells;
  - renumbered answers repeated in a code fence are read (only the first
    1..k run counts); bold markers inside an answer are removed
    ("**12.5** km");
  - a composition table section must contain a Markdown table (≥ 3 rows)
    to be accepted;
  - nodes advertise their app version and build, operating system,
    architecture and free memory (shown in the Monitor's node tooltip).
- From P3k (all five machines on `6762e76`, 23 October 2026):
  - Ollama's first chunk may take up to 90 s (a cold model load): with a
    30 s read timeout every cold load on a Windows node failed as "timed
    out" (needs the update on each worker);
  - workers report the model load time (`load_ms`), and the requester
    subtracts it before learning speed: a cold load had made the largest
    models look too slow;
  - a model rejected by the quality check ranks after the others for the
    rest of the request;
  - tie-breaks only go to a worker that is free now (one queued behind a
    cold load added 60 s and failed).
- From P3l (23 October 2026): batch answers given as a Markdown table whose
  first cell is the item number ("| 7 | Pingüino | Ave |") are read.

**Public evidence for batch items (P2 prototype, off by default)**
- `evidence.enabled` (default off): for an enumerated batch of a PUBLIC
  request, items that name something (several words, or capitalised) are
  looked up on Wikipedia in the request's language; the first two sentences
  of the lead are added to that item's fragment under "Contexto público
  (Wikipedia)…; úsalo solo si es pertinente". Only item texts are sent to
  the provider — never the request — and nothing is sent for SENSITIVE or
  SANITISABLE requests.
- A result is used only if its title or lead shares a word with the item
  (titles are often scientific names); disambiguation pages are skipped.
- `evidence` in the request metadata: items queried, sources used (title
  and URL, for attribution), errors and time.
- Motivation: several models agreed on the same wrong answer ("piquero →
  pez", "pingüino → mamífero"), which no vote can correct. Whether the
  evidence helps is measured in a preregistered round, not assumed.

A single composition of a stated length (an essay, a speech, a report of N
words) is no longer sent whole to one model or to whole-request replicas: the
**local model plans it** and the swarm writes it section by section.

- **Outline on this device**: the local model reads the whole request and
  returns a JSON outline (title, topic, style line, 3–6 sections with purpose,
  word budget, key points, the explicit requirements that belong to each,
  prose or table). The code validates it (sections, word budgets rescaled to
  the requested length, tables never open or close the text); an unusable
  outline falls back to a deterministic one, and the monitor says which.
- **Decontextualised sections**: each packet carries Γ, the title, the topic
  and one section's brief and position — never the request, its instruction
  list or rubric. Γ's objective is the title, not the request's first
  sentence (which states the length of the whole text).
- **Transitions by the workers**: every section after the first opens with a
  transition from the previous heading; no bridges (the upstream bridge
  prompt is English). Seam similarity is still measured.
- **Requirement check**: each requirement of the outline is checked against
  the final text (lexical presence, not a quality judgement) and reported
  with the outline in the response metadata.
- Settings: `swarm.composer_enabled` (on), `swarm.composer_min_words` (400),
  `swarm.composer_max_sections` (6). Applies only when a local model and at
  least one worker (remote or local pool) are available.
- Fixes from the first live comparison (P3.2, 2026-10-16): a requested table
  is added when the outline omits it; repeated section headings are dropped;
  transitions no longer repeat the previous heading; a section cut at its
  budget loses its unfinished last sentence and stray `---` rules. Batch
  voting also matches unnumbered bullets by the item's own text.
- Second live round (P3.2b): a malformed outline is retried at temperature 0
  and an outline cut mid-section is repaired; a section's mandatory
  requirement comes first in its brief; replica selection prefers the replica
  that meets the section's requirements (e.g. the presenter's name); a table
  requirement is checked against the table itself; words asked of each
  section are scaled by `swarm.composer_length_factor` (0.8, provisional:
  sections overshot by +16 to +44 % in six runs).
- 197 tests (23 new in `tests/test_p1_composer.py`, including a two-node
  end-to-end run over real TLS).

**Windows install and a quieter terminal** (17 October 2026)
- SwarmblyLCE pin moved to `b659ac4`: the previous pin tracked 18 cache
  files whose names contained `:` (Ollama model tags), which Windows forbids,
  so `git clone` — and with it `pip install` — failed on Windows.
- The terminal no longer prints every WebSocket attempt. A browser tab left
  open from an earlier launch holds a stale session token; its reconnections
  were logged twice each, with the token in clear text. They are now dropped
  (one note a minute at most), tokens are redacted from any log line, and
  the web client reloads itself once to pick up the new token, with
  exponential back-off while the server is down.
- Network outcomes on the terminal: node found (once), connected and
  authenticated, left; authentication failures once per address; a single
  "no nodes found" line after an empty search, and a summary after
  “Search again”.

## 0.2.1 — Distributed answers that follow the request (unreleased)

Fixes from the diagnosis of 2026-10-15: a Spanish essay request came back as
mixed English/Spanish, partial answers that echoed the contract.

- **Admission**: numbered lines are a batch only when they are data items
  with a stated operation. The criteria, instructions, steps or rules of one
  task, and single compositions (essay, speech, text of N words), are no
  longer split; they run as one task. Each packet used to carry ~95 % of such
  a request, so every worker wrote the whole essay.
- **The user's closing instructions travel with every fragment**
  (`answer_sheet=False`); the English `[NN] value` directive is gone. Batches
  get a short directive in the request's language.
- **Language**: the request's language is detected on-device and carried as
  the Γ extension `lang`. Workers render the contract and task headings in
  that language; a "respond in <language>" line inside the task covers
  workers on older versions. English packets are unchanged.
- **Conversation context**: a follow-up in a distributed mode is rewritten by
  the local model into a self-contained request; the history never leaves the
  device. Without a local rewrite it is answered locally with the
  conversation.
- **Consensus for compositions**: one whole replica is selected (request
  language, then complete, then document medoid); per-unit alignment is kept
  as the divergence report. Batches vote per numbered item (majority, ties
  to the best-ranked replica); per-unit alignment had appended a second
  replica's re-listed items to the answer in a live smoke test.
- **Length**: requested lengths in words are read in es/en/pt/fr; output
  budgets follow them (whole-request replicas and the local answer included).
  Workers report `finish_reason`; truncated tasks are listed and noted.
- **Contract**: neutral audience when none is stated; capitalised verbs at
  line or bullet starts are no longer canonical entities; English default
  forbidden phrases are not sent with non-English requests.
- **Monitor**: largest share of the request carried by one packet
  (`max_packet_prompt_fraction`).
- 174 tests (34 new in `tests/test_p0_quality.py`).

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
