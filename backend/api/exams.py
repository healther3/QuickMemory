"""Snapshot exams, background submission, complete results and manual labels."""

import random
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.common import get_db, iso, must_get
from backend.models import ErrorType, ExamAnswer, ExamSession, Folder, utc_now
from backend.repositories import get_settings, settings_snapshot

router = APIRouter(tags=["考试"])


class ExamStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: int = Field(gt=0, strict=True)


class AnswerSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_answer: str = Field(max_length=200000, strict=True)
    time_spent_ms: int = Field(ge=0, le=31536000000, strict=True)


class LabelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_type_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(max_length=1000)


class NamedType(BaseModel):
    id: int
    name: str


class QuestionResponse(BaseModel):
    id: int
    card_id: int | None
    position: int
    term: str
    user_answer: str
    time_spent_ms: int
    submitted_at: str | None
    status: Literal["pending", "graded", "failed"]


class JudgeResponse(BaseModel):
    judge_index: int
    success: bool
    accuracy: float | None
    completeness: float | None
    raw_json: dict | None
    raw_text: str | None
    error: str | None


class AnswerResponse(QuestionResponse):
    definition: str
    accuracy: float | None
    completeness: float | None
    final_score: float | None
    merged_feedback: dict[str, Any]
    model_knowledge_notes: list[str]
    judges: list[JudgeResponse]
    disagreement: bool
    merge_fallback: bool
    grading_error: str | None
    prompt_version: str | None
    model_name: str | None
    created_at: str
    error_types: list[NamedType]


class ExamResponse(BaseModel):
    id: int
    folder_id: int | None
    folder_name: str
    parent_session_id: int | None
    started_at: str
    finished_at: str | None
    total: int
    submitted_count: int
    graded_count: int
    failed_count: int
    pass_threshold: float
    answers: list[QuestionResponse]


class ResultsResponse(ExamResponse):
    answers: list[AnswerResponse]


class ExamListResponse(BaseModel):
    items: list[ExamResponse]
    total: int


class AcceptedResponse(BaseModel):
    accepted: Literal[True] = True
    answer_id: int


def question_dict(answer):
    return {"id": answer.id, "card_id": answer.card_id, "position": answer.position,
            "term": answer.term_snapshot, "user_answer": answer.user_answer,
            "time_spent_ms": answer.time_spent_ms, "submitted_at": iso(answer.submitted_at),
            "status": answer.status}


def answer_dict(answer):
    return {**question_dict(answer), "definition": answer.definition_snapshot,
            "accuracy": answer.accuracy, "completeness": answer.completeness,
            "final_score": answer.final_score, "merged_feedback": answer.merged_feedback,
            "model_knowledge_notes": answer.model_knowledge_notes,
            "judges": [{"judge_index": j.judge_index, "success": j.success,
                        "accuracy": j.accuracy, "completeness": j.completeness,
                        "raw_json": j.raw_json, "raw_text": j.raw_text, "error": j.error}
                       for j in answer.judge_results],
            "disagreement": answer.disagreement, "merge_fallback": answer.merge_fallback,
            "grading_error": answer.grading_error, "prompt_version": answer.prompt_version,
            "model_name": answer.model_name, "created_at": iso(answer.created_at),
            "error_types": [{"id": item.id, "name": item.name} for item in answer.error_types]}


def exam_dict(exam, *, results=False):
    answers = sorted(exam.answers, key=lambda item: item.position)
    return {"id": exam.id, "folder_id": exam.folder_id,
            "folder_name": exam.folder_name_snapshot, "parent_session_id": exam.parent_session_id,
            "started_at": iso(exam.started_at), "finished_at": iso(exam.finished_at),
            "total": len(answers), "submitted_count": sum(a.submitted_at is not None for a in answers),
            "graded_count": sum(a.status == "graded" for a in answers),
            "failed_count": sum(a.status == "failed" for a in answers),
            "pass_threshold": exam.settings_snapshot.get("pass_threshold", 60),
            "answers": [(answer_dict if results else question_dict)(a) for a in answers]}


def _new_exam(db, rows, folder_id, folder_name, parent_id=None):
    random.SystemRandom().shuffle(rows)
    exam = ExamSession(folder_id=folder_id, folder_name_snapshot=folder_name,
                       parent_session_id=parent_id, settings_snapshot=settings_snapshot(get_settings(db)))
    exam.answers = [ExamAnswer(card_id=card_id, position=index, term_snapshot=term,
                               definition_snapshot=definition)
                    for index, (card_id, term, definition) in enumerate(rows)]
    db.add(exam)
    db.commit()
    return exam_dict(exam)


@router.post("/exams", response_model=ExamResponse, status_code=201)
def create_exam(body: ExamStart, db: Session = Depends(get_db)):
    folder = must_get(db, Folder, body.folder_id)
    rows = [(card.id, card.term, card.definition) for card in folder.cards]
    if not rows:
        raise HTTPException(400, "文件夹中还没有卡片，请先添加卡片")
    return _new_exam(db, rows, folder.id, folder.name)


@router.get("/exams", response_model=ExamListResponse)
def list_exams(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    exams = db.scalars(select(ExamSession).order_by(ExamSession.id.desc()).limit(limit))
    return {"items": [exam_dict(exam) for exam in exams],
            "total": db.scalar(select(func.count()).select_from(ExamSession))}


@router.get("/exams/{exam_id}", response_model=ExamResponse)
def get_exam(exam_id: int, db: Session = Depends(get_db)):
    return exam_dict(must_get(db, ExamSession, exam_id))


@router.post("/answers/{answer_id}/submit", response_model=AcceptedResponse)
async def submit_answer(answer_id: int, body: AnswerSubmit, request: Request):
    with request.app.state.session_factory() as db:
        answer = must_get(db, ExamAnswer, answer_id)
        if answer.submitted_at is not None:
            if answer.user_answer != body.user_answer or answer.time_spent_ms != body.time_spent_ms:
                raise HTTPException(409, "本题已经提交，不能覆盖原作答")
        else:
            answer.user_answer = body.user_answer
            answer.time_spent_ms = body.time_spent_ms
            answer.submitted_at = utc_now()
            db.flush()
            remaining = db.scalar(select(func.count()).select_from(ExamAnswer).where(
                ExamAnswer.session_id == answer.session_id, ExamAnswer.submitted_at.is_(None)))
            if remaining == 0:
                answer.session.finished_at = utc_now()
            db.commit()
        pending = answer.status == "pending"
    if pending:
        request.app.state.grading_queue.enqueue(answer_id)
    return {"accepted": True, "answer_id": answer_id}


@router.get("/exams/{exam_id}/results", response_model=ResultsResponse)
def exam_results(exam_id: int, db: Session = Depends(get_db)):
    exam = must_get(db, ExamSession, exam_id)
    if any(answer.submitted_at is None for answer in exam.answers):
        raise HTTPException(409, "请提交本场全部题目后再查看参考答案和评分结果")
    return exam_dict(exam, results=True)


@router.post("/exams/{exam_id}/retry", response_model=ExamResponse, status_code=201)
def retry_exam(exam_id: int, db: Session = Depends(get_db)):
    exam = must_get(db, ExamSession, exam_id)
    if exam.finished_at is None or any(a.status == "pending" for a in exam.answers):
        raise HTTPException(409, "请等待本场全部题目提交并完成评分后再重考错题")
    threshold = exam.settings_snapshot.get("pass_threshold", 60)
    rows = [(a.card_id, a.term_snapshot, a.definition_snapshot) for a in exam.answers
            if a.status == "graded" and a.final_score is not None and a.final_score < threshold]
    if not rows:
        raise HTTPException(400, "本场没有已评分且低于及格线的错题，未评分题目不计为错题")
    return _new_exam(db, rows, exam.folder_id, exam.folder_name_snapshot, exam.id)


@router.post("/answers/{answer_id}/retry-grade", response_model=AcceptedResponse)
async def retry_grade(answer_id: int, request: Request):
    with request.app.state.session_factory() as db:
        answer = must_get(db, ExamAnswer, answer_id)
        if answer.status != "failed" or answer.submitted_at is None:
            raise HTTPException(409, "只有已提交但评分失败的答案可以重新评分")
        answer.status = "pending"
        answer.grading_error = None
        db.commit()
    request.app.state.grading_queue.enqueue(answer_id)
    return {"accepted": True, "answer_id": answer_id}


@router.patch("/answers/{answer_id}/error-types", response_model=AnswerResponse)
def update_labels(answer_id: int, body: LabelUpdate, db: Session = Depends(get_db)):
    answer = must_get(db, ExamAnswer, answer_id)
    if answer.status != "graded":
        raise HTTPException(409, "只有已评分答案可以修改错误类型")
    identifiers = set(body.error_type_ids)
    labels = list(db.scalars(select(ErrorType).where(ErrorType.id.in_(identifiers)).order_by(ErrorType.id)))
    if len(labels) != len(identifiers):
        raise HTTPException(400, "所选错误类型已不存在，请刷新后重试")
    answer.error_types = labels
    answer.merged_feedback = {**answer.merged_feedback, "error_types": [item.name for item in labels]}
    db.commit()
    return answer_dict(answer)
