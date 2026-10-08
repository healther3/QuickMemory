"""SQLAlchemy models for the local QuickMemory database.

Exam answers hold their own immutable-at-exam-time card text. Deleting a card or
folder therefore removes its live relationships without erasing exam history.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    """本地初始化标记与不复用的错误类型 ID 序列。"""
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


card_user_tags = Table(
    "card_user_tags",
    Base.metadata,
    Column("card_id", ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True),
    Column("user_tag_id", ForeignKey("user_tags.id", ondelete="CASCADE"), primary_key=True),
)

card_folders = Table(
    "card_folders",
    Base.metadata,
    Column("card_id", ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True),
    Column("folder_id", ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True),
)

answer_error_types = Table(
    "answer_error_types",
    Base.metadata,
    Column("answer_id", ForeignKey("exam_answers.id", ondelete="CASCADE"), primary_key=True),
    Column("error_type_id", ForeignKey("error_types.id", ondelete="CASCADE"), primary_key=True),
)


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("length(trim(term)) > 0", name="ck_cards_term_nonempty"),
        CheckConstraint("length(trim(definition)) > 0", name="ck_cards_definition_nonempty"),
        Index("ix_cards_term", "term"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(Text)
    definition: Mapped[str] = mapped_column(Text)
    reference_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user_tags: Mapped[list[UserTag]] = relationship(
        secondary=card_user_tags, back_populates="cards", passive_deletes=True
    )
    folders: Mapped[list[Folder]] = relationship(
        secondary=card_folders, back_populates="cards", passive_deletes=True
    )
    answers: Mapped[list[ExamAnswer]] = relationship(
        back_populates="card", passive_deletes="all"
    )


class UserTag(Base):
    __tablename__ = "user_tags"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_user_tags_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    cards: Mapped[list[Card]] = relationship(
        secondary=card_user_tags, back_populates="user_tags", passive_deletes=True
    )


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_folders_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    cards: Mapped[list[Card]] = relationship(
        secondary=card_folders, back_populates="folders", passive_deletes=True
    )
    exam_sessions: Mapped[list[ExamSession]] = relationship(
        back_populates="folder", passive_deletes="all"
    )


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    parent_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="SET NULL"), index=True
    )
    folder_name_snapshot: Mapped[str] = mapped_column(String(200), default="")
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    folder: Mapped[Folder | None] = relationship(back_populates="exam_sessions")
    parent_session: Mapped[ExamSession | None] = relationship(
        remote_side="ExamSession.id", back_populates="retry_sessions"
    )
    retry_sessions: Mapped[list[ExamSession]] = relationship(
        back_populates="parent_session", passive_deletes="all"
    )
    answers: Mapped[list[ExamAnswer]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExamAnswer.position",
    )

    @validates("settings_snapshot")
    def omit_api_key(self, _key: str, value: dict[str, Any]) -> dict[str, Any]:
        """A historical settings snapshot must never duplicate the saved secret."""
        return deepcopy({key: item for key, item in value.items() if key != "api_key"})


class ExamAnswer(Base):
    __tablename__ = "exam_answers"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_exam_answer_position"),
        CheckConstraint("position >= 0", name="ck_exam_answer_position"),
        CheckConstraint("time_spent_ms >= 0", name="ck_exam_answer_time"),
        CheckConstraint("status IN ('pending', 'graded', 'failed')", name="ck_exam_answer_status"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 100", name="ck_exam_answer_accuracy"),
        CheckConstraint(
            "completeness >= 0 AND completeness <= 100", name="ck_exam_answer_completeness"
        ),
        CheckConstraint("final_score >= 0 AND final_score <= 100", name="ck_exam_answer_score"),
        CheckConstraint(
            "(status = 'graded' AND accuracy IS NOT NULL AND completeness IS NOT NULL "
            "AND final_score IS NOT NULL) OR (status != 'graded' AND accuracy IS NULL "
            "AND completeness IS NULL AND final_score IS NULL)",
            name="ck_exam_answer_scored_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True
    )
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    term_snapshot: Mapped[str] = mapped_column(Text)
    definition_snapshot: Mapped[str] = mapped_column(Text)
    user_answer: Mapped[str] = mapped_column(Text, default="")
    time_spent_ms: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accuracy: Mapped[float | None] = mapped_column(Float)
    completeness: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    merged_feedback: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), default=dict)
    model_knowledge_notes: Mapped[list[str]] = mapped_column(JSON(none_as_null=True), default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(300))
    grading_error: Mapped[str | None] = mapped_column(Text)
    disagreement: Mapped[bool] = mapped_column(Boolean, default=False)
    merge_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped[ExamSession] = relationship(back_populates="answers")
    card: Mapped[Card | None] = relationship(back_populates="answers")
    judge_results: Mapped[list[JudgeResult]] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="JudgeResult.judge_index",
    )
    error_types: Mapped[list[ErrorType]] = relationship(
        secondary=answer_error_types, back_populates="answers", passive_deletes=True
    )


class JudgeResult(Base):
    __tablename__ = "judge_results"
    __table_args__ = (
        UniqueConstraint("answer_id", "judge_index", name="uq_judge_answer_index"),
        CheckConstraint("judge_index >= 1 AND judge_index <= 3", name="ck_judge_index"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 100", name="ck_judge_accuracy"),
        CheckConstraint("completeness >= 0 AND completeness <= 100", name="ck_judge_completeness"),
        CheckConstraint(
            "(success = 1 AND accuracy IS NOT NULL AND completeness IS NOT NULL) "
            "OR (success = 0 AND accuracy IS NULL AND completeness IS NULL)",
            name="ck_judge_success_scores",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("exam_answers.id", ondelete="CASCADE"), index=True
    )
    judge_index: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float | None] = mapped_column(Float)
    completeness: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    raw_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    answer: Mapped[ExamAnswer] = relationship(back_populates="judge_results")


class ErrorType(Base):
    __tablename__ = "error_types"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_error_type_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    answers: Mapped[list[ExamAnswer]] = relationship(
        secondary=answer_error_types, back_populates="error_types", passive_deletes=True
    )


class Settings(Base):
    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_settings_single_row"),
        CheckConstraint("judge_count IN (2, 3)", name="ck_settings_judge_count"),
        CheckConstraint(
            "judge_temperature >= 0 AND judge_temperature <= 2", name="ck_settings_judge_temp"
        ),
        CheckConstraint(
            "merge_temperature >= 0 AND merge_temperature <= 2", name="ck_settings_merge_temp"
        ),
        CheckConstraint("w_accuracy >= 0 AND w_accuracy <= 1", name="ck_settings_weight_accuracy"),
        CheckConstraint(
            "w_completeness >= 0 AND w_completeness <= 1", name="ck_settings_weight_completeness"
        ),
        CheckConstraint(
            "abs(w_accuracy + w_completeness - 1.0) <= 0.000000001",
            name="ck_settings_weights_sum",
        ),
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100", name="ck_settings_pass_threshold"
        ),
        CheckConstraint("json_mode IN ('auto', 'on', 'off')", name="ck_settings_json_mode"),
        CheckConstraint(
            "request_timeout >= 1 AND request_timeout <= 600", name="ck_settings_request_timeout"
        ),
        CheckConstraint("length(trim(model)) > 0", name="ck_settings_model"),
        CheckConstraint("length(trim(provider)) > 0", name="ck_settings_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(100), default="deepseek")
    base_url: Mapped[str] = mapped_column(Text, default="https://api.deepseek.com/v1")
    api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(300), default="deepseek-chat")
    judge_count: Mapped[int] = mapped_column(Integer, default=3)
    judge_temperature: Mapped[float] = mapped_column(Float, default=0.7)
    merge_temperature: Mapped[float] = mapped_column(Float, default=0.2)
    w_accuracy: Mapped[float] = mapped_column(Float, default=0.5)
    w_completeness: Mapped[float] = mapped_column(Float, default=0.5)
    pass_threshold: Mapped[float] = mapped_column(Float, default=60.0)
    json_mode: Mapped[str] = mapped_column(String(10), default="auto")
    request_timeout: Mapped[float] = mapped_column(Float, default=60.0)
