"""本地 HTTP 服务: 静态资源 + JSON API + 后台同步."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__, db
from .commandcode_api import (
    AUTH_APIKEY,
    AUTH_COOKIE,
    AuthError,
    CmdAPIError,
    apikey_identity,
    check_auth_apikey,
    fetch_alpha_summary,
    fetch_chart_buckets,
    fetch_quota,
    fetch_quota_any,
    fetch_usage_all,
    usage_page_url,
)
from .updater import RELEASE_PAGE_URL, check_update

INCREMENTAL_LIMIT = 100  # 单次增量同步上限 (服务端窗口本来就是 1 天/100 条)
FULL_MAX_PAGES = 20  # 全量同步翻页上限, 防失控
QUOTA_CACHE_TTL = 30.0


def _resource_path(rel: str) -> str:
    """定位资源文件 (开发/打包后通用)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "app", "web", rel)
    return os.path.join(os.path.dirname(__file__), "web", rel)


# ---------------------------------------------------------------------------
# 同步状态 (跨线程)
# ---------------------------------------------------------------------------

_sync_lock = threading.Lock()
_sync_state: dict[str, Any] = {
    "running": False,
    "mode": "",
    "page": 0,
    "inserted": 0,
    "buckets": 0,  # 本次同步新增的 5 分钟聚合桶数
    "phase": "idle",  # idle | quota | usage | done | error
    "message": "",
    "account": "",  # 当前正在同步的账号名 (多账号顺序轮询)
}
_quota_cache: dict[int, dict[str, Any]] = {}  # {account_id: {"at": float, "data": ...}}
_quota_refreshing: set[int] = set()  # 防重入: 同一账号同时只允许一个刷新线程
_quota_lock = threading.Lock()  # 防重入检查与登记的原子化
_exchange_cache: dict[str, Any] = {"at": 0.0, "usd_cny": 7.2, "fail_at": 0.0}
_exchange_lock = threading.Lock()
_EXCHANGE_TTL = 6 * 3600  # 汇率缓存 6 小时
_EXCHANGE_FAIL_TTL = 300.0  # 拉取失败后 5 分钟内不重试 (失败不占用 6 小时正缓存)
_DEFAULT_USD_CNY = 7.2


def _fetch_usd_cny() -> float:
    """从 open.er-api.com 获取 USD→CNY 汇率, 失败时返回上次缓存/默认值."""
    if time.time() - _exchange_cache["at"] < _EXCHANGE_TTL:
        return _exchange_cache["usd_cny"]
    with _exchange_lock:  # 并发请求去重: 只放一个线程去拉
        now = time.time()
        if now - _exchange_cache["at"] < _EXCHANGE_TTL:
            return _exchange_cache["usd_cny"]
        if now - _exchange_cache.get("fail_at", 0.0) < _EXCHANGE_FAIL_TTL:
            return _exchange_cache["usd_cny"]
        try:
            import urllib.request

            req = urllib.request.Request(
                "https://open.er-api.com/v6/latest/USD",
                headers={"User-Agent": "CmdGauge/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            rate = float(data.get("rates", {}).get("CNY") or 0)
            if rate > 0:
                _exchange_cache.update(at=now, usd_cny=rate, fail_at=0.0)
            else:
                _exchange_cache["fail_at"] = now
        except Exception:  # noqa: BLE001 网络失败时保留旧值; 只短路 5 分钟而非缓存 6 小时
            _exchange_cache["fail_at"] = now
    return _exchange_cache["usd_cny"]


def _sync_progress_snapshot() -> dict[str, Any]:
    with _sync_lock:
        return dict(_sync_state)


def _set_phase(phase: str, message: str = "") -> None:
    with _sync_lock:
        _sync_state["phase"] = phase
        _sync_state["message"] = message
        _sync_state["running"] = phase in ("quota", "usage")


# ---------------------------------------------------------------------------
# 配额 (实时拉取 + 短缓存, 不落库)
# ---------------------------------------------------------------------------


def _fetch_quota_with_cache(
    account_id: int, cred: str, login: str, org_id: str, name: str,
    auth_type: str = AUTH_COOKIE,
) -> Optional[dict[str, Any]]:
    slot = _quota_cache.setdefault(account_id, {"at": 0.0, "data": None})
    now = time.time()
    if slot["data"] and now - slot["at"] < QUOTA_CACHE_TTL:
        return slot["data"]
    result = fetch_quota_any(
        cred, auth_type=auth_type, org_id=org_id or None, name=name or login or "Default"
    )
    data = result.to_dict() if result.success else None
    data = data or result.to_dict()  # 失败也带上 error 字段供前端提示
    slot["at"] = now
    slot["data"] = data
    return data


def _ensure_quota_async(account_id: Optional[int] = None) -> None:
    """若该账号配额缓存过期, 在后台线程刷新 (不阻塞 dashboard 响应, 防重入)."""
    aid = account_id or db.get_active_account_id()
    if not aid:
        return
    slot = _quota_cache.get(aid)
    now = time.time()
    if slot and slot["data"] and now - slot["at"] < QUOTA_CACHE_TTL:
        return
    with _quota_lock:  # 检查与登记原子化, 防并发请求双拉
        if aid in _quota_refreshing:
            return
        _quota_refreshing.add(aid)
    try:
        cred, login, org_id, auth_type = db.get_account_credentials(aid)
    except Exception:  # noqa: BLE001
        with _quota_lock:
            _quota_refreshing.discard(aid)
        return
    if not cred:
        with _quota_lock:
            _quota_refreshing.discard(aid)
        return
    acc = next((a for a in db.list_accounts() if a["id"] == aid), {})
    name = acc.get("name") or login or "Default"

    def worker() -> None:
        try:
            _fetch_quota_with_cache(aid, cred, login, org_id, name, auth_type)
        except Exception:  # noqa: BLE001
            _quota_cache[aid] = {
                "at": time.time(),
                "data": {"success": False, "error": "配额获取失败"},
            }
        finally:
            _quota_refreshing.discard(aid)
            db.close_thread_conn()  # worker 线程结束, 回收其 DB 连接

    threading.Thread(target=worker, daemon=True, name="cmdgauge-quota").start()


# ---------------------------------------------------------------------------
# 用量同步
# ---------------------------------------------------------------------------


def _sync_buckets(cred: str, org_id: str, account_id: int) -> int:
    """拉取 5 分钟聚合桶并入库 (缓存 token 的唯一上游来源).

    该端点窗口很小 (约 7 个桶 / 35 分钟) 且只回窗口内「有数据」的桶, 因此每次同步
    都要拉一次以连续累积。失败静默返回 0: 桶只影响缓存指标, 不该拖垮明细同步。
    """
    try:
        buckets = fetch_chart_buckets(cred, org_id=org_id or None)
    except (AuthError, CmdAPIError):
        return 0
    if not buckets:
        return 0
    try:
        return db.insert_usage_buckets([b.to_db_dict() for b in buckets], account_id)
    except Exception:  # noqa: BLE001
        return 0


def _sync_one_account(
    account_id: int, name: str, mode: str, window_days: Optional[int]
) -> dict[str, Any]:
    """同步单个账号的用量记录 (增量/全量均为"拉满服务端窗口后累积")."""
    cred, login, org_id, auth_type = db.get_account_credentials(account_id)
    if not cred:
        return {"ok": False, "error": "未登录"}

    with _sync_lock:
        _sync_state.update(account=name)

    # API Key 模式: /alpha/* 只提供聚合数据, 没有请求明细与 5 分钟桶。
    # 拉一次账单周期汇总存起来, 供「用量概览」兜底 (否则界面全是 0, 看起来像坏了)。
    if auth_type == AUTH_APIKEY:
        try:
            summary = fetch_alpha_summary(cred, org_id=org_id or None)
        except CmdAPIError as exc:
            db.update_sync_state("error", str(exc), 0, account_id)
            return {"ok": False, "error": str(exc)}
        if summary:
            db.save_account_summary(summary, account_id)
        db.update_sync_state("ok", None, 0, account_id, pages=0)
        return {
            "ok": True, "inserted": 0, "pages": 0, "fetched": 0, "buckets": 0,
            "apikey": True, "summary_requests": int(summary.get("totalCount") or 0),
        }

    try:
        max_pages = FULL_MAX_PAGES if mode == "full" else 2
        records, pages = fetch_usage_all(
            cred, max_pages=max_pages, org_id=org_id or None
        )
        inserted = db.insert_usage_records([r.to_db_dict() for r in records], account_id)
        buckets_added = _sync_buckets(cred, org_id, account_id)
        with _sync_lock:
            _sync_state["page"] = pages
            _sync_state["inserted"] = inserted
            _sync_state["buckets"] = buckets_added
        # 本地保留窗口裁剪 (与本次新增独立)
        if window_days is not None:
            db.prune_old_records(window_days, account_id)
        db.update_sync_state("ok", None, inserted, account_id, pages=pages)
        return {
            "ok": True, "inserted": inserted, "pages": pages,
            "fetched": len(records), "buckets": buckets_added,
        }
    except AuthError as exc:
        db.update_sync_state("error", str(exc), 0, account_id)
        return {"ok": False, "error": str(exc), "auth": True}
    except CmdAPIError as exc:
        db.update_sync_state("error", str(exc), 0, account_id)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        db.update_sync_state("error", str(exc), 0, account_id)
        return {"ok": False, "error": str(exc)}


def sync_usage(mode: str = "incremental") -> dict[str, Any]:
    """同步用量记录.

    - incremental: 顺序轮询所有已登录账号 (各账号独立状态)
    - full: 仅对当前活跃账号翻更多页
    """
    window_days = db.get_settings().get("window_days")

    if mode == "full":
        aid = db.get_active_account_id()
        targets = (
            [(aid, db.get_account().get("name") or f"#{aid}")]
            if aid and db.get_token()
            else []
        )
    else:
        targets = [(a["id"], a["name"]) for a in db.list_accounts() if a["has_token"]]
    if not targets:
        return {"ok": False, "error": "未登录"}

    with _sync_lock:
        if _sync_state["running"]:
            return {"ok": False, "error": "已有同步任务进行中"}
        _sync_state.update(running=True, mode=mode, page=0, inserted=0, phase="usage", message="")

    try:
        total_inserted = 0
        total_fetched = 0
        pages = 0
        errors: list[tuple[str, str, bool]] = []  # (账号名, 错误, 是否认证失败)
        ok_count = 0
        for aid, name in targets:
            result = _sync_one_account(aid, name, mode, window_days)
            total_inserted += int(result.get("inserted") or 0)
            total_fetched += int(result.get("fetched") or 0)
            pages += int(result.get("pages") or 0)
            if result.get("ok"):
                ok_count += 1
            else:
                # 单账号失败不中止其余账号 (坏 cookie 曾把多账号自动同步整个卡死)
                errors.append((name, result.get("error") or "同步失败", bool(result.get("auth"))))

        if errors and ok_count == 0:
            # 全部失败: 明确报错 (原先 full 模式唯一目标失败仍返回 ok=True)
            name, err, auth = errors[0]
            _set_phase("error", f"[{name}] {err}")
            return {
                "ok": False,
                "error": err,
                "auth": auth,
                "partial_inserted": total_inserted,
            }

        if errors:
            _set_phase("done", f"部分账号同步失败 ({ok_count}/{len(targets)} 成功)")
            return {
                "ok": True, "partial": True,
                "inserted": total_inserted, "pages": pages,
                "fetched": total_fetched,
                "errors": [f"[{n}] {e}" for n, e, _ in errors],
            }

        if total_fetched == 0:
            _set_phase("done", "同步完成, 服务端当前窗口内没有新记录")
        else:
            _set_phase("done", f"同步完成, 拉取 {total_fetched} 条, 新增 {total_inserted} 条")
        return {"ok": True, "inserted": total_inserted, "pages": pages, "fetched": total_fetched}
    except Exception as exc:  # noqa: BLE001
        _set_phase("error", str(exc))
        return {"ok": False, "error": str(exc)}
    finally:
        with _sync_lock:
            _sync_state["running"] = False


def sync_all_async(mode: str) -> None:
    """后台线程执行用量同步 (配额由独立后台线程刷新, 不阻塞用量)."""

    def worker() -> None:
        try:
            _ensure_quota_async()
            sync_usage(mode)
        except Exception:  # noqa: BLE001
            _set_phase("error", "同步失败")
        finally:
            db.close_thread_conn()  # worker 线程结束, 回收其 DB 连接

    threading.Thread(target=worker, daemon=True, name="cmdgauge-sync").start()


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

_on_open_login: Optional[Callable[[str], None]] = None
_server: Optional[ThreadingHTTPServer] = None


def set_login_callback(callback: Callable[[str], None]) -> None:
    """由 main.py 注册: 前端请求登录时触发窗口跳转.

    回调契约: callback(mode), mode 为 "add" (添加新用户) 或 "relogin" (重新登录).
    """
    global _on_open_login
    _on_open_login = callback


_MAX_BODY_BYTES = 1 << 20  # 请求体上限 1 MiB (声明超大 Content-Length 会阻塞 handler 线程)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        raise ValueError("invalid Content-Length")
    if length < 0 or length > _MAX_BODY_BYTES:
        raise ValueError("request body too large")
    return json.loads(handler.rfile.read(length).decode("utf-8", errors="replace"))


def _json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _static_response(handler: BaseHTTPRequestHandler, rel: str) -> None:
    rel = rel.lstrip("/")
    if ".." in rel.replace("\\", "/").split("/"):
        handler.send_error(403)
        return
    path = _resource_path(rel)
    # os.path.join 遇到盘符绝对路径 (C:/...) 或 UNC (//host/share) 会整体重置,
    # 仅挡 ".." 挡不住这类请求 → 任意文件读。解析后必须仍在资源根目录内。
    root = os.path.realpath(_resource_path(""))
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        handler.send_error(403)
        return
    if not os.path.isfile(path):
        handler.send_error(404)
        return
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    try:
        with open(path, "rb") as fh:
            body = fh.read()
    except OSError:
        handler.send_error(500)
        return
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def _handle_api(handler: BaseHTTPRequestHandler, path: str, query: dict[str, list[str]]) -> None:
    method = handler.command
    route = path

    if route == "/api/version" and method == "GET":
        _json_response(handler, {"version": __version__})
        return

    if route == "/api/update/check" and method == "GET":
        try:
            _json_response(handler, check_update())
        except Exception as exc:  # noqa: BLE001 网络/解析失败 -> 前端提示
            _json_response(handler, {"error": str(exc)}, status=502)
        return

    if route == "/api/update/open" and method == "POST":
        import webbrowser

        webbrowser.open(RELEASE_PAGE_URL)
        _json_response(handler, {"ok": True})
        return

    if route == "/api/open/usage" and method == "POST":
        # 用系统默认浏览器打开当前账号的官方用量页 (WebView 内 window.open 不可靠)
        import webbrowser

        url = usage_page_url(db.get_login_hint())
        webbrowser.open(url)
        _json_response(handler, {"ok": True, "url": url})
        return

    if route == "/api/state" and method == "GET":
        account = db.get_account()
        _json_response(
            handler,
            {
                "logged_in": bool(db.count_logged_in_accounts()),
                "account": account,
                "accounts": db.list_accounts(),
                "accounts_total": db.count_accounts(),
                "accounts_logged_in": db.count_logged_in_accounts(),
                "sync": db.get_sync_state(),
                "progress": _sync_progress_snapshot(),
                "datadir": db.data_dir(),
                "usage_page_url": usage_page_url(account.get("login", "")),
                "version": __version__,
            },
        )
        return

    if route == "/api/sync" and method == "POST":
        mode = (query.get("mode") or ["incremental"])[0]
        if mode not in ("incremental", "full"):
            _json_response(handler, {"ok": False, "error": "invalid mode"}, 400)
            return
        if mode == "incremental":
            if not db.count_logged_in_accounts():
                _json_response(handler, {"ok": False, "error": "未登录"}, 401)
                return
        elif not db.get_token():
            _json_response(handler, {"ok": False, "error": "未登录"}, 401)
            return
        sync_all_async(mode)
        _json_response(handler, {"ok": True})
        return

    if route == "/api/dashboard" and method == "GET":
        range_param = query.get("range", ["today"])[0]
        if range_param == "today":
            period = "today"
        elif range_param == "7d":
            period = "7d"
        elif range_param == "all":
            period = "all"
        else:
            period = "30d"
        token = db.get_token()
        account = db.get_account()
        active_id = db.get_active_account_id()
        _ensure_quota_async(active_id)
        slot = _quota_cache.get(active_id) or {}
        quota = slot.get("data") if token else None
        # 模型排行合并缓存命中率 (来自 5 分钟聚合桶, 与明细表口径不同源)
        models = db.model_stats(period)
        cache_by_model = {m["model"]: m for m in db.model_cache_stats(period)}
        for m in models:
            c = cache_by_model.get(m["model"])
            m["hit_rate"] = c["hit_rate"] if c else None
            m["cache_read_tokens"] = c["cache_read_tokens"] if c else 0
            m["cache_creation_tokens"] = c["cache_creation_tokens"] if c else 0
            m["cache_savings"] = c["cache_savings"] if c else 0.0
        # API Key 模式没有请求明细, 用账单周期汇总兜底, 并明确标注口径来源
        _, _, _, auth_type = db.get_account_credentials(active_id)
        totals = db.totals(period)
        totals_source = "records"
        if auth_type == AUTH_APIKEY:
            fb = db.summary_as_totals(db.get_account_summary(active_id))
            if fb:
                totals = fb
                totals_source = "billing-period"
        _json_response(
            handler,
            {
                "logged_in": bool(token),
                "account": account,
                "account_name": account.get("name", ""),
                "accounts_total": db.count_accounts(),
                "accounts_logged_in": db.count_logged_in_accounts(),
                "quota": quota,
                "totals": totals,
                "totals_source": totals_source,
                "today": totals if totals_source == "billing-period" else db.totals("today"),
                "cache": db.cache_stats(period),
                "daily": db.daily_stats(7) if totals_source == "records" else [],
                "trend": db.daily_stats(30) if totals_source == "records" else [],
                "today_trend": db.today_trend() if totals_source == "records" else [],
                "models": models if totals_source == "records" else [],
                "sync": db.get_sync_state(),
                "progress": _sync_progress_snapshot(),
                "range": range_param,
                "auth_type": auth_type,
                "usage_page_url": usage_page_url(account.get("login", "")),
                "exchange_rate": {"usd_cny": _fetch_usd_cny(), "currency": "CNY"},
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        return

    if route == "/api/logout" and method == "POST":
        with _sync_lock:
            running = _sync_state["running"]
        if running:
            # 同步在飞时清库会让刚删的数据被同步线程写回 ("复活")
            _json_response(handler, {"ok": False, "error": "同步进行中, 请稍后再退出登录"}, 409)
            return
        aid = db.get_active_account_id()
        db.clear_account()
        if aid:
            _quota_cache.pop(aid, None)
        _json_response(handler, {"ok": True})
        return

    if route == "/api/relogin" and method == "POST":
        if _on_open_login:
            _on_open_login("relogin")
        _json_response(handler, {"ok": True})
        return

    if route == "/api/login/apikey" and method == "POST":
        # API Key 登录 (备选认证): 先校验再用 /alpha/* 拉身份
        try:
            body = _read_json_body(handler)
            key = str((body or {}).get("key") or "").strip()
        except Exception:  # noqa: BLE001
            _json_response(handler, {"ok": False, "error": "无效请求体"}, 400)
            return
        if not key:
            _json_response(handler, {"ok": False, "error": "API Key 不能为空"}, 400)
            return
        ok, err = check_auth_apikey(key)
        if not ok:
            _json_response(handler, {"ok": False, "error": err or "API Key 无效"}, 400)
            return
        ident = apikey_identity(key)
        login = ident.get("login", "")
        org_id = ident.get("org_id", "")
        mode = (query.get("mode") or ["relogin"])[0]
        if mode == "add":
            aid = db.add_account(key, login, org_id, AUTH_APIKEY, switch=True)
        else:
            db.save_token(key, login, org_id, AUTH_APIKEY)
            aid = db.get_active_account_id()
        if aid:
            _quota_cache.pop(aid, None)  # 认证方式变了, 丢弃旧配额缓存
        # 与浏览器登录保持一致: 登录成功立即同步 (API Key 模式下账单汇总
        # 只有同步时才入库, 不触发的话概览会一直是 0)
        sync_all_async("full")
        _json_response(
            handler,
            {"ok": True, "id": aid, "login": login, "org_id": org_id,
             "auth_type": AUTH_APIKEY},
        )
        return

    # ---------------- 多账号管理 ----------------

    if route == "/api/accounts" and method == "GET":
        _json_response(
            handler,
            {
                "ok": True,
                "accounts": db.list_accounts(),
                "active_id": db.get_active_account_id(),
            },
        )
        return

    if route == "/api/accounts/overview" and method == "GET":
        active_id = db.get_active_account_id()
        accounts: list[dict[str, Any]] = []
        for acc in db.list_accounts():
            if not acc["has_token"]:
                continue
            aid = acc["id"]
            _ensure_quota_async(aid)
            slot = _quota_cache.get(aid)
            sync_state = db.get_sync_state(aid)
            # API Key 模式没有请求明细: today 也用账单汇总兜底 (与 dashboard 同口径)
            if acc.get("auth_type") == "apikey":
                today = db.summary_as_totals(db.get_account_summary(aid))
            else:
                today = db.totals("today", aid)
            accounts.append(
                {
                    "id": aid,
                    "name": acc["name"],
                    "login": acc.get("login", ""),
                    "auth_type": acc.get("auth_type", "cookie"),
                    "logged_in": True,
                    "active": aid == active_id,
                    "quota": slot.get("data") if slot else None,
                    "today": today,
                    "cache": db.cache_stats("today", aid),
                    "today_trend": db.today_trend(aid),
                    "daily7": db.daily_stats(7, aid),
                    "last_sync_at": sync_state.get("last_sync_at"),
                    "last_sync_status": sync_state.get("last_sync_status"),
                }
            )
        _json_response(
            handler,
            {
                "ok": True,
                "accounts": accounts,
                "active_id": active_id,
                "exchange_rate": {"usd_cny": _fetch_usd_cny(), "currency": "CNY"},
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        return

    if route.startswith("/api/accounts/") and method == "POST":
        try:
            body = _read_json_body(handler)
            if not isinstance(body, dict):
                raise ValueError
        except Exception:  # noqa: BLE001
            _json_response(handler, {"ok": False, "error": "无效请求体"}, 400)
            return
        action = route[len("/api/accounts/"):]

        if action == "switch":
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            row = (
                db.get_db()
                .execute("SELECT TRIM(token) AS t FROM accounts WHERE id = ?", (aid,))
                .fetchone()
                if aid
                else None
            )
            if row is None:
                _json_response(handler, {"ok": False, "error": "账号不存在"}, 404)
                return
            if not row["t"]:
                _json_response(handler, {"ok": False, "error": "该账号未登录"}, 400)
                return
            db.set_active_account(aid)
            _json_response(handler, {"ok": True, "active_id": aid})
            return

        if action == "rename":
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            if not db.rename_account(aid, str(body.get("name") or "")):
                _json_response(
                    handler, {"ok": False, "error": "重命名失败 (账号不存在或名称为空)"}, 400
                )
                return
            _json_response(handler, {"ok": True})
            return

        if action == "delete":
            with _sync_lock:
                running = _sync_state["running"]
            if running:
                _json_response(handler, {"ok": False, "error": "同步进行中, 请稍后再删除账号"}, 409)
                return
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            remaining = db.delete_account(aid) if aid else -1
            if remaining < 0:
                _json_response(handler, {"ok": False, "error": "无效账号 id"}, 400)
                return
            _quota_cache.pop(aid, None)
            _json_response(handler, {"ok": True, "remaining": remaining})
            return

        if action == "add":
            opened = bool(_on_open_login)
            if opened:
                _on_open_login("add")
            _json_response(handler, {"ok": True, "opened": opened})
            return

        _json_response(handler, {"ok": False, "error": "未知操作"}, 404)
        return

    if route == "/api/usage/records" and method == "GET":
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        try:
            page_size = max(1, min(int(query.get("page_size", ["50"])[0]), 100))
        except ValueError:
            page_size = 50
        model = query.get("model", [""])[0] or None
        status = query.get("status", [""])[0] or None
        days_raw = query.get("days", [""])[0]
        try:
            days = max(1, min(int(days_raw), 365)) if days_raw else None
        except ValueError:
            days = None
        records, total = db.usage_records_page(page, page_size, model, days, status)
        _json_response(
            handler,
            {
                "records": records,
                "total": total,
                "page": page,
                "page_size": page_size,
                "models": db.list_models(),
                "filter": {"model": model, "days": days, "status": status},
            },
        )
        return

    if route == "/api/usage/days" and method == "GET":
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        try:
            page_size = max(1, min(int(query.get("page_size", ["10"])[0]), 50))
        except ValueError:
            page_size = 10
        days_raw = query.get("days", [""])[0]
        try:
            days = max(1, min(int(days_raw), 365)) if days_raw else None
        except ValueError:
            days = None
        records, total = db.day_stats_page(page, page_size, days)
        _json_response(
            handler,
            {
                "records": records,
                "total": total,
                "page": page,
                "page_size": page_size,
                "filter": {"days": days},
            },
        )
        return

    if route == "/api/settings" and method == "GET":
        _json_response(handler, db.get_settings())
        return

    if route == "/api/settings" and method == "PUT":
        try:
            body = _read_json_body(handler)
            if not isinstance(body, dict):
                raise ValueError
        except Exception:  # noqa: BLE001
            _json_response(handler, {"ok": False, "error": "无效请求体"}, 400)
            return
        _json_response(handler, db.save_settings(body))
        return

    _json_response(handler, {"ok": False, "error": "not found"}, 404)


_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _host_allowed(handler: BaseHTTPRequestHandler) -> bool:
    """校验 Host 头 (防 DNS rebinding: 无校验时外部页面可借域名指到 127.0.0.1 同源读接口)."""
    host = (handler.headers.get("Host") or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):  # [::1]:8000
        host = host[1:host.index("]")] if "]" in host else host[1:]
    elif host.count(":") == 1:  # host:port
        host = host.rsplit(":", 1)[0]
    return host in _ALLOWED_HOSTS


class _Handler(BaseHTTPRequestHandler):
    server_version = "CmdGauge/1.0"
    # keep-alive: 浏览器在同一条 TCP 连接上复用同一 handler 线程 → 线程内 DB 连接
    # 一并复用。原 HTTP/1.0 每请求新连接新线程, 而线程内连接被 _ALL_CONNS 永久
    # 持有, 长驻进程按请求泄漏 SQLite 连接 (实测 50 请求泄 50 条)。
    protocol_version = "HTTP/1.1"
    timeout = 120  # 空闲 keep-alive 连接最长等待, 超时后线程退出并回收连接

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默日志
        pass

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            db.close_thread_conn()  # 连接/线程结束, 回收线程内 DB 连接

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if not _host_allowed(self):
            try:
                _json_response(self, {"ok": False, "error": "forbidden host"}, 403)
            except Exception:  # noqa: BLE001 客户端已断开等
                pass
            return
        if path.startswith("/api/"):
            try:
                _handle_api(self, path, query)
            except Exception as exc:  # noqa: BLE001
                try:
                    _json_response(self, {"ok": False, "error": str(exc)}, 500)
                except Exception:  # noqa: BLE001 响应已部分写出时不再二次写
                    pass
            return
        if path == "/" or path == "":
            _static_response(self, "index.html")
        else:
            _static_response(self, path)

    def do_POST(self) -> None:  # noqa: N802
        self._handle_api_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_api_request()

    def _handle_api_request(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if not _host_allowed(self):
            try:
                _json_response(self, {"ok": False, "error": "forbidden host"}, 403)
            except Exception:  # noqa: BLE001
                pass
            return
        if path.startswith("/api/"):
            try:
                _handle_api(self, path, query)
            except Exception as exc:  # noqa: BLE001
                try:
                    _json_response(self, {"ok": False, "error": str(exc)}, 500)
                except Exception:  # noqa: BLE001
                    pass
            return
        self.send_error(404)


def start_server(host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
    """启动 HTTP 服务, 返回 (host, port)."""
    global _server
    _server = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(target=_server.serve_forever, daemon=True, name="cmdgauge-http")
    thread.start()
    return _server.server_address[0], _server.server_address[1]


def stop_server() -> None:
    global _server
    if _server:
        _server.shutdown()
        _server.server_close()
        _server = None
