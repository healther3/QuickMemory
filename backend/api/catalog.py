"""Local card, folder and user-tag catalog API."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.api.common import card_dict, folder_dict, get_db, must_get
from backend.models import Card, Folder, UserTag, utc_now
from backend.schemas import StrictModel

router = APIRouter(tags=["卡片与文件夹"])
Db = Annotated[Session, Depends(get_db)]
Name = Annotated[str, Field(min_length=1, max_length=200, strict=True)]


class NamedInput(StrictModel):
    name: Name


class CardInput(StrictModel):
    term: str = Field(min_length=1, max_length=2000, strict=True)
    definition: str = Field(min_length=1, max_length=100000, strict=True)
    reference_note: str = Field(default="", max_length=100000, strict=True)
    tags: list[Name] = Field(default_factory=list, max_length=200)
    folder_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def distinct_tags(cls, values):
        names = {}
        for value in values:
            names.setdefault(value.casefold(), value)
        return list(names.values())

    @field_validator("folder_ids")
    @classmethod
    def distinct_folders(cls, values):
        return list(dict.fromkeys(values))


class NamedOutput(BaseModel):
    id: int
    name: str


class TagOutput(NamedOutput):
    card_count: int


class FolderOutput(TagOutput):
    created_at: str


class CardOutput(BaseModel):
    id: int
    term: str
    definition: str
    reference_note: str
    tags: list[NamedOutput]
    folders: list[NamedOutput]
    created_at: str
    updated_at: str


class CardList(BaseModel):
    items: list[CardOutput]
    total: int


class ExportCard(BaseModel):
    term: str
    definition: str
    tags: list[str]
    reference_note: str


def resolve_tags(db: Session, names: list[str]) -> list[UserTag]:
    """Reuse case-insensitive names, creating only missing free-form tags."""
    existing = {tag.name.casefold(): tag for tag in db.scalars(select(UserTag)).all()}
    result = []
    for name in names:
        key = name.casefold()
        tag = existing.get(key)
        if tag is None:
            tag = UserTag(name=name)
            db.add(tag)
            existing[key] = tag
        if tag not in result:
            result.append(tag)
    return result


def save_card(db: Session, card: Card, data: CardInput):
    folders = [must_get(db, Folder, identifier) for identifier in data.folder_ids]
    card.term = data.term
    card.definition = data.definition
    card.reference_note = data.reference_note
    card.folders = folders
    card.user_tags = resolve_tags(db, data.tags)
    card.updated_at = utc_now()
    db.add(card)
    commit_catalog(db)
    return card_dict(card)


def commit_catalog(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "记录发生冲突，请刷新后重试") from exc


@router.get("/cards", response_model=CardList)
def list_cards(db: Db, q: str = "", tag_id: int | None = Query(None, gt=0),
               folder_id: int | None = Query(None, gt=0), offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=10000)):
    statement = select(Card).options(selectinload(Card.user_tags), selectinload(Card.folders))
    if tag_id is not None:
        statement = statement.where(Card.user_tags.any(UserTag.id == tag_id))
    if folder_id is not None:
        statement = statement.where(Card.folders.any(Folder.id == folder_id))
    cards = db.scalars(statement.order_by(Card.updated_at.desc(), Card.id.desc())).all()
    # SQLite lower/LIKE does not casefold Unicode (e.g. Straße versus STRASSE).
    keyword = q.strip().casefold()
    if keyword:
        cards = [card for card in cards if any(keyword in value.casefold()
                 for value in (card.term, card.definition, card.reference_note))]
    return {"items": [card_dict(card) for card in cards[offset:offset + limit]], "total": len(cards)}


@router.post("/cards", response_model=CardOutput, status_code=201)
def create_card(data: CardInput, db: Db):
    return save_card(db, Card(), data)


@router.get("/cards/{card_id}", response_model=CardOutput)
def get_card(card_id: int, db: Db):
    return card_dict(must_get(db, Card, card_id))


@router.put("/cards/{card_id}", response_model=CardOutput)
def update_card(card_id: int, data: CardInput, db: Db):
    return save_card(db, must_get(db, Card, card_id), data)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, db: Db):
    db.delete(must_get(db, Card, card_id))
    commit_catalog(db)
    return Response(status_code=204)


@router.get("/tags", response_model=list[TagOutput])
def list_tags(db: Db):
    tags = db.scalars(select(UserTag).options(selectinload(UserTag.cards)).order_by(UserTag.id)).all()
    return [{"id": tag.id, "name": tag.name, "card_count": len(tag.cards)} for tag in tags]


def save_tag(db: Session, tag: UserTag, name: str):
    if any(other.id != tag.id and other.name.casefold() == name.casefold()
           for other in db.scalars(select(UserTag)).all()):
        raise HTTPException(409, "已存在同名标签")
    tag.name = name
    db.add(tag)
    commit_catalog(db)
    return {"id": tag.id, "name": tag.name, "card_count": len(tag.cards)}


@router.post("/tags", response_model=TagOutput, status_code=201)
def create_tag(data: NamedInput, db: Db):
    return save_tag(db, UserTag(), data.name)


@router.put("/tags/{tag_id}", response_model=TagOutput)
def update_tag(tag_id: int, data: NamedInput, db: Db):
    return save_tag(db, must_get(db, UserTag, tag_id), data.name)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Db):
    db.delete(must_get(db, UserTag, tag_id))
    commit_catalog(db)
    return Response(status_code=204)


@router.get("/folders", response_model=list[FolderOutput])
def list_folders(db: Db):
    folders = db.scalars(select(Folder).options(selectinload(Folder.cards)).order_by(Folder.id)).all()
    return [folder_dict(folder) for folder in folders]


@router.post("/folders", response_model=FolderOutput, status_code=201)
def create_folder(data: NamedInput, db: Db):
    folder = Folder(name=data.name)
    db.add(folder)
    commit_catalog(db)
    return folder_dict(folder)


@router.put("/folders/{folder_id}", response_model=FolderOutput)
def update_folder(folder_id: int, data: NamedInput, db: Db):
    folder = must_get(db, Folder, folder_id)
    folder.name = data.name
    commit_catalog(db)
    return folder_dict(folder)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int, db: Db):
    db.delete(must_get(db, Folder, folder_id))
    commit_catalog(db)
    return Response(status_code=204)


@router.get("/folders/{folder_id}/export", response_model=list[ExportCard])
def export_folder(folder_id: int, db: Db):
    folder = must_get(db, Folder, folder_id)
    rows = [{"term": card.term, "definition": card.definition,
             "tags": [tag.name for tag in card.user_tags], "reference_note": card.reference_note}
            for card in sorted(folder.cards, key=lambda item: item.id)]
    return JSONResponse(rows, headers={"Content-Disposition":
                        "attachment; filename*=UTF-8''" + quote(folder.name + ".json", safe="")})
