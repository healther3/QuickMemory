"""Import preview tokens bind confirmation to the input and target state."""

from collections import OrderedDict
from dataclasses import dataclass, field
import secrets
import threading
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.api.common import get_db
from backend.models import Settings
from backend.services.importing import (
    ConfirmImportRequest, ImportConfirmed, ImportReport, ImportRequest, apply_plan, build_plan,
)

router = APIRouter(tags=["题库导入"])
Db = Annotated[Session, Depends(get_db)]
_initialization_lock = threading.Lock()
TOKEN_LIFETIME = 30 * 60
MAX_TOKENS = 256


@dataclass
class PreviewStore:
    lock: threading.RLock = field(default_factory=threading.RLock)
    tokens: OrderedDict = field(default_factory=OrderedDict)

    def prune(self):
        cutoff = time.monotonic() - TOKEN_LIFETIME
        for token, (_, created) in list(self.tokens.items()):
            if created < cutoff:
                del self.tokens[token]


def preview_store(request: Request) -> PreviewStore:
    with _initialization_lock:
        if not hasattr(request.app.state, "import_previews"):
            request.app.state.import_previews = PreviewStore()
        return request.app.state.import_previews


@router.post("/imports/preview", response_model=ImportReport)
def preview_import(data: ImportRequest, request: Request, db: Db):
    plan = build_plan(db, data)
    store = preview_store(request)
    with store.lock:
        store.prune()
        while len(store.tokens) >= MAX_TOKENS:
            store.tokens.popitem(last=False)
        token = secrets.token_urlsafe(32)
        store.tokens[token] = (plan.fingerprint, time.monotonic())
    return plan.report.model_copy(update={"preview_token": token})


@router.post("/imports/confirm", response_model=ImportConfirmed)
def confirm_import(data: ConfirmImportRequest, request: Request, db: Db):
    store = preview_store(request)
    with store.lock:
        store.prune()
        saved = store.tokens.get(data.preview_token)
        if saved is None:
            raise HTTPException(409, "预览已过期或已确认，请重新预览后再导入")
        try:
            # Acquire SQLite's writer lock before reading a target fingerprint.
            # This closes the check/write gap against catalog edits and imports.
            db.execute(update(Settings).where(Settings.id == 1).values(id=1))
            try:
                plan = build_plan(db, data)
            except HTTPException as exc:
                if exc.status_code == 404:
                    raise HTTPException(409, "目标文件夹已变化，请重新预览") from exc
                raise
            if plan.fingerprint != saved[0]:
                raise HTTPException(409, "导入内容或目标文件夹已变化，请重新预览后再导入")
            folder = apply_plan(db, plan)
            db.commit()
        except (IntegrityError, OperationalError) as exc:
            db.rollback()
            raise HTTPException(409, "数据库正在更新或导入记录冲突，请重新预览后重试") from exc
        except Exception:
            db.rollback()
            raise
        del store.tokens[data.preview_token]
        return ImportConfirmed(**plan.report.model_dump(exclude={"preview_token"}),
                               preview_token=data.preview_token, folder_id=folder.id)
