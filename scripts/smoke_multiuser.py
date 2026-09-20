"""多用户功能端到端冒烟测试 (无 GUI).

起真实 HTTP 服务 (随机端口), 用临时数据目录, 通过 API 断言多账号全流程:
账号列表/重命名/切换/删除(级联)/退出登录(移除行)/活跃偏好已登录/dashboard
按活跃账号过滤/守卫响应码. 配额接口打桩, 不触网.

运行: python scripts/smoke_multiuser.py   (退出码 0 = 全部通过)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp(prefix="cmdgauge-smoke-")
os.environ["CMDGAUGE_DATA"] = _tmpdir  # 必须在 app.db 首次连接前生效

from app import db, server  # noqa: E402
from app.commandcode_api import QuotaResult  # noqa: E402


def _fake_quota(cred=None, auth_type="cookie", org_id=None, name="Default",  # noqa: ARG001
                target_user_id=None):
    """配额打桩: 避免冒烟测试访问外网.

    注意 server 侧走的是 ``fetch_quota_any`` (按 auth_type 分派), 因此必须替换
    这个名字, 替换 ``fetch_quota`` 不会生效。
    """
    return QuotaResult(name=name or "Default", success=True, updated_at="", windows=[])


server.fetch_quota_any = _fake_quota


def call(method: str, path: str, body: dict | None = None):
    """请求本地服务, 返回 (status, json)."""
    url = f"http://{_host}:{_port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            payload = {}
        return exc.code, payload


PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _rec(usg_id, inp=10):
    return {
        "usg_id": usg_id, "created_at": "2026-08-01T00:00:00Z", "model": "m1",
        "input_tokens": inp, "output_tokens": 5, "duration_ms": 800,
        "status": "completed", "mode": "agent", "type": "api",
        "input_cost": 0.02, "output_cost": 0.06, "cache_cost": 0.02,
        "cost_usd": 0.1, "trace_id": None,
    }


def main() -> int:
    global _host, _port
    # with_scheduler=False: 调度线程会真实访问上游, 冒烟测试必须隔离掉
    _host, _port = server.start_server(port=0, with_scheduler=False)
    print(f"server at {_host}:{_port}, data={_tmpdir}")

    # 1. 全新库初始态
    st, st_body = call("GET", "/api/state")
    check("state 200", st == 200)
    check("fresh logged_in=False", st_body.get("logged_in") is False)
    check("fresh accounts_total==1", st_body.get("accounts_total") == 1)
    check("state has accounts list", isinstance(st_body.get("accounts"), list))
    check("state has usage_page_url", st_body.get("usage_page_url", "").startswith("https://commandcode.ai/"))
    st, acc = call("GET", "/api/accounts")
    check("accounts list ok", st == 200 and acc.get("ok") is True and acc.get("active_id") == 1)
    st, r = call("POST", "/api/sync?mode=incremental")
    check("sync guard 401 when none logged in", st == 401)

    # 2. 重命名种子账号 + 守卫
    st, r = call("POST", "/api/accounts/rename", {"id": 1, "name": "  主号 "})
    check("rename ok+stripped", st == 200 and r.get("ok") is True)
    st, r = call("POST", "/api/accounts/rename", {"id": 9999, "name": "x"})
    check("rename bogus id -> 400", st == 400)

    # 3. 添加账号 / 去重 / 切换守卫
    a2 = db.add_account("cookie-b", "userb", switch=True)
    a3 = db.add_account("cookie-c", "userc", switch=True)
    db.insert_usage_records([_rec("b1"), _rec("b2")], account_id=a2)
    db.insert_usage_records([_rec("c1", inp=99)], account_id=a3)
    dup = db.add_account("cookie-b", "userb", switch=True)
    check("add dedup reactivates existing", dup == a2 and db.get_active_account_id() == a2)
    db.set_active_account(a3)
    st, r = call("POST", "/api/accounts/switch", {"id": 1})
    check("switch tokenless -> 400", st == 400, str(r))
    st, r = call("POST", "/api/accounts/switch", {"id": 424242})
    check("switch bogus id -> 404", st == 404)

    # 4. dashboard 反映活跃账号 userc
    st, dash = call("GET", "/api/dashboard?range=all")
    check("dashboard 200", st == 200)
    check("dashboard active filter (userc)", dash["totals"]["request_count"] == 1, str(dash["totals"]))
    check("dashboard account_name==userc", dash.get("account_name") == "userc")
    check("dashboard counts 2/3", dash.get("accounts_logged_in") == 2 and dash.get("accounts_total") == 3)
    check("dashboard has new metric keys",
          all(k in dash["totals"] for k in ("success_rate", "cache_cost_ratio", "avg_duration_ms", "total_tokens")))
    check("quota stubbed ok when logged in", bool(dash.get("quota")) and dash["quota"].get("success") is True)

    # 5. 切到 userb
    st, r = call("POST", "/api/accounts/switch", {"id": a2})
    check("switch ok", st == 200 and r.get("ok") is True)
    st, dash = call("GET", "/api/dashboard?range=all")
    check("dashboard follows switch (userb)",
          dash["totals"]["request_count"] == 2 and dash.get("account_name") == "userb")

    # 6. 删除 userb (级联): 活跃自动回落到已登录的 userc
    st, r = call("POST", "/api/accounts/delete", {"id": a2})
    check("delete ok remaining==2", st == 200 and r.get("remaining") == 2, str(r))
    st, dash = call("GET", "/api/dashboard?range=all")
    check("active falls back to logged-in userc",
          dash["totals"]["request_count"] == 1 and dash.get("account_name") == "userc")

    # 7. 每日用量 / 使用记录 接口
    st, days = call("GET", "/api/usage/days?page=1&page_size=10")
    check("usage/days 200", st == 200 and days.get("total", 0) >= 1, str(days)[:120])
    check("usage/days has metrics",
          days["records"] and "success_rate" in days["records"][0] and "day" in days["records"][0])
    st, recs = call("GET", "/api/usage/records?page=1&page_size=10")
    check("usage/records 200", st == 200 and recs.get("total") == 1)
    check("usage/records has duration/status",
          recs["records"] and "duration_ms" in recs["records"][0] and "status" in recs["records"][0])
    st, recs0 = call("GET", "/api/usage/records?status=failed")
    check("usage/records status filter", st == 200 and recs0.get("total") == 0)

    # 8. 退出登录当前账号 (=移除行): 全部退完 -> logged_in False / 回欢迎页条件成立
    st, r = call("POST", "/api/logout")
    check("logout ok", st == 200 and r.get("ok") is True)
    st, st2 = call("GET", "/api/state")
    check("all logged out state", st2.get("logged_in") is False and st2.get("accounts_logged_in") == 0)
    st, dash = call("GET", "/api/dashboard?range=all")
    check("dashboard empty after logout-all", dash["totals"]["request_count"] == 0)
    check("quota None after logout-all", dash.get("quota") is None)
    st, r = call("POST", "/api/sync?mode=full")
    check("full sync guard 401 when none logged in", st == 401)

    # 9. add 路由在无窗口环境返回 opened=False 且不崩溃
    st, r = call("POST", "/api/accounts/add", {})
    check("accounts/add no-window ok", st == 200 and r.get("opened") is False)

    # 10. settings PUT 不破坏 active_account_id
    a4 = db.add_account("cookie-d", "userd", switch=True)
    st, r = call("PUT", "/api/settings", {"sync_interval_sec": 60})
    check("settings put ok", st == 200 and r.get("sync_interval_sec") == 60)
    check("active_account_id preserved", db.get_active_account_id() == a4)

    # 11. 账户总览 (此时仅 userd 持有效凭证: userc 已在第 8 步退出登录)
    st, ov = call("GET", "/api/accounts/overview")
    check("accounts/overview 200", st == 200)
    check("overview only logged-in",
          all(a["logged_in"] for a in ov["accounts"]) and len(ov["accounts"]) == 1,
          f"got {len(ov['accounts'])}")
    check("overview card fields",
          all(k in ov["accounts"][0] for k in ("today", "today_trend", "daily7", "login", "active")))

    # 12. 错误路径
    st, _ = call("POST", "/api/sync?mode=nope")
    check("bad sync mode -> 400", st == 400)
    st, _ = call("GET", "/api/definitely-not-a-route")
    check("unknown api route -> 404", st == 404)

    # 13. 调度器: 配额刷新覆盖**全部**已登录账号 (旧实现只刷活跃账号)
    server._quota_cache.clear()
    refreshed = server._refresh_all_quotas()
    logged_in_ids = {a["id"] for a in db.list_accounts() if a["has_token"]}
    check("scheduler refreshes every logged-in account",
          refreshed == len(logged_in_ids) and set(server._quota_cache) == logged_in_ids,
          f"refreshed={refreshed} cache={set(server._quota_cache)} want={logged_in_ids}")
    check("scheduler settings follow db settings", server._scheduler_settings() == (True, 60),
          str(server._scheduler_settings()))
    st, stx = call("GET", "/api/state")
    check("state exposes scheduler snapshot",
          isinstance(stx.get("scheduler"), dict) and "last_sync_at" in stx["scheduler"],
          str(stx.get("scheduler"))[:120])

    print(f"\nresult: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        server.stop_server()
        db.close_db()
    sys.exit(code)
