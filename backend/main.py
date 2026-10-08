"""FastAPI 本地应用，统一提供业务 API 和构建后的 React 文件。"""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.database import init_db, make_engine, make_session_factory
from backend.launcher import database_path
from backend.local_service import LauncherPreferences
from backend.seed import seed_once
from backend.services.grading import GradingService

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(db_path: str | Path | None = None, seed: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from backend.services.queue import GradingQueue
        engine = make_engine(db_path)
        init_db(engine)
        factory = make_session_factory(engine)
        if seed:
            seed_once(factory)
        app.state.engine = engine
        app.state.local_service_database = str(engine.url.database)
        app.state.session_factory = factory
        app.state.utility_llm_semaphore = asyncio.Semaphore(2)
        queue = GradingQueue(factory, app.state.grading_service, workers=2)
        app.state.grading_queue = queue
        await queue.start()
        try:
            yield
        finally:
            await queue.stop()
            engine.dispose()

    app = FastAPI(title="轻记 · 本地概念默写", version="1.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.grading_service = GradingService()
    app.state.local_service_database = str(db_path) if db_path is not None else str(database_path())
    app.state.local_service_preferences = LauncherPreferences()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_browser_requests(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                except ValueError:
                    return JSONResponse({"detail": "请求来源无效"}, status_code=403)
                allowed_ports = {request.url.port or 80, int(os.environ.get("QUICKMEMORY_VITE_PORT", "5173"))}
                if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"} or port not in allowed_ports:
                    return JSONResponse({"detail": "只允许从本机应用页面提交操作"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不接受外部网页发起的修改请求"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        names = {"term": "术语", "definition": "参考定义", "name": "名称", "user_answer": "作答内容",
                 "time_spent_ms": "作答用时", "content": "题库内容", "api_key": "API 密钥",
                 "judge_count": "裁判数量", "folder_ids": "所属文件夹", "folder_id": "文件夹",
                 "tags": "用户标签", "reference_note": "参考笔记", "preferred_port": "网页端口"}
        fields = list(dict.fromkeys(names.get(str(error["loc"][-1]), "输入参数") for error in exc.errors()))
        return JSONResponse({"detail": "、".join(fields) + "格式不正确，请检查必填项、数据类型及长度范围"}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request, _exc):
        return JSONResponse({"detail": "记录重复或数据已变更，请刷新后重试"}, status_code=409)

    @app.exception_handler(OperationalError)
    async def database_error(_request, _exc):
        return JSONResponse({"detail": "本地数据库暂时不可用，请稍后重试并检查数据目录"}, status_code=503)

    @app.get("/api/health", tags=["系统"])
    def health():
        return {"status": "ok", "message": "本地服务已就绪", "phase": 4}

    from backend.api import catalog, exams, imports, local_service, settings, stats
    for module in (catalog, imports, exams, stats, settings, local_service):
        app.include_router(module.router, prefix="/api")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/") or path in {"docs", "redoc"}:
            return JSONResponse({"detail": "未找到该接口"}, status_code=404)
        root = DIST.resolve()
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        if path.startswith("assets/") or Path(path).suffix:
            return JSONResponse({"detail": "未找到该文件"}, status_code=404)
        if (root / "index.html").is_file():
            return FileResponse(root / "index.html")
        return JSONResponse({"detail": "前端尚未构建，请先在 frontend 目录执行 npm install 和 npm run build"}, status_code=503)

    return app


app = create_app()
