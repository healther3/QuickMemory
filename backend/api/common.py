from datetime import timezone

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def must_get(db: Session, model, identifier: int):
    obj = db.get(model, identifier)
    if obj is None:
        raise HTTPException(404, "未找到对应记录，可能已被删除")
    return obj


def card_dict(card):
    return {"id": card.id, "term": card.term, "definition": card.definition,
            "reference_note": card.reference_note,
            "tags": [{"id": t.id, "name": t.name} for t in card.user_tags],
            "folders": [{"id": f.id, "name": f.name} for f in card.folders],
            "created_at": iso(card.created_at), "updated_at": iso(card.updated_at)}


def folder_dict(folder):
    return {"id": folder.id, "name": folder.name, "card_count": len(folder.cards),
            "created_at": iso(folder.created_at)}
