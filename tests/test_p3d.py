"""Fixes from the P3d round on the five-machine network (22 October 2026)."""

from __future__ import annotations

from swarmbly_app.engine import composer
from swarmbly_app.engine.contract import build_contract
from swarmbly_app.engine.orchestrator import _normalise_items, _parse_items, _vote_items

REPORT_ES = ("Escribe un informe de unas 500 palabras sobre las ventajas y riesgos de la "
             "energía solar en zonas rurales de Ecuador, en registro profesional, con una "
             "introducción, tres secciones y una conclusión.")
CAPITALS_ES = ("Para cada uno de los siguientes países, indica solo el nombre de su "
               "capital:\n1. Ecuador\n2. Perú\n3. Chile\n4. Argentina\n5. Colombia\n"
               "6. Uruguay\n7. Paraguay\n8. Venezuela")


# -- item answers -----------------------------------------------------------------
def test_renumbered_echo_with_its_own_label_is_not_an_answer():
    """'1. 7. libro' is item 7 echoed, not a translation (accepted in P3d.1)."""
    items = {7: "libro", 8: "árbol"}
    assert _parse_items("1. 7. libro\n2. 8. tree", items) == {8: "tree"}


def test_label_followed_by_markdown_star():
    """'7.* Asunción' was shown as '7. 7.* Asunción'."""
    items = {7: "Paraguay", 8: "Venezuela"}
    assert _parse_items("7.* Asunción\n8.** Caracas", items) == {7: "Asunción",
                                                                 8: "Caracas"}


def test_decimals_are_not_taken_for_labels():
    items = {1: "1500 m", 2: "250 m"}
    assert _parse_items("1. 1.5 km\n2. 0.25 km", items) == {1: "1.5 km", 2: "0.25 km"}


def test_positional_reading_needs_unlabelled_lines():
    """A labelled echo plus a stray line must not become 'item 20 = the stray line'."""
    items = {19: "grande", 20: "pequeño"}
    assert _parse_items("19. grande - grande\n\nEn formato markdown, esto se vería así:",
                        items) == {}


def test_rejected_replica_text_is_not_shown():
    items = {19: "grande", 20: "pequeño"}
    junk = "19. grande - grande\n\nEn formato markdown, esto se vería así:\n```"
    out = _normalise_items(junk, items, "es", rejected=True)
    assert out.splitlines() == ["19. grande — (sin respuesta verificada)",
                                "20. pequeño — (sin respuesta verificada)"]
    assert _normalise_items("Todas son aves.", items, "es") == "Todas son aves."


def test_vote_marks_items_nobody_answered():
    from swarmbly_app.engine.scheduler import Replica
    items = {1: "Ecuador", 2: "Perú", 3: "Chile"}
    reps = [Replica("1. Quito\n2. Lima", "n1", "a", "a", 1),
            Replica("1. Quito\n2. Lima", "n2", "b", "b", 1)]
    text, report = _vote_items(reps, items, [0, 1], "es")
    assert text.splitlines()[-1] == "3. Chile — (sin respuesta verificada)"
    assert report["missing_items"] == [3]


# -- whole-replica selection by length ---------------------------------------------
def test_replica_near_the_section_target_wins(app_state):
    from swarmbly_v0 import HashEmbedder
    from swarmbly_app.engine.orchestrator import Orchestrator
    from swarmbly_app.engine.scheduler import Replica
    short = "Las islas Galápagos son únicas. " * 6          # 30 words
    right = "Las islas Galápagos son únicas y frágiles. " * 17   # ~119 words
    orch = Orchestrator(app_state.nodes, app_state.bus, None, app_state.config.all)
    out = orch._resolve("t1", [Replica(short, "n1", "gemma2", "g", 5),
                               Replica(right, "n2", "llama", "l", 6)],
                        build_contract(REPORT_ES).contract, HashEmbedder(),
                        policy="whole", lang="es", target_words=120)
    assert out["text"] == right
    sel = out["consensus"]["selection"]
    assert sel["target_words"] == 120 and [c["length_fits"] for c in sel["candidates"]] == [False, True]


# -- section count ------------------------------------------------------------------
def test_requested_sections():
    assert composer.requested_sections(REPORT_ES) == 5
    assert composer.requested_sections("Redacta un ensayo en tres secciones: introducción, "
                                       "desarrollo y conclusión.") == 3
    assert composer.requested_sections("Write a report in 4 sections.") == 4
    assert composer.requested_sections("Redacta un artículo de 600 palabras.") is None
    assert "Exactly 5 sections" in composer.outline_prompt(REPORT_ES, "es", 500, 6, 5)


def _outline(*specs):
    return composer.Outline("T", "energía solar", "",
                            [composer.Section(h, "x", w, kind=k) for h, w, k in specs],
                            "local_model")


def test_missing_section_is_added_before_the_closing():
    o = _outline(("Introducción", 107, "prose"), ("Ventajas", 143, "prose"),
                 ("Riesgos", 143, "prose"), ("Conclusión", 107, "prose"))
    composer._ensure_section_count(o, 5, "es", 500)
    heads = [s.heading for s in o.sections]
    assert len(heads) == 5 and heads[0] == "Introducción" and heads[-1] == "Conclusión"
    assert heads[1:3] == ["Ventajas", "Riesgos"]
    assert abs(sum(s.words for s in o.sections) - 500) <= 10
    assert o.adjustments and "5" in o.adjustments[-1]


def test_extra_sections_are_folded_and_tables_not_counted():
    o = _outline(("A", 100, "prose"), ("B", 100, "prose"), ("C", 50, "prose"),
                 ("Tabla", 120, "table"), ("D", 100, "prose"), ("E", 100, "prose"))
    composer._ensure_section_count(o, 4, "es", 500)
    assert [s.heading for s in o.sections] == ["A", "B", "Tabla", "D", "E"]
    assert "C" in o.sections[1].key_points            # folded, not lost


class _Backend:
    def __init__(self, raw):
        self.raw = raw

    def generate(self, prompt, max_tokens, temperature):
        return self.raw


def test_make_outline_honours_the_requested_count():
    import json
    raw = json.dumps({"title": "Energía solar rural", "topic": "energía solar",
                      "style": "profesional", "sections": [
                          {"heading": "Introducción", "purpose": "abre", "words": 100},
                          {"heading": "Ventajas", "purpose": "v", "words": 150},
                          {"heading": "Riesgos", "purpose": "r", "words": 150},
                          {"heading": "Conclusión", "purpose": "cierra", "words": 100}]})
    o = composer.make_outline(REPORT_ES, build_contract(REPORT_ES).contract, "es", 500,
                              _Backend(raw), 6)
    assert len(o.sections) == 5 and o.source == "local_model"


# -- local rescue without the contract header ---------------------------------------
def test_local_rescue_retries_the_bare_task(tmp_path):
    """P3d.1: the 3B model echoed a fragment wrapped in the contract and
    answered the same fragment without it."""
    from test_p2p_two_nodes import connect, make_node
    answers = ("1. Quito\n2. Lima\n3. Santiago\n4. Buenos Aires\n5. Bogotá\n"
               "6. Montevideo\n7. Asunción\n8. Caracas")
    echo = "\n".join(f"{n}. {c}" for n, c in enumerate(
        ["Ecuador", "Perú", "Chile", "Argentina", "Colombia", "Uruguay", "Paraguay",
         "Venezuela"], 1))
    worker, _ = make_node(tmp_path, "W", worker=True, reply="No lo sé.")
    client, fake = make_node(tmp_path, "C", reply=answers,
                             extra={"swarm": {"k_min": 1, "k_max": 1}})
    original = fake.stream_chat
    seen = []

    def stream_chat(messages, **kw):
        prompt = " ".join(str(m.get("content", "")) for m in messages)
        seen.append("[CONTRATO GLOBAL]" in prompt)
        fake.reply = echo if "[CONTRATO GLOBAL]" in prompt else answers
        return original(messages, **kw)

    fake.stream_chat = stream_chat
    try:
        connect(client, worker)
        conv = client.chat.create_conversation(mode="lan")
        client.chat.send(conv["id"], CAPITALS_ES, mode="lan", run_async=False)
        final = client.chat.get_messages(conv["id"])[-1]
        assert final["meta"]["status"] == "done", final["meta"]
        assert final["meta"]["swarm"]["local_fallback_tasks"]
        assert "Quito" in final["content"] and "No lo sé" not in final["content"]
        assert True in seen and False in seen         # packet first, then bare task
    finally:
        worker.stop()
        client.stop()


def test_item_texts_drop_the_upstream_suffix():
    from swarmbly_app.engine.orchestrator import _item_texts
    text = ("Convierte:\n\n7. 100 m\n8. 7000 m Close the answer; do not repeat "
            "earlier parts.")
    assert _item_texts(text) == {7: "100 m", 8: "7000 m"}


def test_unrequested_table_is_removed_and_count_kept():
    """P3e.2: the report asked for no table and got one."""
    import json
    raw = json.dumps({"title": "Energía solar rural", "topic": "energía solar",
                      "style": "profesional", "sections": [
                          {"heading": "Introducción", "purpose": "abre", "words": 60},
                          {"heading": "Ventajas", "purpose": "v", "words": 90},
                          {"heading": "Riesgos", "purpose": "r", "words": 80},
                          {"heading": "Tabla de costos", "purpose": "t", "words": 120,
                           "kind": "table", "key_points": ["costos"]},
                          {"heading": "Conclusión", "purpose": "cierra", "words": 60}]})
    o = composer.make_outline(REPORT_ES, build_contract(REPORT_ES).contract, "es", 500,
                              _Backend(raw), 6)
    assert [s.kind for s in o.sections] == ["prose"] * 5
    assert "costos" in o.sections[2].key_points
    assert any("table section removed" in a for a in o.adjustments)
