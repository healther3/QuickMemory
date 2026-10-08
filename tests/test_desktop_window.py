import json
import sys
import threading
from types import SimpleNamespace

import pytest

from desktop_window import DesktopWindow, same_origin


@pytest.mark.parametrize("target", [
    "http://localhost:8000/cards", "http://localhost:8000/settings#local-service",
    "blob:http://localhost:8000/12345",
])
def test_local_navigation_and_json_download_stay_in_app(target):
    assert same_origin(target, "http://localhost:8000")


@pytest.mark.parametrize("target", [
    "https://example.com", "http://localhost:8001", "http://localhost:8000.evil.test",
    "http://localhost:8000@example.com", "http://user@localhost:8000", "file:///secret.txt",
    "javascript:alert(1)", "data:text/html,hello", "blob:https://example.com/file",
    "http://127.0.0.1:8000", "http://localhost:invalid", "about:blank",
])
def test_foreign_navigation_cannot_enter_native_window(target):
    assert not same_origin(target, "http://localhost:8000")


class Event:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self

    def emit(self, *args):
        return all(callback(*args) is not False for callback in self.callbacks)


class FakeWindow:
    def __init__(self):
        self.events = SimpleNamespace(**{name: Event() for name in
            ("initialized", "before_show", "shown", "loaded", "closing", "closed")})
        self.native = SimpleNamespace(webview=SimpleNamespace(
            NavigationStarting=Event(), NavigationCompleted=Event(), CoreWebView2InitializationCompleted=Event(),
            CoreWebView2=SimpleNamespace(Settings=SimpleNamespace())))
        self.destroyed = 0
        self.restored = 0
        self.shown = 0
        self.dirty = False
        self.confirm = False
        self.confirmations = []

    def destroy(self):
        if not self.events.closing.emit():
            return
        self.destroyed += 1
        self.events.closed.emit()

    def restore(self):
        self.restored += 1

    def show(self):
        self.shown += 1
        self.destroy()

    def evaluate_js(self, script):
        assert script == "window.__quickMemoryHasUnsavedChanges === true"
        return self.dirty

    def create_confirmation_dialog(self, title, message):
        self.confirmations.append((title, message))
        return self.confirm


class FakeWebview:
    def __init__(self, after_loaded=None, renderer="edgechromium"):
        self.settings = {}
        self.window = FakeWindow()
        self.after_loaded = after_loaded
        self.renderer = renderer

    def create_window(self, *args, **kwargs):
        self.create_args = args, kwargs
        return self.window

    def start(self, function, **kwargs):
        self.start_args = kwargs
        if not self.window.events.initialized.emit(self.renderer):
            return
        self.window.events.before_show.emit()
        view = self.window.native.webview
        view.CoreWebView2InitializationCompleted.emit(view, SimpleNamespace(IsSuccess=True))
        self.window.events.shown.emit()
        self.window.events.loaded.emit()
        if self.after_loaded:
            self.after_loaded()
        function()


def test_backend_shutdown_closes_window_and_persistent_profile_is_configured(tmp_path, monkeypatch):
    callbacks = []
    controller = DesktopWindow("http://localhost:8000", tmp_path / "profile", tmp_path / "app.ico",
                               lambda: callbacks.append("stop"), smoke_report=tmp_path / "report.json")
    engine = FakeWebview(after_loaded=controller.service_stopped)
    monkeypatch.setitem(sys.modules, "webview", engine)
    controller.run()
    assert engine.window.destroyed == 1
    assert callbacks
    assert engine.create_args[1]["js_api"] is None
    assert engine.start_args["private_mode"] is False
    assert engine.start_args["storage_path"] == str(tmp_path / "profile")
    assert engine.start_args["gui"] == "edgechromium"
    assert engine.settings["ALLOW_DOWNLOADS"] is True
    assert engine.settings["ALLOW_FILE_URLS"] is False
    assert engine.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is False
    assert engine.window.native.webview.CoreWebView2.Settings.AreHostObjectsAllowed is False
    assert json.loads((tmp_path / "report.json").read_text()) == {
        "ok": True, "renderer": "edgechromium", "shown": True, "loaded": True, "closed": True}
    local = SimpleNamespace(Uri="http://localhost:8000/cards", Cancel=False)
    external = SimpleNamespace(Uri="https://example.com", Cancel=False)
    engine.window.native.webview.NavigationStarting.emit(None, local)
    engine.window.native.webview.NavigationStarting.emit(None, external)
    assert not local.Cancel
    assert external.Cancel


def test_duplicate_activation_waits_until_window_is_shown(tmp_path, monkeypatch):
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico", lambda: None)
    engine = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", engine)
    assert controller.activate()  # Arrives before webview creates the native window.
    controller.run()
    assert engine.window.restored == engine.window.shown == 1
    assert not controller.activate()


def test_unsupported_renderer_stops_service_without_opening_legacy_ie(tmp_path, monkeypatch):
    stopped = []
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico",
                               lambda: stopped.append(True))
    engine = FakeWebview(renderer="mshtml")
    monkeypatch.setitem(sys.modules, "webview", engine)
    with pytest.raises(RuntimeError, match="WebView2 Runtime"):
        controller.run()
    assert stopped
    assert not controller._shown.is_set()


@pytest.mark.parametrize("dirty,confirm,destroyed", [(False, False, 1), (True, False, 0), (True, True, 1)])
def test_normal_close_respects_unsaved_changes(tmp_path, dirty, confirm, destroyed):
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico", lambda: None)
    window = FakeWindow()
    controller.window = window
    window.dirty, window.confirm = dirty, confirm
    controller._checking_close.acquire()
    controller._confirm_close()
    assert window.destroyed == destroyed
    assert bool(window.confirmations) is dirty
    assert not controller._checking_close.locked()


def test_service_stop_does_not_repeat_the_web_pages_confirmation(tmp_path):
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico", lambda: None)
    controller._loaded.set()
    controller.service_stopped()
    assert controller._on_closing() is True


def test_closing_never_evaluates_javascript_on_gui_thread(tmp_path, monkeypatch):
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico", lambda: None)
    controller._loaded.set()
    queued = []

    class DeferredThread:
        def __init__(self, target, **kwargs):
            queued.append(target)

        def start(self):
            pass

    monkeypatch.setattr(threading, "Thread", DeferredThread)
    assert controller._on_closing() is False
    assert controller._on_closing() is False  # Double-click X starts only one check.
    assert queued == [controller._confirm_close]


def test_unreadable_dirty_state_requires_confirmation_instead_of_losing_edits(tmp_path):
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico", lambda: None)
    window = FakeWindow()
    controller.window = window
    window.evaluate_js = lambda script: None
    controller._checking_close.acquire()
    controller._confirm_close()
    assert window.destroyed == 0
    assert "无法确认编辑状态" in window.confirmations[0][1]
    assert not controller._checking_close.locked()


def test_gui_start_failure_does_not_leave_non_daemon_watch_thread(tmp_path, monkeypatch):
    stopped = []
    controller = DesktopWindow("http://localhost:8000", tmp_path, tmp_path / "app.ico",
                               lambda: stopped.append(True))

    class FailedWebview(FakeWebview):
        def start(self, function, **kwargs):
            self.watcher = threading.Thread(target=function)
            self.watcher.start()
            raise RuntimeError("simulated native startup failure")

    engine = FailedWebview()
    monkeypatch.setitem(sys.modules, "webview", engine)
    try:
        with pytest.raises(RuntimeError, match="simulated native startup failure"):
            controller.run()
        engine.watcher.join(timeout=1)
        assert not engine.watcher.is_alive()
        assert stopped == [True]
        assert not controller._closed.is_set()  # A failed startup is not a verified window close.
    finally:
        controller._closed.set()
        engine.watcher.join(timeout=1)


@pytest.mark.parametrize("window_error", [False, True])
def test_native_launcher_stops_server_and_releases_database_on_window_exit(tmp_path, monkeypatch, window_error):
    import desktop
    import desktop_window
    import uvicorn
    from backend.launcher import InstanceLease

    database = tmp_path / "isolated.db"
    monkeypatch.setenv("QUICKMEMORY_DB", str(database))
    instances = []

    class Server:
        def __init__(self, config):
            self.config = config
            self.started = self.should_exit = False
            instances.append(self)

        def run(self):
            self.started = True
            while not self.should_exit:
                threading.Event().wait(0.01)

    class Window:
        def __init__(self, url, storage, icon, on_close, **kwargs):
            self.on_close = on_close

        def activate(self):
            return True

        def service_stopped(self):
            pass

        def run(self):
            assert threading.current_thread() is threading.main_thread()
            if window_error:
                raise RuntimeError("simulated window failure")
            self.on_close()

    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(desktop_window, "DesktopWindow", Window)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda *_: pytest.fail("原生模式不应打开浏览器"))
    args = SimpleNamespace(stop=False, browser=False, no_browser=False, no_tray=True,
                           port=8900, window_smoke_test=None)
    if window_error:
        with pytest.raises(RuntimeError, match="simulated window failure"):
            desktop.run_application(args)
    else:
        assert desktop.run_application(args) == 0
    assert instances[0].should_exit
    assert instances[0].config.app.state.local_service_desktop_window is True
    with InstanceLease(database):
        pass
    assert not any(thread.name == "quickmemory-service" for thread in threading.enumerate())
