"""History and many-to-many-safe statistics; ungraded scores remain null."""

from statistics import mean

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.api.common import card_dict, get_db, must_get
from backend.api.catalog import CardOutput, NamedOutput
from backend.api.exams import AnswerResponse, ExamResponse, answer_dict, exam_dict
from backend.models import Card, ErrorType, ExamAnswer, ExamSession, Folder, UserTag

router = APIRouter(tags=["统计"])


class CardStats(BaseModel):
    id: int
    term: str
    tags: list[NamedOutput]
    folder_ids: list[int]
    attempt_count: int
    average_score: float | None
    lowest_score: float | None
    last_score: float | None
    average_time_ms: float | None


class CardHistory(BaseModel):
    card: CardOutput
    stats: CardStats
    answers: list[AnswerResponse]


class Overview(BaseModel):
    card_count: int
    folder_count: int
    attempt_count: int
    graded_count: int
    average_score: float | None
    average_time_ms: float | None


class ErrorDistribution(NamedOutput):
    count: int


class StatsResponse(BaseModel):
    overview: Overview
    error_distribution: list[ErrorDistribution]
    cards: list[CardStats]
    recent_exams: list[ExamResponse]


def _average(values):
    return mean(values) if values else None


def card_stats(card, answers):
    submitted = [a for a in answers if a.submitted_at is not None]
    graded = sorted((a for a in submitted if a.status == "graded" and a.final_score is not None),
                    key=lambda a: (a.submitted_at, a.id))
    scores = [a.final_score for a in graded]
    return {"id": card.id, "term": card.term,
            "tags": [{"id": t.id, "name": t.name} for t in card.user_tags],
            "folder_ids": [folder.id for folder in card.folders],
            "attempt_count": len(submitted), "average_score": _average(scores),
            "lowest_score": min(scores) if scores else None,
            "last_score": graded[-1].final_score if graded else None,
            "average_time_ms": _average([answer.time_spent_ms for answer in submitted])}


@router.get("/cards/{card_id}/history", response_model=CardHistory)
def card_history(card_id: int, db: Session = Depends(get_db)):
    card = must_get(db, Card, card_id)
    answers = list(db.scalars(select(ExamAnswer).where(ExamAnswer.card_id == card_id,
                        ExamAnswer.submitted_at.is_not(None)).order_by(ExamAnswer.submitted_at.desc(), ExamAnswer.id.desc())))
    return {"card": card_dict(card), "stats": card_stats(card, answers),
            "answers": [answer_dict(answer) for answer in answers]}


@router.get("/stats", response_model=StatsResponse)
def statistics(folder_id: int | None = None, tag_id: int | None = None, db: Session = Depends(get_db)):
    card_query = select(Card).options(selectinload(Card.user_tags), selectinload(Card.folders))
    if folder_id is not None:
        must_get(db, Folder, folder_id)
        card_query = card_query.where(Card.folders.any(Folder.id == folder_id))
    if tag_id is not None:
        must_get(db, UserTag, tag_id)
        card_query = card_query.where(Card.user_tags.any(UserTag.id == tag_id))
    cards = list(db.scalars(card_query))
    selected_ids = [card.id for card in cards]
    answer_query = select(ExamAnswer).where(ExamAnswer.submitted_at.is_not(None)).options(selectinload(ExamAnswer.error_types))
    exam_query = select(ExamSession).order_by(ExamSession.id.desc())
    folder_query = select(Folder)
    if folder_id is not None or tag_id is not None:
        answer_query = answer_query.where(ExamAnswer.card_id.in_(selected_ids))
        exam_query = exam_query.where(ExamSession.answers.any(ExamAnswer.card_id.in_(selected_ids)))
        folder_query = folder_query.where(Folder.cards.any(Card.id.in_(selected_ids)))
    if folder_id is not None:
        folder_query = select(Folder).where(Folder.id == folder_id)
    answers = list(db.scalars(answer_query))
    by_card = {card.id: [] for card in cards}
    for answer in answers:
        if answer.card_id in by_card:
            by_card[answer.card_id].append(answer)
    rows = [card_stats(card, by_card[card.id]) for card in cards]
    rows.sort(key=lambda row: (row["average_score"] is None, row["average_score"] or 0, row["id"]))
    graded = [answer for answer in answers if answer.status == "graded" and answer.final_score is not None]
    counts: dict[int, int] = {}
    for answer in graded:
        for label in answer.error_types:
            counts[label.id] = counts.get(label.id, 0) + 1
    distribution = [{"id": label.id, "name": label.name, "count": counts.get(label.id, 0)}
                    for label in db.scalars(select(ErrorType).order_by(ErrorType.id))]
    distribution.sort(key=lambda item: (-item["count"], item["id"]))
    return {"overview": {"card_count": len(cards), "folder_count": len(list(db.scalars(folder_query))),
                         "attempt_count": len(answers), "graded_count": len(graded),
                         "average_score": _average([answer.final_score for answer in graded]),
                         "average_time_ms": _average([answer.time_spent_ms for answer in answers])},
            "error_distribution": distribution, "cards": rows,
            "recent_exams": [exam_dict(exam) for exam in db.scalars(exam_query.limit(10))]}
