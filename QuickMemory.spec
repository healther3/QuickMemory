# -*- mode: python ; coding: utf-8 -*-
"""Windows standalone, windowless, single-file release; private data is excluded."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, collect_data_files

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "examples" / "ml_terms.json"), "examples"),
    (str(ROOT / "assets" / "quickmemory.ico"), "assets"),
]
# importlib.metadata is used by the SDK and the offline release self-test.
for package in ("litellm", "fastapi", "uvicorn", "SQLAlchemy", "pydantic", "pywebview", "pythonnet"):
    datas += copy_metadata(package, recursive=True)
datas += collect_data_files("webview", includes=["js/**"])

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("backend") + [
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite", "tiktoken_ext.openai_public",
        "webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "clr_loader",
    ],
    hookspath=[str(ROOT / "scripts" / "pyinstaller_hooks")],
    runtime_hooks=[str(ROOT / "scripts" / "pyinstaller_hooks" / "runtime_local_only.py")],
    excludes=["pytest", "IPython", "notebook", "matplotlib", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="QuickMemory", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "quickmemory.ico"),
)
