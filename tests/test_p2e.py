"""P2e: cross-language C1 retrieval and public evidence for local answers."""

from __future__ import annotations

from swarmbly_app.lce_adapter import _paragraphs, _tokens
from swarmbly_app.local_context import (Expansion, binomials, parse_expansion,
                                        public_entities, render_public)
from swarmbly_app.engine.evidence import WikipediaEvidence


def _write(state, name, text):
    state.dirs.sources.mkdir(parents=True, exist_ok=True)
    (state.dirs.sources / name).write_text(text, encoding="utf-8")


def test_tokens_fold_accents_drop_function_words_and_plurals():
    assert _tokens("¿Cuántos cucuves de las islas Galápagos?") == ["cucuve", "isla", "galapago"]
    assert _tokens("I+D en la PUCE") == ["i+d", "puce"]


def test_paragraphs_index_file_name_title_and_heading_not_as_spans():
    text = "# Chapter 2: genome assembly\n\nMethods\n\nWe used Supernova to assemble the genome."
    spans = _paragraphs("02_tesis_genoma.md", text, label="tesis/02_tesis_genoma.md")
    assert [s["text"] for s in spans] == ["We used Supernova to assemble the genome."]
    assert "tesis" in spans[0]["index"] and "Chapter 2" in spans[0]["index"] \
        and "Methods" in spans[0]["index"]


def test_long_paragraph_is_cut_at_a_sentence_end():
    body = ("Sentence one is here. " * 40).strip()
    spans = _paragraphs("a.md", body)
    assert all(len(s["text"]) <= 600 for s in spans) and spans[0]["text"].endswith(".")


def test_expansion_lets_a_spanish_question_reach_an_english_source(app_state):
    _write(app_state, "tesis_cap2.md", "A total of 139 individual Galapagos mockingbirds were "
           "sampled from six different islands.\n\nThe weather was dry in 2017.")
    _write(app_state, "notas.md", "Receta de pan: harina, agua y sal.")
    q = "¿Cuántos cucuves se muestrearon?"
    assert not app_state.lce.retrieve(q)
    hits = app_state.lce.retrieve(q, expansion="mockingbirds sampled total individuals")
    assert hits and "139" in hits[0]["text"]


def test_duplicate_paragraphs_are_returned_once(app_state):
    _write(app_state, "a.md", "The Supernova assembler built the genome.")
    _write(app_state, "b.md", "The Supernova assembler built the genome.")
    assert len(app_state.lce.retrieve("Supernova genome")) == 1


def test_parse_expansion_and_binomials():
    e = parse_expansion("Keywords: IUCN, conservation status, Mimus melanotis || "
                        "San Cristobal mockingbird; San Cristobal Island")
    assert e.keywords.startswith("IUCN") and e.entities == ["San Cristobal mockingbird",
                                                           "San Cristobal Island"]
    assert parse_expansion("only words without a bar").entities == []
    assert binomials("Según Mimus melanotis y Laterallus spilonota; Mimus species") == \
        ["Mimus melanotis", "Laterallus spilonota"]


def test_public_entities_come_from_the_question_or_species_names_in_passages():
    exp = Expansion(keywords="parasite epigenetics", entities=["Galapagos"])
    passages = [{"text": "We studied the invasive Philornis downsi in nests of AB1 owners at "
                         "AcmeLabs."}]
    picked = public_entities("¿Qué parásito estudié en mi artículo de 2021?", exp, passages)
    names = [p["name"] for p in picked]
    assert names == ["Philornis downsi"]          # "Galapagos" is not in the question
    assert picked[0]["from"].startswith("local passage")
    assert not any("AcmeLabs" in n or "AB1" in n for n in names)   # only scientific names cross


def test_passages_keep_first_sentence_and_focus_sentences_outside_the_intro():
    article = ("The San Cristóbal mockingbird (Mimus melanotis) is a species of bird. "
               "== Distribution == It lives on San Cristóbal Island. "
               "== Status == The IUCN has assessed the San Cristóbal mockingbird as Near "
               "Threatened. Prior to 2020 it was classified as Endangered.")
    seen = []

    def fetch(url, timeout, ua):
        seen.append(url)
        return {"query": {"pages": {"1": {"title": "San Cristóbal mockingbird",
                                          "extract": article}}}}
    hit = WikipediaEvidence(lang="en", fetch=fetch).passages(
        "Mimus melanotis", ["iucn", "conservation", "status", "endangered"])
    assert hit["text"].startswith("The San Cristóbal mockingbird")
    assert "Near Threatened" in hit["text"] and "Endangered" in hit["text"]
    assert "==" not in hit["text"] and "exintro" not in seen[0]


def test_local_answer_with_public_evidence_sends_only_names(app_state, fake_chat):
    chat, fake = fake_chat
    _write(app_state, "tesis.md", "M. melanotis (IUCN: endangered), the San Cristobal "
           "mockingbird; Mimus melanotis was sequenced from sample AB1.")
    app_state.config.update({"lce": {"enabled": True, "level": "C1"},
                             "evidence": {"enabled": True}})
    fake.reply = "IUCN, endangered, Mimus melanotis, mockingbird || San Cristobal mockingbird"
    asked = []

    class Provider:
        lang = "en"

        def passages(self, entity, focus):
            asked.append(entity)
            return {"title": "San Cristóbal mockingbird", "url": "https://en.wikipedia.org/x",
                    "text": "The IUCN has assessed it as Near Threatened."}
    chat.public_provider = Provider()
    conv = chat.create_conversation(mode="local")
    q = "¿Qué categoría UICN da mi tesis a Mimus melanotis y cuál es la actual?"
    chat.send(conv["id"], q, mode="local", run_async=False)
    assert sorted(asked) == ["Mimus melanotis", "San Cristobal mockingbird"]
    assert all(q not in a for a in asked)
    system = [m["content"] for m in fake.calls[-1]["messages"] if m["role"] == "system"]
    assert any("[1] (tesis.md)" in s for s in system)
    assert any("[W1] (San Cristóbal mockingbird)" in s and "solo se enviaron" in s for s in system)
    meta = chat.get_messages(conv["id"])[-1]["meta"]
    assert sorted(meta["evidence"]["queried"]) == sorted(asked) and meta["evidence"]["local_answer"]
    assert meta["lce"]["expansion"]["entities"] == ["San Cristobal mockingbird"]


def test_no_public_lookup_when_evidence_is_off(app_state, fake_chat):
    chat, fake = fake_chat
    app_state.config.update({"lce": {"enabled": True, "level": "C1"}})

    class Provider:
        lang = "en"

        def passages(self, entity, focus):
            raise AssertionError("must not be called")
    chat.public_provider = Provider()
    conv = chat.create_conversation(mode="local")
    chat.send(conv["id"], "¿Qué es Mimus melanotis?", mode="local", run_async=False)
    assert "evidence" not in chat.get_messages(conv["id"])[-1]["meta"]


def test_render_public_lists_what_was_sent():
    out = render_public([{"sent": "Mimus melanotis", "title": "T", "text": "x"}], "es")
    assert "solo se enviaron estos nombres: Mimus melanotis" in out and "[W1] (T) x" in out


def test_model_names_are_sent_only_when_their_words_are_known():
    exp = Expansion(keywords="", entities=["Galapagos rat", "Project Isabela"])
    q = "¿Qué encontramos sobre el rascón de Galápagos y el Proyecto Isabela?"
    passages = [{"text": "Goat eradication on Isabela helped the Galapagos rail; the project ended."}]
    names = [p["name"] for p in public_entities(q, exp, passages)]
    assert names == ["Project Isabela"]           # a 3B model's "rat" for "rascón" stays home


def test_glossary_bridges_terms_and_is_not_a_passage(app_state):
    _write(app_state, "glosario.md", "# Glosario\n\n- cucuve = mockingbird, Mimus\n"
           "- tamaño poblacional efectivo = effective population size, Ne\n")
    _write(app_state, "thesis.md", "The Champion mockingbird population has an effective "
           "population size near 30.")
    assert app_state.lce.glossary_terms("¿Qué tamaño poblacional efectivo tiene el cucuve?") == \
        "mockingbird, Mimus effective population size, Ne"
    hits = app_state.lce.retrieve("¿Qué tamaño poblacional efectivo tiene el cucuve de Champion?")
    assert hits and hits[0]["source"] == "thesis.md"
    assert all(h["source"] != "glosario.md" for h in hits)
