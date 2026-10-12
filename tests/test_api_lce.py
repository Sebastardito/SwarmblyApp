"""API integration tests (FastAPI TestClient) and LCE adapter tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from swarmbly_app.api import create_app


def make_client(app_state):
    return TestClient(create_app(app_state))


class TestApi:
    def test_health(self, app_state):
        client = make_client(app_state)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["protocol_spec"] == "0.2"
        assert body["node_id"]

    def test_system_report(self, app_state):
        client = make_client(app_state)
        resp = client.get("/api/system")
        assert resp.status_code == 200
        assert "os" in resp.json() and "gpu" in resp.json()

    def test_config_roundtrip(self, app_state):
        client = make_client(app_state)
        resp = client.put("/api/config", json={"language": "es"})
        assert resp.status_code == 200
        assert resp.json()["language"] == "es"
        assert client.get("/api/config").json()["language"] == "es"
        # swarm mode cannot silently become non-local without explicit intent:
        # it is settable, but the default is local (safety default tested in core)

    def test_conversations_flow(self, app_state):
        client = make_client(app_state)
        conv = client.post("/api/conversations", json={"title": "API test"}).json()
        conv_id = conv["id"]
        assert client.get(f"/api/conversations/{conv_id}").status_code == 200
        send = client.post(f"/api/conversations/{conv_id}/messages",
                           json={"text": "hello"}).json()
        assert send["user_message"]["role"] == "user"
        assert send["assistant_message"]["role"] == "assistant"
        messages = client.get(f"/api/conversations/{conv_id}/messages").json()
        assert len(messages) == 2
        export = client.get(f"/api/conversations/{conv_id}/export?format=markdown")
        assert export.status_code == 200
        assert client.delete(f"/api/conversations/{conv_id}").status_code == 200
        assert client.get(f"/api/conversations/{conv_id}").status_code == 404

    def test_stop_last(self, app_state):
        client = make_client(app_state)
        resp = client.post("/api/requests/_stop_last")
        assert resp.status_code == 200
        assert resp.json()["stopped"] is False  # nothing active

    def test_models_endpoint(self, app_state):
        client = make_client(app_state)
        resp = client.get("/api/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "backends" in body and "recommendations" in body

    def test_index_served(self, app_state):
        client = make_client(app_state)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Swarmbly" in resp.text


class TestLceAdapter:
    def test_status_c0_default(self, app_state):
        status = app_state.lce.status(False, "C0")
        assert status["enabled"] is False
        assert status["level"] == "C0"

    def test_activate_c0_and_c1(self, app_state):
        status = app_state.lce.activate("C0")
        assert status["enabled"] is True
        status = app_state.lce.activate("C1")
        assert status["level"] == "C1"
        assert app_state.dirs.sources.exists()
        policy = app_state.dirs.wiki / "policy.json"
        assert policy.exists()
        assert app_state.lce.list_sources()  # README.md created

    def test_higher_levels_refused(self, app_state):
        try:
            app_state.lce.activate("C4")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_policy_defaults_never_trains(self, app_state):
        app_state.lce.activate("C1")
        import json
        policy = json.loads(
            (app_state.dirs.wiki / "policy.json").read_text(encoding="utf-8"))
        # invariant I8: nothing trains unless explicitly declared
        assert policy["defaults"]["reference_only"] is True
        assert policy["sources"] == {}

    def test_worker_guard(self, app_state):
        guard = app_state.lce.worker_guard()
        assert guard is not None  # swarmbly_lce is installed as a dependency
