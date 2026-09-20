"""CmdGauge - Command Code 用量统计面板 (Python 单文件 exe + WebView).

入口: 启动本地 HTTP 服务 → 创建 WebView 窗口 → 未登录时加载官网登录页,
登录成功后自动进入面板 (首次自动全量同步, 之后读本地数据库).
系统托盘: 关闭窗口最小化到托盘, 托盘菜单可显示窗口/退出。

移植自 GoGauge (opencode-go-gauge): 窗口/托盘/单实例/拖动等 Win32 逻辑原样保留,
仅把登录目标与回调契约换成 Command Code。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import tempfile
import threading
import time

import webview

from . import db, server
from .auth import LoginWatcher, build_login_url

APP_TITLE = "CmdGauge - Command Code Usage Panel"
WINDOW_SIZE = (1280, 840)
WINDOW_MIN_SIZE = (1000, 680)
ICON_NAME = "CmdGauge.ico"


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _screen_workarea_logical() -> tuple[int, int]:
    """主屏工作区尺寸(逻辑像素): 窗口初始尺寸不超工作区, 避免矮屏上底部被裁."""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem() or 96
        scale = dpi / 96.0
        rect = _RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return int(rect.right / scale), int(rect.bottom / scale)
    except Exception:  # noqa: BLE001
        pass
    return WINDOW_SIZE

_quitting = False  # 托盘"退出"标志: 为 True 时关闭窗口=真正退出
_tray_ready = False  # 托盘是否成功启动 (失败时关闭窗口=直接退出, 避免无法关闭)
_move_lock = threading.Lock()  # 拖动 move_by 串行化: 防 js_api 并发读-写丢增量


def _enable_taskbar_minimize(win) -> None:
    """无边框窗口修复: 补上 WS_MINIMIZEBOX 样式, 让任务栏点击可最小化/恢复.

    pywebview frameless -> WinForms FormBorderStyle.None, 该样式不包含
    WS_MINIMIZEBOX (初始样式仅含 WS_MAXIMIZEBOX), 系统会忽略任务栏按钮的
    最小化请求 (点击无反应). 给窗口句柄补上该样式, 恢复标准任务栏行为.
    """
    try:
        hwnd = int(win.native.Handle.ToInt32())
        GWL_STYLE = -16
        WS_MINIMIZEBOX = 0x00020000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style and not (style & WS_MINIMIZEBOX):
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX)
    except Exception:  # noqa: BLE001
        pass

_MAIN_LOG = os.path.join(tempfile.gettempdir(), "cmdgauge_main.log")


def _mlog(msg: str) -> None:
    """主流程日志 (exe 无控制台, 落盘便于排查)."""
    try:
        with open(_MAIN_LOG, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def _asset_path(rel: str) -> str:
    """定位资源文件 (开发/打包后通用)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "assets", rel)
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", rel)


# ── 单实例检测常量 (Win32) ──
_LOCK_FILE_NAME = "CmdGauge.lock"
_MUTEX_NAME = "CmdGauge_SingleInstance_Mutex"
_ERROR_ALREADY_EXISTS = 183  # GetLastError: 命名对象已存在
_ACTIVATE_RETRY_INTERVAL = 0.5  # 激活旧实例窗口的重试间隔(秒)
_ACTIVATE_RETRY_TIMES = 30  # 重试次数 (共约15秒, 覆盖旧实例 onefile 解压+启动耗时)
_SW_SHOW = 5
_SW_RESTORE = 9
_MB_ICONINFORMATION = 0x40
_VK_MENU = 0x12  # ALT 虚拟键码
_KEYEVENTF_KEYUP = 0x0002

_mutex_handle = None  # 首实例持有的互斥体句柄 (全局引用防回收, 进程退出由内核自动释放)


def _is_process_running(pid: int) -> bool:
    """检查指定 PID 的进程是否存活."""
    # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION, 权限要求最低
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def _get_process_image_name(pid: int) -> str:
    """获取进程可执行文件完整路径, 用于确认锁文件 PID 是否仍属于本程序."""
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _is_cmdgauge_process(pid: int) -> bool:
    """确认指定 PID 的进程确为本程序 (打包 CmdGauge.exe, 开发 python.exe).

    进程崩溃后锁文件残留, 其 PID 可能被系统其他进程复用. 仅凭"进程存活"会误判为
    旧实例仍在运行, 进而拦截新实例导致无法启动. 必须同时校验进程可执行文件名.
    """
    name = os.path.basename(_get_process_image_name(pid)).lower()
    if getattr(sys, "frozen", False):
        return "cmdgauge" in name
    return name.startswith("python")


def _activate_existing_instance(old_pid: int) -> bool:
    """激活已运行实例的主窗口 (含被隐藏到托盘的情况)."""
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, str]] = []  # (窗口句柄, 窗口标题)

    # 回调签名必须用 HWND/LPARAM (64位系统下指针宽度), 用 c_int 会截断且吞异常
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _on_window(hwnd, _lparam):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if old_pid == 0 or pid.value == old_pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:  # 过滤 WinForms 无标题的消息窗口
                candidates.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_on_window, 0)
    # 优先主窗口: 标题含 CmdGauge 且非登录窗; 找不到再退回任一候选
    hwnd = next((h for h, t in candidates if "CmdGauge" in t and "Login" not in t), 0)
    if not hwnd:
        hwnd = next((h for h, t in candidates if "CmdGauge" in t), 0)
    if not hwnd:
        return False
    # 隐藏窗口用 SW_SHOW 唤起, 最小化窗口用 SW_RESTORE 还原
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, _SW_SHOW)
    # 后台进程直接 SetForegroundWindow 会被系统前台锁拒绝, 先模拟一次 ALT 击键绕过
    user32.keybd_event(_VK_MENU, 0, 0, 0)
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    return True


def _read_valid_lock_pid() -> int:
    """读取锁文件中的首实例 PID 并校验有效性 (0 = 无效/不存在)."""
    try:
        lock_path = os.path.join(tempfile.gettempdir(), _LOCK_FILE_NAME)
        if os.path.isfile(lock_path):
            with open(lock_path, "r") as fh:
                pid = int(fh.read().strip())
            if _is_process_running(pid) and _is_cmdgauge_process(pid):
                return pid
    except (ValueError, OSError):
        pass
    return 0


def _activate_with_retry() -> bool:
    """带重试激活旧实例窗口 (覆盖首实例 onefile 解压/初始化的窗口创建延迟)."""
    for _ in range(_ACTIVATE_RETRY_TIMES):
        if _activate_existing_instance(_read_valid_lock_pid()):
            return True
        time.sleep(_ACTIVATE_RETRY_INTERVAL)
    return False


def _ensure_single_instance() -> None:
    """单实例守卫: 命名互斥体原子判定, 已有实例时激活其窗口并结束当前进程.

    主判定用内核命名互斥体 (CreateMutexW): 创建是否冲突由内核原子保证,
    无锁文件方案的竞态窗口; 进程崩溃时内核自动回收互斥体, 无残留无 PID 复用问题.
    锁文件降级为辅助: 记录首实例 PID 供激活窗口定位; 失效时按标题全局枚举兜底.
    """
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        if handle:
            kernel32.CloseHandle(handle)
        if not _activate_with_retry():
            ctypes.windll.user32.MessageBoxW(
                0, "CmdGauge 已在运行, 请从系统托盘打开窗口。", "CmdGauge", _MB_ICONINFORMATION
            )
        sys.exit(0)
    _mutex_handle = handle
    try:
        with open(os.path.join(tempfile.gettempdir(), _LOCK_FILE_NAME), "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        _mlog("[single-instance] 写锁文件失败")


class TrayIcon:
    """系统托盘 (pystray): logo 图标 + 显示窗口/退出 菜单."""

    def __init__(self, icon_path: str) -> None:
        self._icon_path = icon_path
        self._icon = None
        self._win_getter = None

    def bind_window(self, getter) -> None:
        self._win_getter = getter

    def start(self) -> bool:
        global _tray_ready
        try:
            from PIL import Image
            import pystray

            if not os.path.isfile(self._icon_path):
                # 原实现这里静默 return False, 而 _tray_ready 初值就是 False,
                # 结果表现为「点 × 直接退出进程」且日志里毫无线索。必须留痕。
                _mlog(f"[tray] 图标文件不存在, 托盘不可用: {self._icon_path}")
                _tray_ready = False
                return False
            img = Image.open(self._icon_path).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            )
            self._icon = pystray.Icon("CmdGauge", img, "CmdGauge - Command Code 用量面板", menu)
            threading.Thread(target=self._icon.run, daemon=True).start()
            # 只在线程真的把图标画出来之后才算就绪: `icon.run` 是异步的, 原来
            # 启动后立刻置 True, 若图标实际没显示出来, 窗口 hide() 之后就再没有
            # 入口能把它叫回来, 用户只能去任务管理器杀进程。
            _tray_ready = self._wait_visible()
            if not _tray_ready:
                _mlog("[tray] 托盘图标未在超时内可见, 关闭窗口将直接退出")
            return _tray_ready
        except Exception as exc:  # noqa: BLE001
            _mlog(f"[tray] 托盘启动失败: {exc}")
            _tray_ready = False
            return False

    def _wait_visible(self, timeout: float = 3.0) -> bool:
        """轮询 pystray 的 ``visible`` 属性, 确认托盘图标真的显示出来了.

        实测图标在 0.25s 内即可见, 所以正常路径几乎不产生额外启动延迟。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if getattr(self._icon, "visible", False):
                return True
            time.sleep(0.1)
        return bool(getattr(self._icon, "visible", False))

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def _show(self, icon=None, item=None) -> None:
        if self._win_getter:
            win = self._win_getter()
            if win:
                win.show()
                win.restore()

    def _quit(self, icon=None, item=None) -> None:
        global _quitting
        _quitting = True
        if icon:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
        _destroy_all_windows()


def _compute_resized_rect(
    left: int, top: int, right: int, bottom: int, edge: str, dx: int, dy: int
) -> tuple[int, int, int, int]:
    """按拖拽方向计算新的窗口矩形 (纯函数, 便于单测).

    Args:
        left/top/right/bottom: 当前窗口矩形 (屏幕物理像素)
        edge: "n"/"s"/"e"/"w" 的组合, 如 "ne"
        dx/dy: 屏幕像素增量
    Returns:
        (left, top, right, bottom); 受 WINDOW_MIN_SIZE 约束, 不会倒置或成负尺寸
    """
    min_w, min_h = WINDOW_MIN_SIZE
    edge = (edge or "").lower()
    if "e" in edge:
        right = max(left + min_w, right + int(dx))
    if "w" in edge:
        left = min(right - min_w, left + int(dx))
    if "s" in edge:
        bottom = max(top + min_h, bottom + int(dy))
    if "n" in edge:
        top = min(bottom - min_h, top + int(dy))
    return left, top, right, bottom


class WindowApi:
    """通过 js_api 暴露给前端的窗口控制 (自定义标题栏按钮)."""

    def __init__(self) -> None:
        self._win = None
        self._on_open_login = None

    def bind(self, win) -> None:
        self._win = win

    def set_login_callback(self, cb) -> None:
        self._on_open_login = cb

    def open_login(self, mode: str = "relogin") -> bool:
        """前端登录入口: 弹出独立登录窗口. mode: "add"=添加新用户 / "relogin"=重登当前用户."""
        if self._on_open_login:
            self._on_open_login(mode if mode in ("add", "relogin") else "relogin")
        return True

    def minimize(self) -> bool:
        if self._win:
            self._win.minimize()
        return True

    def move_by(self, dx: float, dy: float) -> bool:
        """标题栏拖动(增量): dx/dy 为屏幕物理像素增量, 直接换算窗口位置.

        自实现拖动替代 pywebview easy_drag: easy_drag 的 JS 用 clientX 记录起点、
        screenX 计算增量 (两坐标系在 DPI 缩放下不同源), 后端 move() 又把参数
        乘一次 DPI 缩放, 高 DPI 屏幕上拖动会漂移抽动。前端已把 DIP 增量乘
        devicePixelRatio 换算成物理像素 (含小数余量累积), 与 GetWindowRect/
        SetWindowPos 的物理坐标系 1:1 对齐。

        加锁: js_api 高频触发时多个调用可能并发进入, 并发读-写会让多个线程
        读到同一旧位置、各自 SetWindowPos, 增量被覆盖丢失。
        """
        try:
            native = self._win.native
            hwnd = int(native.Handle.ToInt32())
            with _move_lock:
                rect = _RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                ctypes.windll.user32.SetWindowPos(
                    hwnd, None, rect.left + int(dx), rect.top + int(dy),
                    0, 0, 0x0001 | 0x0004,  # SWP_NOSIZE | SWP_NOZORDER
                )
        except Exception:  # noqa: BLE001
            pass
        return True

    def resize_by(self, edge: str, dx: float, dy: float) -> bool:
        """边缘拖拽调整窗口大小 (frameless 窗口在 Windows 上无系统边框可拖).

        pywebview 的 frameless -> WinForms ``FormBorderStyle.None``, 系统不再提供
        边框拖拽, 因此由前端在窗口边缘捕获拖拽后调用本方法。
        edge 为 "n"/"s"/"e"/"w" 或 "ne"/"nw"/"se"/"sw" 组合; dx/dy 是屏幕物理像素
        增量 (与 GetWindowRect 同坐标系), 与 move_by 保持一致; 最小尺寸受
        WINDOW_MIN_SIZE 约束。
        """
        try:
            if not self._win:
                return False
            native = self._win.native
            hwnd = int(native.Handle.ToInt32())
            edge = (edge or "").lower()
            with _move_lock:
                rect = _RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                left, top, right, bottom = _compute_resized_rect(
                    rect.left, rect.top, rect.right, rect.bottom, edge, dx, dy
                )
                ctypes.windll.user32.SetWindowPos(
                    hwnd, None, left, top, right - left, bottom - top,
                    0x0004,  # SWP_NOZORDER
                )
        except Exception:  # noqa: BLE001
            pass
        return True

    def close(self) -> bool:
        """关闭按钮: 托盘可用时最小化到托盘, 否则真正关闭."""
        global _quitting, _tray_ready
        if not self._win:
            return True
        if _quitting or not _tray_ready:
            _mlog(f"  [close] real quit (quitting={_quitting}, tray_ready={_tray_ready})")
            self._win.destroy()
        else:
            self._win.hide()  # 最小化到托盘
            _mlog("  [close] hidden to tray")
        return True

    def quit(self) -> bool:
        """退出应用 (欢迎页/设置页按钮): 真正退出, 不驻留托盘."""
        global _quitting
        _quitting = True
        _destroy_all_windows()
        return True


def _destroy_all_windows() -> None:
    """销毁所有窗口 (含隐藏登录窗), 让 pywebview 事件循环退出, 进程真正结束."""
    for w in list(webview.windows):
        try:
            w.destroy()
        except Exception:  # noqa: BLE001
            pass


def _install_close_to_tray(win) -> bool:
    """在 WinForms 层订阅 `FormClosing`, 把「关闭」改写成「隐藏到托盘」.

    **不要用 pywebview 自带的 `closing` 事件**: `Event.set()` 把 handler 丢进
    新线程异步执行, 却**立刻**读取返回值 (webview/event.py 的
    `false_values = [v for v in return_values if v is False]`), 此时集合还是空的,
    于是 `should_cancel` 恒为 False、`args.Cancel` 永远不被赋值 —— 无论 handler
    返回 True 还是 False 都拦不住关闭。实测结论: `TRUE_DOES_NOT_CANCEL`。

    改为直接订阅 .NET 的 `FormClosing`: 它在 UI 线程**同步**触发,
    `args.Cancel = True` 一定生效 (实测结论: `FORMCLOSING_CANCELS`)。
    这样 Alt+F4 / 任务栏缩略图关闭 / 系统菜单关闭都会合并到「隐藏到托盘」。
    """
    try:
        form = getattr(win, "native", None)
        if form is None:
            _mlog("[close] win.native 不可用, 无法安装原生关闭拦截")
            return False

        def on_form_closing(sender, args) -> None:  # noqa: ARG001 .NET 事件签名
            if _quitting or not _tray_ready:
                return  # 放行: 托盘不可用或正在退出, 必须能真正关掉
            try:
                form.Hide()
            except Exception as exc:  # noqa: BLE001
                # 藏不住就别拦, 否则窗口关不掉、托盘也没有 → 只能杀进程
                _mlog(f"[close] FormClosing hide failed: {exc}")
                return
            args.Cancel = True
            _mlog("[close] native close intercepted -> hidden to tray")

        form.FormClosing += on_form_closing
        _mlog("[close] FormClosing interceptor installed")
        return True
    except Exception as exc:  # noqa: BLE001
        _mlog(f"[close] 安装 FormClosing 拦截失败: {exc}")
        return False


def _install_close_to_tray_when_ready(win, timeout: float = 5.0) -> None:
    """等 ``win.native`` 就绪后再装拦截.

    `native` 由 pywebview 在 `webview.start()` 内部创建, 所以这个函数是交给
    `webview.start(func)` 当后台钩子调用的。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(win, "native", None) is not None:
            if _install_close_to_tray(win):
                return
        time.sleep(0.1)
    _mlog("[close] 超时: 未能安装 FormClosing 拦截 (关闭窗口仍会退出进程)")


def main() -> None:
    global _quitting

    # 单实例守卫: 已有实例在运行时激活其窗口, 当前进程直接退出
    _ensure_single_instance()

    db.get_db()  # 初始化数据库

    host, port = server.start_server()
    dashboard_url = f"http://{host}:{port}/"
    watcher: dict[str, object] = {"ref": None}
    api = WindowApi()

    # 启动窗口: 始终加载本地页面; 未登录时前端显示欢迎页引导登录
    wa_w, wa_h = _screen_workarea_logical()
    win_w = min(WINDOW_SIZE[0], wa_w - 60)
    win_h = min(WINDOW_SIZE[1], wa_h - 60)
    main_win = webview.create_window(
        APP_TITLE,
        dashboard_url,
        width=win_w,
        height=win_h,
        min_size=WINDOW_MIN_SIZE,
        frameless=True,  # 自定义标题栏
        # 显式关闭 easy_drag: 其默认值为 True, 不传会保持开启 (高 DPI 下拖动漂移)
        easy_drag=False,
        js_api=api,
    )
    api.bind(main_win)

    # 预创建独立登录子窗口 (hidden, 系统边框含关闭按钮; 点击"立即登录"时弹出)
    login_win_ref: dict[str, object] = {"win": webview.create_window(
        "CmdGauge - Command Code Login",
        "about:blank",
        width=720,
        height=640,
        min_size=(560, 500),
        hidden=True,
        background_color="#f7f6f4",
    )}

    def login_win() -> object:
        return login_win_ref["win"]

    def _bind_login_close_cleanup(win) -> None:
        """登录窗被手动关闭时: 停掉其监听线程并清理引用 (仅当引用仍指向该窗口)."""
        def _on_closed() -> None:
            w = watcher.get("ref")
            if isinstance(w, LoginWatcher) and getattr(w, "win", None) is win:
                w.stop()
                watcher["ref"] = None
                _mlog("  login window closed -> watcher cleaned")

        try:
            win.events.closed += _on_closed
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  bind login closed event error: {exc}")

    _bind_login_close_cleanup(login_win_ref["win"])

    # 登录模式: open_login(mode) 记录意图, on_login_success 按模式落库
    pending_mode = {"mode": "relogin"}

    def on_login_success(cookie: str, login_hint: str) -> None:
        """登录成功: 按模式保存 → 隐藏登录窗口 → 主窗口进入面板 → 全量同步.

        - add: 新建账号 (同 cookie 自动去重为既有账号) 并切换为活跃
        - relogin: 更新当前活跃账号凭证
        login_hint 来自 dotcom_user cookie (GitHub OAuth 登录场景), 用作账号名。
        """
        mode = pending_mode.get("mode", "relogin")
        _mlog(f"on_login_success: login={login_hint or '-'} mode={mode}")
        try:
            if mode == "add":
                db.add_account(cookie, login_hint, switch=True)
            else:
                db.save_token(cookie, login_hint)
            _mlog("  credentials saved")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  save credentials ERROR: {exc}")
        try:
            login_win().hide()
            _mlog("  login window hidden")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  hide ERROR: {exc}")
        try:
            main_win.load_url(dashboard_url)
            _mlog("  dashboard load_url called")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  load_url ERROR: {exc}")
        # 同 URL 的 load_url 可能被 WebView 跳过 (不重载): 显式通知前端就地刷新
        try:
            main_win.evaluate_js(
                "window.cmdgaugeOnLoginSuccess && window.cmdgaugeOnLoginSuccess();"
            )
            _mlog("  evaluate_js cmdgaugeOnLoginSuccess sent")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  evaluate_js ERROR: {exc}")
        server.sync_all_async("full")

    def _start_watcher(lw) -> None:
        """启动登录监听: 优先等 shown 事件 (避免 hidden 窗口调用窗口方法抛内部异常);
        复用窗口 (已显示过) 直接启动; 事件不触发时 3s 兜底启动 (LoginWatcher 对未就绪窗口有重试)."""
        w = LoginWatcher(lw, on_login_success)
        watcher["ref"] = w
        if getattr(lw, "_cmdgauge_shown", False):
            w.start()
            _mlog("  watcher started (reused window)")
            return

        def on_shown() -> None:
            setattr(lw, "_cmdgauge_shown", True)
            w.start()
            _mlog("  watcher started (shown event)")

        try:
            lw.events.shown += on_shown
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  shown event register error: {exc}")
        # 兜底: shown 事件在打包环境可能不触发, 3s 后无条件启动监听
        threading.Timer(3.0, w.start).start()

    def _login_win_alive() -> bool:
        try:
            return login_win() in webview.windows
        except Exception:  # noqa: BLE001
            return False

    def open_login(mode: str = "relogin") -> None:
        """弹出独立登录窗口并开始监听. 单飞守卫: 已有登录流程时忽略."""
        # 登录窗已被手动关闭 => 旧监听已失效: 先停旧线程再重建窗口
        if not _login_win_alive():
            w = watcher.get("ref")
            if isinstance(w, LoginWatcher):
                w.stop()
            watcher["ref"] = None
            _mlog("[main] login window gone -> recreate")
            pending_mode["mode"] = mode if mode in ("add", "relogin") else "relogin"
            _recreate_login_window()
            return
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher) and w._thread and w._thread.is_alive() and not w.done:
            return  # 已有登录监听进行中 (窗口存活)
        pending_mode["mode"] = mode if mode in ("add", "relogin") else "relogin"
        lw = login_win()
        try:
            lw.show()
            lw.load_url(build_login_url())
        except Exception as exc:  # noqa: BLE001 窗口可能被用户手动关闭, 重建
            print(f"[main] login window reopen: {exc}", flush=True)
            _recreate_login_window()
            return
        _start_watcher(lw)

    def _recreate_login_window() -> None:
        """登录窗口被手动关闭后重建 (回调绑定新窗口)."""
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher):
            w.stop()
        try:
            login_win().destroy()
        except Exception:  # noqa: BLE001
            pass
        new_win = webview.create_window(
            "CmdGauge - Command Code Login",
            build_login_url(),
            width=720,
            height=640,
            min_size=(560, 500),
            background_color="#f7f6f4",
        )
        login_win_ref["win"] = new_win
        _bind_login_close_cleanup(new_win)
        _start_watcher(new_win)

    api.set_login_callback(open_login)
    server.set_login_callback(open_login)  # /api/relogin 兼容 (浏览器环境/兜底)

    # 首次启动未登录: 主窗口欢迎页; 已登录但数据库为空: 自动全量同步
    if db.get_token() and not db.get_sync_state().get("total_records"):
        server.sync_all_async("full")

    def on_window_closed() -> None:
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher):
            w.stop()

    def on_shown() -> None:
        # 窗口显示后 native 句柄才可用: 补 WS_MINIMIZEBOX, 修复任务栏点击不最小化
        _enable_taskbar_minimize(main_win)

    def on_restored() -> None:
        # 窗口最小化->恢复过程中 WinForms 可能重建句柄导致样式丢失, 恢复后重新补上
        _enable_taskbar_minimize(main_win)

    main_win.events.closed += on_window_closed
    main_win.events.shown += on_shown
    main_win.events.restored += on_restored

    # 系统托盘 (logo 图标)
    tray = TrayIcon(_asset_path(ICON_NAME))
    tray.bind_window(lambda: main_win if main_win in webview.windows else None)
    tray.start()

    icon_path = _asset_path(ICON_NAME)
    # 持久化 WebView2 数据目录: pywebview 默认 private_mode=True, 每次启动都是全新的
    # 临时 profile, 导致登录态从不落盘 (GitHub 的登录 cookie 也随之丢弃, 每次都得重登)。
    # 改为存到数据目录下的 webview/, 这样重开登录窗时 GitHub 仍是登录态,
    # OAuth 会自动走完, 用户无需再次输入账号密码。
    storage = os.path.join(db.data_dir(), "webview")
    try:
        os.makedirs(storage, exist_ok=True)
    except OSError as exc:
        _mlog(f"[main] webview storage 目录不可用, 回退临时 profile: {exc}")
        storage = ""
    # 「关闭→托盘」的拦截要等 WinForms 窗口真正建好 (win.native 才有值), 而那已经
    # 是 webview.start() 内部的事了 —— 所以借它的后台 func 钩子来装。
    install_close_hook = lambda: _install_close_to_tray_when_ready(main_win)  # noqa: E731
    if storage:
        webview.start(
            install_close_hook,
            icon=icon_path if os.path.isfile(icon_path) else None,
            private_mode=False,
            storage_path=storage,
        )
    else:
        webview.start(install_close_hook, icon=icon_path if os.path.isfile(icon_path) else None)

    if not _quitting:
        tray.stop()


def shutdown() -> None:
    server.stop_server()
    db.close_db()


if __name__ == "__main__":
    main()
