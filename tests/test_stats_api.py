"""Statistics are computed once per answer even with many-to-many membership."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import create_app
from backend.models import Card, ErrorType, ExamAnswer, ExamSession, Folder, Settings, UserTag, utc_now
from backend.repositories import persist_grade, settings_snapshot
from backend.schemas import FeedbackSections, GradingResult


@pytest.fixture
def statistics_data(tmp_path):
    app = create_app(tmp_path / "stats.db", seed=False)
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            folders = [Folder(name="甲文件夹"), Folder(name="乙文件夹"), Folder(name="空文件夹")]
            tags = [UserTag(name="机器学习"), UserTag(name="重点")]
            first = Card(term="已练习概念", definition="原定义", folders=folders[:2], user_tags=tags)
            second = Card(term="未练习概念", definition="另一参考", folders=folders[:1], user_tags=tags[:1])
            db.add_all([*folders, *tags, first, second])
            db.flush()
            base = utc_now()
            exam = ExamSession(folder_id=folders[0].id, folder_name_snapshot=folders[0].name,
                               settings_snapshot=settings_snapshot(db.get(Settings, 1)), finished_at=base)
            exam.answers = [ExamAnswer(card_id=first.id, position=index, term_snapshot=first.term,
                            definition_snapshot="原定义", user_answer=f"历史作答 {index}", time_spent_ms=(index + 1) * 1000,
                            submitted_at=base + timedelta(seconds=index)) for index in range(3)]
            exam.answers.append(ExamAnswer(card_id=second.id, position=3, term_snapshot=second.term,
                                definition_snapshot=second.definition))
            # A deleted card remains in all-history overview but cannot match live filters.
            exam.answers.append(ExamAnswer(card_id=None, position=4, term_snapshot="已删除概念", definition_snapshot="删除前参考",
                                user_answer="曾经的答案", time_spent_ms=4000, submitted_at=base))
            db.add(exam)
            db.flush()
            labels = list(db.scalars(select(ErrorType).order_by(ErrorType.id)))
            for answer, score in [(exam.answers[0], 80), (exam.answers[1], 20), (exam.answers[4], 40)]:
                persist_grade(db, answer.id, GradingResult(status="graded", accuracy=score, completeness=score,
                    final_score=score, merged_feedback=FeedbackSections(correct_parts=["参考内的正确点"],
                    wrong_parts=[], uncertain_parts=[], error_types=[labels[0].name, labels[1].name]),
                    model_knowledge_notes=["知识提示不计分"], prompt_version="test", model_name="mock"))
            persist_grade(db, exam.answers[2].id, GradingResult(status="failed", error="模拟失败", prompt_version="test", model_name="mock"))
            first.definition = "修改后的定义"
            db.commit()
            data = dict(card_id=first.id, second_id=second.id, folder_id=folders[0].id,
                        empty_folder_id=folders[2].id, tag_id=tags[0].id, label_id=labels[0].id, exam_id=exam.id)
        yield client, data


def test_overview_counts_submissions_and_excludes_null_from_score_average(statistics_data):
    client, ids = statistics_data
    response = client.get("/api/stats")
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["overview"] == {"card_count": 2, "folder_count": 3, "attempt_count": 4,
        "graded_count": 3, "average_score": pytest.approx(140 / 3), "average_time_ms": 2500}
    rows = stats["cards"]
    assert [row["id"] for row in rows] == [ids["card_id"], ids["second_id"]]
    assert rows[0]["attempt_count"] == 3
    assert rows[0]["average_score"] == 50
    assert rows[0]["lowest_score"] == 20
    assert rows[0]["last_score"] == 20
    assert rows[0]["average_time_ms"] == 2000
    assert rows[1]["average_score"] is None
    assert rows[1]["last_score"] is None
    assert rows[1]["average_time_ms"] is None
    assert stats["error_distribution"][0]["count"] == 3
    assert len(stats["recent_exams"]) == 1
    assert "definition" not in stats["recent_exams"][0]["answers"][0]


@pytest.mark.parametrize("filters", ["folder", "tag", "both"])
def test_membership_filters_do_not_multiply_answers_or_error_counts(statistics_data, filters):
    client, ids = statistics_data
    params = {}
    if filters in {"folder", "both"}:
        params["folder_id"] = ids["folder_id"]
    if filters in {"tag", "both"}:
        params["tag_id"] = ids["tag_id"]
    stats = client.get("/api/stats", params=params).json()
    assert stats["overview"]["card_count"] == 2
    assert stats["overview"]["attempt_count"] == 3
    assert stats["overview"]["graded_count"] == 2
    assert stats["overview"]["average_score"] == 50
    assert stats["overview"]["average_time_ms"] == 2000
    assert stats["error_distribution"][0]["count"] == 2
    assert len(stats["recent_exams"]) == 1


def test_empty_folder_has_null_averages_and_no_exams(statistics_data):
    client, ids = statistics_data
    stats = client.get("/api/stats", params={"folder_id": ids["empty_folder_id"]}).json()
    assert stats["overview"]["card_count"] == 0
    assert stats["overview"]["attempt_count"] == 0
    assert stats["overview"]["average_score"] is None
    assert stats["cards"] == []
    assert stats["recent_exams"] == []
    assert all(item["count"] == 0 for item in stats["error_distribution"])


def test_card_history_preserves_snapshot_notes_failure_and_submission_order(statistics_data):
    client, ids = statistics_data
    response = client.get(f"/api/cards/{ids['card_id']}/history")
    assert response.status_code == 200, response.text
    history = response.json()
    assert history["card"]["definition"] == "修改后的定义"
    assert len(history["answers"]) == 3
    assert [answer["user_answer"] for answer in history["answers"]] == ["历史作答 2", "历史作答 1", "历史作答 0"]
    assert all(answer["definition"] == "原定义" for answer in history["answers"])
    assert history["answers"][0]["final_score"] is None
    assert history["answers"][1]["model_knowledge_notes"] == ["知识提示不计分"]
    assert history["stats"]["average_score"] == 50
    assert client.get("/api/cards/99999/history").status_code == 404
    assert client.get("/api/stats?folder_id=99999").status_code == 404
    assert client.get("/api/stats?tag_id=99999").status_code == 404
