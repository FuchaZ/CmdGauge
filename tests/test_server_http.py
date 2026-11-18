"""server.py HTTP 层测试: 安全 (Host 白名单/路径穿越) / 守卫 / 分页夹紧 / 口径对齐.

起真实 HTTP 服务 (随机端口), 临时数据目录, 打桩配额接口, 不触网。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module")
def http_env(tmp_path_factory):
    """模块级独立服务: CMDGAUGE_DATA 指向临时目录, 起服务, 打桩配额."""
    tmp = tmp_path_factory.mktemp("cmdgauge-http")
    os.environ["CMDGAUGE_DATA"] = str(tmp)
    # db 解析结果进程内缓存: 重置连接让本模块用新目录
    from app import db, server

    db.close_db()
    db._resolved_data_dir = None

    def _fake_quota(cred=None, auth_type="cookie", org_id=None, name="Default",  # noqa: ARG001
                    target_user_id=None):
        from app.commandcode_api import QuotaResult, QuotaWindow

        return QuotaResult(
            name=name or "Default", success=True, updated_at="",
            windows=[QuotaWindow(label="5h", used=1.0, total=10.0, remaining=9.0)],
        )

    server.fetch_quota_any = _fake_quota
    host, port = server.start_server(port=0, with_scheduler=False)
    yield {"host": host, "port": port, "db": db, "server": server}
    server.stop_server()
    db.close_db()
    server.fetch_quota_any = None


def _call(port, method, path, body=None, headers=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            ctype = resp.headers.get("Content-Type", "")
            try:
                return resp.status, json.loads(body) if body else None, ctype
            except ValueError:
                return resp.status, body, ctype
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode()), ""
        except Exception:  # noqa: BLE001
            return exc.code, None, ""


def _seed(db, n=3, model="m1"):
    from datetime import datetime as dt

    aid = db.add_account("ck-http", login="carol")
    now = dt.now(timezone.utc)
    recs = [
        {
            "usg_id": f"h{i}", "created_at": (now - timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "model": model, "input_tokens": 100, "output_tokens": 10, "duration_ms": 900,
            "status": "completed" if i else "error",   # 1 条非 completed 非空状态
            "mode": "agent", "type": "api",
            "input_cost": 0.01, "output_cost": 0.02, "cache_cost": 0.003,
            "cost_usd": 0.033, "trace_id": None,
        }
        for i in range(n)
    ]
    db.insert_usage_records(recs, aid)
    return aid


# ---------------------------------------------------------------------------
# 安全
# ---------------------------------------------------------------------------


def test_host_allowlist(http_env):
    port = http_env["port"]
    st, body, _ = _call(port, "GET", "/api/version", headers={"Host": "evil.example.com"})
    assert st == 403 and body["error"] == "forbidden host"
    st, body, _ = _call(port, "GET", "/api/version")
    assert st == 200 and "version" in body


def test_static_traversal_blocked(http_env):
    port = http_env["port"]
    # 字面量 .. 直接 403
    st, _, _ = _call(port, "GET", "/../../etc/passwd")
    assert st == 403
    # 编码穿越 (%2e%2e / %2f) 也拿不到文件: realpath 守卫或 404
    st, body, _ = _call(port, "GET", "/%2e%2e/%2e%2e/windows/win.ini")
    assert st in (403, 404)
    st, body, _ = _call(port, "GET", "/..%5C..%5Cwindows%5Cwin.ini")
    assert st in (403, 404)


def test_static_serves_assets(http_env):
    port = http_env["port"]
    st, body, ctype = _call(port, "GET", "/")
    assert st == 200 and "text/html" in ctype and "CmdGauge" in body
    st, body, ctype = _call(port, "GET", "/app.js")
    assert st == 200 and "javascript" in ctype
    st, _, ctype = _call(port, "GET", "/icons/default.svg")
    assert st == 200 and ctype == "image/svg+xml"


def test_unknown_api_route_404(http_env):
    st, body, _ = _call(http_env["port"], "GET", "/api/definitely-not-a-route")
    assert st == 404 and body["ok"] is False


# ---------------------------------------------------------------------------
# 业务守卫与口径
# ---------------------------------------------------------------------------


def test_settings_roundtrip_and_clamps(http_env):
    port = http_env["port"]
    db = http_env["db"]
    st, saved, _ = _call(port, "PUT", "/api/settings", {"sync_interval_sec": 10})
    assert st == 200 and saved["sync_interval_sec"] == 30       # 下界夹紧
    st, saved, _ = _call(port, "PUT", "/api/settings", {"window_days": "all"})
    assert saved["window_days"] is None
    st, saved, _ = _call(port, "PUT", "/api/settings", {"auto_sync": "false"})
    assert saved["auto_sync"] is False                          # 字符串布尔严格转换
    _call(port, "PUT", "/api/settings", {"auto_sync": True})
    st, state, _ = _call(port, "GET", "/api/state")
    assert st == 200
    for key in ("logged_in", "account", "accounts", "sync", "progress", "scheduler", "datadir"):
        assert key in state


def test_failed_filter_matches_any_non_completed(http_env):
    """失败筛选 = 一切非 completed (与统计口径一致), 不只是字面量 failed."""
    port = http_env["port"]
    db = http_env["db"]
    _seed(db, n=3)   # 1 条 status="error"
    st, recs, _ = _call(port, "GET", "/api/usage/records?status=failed")
    assert st == 200 and recs["total"] == 1
    assert recs["records"][0]["status"] == "error"
    st, recs, _ = _call(port, "GET", "/api/usage/records?status=completed")
    assert recs["total"] == 2
    st, recs, _ = _call(port, "GET", "/api/usage/records")
    assert recs["total"] == 3


def test_records_pagination_clamp_and_shape(http_env):
    port = http_env["port"]
    st, recs, _ = _call(port, "GET", "/api/usage/records?page=1&page_size=999")
    assert st == 200 and recs["page_size"] == 100      # 999 被夹到 100
    st, recs, _ = _call(port, "GET", "/api/usage/records?page=0&days=abc")
    assert st == 200 and recs["page"] == 1 and recs["filter"]["days"] is None


def test_dashboard_shape_and_account_scope(http_env):
    port = http_env["port"]
    st, dash, _ = _call(port, "GET", "/api/dashboard?range=all")
    assert st == 200
    for key in ("logged_in", "quota", "totals", "totals_source", "cache", "models",
                "daily", "trend", "today_trend", "sync", "auth_type", "exchange_rate"):
        assert key in dash
    assert dash["totals"]["request_count"] == 3
    assert dash["totals"]["failed_count"] == 1        # status="error" 也计失败
    assert dash["quota"]["success"] is True
    assert dash["models"][0]["hit_rate"] is None      # 无桶数据时 None (前端显示 —)
    st, dash, _ = _call(port, "GET", "/api/dashboard?range=bogus")
    assert dash["range"] == "30d"                     # 非法 range 回落 30d


def test_logout_guard_while_sync_running(http_env):
    port = http_env["port"]
    server = http_env["server"]
    db = http_env["db"]
    _seed(db, n=1)
    server._sync_state["running"] = True
    try:
        st, body, _ = _call(port, "POST", "/api/logout")
        assert st == 409
        st, body, _ = _call(port, "POST", "/api/accounts/delete", {"id": 9999})
        assert st == 409                # 同步进行中: 删除账号同样被守卫拦下
    finally:
        server._sync_state["running"] = False


def test_body_size_limit(http_env):
    """超过 1 MiB 的请求体 -> 400 (声明超大 Content-Length 不能阻塞 handler)."""
    port = http_env["port"]
    url = f"http://127.0.0.1:{port}/api/settings"
    req = urllib.request.Request(
        url, data=b"x", method="PUT",
        headers={"Content-Type": "application/json", "Content-Length": str(2 << 20)},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400
