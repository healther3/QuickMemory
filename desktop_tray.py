"""轻记的 Windows 通知区域入口，不依赖第三方 GUI 框架。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable
import uuid


if os.name == "nt":
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    class IconVersion(ctypes.Union):
        _fields_ = [("uTimeout", wintypes.UINT), ("uVersion", wintypes.UINT)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _anonymous_ = ("version",)
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
            ("version", IconVersion), ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("wParam", WPARAM), ("lParam", LPARAM),
                    ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                    ("lPrivate", wintypes.DWORD)]


WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_CONTEXTMENU = 0x007B
WM_TIMER = 0x0113
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401
WM_TRAY = 0x8001
WM_TITLE = 0x8002
WM_STOP = 0x8003
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 1, 2, 4, 0x80
OPEN_COMMAND, QUIT_COMMAND = 1001, 1002


class TrayIcon:
    """Run on the main thread; ``stop`` and ``set_title`` may run on any thread.

    Callbacks run on the message-loop thread and should return promptly. ``stop``
    removes the tray without calling ``on_quit``; the menu calls ``on_quit`` once.
    """

    def __init__(self, icon_path: Path, on_open: Callable[[], None], on_quit: Callable[[], None]):
        if os.name != "nt":
            raise RuntimeError("系统托盘入口仅支持 Windows")
        self.icon_path = Path(icon_path).resolve()
        self.on_open, self.on_quit = on_open, on_quit
        self._title = "轻记 · 正在启动"
        self._title_lock = threading.Lock()
        self._stopped = threading.Event()
        self._hwnd = None
        self._hicon = None
        self._registered = False
        self._added = False
        self._quitting = False
        self._used = False
        self._error: BaseException | None = None
        self._class_name = "QuickMemoryTray_" + uuid.uuid4().hex
        self._recovery_attempts = 0
        self._last_activation = float("-inf")
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._shell = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._declare_apis()
        # Keep both the callback and class structure alive until UnregisterClass.
        self._callback = WNDPROC(self._window_proc)
        self._window_class = WNDCLASSW()
        self._instance = self._kernel.GetModuleHandleW(None)
        self._taskbar_created = self._user.RegisterWindowMessageW("TaskbarCreated")
        if not self._instance or not self._taskbar_created:
            self._fail("无法初始化 Windows 托盘消息")

    def _declare_apis(self):
        def signature(dll, name, args, result):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result

        U, K, S = self._user, self._kernel, self._shell
        P = ctypes.POINTER
        signature(K, "GetModuleHandleW", [wintypes.LPCWSTR], wintypes.HMODULE)
        signature(U, "RegisterWindowMessageW", [wintypes.LPCWSTR], wintypes.UINT)
        signature(U, "GetDoubleClickTime", [], wintypes.UINT)
        signature(U, "RegisterClassW", [P(WNDCLASSW)], wintypes.ATOM)
        signature(U, "UnregisterClassW", [wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL)
        signature(U, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                  wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID], wintypes.HWND)
        signature(U, "DefWindowProcW", [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM], LRESULT)
        signature(U, "DestroyWindow", [wintypes.HWND], wintypes.BOOL)
        signature(U, "IsWindow", [wintypes.HWND], wintypes.BOOL)
        signature(U, "LoadImageW", [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                  ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.HANDLE)
        signature(U, "DestroyIcon", [wintypes.HICON], wintypes.BOOL)
        signature(U, "GetMessageW", [P(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int)
        signature(U, "TranslateMessage", [P(MSG)], wintypes.BOOL)
        signature(U, "DispatchMessageW", [P(MSG)], LRESULT)
        signature(U, "PostMessageW", [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM], wintypes.BOOL)
        signature(U, "PostQuitMessage", [ctypes.c_int], None)
        signature(U, "CreatePopupMenu", [], wintypes.HMENU)
        signature(U, "AppendMenuW", [wintypes.HMENU, wintypes.UINT, WPARAM, wintypes.LPCWSTR], wintypes.BOOL)
        signature(U, "SetMenuDefaultItem", [wintypes.HMENU, wintypes.UINT, wintypes.UINT], wintypes.BOOL)
        signature(U, "DestroyMenu", [wintypes.HMENU], wintypes.BOOL)
        signature(U, "GetCursorPos", [P(wintypes.POINT)], wintypes.BOOL)
        signature(U, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL)
        signature(U, "TrackPopupMenu", [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                  ctypes.c_int, ctypes.c_int, wintypes.HWND, P(wintypes.RECT)], wintypes.UINT)
        signature(U, "SetTimer", [wintypes.HWND, WPARAM, wintypes.UINT, wintypes.LPVOID], WPARAM)
        signature(U, "KillTimer", [wintypes.HWND, WPARAM], wintypes.BOOL)
        signature(S, "Shell_NotifyIconW", [wintypes.DWORD, P(NOTIFYICONDATAW)], wintypes.BOOL)

    @staticmethod
    def _fail(message: str):
        code = ctypes.get_last_error()
        raise RuntimeError(f"{message}（Windows 错误 {code}）" if code else message)

    def _icon_data(self):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd, data.uID = self._hwnd, 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        data.uCallbackMessage, data.hIcon = WM_TRAY, self._hicon
        with self._title_lock:
            data.szTip = self._title
        return data

    def _add_icon(self) -> bool:
        data = self._icon_data()
        if not self._shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            return False
        self._added = True
        data.uVersion = 4
        # Legacy event IDs are still handled if a shell does not accept v4.
        self._shell.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(data))
        return True

    def _recover_icon(self):
        if self._add_icon():
            self._recovery_attempts = 0
            self._user.KillTimer(self._hwnd, 1)
            return
        self._recovery_attempts += 1
        if self._recovery_attempts > 20:
            raise RuntimeError("Windows 系统托盘恢复失败，请重新打开轻记")
        if not self._user.SetTimer(self._hwnd, 1, 1000, None):
            self._fail("无法等待 Windows 系统托盘恢复")

    def _remove_icon(self):
        if self._added:
            data = self._icon_data()
            self._shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            self._added = False

    def _show_menu(self):
        menu = self._user.CreatePopupMenu()
        if not menu:
            self._fail("无法创建轻记托盘菜单")
        try:
            for flags, item, label in [(0, OPEN_COMMAND, "打开轻记"),
                                       (0x0800, 0, None), (0, QUIT_COMMAND, "退出轻记")]:
                if not self._user.AppendMenuW(menu, flags, item, label):
                    self._fail("无法创建轻记托盘菜单")
            self._user.SetMenuDefaultItem(menu, OPEN_COMMAND, False)
            point = wintypes.POINT()
            if not self._user.GetCursorPos(ctypes.byref(point)):
                self._fail("无法读取鼠标位置")
            self._user.SetForegroundWindow(self._hwnd)
            choice = self._user.TrackPopupMenu(menu, 0x0100 | 0x0080 | 0x0002,
                                              point.x, point.y, 0, self._hwnd, None)
            # Microsoft requires the benign message so successive menus dismiss.
            self._user.PostMessageW(self._hwnd, 0, 0, 0)
        finally:
            self._user.DestroyMenu(menu)
        if choice == OPEN_COMMAND:
            self.on_open()
        elif choice == QUIT_COMMAND:
            self._request_quit()
        else:
            # Restore keyboard focus when the user cancels the shortcut menu.
            data = self._icon_data()
            self._shell.Shell_NotifyIconW(3, ctypes.byref(data))

    def _request_quit(self):
        if not self._quitting:
            self._quitting = True
            try:
                self.on_quit()
            finally:
                self.stop()

    def _window_proc(self, hwnd, message, wparam, lparam):
        # Exceptions must not escape a ctypes callback into Windows.
        try:
            if message == self._taskbar_created:
                self._added = False
                self._recover_icon()
                return 0
            if message == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (NIN_SELECT, NIN_KEYSELECT, WM_LBUTTONDBLCLK):
                    # Version 4 can report selection instead of a mouse event.
                    # Coalesce its selection/double-click sequence to one page.
                    now = time.monotonic()
                    if now - self._last_activation >= self._user.GetDoubleClickTime() / 1000:
                        self._last_activation = now
                        self.on_open()
                elif event in (WM_CONTEXTMENU, WM_RBUTTONUP):
                    self._show_menu()
                return 0
            if message == WM_TITLE:
                if self._added:
                    data = self._icon_data()
                    data.uFlags = NIF_TIP | NIF_SHOWTIP
                    self._shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
                return 0
            if message == WM_TIMER and wparam == 1:
                self._recover_icon()
                return 0
            if message == WM_CLOSE:
                self._request_quit()
                return 0
            if message == WM_STOP:
                self._remove_icon()
                self._user.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                self._user.PostQuitMessage(0)
                return 0
            return self._user.DefWindowProcW(hwnd, message, wparam, lparam)
        except BaseException as exc:
            logging.exception("系统托盘消息处理失败")
            self._error = exc
            self.stop()
            return 0

    def set_title(self, title: str):
        # Windows counts UTF-16 code units, so slicing Python characters alone
        # could overflow the tooltip buffer for characters outside the BMP.
        tooltip = str(title).replace("\0", "").encode("utf-16-le")[:254].decode("utf-16-le", errors="ignore")
        with self._title_lock:
            self._title = tooltip
        if self._hwnd:
            self._user.PostMessageW(self._hwnd, WM_TITLE, 0, 0)

    def stop(self):
        self._stopped.set()
        if self._hwnd:
            self._user.PostMessageW(self._hwnd, WM_STOP, 0, 0)

    def run(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("轻记托盘必须在主线程运行")
        if self._used:
            raise RuntimeError("轻记托盘不能重复运行")
        self._used = True
        if self._stopped.is_set():
            return
        if not self.icon_path.is_file():
            raise RuntimeError("缺少轻记托盘图标，请重新打包应用")
        try:
            self._hicon = self._user.LoadImageW(None, str(self.icon_path), 1, 0, 0, 0x0010 | 0x0040)
            if not self._hicon:
                self._fail("无法加载轻记托盘图标")
            window_class = self._window_class
            window_class.lpfnWndProc = self._callback
            window_class.hInstance, window_class.hIcon = self._instance, self._hicon
            window_class.lpszClassName = self._class_name
            if not self._user.RegisterClassW(ctypes.byref(window_class)):
                self._fail("无法注册轻记托盘窗口")
            self._registered = True
            # Invisible top-level window receives TaskbarCreated broadcasts;
            # a message-only window would miss Explorer restarts.
            self._hwnd = self._user.CreateWindowExW(0, self._class_name, "轻记", 0,
                0, 0, 0, 0, None, None, self._instance, None)
            if not self._hwnd:
                self._fail("无法创建轻记托盘窗口")
            if not self._add_icon():
                self._fail("无法显示轻记系统托盘图标")
            if self._stopped.is_set():
                self.stop()
            message = MSG()
            while True:
                result = self._user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    self._fail("轻记托盘消息循环失败")
                if result == 0:
                    break
                self._user.TranslateMessage(ctypes.byref(message))
                self._user.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hwnd:
                self._user.KillTimer(self._hwnd, 1)
                self._remove_icon()
                if self._user.IsWindow(self._hwnd):
                    self._user.DestroyWindow(self._hwnd)
                self._hwnd = None
                self._added = False
            if self._registered:
                self._user.UnregisterClassW(self._class_name, self._instance)
                self._registered = False
            if self._hicon:
                self._user.DestroyIcon(self._hicon)
                self._hicon = None
        if self._error is not None:
            raise RuntimeError("轻记系统托盘发生错误，请查看启动日志") from self._error
