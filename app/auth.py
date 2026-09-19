"""WebView 登录: 加载 commandcode.ai 登录页, 捕获 session cookie.

原理: 用户在弹出的独立窗口里完成登录 (GitHub OAuth / 邮箱等), 登录成功后页面会
落回 ``commandcode.ai`` 自己的域名; 此时 pywebview (WebView2) 的
``window.get_cookies()`` 能读到 HttpOnly 的 session cookie。

除 session cookie 外还会顺带读取 GitHub OAuth 场景下的 ``dotcom_user``
(即站点 login), 用于回填账号名与官方用量页链接 ``/<login>/settings/usage``。
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from http.cookies import SimpleCookie as SimpleCookieCls
from typing import Callable, Optional
from urllib.parse import urlparse

import webview

from . import db

SITE_HOST = "commandcode.ai"
SITE_BASE = "https://commandcode.ai"
LOGIN_URL = "https://commandcode.ai/signin"

# better-auth 在本站使用的 cookie 名 (实测)
SESSION_COOKIE_NAME = "__Secure-commandcode_prod_.session_token"
SESSION_COOKIE_HINT = "session_token"
COOKIE_PREFIX = "commandcode"

# GitHub OAuth 登录场景下可借此拿到站点 login
LOGIN_HINT_COOKIE = "dotcom_user"

COOKIE_POLL_SEC = 1.0
LOGIN_TIMEOUT_SEC = 15 * 60  # 15 分钟未完成登录则放弃监听

# OAuth 中间页干预: GitHub 授权完成后会给一个"正在重定向回应用"的页面, 若它没能
# 自动跳回 (WebView2 与真实 Chrome 行为有差异), 就由 watcher 主动干预。
STUCK_NUDGE_SEC = 8.0  # 停留在非站点域多久后开始干预
MAX_NUDGES = 3  # 最多干预几次, 避免死循环
STUCK_MARKERS = (
    "redirected to the authorized application",
    "does not redirect you back",
    "setup page",
)

_LOG_FILE = os.path.join(tempfile.gettempdir(), "cmdgauge_login.log")


def _log(msg: str) -> None:
    """同时输出到 stdout 与日志文件 (便于诊断)."""
    print(msg, flush=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def build_login_url(return_to: str = "/settings/usage") -> str:
    """构造登录 URL (带 returnTo, 登录后直接回到用量页)."""
    from urllib.parse import quote

    if return_to:
        return f"{LOGIN_URL}?returnTo={quote(return_to, safe='')}"
    return LOGIN_URL


def _cookie_pairs(cookies) -> list[tuple[str, str]]:
    """把 pywebview ``get_cookies()`` 的多种返回形态统一为 (name, value) 列表.

    pywebview 可能返回 ``http.cookies.SimpleCookie`` (dict 子类) 或普通 dict,
    必须优先按 SimpleCookie 解析, 否则会把整张 cookie 当成一个 name。
    """
    pairs: list[tuple[str, str]] = []
    for cookie in cookies or []:
        if isinstance(cookie, SimpleCookieCls):
            for name, morsel in cookie.items():
                if name and morsel.value:
                    pairs.append((str(name), str(morsel.value)))
        elif isinstance(cookie, dict):
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            if name and value:
                pairs.append((name, value))
    return pairs


def pick_session_cookies(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    """从 (name, value) 列表中挑出凭证.

    Returns:
        (cookie_header, login_hint)
        - cookie_header: 带上全部 commandcode 域 cookie 的 Cookie 头 (空串=未登录)
        - login_hint: GitHub OAuth 场景下的站点 login (可能为空)
    """
    site_cookies = [(n, v) for n, v in pairs if COOKIE_PREFIX in n]
    session = next(
        (v for n, v in site_cookies if n == SESSION_COOKIE_NAME or SESSION_COOKIE_HINT in n),
        "",
    )
    if not session:
        return "", ""
    # 同时带上 session_data 等附属 cookie (实测更稳)
    header = "; ".join(f"{n}={v}" for n, v in site_cookies)
    login = next((v for n, v in pairs if n == LOGIN_HINT_COOKIE), "")
    return header, login


def host_of(url: str) -> str:
    """取 URL 的 host (小写), 解析失败返回空串."""
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def needs_nudge(host: str, text: str) -> bool:
    """判断当前页面是否属于「自动流程卡住」, 需要主动干预.

    注意 OAuth 的 redirect_uri 落在 ``api.commandcode.ai/auth/callback``, 即
    **api 子域也是 commandcode.ai 的一部分**; 若只用 ``SITE_HOST in url`` 判断,
    会把卡在 api 回调页的情况当成"已回到站点"而永远不干预 (这正是登录卡死的根因)。

    - GitHub 域: 仅当停在"正在重定向回应用"这类页面才干预 (普通登录页要留给用户输入)
    - api 子域: OAuth 回调页属自动流程, 停留过久即视为卡住
    """
    low = (text or "").lower()
    if "github.com" in host:
        return any(m in low for m in STUCK_MARKERS)
    if host.startswith("api.") and SITE_HOST in host:
        return True
    return False


class LoginWatcher:
    """后台轮询登录窗口, 捕获 session cookie."""

    def __init__(
        self,
        win,
        on_success: Callable[[str, str], None],
        on_cancelled: Optional[Callable[[], None]] = None,
        timeout_sec: float = LOGIN_TIMEOUT_SEC,
    ):
        self.win = win
        self.on_success = on_success  # fn(cookie_header, login_hint)
        self.on_cancelled = on_cancelled
        self.timeout_sec = timeout_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.done = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cmdgauge-login")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _window_alive(self) -> bool:
        try:
            return self.win in webview.windows
        except Exception:  # noqa: BLE001
            return False

    def _page_text(self, limit: int = 300) -> str:
        """读取登录窗当前页面可见文本 (诊断 + 卡住判定), 失败返回空串."""
        try:
            text = self.win.evaluate_js(
                "(document.body && document.body.innerText || '').slice(0, %d)" % limit
            )
            return str(text or "")
        except Exception:  # noqa: BLE001 页面未就绪/已销毁
            return ""

    def _click_continue(self) -> str:
        """尝试点击中间页上的"继续/授权"链接, 返回结果描述 (供日志)."""
        script = (
            "(function(){"
            "var links = Array.prototype.slice.call(document.querySelectorAll('a[href]'));"
            "var t = links.filter(function(a){"
            "  return /setup|continue|authorize|redirect/i.test(a.textContent || '')"
            "      || /setup|continue|authorize/i.test(a.getAttribute('href') || '');"
            "})[0];"
            "if (t) { var s = t.textContent || t.getAttribute('href'); t.click(); return 'clicked:' + s; }"
            "return 'no-link';"
            "})()"
        )
        try:
            return str(self.win.evaluate_js(script) or "no-result")
        except Exception as exc:  # noqa: BLE001
            return f"error:{type(exc).__name__}"

    def _nudge(self) -> str:
        """干预卡住的自动流程页: 优先点击页面上的继续链接, 否则导航回站点."""
        clicked = self._click_continue()
        if clicked.startswith("clicked:"):
            return clicked
        try:
            self.win.load_url(f"{SITE_BASE}/")
            return f"navigated to {SITE_BASE}/ ({clicked})"
        except Exception as exc:  # noqa: BLE001
            return f"navigate failed: {exc}"

    def _run(self) -> None:
        _log("[login] watcher started")
        try:
            self._run_loop()
        finally:
            # on_success 回调在本线程内触库; 线程退出前回收其连接, 防泄漏
            db.close_thread_conn()

    def _run_loop(self) -> None:
        deadline = time.monotonic() + self.timeout_sec
        last_url = ""
        stuck_since = time.monotonic()
        last_cookie_log = 0.0
        nudges = 0
        while not self._stop.is_set():
            try:
                url = self.win.get_current_url() or ""
            except Exception:  # noqa: BLE001 窗口未加载完成或已销毁
                if not self._window_alive():
                    _log("[login] window closed, watcher exits")
                    break
                self._stop.wait(COOKIE_POLL_SEC)
                continue

            # URL 变化一律记录 (含非站点域): 卡住时这是唯一诊断线索
            if url != last_url:
                _log(f"[login] url -> {url[:200]}")
                last_url = url
                stuck_since = time.monotonic()

            host = host_of(url)
            now_m = time.monotonic()

            # 任何 *.commandcode.ai 页面都查 session cookie
            # (session cookie 的 domain 是 .commandcode.ai, api 子域同样可见)
            if SITE_HOST in host:
                try:
                    pairs = _cookie_pairs(self.win.get_cookies())
                except Exception as exc:  # noqa: BLE001
                    pairs = []
                    _log(f"[login] get_cookies ERROR {type(exc).__name__}: {exc}")
                header, login_hint = pick_session_cookies(pairs)
                if header:
                    _log(
                        f"[login] SUCCESS: session captured (len={len(header)}), "
                        f"login={login_hint or '-'}"
                    )
                    self.done = True
                    self._stop.set()
                    self.on_success(header, login_hint)
                    return
                # 没拿到 session 时周期性记录 cookie 名, 便于诊断卡在哪一步
                if now_m - last_cookie_log >= 6.0:
                    last_cookie_log = now_m
                    _log(
                        f"[login] on {host}: no session yet, "
                        f"cookies={[n for n, _ in pairs][:12]}"
                    )

            # 卡住干预: OAuth 回调落在 api 子域, GitHub 侧也可能停在中间页
            if now_m - stuck_since >= STUCK_NUDGE_SEC and nudges < MAX_NUDGES:
                nudges += 1
                text = self._page_text()
                if needs_nudge(host, text):
                    _log(
                        f"[login] stuck {int(now_m - stuck_since)}s on {url[:140]} "
                        f"| text={text[:140]!r}"
                    )
                    _log(f"[login] nudge#{nudges} -> {self._nudge()}")
                else:
                    _log(f"[login] idle {int(now_m - stuck_since)}s on {url[:140]} (等待用户操作)")
                stuck_since = now_m

            if now_m > deadline:
                _log("[login] timeout, watcher exits")
                break
            self._stop.wait(COOKIE_POLL_SEC)
        if not self.done and self.on_cancelled:
            self.on_cancelled()
