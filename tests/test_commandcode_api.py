"""commandcode_api 纯逻辑测试: 解析 / 配额窗口 / 会话探测 / 游标翻页 (不触网)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import commandcode_api as capi


# ---------------------------------------------------------------------------
# 凭证规范化
# ---------------------------------------------------------------------------


def test_build_cookie_header_full_string():
    raw = "a=1; b=2; __Secure-commandcode_prod_.session_token=tok123"
    assert capi.build_cookie_header(raw) == raw


def test_build_cookie_header_prefix_stripped():
    assert capi.build_cookie_header("Cookie: a=1; b=2") == "a=1; b=2"


def test_build_cookie_header_bare_token_wrapped():
    out = capi.build_cookie_header("  tok123  ")
    assert out == f"{capi.SESSION_COOKIE_NAME}=tok123"


def test_build_cookie_header_empty():
    assert capi.build_cookie_header("") == ""
    assert capi.build_cookie_header("Cookie:") == ""


def test_has_session_cookie():
    assert capi.has_session_cookie(f"{capi.SESSION_COOKIE_NAME}=x")
    assert not capi.has_session_cookie("other=x")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def test_usage_page_url_personal_and_org():
    assert capi.usage_page_url("") == "https://commandcode.ai/settings/usage"
    assert capi.usage_page_url("alice") == "https://commandcode.ai/alice/settings/usage"
    assert capi.usage_page_url("/alice/") == "https://commandcode.ai/alice/settings/usage"


def test_usage_page_url_quotes_spaces():
    assert "ali%20ce" in capi.usage_page_url("ali ce")


def test_plan_info_known_and_unknown():
    go = capi.plan_info("individual-go")
    assert go == {"id": "individual-go", "name": "Individual Go", "monthly_credits": 10}
    assert capi.plan_info("NOPE")["monthly_credits"] is None
    assert capi.plan_info(" Individual-Pro ")["id"] == "individual-pro"


def test_ms_to_iso_variants():
    dt = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
    iso, remaining = capi._ms_to_iso(int(dt.timestamp() * 1000))
    assert iso.startswith(dt.strftime("%Y-%m-%dT%H"))
    assert remaining > 0
    # 秒级时间戳兼容 (< 1e11 视为秒)
    iso2, _ = capi._ms_to_iso(int(dt.timestamp()))
    assert iso2 == iso
    assert capi._ms_to_iso(0) == ("", 0)
    assert capi._ms_to_iso(-5) == ("", 0)
    assert capi._ms_to_iso("bad") == ("", 0)


# ---------------------------------------------------------------------------
# 用量记录解析
# ---------------------------------------------------------------------------


def _usage_raw(uid="u1", **over):
    meta = {
        "inputCost": 0.0117, "outputCost": 0.0345, "cacheCost": 0.0089,
        "totalCost": 0.0551, "traceId": "tr-1",
    }
    raw = {
        "id": uid,
        "createdAt": "2026-09-17T16:52:11Z",
        "model": "deepseek/x",
        "tokensIn": "117894",        # 上游给字符串数字
        "tokensOut": 8921,
        "durationTotal": "4512",
        "status": "completed",
        "mode": "agent",
        "type": "api",
        "meta": meta,
    }
    raw.update(over)
    return raw


def test_parse_usage_item_full():
    r = capi.parse_usage_item(_usage_raw())
    assert r.usg_id == "u1"
    assert r.model == "deepseek/x"
    assert r.input_tokens == 117894          # 字符串数字安全转 int
    assert r.output_tokens == 8921
    assert r.duration_ms == 4512
    assert r.cost_usd == 0.0551
    assert r.input_cost + r.output_cost + r.cache_cost == pytest.approx(0.0551, abs=1e-9)
    assert r.trace_id == "tr-1"


def test_parse_usage_item_missing_id_or_created_at():
    assert capi.parse_usage_item(_usage_raw(uid="")) is None
    assert capi.parse_usage_item(_usage_raw(createdAt="")) is None


def test_parse_usage_item_defaults():
    r = capi.parse_usage_item({"id": "u2", "createdAt": "2026-09-17T16:52:11Z"})
    assert r.model == "unknown"              # 缺模型回落 unknown
    assert r.input_tokens == 0
    assert r.cost_usd == 0.0
    assert r.status == ""


def test_parse_usage_page_skips_bad_rows():
    page = capi.parse_usage_page({
        "usages": [_usage_raw(), {"id": ""}],   # 缺 id 的坏行被跳过
        "nextCursor": "c1",
        "limit": 100,
        "window": {"days": 1, "entries": 100},
    })
    assert len(page.records) == 1
    assert page.has_more is True
    assert page.next_cursor == "c1"
    assert page.window_days == 1
    assert page.window_entries == 100


def test_parse_usage_page_no_cursor():
    page = capi.parse_usage_page({"usages": []})
    assert page.records == []
    assert page.has_more is False


# ---------------------------------------------------------------------------
# 图表桶解析
# ---------------------------------------------------------------------------


def _chart_raw(**over):
    raw = {
        "model": "m1", "timeBucket": "2026-09-17 16:50:00",
        "requests": 3, "tokensIn": "500", "tokensOut": 20, "tokensTotal": 520,
        "inputCost": 0.01, "outputCost": 0.02, "cacheCost": 0.003,
        "cacheSavings": 0.5, "totalCost": 0.033, "creditsTotal": 0.033,
        "consumedFreeCredits": 0.0, "consumedMonthlyCredits": 0.033,
        "consumedPurchasedCredits": 0.0, "consumedTotal": 0.033,
        "cacheReadInputTokens": "400", "cacheCreationInputTokens": 50,
    }
    raw.update(over)
    return raw


def test_parse_chart_row():
    b = capi.parse_chart_row(_chart_raw())
    assert b.bucket_key == "m1|2026-09-17 16:50:00"
    assert b.tokens_in == 500
    assert b.cache_read_tokens == 400        # 字符串数字安全转 int
    assert b.cache_creation_tokens == 50
    assert b.cache_savings == 0.5


def test_parse_chart_row_requires_model_and_bucket():
    assert capi.parse_chart_row({"model": "", "timeBucket": "x"}) is None
    assert capi.parse_chart_row({"model": "m", "timeBucket": ""}) is None


def test_fetch_chart_buckets_sends_iso_window():
    """from/to 必须是 ISO8601; 断言请求路径里带上正确的窗口参数."""
    captured = {}

    def fake_fetch(path, cred, auth_type="cookie", timeout=25.0, retries=3):  # noqa: ARG001
        captured["path"] = path
        return {"data": [_chart_raw()]}

    monkey_target = capi
    monkey_target._fetch = fake_fetch
    try:
        buckets = capi.fetch_chart_buckets(
            "cred", window_minutes=35,
            now=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
    finally:
        reload_module()
    assert len(buckets) == 1
    assert "from=2026-09-17T11%3A25%3A00Z" in captured["path"]
    assert "to=2026-09-17T12%3A00%3A00Z" in captured["path"]


def test_fetch_chart_buckets_empty_rows():
    capi._fetch = lambda *a, **k: {"data": []}
    try:
        assert capi.fetch_chart_buckets("cred") == []
    finally:
        reload_module()


# ---------------------------------------------------------------------------
# 配额解析
# ---------------------------------------------------------------------------


def _credits_payload(granted=100.0, remaining=60.0, purchased=5.0, free=2.0):
    return {
        "credits": {
            "monthlyCreditsGranted": granted,
            "monthlyCredits": remaining,
            "purchasedCredits": purchased,
            "freeCredits": free,
        },
        "windowLimits": {
            "fiveHour": {
                "used": 1.5, "cap": 10.0,
                "resetAt": int((datetime.now(timezone.utc) + timedelta(hours=3)).timestamp() * 1000),
            },
            "weekly": {"used": 12.0, "cap": 100.0, "resetAt": 0},
        },
    }


def test_parse_quota_windows():
    sub = {
        "planId": "individual-go", "status": "active",
        "currentPeriodEnd": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
    }
    q = capi.parse_quota(_credits_payload(), sub, name="alice", org_id="org1")
    assert q.success is True
    assert q.plan_name == "Individual Go"
    assert q.monthly_granted == 100.0
    assert q.monthly_remaining == 60.0
    assert q.purchased_remaining == 5.0
    assert q.free_remaining == 2.0
    assert q.total_remaining == 67.0   # monthly + purchased + free; 内部拆分不重复计入
    assert [w.label for w in q.windows] == ["5h", "Weekly", "Monthly"]
    five = q.windows[0]
    assert five.used == 1.5 and five.total == 10.0
    assert five.to_dict()["used_percent"] == 15.0   # used_percent 只在 to_dict 里
    assert five.reset_at != ""
    weekly = q.windows[1]
    assert weekly.reset_at == "" and weekly.reset_in_sec == 0


def test_parse_quota_granted_missing_falls_back_to_plan():
    payload = _credits_payload(granted=0, remaining=30.0)
    q = capi.parse_quota(payload, {"planId": "individual-goat"})   # goat = 70
    assert q.monthly_granted == 70.0
    assert q.monthly_granted_from_plan is True


def test_parse_quota_no_windows_when_limits_empty():
    q = capi.parse_quota({"credits": {}}, {})
    assert q.success is True
    assert q.windows == []
    assert q.total_remaining == 0.0


def test_fetch_quota_error_path():
    """凭证/网络失败 -> success=False 的 QuotaResult, 不抛异常."""
    def boom(*a, **k):
        raise capi.AuthError("登录无效或已过期, 请重新登录 (HTTP 401)")

    capi._fetch = boom
    try:
        q = capi.fetch_quota("ck")
        assert q.success is False
        assert "重新登录" in q.error
    finally:
        reload_module()


def test_fetch_quota_empty_credential():
    q = capi.fetch_quota("  ")
    assert q.success is False
    assert "未配置" in q.error


def test_fetch_session_info_paths():
    cases = [
        ({"session": {"expiresAt": "2026-12-01T00:00:00Z"}, "user": {"userName": "alice"}}, "ok"),
        (None, "expired"),                    # 未登录: 200 + 字面量 null
        ({"session": None, "user": None}, "expired"),   # 对象形态但 session 为空
        ({}, "expired"),                      # 空对象同上
        ({"session": {"expiresAt": ""}}, "expired"),    # 有 session 但缺 expiresAt
    ]
    for payload, expected in cases:
        capi._fetch = (lambda p: (lambda *a, **k: p))(payload)
        try:
            info = capi.fetch_session_info("ck")
            assert info.status == expected, (payload, info)
            if expected == "ok":
                assert info.expires_at == "2026-12-01T00:00:00Z"
                assert info.authenticated is True
        finally:
            reload_module()


def test_fetch_session_info_apikey_na():
    info = capi.fetch_session_info("sk-key", capi.AUTH_APIKEY)
    assert info.status == "na"


def test_fetch_session_info_network_error_is_not_expired():
    """网络失败必须报 error 而不是 expired: 探测失败不该让用户重登."""
    def boom(*a, **k):
        raise capi.CmdAPIError("网络错误")

    capi._fetch = boom
    try:
        info = capi.fetch_session_info("ck")
        assert info.status == "error"
        assert info.authenticated is False
    finally:
        reload_module()


# ---------------------------------------------------------------------------
# 游标翻页
# ---------------------------------------------------------------------------


def test_fetch_usage_all_single_page_when_no_cursor():
    payload = {"usages": [_usage_raw(uid=f"u{i}") for i in range(100)], "nextCursor": None}
    capi._fetch = lambda *a, **k: payload
    try:
        records, pages = capi.fetch_usage_all("ck", max_pages=5)
        assert pages == 1                      # 上游不回游标: 实际永远只跑 1 页
        assert len(records) == 100
    finally:
        reload_module()


def test_fetch_usage_all_follows_cursor_when_upstream_offers_it():
    payloads = [
        {"usages": [_usage_raw(uid="a1"), _usage_raw(uid="a2")], "nextCursor": "c2"},
        {"usages": [_usage_raw(uid="b1")], "nextCursor": ""},
    ]
    calls = []

    def fake_fetch(path, *a, **k):
        calls.append(path)
        return payloads[0] if "cursor" not in path else payloads[1]

    capi._fetch = fake_fetch
    try:
        records, pages = capi.fetch_usage_all("ck", max_pages=5)
        assert pages == 2
        assert [r.usg_id for r in records] == ["a1", "a2", "b1"]
        assert len(calls) == 2
    finally:
        reload_module()


def test_fetch_usage_all_respects_max_pages():
    def fake_fetch(path, *a, **k):
        return {"usages": [{"id": "x", "createdAt": "2026-01-01T00:00:00Z"}], "nextCursor": "always"}

    capi._fetch = fake_fetch
    try:
        records, pages = capi.fetch_usage_all("ck", max_pages=3)
        assert pages == 3                      # 防失控兜底生效
        assert len(records) == 3
    finally:
        reload_module()


def reload_module() -> None:
    """还原被测试替换的模块级 _fetch (有 monkeypatch 更优雅, 但这里 patch 的是
    模块属性本身, 用 importlib 还原最直接)."""
    import importlib

    importlib.reload(capi)
