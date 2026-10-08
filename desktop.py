"""Windows 双击入口：独立窗口；--browser 可使用浏览器和系统托盘。"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import threading
import webbrowser

from backend.launcher import (AlreadyRunning, InstanceLease, activate_running, attach_instance_routes,
                              available_port, database_path, find_running, stop_running)
from backend.desktop_paths import runtime_root
from backend.local_service import read_preferences


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
    logger = logging.getLogger("quickmemory.desktop")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(stream))
    return stream


def run_application(args):
    isolated_database = bool(os.environ.get("QUICKMEMORY_DB"))
    database = database_path()
    os.environ["QUICKMEMORY_DB"] = str(database)
    if args.stop:
        state = find_running(database)
        return 0 if state is None or stop_running(state) else 1
    desktop_mode = not args.browser and not args.no_browser
    if args.window_smoke_test and (not desktop_mode or not isolated_database):
        raise RuntimeError("窗口验收需要独立的 QUICKMEMORY_DB 数据目录，并使用默认桌面模式。")

    lease = InstanceLease(database)
    try:
        lease.__enter__()
    except AlreadyRunning:
        state = find_running(database, wait_seconds=8)
        if state:
            if args.window_smoke_test:
                raise RuntimeError("窗口验收数据目录已有运行实例，请使用独立目录。")
            if desktop_mode:
                if activate_running(state):
                    return 0
                raise RuntimeError("此数据目录的轻记已在浏览器模式运行。\n请在设置页关闭本地服务，再重新双击轻记，即可打开独立窗口。\n题库和设置不会丢失。")
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{state['page_port']}")
            return 0
        raise RuntimeError("轻记已经运行。\n\n若当前使用旧版启动脚本，请先在原启动窗口按 Ctrl+C 关闭，再双击轻记.exe。\n题库和设置不会丢失。") from None

    tray = None
    window = None
    service_thread = None
    stopped = threading.Event()
    errors = []
    try:
        import uvicorn
        from backend.main import create_app

        preferred_port = args.port if args.port is not None else read_preferences(database).preferred_port
        port = available_port(preferred_port)
        url = f"http://localhost:{port}"
        app = create_app(database)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                             proxy_headers=False, access_log=False,
                                             timeout_graceful_shutdown=10, use_colors=False))
        def request_stop():
            server.should_exit = True

        app.state.local_service_stop = request_stop
        app.state.local_service_page_port = port
        app.state.local_service_desktop_window = desktop_mode
        assets_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        if desktop_mode:
            from desktop_window import DesktopWindow
            window = DesktopWindow(url, runtime_root() / "webview", assets_root / "assets" / "quickmemory.ico",
                                   request_stop, smoke_report=Path(args.window_smoke_test) if args.window_smoke_test else None)
        attach_instance_routes(app, lease, request_stop, window.activate if window else None)
        lease.publish(port)

        def open_page():
            if server.started:
                webbrowser.open(url)

        def open_settings():
            if server.started:
                webbrowser.open(url + "/settings#local-service")

        if not desktop_mode and not args.no_tray:
            from desktop_tray import TrayIcon
            tray = TrayIcon(assets_root / "assets" / "quickmemory.ico", open_page, request_stop,
                            on_settings=open_settings)

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
                if window:
                    window.service_stopped()

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

        if window:
            service_thread = threading.Thread(target=serve, name="quickmemory-service")
            service_thread.start()
            try:
                # Do not create a blank window before SQLite and HTTP startup succeed.
                for _ in range(300):
                    if stopped.wait(0.2):
                        break
                    if server.started:
                        window.run()  # pywebview requires the process main thread.
                        break
                else:
                    errors.append("启动超时，请检查数据目录与 logs/launcher.log。")
            finally:
                request_stop()
                service_thread.join()
        elif tray:
            threading.Thread(target=ready, daemon=True, name="quickmemory-ready").start()
            service_thread = threading.Thread(target=serve, name="quickmemory-service")
            service_thread.start()
            try:
                tray.run()
            finally:
                request_stop()
                service_thread.join()
        else:
            threading.Thread(target=ready, daemon=True, name="quickmemory-ready").start()
            serve()
        if errors:
            raise RuntimeError(errors[0])
        return 0
    finally:
        lease.__exit__(None, None, None)


def main():
    parser = argparse.ArgumentParser(description="轻记桌面启动器")
    parser.add_argument("--port", type=int, help="覆盖已保存的首选端口，仅本次启动生效")
    parser.add_argument("--browser", action="store_true", help="使用浏览器与托盘模式，默认打开独立桌面窗口")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="用于自动验收")
    parser.add_argument("--stop", action="store_true", help="关闭同数据目录的正在运行实例")
    parser.add_argument("--self-test", metavar="REPORT", help="执行离线打包自检并写入报告")
    parser.add_argument("--window-smoke-test", metavar="REPORT", help="用隔离数据目录验证真实桌面窗口后自动关闭")
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024 到 65535 之间")
    stream = None
    try:
        stream = configure_output(runtime_root())
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
