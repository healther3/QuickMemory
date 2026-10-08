"""Build the self-contained Windows release, without copying any user data.

Run: .venv\\Scripts\\python.exe scripts\\build_windows.py
Use --skip-frontend only when frontend/dist already contains the desired build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]


def _inside_polygon(x, y, points):
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2-x1) * (y-y1) / (y2-y1) + x1:
            inside = not inside
        previous = current
    return inside


def write_icon(path: Path):
    """Draw a local vector-style book icon, with no build-time imaging package."""
    def color(x, y):
        distance = max(abs(x-0.5)-0.30, 0)**2 + max(abs(y-0.5)-0.30, 0)**2
        if distance > 0.17**2:
            return (0, 0, 0, 0)
        result = (8, 107, 88, 255)
        if _inside_polygon(x, y, [(0.20,0.26),(0.44,0.29),(0.49,0.34),(0.49,0.77),(0.40,0.72),(0.20,0.69)]):
            result = (249, 248, 239, 255)
        if _inside_polygon(x, y, [(0.51,0.34),(0.56,0.29),(0.80,0.26),(0.80,0.69),(0.60,0.72),(0.51,0.77)]):
            result = (230, 240, 221, 255)
        if 0.27 < x < 0.43 and any(abs(y - line - (x-0.27)*0.17) < 0.012 for line in (0.40,0.49,0.58)):
            result = (114, 151, 133, 255)
        if _inside_polygon(x, y, [(0.65,0.279),(0.73,0.269),(0.73,0.47),(0.69,0.43),(0.65,0.47)]):
            result = (225, 177, 75, 255)
        return result

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)

    images = []
    for size in (16, 32, 48, 64, 128, 256):
        rows = bytearray()
        for row in range(size):
            rows.append(0)
            for column in range(size):
                samples = [color((column+(sx+0.5)/3)/size, (row+(sy+0.5)/3)/size)
                           for sy in range(3) for sx in range(3)]
                alpha = sum(sample[3] for sample in samples)
                rows.extend([round(sum(sample[c]*sample[3] for sample in samples)/alpha) if alpha else 0
                             for c in range(3)] + [round(alpha/9)])
        data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size,size,8,6,0,0,0))
        data += chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")
        images.append((size, data))
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    payload = b""
    for size, data in images:
        header += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + payload)


def main():
    parser = argparse.ArgumentParser(description="生成轻记 Windows 一键启动 exe")
    parser.add_argument("--skip-frontend", action="store_true", help="使用已有前端生产构建")
    parser.add_argument("--no-copy", action="store_true", help="仅输出 dist/QuickMemory.exe")
    parser.add_argument("--incremental", action="store_true", help="复用已有打包缓存，仅用于依赖未变更的重建")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows exe 必须在 Windows 上构建")
    if importlib.util.find_spec("PyInstaller") is None:
        parser.error("请先运行 .venv\\Scripts\\python.exe -m pip install -r requirements-build.txt")
    if not args.skip_frontend:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            parser.error("重建前端需要 Node.js；已有生产构建可添加 --skip-frontend")
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    for file in ("desktop.py", "desktop_tray.py", "backend/frozen_check.py", "frontend/dist/index.html", "examples/ml_terms.json"):
        if not (ROOT / file).is_file():
            parser.error(f"缺少构建文件：{file}")
    icon = ROOT / "assets" / "quickmemory.ico"
    write_icon(icon)
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    log_path = build_dir / "windows-build.log"
    print(f"正在构建独立 exe；完整日志：{log_path}", flush=True)
    env = dict(os.environ, LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_TELEMETRY="False",
               LITELLM_MODE="PRODUCTION", DO_NOT_TRACK="1", PYTHONUTF8="1")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if not args.incremental:
        command.append("--clean")
    command += ["--distpath", str(ROOT / "dist"), "--workpath", str(build_dir),
                str(ROOT / "QuickMemory.spec")]
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print("构建失败，末尾日志：", file=sys.stderr)
        print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-45:]), file=sys.stderr)
        return result.returncode
    artifact = ROOT / "dist" / "QuickMemory.exe"
    report_path = build_dir / "windows-self-test.json"
    report_path.write_text("{}", encoding="utf-8")
    print("正在验证 exe 内的资源、数据库和本机模拟评分……", flush=True)
    try:
        checked = subprocess.run([str(artifact), "--self-test", str(report_path)],
                                 cwd=ROOT, timeout=90, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if checked.returncode or report.get("ok") is not True or report.get("checks", {}).get("frozen") is not True:
            raise RuntimeError(report.get("error", "发行包离线自检未通过"))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"exe 自检失败，未替换项目根目录版本：{exc}\n报告：{report_path}", file=sys.stderr)
        return 1
    if not args.no_copy:
        destination = ROOT / "轻记.exe"
        try:
            shutil.copy2(artifact, destination)
        except PermissionError:
            print(f"exe 已构建：{artifact}\n请退出当前轻记，再复制到 {destination}。", file=sys.stderr)
            return 1
    else:
        destination = artifact
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (ROOT / "dist" / "release.json").write_text(json.dumps({
        "artifact": artifact.name, "bytes": artifact.stat().st_size, "sha256": digest,
        "python": sys.version, "mode": "onefile-windowed", "user_data_included": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{destination}\n体积：{artifact.stat().st_size / 1024 / 1024:.1f} MiB\nSHA256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
