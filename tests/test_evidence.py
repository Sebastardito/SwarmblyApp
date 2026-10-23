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
