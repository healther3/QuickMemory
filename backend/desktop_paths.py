"""Writable runtime locations for the portable EXE and an MSIX package."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re


def package_family_name() -> str | None:
    """Read the current process's package identity, without registry guesses."""
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_family = getattr(kernel, "GetCurrentPackageFamilyName", None)
    if get_family is None:
        return None
    get_family.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    get_family.restype = ctypes.c_long
    length = ctypes.c_uint32(0)
    result = get_family(ctypes.byref(length), None)
    if result == 15700:  # APPMODEL_ERROR_NO_PACKAGE
        return None
    if result != 122 or not 1 < length.value < 1024:  # ERROR_INSUFFICIENT_BUFFER
        raise RuntimeError("无法确定 Windows 应用数据目录，请重新启动轻记。")
    buffer = ctypes.create_unicode_buffer(length.value)
    if get_family(ctypes.byref(length), buffer) != 0:
        raise RuntimeError("无法读取 Windows 应用身份。")
    family = buffer.value
    if not re.fullmatch(r"[A-Za-z0-9.-]+_[A-Za-z0-9]+", family):
        raise RuntimeError("Windows 应用身份无效。")
    return family


def runtime_root() -> Path:
    """Packaged app state lives outside read-only WindowsApps; portable stays put."""
    from backend.launcher import application_root

    family = package_family_name()
    if family:
        local = os.environ.get("LOCALAPPDATA")
        if not local or not Path(local).is_absolute():
            raise RuntimeError("无法找到当前用户的本地应用数据目录。")
        root = Path(local) / "Packages" / family / "LocalState"
    else:
        root = application_root()
    override = os.environ.get("QUICKMEMORY_DB")
    if override and override != ":memory:":
        selected = Path(override).expanduser().resolve()
        if selected != (root / "data" / "quickmemory.db").resolve():
            return selected.parent
    return root.resolve()
