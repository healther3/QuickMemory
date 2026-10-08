"""应用启动、CLI、评分持久化之间的连接；全部离线模拟。"""

import json
import sys

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.cli import configure, grade_sample
from backend.database import make_engine, make_session_factory
from backend.main import create_app
from backend.models import ExamAnswer, Settings
from backend.schemas import SettingsData
from backend.services.grading import GradingService


class FakeClient:
    async def complete(self, messages, settings, temperature):
        if "独立裁判" in messages[0]["content"]:
            return json.dumps({
                "accuracy": 80, "completeness": 60, "correct_parts": ["覆盖了泛化差这一点"],
                "wrong_parts": [], "uncertain_parts": [], "error_types": ["遗漏要点"],
                "model_knowledge_notes": ["仅供参考的模型提示"], "reasoning": "回答遗漏噪声部分",
            })
        return json.dumps({"correct_parts": ["覆盖了泛化差这一点"], "wrong_parts": [],
                           "uncertain_parts": [], "error_types": ["遗漏要点"],
                           "model_knowledge_notes": ["仅供参考的模型提示"]})


def test_app_initialization_is_local_and_has_no_remote_docs(tmp_path):
    db = tmp_path / "local.db"
    app = create_app(db)
    assert not db.exists()
    with TestClient(app) as client:
        assert client.get("/api/health").json()["phase"] == 4
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/api/health", headers={"host": "unexpected.example"}).status_code == 400
    assert db.exists()


def test_cli_real_service_persists_mock_grade(tmp_path, monkeypatch, capsys):
    db = tmp_path / "grade.db"
    monkeypatch.setenv("QUICKMEMORY_API_KEY", "test-secret-only")
    monkeypatch.setattr(sys, "argv", ["grade_sample", "--db", str(db), "--save-result"])
    monkeypatch.setattr(grade_sample, "GradingService", lambda: GradingService(FakeClient()))
    assert grade_sample.main() == 0
    output = capsys.readouterr()
    assert "test-secret-only" not in output.out + output.err
    assert json.loads(output.out)["final_score"] == 70
    engine = make_engine(db)
    with make_session_factory(engine)() as session:
        answer = session.scalar(select(ExamAnswer))
        assert answer.status == "graded"
        assert answer.final_score == 70
        assert [j.judge_index for j in answer.judge_results] == [1, 2, 3]
        assert answer.error_types[0].name == "遗漏要点"
        assert answer.model_knowledge_notes == ["仅供参考的模型提示"]
        assert answer.term_snapshot == "过拟合"
        assert answer.submitted_at is not None
        assert "api_key" not in answer.session.settings_snapshot
        assert session.get(Settings, 1).api_key == ""  # 临时密钥不被 CLI 隐式保存。
    engine.dispose()


def test_cli_no_key_never_calls_llm(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("QUICKMEMORY_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["grade_sample", "--db", str(tmp_path / "no-key.db")])
    monkeypatch.setattr(grade_sample, "GradingService", lambda: (_ for _ in ()).throw(AssertionError("不得调用")))
    assert grade_sample.main() == 2
    assert "未配置密钥" in capsys.readouterr().err


def test_cli_configure_save_and_mask(tmp_path, monkeypatch, capsys):
    db = tmp_path / "settings.db"
    monkeypatch.setenv("QUICKMEMORY_API_KEY", "test-secret-only")
    monkeypatch.setattr(sys, "argv", ["configure", "--db", str(db), "--judge-count", "2",
                                     "--accuracy-weight", "0.6", "--save"])
    assert configure.main() == 0
    output = capsys.readouterr()
    assert "test-secret-only" not in output.out + output.err
    engine = make_engine(db)
    with make_session_factory(engine)() as session:
        stored = SettingsData.model_validate(session.get(Settings, 1))
        assert stored.judge_count == 2
        assert stored.w_completeness == 0.4
        assert stored.api_key == "test-secret-only"
    engine.dispose()


def test_invalid_cli_settings_do_not_save(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUICKMEMORY_API_KEY", "test-secret-only")
    monkeypatch.setattr(sys, "argv", ["configure", "--db", str(tmp_path / "invalid.db"),
                                     "--accuracy-weight", "9", "--save"])
    assert configure.main() == 2
    output = capsys.readouterr()
    assert "test-secret-only" not in output.out + output.err
    assert "配置无效" in output.err


def test_invalid_sample_rejected_without_llm(tmp_path, monkeypatch, capsys):
    sample = tmp_path / "bad.json"
    sample.write_text('{"term": "", "reference_definition": 42}', encoding="utf-8-sig")
    monkeypatch.setattr(sys, "argv", ["grade_sample", "--db", str(tmp_path / "sample.db"), "--sample", str(sample)])
    assert grade_sample.main() == 2
    assert "输入校验失败" in capsys.readouterr().err
