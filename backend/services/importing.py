"""Pure parsing and deterministic import planning, shared by preview and confirm."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import PureWindowsPath
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.api.common import card_dict, iso, must_get
from backend.api.catalog import Name, resolve_tags
from backend.models import Card, Folder, utc_now
from backend.schemas import StrictModel


class ImportRequest(StrictModel):
    content: str = Field(min_length=1, max_length=10000000, strict=True)
    filename: str | None = Field(default=None, max_length=255, strict=True)
    folder_id: int | None = Field(default=None, gt=0, strict=True)
    folder_name: str | None = Field(default=None, max_length=200, strict=True)
    duplicate_mode: Literal["skip", "overwrite"] = "skip"

    @model_validator(mode="after")
    def target_is_valid(self):
        if self.folder_id is None and not self.folder_name and not self.filename:
            raise ValueError("请选择已有文件夹，或填写新文件夹名称 / 文件名")
        return self


class ConfirmImportRequest(ImportRequest):
    preview_token: str = Field(min_length=1, max_length=200, strict=True)


class ImportEntry(StrictModel):
    term: str = Field(min_length=1, max_length=2000, strict=True)
    definition: str = Field(min_length=1, max_length=100000, strict=True)
    reference_note: str = Field(default="", max_length=100000, strict=True)
    tags: list[Name] = Field(default_factory=list, max_length=200)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, values):
        names = {}
        for value in values:
            names.setdefault(value.casefold(), value)
        return list(names.values())


class ImportRow(StrictModel):
    term: str
    definition: str
    action: Literal["add", "skip", "overwrite", "invalid"]
    reason: str


class ImportReport(StrictModel):
    added: int = 0
    skipped: int = 0
    overwritten: int = 0
    invalid: int = 0
    rows: list[ImportRow]
    preview_token: str = ""


class ImportConfirmed(ImportReport):
    folder_id: int


@dataclass
class ImportPlan:
    report: ImportReport
    entries: list[ImportEntry | None]
    target: Folder | None
    new_folder_name: str
    fingerprint: str
    existing: dict[str, Card]


class ObjectPairs(list):
    """Preserve duplicate terms in object imports rather than silently losing rows."""


def reject_nonfinite_json(_value: str):
    raise ValueError("JSON 不允许非有限数值")


def parse_content(content: str) -> list[dict | object]:
    try:
        value = json.loads(content.lstrip("\ufeff"), object_pairs_hook=ObjectPairs,
                           parse_constant=reject_nonfinite_json)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "JSON 内容无效，请检查引号、逗号和括号，并使用 UTF-8 编码") from exc
    if isinstance(value, ObjectPairs):
        if not all(isinstance(definition, str) for _, definition in value):
            raise HTTPException(400, "题库格式不匹配：对象格式的每个值都必须是定义文本；也可使用卡片对象数组")
        entries = [{"term": term, "definition": definition} for term, definition in value]
    elif isinstance(value, list):
        entries = []
        for row in value:
            if isinstance(row, ObjectPairs):
                if len({key for key, _ in row}) != len(row):
                    entries.append(None)
                else:
                    entries.append(dict(row))
            else:
                entries.append(row)
    else:
        raise HTTPException(400, "题库格式不匹配：请提供“术语 → 定义”对象或卡片对象数组")
    if len(entries) > 10000:
        raise HTTPException(400, "单次最多导入 10000 张卡片，请分批导入")
    return entries


def invalid_reason(exc: ValidationError) -> str:
    names = {"term": "术语", "definition": "定义", "reference_note": "参考笔记", "tags": "标签"}
    problems = []
    for error in exc.errors():
        field = names.get(str(error["loc"][0]), str(error["loc"][0])) if error["loc"] else "条目"
        kind = error["type"]
        if kind == "missing":
            problem = field + "缺失"
        elif kind in {"string_too_short", "too_short"}:
            problem = field + "不能为空"
        elif kind in {"string_too_long", "too_long"}:
            problem = field + "超出长度限制"
        elif kind == "extra_forbidden":
            problem = "不支持的字段：" + field
        else:
            problem = field + "格式错误，请检查文本和列表类型"
        if problem not in problems:
            problems.append(problem)
    return "；".join(problems)


def build_plan(db: Session, data: ImportRequest) -> ImportPlan:
    raw_entries = parse_content(data.content)
    target = must_get(db, Folder, data.folder_id) if data.folder_id is not None else None
    new_name = data.folder_name or (PureWindowsPath(data.filename or "导入题库.json").stem.strip())
    new_name = new_name[:200] or "导入题库"
    target_cards = [] if target is None else db.scalars(
        select(Card).where(Card.folders.any(Folder.id == target.id))
        .options(selectinload(Card.folders), selectinload(Card.user_tags)).order_by(Card.id)
    ).all()
    existing = {}
    for card in target_cards:
        existing.setdefault(card.term.strip().casefold(), card)
    # Fingerprint metadata too: shared-card warnings must still be true at confirm.
    snapshot = [{**card_dict(card),
                 "tags": sorted([{"id": tag.id, "name": tag.name} for tag in card.user_tags], key=lambda tag: tag["id"]),
                 "folders": sorted([{"id": folder.id, "name": folder.name} for folder in card.folders], key=lambda folder: folder["id"])}
                for card in target_cards]
    source = data.model_dump(exclude={"preview_token"})
    state = {"request": source, "target": None if target is None else {
        "id": target.id, "name": target.name, "created_at": iso(target.created_at), "cards": snapshot}}
    fingerprint = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    rows = []
    entries = []
    seen = set(existing)
    counts = {"added": 0, "skipped": 0, "overwritten": 0, "invalid": 0}
    for index, raw in enumerate(raw_entries, start=1):
        try:
            entry = ImportEntry.model_validate(raw)
        except ValidationError as exc:
            term = raw.get("term", "") if isinstance(raw, dict) else ""
            definition = raw.get("definition", "") if isinstance(raw, dict) else ""
            rows.append(ImportRow(term=term if isinstance(term, str) else "",
                                  definition=definition if isinstance(definition, str) else "",
                                  action="invalid", reason=f"第 {index} 项：{invalid_reason(exc)}"))
            entries.append(None)
            counts["invalid"] += 1
            continue
        key = entry.term.casefold()
        if key in seen:
            if data.duplicate_mode == "skip":
                action, reason = "skip", "术语已存在于目标文件夹或本次导入中"
                counts["skipped"] += 1
            else:
                action, reason = "overwrite", "仅覆盖定义，保留原有术语、标签、参考笔记与文件夹归属"
                if key in existing and len(existing[key].folders) > 1:
                    reason += f"；共享卡片同时属于 {len(existing[key].folders)} 个文件夹，其他文件夹中的定义也会更新"
                elif key not in existing:
                    reason += "；本次导入内重复，以最后一条定义为准"
                counts["overwritten"] += 1
        else:
            action, reason = "add", "新增卡片"
            counts["added"] += 1
            seen.add(key)
        rows.append(ImportRow(term=entry.term, definition=entry.definition, action=action, reason=reason))
        entries.append(entry)
    return ImportPlan(ImportReport(**counts, rows=rows), entries, target, new_name, fingerprint, existing)


def apply_plan(db: Session, plan: ImportPlan) -> Folder:
    folder = plan.target
    if folder is None:
        folder = Folder(name=plan.new_folder_name)
        db.add(folder)
        db.flush()
    existing = dict(plan.existing)
    for row, entry in zip(plan.report.rows, plan.entries):
        if entry is None or row.action == "skip":
            continue
        key = entry.term.casefold()
        if row.action == "overwrite":
            existing[key].definition = entry.definition
            existing[key].updated_at = utc_now()
        elif row.action == "add":
            card = Card(term=entry.term, definition=entry.definition,
                        reference_note=entry.reference_note, folders=[folder],
                        user_tags=resolve_tags(db, entry.tags))
            db.add(card)
            db.flush()  # Makes newly created tags visible to subsequent rows.
            existing[key] = card
    db.flush()
    return folder
