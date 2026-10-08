"""Windows WebView2 窗口；只展示本机界面，不向网页暴露 Python API。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

logger = logging.getLogger("quickmemory.desktop")

LOCALIZATION = {
    "global.quitConfirmation": "确定退出轻记吗？后台评分会暂停，下次启动时继续。",
    "global.ok": "确定", "global.quit": "退出", "global.cancel": "取消",
    "global.saveFile": "保存文件", "windows.fileFilter.allFiles": "所有文件",
    "windows.fileFilter.otherFiles": "其他文件类型",
}


def same_origin(target: str, origin: str) -> bool:
    """拒绝外部导航及 file/javascript URL；允许本机导出的 blob 下载。"""
    if target.startswith("blob:"):
        target = target[5:]
    try:
        parsed, expected = urlsplit(target), urlsplit(origin)
        return (parsed.scheme == expected.scheme == "http"
                and parsed.hostname == expected.hostname
                and parsed.port == expected.port
                and parsed.username is None and parsed.password is None)
    except (ValueError, AttributeError):
        return False


class DesktopWindow:
    def __init__(self, url: str, storage: Path, icon: Path, on_close, *, smoke_report: Path | None = None):
        if urlsplit(url).hostname not in ("localhost", "127.0.0.1") or urlsplit(url).scheme != "http":
            raise ValueError("桌面窗口只能加载本机轻记服务")
        self.url = url
        self.storage = storage
        self.icon = icon
        self.on_close = on_close
        self.smoke_report = smoke_report
        self.window = None
        self.renderer = None
        self.error = None
        self._closed = threading.Event()
        self._finished = threading.Event()
        self._shown = threading.Event()
        self._loaded = threading.Event()
        self._stopped = threading.Event()
        self._activate = threading.Event()
        self._allow_close = threading.Event()
        self._checking_close = threading.Lock()
        self._close_at = None
        self._native_handlers = []  # Retain .NET delegates for the window lifetime.

    def activate(self) -> bool:
        if self._closed.is_set() or self._stopped.is_set():
            return False
        self._activate.set()
        return True

    def service_stopped(self):
        self._stopped.set()

    def _on_closed(self):
        logger.info("桌面窗口：closed")
        self._closed.set()
        self.on_close()

    def _on_loaded(self):
        logger.info("桌面窗口：loaded")
        self._loaded.set()
        if self.smoke_report is not None:
            self._close_at = time.monotonic() + 1

    def _on_closing(self):
        if (self._allow_close.is_set() or self._stopped.is_set() or self.error is not None
                or self.smoke_report is not None or not self._loaded.is_set()):
            return True
        # closing is synchronous on the native UI thread. JS evaluation must run
        # elsewhere so WebView2 can finish its asynchronous ExecuteScript call.
        if self._checking_close.acquire(blocking=False):
            threading.Thread(target=self._confirm_close, name="quickmemory-close", daemon=True).start()
        return False

    def _confirm_close(self):
        done = threading.Event()
        result = []

        def read_dirty():
            try:
                result.append(self.window.evaluate_js("window.__quickMemoryHasUnsavedChanges === true"))
            except Exception:
                logging.exception("无法读取未保存编辑状态")
            finally:
                done.set()

        try:
            threading.Thread(target=read_dirty, name="quickmemory-close-state", daemon=True).start()
            known = done.wait(3) and len(result) == 1 and type(result[0]) is bool
            if self._closed.is_set():
                return
            can_close = known and result[0] is False
            if not can_close and not self._stopped.is_set():
                message = ("有尚未保存的修改。确定退出并放弃这些修改吗？" if known else
                           "暂时无法确认编辑状态。确定退出轻记吗？尚未保存的修改会丢失。")
                can_close = self.window.create_confirmation_dialog("轻记 · 退出确认", message)
            if (can_close or self._stopped.is_set()) and not self._closed.is_set():
                self._allow_close.set()
                self.window.destroy()
        finally:
            self._checking_close.release()

    def _initialized(self, renderer):
        logger.info("桌面窗口：renderer=%s", renderer)
        self.renderer = renderer
        if renderer != "edgechromium":
            self.error = "独立窗口需要 Microsoft Edge WebView2 Runtime。请安装该运行时，或使用 --browser 启动浏览器模式。"
            return False
        return True

    def _before_show(self):
        """在原生 UI 线程、首次导航之前绑定同源限制。"""
        try:
            logger.info("桌面窗口：before_show")
            view = self.window.native.webview

            def navigating(sender, args):
                if not same_origin(str(args.Uri), self.url):
                    args.Cancel = True

            def initialized(sender, args):
                logger.info("桌面窗口：WebView2 initialized=%s", args.IsSuccess)
                if not args.IsSuccess:
                    self.error = "WebView2 窗口初始化失败，请修复 Microsoft Edge WebView2 Runtime 后重试。"
                    return
                try:
                    # No host objects or custom JS API are needed by this application.
                    sender.CoreWebView2.Settings.AreHostObjectsAllowed = False
                    sender.CoreWebView2.Settings.IsPasswordAutosaveEnabled = False
                    sender.CoreWebView2.Settings.IsGeneralAutofillEnabled = False
                except Exception:
                    logging.exception("无法配置 WebView2 窗口")
                    self.error = "无法配置桌面窗口，请更新 Microsoft Edge WebView2 Runtime 后重试。"

            def navigated(sender, args):
                logger.info("桌面窗口：navigation completed=%s", args.IsSuccess)

            view.NavigationStarting += navigating
            view.CoreWebView2InitializationCompleted += initialized
            view.NavigationCompleted += navigated
            self._native_handlers.extend((navigating, initialized, navigated))
        except Exception:
            logging.exception("无法初始化桌面窗口导航限制")
            self.error = "无法初始化桌面窗口，请查看 logs/launcher.log。"

    def _watch(self):
        # webview.start invokes this in a worker, so GUI methods marshal to its UI thread.
        deadline = time.monotonic() + 60
        while not self._closed.wait(0.1):
            if self._finished.is_set():
                return
            if not self._loaded.is_set() and time.monotonic() > deadline:
                self.error = "桌面页面加载超时，请查看 logs/launcher.log。"
            closing = self._stopped.is_set() or self.error is not None
            closing = closing or (self._close_at is not None and time.monotonic() >= self._close_at)
            if self._shown.is_set() and closing:
                self.window.destroy()
                return
            if self._shown.is_set() and self._activate.is_set():
                self._activate.clear()
                self.window.restore()
                self.window.show()

    def run(self):
        if self._stopped.is_set():
            return
        try:
            logger.info("桌面窗口：import webview")
            import webview
        except ImportError:
            raise RuntimeError("桌面组件缺失，请重新下载安装包；源码运行请安装 requirements.txt。") from None

        self.storage.mkdir(parents=True, exist_ok=True)
        webview.settings.update({"ALLOW_DOWNLOADS": True, "ALLOW_FILE_URLS": False,
                                 "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
                                 "REMOTE_DEBUGGING_PORT": None})
        self.window = webview.create_window("轻记", self.url, width=1200, height=820,
            min_size=(740, 560), text_select=True, zoomable=True, background_color="#F6F5F0",
            js_api=None, localization=LOCALIZATION)
        self.window.events.initialized += self._initialized
        self.window.events.before_show += self._before_show
        self.window.events.shown += self._shown.set
        self.window.events.loaded += self._on_loaded
        self.window.events.closing += self._on_closing
        self.window.events.closed += self._on_closed
        try:
            logger.info("桌面窗口：start WebView2")
            webview.start(self._watch, gui="edgechromium", debug=False, private_mode=False,
                          storage_path=str(self.storage), localization=LOCALIZATION, icon=str(self.icon))
        finally:
            # pywebview's start callback is a non-daemon thread. Native startup
            # can fail before a closed event exists; still let that worker exit.
            self._finished.set()
            self.on_close()
        if self.error:
            raise RuntimeError(self.error)
        if self.smoke_report is not None:
            self._closed.wait(2)
            report = {"ok": self._shown.is_set() and self._loaded.is_set() and self._closed.is_set(),
                      "renderer": self.renderer, "shown": self._shown.is_set(),
                      "loaded": self._loaded.is_set(), "closed": self._closed.is_set()}
            self.smoke_report.parent.mkdir(parents=True, exist_ok=True)
            self.smoke_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            if not report["ok"]:
                raise RuntimeError("桌面窗口验收未完成")
