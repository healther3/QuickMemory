from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.main import create_app
from backend.models import Card, ErrorType, ExamAnswer, ExamSession, Settings
from backend.schemas import ConnectionFeedback, PrecheckFeedback
from backend.services.llm import LLMError


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "settings.db", seed=False)
    with TestClient(app) as test_client:
        yield test_client


def test_secret_never_returned_and_target_change_clears(client):
    assert client.put("/api/settings", json={"api_key": "private-key"}).status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["has_api_key"]
    assert "private-key" not in str(settings)
    assert "api_key" not in settings
    client.put("/api/settings", json={"model": "alternate-model", "api_key": None})
    assert client.get("/api/settings").json()["has_api_key"]
    settings = client.put("/api/settings", json={"base_url": "http://localhost:9900/v1"}).json()
    assert not settings["has_api_key"]


def test_saved_key_survives_full_form_save_and_application_restart(tmp_path):
    """Exercise a real file database; the browser never receives the stored key."""
    database = tmp_path / "persisted-settings.db"
    fake_key = "isolated-persistence-test-key"
    with TestClient(create_app(database, seed=False)) as first:
        response = first.put("/api/settings", json={
            "provider": "custom", "base_url": "http://localhost:9911/v1/",
            "model": "isolated-test-model", "api_key": fake_key,
        })
        assert response.status_code == 200
        assert response.json()["has_api_key"] is True
        assert fake_key not in response.text

        # A remounted Settings page submits all public fields and omits a blank
        # password input. A harmless trailing slash also preserves the key.
        public_settings = first.get("/api/settings").json()
        public_settings.pop("has_api_key")
        public_settings.update(judge_count=2, base_url="http://localhost:9911/v1/")
        saved_again = first.put("/api/settings", json=public_settings)
        assert saved_again.status_code == 200
        assert saved_again.json()["has_api_key"] is True

    # Starting a new application recreates the engine and reruns init_db,
    # preventing a session cache from hiding a missing database commit.
    restarted = create_app(database, seed=False)
    calls = []

    async def fake_connection(settings):
        calls.append(("connection", settings.api_key))
        return ConnectionFeedback(ok=True, message="模拟连接成功")

    async def fake_precheck(**kwargs):
        calls.append(("precheck", kwargs["settings"].api_key))
        return PrecheckFeedback(correct_parts=[], wrong_parts=[], uncertain_parts=[],
                                clarifying_questions=[], suggested_rewrite=None)

    restarted.state.grading_service = SimpleNamespace(
        test_connection=fake_connection, precheck=fake_precheck,
    )
    with TestClient(restarted) as second:
        restored = second.get("/api/settings")
        assert restored.json()["has_api_key"] is True
        assert restored.json()["judge_count"] == 2
        assert restored.json()["model"] == "isolated-test-model"
        assert "api_key" not in restored.json()
        assert fake_key not in restored.text
        assert second.post("/api/settings/test", json={}).status_code == 200
        assert second.post("/api/precheck", json={
            "term": "测试术语", "definition": "测试定义",
        }).status_code == 200
        assert calls == [("connection", fake_key), ("precheck", fake_key)]
        assert second.get("/api/settings").json()["has_api_key"] is True


def test_invalid_weights_reject_whole_update_and_no_secret_echo(client):
    response = client.put("/api/settings", json={"w_accuracy": 0.9, "api_key": "must-not-leak"})
    assert response.status_code == 422
    assert "must-not-leak" not in response.text
    assert not client.get("/api/settings").json()["has_api_key"]
    response = client.put("/api/settings", json={"api_key": ["must-not-leak"]})
    assert response.status_code == 422
    assert "must-not-leak" not in response.text


def test_connection_uses_unsaved_settings_without_persisting(client):
    seen = []
    async def fake(config):
        seen.append(config)
        return ConnectionFeedback(ok=True, message="连接成功")
    client.app.state.grading_service = SimpleNamespace(test_connection=fake)
    response = client.post("/api/settings/test", json={"api_key": "temporary-key", "model": "test-model"})
    assert response.status_code == 200
    assert seen[0].model == "test-model"
    assert seen[0].api_key == "temporary-key"
    assert not client.get("/api/settings").json()["has_api_key"]


def test_precheck_does_not_write_card_or_history(client):
    seen = []
    async def fake(**kwargs):
        seen.append(kwargs)
        return PrecheckFeedback(correct_parts=["定义一致"], wrong_parts=[], uncertain_parts=[],
                                clarifying_questions=[], suggested_rewrite="建议改写")
    client.app.state.grading_service = SimpleNamespace(precheck=fake)
    response = client.post("/api/precheck", json={"term": "术语", "definition": "原定义", "reference_note": "教材摘录"})
    assert response.status_code == 200
    assert seen[0]["reference_note"] == "教材摘录"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Card.id)) is None
        assert db.scalar(select(ExamAnswer.id)) is None


def test_precheck_accepts_lengths_allowed_by_card_editor(client):
    async def fake(**_kwargs):
        return PrecheckFeedback(correct_parts=[], wrong_parts=[], uncertain_parts=[],
                                clarifying_questions=[], suggested_rewrite=None)
    client.app.state.grading_service = SimpleNamespace(precheck=fake)
    response = client.post("/api/precheck", json={"term": "长" * 1000, "definition": "文" * 50001})
    assert response.status_code == 200


def test_connection_failure_returns_actionable_chinese(client):
    async def fake(_config):
        raise LLMError("模型鉴权失败，请检查 API 密钥")
    client.app.state.grading_service = SimpleNamespace(test_connection=fake)
    response = client.post("/api/settings/test", json={})
    assert response.status_code == 502
    assert "密钥" in response.json()["detail"]


def test_rename_delete_error_type_updates_history_and_preserves_scores(client):
    with client.app.state.session_factory.begin() as db:
        label = db.scalar(select(ErrorType).where(ErrorType.name == "遗漏要点"))
        identifier = label.id
        answer = ExamAnswer(session=ExamSession(), position=0, term_snapshot="术语", definition_snapshot="定义",
                            status="graded", accuracy=50, completeness=40, final_score=45,
                            error_types=[label], merged_feedback={"error_types": [label.name], "correct_parts": ["内容"]})
        db.add(answer)
    assert client.put(f"/api/error-types/{identifier}", json={"name": "遗漏定义"}).status_code == 200
    with client.app.state.session_factory() as db:
        answer = db.scalar(select(ExamAnswer))
        assert answer.merged_feedback["error_types"] == ["遗漏定义"]
        assert answer.final_score == 45
    assert client.delete(f"/api/error-types/{identifier}").status_code == 204
    with client.app.state.session_factory() as db:
        answer = db.scalar(select(ExamAnswer))
        assert answer.merged_feedback["error_types"] == []
        assert answer.final_score == 45


def test_deleted_error_type_ids_are_not_reused(client):
    labels = client.get("/api/error-types").json()
    last = max(row["id"] for row in labels)
    client.delete(f"/api/error-types/{last}")
    added = client.post("/api/error-types", json={"name": "新类型"})
    assert added.status_code == 201
    assert added.json()["id"] > last
    assert client.post("/api/error-types", json={"name": "新类型"}).status_code == 409


@pytest.mark.parametrize("origin", ["https://external.example", "null", "http://localhost:9999", "http://["])
def test_browser_cross_origin_writes_rejected(client, origin):
    response = client.post("/api/error-types", json={"name": "不能创建"}, headers={"origin": origin})
    assert response.status_code == 403


def test_browser_same_origin_writes_allowed(client):
    response = client.post("/api/error-types", json={"name": "可创建"}, headers={"origin": "http://testserver"})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
