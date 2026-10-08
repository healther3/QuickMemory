"""python run.py：本地服务、静态前端和浏览器；--dev 同时启动 Vite。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from urllib.request import urlopen
import webbrowser

from backend.launcher import (AlreadyRunning, InstanceLease, attach_instance_routes,
                              available_port, find_running)

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def ensure_environment():
    local_python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if local_python.is_file() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        raise SystemExit(subprocess.call([str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]]))
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        raise SystemExit("缺少后端依赖。请先执行：python -m pip install -r requirements.txt")


@contextmanager
def instance_lock():
    with InstanceLease():
        yield


def build_frontend(force: bool):
    if (FRONTEND / "dist" / "index.html").is_file() and not force:
        return
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not (FRONTEND / "node_modules").is_dir():
        raise RuntimeError("前端尚未构建。请安装 Node.js，然后在 frontend 目录执行 npm install 和 npm run build")
    print("正在构建本地界面……", flush=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def open_when_ready(port: int, page_port: int, stop: threading.Event):
    for _ in range(150):
        if stop.wait(0.2):
            return
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
                if json.load(response).get("status") != "ok":
                    continue
            if page_port != port:
                with urlopen(f"http://127.0.0.1:{page_port}", timeout=0.5):
                    pass
            webbrowser.open(f"http://localhost:{page_port}")
            return
        except (OSError, ValueError):
            continue


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="启动轻记本地概念默写应用")
    parser.add_argument("--port", type=int, help="覆盖已保存的首选端口，仅本次启动生效")
    parser.add_argument("--dev", action="store_true", help="启动 Vite 开发服务和后端")
    parser.add_argument("--build", action="store_true", help="启动前重新构建前端")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024 到 65535 之间")
    ensure_environment()
    from backend.local_service import read_preferences

    os.chdir(ROOT)
    try:
        lease = InstanceLease()
        lease.__enter__()
    except AlreadyRunning:
        state = find_running(wait_seconds=5)
        if state:
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{state['page_port']}")
            print(f"轻记已经运行：http://localhost:{state['page_port']}")
            return
        raise RuntimeError("轻记已经运行，请先关闭旧版启动窗口或回到原页面") from None
    try:
        preferred_port = args.port if args.port is not None else read_preferences(lease.database).preferred_port
        port = available_port(preferred_port)
        page_port = port
        dev_process = None
        stop = threading.Event()
        try:
            if args.dev:
                npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
                if not npm or not (FRONTEND / "node_modules").is_dir():
                    raise RuntimeError("缺少前端依赖，请先在 frontend 目录执行 npm install")
                page_port = available_port(5173, exclude=(port,))
                os.environ["QUICKMEMORY_VITE_PORT"] = str(page_port)
                child_env = {**os.environ, "QUICKMEMORY_API_PORT": str(port)}
                # 直接启动 Node，不经 npm shell，退出时不会遗留 npm 的子进程。
                node = shutil.which("node")
                if not node:
                    raise RuntimeError("未找到 Node.js")
                dev_process = subprocess.Popen([node, str(FRONTEND / "node_modules/vite/bin/vite.js"),
                    "--host", "127.0.0.1", "--port", str(page_port), "--strictPort"],
                    cwd=FRONTEND, env=child_env)
            else:
                build_frontend(args.build)
            print(f"轻记已启动：http://localhost:{page_port}  （按 Ctrl+C 关闭）", flush=True)
            if not args.no_browser:
                threading.Thread(target=open_when_ready, args=(port, page_port, stop), daemon=True).start()
            import uvicorn
            from backend.main import create_app
            app = create_app(lease.database)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                                   proxy_headers=False, access_log=False))
            request_stop = lambda: setattr(server, "should_exit", True)
            app.state.local_service_stop = request_stop
            app.state.local_service_page_port = page_port
            attach_instance_routes(app, lease, request_stop)
            lease.publish(port, page_port)
            server.run()
        finally:
            stop.set()
            if dev_process is not None:
                dev_process.terminate()
                try:
                    dev_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    dev_process.kill()
                    dev_process.wait()
    finally:
        lease.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
