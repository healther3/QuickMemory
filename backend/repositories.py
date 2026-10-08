"""Persistence helpers. Callers own the outer transaction and its commit."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ErrorType, ExamAnswer, JudgeResult, Settings


SETTINGS_FIELDS = frozenset(
    {
        "provider", "base_url", "api_key", "model", "judge_count",
        "judge_temperature", "merge_temperature", "w_accuracy", "w_completeness",
        "pass_threshold", "json_mode", "request_timeout",
    }
)


def get_settings(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        raise RuntimeError("设置尚未初始化，请先调用 init_db。")
    return settings


def save_settings(session: Session, validated: dict[str, Any]) -> Settings:
    """Apply already validated settings within a savepoint; do not commit."""
    unknown_fields = set(validated) - SETTINGS_FIELDS
    if unknown_fields:
        raise ValueError(f"未知设置字段：{', '.join(sorted(unknown_fields))}")
    with session.begin_nested():
        settings = get_settings(session)
        for key, value in validated.items():
            setattr(settings, key, value)
        session.flush()
    return settings


def settings_snapshot(settings: Settings) -> dict[str, Any]:
    """Return grading configuration without copying the plaintext API key."""
    return {key: getattr(settings, key) for key in sorted(SETTINGS_FIELDS - {"api_key"})}


def _score(value: Any, label: str, required: bool) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}必须是 0 到 100 之间的有限数值。")
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{label}必须是 0 到 100 之间的有限数值。")
    if not required:
        raise ValueError("未成功评分时不能保存分数。")
    return float(value)


def persist_grade(session: Session, answer_id: int, result: Any) -> ExamAnswer:
    """Atomically replace one answer's grade, judges, and allowed error labels.

    Accepts the validated GradingResult (or a dictionary for non-LLM callers).
    This helper never changes the exam's card snapshots, answer text, or timer.
    Unknown/deleted error names are discarded, not recreated as new types.
    """
    data = deepcopy(result.model_dump() if hasattr(result, "model_dump") else dict(result))
    status = data.get("status")
    if status not in {"pending", "graded", "failed"}:
        raise ValueError("未知评分状态。")
    graded = status == "graded"
    scores = {
        name: _score(data.get(name), name, graded)
        for name in ("accuracy", "completeness", "final_score")
    }
    judge_rows = []
    seen_indices: set[int] = set()
    for judge in data.get("judges", []):
        index = judge["judge_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index not in {1, 2, 3}:
            raise ValueError("评委序号必须为 1、2 或 3。")
        if index in seen_indices:
            raise ValueError("评委序号不能重复。")
        seen_indices.add(index)
        success = judge["success"]
        if not isinstance(success, bool):
            raise ValueError("评委成功状态必须是布尔值。")
        judge_rows.append(
            JudgeResult(
                judge_index=index,
                success=success,
                accuracy=_score(judge.get("accuracy"), "accuracy", success),
                completeness=_score(judge.get("completeness"), "completeness", success),
                raw_json=judge.get("raw_json"),
                raw_text=judge.get("raw_text"),
                error=judge.get("error"),
            )
        )

    feedback = data.get("merged_feedback") or {}
    allowed_names = set(feedback.get("error_types", []))
    with session.begin_nested():
        answer = session.get(ExamAnswer, answer_id)
        if answer is None:
            raise ValueError("找不到要保存评分的作答记录。")
        error_types = list(
            session.scalars(select(ErrorType).where(ErrorType.name.in_(allowed_names)).order_by(ErrorType.id))
        ) if allowed_names else []
        # The vocabulary may have changed while requests were in flight.
        feedback["error_types"] = [error_type.name for error_type in error_types]
        answer.judge_results.clear()
        session.flush()  # Delete old indices before replacing them under the unique constraint.
        answer.judge_results.extend(judge_rows)
        answer.error_types = error_types
        answer.status = status
        for key, value in scores.items():
            setattr(answer, key, value)
        answer.merged_feedback = feedback
        answer.model_knowledge_notes = data.get("model_knowledge_notes", [])
        answer.disagreement = data.get("disagreement", False)
        answer.merge_fallback = data.get("merge_fallback", False)
        answer.grading_error = data.get("error")
        answer.prompt_version = data.get("prompt_version")
        answer.model_name = data.get("model_name")
        session.flush()
    return answer
