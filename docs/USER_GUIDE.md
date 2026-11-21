# User guide

How to use Swarmbly App once it is running. Installation is in
[INSTALL.md](INSTALL.md). *[Español](#español) below.*

The app has four views, in the sidebar (bottom bar on a phone): **Chat**,
**Swarm**, **Memory** and **Settings**. The node card under the navigation
shows your node identity, default mode, privacy tier, local network, peers and
whether you are sharing this computer. The **Current request** panel on the
right follows the request in progress stage by stage (on narrow screens, open
it with the *Pipeline* button).

## 1. Chat

Type a message and press **Send** (Enter; Shift+Enter for a new line).
Answers stream in; **Stop** ends one early and **Retry** asks again.

**Mode** decides where a message may be processed:

| Mode | What happens |
|---|---|
| Local | Answered on this computer only |
| Swarm LAN | Itemised requests may be shared with authenticated computers on this network; everything else is answered locally |
| Automatic | Shared only when the request splits cleanly and workers are available |
| Swarm Internet | Phase 3; not available yet |

Two conditions must hold before anything is shared: a swarm mode, **and** a
privacy tier that allows it (Settings → Privacy → *Privacy tier* = GLOBAL).
With the default tier, LOCAL, the hint under the composer tells you nothing
will be sent.

**What gets shared.** Swarmbly fragments the *problem*: only requests with a
structure are split — a list of items to process one by one, or questions tied
to the material that answers them. This one is a good first test:

> Extract one key fact per item from the following list of five items:
> apples, bridges, comets, drums, electrons. List 5 bullet points, one per
> item, separately.

Free prose ("write an essay about …") is answered locally and the processing
record says why. Messages with attachments are answered locally too.

**Attachments.** *Attach text* adds text files up to 200 KB (txt, md, csv,
json, code…). They are read on this computer.

**Under each answer** small labels say where it ran (*local model*, *local
models*, *swarm*), how many fragments or replicas were used, the agreement
between replicas, the model and the time. Agreement is convergence, not
correctness.

**Conversations** are listed on the left (a picker at the top on a phone).
*Export* saves one as Markdown, JSON or HTML; *Delete* removes it from this
computer.

**Projects** (above the conversation). Choose *Personal* or a project, or
create one. A project is a folder of yours, by default
`Documents/Swarmbly/<Project>`:

| Folder | What goes there |
|---|---|
| `sources/` | the project's documents (text, Markdown, Word, HTML, PDF) |
| `memory/` | the project's memory: notes saved from the chat (`notas.md`), a glossary (`glosario.md`: `term = equivalent`, or `term = equivalent | privado` for an entry never used in public searches), and any notes of yours |
| `chats/` | the project's conversations, one file each, kept up to date by the app |
| `exports/` | `.swarmbly` packages of the project |

- A conversation in a project reads only that project's documents and
  memory. Your personal sources are added only if you tick *Include my
  personal sources*; a personal conversation never reads a project.
- *Export .swarmbly* writes one file with the documents, memory and chats,
  and the SHA-256 of each file. It never contains API keys: if a file holds
  one of your keys, the export stops and names it.
- *Restore a .swarmbly package* checks every hash before writing anything and
  restores into a new folder. On another computer, the chats come back and
  their citations still point to the right paragraph (a citation names a
  file by the hash of its content, not by its path). If that project is
  already open here, it is restored as a copy.
- *Close project* removes it from this app; the folder stays, and *Open a
  project folder* brings it back with its chats.
- If the folder is synced by iCloud, Dropbox, OneDrive or Google Drive, the
  app warns you: those services can move files to the cloud to free space or
  create duplicates ("chat 2.json"). Prefer a folder that is not synced, or
  keep this one always on this computer.

**Remember something.** Start a message with *Recuerda:*, *Memoriza* or
*Remember*: before answering, the app writes it, dated, to the project's
`memory/notas.md` (in a personal conversation, to `notas.md` in your sources
folder). A *Saved to memory* label says where, and the next answers find it.
It stays on this computer and such a message never goes to the swarm.
*Documents* in the project bar shows what the project can read, and why a
file gave nothing (for example a scanned PDF).

**Memory and glossary proposals.** If you ask in a message to remember
something or to add it to the glossary, or you define or correct a term
("TRU significa Trial Rearing Unit", "los cucujos, también conocidos como
cucuyos…"), a card under the answer proposes notes and glossary entries.
Edit them, untick what you do not want, and press *Save to memory*; nothing
is saved otherwise. The glossary (`term = synonyms, translations`) widens
later searches: any one of the equivalents finds the term. Add `| privado`
(or `| private`) to an entry, or tick *Private: never used in public
searches* when you save it, to keep its term and equivalents out of public
queries; local answers still use it.

**Searching online.** Swarmbly never sends your question to a search engine
on its own. If you ask for online or recent references, the answer says no
search was made and offers *Search online*: you see the exact text that
would be sent, edit it, and approve it. Results from PubMed, Wikipedia (and
your SearXNG, if configured) are listed under the new answer as [W1], [W2]…
with their links. A label in an answer that matches no passage or result is
flagged as *citation without a source*.

**Public lookups need your yes when the question is about you.** If a
question is personal or sensitive, or your documents answer it, and it would
also need a public source, the answer is written without the lookup and
offers *Also search public sources*, with the names that would be sent. The
yes covers that question only. *Explore processing → What left this
computer* shows the scope (personal or project) and the consent.

## 2. Explore processing

*Explore processing* under an answer opens **How this answer was made**:

- **Readouts** — executed locally or distributed, privacy tier, content
  lane, micro-tasks, context ratio ρ, total time, effective coverage,
  similarity method. Each is labelled *measured*, *estimated* or *unknown*.
- **Pipeline** — the 14 stages drawn as a DNA strand. Each is *completed*,
  *partial*, *skipped* or *failed*, with its own details. A stage that did not
  apply is *skipped*, never shown as completed. *Verification* is *partial* on
  purpose: signatures are checked, while the Layer-1 commitment has no
  normative construction yet.
- **Attempts** — every micro-task attempt: task, why it was sent (first
  attempt, hedge or retry), node, model family, status, time and error code.
- **Consensus** — units where replicas agreed strongly, moderately or weakly.
- **Seams** — how the pieces were joined, with their similarity scores.
- **Caveats** — what the numbers do not mean.
- **Report** — download or save the record as JSON, Markdown or HTML, at the
  detail level chosen in Settings → Results.

## 3. Swarm

**Local network** turns discovery on or off (it asks for permission the first
time). **Search now** sends a fresh query. **Connect by address** joins a
computer directly when your network blocks discovery; its identity is still
verified.

- **Health** — discovered, connected and authenticated nodes, free and busy
  workers, unreachable nodes, model families, latency, uptime, shared
  requests and micro-tasks.
- **Map** — this computer in the centre with its local models, peers around
  it. A pulse travels along a link only when a real micro-task is sent to that
  node.
- **Peers** — each node's address, state, role, models, latency and tasks in
  flight.
- **Discovery cache** — every announcement with first seen, last confirmed and
  expiry times.
- **Your contribution** — tasks served for others, processing time, tokens,
  data in and out, shared models. Your own requests are not counted.

### Sharing this computer

**Share this computer** makes your node a worker that serves micro-tasks for
others. Settings → Swarm controls it:

| Setting | Meaning |
|---|---|
| Models offered to others | Which installed models workers may use (default: your chat model) |
| Tasks at once | Simultaneous micro-tasks |
| Tokens per task | Upper bound on each answer |
| Maximum seconds per task | Generation stops at the deadline |
| Only when idle | Serve only while the processor is mostly idle |
| Only when plugged in | Serve only on mains power |
| Pause sharing | Stop serving without leaving the swarm |

Workers serve the base model only. Your memory, sources and conversations are
never used for other people's tasks.

### Trusted circles · Círculos de confianza

A **circle** is a list of members signed by its owner. Each version has a
number and an expiry date, and it is the only thing that authorises a peer:

1. **Create** a circle in **Swarm → Trusted circles** and give it a name (for
   example *Familia* or *Lab*). This device is the owner.
2. **Invite** a node: the app shows a code (`SWC1…`) and a QR. Send either to
   the other person. The invitation is signed, expires (7 days by default) and
   can be used once.
3. **Accept** on the other device: paste the code in **Swarm → Trusted
   circles → Accept invitation**. The device sends a signed join request. If
   the owner is offline the request is kept and sent when it is reachable.
4. **Approve** the request on the owner's device. The owner signs a new
   manifest version and sends it to the newcomer; both nodes then list each
   other.
5. **Members** shows every node, its endpoints and its role. The owner can
   **revoke** a member (a new version without it) or delete the circle; a
   member can **leave**. Revocation is checked again for every task, so it
   takes effect even on a connection that was already open. Older manifest
   versions are rejected.

**Who may connect.** New installations admit a peer only when both nodes are in
a valid, unexpired circle manifest (*Only my circles*). An installation that
already existed before 3.5 keeps the old LAN rule (*My own devices*, any
authenticated peer on the LAN) and shows a notice in Swarm until you choose.
Change it in **Settings → Swarm → Peer admission**. **Accepting an invitation
is not membership yet**: the owner must approve it, and until then the
connection can only carry the join request, never a task.

The circle does not change the privacy tier or the receipt yet: peer traffic
is still labelled `OWN_NETWORK` and the `CIRCLE` destination class with its
egress gate arrives in WP2. Keep the node key private: 3.5 has no mutual TLS,
so a stolen key can impersonate a member until the owner revokes it.

## 4. Memory

The Local Cognitive Extension keeps a personal memory on this computer. It is
optional and never changes what other nodes receive.

| Level | Adds | In this version |
|---|---|---|
| C0 | Nothing: Swarmbly without the extension | Active |
| C1 | Your sources, retrieval over them, a wiki recording where each claim came from | Selectable; the source folder is prepared, retrieval in answers comes next |
| C2 | Automatic digestion of sources | Later phase |
| C3 | Social capsules between nodes | Later phase |
| C4 | Personal fine-tuning (LoRA) | Experimental upstream, no verdict |

Each level lists its requirements and whether this computer meets them.
**Your sources** opens the folder where documents go; they are read, never
modified.

## 5. Settings

The **Profile** at the top chooses how much you see: *Automatic* (the
recommended configuration), *Custom* (everyday settings) or *Advanced* (every
parameter). Every change is validated and saved at once.

| Tab | Contents |
|---|---|
| Recommended | What was measured on this computer, the proposed values with reasons, *Apply* and *Revert* |
| General | Language (English / Spanish), theme, reduced motion, output folder |
| Models | Model runner and address, chat model, several local models, answer limits, similarity method, downloads |
| Swarm | Default mode, local network, minimum and maximum responses per micro-task, fragments, timeouts, sharing this computer |
| Privacy | Privacy tier (LOCAL, GLOBAL; TRUSTED is answered locally until mutual TLS exists) |
| Results | Export format, report detail, saving a report for every shared request, export folder |
| Permissions | Local-network discovery, model downloads (internet swarms later) |
| System | The same system check as the first-run assistant, with consented installs |

**Minimum and maximum responses per micro-task.** The minimum is how many
replicas go out from the start; two or more give a map of where models
disagree, at a proportional cost. The maximum is the ceiling including extra
attempts for slow or failed workers.

**Downloads.** Settings → Models lists suggested models with size and licence.
With the download permission on, *Download* asks for confirmation and Ollama
does the rest; progress shows in the app and can be cancelled. Some licences
restrict commercial use; the dialog says so.

## 6. Without a window (headless)

```bash
./launch.sh --headless                        # or: swarmbly-app headless
swarmbly-app config set swarm.worker_enabled true
swarmbly-app config set swarm.lan_enabled true
swarmbly-app config set model.model_name llama3.2:3b
```

Useful for a second computer or a Raspberry Pi that only lends compute.
`swarmbly-app status` prints version, node id and data directory.

## 7. Keyboard and accessibility

Every control is reachable with the keyboard and shows a visible focus ring;
*Skip to content* is the first tab stop. *Reduce motion* (Settings → General,
or your system preference) turns off pulses and animations. The theme is dark
by default; a light theme is in Settings → General.

---

## Español

La app tiene cuatro vistas: **Chat**, **Swarm**, **Memory** y **Settings**.
La tarjeta del nodo muestra tu identidad, modo por defecto, nivel de
privacidad, red local, pares y si compartes tu equipo; el panel **Current
request** sigue la solicitud en curso etapa por etapa.

**Chat.** Modos: *Local* (solo este equipo), *Swarm LAN* (las solicitudes con
ítems pueden compartirse con equipos autenticados de tu red; lo demás se
responde localmente), *Automatic* (solo si la solicitud se divide limpiamente
y hay workers) y *Swarm Internet* (Fase 3). Para compartir hacen falta un modo
de enjambre **y** el nivel de privacidad GLOBAL (Settings → Privacy); con
LOCAL, que es el valor por defecto, nada se envía. Solo se fragmentan
solicitudes con estructura (listas de ítems, preguntas ligadas a su
material); la prosa libre y los mensajes con adjuntos se responden
localmente. Las etiquetas bajo cada respuesta indican dónde se ejecutó,
cuántos fragmentos o réplicas hubo, el acuerdo (convergencia, no exactitud),
el modelo y el tiempo.

**Explorar el procesamiento.** Muestra lecturas etiquetadas como *medidas*,
*estimadas* o *desconocidas*; las 14 etapas como una hebra de ADN (una etapa
que no aplica aparece *omitida*, nunca completada; la verificación es
*parcial* a propósito); cada intento con su nodo y familia; el consenso; las
costuras; las advertencias; y un reporte en JSON, Markdown o HTML.

**Swarm.** Activa la red local, busca, o conecta por dirección cuando la red
bloquea el descubrimiento. Salud, mapa (un pulso solo cuando se envía una
microtarea real), pares, caché de descubrimiento y tu contribución.
**Compartir este equipo** lo convierte en worker: eliges modelos, tareas
simultáneas, tokens y segundos por tarea, solo inactivo o conectado a la
corriente, y puedes pausar. Los workers sirven solo el modelo base; tu
memoria y tus archivos nunca se usan.

**Círculos de confianza.** Un círculo es una lista de miembros firmada por su
dueño, con número de versión y caducidad. En **Swarm → Círculos de confianza**
puedes crear uno, invitar a otro nodo (código `SWC1…` o QR, de un solo uso y
con caducidad), aceptar una invitación y aprobar la solicitud de unión. El
dueño firma una nueva versión del manifiesto al aprobar o revocar; los miembros
se listan con sus endpoints y roles, y una revocación se comprueba otra vez en
cada tarea, aunque la conexión ya estuviera abierta. Las versiones antiguas se
rechazan. Una instalación nueva solo admite pares que estén en un manifiesto
vigente (*Solo mis círculos*); una instalación anterior a 3.5 conserva la regla
LAN de 3.4 (*Mis propios dispositivos*) y muestra un aviso hasta que elijas en
**Ajustes → Swarm → Admisión de pares**. Aceptar una invitación no da
membresía: el dueño tiene que aprobarla y, hasta entonces, la conexión solo
puede llevar la solicitud, nunca una tarea. El recibo todavía etiqueta el
tráfico entre pares como `OWN_NETWORK`; la clase `CIRCLE` y su puerta de salida
llegan en WP2. Sin TLS mutuo en 3.5, protege la clave del nodo: una clave
robada puede suplantar a un miembro hasta que el dueño lo revoque.

**Memory.** C0 activa; C1 recupera pasajes de tus fuentes para las
respuestas hechas en este equipo; C2–C4 en fases posteriores.

**Proyectos** (sobre la conversación). Un proyecto es una carpeta tuya, por
defecto `Documentos/Swarmbly/<Proyecto>`, con `sources/` (documentos),
`memory/` (glosario y notas), `chats/` (las conversaciones, una por archivo)
y `exports/` (paquetes `.swarmbly`). Una conversación del proyecto solo lee
sus documentos y su memoria; tus fuentes personales se añaden solo si marcas
*Incluir mis fuentes personales*, y una conversación personal nunca lee un
proyecto. *Exportar .swarmbly* guarda documentos, memoria y chats con el
SHA-256 de cada archivo y nunca lleva claves API. *Restaurar* comprueba cada
hash antes de escribir y restaura en una carpeta nueva; en otra computadora
vuelven los chats y sus citas siguen apuntando al párrafo correcto. *Cerrar
proyecto* lo quita de la app y deja la carpeta. Si la carpeta está
sincronizada (iCloud, Dropbox, OneDrive, Google Drive), la app te avisa. Para que el proyecto recuerde algo, empieza el mensaje con *Recuerda:* o
*Memoriza*: la app lo guarda, con fecha, en `memory/notas.md` antes de
responder (en una conversación personal, en `notas.md` de tus fuentes), y las
siguientes respuestas lo encuentran. *Documentos* muestra qué puede leer el
proyecto y por qué un archivo no dio nada. Si pides recordar algo en medio
de un mensaje, o defines o corriges un término, aparece una propuesta de
memoria y glosario bajo la respuesta: la editas y la confirmas con *Guardar
en memoria*; una entrada marcada *Privado* (o `| privado`) no se usa en
búsquedas públicas, aunque las respuestas locales sí la usan. Para buscar en
internet, la respuesta ofrece *Buscar en línea*
con el texto exacto que se enviaría a PubMed y Wikipedia; lo revisas y lo
apruebas. Una etiqueta que no corresponde a ninguna fuente se marca como
*cita sin fuente*.

**Consultas públicas con tu sí.** Si la pregunta trata de ti o de tus
documentos y además pediría una fuente pública, la respuesta se escribe sin
consultarla y ofrece *Buscar también en fuentes públicas*, con los nombres
que se enviarían; el sí vale solo para esa pregunta.

**Settings.** Perfiles *Automatic*, *Custom* y *Advanced*; pestañas
Recommended, General, Models, Swarm, Privacy, Results, Permissions y System.
Mínimo de respuestas por microtarea = réplicas desde el inicio; máximo =
techo incluyendo intentos extra. Las descargas muestran tamaño y licencia y
requieren el permiso correspondiente.

**Sin ventana:** `./launch.sh --headless` y `swarmbly-app config set …` para
equipos que solo prestan cómputo. **Accesibilidad:** todo es operable con
teclado, con foco visible; *Reduce motion* desactiva las animaciones.
