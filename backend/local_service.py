"""独立于题库及模型密钥的本机启动偏好。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.launcher import database_path


class LauncherPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_port: int = Field(default=8000, ge=1024, le=65535, strict=True)


class LauncherPreferencesError(RuntimeError):
    """向本机使用者显示的配置读写错误，不包含配置文件内容。"""


def preferences_path(db_path: str | Path | None = None) -> Path:
    if str(db_path) == ":memory:":
        raise ValueError("内存数据库没有启动配置文件")
    database = Path(db_path).expanduser().resolve() if db_path is not None else database_path()
    return database.parent / "launcher.json"


def read_preferences(db_path: str | Path | None = None) -> LauncherPreferences:
    path = preferences_path(db_path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return LauncherPreferences()
    except OSError as exc:
        raise LauncherPreferencesError("无法读取本地启动配置 launcher.json，请检查数据目录的访问权限。") from exc
    except UnicodeError as exc:
        raise LauncherPreferencesError("本地启动配置 launcher.json 无法解码，请将其保存为 UTF-8 后重试。") from exc
    try:
        return LauncherPreferences.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise LauncherPreferencesError(
            "本地启动配置 launcher.json 无效：preferred_port 必须是 1024–65535 的整数。请修正或移走该文件后重试。"
        ) from exc


def save_preferences(preferences: LauncherPreferences, db_path: str | Path | None = None) -> LauncherPreferences:
    """先完整写入临时文件，再原子替换，防止中途退出损坏现有配置。"""
    preferences = LauncherPreferences.model_validate(preferences.model_dump())
    path = preferences_path(db_path)
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="launcher-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(preferences.model_dump(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        raise LauncherPreferencesError("无法保存本地启动配置 launcher.json，请检查数据目录的写入权限。") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return preferences
