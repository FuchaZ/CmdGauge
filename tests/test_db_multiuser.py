"""db.py 多账号数据层测试: 账号 CRUD / 隔离查询 / 级联删除 / 聚合统计 / 设置."""
from __future__ import annotations

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置连接 (连接按线程隔离, 用 close_db 清空)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db.close_db()
    yield tmp_path
    db.close_db()


def _rec(usg_id, created="2026-01-01T00:00:00Z", model="m", inp=10, outp=20,
         cost_usd=0.5, status="completed", duration_ms=1000):
    """Command Code 风格的用量记录 (字段与 commandcode_api.UsageRecord.to_db_dict 对齐)."""
    return {
        "usg_id": usg_id, "created_at": created, "model": model,
        "input_tokens": inp, "output_tokens": outp, "duration_ms": duration_ms,
        "status": status, "mode": "agent", "type": "api",
        "input_cost": cost_usd * 0.2, "output_cost": cost_usd * 0.6,
        "cache_cost": cost_usd * 0.2, "cost_usd": cost_usd, "trace_id": None,
    }


def test_fresh_seed(tmp_db):
    """全新库种子一个空账号 (id=1, 未登录)."""
    accounts = db.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["id"] == 1
    assert accounts[0]["has_token"] is False
    assert accounts[0]["login"] == ""
    assert db.count_logged_in_accounts() == 0
    assert db.get_active_account_id() == 1


def test_add_and_dedup_by_token(tmp_db):
    """同一 cookie 重复登录视为同一账号, 只更新身份信息."""
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-a", login="alice2")
    assert a1 == a2
    assert db.count_accounts() == 2  # 含种子空账号
    assert db.get_account()["login"] == "alice2"
    a3 = db.add_account("cookie-b", login="bob")
    assert a3 != a1
    assert db.get_active_account_id() == a3


def test_switch_persists_across_reopen(tmp_db):
    """活跃账号写入 settings.payload, 重开连接后仍生效."""
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-b", login="bob")
    db.set_active_account(a1)
    db.close_db()
    assert db.get_active_account_id() == a1
    assert db.set_active_account(a2) is True
    assert db.set_active_account(9999) is False


def test_active_prefers_logged_in(tmp_db):
    """活跃账号未登录时让位给已登录账号."""
    guest = db.add_account("", login="")          # 有账号行但无凭证
    logged = db.add_account("cookie-a", login="alice")
    db.set_active_account(guest)
    # 该账号未登录 -> 自动让位
    assert db.get_active_account_id() == logged


def test_rename_clamp_strip(tmp_db):
    aid = db.add_account("cookie-a", login="alice")
    assert db.rename_account(aid, "  x  ") is True
    assert db.get_account()["name"] == "x"
    assert db.rename_account(aid, "   ") is False   # 全空 -> 拒绝
    assert db.rename_account(aid, "y" * 80) is True
    assert len(db.get_account()["name"]) == 50      # 截断到 50


def test_save_token_targets_active_only(tmp_db):
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-b", login="bob")
    db.set_active_account(a1)
    db.save_token("cookie-new", "alice-new", "")
    t1, login1, _, at1 = db.get_account_credentials(a1)
    t2, login2, _, at2 = db.get_account_credentials(a2)
    assert (t1, login1) == ("cookie-new", "alice-new")
    assert (t2, login2) == ("cookie-b", "bob")      # 未受影响
    assert (at1, at2) == ("cookie", "cookie")       # 默认仍是 cookie 模式


def test_account_auth_type(tmp_db):
    """认证类型: 默认 cookie, 可存 apikey, 切换账号/重登时保持各自的值."""
    a1 = db.add_account("ck-cookie", login="alice")
    a2 = db.add_account("sk-key", login="bob", auth_type="apikey")
    assert db.get_account_credentials(a1)[3] == "cookie"
    assert db.get_account_credentials(a2)[3] == "apikey"
    assert next(a for a in db.list_accounts() if a["id"] == a2)["auth_type"] == "apikey"
    # 重新登录 active (a2) 换成 cookie 模式
    db.save_token("ck-cookie2", "bob", "", "cookie")
    assert db.get_account_credentials(a2)[3] == "cookie"
    assert db.get_account_credentials(a1)[3] == "cookie"
    # 同凭证去重时应刷新认证类型
    assert db.add_account("ck-cookie", login="alice", auth_type="apikey") == a1
    assert db.get_account_credentials(a1)[3] == "apikey"


def test_usage_buckets_cache_stats(tmp_db):
    """5 分钟聚合桶: 覆盖式 upsert / 缓存口径 / 账号隔离."""
    a1 = db.add_account("ck1", login="alice")
    a2 = db.add_account("ck2", login="bob")

    def bucket(model, ts, tin=100, cr=80, req=1, savings=0.5):
        return {
            "bucket_key": f"{model}|{ts}", "model": model, "provider": "p",
            "time_bucket": ts, "requests": req,
            "tokens_in": tin, "tokens_out": 10, "tokens_total": tin + 10,
            "input_cost": 0.002, "output_cost": 0.006, "cache_cost": 0.002,
            "cache_savings": savings, "total_cost": 0.01, "credits_total": 0.01,
            "consumed_free": 0.0, "consumed_monthly": 0.01, "consumed_purchased": 0.0,
            "consumed_total": 0.01, "cache_read_tokens": cr, "cache_creation_tokens": 0,
        }

    assert db.insert_usage_buckets([bucket("m/a", "2026-09-17 16:50:00")], a1) == 1
    assert db.insert_usage_buckets([bucket("m/a", "2026-09-17 16:50:00")], a1) == 0  # 同桶不新增
    # 同桶累计值应被覆盖而非累加
    db.insert_usage_buckets([bucket("m/a", "2026-09-17 16:50:00", req=5, tin=999, cr=900)], a1)
    st = db.cache_stats("all", a1)
    assert (st["requests"], st["tokens_in"], st["cache_read_tokens"]) == (5, 999, 900), st
    assert st["hit_rate"] == round(900 / 999 * 100, 2)
    assert st["miss_tokens"] == 99
    assert st["bucket_count"] == 1

    # 账号隔离 (主键含 account_id, 同 model+桶不互相覆盖)
    db.insert_usage_buckets([bucket("m/a", "2026-09-17 16:50:00", tin=7, cr=7)], a2)
    assert db.cache_stats("all", a1)["tokens_in"] == 999
    assert db.cache_stats("all", a2)["tokens_in"] == 7

    # 空账号零值口径
    a3 = db.add_account("ck3", login="carol")
    assert db.cache_stats("all", a3)["hit_rate"] == 0.0
    assert db.cache_stats("all", a3)["bucket_count"] == 0

    # 按模型 + prune 同步清理
    db.insert_usage_buckets([bucket("m/b", "2026-09-17 16:55:00", tin=50, cr=25)], a1)
    mc = {m["model"]: m for m in db.model_cache_stats("all", a1)}
    assert mc["m/a"]["hit_rate"] == round(900 / 999 * 100, 2)
    assert mc["m/b"]["hit_rate"] == 50.0
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_usage_buckets([bucket("m/old", old, tin=1, cr=1)], a1)
    assert db.cache_stats("all", a1)["bucket_count"] == 3
    db.prune_old_records(30, a1)
    assert db.cache_stats("all", a1)["bucket_count"] == 2


def test_query_isolation_between_accounts(tmp_db):
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-b", login="bob")
    db.insert_usage_records([_rec("u1"), _rec("u2", inp=100)], a1)
    db.insert_usage_records([_rec("u3", inp=7)], a2)
    assert db.totals("all", a1)["request_count"] == 2
    assert db.totals("all", a2)["request_count"] == 1
    assert db.totals("all", a1)["total_input_tokens"] == 110
    assert db.totals("all", a2)["total_input_tokens"] == 7
    # 活跃账号默认取 a2
    assert db.totals("all")["request_count"] == 1


def test_delete_cascades_and_fallback(tmp_db):
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-b", login="bob")
    db.insert_usage_records([_rec("u1"), _rec("u2")], a2)
    remaining = db.delete_account(a2)
    assert remaining == db.count_accounts()
    assert db.totals("all", a2)["request_count"] == 0
    # 活跃账号被删 -> 回落到剩余账号
    assert db.get_active_account_id() == a1


def test_delete_last_account_safe(tmp_db):
    """删光账号不应崩溃; 无账号时活跃 id 为 0."""
    for acc in db.list_accounts():
        db.delete_account(acc["id"])
    assert db.count_accounts() == 0
    assert db.get_active_account_id() == 0
    assert db.get_account() == {}
    assert db.get_token() == ""


def test_clear_account_scoped_to_active(tmp_db):
    a1 = db.add_account("cookie-a", login="alice")
    a2 = db.add_account("cookie-b", login="bob")
    db.insert_usage_records([_rec("u1")], a1)
    db.insert_usage_records([_rec("u2")], a2)
    db.set_active_account(a1)
    db.clear_account()
    assert db.get_account_credentials(a1)[0] == ""       # a1 凭证已被清空
    assert db.totals("all", a1)["request_count"] == 0    # a1 本地数据被清
    assert db.totals("all", a2)["request_count"] == 1    # 另一个账号不受影响
    # 活跃账号按设计让位给仍登录的 a2
    assert db.get_active_account_id() == a2


def test_insert_dedup_counts(tmp_db):
    """按 usg_id upsert: 重复插入不计新增, 但字段会被刷新."""
    a = db.add_account("cookie-a", login="alice")
    assert db.insert_usage_records([_rec("u1"), _rec("u2")], a) == 2
    assert db.insert_usage_records([_rec("u1"), _rec("u2")], a) == 0
    assert db.insert_usage_records([_rec("u1", cost_usd=9.9), _rec("u3")], a) == 1
    recs, total = db.usage_records_page(1, 10, account_id=a)
    assert total == 3
    assert next(r for r in recs if r["usg_id"] == "u1")["cost_usd"] == 9.9


def test_settings_roundtrip_preserves_extras(tmp_db):
    assert db.get_settings()["window_days"] == 60
    out = db.save_settings({"sync_interval_sec": 900, "window_days": None})
    assert out["sync_interval_sec"] == 900
    assert out["window_days"] is None
    # 非白名单键 (如 active_account_id) 不被覆盖丢失
    db.add_account("cookie-a", login="alice")
    active = db.get_active_account_id()
    db.save_settings({})
    assert db.get_active_account_id() == active
    # 越界值被夹紧 (合法区间 30..3600)
    assert db.save_settings({"sync_interval_sec": 10})["sync_interval_sec"] == 30
    assert db.save_settings({"sync_interval_sec": 99})["sync_interval_sec"] == 99
    assert db.save_settings({"sync_interval_sec": 99999})["sync_interval_sec"] == 3600
    # window_days: None 表示不裁剪 (前端「所有」按钮)
    assert db.save_settings({"window_days": "all"})["window_days"] is None
    assert db.save_settings({"window_days": 99999})["window_days"] == 3650


def test_aggregations(tmp_db):
    """totals / model_stats / daily_stats / today_trend / day_stats_page 口径."""
    a = db.add_account("cookie-a", login="alice")
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    today = now.isoformat().replace("+00:00", "Z")
    old = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    db.insert_usage_records([
        _rec("u1", created=today, model="deepseek/x", inp=100, outp=50, cost_usd=0.3),
        _rec("u2", created=today, model="deepseek/x", inp=10, outp=5, cost_usd=0.2, status="failed"),
        _rec("u3", created=old, model="kimi/y", inp=7, outp=3, cost_usd=0.1),
    ], a)

    t = db.totals("all", a)
    assert t["request_count"] == 3
    assert t["failed_count"] == 1
    assert t["success_rate"] == round(2 / 3 * 100, 2)
    assert t["total_input_tokens"] == 117
    assert t["total_output_tokens"] == 58
    assert t["total_tokens"] == 175
    assert abs(t["total_cost_usd"] - 0.6) < 1e-9
    assert t["model_count"] == 2

    ms = db.model_stats("all", a)
    assert [m["model"] for m in ms] == ["deepseek/x", "kimi/y"]   # 按成本降序
    assert ms[0]["request_count"] == 2

    # 近 7 天不含 10 天前的记录
    assert db.totals("7d", a)["request_count"] == 2

    daily = db.daily_stats(7, a)
    assert len(daily) == 7
    assert daily[-1]["date"] == datetime.now().strftime("%Y-%m-%d")

    trend = db.today_trend(a)
    assert len(trend) == 24
    assert sum(x["requests"] for x in trend) == 2

    days, dtot = db.day_stats_page(1, 10, account_id=a)
    assert dtot == 2                                  # 两个不同日期
    assert days[0]["day"] >= days[1]["day"]           # 倒序
    assert days[0]["model_count"] == 1


def test_prune_and_models_list(tmp_db):
    a = db.add_account("cookie-a", login="alice")
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = now.isoformat().replace("+00:00", "Z")
    old = (now - timedelta(days=100)).isoformat().replace("+00:00", "Z")
    db.insert_usage_records([_rec("u1", created=recent), _rec("u2", created=old, model="old/m")], a)
    assert db.prune_old_records(30, a) == 1
    assert db.totals("all", a)["request_count"] == 1
    assert "old/m" not in db.list_models(a)
    assert db.prune_old_records(None, a) == 0         # None = 不裁剪


def test_records_page_filters(tmp_db):
    a = db.add_account("cookie-a", login="alice")
    db.insert_usage_records([
        _rec("u1", model="alpha"), _rec("u2", model="beta"),
        _rec("u3", model="beta", status="failed"),
    ], a)
    recs, total = db.usage_records_page(1, 10, model="beta", account_id=a)
    assert total == 2
    recs, total = db.usage_records_page(1, 10, status="failed", account_id=a)
    assert total == 1 and recs[0]["usg_id"] == "u3"
    assert sorted(db.list_models(a)) == ["alpha", "beta"]
