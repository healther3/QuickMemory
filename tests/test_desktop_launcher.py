import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from backend import launcher
from backend.main import create_app


def test_frozen_database_lives_next_to_executable_not_temporary_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "轻记.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "temporary-extraction"), raising=False)
    monkeypatch.delenv("QUICKMEMORY_DB", raising=False)
    assert launcher.database_path() == tmp_path / "data" / "quickmemory.db"


def test_metadata_is_owned_by_lease_and_removed_after_shutdown(tmp_path):
    database = tmp_path / "memory.db"
    lease = launcher.InstanceLease(database)
    with pytest.raises(RuntimeError, match="取得数据库锁"):
        lease.publish(8020)
    with lease:
        lease.publish(8020)
        metadata = json.loads(lease.state_file.read_text())
        assert metadata["database"] == launcher.database_identity(database)
        assert metadata["token"] == lease.token
        assert str(database) not in lease.state_file.read_text()
        with pytest.raises(launcher.AlreadyRunning):
            with launcher.InstanceLease(database):
                pytest.fail("重复实例不应拿到锁")
    assert not lease.state_file.exists()
    with launcher.InstanceLease(database):
        pass


@pytest.mark.parametrize("invalid", [{"port": 80}, {"port": True}, {"page_port": "8000"},
                                     {"database": "other-database"}, {"token": "invalid"}])
def test_untrusted_instance_metadata_never_contacts_a_server(tmp_path, monkeypatch, invalid):
    database = tmp_path / "test.db"
    with launcher.InstanceLease(database) as lease:
        lease.publish(8020)
        state = json.loads(lease.state_file.read_text())
        state.update(invalid)
        lease.state_file.write_text(json.dumps(state))
        monkeypatch.setattr(launcher, "_request_instance", lambda *_: pytest.fail("不能请求无效实例"))
        assert launcher.find_running(database) is None


def test_instance_probe_requires_matching_database_response(tmp_path, monkeypatch):
    database = tmp_path / "test.db"
    with launcher.InstanceLease(database) as lease:
        lease.publish(8020)
        monkeypatch.setattr(launcher, "_request_instance", lambda *_: {"app": "QuickMemory", "database": "other"})
        assert launcher.find_running(database) is None
        monkeypatch.setattr(launcher, "_request_instance", lambda *_: {"app": "QuickMemory", "database": lease.identity})
        assert launcher.find_running(database)["port"] == 8020


def test_instance_control_requires_secret_and_blocks_cross_site(tmp_path):
    with launcher.InstanceLease(tmp_path / "test.db") as lease:
        app = create_app(lease.database, seed=False)
        stopping = []
        launcher.attach_instance_routes(app, lease, lambda: stopping.append(True))
        with TestClient(app) as client:
            assert client.get("/api/_local_instance").status_code == 403
            assert client.post("/api/_local_instance").status_code == 403
            headers = {"X-QuickMemory-Instance": lease.token}
            reply = client.get("/api/_local_instance", headers=headers)
            assert reply.json() == {"app": "QuickMemory", "database": lease.identity}
            assert lease.token not in reply.text
            assert client.post("/api/_local_instance", headers={**headers, "Origin": "https://example.com"}).status_code == 403
            assert not stopping
            assert client.post("/api/_local_instance", headers=headers).json() == {"stopping": True}
            assert stopping == [True]
            assert "/api/_local_instance" not in app.openapi()["paths"]
