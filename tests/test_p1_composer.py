"""P1: composition planner (outline on the local model, sections on workers)."""

from __future__ import annotations

import json

import pytest

from swarmbly_app.engine import composer
from swarmbly_app.engine.contract import build_contract

from test_p0_quality import ESSAY_ES

OUTLINE = {
    "title": "Ecuador y las Galápagos: un laboratorio vivo",
    "topic": "Ecuador y las islas Galápagos",
    "style": "español neutro, tono divulgativo, sin listas",
    "sections": [
        {"heading": "Presentación", "purpose": "Andrea presenta el tema", "words": 120,
         "key_points": ["presentadora", "idea central"],
         "must_include": ["presentación de Andrea"], "kind": "prose"},
        {"heading": "Biodiversidad", "purpose": "Especies endémicas", "words": 200,
         "key_points": ["endemismo"], "must_include": [], "kind": "prose"},
        {"heading": "Conservación", "purpose": "Retos y políticas", "words": 200,
         "key_points": ["turismo"], "must_include": [], "kind": "prose"},
        {"heading": "Tabla de resumen", "purpose": "Datos clave", "words": 50,
         "key_points": [], "must_include": ["tabla de resumen"], "kind": "table"},
        {"heading": "Cierre", "purpose": "Síntesis y reflexión", "words": 150,
         "key_points": [], "must_include": [], "kind": "prose"},
    ],
}


class _Backend:
    def __init__(self, out):
        self.out, self.prompts = out, []

    def generate(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.out


def _outline(raw):
    rc = build_contract(ESSAY_ES)
    return composer.make_outline(ESSAY_ES, rc.contract, rc.lang, rc.target_words,
                                 _Backend(raw), 6)


class TestOutline:
    def test_valid_outline_is_used_and_rescaled(self):
        o = _outline("```json\n" + json.dumps(OUTLINE, ensure_ascii=False) + "\n```")
        assert o.source == "local_model" and len(o.sections) == 5
        prose = [s for s in o.sections if s.kind == "prose"]
        assert abs(sum(s.words for s in prose) - (800 - composer.TABLE_SECTION_WORDS)) <= 4
        assert o.sections[3].kind == "table"
        assert o.sections[3].words == composer.TABLE_SECTION_WORDS

    def test_trailing_commas_tolerated(self):
        raw = json.dumps(OUTLINE, ensure_ascii=False).replace('"kind": "prose"}', '"kind": "prose",}')
        assert _outline(raw).source == "local_model"

    def test_prompt_asks_for_spanish_values_and_has_the_request(self):
        backend = _Backend(json.dumps(OUTLINE))
        rc = build_contract(ESSAY_ES)
        composer.make_outline(ESSAY_ES, rc.contract, "es", 800, backend, 6)
        assert "written in Spanish" in backend.prompts[0]
        assert "Criterios de calidad" in backend.prompts[0]    # the whole request, locally

    @pytest.mark.parametrize("raw", ["", "no JSON here", '{"sections": [{"heading": "x"}]}'])
    def test_unusable_output_falls_back(self, raw):
        o = _outline(raw)
        assert o.source == "fallback" and o.errors
        assert o.topic == "Ecuador y Las Islas Galapagos"      # no "800 palabras"
        assert any(s.kind == "table" for s in o.sections)      # the request asks for tables
        assert "Andrea" in " ".join(o.sections[0].must_include)
        assert o.sections[-1].kind == "prose"

    def test_table_never_opens_or_closes(self):
        data = dict(OUTLINE, sections=OUTLINE["sections"][3:] + OUTLINE["sections"][:3])
        o = _outline(json.dumps(data, ensure_ascii=False))
        assert o.sections[0].kind == "prose" and o.sections[-1].kind == "prose"


class TestBriefs:
    def test_brief_is_a_section_not_the_request(self):
        o = _outline(json.dumps(OUTLINE, ensure_ascii=False))
        briefs = [composer.section_instruction(o, i, "es") for i in range(len(o.sections))]
        assert briefs[0].startswith("Escribe la sección 1 de 5")
        assert "Es la apertura" in briefs[0]
        assert "transición" in briefs[1] and "«Presentación»" in briefs[1]
        assert "tabla en Markdown" in briefs[3]
        assert "conclusión" in briefs[4]
        for b in briefs:
            assert "Criterios de calidad" not in b and "800" not in b
            assert "Andrea" not in b or b is briefs[0]          # requirement only where it belongs

    def test_clean_section_and_assemble(self):
        o = _outline(json.dumps(OUTLINE, ensure_ascii=False))
        raw = "## Biodiversidad\n\nLas islas albergan especies únicas."
        assert composer.clean_section(raw, o.sections[1], o.title) == \
            "Las islas albergan especies únicas."
        table = "| Isla | Dato |\n|---|---|\n| Isabela | grande |"
        assert composer.clean_section(table, o.sections[3], o.title) == table
        text = composer.assemble(o, ["A.", "B."])
        assert text.startswith("# Ecuador y las Galápagos") and text.endswith("A.\n\nB.")

    def test_requirement_report(self):
        o = _outline(json.dumps(OUTLINE, ensure_ascii=False))
        rep = composer.requirement_report(o, "Hola, soy Andrea.\n\n| a | b |\n|---|---|")
        assert rep["checks"][0]["found"] is True
        assert rep["tables_requested"] and rep["table_rows"] == 2


class TestOrchestratorComposition:
    def _orch(self, app_state, local=None):
        from swarmbly_app.engine.orchestrator import Orchestrator
        return Orchestrator(app_state.nodes, app_state.bus, local, app_state.config.all,
                            local_model="m" if local else "")

    def test_applies_only_to_long_compositions_with_a_planner(self, app_state):
        from swarmbly_app.engine.admission import admit
        cfg = {"composer_enabled": True, "composer_min_words": 400}
        orch = self._orch(app_state, local=object())
        adm = admit(ESSAY_ES, n_max=4, n_workers=2)
        assert orch._composer_applies(ESSAY_ES, adm, cfg, workers=[object()])
        assert not orch._composer_applies(ESSAY_ES, adm, cfg, workers=[])
        assert not orch._composer_applies(ESSAY_ES, adm, dict(cfg, composer_enabled=False),
                                          workers=[object()])
        short = "Escribe un poema de 100 palabras sobre el mar."
        assert not orch._composer_applies(short, admit(short, n_max=4, n_workers=2), cfg,
                                          workers=[object()])
        assert not self._orch(app_state)._composer_applies(ESSAY_ES, adm, cfg,
                                                           workers=[object()])


def test_end_to_end_composition_on_two_nodes(tmp_path):
    """Real TLS nodes: the client plans (fake local model), the worker writes."""
    from test_p2p_two_nodes import connect, make_node
    worker, fake_w = make_node(tmp_path, "W", worker=True,
                               reply="Las islas guardan especies únicas en el mundo.")
    client, fake_c = make_node(tmp_path, "C", reply=json.dumps(OUTLINE, ensure_ascii=False),
                               extra={"swarm": {"max_concurrency": 4}})
    try:
        connect(client, worker)
        conv = client.chat.create_conversation(mode="lan")
        client.chat.send(conv["id"], ESSAY_ES, mode="lan", run_async=False)
        final = client.chat.get_messages(conv["id"])[-1]
        swarm = final["meta"]["swarm"]
        assert final["meta"]["executed"] == "distributed", final["meta"]
        assert swarm["router"]["composition"] is True
        assert swarm["n_tasks"] == 5
        assert swarm["composition"]["outline"]["source"] == "local_model"
        assert final["content"].startswith("# Ecuador y las Galápagos")
        prompts = [c["messages"][-1]["content"] for c in fake_w.calls]
        assert len(prompts) >= 5
        for p in prompts:
            assert "Criterios de calidad" not in p          # decontextualised
            assert "800 palabras" not in p
            assert "[CONTRATO GLOBAL]" in p and "Responde en español." in p
        assert swarm["max_packet_prompt_fraction"] < 0.5
    finally:
        worker.stop()
        client.stop()
