from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.common import get_db, must_get
from backend.models import AppMeta, ErrorType
from backend.providers import list_provider_presets
from backend.repositories import get_settings, save_settings
from backend.schemas import ConnectionFeedback, PrecheckFeedback, Provider, SettingsData
from backend.services.llm import LLMError

router = APIRouter(tags=["设置与核对"])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Provider | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    model: str | None = None
    judge_count: Literal[2, 3] | None = None
    judge_temperature: float | None = None
    merge_temperature: float | None = None
    w_accuracy: float | None = None
    w_completeness: float | None = None
    pass_threshold: float | None = None
    json_mode: Literal["auto", "on", "off"] | None = None
    request_timeout: float | None = None


class SettingsView(BaseModel):
    provider: str
    base_url: str
    model: str
    judge_count: int
    judge_temperature: float
    merge_temperature: float
    w_accuracy: float
    w_completeness: float
    pass_threshold: float
    json_mode: str
    request_timeout: float
    has_api_key: bool


class NameInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)


class NameView(BaseModel):
    id: int
    name: str


class PrecheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    term: str = Field(min_length=1, max_length=2000)
    definition: str = Field(min_length=1, max_length=100000)
    reference_note: str = Field(default="", max_length=100000)


def resolve_settings(db: Session, body: SettingsInput) -> SettingsData:
    current = SettingsData.model_validate(get_settings(db)).model_dump()
    changes = body.model_dump(exclude_none=True)
    changed_target = any(key in changes and changes[key].rstrip("/") != current[key].rstrip("/")
                         for key in ("provider", "base_url"))
    if changed_target and body.api_key is None:
        current["api_key"] = ""
    current.update(changes)
    try:
        return SettingsData.model_validate(current)
    except ValidationError:
        raise HTTPException(422, "模型配置无效，请检查地址、模型名称、参数范围及权重之和是否为 1") from None


@router.get("/settings", response_model=SettingsView)
def read_settings(db: Session = Depends(get_db)):
    return SettingsData.model_validate(get_settings(db)).public_dict()


@router.put("/settings", response_model=SettingsView)
def update_settings(body: SettingsInput, db: Session = Depends(get_db)):
    config = resolve_settings(db, body)
    save_settings(db, config.model_dump())
    db.commit()
    return config.public_dict()


@router.get("/providers")
def providers():
    return list_provider_presets()


@router.post("/settings/test", response_model=ConnectionFeedback)
async def test_connection(body: SettingsInput, request: Request):
    with request.app.state.session_factory() as db:
        config = resolve_settings(db, body)
    try:
        async with request.app.state.utility_llm_semaphore:
            return await request.app.state.grading_service.test_connection(config)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/precheck", response_model=PrecheckFeedback)
async def precheck(body: PrecheckInput, request: Request):
    with request.app.state.session_factory() as db:
        config = SettingsData.model_validate(get_settings(db))
    try:
        async with request.app.state.utility_llm_semaphore:
            return await request.app.state.grading_service.precheck(**body.model_dump(), settings=config)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/error-types", response_model=list[NameView])
def list_error_types(db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name} for t in db.scalars(select(ErrorType).order_by(ErrorType.id))]


def record_sequence(db: Session) -> AppMeta:
    maximum = db.scalar(select(func.max(ErrorType.id))) or 0
    sequence = db.get(AppMeta, "error_type_sequence")
    if sequence is None:
        sequence = AppMeta(key="error_type_sequence", value=str(maximum))
        db.add(sequence)
    else:
        sequence.value = str(max(maximum, int(sequence.value)))
    return sequence


@router.post("/error-types", response_model=NameView, status_code=201)
def create_error_type(body: NameInput, db: Session = Depends(get_db)):
    if db.scalar(select(ErrorType).where(ErrorType.name == body.name)):
        raise HTTPException(409, "此错误类型已存在")
    sequence = record_sequence(db)
    identifier = int(sequence.value) + 1
    sequence.value = str(identifier)
    item = ErrorType(id=identifier, name=body.name)
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name}


@router.put("/error-types/{identifier}", response_model=NameView)
def rename_error_type(identifier: int, body: NameInput, db: Session = Depends(get_db)):
    item = must_get(db, ErrorType, identifier)
    if db.scalar(select(ErrorType).where(ErrorType.name == body.name, ErrorType.id != identifier)):
        raise HTTPException(409, "此错误类型已存在")
    item.name = body.name
    for answer in item.answers:
        answer.merged_feedback = {**answer.merged_feedback, "error_types": [t.name for t in answer.error_types]}
    db.commit()
    return {"id": item.id, "name": item.name}


@router.delete("/error-types/{identifier}", status_code=204)
def delete_error_type(identifier: int, db: Session = Depends(get_db)):
    item = must_get(db, ErrorType, identifier)
    record_sequence(db)
    for answer in list(item.answers):
        answer.merged_feedback = {**answer.merged_feedback,
                                  "error_types": [t.name for t in answer.error_types if t.id != identifier]}
    db.delete(item)
    db.commit()
    return Response(status_code=204)
