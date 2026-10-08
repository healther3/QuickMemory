import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.local_service import (
    LauncherPreferences,
    LauncherPreferencesError,
    preferences_path,
    read_preferences,
    save_preferences,
)
from backend.main import create_app


def test_preferred_port_survives_restart_without_changing_running_port(tmp_path):
    database = tmp_path / "isolated.db"
    first = create_app(database, seed=False)
    first.state.local_service_page_port = 5173
    with TestClient(first, base_url="http://localhost:8123") as client:
        initial = client.get("/api/local-service")
        assert initial.status_code == 200
        assert initial.json() == {"port": 8123, "page_port": 5173, "can_stop": False, "desktop_window": False, "preferred_port": 8000}
        saved = client.put("/api/local-service", json={"preferred_port": 9011})
        assert saved.status_code == 200
        assert saved.json() == {"port": 8123, "page_port": 5173, "can_stop": False, "desktop_window": False, "preferred_port": 9011}
        assert client.get("/api/health").status_code == 200

    # A new application/engine must read the independent disk configuration.
    with TestClient(create_app(database, seed=False), base_url="http://localhost:9011") as restarted:
        current = restarted.get("/api/local-service").json()
        assert current == {"port": 9011, "page_port": 9011, "can_stop": False, "desktop_window": False, "preferred_port": 9011}
    assert json.loads(preferences_path(database).read_text(encoding="utf-8")) == {"preferred_port": 9011}
    assert read_preferences(database).preferred_port == 9011


@pytest.mark.parametrize("body", [
    {}, {"preferred_port": 1023}, {"preferred_port": 65536}, {"preferred_port": True},
    {"preferred_port": "9000"}, {"preferred_port": 9000.5}, {"preferred_port": None},
    {"preferred_port": 9000, "host": "0.0.0.0"},
])
def test_invalid_update_preserves_saved_preference(tmp_path, body):
    database = tmp_path / "validation.db"
    save_preferences(LauncherPreferences(preferred_port=9111), database)
    with TestClient(create_app(database, seed=False)) as client:
        assert client.put("/api/local-service", json=body).status_code == 422
    assert read_preferences(database).preferred_port == 9111


@pytest.mark.parametrize("raw", ['{"preferred_port": 1}', "not-json", '{"preferred_port":"9000"}', '{"token":"private-marker"}'])
def test_invalid_config_fails_clearly_without_echoing_contents(tmp_path, raw):
    database = tmp_path / "invalid.db"
    preferences_path(database).write_text(raw, encoding="utf-8")
    with pytest.raises(LauncherPreferencesError, match="launcher.json") as error:
        read_preferences(database)
    assert "private-marker" not in str(error.value)
    with TestClient(create_app(database, seed=False)) as client:
        response = client.get("/api/local-service")
        assert response.status_code == 503
        assert "private-marker" not in response.text


def test_failed_atomic_save_preserves_existing_file(tmp_path, monkeypatch):
    database = tmp_path / "atomic.db"
    save_preferences(LauncherPreferences(preferred_port=9200), database)

    def denied_replace(self, destination):
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(Path, "replace", denied_replace)
    with pytest.raises(LauncherPreferencesError, match="无法保存"):
        save_preferences(LauncherPreferences(preferred_port=9201), database)
    assert read_preferences(database).preferred_port == 9200
    assert list(tmp_path.glob("launcher-*.tmp")) == []


@pytest.mark.parametrize("headers", [
    {"origin": "https://malicious.example"},
    {"origin": "http://localhost:9222"},
    {"sec-fetch-site": "cross-site"},
])
def test_external_page_cannot_shutdown_or_reconfigure(tmp_path, headers):
    calls = []
    app = create_app(tmp_path / "origin.db", seed=False)
    app.state.local_service_stop = lambda: calls.append("stop")
    with TestClient(app, base_url="http://localhost:8123") as client:
        assert client.post("/api/local-service/stop", headers=headers).status_code == 403
        assert client.put("/api/local-service", json={"preferred_port": 9000}, headers=headers).status_code == 403
        assert client.get("/api/local-service").json()["preferred_port"] == 8000
    assert calls == []


def test_stop_uses_launcher_callback_without_disclosing_instance_token(tmp_path):
    calls = []
    app = create_app(tmp_path / "stop.db", seed=False)
    with TestClient(app, base_url="http://localhost:8123") as client:
        assert client.post("/api/local-service/stop").status_code == 409
        app.state.local_service_stop = lambda: calls.append("stop")
        app.state.local_service_desktop_window = True
        assert client.get("/api/local-service").json()["desktop_window"] is True
        assert client.get("/api/local-service").json()["can_stop"] is True
        response = client.post("/api/local-service/stop", headers={"origin": "http://localhost:8123"})
        assert response.status_code == 200
        assert response.json()["stopping"] is True
        assert set(response.json()) == {"stopping", "message"}
        assert calls == ["stop"]


@pytest.mark.parametrize("database", [":memory:", None])
def test_memory_database_preferences_do_not_touch_default_data(monkeypatch, database):
    def unexpected_filesystem_call(*args, **kwargs):
        pytest.fail("In-memory test must not access a launcher preference file")

    monkeypatch.setattr("backend.api.local_service.read_preferences", unexpected_filesystem_call)
    monkeypatch.setattr("backend.api.local_service.save_preferences", unexpected_filesystem_call)
    monkeypatch.setenv("QUICKMEMORY_DB", ":memory:")
    with TestClient(create_app(database, seed=False)) as client:
        assert client.get("/api/local-service").json()["preferred_port"] == 8000
        assert client.put("/api/local-service", json={"preferred_port": 9999}).status_code == 200
        assert client.get("/api/local-service").json()["preferred_port"] == 9999
