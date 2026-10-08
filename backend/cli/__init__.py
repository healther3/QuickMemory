"""本地命令行入口。"""

import sys

# Windows 重定向时也输出 UTF-8，避免中文反馈损坏。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")
