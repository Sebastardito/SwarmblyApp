# Known limitations (v0.1)

This file is part of the deliverable set: limitations are documented, never
hidden. *[Español](#español) below.*

## v0.1 (Phases 1–2)

1. **Distributed requests are single-turn.** LAN dispatch fragments the last
   user message; prior conversation context is not yet packed into the plan.
2. **No internet swarms.** Rendezvous, NAT traversal and relay are Phase 3
   (experimental). The chat mode selector disables `internet`.
3. **TRUSTED tier needs mTLS.** Trusted swarms require mutual TLS per SPEC
   §15c; until implemented, TRUSTED requests are refused honestly
   (`E_MTLS_REQUIRED`). Default tier is LOCAL.
4. **Verification is not available.** The Layer-1 commitment
   (`lsh-activation-v1`) has no normative construction yet (SPEC v0.2 open
   question #1). The orchestrator verifies result *signatures* and reports
   commitments as not checked — never simulated.
5. **Consensus requires k>1.** With the default `k=1`, response metadata
   reports `consensus: null` with `consensus_waived_reason: "k=1_requested"`.
   With k>1 the app resolves replicas by multiple alignment with
   placeholder α thresholds (flagged as such); agreement is agreement, never
   accuracy.
6. **τ_sem is a documented placeholder** until calibrated (same footing as
   SwarmblyAI's own defaults). τ is reported with its source.
7. **Packet prompts carry SwarmblyAI's packed text** inside the SPEC packet
   `task.instruction`; the wire JSON is conformant, the mapping is documented
   in `swarmbly_app/engine/`.
8. **Workers serve the configured model name**; the LCE invariant I2 guard
   rejects any personal adapter. The worker's advertised profile is what it
   actually runs.
9. **No model downloads.** The app detects existing models and recommends
   sizes by hardware; installation is manual (user decision Q4).
10. **LCE C0/C1-prepared only.** C1 creates the source space and a policy in
    which *nothing trains by default* (I8). Digestion, retrieval over sources
    and Γ projection arrive with the full LCE integration phase. C3 is
    implemented upstream but not validated on a real network; C4 is
    experimental with no verdict (upstream R11) and is not exposed.
11. **GPU detection is best-effort**; unknown values are reported as unknown,
    never invented.
12. **Single process, loopback-only API, no user accounts** (node identity
    only, per the product spec). P2P listener is a separate socket with its
    own policy gates.
13. **Coherence tax.** SwarmblyAI's go/no-go criterion was **not met** in its
    published measurement; distributed answers carry coherence metadata and
    the UI shows it.
14. **mDNS on hostile/broken networks** degrades to manual `host:port`
    connections; discovery failure never blocks direct connections.

## Upstream (from the audited repositories)

- SwarmblyAI: no networking, no verification, no adversarial-node handling
  (V0); wire formats specified but not implemented in code; SPEC v0.2 lags
  whitepaper v2 in some fields.
- SwarmblyLCE: the digested wiki **loses** to raw retrieval over sources
  (R13: −0.146); digestion is not run-to-run reproducible (AA2); adapter
  (C4) untested at evaluation (R11).

---

## Español

1. Las solicitudes distribuidas son de un solo turno por ahora. 2. Sin
enjambres por internet (Fase 3). 3. El tier TRUSTED exige mTLS y se rechaza
honestamente hasta implementarlo; el default es LOCAL. 4. La verificación
Layer-1 no está disponible (sin construcción normativa); se verifican las
firmas de los resultados y nada se simula. 5. El consenso solo se reporta si
k>1 realmente se ejecutó; con k=1 se declara `consensus: null` con su razón.
6. τ_sem es un placeholder documentado. 7. Los prompts empaquetados de
SwarmblyAI viajan dentro del `task.instruction` del paquete SPEC; el mapeo
está documentado. 8. Los workers sirven el modelo base (invariante I2). 9. La
app nunca descarga modelos. 10. LCE: C0 activo y C1 preparado; digestión y
proyección llegan con la integración completa; C3 sin validar en red; C4
experimental sin veredicto. 11. La GPU se reporta como desconocida cuando no
es detectable. 12. API solo en loopback, sin cuentas de usuario; el listener
P2P es independiente. 13. El impuesto de coherencia se muestra, no se oculta.
14. Sin mDNS, la conexión manual host:puerto sigue disponible.
