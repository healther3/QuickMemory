"""Windows 双击入口：后台服务、浏览器和系统托盘。"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import threading
import webbrowser

from backend.launcher import (AlreadyRunning, InstanceLease, application_root, attach_instance_routes,
                              available_port, database_path, find_running, stop_running)


def show_error(message: str):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "轻记 · 启动提示", 0x10)
    else:
        print(message, file=sys.stderr)


def configure_output(root: Path):
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    output = logs / "launcher.log"
    if output.exists() and output.stat().st_size > 2_000_000:
        try:
            output.replace(logs / "launcher.previous.log")
        except OSError:
            # 另一个实例仍打开日志时（尤其 Windows），重复启动不能因轮转失败而中止。
            pass
    stream = output.open("a", encoding="utf-8", buffering=1)
    # --windowed 的 stdout/stderr 是 None。Uvicorn 和 SDK 均需要有效文本流。
    sys.stdout = stream
    sys.stderr = stream
    return stream


def run_application(args):
    database = database_path()
    os.environ["QUICKMEMORY_DB"] = str(database)
    if args.stop:
        state = find_running(database)
        return 0 if state is None or stop_running(state) else 1

    lease = InstanceLease(database)
    try:
        lease.__enter__()
    except AlreadyRunning:
        state = find_running(database, wait_seconds=8)
        if state:
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{state['page_port']}")
            return 0
        raise RuntimeError("轻记已经运行。\n\n若当前使用旧版启动脚本，请先在原启动窗口按 Ctrl+C 关闭，再双击轻记.exe。\n题库和设置不会丢失。") from None

    tray = None
    service_thread = None
    stopped = threading.Event()
    errors = []
    try:
        import uvicorn
        from backend.main import create_app

        port = available_port(args.port)
        url = f"http://localhost:{port}"
        app = create_app(database)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                             proxy_headers=False, access_log=False,
                                             timeout_graceful_shutdown=10, use_colors=False))
        def request_stop():
            server.should_exit = True

        attach_instance_routes(app, lease, request_stop)
        lease.publish(port)

        def open_page():
            if server.started:
                webbrowser.open(url)

        if not args.no_tray:
            from desktop_tray import TrayIcon
            assets_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
            tray = TrayIcon(assets_root / "assets" / "quickmemory.ico", open_page, request_stop)

        def serve():
            try:
                server.run()
                if not server.started:
                    errors.append("本地服务未能启动，请查看 logs/launcher.log。")
            except BaseException:
                logging.exception("本地服务启动或运行失败")
                errors.append("本地服务运行失败，请查看 logs/launcher.log。")
            finally:
                stopped.set()
                if tray:
                    tray.stop()

        def ready():
            for _ in range(300):
                if stopped.wait(0.2):
                    return
                if server.started:
                    if tray:
                        tray.set_title("轻记 · 双击打开，右键退出")
                    if not args.no_browser:
                        open_page()
                    return
            errors.append("启动超时，请检查数据目录与 logs/launcher.log。")
            request_stop()

        threading.Thread(target=ready, daemon=True, name="quickmemory-ready").start()
        if tray:
            service_thread = threading.Thread(target=serve, name="quickmemory-service")
            service_thread.start()
            try:
                tray.run()
            finally:
                request_stop()
                service_thread.join()
        else:
            serve()
        if errors:
            raise RuntimeError(errors[0])
        return 0
    finally:
        lease.__exit__(None, None, None)


def main():
    parser = argparse.ArgumentParser(description="轻记桌面启动器")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="用于自动验收")
    parser.add_argument("--stop", action="store_true", help="关闭同数据目录的正在运行实例")
    parser.add_argument("--self-test", metavar="REPORT", help="执行离线打包自检并写入报告")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024 到 65535 之间")
    stream = None
    try:
        stream = configure_output(application_root())
        if args.self_test:
            try:
                from backend.frozen_check import run_checks
                report = {"ok": True, "checks": run_checks()}
            except BaseException as exc:
                logging.exception("打包自检失败")
                report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            destination = Path(args.self_test).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0 if report["ok"] else 1
        return run_application(args)
    except Exception as exc:
        if stream:
            logging.exception("桌面入口失败")
        message = str(exc) if isinstance(exc, RuntimeError) else "启动失败，请确认轻记所在文件夹可写，并查看 logs/launcher.log。"
        if not args.no_tray:
            show_error(message)
        return 1
    finally:
        if stream:
            stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
