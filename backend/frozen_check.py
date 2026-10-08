"""发行包离线自检：使用内存数据库和本机模拟接口，不接触用户资料。

仅供桌面入口的独立 ``--self-test`` 进程调用；网络保护会临时作用于整个进程。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import io
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import platform
import socket
import sqlite3
import sys
import threading


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _loopback(host) -> str:
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(str(host).split("%", 1)[0])
        mapped = getattr(address, "ipv4_mapped", None)
        if address.is_loopback or (mapped is not None and mapped.is_loopback):
            return str(host)
    except ValueError:
        pass
    raise OSError("离线自检禁止连接非本机地址")


@contextmanager
def _local_network_only():
    """在 SDK 导入之前禁用外部 DNS、连接与数据报，退出时还原全部钩子。"""
    originals = {}
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                  "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    previous_env = {key: os.environ.get(key) for key in proxy_keys}

    def replace(owner, name, value):
        originals[(owner, name)] = getattr(owner, name)
        setattr(owner, name, value)

    def check_address(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            if not isinstance(address, tuple) or not address:
                raise OSError("离线自检收到无效网络地址")
            _loopback(address[0])
        elif sock.family != getattr(socket, "AF_UNIX", object()):
            raise OSError("离线自检不允许此网络协议")

    def guarded_connection(method):
        def call(sock, address):
            check_address(sock, address)
            return method(sock, address)
        return call

    def guarded_send(method):
        def call(sock, *args, **kwargs):
            check_address(sock, sock.getpeername())
            return method(sock, *args, **kwargs)
        return call

    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo
    original_getnameinfo = socket.getnameinfo

    def sendto(sock, *args):
        check_address(sock, args[-1])
        return original_sendto(sock, *args)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(_loopback(host), port, family, type, proto,
                                    flags | socket.AI_NUMERICHOST)

    def gethostbyname(host):
        value = _loopback(host)
        if ipaddress.ip_address(value).version != 4:
            raise OSError("离线自检 IPv4 地址无效")
        return value

    def gethostbyname_ex(host):
        return ("localhost", [], [gethostbyname(host)])

    def gethostbyaddr(host):
        return ("localhost", [], [_loopback(host)])

    def getnameinfo(address, flags):
        _loopback(address[0])
        return original_getnameinfo(address, flags | socket.NI_NUMERICHOST | socket.NI_NUMERICSERV)

    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
        for name in ("connect", "connect_ex"):
            replace(socket.socket, name, guarded_connection(getattr(socket.socket, name)))
        for name in ("send", "sendall"):
            replace(socket.socket, name, guarded_send(getattr(socket.socket, name)))
        replace(socket.socket, "sendto", sendto)
        if hasattr(socket.socket, "sendmsg"):
            original_sendmsg = socket.socket.sendmsg

            def sendmsg(sock, buffers, ancdata=(), flags=0, address=None):
                check_address(sock, address if address is not None else sock.getpeername())
                if address is None:
                    return original_sendmsg(sock, buffers, ancdata, flags)
                return original_sendmsg(sock, buffers, ancdata, flags, address)

            replace(socket.socket, "sendmsg", sendmsg)
        replace(socket, "getaddrinfo", getaddrinfo)
        replace(socket, "gethostbyname", gethostbyname)
        replace(socket, "gethostbyname_ex", gethostbyname_ex)
        replace(socket, "gethostbyaddr", gethostbyaddr)
        replace(socket, "getnameinfo", getnameinfo)
        yield
    finally:
        for (owner, name), original in reversed(tuple(originals.items())):
            setattr(owner, name, original)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _check_database():
    from sqlalchemy import func, select
    from backend.database import init_db, make_engine, make_session_factory
    from backend.models import Card, Folder, Settings
    from backend.seed import seed_once

    engine = make_engine(":memory:")
    try:
        init_db(engine)
        factory = make_session_factory(engine)
        seed_once(factory)
        seed_once(factory)
        with factory() as db:
            _require(db.scalar(select(func.count()).select_from(Card)) == 10,
                     "内存数据库示例卡片数量不正确")
            _require(db.scalar(select(func.count()).select_from(Folder)) == 1,
                     "内存数据库示例文件夹不正确")
            _require(db.get(Settings, 1).api_key == "", "自检数据库不应包含真实密钥")
    finally:
        engine.dispose()


def _check_grading():
    from backend.schemas import SettingsData
    from backend.services.grading import GradingService
    from backend.services.llm import load_litellm

    load_litellm()  # 使用真实 SDK 导入和 HTTP 路径，禁用任何 mock_response 捷径。
    note = "【自检模拟】模型补充提示不参与评分。"
    sections = {"correct_parts": ["【自检模拟】覆盖参考中的训练集表现。"],
                "wrong_parts": ["【自检模拟】遗漏参考中的泛化表现。"],
                "uncertain_parts": [], "error_types": ["遗漏要点"],
                "model_knowledge_notes": [note]}
    counts = {"judges": [], "merge": 0, "invalid": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                _require(self.path == "/v1/chat/completions", "自检接口路径错误")
                length = int(self.headers.get("Content-Length", "0"))
                _require(0 < length <= 100_000, "自检请求大小错误")
                request = json.loads(self.rfile.read(length))
                _require(request.get("model") == "quickmemory-self-test", "自检模型名错误")
                _require(request.get("stream", False) is False, "自检不应使用流式请求")
                _require(request.get("response_format") == {"type": "json_object"},
                         "自检必须验证 JSON 模式")
                payload = json.loads(request["messages"][1]["content"])
                if "judge_index" in payload:
                    index = payload["judge_index"]
                    _require(index in (1, 2, 3), "自检裁判编号错误")
                    response = {**sections, "accuracy": [72.0, 84.0, 96.0][index - 1],
                                "completeness": [50.0, 60.0, 70.0][index - 1],
                                "reasoning": "【自检模拟】只按给定参考定义评分。"}
                    with lock:
                        counts["judges"].append(index)
                else:
                    _require(len(payload.get("judges", [])) == 3, "自检合并输入错误")
                    _require(all("accuracy" not in judge and "completeness" not in judge
                                 for judge in payload["judges"]), "合并调用不应携带数值评分")
                    response = sections
                    with lock:
                        counts["merge"] += 1
                content = json.dumps({"id": "quickmemory-offline-check", "object": "chat.completion",
                    "created": 0, "model": "quickmemory-self-test",
                    "choices": [{"index": 0, "message": {"role": "assistant",
                        "content": json.dumps(response, ensure_ascii=False)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
                    ensure_ascii=False).encode("utf-8")
                status = 200
            except Exception:
                with lock:
                    counts["invalid"] += 1
                status, content = 400, b'{"error":{"message":"offline check failed"}}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = SettingsData(provider="custom", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                api_key="offline-self-test-placeholder", model="quickmemory-self-test",
                                judge_count=3, w_accuracy=0.6, w_completeness=0.4,
                                json_mode="on", request_timeout=15)
        # SelectorEventLoop 确保 Windows 上也经过已保护的 socket.connect，
        # 不经过 Proactor 的底层 ConnectEx 路径。
        result = asyncio.run(GradingService().grade(term="自检：过拟合",
            reference_definition="训练集表现好，但泛化表现差。", user_answer="训练集表现好。",
            settings=settings, error_types=["遗漏要点"]), loop_factory=asyncio.SelectorEventLoop)
        _require(result.status == "graded" and len(result.judges) == 3 and
                 all(judge.success for judge in result.judges), "真实 SDK 的本机裁判调用失败")
        _require(result.accuracy == 84.0 and result.completeness == 60.0 and
                 math.isclose(result.final_score, 74.4), "多裁判数值聚合结果不正确")
        _require(not result.merge_fallback and result.disagreement, "合并或裁判分歧检查失败")
        _require(result.model_knowledge_notes == [note] and
                 result.merged_feedback.model_dump() == {
                     key: value for key, value in sections.items() if key != "model_knowledge_notes"
                 }, "模型提示隔离检查失败")
        _require(sorted(counts["judges"]) == [1, 2, 3] and counts["merge"] == 1 and
                 counts["invalid"] == 0, "本机模拟接口调用次数不正确")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_checks() -> dict:
    """返回无密钥的紧凑报告；失败抛异常，由桌面入口保存失败报告。"""
    root = Path(__file__).resolve().parents[1]
    _require((root / "frontend" / "dist" / "index.html").is_file(), "发行包缺少前端页面")
    _require(any((root / "frontend" / "dist" / "assets").glob("*.js")), "发行包缺少前端脚本")
    _require((root / "examples" / "ml_terms.json").is_file(), "发行包缺少示例题库")
    previous_logging = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with _local_network_only(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            _check_database()
            _check_grading()
    finally:
        logging.disable(previous_logging)
    import sqlalchemy
    return {"status": "ok", "frozen": bool(getattr(sys, "frozen", False)),
            "checks": {"resources": True, "sqlite_seed_cards": 10,
                       "litellm_local_judges": 3, "litellm_local_merge": True,
                       "numeric_aggregation": True, "knowledge_notes_separate": True,
                       "external_network_blocked": True},
            "versions": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                         "sqlalchemy": sqlalchemy.__version__,
                         "litellm": importlib.metadata.version("litellm")}}
