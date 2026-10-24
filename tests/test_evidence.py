"""P2 prototype: public evidence for batch items (off by default)."""

from __future__ import annotations

from swarmbly_app.engine import evidence as ev


def _page(title, extract):
    return {"query": {"pages": {"1": {"title": title, "extract": extract}}}}


def test_which_items_are_looked_up():
    assert ev.qualifies("Piquero de patas azules") and ev.qualifies("Ecuador")
    assert not ev.qualifies("perro") and not ev.qualifies("1500 m")


def test_lookup_keeps_relevant_results_and_attribution():
    seen = []

    def fetch(url, timeout, ua):
        seen.append((url, ua))
        return _page("Sula nebouxii piquero", "El piquero patiazul (Sula nebouxii) es una "
                     "especie de ave suliforme de la familia Sulidae. Vive en el Pacífico.")
    hit = ev.WikipediaEvidence(lang="es", fetch=fetch).lookup("Piquero de patas azules")
    assert hit["text"].startswith("El piquero patiazul") and "es.wikipedia.org" in hit["url"]
    assert "gsrsearch=Piquero+de+patas+azules" in seen[0][0] and "SwarmblyApp" in seen[0][1]


def test_scientific_title_is_accepted_and_disambiguation_dropped():
    sula = lambda url, t, ua: _page("Sula nebouxii", "El pájaro bobo de patas azules "  # noqa
                                    "(Sula nebouxii) es una especie de ave Suliforme.")
    assert ev.WikipediaEvidence(fetch=sula).lookup("Piquero de patas azules")
    lobo = lambda url, t, ua: _page("Lobo marino",                                      # noqa
                                    "El término lobo marino puede referirse a:")
    assert ev.WikipediaEvidence(fetch=lobo).lookup("Lobo marino") is None


def test_irrelevant_title_is_dropped():
    fetch = lambda url, t, ua: _page("Fútbol", "El fútbol es un deporte.")     # noqa: E731
    assert ev.WikipediaEvidence(fetch=fetch).lookup("Piquero de patas azules") is None


def test_long_extract_is_cut_at_a_word():
    fetch = lambda url, t, ua: _page("Ecuador", "Ecuador es un país " + "muy " * 100)  # noqa: E731
    hit = ev.WikipediaEvidence(fetch=fetch, max_chars=60).lookup("Ecuador")
    assert len(hit["text"]) <= 62 and hit["text"].endswith("…")


def test_gather_reports_queries_use_and_errors():
    def fetch(url, t, ua):
        if "Iguana" in url:
            raise TimeoutError()
        return _page("Ecuador", "Ecuador es un país de América del Sur; su capital es Quito.")
    found, report = ev.gather({1: "Ecuador", 2: "Iguana marina", 3: "perro"},
                              ev.WikipediaEvidence(fetch=fetch))
    assert list(found) == [1] and report["queried"] == ["Ecuador", "Iguana marina"]
    assert report["used"] == 1 and report["errors"] == ["TimeoutError"]
    block = ev.render(found, "es")
    assert block.splitlines()[0].startswith("Contexto público (Wikipedia)")
    assert block.splitlines()[1].startswith("- Ecuador: Ecuador es un país")


def test_orchestrator_adds_evidence_only_when_enabled_and_public(tmp_path, monkeypatch):
    from test_p2p_two_nodes import connect, make_node
    monkeypatch.setattr(ev, "_http_get_json", lambda url, t, ua: _page(
        "Ecuador", "Ecuador es un país de América del Sur; su capital es Quito."))
    worker, wfake = make_node(tmp_path, "W", worker=True,
                              reply="1. Quito\n2. Lima\n3. Santiago\n4. Buenos Aires\n"
                                    "5. Bogotá\n6. Montevideo\n7. Asunción\n8. Caracas")
    client, _ = make_node(tmp_path, "C", extra={
        "swarm": {"k_min": 1, "k_max": 1, "min_items_per_fragment": 4},
        "evidence": {"enabled": True}})
    try:
        connect(client, worker)
        conv = client.chat.create_conversation(mode="lan")
        client.chat.send(conv["id"], "Para cada uno de los siguientes países, indica solo "
                         "el nombre de su capital:\n1. Ecuador\n2. Perú\n3. Chile\n"
                         "4. Argentina\n5. Colombia\n6. Uruguay\n7. Paraguay\n8. Venezuela",
                         mode="lan", run_async=False)
        final = client.chat.get_messages(conv["id"])[-1]
        assert final["meta"].get("swarm"), final["meta"]
        report = final["meta"]["swarm"]["evidence"]
        assert report["used"] >= 1 and report["queried"][0] == "Ecuador"
        prompts = [m["content"] for call in wfake.calls for m in call["messages"]]
        assert any("Contexto público (Wikipedia)" in p and "su capital es Quito" in p
                   for p in prompts)
        assert not any("Para cada uno de los siguientes países, indica solo el nombre de su "
                       "capital:\n1. Ecuador\n2. Perú\n3. Chile\n4. Argentina\n5. Colombia" in p
                       for p in prompts)          # the request itself never travels
    finally:
        worker.stop()
        client.stop()


# -- operation-aware lookups (P2d) ----------------------------------------------------
ANIMALS = ("Para cada uno de los siguientes animales, indica en una sola palabra si es "
           "mamífero, ave, reptil, anfibio o pez:")


def _pages(mapping):
    """Fake fetch: the search query (gsrsearch) → (title, lead)."""
    import urllib.parse

    def fetch(url, t, ua):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["gsrsearch"][0]
        title, lead = mapping.get(q, ("", ""))
        return _page(title, lead) if title else {}
    return fetch


def test_profile_of_a_batch_operation():
    p = ev.operation_profile(ANIMALS)
    assert p.query_topic == "animal" and "anfibio" in p.focus and "ave" in p.focus
    p = ev.operation_profile("Para cada uno de los siguientes elementos químicos, indica "
                             "solo su símbolo químico:")
    assert p.focus == ["simbolo"] and p.query_topic == "elemento químico"
    p = ev.operation_profile("Para cada uno de los siguientes países, indica solo el "
                             "nombre de su capital:")
    assert p.query_topic == "país" and p.focus == ["capital"]
    assert ev.operation_profile("Para cada una de las siguientes frases en español, da "
                                "solo su traducción al inglés:").translation


def test_homonym_is_rejected_and_the_search_retried_with_the_topic():
    fetch = _pages({
        "Cecilia": ("Cecilia", "Cecilia es un nombre propio femenino de origen latino."),
        "Cecilia animal": ("Gymnophiona", "Los gimnofiones o cecilias son anfibios grandes "
                                          "sin patas, con forma de lombriz."),
    })
    hit = ev.WikipediaEvidence(fetch=fetch).lookup("Cecilia", ev.operation_profile(ANIMALS))
    assert hit["title"] == "Gymnophiona" and hit["query"] == "Cecilia animal"
    assert "anfibios" in hit["text"]


def test_snippet_takes_the_sentence_with_the_asked_fact():
    profile = ev.operation_profile("Para cada uno de los siguientes países, indica solo el "
                                   "nombre de su capital:")
    fetch = _pages({"Nigeria": ("Nigeria", "Nigeria es un país de África occidental. Lagos "
                                           "es su ciudad más poblada. Su capital es Abuya.")})
    hit = ev.WikipediaEvidence(fetch=fetch).lookup("Nigeria", profile)
    assert hit["text"] == "Nigeria es un país de África occidental. Su capital es Abuya."


def test_neighbouring_fact_does_not_pass_as_the_focus():
    profile = ev.operation_profile("Para cada uno de los siguientes elementos químicos, "
                                   "indica solo su símbolo químico:")
    fetch = _pages({"Plomo": ("Plomo", "El plomo es un elemento químico de número atómico "
                                       "82. Su símbolo es Pb, del latín plumbum.")})
    hit = ev.WikipediaEvidence(fetch=fetch).lookup("Plomo", profile)
    assert "Su símbolo es Pb" in hit["text"]


def test_implicit_disambiguation_and_translation_are_skipped():
    profile = ev.operation_profile("Para cada uno de los siguientes elementos químicos, "
                                   "indica solo su símbolo químico:")
    fetch = _pages({
        "Mercurio": ("Mercurio", "El término mercurio puede hacer referencia a: Mercurio "
                                 "(elemento), Mercurio (planeta)."),
        "Mercurio elemento químico": ("Mercurio (elemento)", "El mercurio es un elemento "
                                      "químico con el símbolo Hg y número atómico 80."),
    })
    hit = ev.WikipediaEvidence(fetch=fetch).lookup("Mercurio", profile)
    assert hit["title"] == "Mercurio (elemento)"
    found, report = ev.gather({1: "Buenos días"}, ev.WikipediaEvidence(fetch=fetch), 24,
                              ev.operation_profile("Para cada una de las siguientes frases "
                                                   "en español, da solo su traducción al "
                                                   "inglés:"))
    assert found == {} and report["skipped"].startswith("translation")


def test_unasked_figures_are_dropped_from_the_snippet():
    """P2d: 'cuyo símbolo es Pb … y su número atómico es 82' → answers 82, 80, 50."""
    e3 = ev.operation_profile("Para cada uno de los siguientes elementos químicos, indica "
                              "solo su símbolo químico:")
    assert ev.drop_unasked_numbers(
        e3, "El mercurio es un elemento químico con el símbolo Hg y número atómico 80."
    ) == "El mercurio es un elemento químico con el símbolo Hg."
    e2 = ev.operation_profile("Para cada uno de los siguientes países, indica solo el "
                              "nombre de su capital:")
    assert ev.drop_unasked_numbers(e2, "Nigeria tiene 220 millones de habitantes. Su capital "
                                       "es Abuya, y Lagos tiene 15 millones.") == "Su capital es Abuya."
    e5 = ev.operation_profile("Para cada uno de los siguientes acontecimientos históricos, "
                              "indica solo el año en que ocurrió:")
    text = "La batalla ocurrió el 24 de mayo de 1822."
    assert ev.drop_unasked_numbers(e5, text) == text          # a year is what is asked
    e4 = ev.operation_profile("Para cada una de las siguientes obras literarias, indica solo "
                              "el nombre de su autor:")
    text = "Huasipungo es una novela publicada en 1934 por el escritor Jorge Icaza."
    assert ev.drop_unasked_numbers(e4, text) == text          # the clause carries the author
