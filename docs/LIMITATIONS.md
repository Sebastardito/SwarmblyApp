# Known limitations (v0.1)

This file is part of the deliverable set: limitations are documented, never
hidden. *[Español](#español) below.*

## Phase 1 (current)

1. **Only local execution.** LAN discovery, node handshake and distributed
   micro-task execution arrive with Phase 2. The chat mode selector falls
   back to `local`; the Monitor shows real local events only — it never
   invents swarm data.
2. **No model downloads.** The app detects existing models and recommends
   sizes by hardware; installation is manual (user decision Q4).
3. **LCE C0/C1-prepared only.** C1 creates the source space and a policy in
   which *nothing trains by default* (invariant I8). Digestion, retrieval
   over sources and Γ projection arrive with the full LCE integration phase.
   C3 (capsules) is implemented upstream but not validated on a real network;
   C4 (LoRA) is experimental with no verdict (upstream R11) and is not
   exposed as a product feature.
4. **Verification is not available.** The Layer-1 commitment
   (`lsh-activation-v1`) has no normative construction yet (SPEC v0.2 open
   question #1). Reports say *not available*; nothing is simulated.
5. **Consensus requires k>1.** With the default `k=1` the response metadata
   reports `consensus: null` with its waiver reason; agreement maps are never
   presented as accuracy.
6. **Thresholds are placeholders.** SwarmblyAI documents its α/τ defaults as
   placeholders pending calibration; the app exposes them and their source
   rather than implying they are calibrated.
7. **GPU detection is best-effort.** Values are reported as *unknown* when the
   OS probe is unreliable; they are never invented.
8. **Single process, loopback-only API.** No user accounts (node identity
   only, per the product spec). The P2P service gets independent access
   limits in Phase 2.
9. **Coherence tax.** SwarmblyAI's go/no-go criterion was **not met** in its
   published measurement; distributed answers carry their coherence metadata
   and the user sees it.

## Upstream (from the audited repositories)

- SwarmblyAI: no networking, no verification, no adversarial-node handling
  (V0); wire formats specified but not implemented in code; SPEC v0.2 lags
  whitepaper v2 in some fields.
- SwarmblyLCE: the digested wiki **loses** to raw retrieval over sources
  (R13: −0.146); digestion is not run-to-run reproducible (AA2); adapter
  (C4) untested at evaluation (R11).

---

## Español

1. Solo ejecución local por ahora; el descubrimiento LAN y la ejecución
   distribuida llegan con la Fase 2. 2. La app nunca descarga modelos.
3. LCE: C0 activo y C1 preparado; digestión, retrieval y proyección llegan
   con la integración completa; C3 no está validado en red real y C4 es
   experimental sin veredicto. 4. La verificación Layer-1 no está disponible
   (sin construcción normativa); se reporta así, nunca se simula. 5. El
   consenso solo se reporta si k>1 realmente se ejecutó; el acuerdo nunca se
   presenta como exactitud. 6. Los umbrales son placeholders declarados.
7. La detección de GPU es de mejor esfuerzo y reporta *unknown* cuando no es
   fiable. 8. API solo en loopback, sin cuentas de usuario. 9. El impuesto de
   coherencia se muestra, no se oculta (criterio go/no-go no cumplido
   aguas arriba).
