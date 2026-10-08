"""源码和桌面入口共用的本机实例锁；实例令牌不属于模型凭证。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def database_path() -> Path:
    return Path(os.environ.get("QUICKMEMORY_DB", application_root() / "data" / "quickmemory.db")).expanduser().resolve()


def database_identity(path: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()


def available_port(preferred: int, exclude: tuple[int, ...] = ()) -> int:
    for port in range(preferred, min(preferred + 20, 65536)):
        if port in exclude:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("附近端口均被占用，请使用 --port 指定其他端口")


class AlreadyRunning(RuntimeError):
    def __init__(self):
        super().__init__("此数据库的轻记应用已经运行")


class InstanceLease:
    def __init__(self, path: Path | None = None):
        self.database = (path or database_path()).resolve()
        self.state_file = self.database.with_name(self.database.name + ".runtime.json")
        self.identity = database_identity(self.database)
        self.token = secrets.token_hex(32)
        self._file = None

    def __enter__(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        handle = self.database.with_name(self.database.name + ".lock").open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise AlreadyRunning() from None
        self._file = handle
        return self

    def publish(self, port: int, page_port: int | None = None):
        if self._file is None:
            raise RuntimeError("发布实例前必须取得数据库锁")
        state = {"app": "QuickMemory", "database": self.identity, "pid": os.getpid(),
                 "port": port, "page_port": page_port or port, "token": self.token}
        temporary = self.state_file.with_suffix(f".tmp-{os.getpid()}")
        try:
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.replace(self.state_file)
        finally:
            temporary.unlink(missing_ok=True)

    def __exit__(self, *_):
        try:
            try:
                state = json.loads(self.state_file.read_text(encoding="utf-8"))
                if state.get("token") == self.token:
                    self.state_file.unlink(missing_ok=True)
            except (OSError, ValueError, AttributeError):
                pass
        finally:
            if self._file is not None:
                self._file.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                finally:
                    self._file.close()
                    self._file = None


def _read_state(path: Path) -> dict | None:
    try:
        state = json.loads(path.with_name(path.name + ".runtime.json").read_text(encoding="utf-8"))
        if state.get("app") != "QuickMemory" or state.get("database") != database_identity(path):
            return None
        for key in ("port", "page_port"):
            if type(state.get(key)) is not int or not 1024 <= state[key] <= 65535:
                return None
        token = state.get("token")
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            return None
        return state
    except (OSError, ValueError, AttributeError):
        return None


def _request_instance(state: dict, stop: bool = False):
    # 不继承系统代理；控制令牌只发送到固定的本机环回地址。
    request = Request(f"http://127.0.0.1:{state['port']}/api/_local_instance",
                      headers={"X-QuickMemory-Instance": state["token"]},
                      method="POST" if stop else "GET", data=b"" if stop else None)
    with build_opener(ProxyHandler({})).open(request, timeout=0.7) as response:
        return json.load(response)


def find_running(path: Path | None = None, wait_seconds: float = 0) -> dict | None:
    path = (path or database_path()).resolve()
    deadline = time.monotonic() + wait_seconds
    while True:
        state = _read_state(path)
        if state:
            try:
                result = _request_instance(state)
                if result.get("app") == "QuickMemory" and result.get("database") == state["database"]:
                    return state
            except (OSError, ValueError, AttributeError):
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.15)


def stop_running(state: dict) -> bool:
    return _request_instance(state, stop=True).get("stopping") is True


def attach_instance_routes(app, lease: InstanceLease, on_stop):
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def control(request):
        supplied = request.headers.get("X-QuickMemory-Instance", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), lease.token.encode("ascii")):
            return JSONResponse({"detail": "无效的本机实例请求"}, status_code=403)
        if request.method == "POST":
            on_stop()
            return JSONResponse({"stopping": True})
        return JSONResponse({"app": "QuickMemory", "database": lease.identity})

    # 位于静态 SPA catch-all 之前；不改变业务 OpenAPI 契约。
    app.router.routes.insert(0, Route("/api/_local_instance", control, methods=["GET", "POST"]))
