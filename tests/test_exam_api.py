"""Exam/queue integration tests use deterministic fake grading, never the network."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.database import init_db, make_engine, make_session_factory
from backend.main import create_app
from backend.models import Card, ErrorType, ExamAnswer, ExamSession, Folder, Settings, utc_now
from backend.repositories import settings_snapshot
from backend.schemas import FeedbackSections, GradingResult, JudgeOutcome
from backend.services.queue import GradingQueue


def result(score=75, label=None):
    return GradingResult(status="graded", accuracy=score, completeness=score, final_score=score,
        merged_feedback=FeedbackSections(correct_parts=["与参考一致"], wrong_parts=[], uncertain_parts=[],
                                         error_types=[label] if label else []),
        model_knowledge_notes=["模型提示不计分"],
        judges=[JudgeOutcome(judge_index=1, success=True, accuracy=score, completeness=score,
                             raw_json={"accuracy": score, "completeness": score})],
        prompt_version="mock-v1", model_name="模拟模型")


class FakeGrader:
    def __init__(self, blocked=False, crash=False):
        self.calls = []
        self.started = threading.Event()
        self.release = asyncio.Event()
        self.blocked = blocked
        self.crash = crash
        self.active = 0
        self.max_active = 0

    async def grade(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            if self.blocked:
                await self.release.wait()
            if self.crash:
                raise RuntimeError("do-not-log-secret-key")
            score = 30 if kwargs["user_answer"] == "错题" else 80
            labels = kwargs["error_types"]
            return result(score, labels[0] if labels else None)
        finally:
            self.active -= 1


def add_folder(app, count=2):
    with app.state.session_factory() as db:
        folder = Folder(name="考试文件夹")
        folder.cards = [Card(term=f"概念 {index}", definition=f"参考定义 {index}") for index in range(count)]
        db.add(folder)
        db.commit()
        return folder.id, [card.id for card in folder.cards]


def wait_result(client, exam_id, predicate=None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/exams/{exam_id}/results")
        assert response.status_code == 200, response.text
        data = response.json()
        if (predicate and predicate(data)) or (not predicate and data["graded_count"] + data["failed_count"] == data["total"]):
            return data
        time.sleep(0.01)
    pytest.fail("模拟后台评分未在时限内完成")


def test_snapshot_hidden_reference_submit_is_nonblocking_and_idempotent(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    grader = FakeGrader(blocked=True)
    app.state.grading_service = grader
    with TestClient(app) as client:
        folder_id, cards = add_folder(app)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        assert exam["total"] == 2
        assert set(a["card_id"] for a in exam["answers"]) == set(cards)
        assert [a["position"] for a in exam["answers"]] == [0, 1]
        assert "参考定义" not in client.get(f"/api/exams/{exam['id']}").text
        assert client.get(f"/api/exams/{exam['id']}/results").status_code == 409
        first = exam["answers"][0]
        body = {"user_answer": "我的原始答案", "time_spent_ms": 1500}
        response = client.post(f"/api/answers/{first['id']}/submit", json=body)
        assert response.status_code == 200
        assert grader.started.wait(2)
        # The call returned with the grader still suspended behind the gate.
        assert not grader.release.is_set()
        assert client.post(f"/api/answers/{first['id']}/submit", json=body).status_code == 200
        assert client.post(f"/api/answers/{first['id']}/submit", json={**body, "user_answer": "覆盖"}).status_code == 409
        with app.state.session_factory() as db:
            saved = db.get(ExamSession, exam["id"])
            assert "api_key" not in saved.settings_snapshot
            card = db.get(Card, first["card_id"])
            card.definition = "编辑后的参考"
            db.commit()
        assert client.get(f"/api/exams/{exam['id']}/results").status_code == 409
        client.post(f"/api/answers/{exam['answers'][1]['id']}/submit", json={"user_answer": "", "time_spent_ms": 0})
        pending = client.get(f"/api/exams/{exam['id']}/results").json()
        assert pending["finished_at"] is not None
        assert pending["submitted_count"] == 2
        assert all(a["definition"].startswith("参考定义") for a in pending["answers"])
        client.portal.call(grader.release.set)
        completed = wait_result(client, exam["id"])
        assert completed["graded_count"] == 2
        assert len(grader.calls) == 2
        assert all(a["final_score"] == 80 for a in completed["answers"])


def test_retry_wrong_uses_original_snapshots_even_deleted_cards(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    app.state.grading_service = FakeGrader()
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 3)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        assert client.post(f"/api/exams/{exam['id']}/retry").status_code == 409
        for index, answer in enumerate(exam["answers"]):
            client.post(f"/api/answers/{answer['id']}/submit", json={"user_answer": "错题" if index == 0 else "正确", "time_spent_ms": 50})
        completed = wait_result(client, exam["id"])
        wrong = completed["answers"][0]
        with app.state.session_factory() as db:
            db.delete(db.get(Card, wrong["card_id"]))
            db.delete(db.get(Folder, folder_id))
            db.commit()
        response = client.post(f"/api/exams/{exam['id']}/retry")
        assert response.status_code == 201, response.text
        retried = response.json()
        assert retried["total"] == 1
        assert retried["parent_session_id"] == exam["id"]
        assert retried["folder_id"] is None
        assert retried["answers"][0]["card_id"] is None
        assert retried["answers"][0]["term"] == wrong["term"]
        with app.state.session_factory() as db:
            assert db.get(ExamAnswer, retried["answers"][0]["id"]).definition_snapshot == wrong["definition"]


def test_crashed_grader_is_unscored_and_can_retry_without_overwriting(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    grader = FakeGrader(crash=True)
    app.state.grading_service = grader
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 1)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        answer = exam["answers"][0]
        url = f"/api/answers/{answer['id']}"
        assert client.post(url + "/retry-grade").status_code == 409
        client.post(url + "/submit", json={"user_answer": "我的回答", "time_spent_ms": 1200})
        failed = wait_result(client, exam["id"])["answers"][0]
        assert failed["status"] == "failed"
        assert failed["final_score"] is None
        assert "secret" not in failed["grading_error"]
        assert client.post(f"/api/exams/{exam['id']}/retry").status_code == 400
        grader.crash = False
        assert client.post(url + "/retry-grade").status_code == 200
        graded = wait_result(client, exam["id"])["answers"][0]
        assert graded["status"] == "graded"
        assert graded["user_answer"] == "我的回答"
        assert graded["time_spent_ms"] == 1200
        assert client.post(url + "/retry-grade").status_code == 409


def test_provider_mismatch_never_sends_current_key_to_snapshot_provider(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    grader = FakeGrader()
    app.state.grading_service = grader
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 1)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        with app.state.session_factory() as db:
            settings = db.get(Settings, 1)
            settings.base_url = "https://other.example/v1"
            settings.api_key = "fake-secret"
            db.commit()
        answer_id = exam["answers"][0]["id"]
        client.post(f"/api/answers/{answer_id}/submit", json={"user_answer": "答", "time_spent_ms": 1})
        failed = wait_result(client, exam["id"])["answers"][0]
        assert failed["status"] == "failed"
        assert "不一致" in failed["grading_error"]
        assert not grader.calls


def test_current_key_with_original_model_weights_and_threshold(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    grader = FakeGrader()
    app.state.grading_service = grader
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 1)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        with app.state.session_factory() as db:
            settings = db.get(Settings, 1)
            original_model = settings.model
            settings.model = "changed-model"
            settings.api_key = "new-fake-key"
            settings.w_accuracy = 0.8
            settings.w_completeness = 0.2
            settings.pass_threshold = 90
            db.commit()
        answer_id = exam["answers"][0]["id"]
        client.post(f"/api/answers/{answer_id}/submit", json={"user_answer": "答", "time_spent_ms": 1})
        completed = wait_result(client, exam["id"])
        assert completed["pass_threshold"] == 60
        settings = grader.calls[0]["settings"]
        assert settings.model == original_model
        assert settings.w_accuracy == 0.5
        assert settings.api_key == "new-fake-key"


@pytest.mark.parametrize("mutation", ["rename", "delete"])
def test_vocabulary_edits_in_flight_are_respected(tmp_path, mutation):
    app = create_app(tmp_path / "exam.db", seed=False)
    grader = FakeGrader(blocked=True)
    app.state.grading_service = grader
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 1)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        client.post(f"/api/answers/{exam['answers'][0]['id']}/submit", json={"user_answer": "答", "time_spent_ms": 1})
        assert grader.started.wait(2)
        with app.state.session_factory() as db:
            label = db.scalar(select(ErrorType).order_by(ErrorType.id))
            if mutation == "rename":
                label.name = "更名后类型"
            else:
                db.delete(label)
            db.commit()
        client.portal.call(grader.release.set)
        answer = wait_result(client, exam["id"])["answers"][0]
        assert answer["merged_feedback"]["error_types"] == (["更名后类型"] if mutation == "rename" else [])
        assert [label["name"] for label in answer["error_types"]] == answer["merged_feedback"]["error_types"]


def test_manual_error_labels_validate_and_preserve_score(tmp_path):
    app = create_app(tmp_path / "exam.db", seed=False)
    app.state.grading_service = FakeGrader()
    with TestClient(app) as client:
        folder_id, _ = add_folder(app, 1)
        exam = client.post("/api/exams", json={"folder_id": folder_id}).json()
        answer_id = exam["answers"][0]["id"]
        path = f"/api/answers/{answer_id}"
        assert client.patch(path + "/error-types", json={"error_type_ids": []}).status_code == 409
        client.post(path + "/submit", json={"user_answer": "答", "time_spent_ms": 1})
        wait_result(client, exam["id"])
        assert client.patch(path + "/error-types", json={"error_type_ids": [999999]}).status_code == 400
        labels = client.get("/api/error-types").json()
        chosen = labels[-1]
        response = client.patch(path + "/error-types", json={"error_type_ids": [chosen["id"], chosen["id"]]}).json()
        assert response["error_types"] == [chosen]
        assert response["merged_feedback"]["error_types"] == [chosen["name"]]
        assert response["final_score"] == 80
        assert client.patch(path + "/error-types", json={"error_type_ids": []}).json()["error_types"] == []


@pytest.mark.parametrize("body", [
    {"user_answer": "x", "time_spent_ms": -1},
    {"user_answer": "x", "time_spent_ms": True},
    {"user_answer": 1, "time_spent_ms": 1},
])
def test_submit_rejects_invalid_body(tmp_path, body):
    app = create_app(tmp_path / "exam.db", seed=False)
    app.state.grading_service = FakeGrader()
    with TestClient(app) as client:
        assert client.post("/api/answers/1/submit", json=body).status_code == 422


async def test_queue_recovers_submitted_only_and_bounds_concurrency(tmp_path):
    engine = make_engine(tmp_path / "queue.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        settings = settings_snapshot(db.get(Settings, 1))
        exam = ExamSession(folder_name_snapshot="恢复", settings_snapshot=settings)
        exam.answers = [ExamAnswer(position=index, term_snapshot="概念", definition_snapshot="参考", user_answer="答",
                                   submitted_at=utc_now() if index < 5 else None) for index in range(6)]
        db.add(exam)
        db.commit()
        identifiers = [answer.id for answer in exam.answers]
    grader = FakeGrader(blocked=True)
    queue = GradingQueue(factory, grader, workers=2)
    await queue.start()
    for _ in range(100):
        if len(grader.calls) == 2:
            break
        await asyncio.sleep(0.005)
    assert len(grader.calls) == 2
    assert grader.max_active == 2
    queue.enqueue(identifiers[0])  # Duplicate in flight remains a single call.
    grader.release.set()
    await asyncio.wait_for(queue._queue.join(), timeout=2)
    assert len(grader.calls) == 5
    with factory() as db:
        assert db.get(ExamAnswer, identifiers[-1]).submitted_at is None
        assert db.get(ExamAnswer, identifiers[-1]).status == "pending"
    await queue.stop()
    engine.dispose()


async def test_shutdown_preserves_pending_for_restart(tmp_path):
    engine = make_engine(tmp_path / "queue.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        exam = ExamSession(folder_name_snapshot="恢复", settings_snapshot=settings_snapshot(db.get(Settings, 1)))
        exam.answers = [ExamAnswer(position=0, term_snapshot="概念", definition_snapshot="参考", submitted_at=utc_now())]
        db.add(exam)
        db.commit()
        answer_id = exam.answers[0].id
    blocked = FakeGrader(blocked=True)
    queue = GradingQueue(factory, blocked)
    await queue.start()
    await asyncio.sleep(0.02)
    await queue.stop()
    with factory() as db:
        assert db.get(ExamAnswer, answer_id).status == "pending"
    next_queue = GradingQueue(factory, FakeGrader())
    await next_queue.start()
    await asyncio.wait_for(next_queue._queue.join(), timeout=2)
    with factory() as db:
        assert db.get(ExamAnswer, answer_id).status == "graded"
    await next_queue.stop()
    engine.dispose()
