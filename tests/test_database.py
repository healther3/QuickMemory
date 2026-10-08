"""Database integration checks use temporary SQLite files and no LLM calls."""

from __future__ import annotations

import importlib
from copy import deepcopy

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from backend import database
from backend.database import DEFAULT_ERROR_TYPES, init_db, make_engine, make_session_factory
from backend.models import Card, ErrorType, ExamAnswer, ExamSession, Folder, JudgeResult, Settings, UserTag
from backend.repositories import get_settings, persist_grade, save_settings, settings_snapshot


@pytest.fixture
def db(tmp_path):
    engine = make_engine(tmp_path / "tests.sqlite3")
    init_db(engine)
    yield engine, make_session_factory(engine)
    engine.dispose()


def create_answer(session):
    folder = Folder(name="机器学习")
    card = Card(term="过拟合", definition="训练表现好，泛化表现差。", folders=[folder])
    exam = ExamSession(
        folder=folder,
        folder_name_snapshot=folder.name,
        settings_snapshot=settings_snapshot(get_settings(session)),
    )
    answer = ExamAnswer(
        session=exam,
        card=card,
        position=0,
        term_snapshot=card.term,
        definition_snapshot=card.definition,
        user_answer="训练集好，测试集差。",
        time_spent_ms=1234,
    )
    session.add(answer)
    session.flush()
    return answer


def grade_result(**changes):
    result = {
        "status": "graded",
        "accuracy": 80.0,
        "completeness": 60.0,
        "final_score": 70.0,
        "merged_feedback": {
            "correct_parts": ["提到了训练与泛化的差异。"],
            "wrong_parts": [],
            "uncertain_parts": [],
            "error_types": ["遗漏要点", "不允许的模型标签"],
        },
        "model_knowledge_notes": ["此处是模型知识提示，不计分。"],
        "judges": [
            {
                "judge_index": 1,
                "success": True,
                "accuracy": 80.0,
                "completeness": 60.0,
                "raw_json": {"accuracy": 80.0, "completeness": 60.0},
                "raw_text": '{"accuracy": 80, "completeness": 60}',
                "error": None,
            },
            {
                "judge_index": 2,
                "success": False,
                "accuracy": None,
                "completeness": None,
                "raw_json": None,
                "raw_text": "invalid json",
                "error": "评委返回的 JSON 无效。",
            },
        ],
        "disagreement": False,
        "merge_fallback": True,
        "error": None,
        "prompt_version": "test-v1",
        "model_name": "test-model",
    }
    result.update(changes)
    return result


def test_import_and_engine_creation_do_not_create_database(tmp_path, monkeypatch):
    path = tmp_path / "unopened.sqlite3"
    monkeypatch.setenv("QUICKMEMORY_DB", str(path))
    importlib.reload(database)
    assert not path.exists()
    engine = database.make_engine()
    assert not path.exists()
    init_db(engine)
    assert path.exists()
    engine.dispose()


def test_sqlite_pragmas_and_initial_defaults(db):
    engine, factory = db
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
    with factory() as session:
        settings = get_settings(session)
        assert settings.id == 1
        assert settings.provider == "deepseek"
        assert settings.model == "deepseek-chat"
        assert settings.judge_count == 3
        assert settings.json_mode == "auto"
        assert settings.request_timeout == 60.0
        assert set(session.scalars(select(ErrorType.name))) == set(DEFAULT_ERROR_TYPES)
        assert session.scalar(select(func.count()).select_from(Card)) == 0
        assert session.scalar(select(func.count()).select_from(Folder)) == 0


def test_reinitializing_preserves_settings_and_edited_error_types(db):
    engine, factory = db
    with factory.begin() as session:
        save_settings(session, {"model": "my-model", "api_key": "local-secret"})
        removed = session.scalar(select(ErrorType).where(ErrorType.name == "遗漏要点"))
        session.delete(removed)
        renamed = session.scalar(select(ErrorType).where(ErrorType.name == "概念错误"))
        renamed.name = "自定义错误"
    init_db(engine)
    with factory() as session:
        assert get_settings(session).model == "my-model"
        assert get_settings(session).api_key == "local-secret"
        assert set(session.scalars(select(ErrorType.name))) == {"自定义错误", "概念混淆", "表述不精确"}
        assert session.scalar(select(func.count()).select_from(Settings)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"judge_count": 1},
        {"judge_temperature": float("inf")},
        {"merge_temperature": -0.1},
        {"w_accuracy": 0.8},
        {"w_accuracy": -0.5, "w_completeness": 1.5},
        {"pass_threshold": 101},
        {"json_mode": "sometimes"},
        {"request_timeout": 0},
    ],
)
def test_invalid_settings_do_not_replace_existing_values(db, changes):
    _, factory = db
    with factory() as session:
        with pytest.raises(IntegrityError):
            save_settings(session, changes)
        assert get_settings(session).judge_count == 3
        assert get_settings(session).w_accuracy == 0.5
        assert get_settings(session).json_mode == "auto"


def test_settings_savepoint_does_not_commit_callers_transaction(db):
    _, factory = db
    with factory() as session:
        save_settings(session, {"model": "rolled-back-model"})
        session.rollback()
    with factory() as session:
        assert get_settings(session).model == "deepseek-chat"


def test_single_settings_row_enforced(db):
    _, factory = db
    with factory() as session:
        session.add(Settings(id=2))
        with pytest.raises(IntegrityError):
            session.flush()


def test_snapshot_excludes_key_and_does_not_alias_input(db):
    _, factory = db
    with factory.begin() as session:
        settings = save_settings(session, {"api_key": "local-secret"})
        snapshot = settings_snapshot(settings)
        assert "api_key" not in snapshot
        snapshot["api_key"] = "must-not-be-copied"
        snapshot["extra"] = ["original"]
        exam = ExamSession(settings_snapshot=snapshot)
        snapshot["extra"].append("later")
        session.add(exam)
        session.flush()
        assert "api_key" not in exam.settings_snapshot
        assert exam.settings_snapshot["extra"] == ["original"]


def test_card_and_folder_deletion_keeps_exam_snapshots(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        answer.card.user_tags.append(UserTag(name="泛化"))
        answer_id = answer.id
        card_id = answer.card_id
        folder_id = answer.session.folder_id
    with factory.begin() as session:
        session.delete(session.get(Card, card_id))
        session.delete(session.get(Folder, folder_id))
    with factory() as session:
        answer = session.get(ExamAnswer, answer_id)
        assert answer.card_id is None
        assert answer.session.folder_id is None
        assert answer.term_snapshot == "过拟合"
        assert answer.definition_snapshot == "训练表现好，泛化表现差。"
        assert answer.session.folder_name_snapshot == "机器学习"
        assert answer.submitted_at is None
        assert answer.status == "pending"
        assert session.scalar(text("SELECT count(*) FROM card_user_tags")) == 0
        assert session.scalar(text("SELECT count(*) FROM card_folders")) == 0


def test_answer_order_is_unique_within_session(db):
    _, factory = db
    with factory() as session:
        answer = create_answer(session)
        session.add(ExamAnswer(session=answer.session, position=0, term_snapshot="另一个词", definition_snapshot="定义"))
        with pytest.raises(IntegrityError):
            session.flush()


def test_grade_replaces_rows_and_labels_without_mutating_snapshots(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        snapshot_before = deepcopy(answer.session.settings_snapshot)
        card_text_before = (answer.term_snapshot, answer.definition_snapshot)
        result = grade_result()
        answer = persist_grade(session, answer.id, result)
        assert answer.final_score == 70
        assert answer.merge_fallback
        assert answer.judge_results[1].error == "评委返回的 JSON 无效。"
        assert [item.name for item in answer.error_types] == ["遗漏要点"]
        assert answer.merged_feedback["error_types"] == ["遗漏要点"]
        assert result["merged_feedback"]["error_types"] == ["遗漏要点", "不允许的模型标签"]
        assert answer.session.settings_snapshot == snapshot_before
        assert (answer.term_snapshot, answer.definition_snapshot) == card_text_before
        assert answer.user_answer == "训练集好，测试集差。"
        assert answer.time_spent_ms == 1234
        assert answer.model_knowledge_notes == ["此处是模型知识提示，不计分。"]
        second_result = grade_result()
        second_result["judges"] = second_result["judges"][:1]
        second_result["merged_feedback"]["error_types"] = ["表述不精确"]
        persist_grade(session, answer.id, second_result)
        assert session.scalar(select(func.count()).select_from(JudgeResult)) == 1
        assert [item.name for item in answer.error_types] == ["表述不精确"]


def test_failed_grading_never_fabricates_scores(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        result = grade_result(
            status="failed", accuracy=None, completeness=None, final_score=None,
            error="所有评委调用失败。", judges=[], merged_feedback={}, model_knowledge_notes=[],
        )
        answer = persist_grade(session, answer.id, result)
        assert answer.status == "failed"
        assert answer.final_score is None
        assert answer.accuracy is None
        assert answer.completeness is None
        assert answer.grading_error == "所有评委调用失败。"


def test_grade_rollback_and_invalid_update_preserve_existing_result(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        persist_grade(session, answer.id, grade_result())
        answer_id = answer.id
    with factory() as session:
        persist_grade(session, answer_id, grade_result(final_score=42.0))
        session.rollback()
    with factory() as session:
        answer = session.get(ExamAnswer, answer_id)
        assert answer.final_score == 70.0
        bad_result = grade_result()
        bad_result["judges"][1]["judge_index"] = 1
        with pytest.raises(ValueError, match="序号不能重复"):
            persist_grade(session, answer_id, bad_result)
        assert answer.final_score == 70.0
        assert len(answer.judge_results) == 2


def test_persist_grade_rolls_back_entire_replacement_on_database_failure(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        persist_grade(session, answer.id, grade_result())
        bad_result = grade_result(final_score=42.0, model_knowledge_notes=None)
        with pytest.raises(IntegrityError):
            persist_grade(session, answer.id, bad_result)
        assert answer.final_score == 70.0
        assert len(answer.judge_results) == 2
        assert [item.name for item in answer.error_types] == ["遗漏要点"]


def test_removing_error_type_removes_only_its_link(db):
    _, factory = db
    with factory.begin() as session:
        answer = create_answer(session)
        persist_grade(session, answer.id, grade_result())
        answer_id = answer.id
        type_id = answer.error_types[0].id
    with factory.begin() as session:
        session.delete(session.get(ErrorType, type_id))
    with factory() as session:
        answer = session.get(ExamAnswer, answer_id)
        assert answer.final_score == 70.0
        assert answer.error_types == []
        assert session.scalar(select(func.count()).select_from(JudgeResult)) == 2
