"""发行包进程验收：独立数据库，隔离 PATH，不依赖已安装 Python / Node。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.launcher import available_port, find_running, stop_running


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--source", action="store_true")
    args = parser.parse_args()
    executable = args.executable.resolve()
    base = [str(executable), str(ROOT / "desktop.py")] if args.source else [str(executable)]
    case = ROOT / ".qa" / ("source-launcher" if args.source else "frozen-launcher")
    case = case / ("tray" if args.tray else "background")
    case.mkdir(parents=True, exist_ok=True)
    database = case / "quickmemory.db"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["QUICKMEMORY_DB"] = str(database)
    if os.name == "nt":
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    port = available_port(8030)
    options = ["--no-browser", "--port", str(port)]
    if not args.tray:
        options.append("--no-tray")
    opener = build_opener(ProxyHandler({}))

    def start():
        return subprocess.Popen(base + options, cwd=case, env=env, creationflags=flags,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def ready(process):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"应用提前退出，code={process.returncode}，请检查 logs/launcher.log")
            state = find_running(database)
            if state:
                return state
            time.sleep(0.25)
        raise RuntimeError("应用启动超时")

    def api(state, path, value=None):
        request = Request(f"http://127.0.0.1:{state['port']}/api/{path}",
                          data=None if value is None else json.dumps(value).encode(),
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=5) as response:
            return json.load(response)

    process = None
    try:
        process = start()
        first = ready(process)
        assert api(first, "health")["status"] == "ok"
        assert api(first, "cards")["total"] == 10
        with opener.open(f"http://127.0.0.1:{first['port']}/settings") as response:
            assert b"<title>" in response.read()
        duplicate = start()
        assert duplicate.wait(timeout=120) == 0
        assert find_running(database)["pid"] == first["pid"]
        name = "打包持久化检查-" + str(time.time_ns())
        api(first, "tags", {"name": name})
        closing = subprocess.run(base + ["--stop"], cwd=case, env=env, creationflags=flags,
                                 timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert closing.returncode == 0
        assert process.wait(timeout=20) == 0
        assert find_running(database) is None
        process = start()
        second = ready(process)
        assert any(tag["name"] == name for tag in api(second, "tags"))
        assert stop_running(second)
        assert process.wait(timeout=20) == 0
        report = {"ok": True, "frozen": not args.source, "tray": args.tray,
                  "isolated_path": True, "static_page": True, "duplicate_reused": True,
                  "graceful_shutdown": True, "restart_persistence": True}
        (case / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        if process is not None and process.poll() is None:
            state = find_running(database)
            if state:
                stop_running(state)
                process.wait(timeout=20)
            else:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
