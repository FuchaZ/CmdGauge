"""Command Code API 客户端.

两种能力:
1. 用量记录 (usage): ``/internal/usage`` 分页拉取请求级明细
2. 配额/账单 (quota): ``/internal/billing/credits`` + ``/internal/billing/subscriptions``

认证方式: 浏览器 **session cookie** (domain ``.commandcode.ai``), 由 auth.py 的
WebView 登录窗口捕获后交给本模块。所有 ``/internal/*`` 端点均以 cookie 认证
(实测: 仅带 cookie 即可, 无需 Origin/CSRF token; ``/alpha/*`` 另走 Bearer API Key,
本应用不使用)。

服务端能力边界 (实测):
- ``/internal/usage`` 硬限制 ``window = {days: 1, entries: 100}``, 且
  ``days`` / ``since`` / ``window`` / ``range`` / ``period`` 参数一律被忽略;
  ``limit`` 上限 100, 超出返回 400。→ 单次最多最近 1 天 100 条,
  长期历史靠"增量同步 + 本地累积"获得。
- ``/internal/usage/charts`` 对个人(无组织)账号恒返回空数组。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_BASE = "https://api.commandcode.ai"
SITE_BASE = "https://commandcode.ai"
SIGNIN_URL = f"{SITE_BASE}/signin"

PATH_USAGE = "/internal/usage"
PATH_USAGE_SUMMARY = "/internal/usage/summary"
PATH_USAGE_CHARTS = "/internal/usage/charts"
PATH_CREDITS = "/internal/billing/credits"
PATH_SUBSCRIPTIONS = "/internal/billing/subscriptions"
PATH_ORGS = "/internal/orgs"
PATH_MODELS = "/internal/models"
PATH_PROFILE = "/internal/profile/{login}"

# /alpha/* 端点: 官方 CLI 使用, 仅接受 Authorization: Bearer <apiKey>
PATH_ALPHA_WHOAMI = "/alpha/whoami"
PATH_ALPHA_SUMMARY = "/alpha/usage/summary"
PATH_ALPHA_CREDITS = "/alpha/billing/credits"
PATH_ALPHA_SUBSCRIPTIONS = "/alpha/billing/subscriptions"

# 认证类型
AUTH_COOKIE = "cookie"  # 浏览器会话 cookie (默认; /internal/* 全线可用)
AUTH_APIKEY = "apikey"  # Bearer API Key (仅 /alpha/* 有效)

# better-auth 在本站使用的 cookie 前缀 (实测, 见 DESIGN.md)
SESSION_COOKIE_NAME = "__Secure-commandcode_prod_.session_token"
SESSION_DATA_COOKIE_NAME = "__Secure-commandcode_prod_.session_data"
COOKIE_DOMAIN = ".commandcode.ai"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 25.0
MAX_BODY_BYTES = 8 << 20  # 8 MiB
FETCH_RETRIES = 3  # 网络抖动重试次数
RETRY_BACKOFF = (0.5, 1.5, 3.0)

PAGE_SIZE_MAX = 100  # 服务端硬上限
MAX_FETCH_PAGES = 20  # 单次同步最多翻页数 (防失控)

# planId -> 可读名称 / 月度额度.
# 额度来自社区从官方 CLI 逆推的映射 (未被官方文档化), **仅用于展示**;
# 真实额度一律以上游 monthlyCreditsGranted 为准 (实测 individual-go = 10 与之吻合)。
PLAN_INFO: dict[str, dict[str, Any]] = {
    "individual-go": {"name": "Individual Go", "monthly_credits": 10},
    "individual-goat": {"name": "Individual GOAT", "monthly_credits": 70},
    "individual-pro": {"name": "Individual Pro", "monthly_credits": 30},
    "individual-pro-v1": {"name": "Individual Pro", "monthly_credits": 80},
    "individual-provider": {"name": "Individual Provider", "monthly_credits": 15},
    "individual-max": {"name": "Individual Max", "monthly_credits": 150},
    "individual-ultra": {"name": "Individual Ultra", "monthly_credits": 300},
    "teams-pro": {"name": "Teams Pro", "monthly_credits": 40},
}


def plan_info(plan_id: str) -> dict[str, Any]:
    """把上游 planId 映射为可读套餐信息; 未知套餐原样回显."""
    pid = (plan_id or "").strip().lower()
    info = PLAN_INFO.get(pid)
    if info:
        return {"id": pid, **info}
    return {"id": pid, "name": pid or "", "monthly_credits": None}


class CmdAPIError(Exception):
    """Command Code API 调用失败."""


class AuthError(CmdAPIError):
    """认证失败 (cookie 无效/过期)."""


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> int:
    """把接口返回的字符串数字 (如 tokensIn: "117894") 安全转 int."""
    if value is None:
        return 0
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class UsageRecord:
    """一条请求级用量记录 (对应 /internal/usage 的 usages[] 项)."""

    usg_id: str
    created_at: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    status: str
    mode: str
    type: str
    input_cost: float
    output_cost: float
    cache_cost: float
    cost_usd: float
    trace_id: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_db_dict(self) -> dict[str, Any]:
        return {
            "usg_id": self.usg_id,
            "created_at": self.created_at,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "mode": self.mode,
            "type": self.type,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "cache_cost": self.cache_cost,
            "cost_usd": self.cost_usd,
            "trace_id": self.trace_id,
        }


@dataclass
class UsagePage:
    """一页用量记录."""

    records: list[UsageRecord] = field(default_factory=list)
    next_cursor: str = ""
    limit: int = PAGE_SIZE_MAX
    period_basis: str = ""
    window_days: int = 0
    window_entries: int = 0

    @property
    def has_more(self) -> bool:
        return bool(self.next_cursor)


@dataclass
class QuotaWindow:
    """一个额度窗口 (5 小时 / 每周 / 每月)."""

    label: str
    used: float  # 已用金额 (USD)
    total: float  # 窗口额度 (USD)
    remaining: float
    unit: str = "USD"
    reset_at: str = ""  # ISO8601, "" 表示接口未给出
    reset_in_sec: int = 0
    exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        pct = (self.used / self.total * 100.0) if self.total > 0 else 0.0
        return {
            "label": self.label,
            "used": round(self.used, 6),
            "total": round(self.total, 6),
            "remaining": round(self.remaining, 6),
            "unit": self.unit,
            "used_percent": round(max(0.0, min(100.0, pct)), 2),
            "remaining_percent": round(max(0.0, min(100.0, 100.0 - pct)), 2),
            "reset_at": self.reset_at,
            "reset_in_sec": self.reset_in_sec,
            "exceeded": self.exceeded,
        }


@dataclass
class QuotaResult:
    """账号配额 + 订阅概览 (供首页配额卡片使用)."""

    name: str = "Default"
    org_id: str = ""
    success: bool = False
    updated_at: str = ""
    plan_id: str = ""
    plan_name: str = ""
    plan_status: str = ""
    plan_monthly_credits: Optional[float] = None
    period_start: str = ""
    period_end: str = ""
    days_left: Optional[int] = None
    monthly_granted: float = 0.0
    monthly_granted_from_plan: bool = False  # 额度是否由套餐映射回退而来
    monthly_remaining: float = 0.0
    purchased_remaining: float = 0.0
    free_remaining: float = 0.0
    total_remaining: float = 0.0
    windows: list[QuotaWindow] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "org_id": self.org_id,
            "success": self.success,
            "updated_at": self.updated_at,
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "plan_status": self.plan_status,
            "plan_monthly_credits": self.plan_monthly_credits,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "days_left": self.days_left,
            "monthly_granted": round(self.monthly_granted, 6),
            "monthly_granted_from_plan": self.monthly_granted_from_plan,
            "monthly_remaining": round(self.monthly_remaining, 6),
            "purchased_remaining": round(self.purchased_remaining, 6),
            "free_remaining": round(self.free_remaining, 6),
            "total_remaining": round(self.total_remaining, 6),
            "windows": [w.to_dict() for w in self.windows],
        }
        if self.error:
            payload["error"] = self.error
        return payload


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_cookie_header(raw: str) -> str:
    """把用户粘贴的凭证规范化为 Cookie 头.

    支持三种输入:
    - 完整 Cookie 串 (含 ``name=value; ...``): 原样(去掉空段)使用
    - ``Cookie: xxx`` 前缀: 去掉前缀
    - 裸 session token (无 ``=``): 包装为 ``<SESSION_COOKIE_NAME>=<token>``
    """
    value = (raw or "").strip()
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if not value:
        return ""
    if "=" not in value:
        return f"{SESSION_COOKIE_NAME}={value}"
    parts = [p.strip() for p in value.split(";") if p.strip()]
    return "; ".join(parts)


def has_session_cookie(cookie: str) -> bool:
    """判断 cookie 串里是否含关键 session cookie."""
    return SESSION_COOKIE_NAME in (cookie or "")


def _auth_headers(cred: str, auth_type: str = "cookie") -> dict[str, str]:
    """按认证类型构造认证头.

    - ``cookie``: 浏览器会话 cookie (``/internal/*`` 全线可用; ``/alpha/*`` 服务端
      也接受, 但其 CORS 不允许凭据, 所以官网自己从不这样调)
    - ``apikey``: ``Authorization: Bearer <key>`` (仅 ``/alpha/*`` 有效)
    """
    value = (cred or "").strip()
    if not value:
        return {}
    if auth_type == AUTH_APIKEY:
        return {"Authorization": f"Bearer {value}"}
    header = build_cookie_header(value)
    return {"Cookie": header} if header else {}


def _fetch(
    path: str,
    cred: str,
    auth_type: str = AUTH_COOKIE,
    timeout: float = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
) -> Any:
    """请求 api.commandcode.ai 并解析 JSON, 返回 dict/list."""
    auth = _auth_headers(cred, auth_type)
    if not auth:
        raise CmdAPIError("凭证为空")
    url = API_BASE + path
    headers = {
        **auth,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Origin": SITE_BASE,
        "Referer": f"{SITE_BASE}/",
    }
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except ValueError as exc:
                raise CmdAPIError(f"响应不是合法 JSON: {body[:200]}") from exc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                kind = "API Key" if auth_type == AUTH_APIKEY else "登录"
                raise AuthError(f"{kind} 无效或已过期, 请重新登录 (HTTP {exc.code})") from exc
            if exc.code == 400:
                raise CmdAPIError(f"请求参数无效 (HTTP 400): {path}") from exc
            if exc.code >= 500 and attempt < retries - 1:
                last_exc = exc
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
                continue
            raise CmdAPIError(f"请求返回 HTTP {exc.code}: {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
                continue
            reason = getattr(exc, "reason", exc)
            raise CmdAPIError(f"网络错误: {reason}") from exc
    raise CmdAPIError(f"网络错误: {last_exc}") from last_exc


def _with_query(path: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", 0)}
    if not clean:
        return path
    return f"{path}?{urllib.parse.urlencode(clean)}"


# ---------------------------------------------------------------------------
# 用量记录
# ---------------------------------------------------------------------------


def parse_usage_item(raw: dict[str, Any]) -> Optional[UsageRecord]:
    """把一条 usages[] 项解析为 UsageRecord; 缺 id/createdAt 时返回 None."""
    usg_id = str(raw.get("id") or "").strip()
    created_at = str(raw.get("createdAt") or "").strip()
    if not usg_id or not created_at:
        return None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    return UsageRecord(
        usg_id=usg_id,
        created_at=created_at,
        model=str(meta.get("model") or raw.get("model") or "").strip() or "unknown",
        input_tokens=_to_int(raw.get("tokensIn")),
        output_tokens=_to_int(raw.get("tokensOut")),
        duration_ms=_to_int(raw.get("durationTotal")),
        status=str(raw.get("status") or "").strip(),
        mode=str(raw.get("mode") or "").strip(),
        type=str(raw.get("type") or "").strip(),
        input_cost=_to_float(meta.get("inputCost")),
        output_cost=_to_float(meta.get("outputCost")),
        cache_cost=_to_float(meta.get("cacheCost")),
        cost_usd=_to_float(meta.get("totalCost")),
        trace_id=str(meta.get("traceId") or "").strip(),
    )


def parse_usage_page(payload: dict[str, Any]) -> UsagePage:
    """解析 /internal/usage 响应."""
    usages = payload.get("usages")
    records: list[UsageRecord] = []
    if isinstance(usages, list):
        for item in usages:
            if isinstance(item, dict):
                rec = parse_usage_item(item)
                if rec is not None:
                    records.append(rec)
    window = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    return UsagePage(
        records=records,
        next_cursor=str(payload.get("nextCursor") or ""),
        limit=_to_int(payload.get("limit")) or PAGE_SIZE_MAX,
        period_basis=str(payload.get("periodBasis") or ""),
        window_days=_to_int(window.get("days")),
        window_entries=_to_int(window.get("entries")),
    )


def fetch_usage_page(
    cookie: str,
    cursor: Optional[str] = None,
    limit: int = PAGE_SIZE_MAX,
    org_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
) -> UsagePage:
    """拉取一页用量记录 (limit 上限 100)."""
    path = _with_query(
        PATH_USAGE,
        {
            "limit": max(1, min(int(limit), PAGE_SIZE_MAX)),
            "cursor": cursor,
            "orgId": org_id,
            "targetUserId": target_user_id,
        },
    )
    return parse_usage_page(_fetch(path, cookie))


def fetch_usage_all(
    cookie: str,
    max_pages: int = MAX_FETCH_PAGES,
    org_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
) -> tuple[list[UsageRecord], int]:
    """翻页拉取全部可用明细, 返回 (records, pages_fetched).

    服务端窗口为"最近 1 天 / 最多 100 条", 因此正常情况下 1~2 页即到底;
    max_pages 仅作防失控兜底.
    """
    records: list[UsageRecord] = []
    cursor: Optional[str] = None
    pages = 0
    for _ in range(max(1, max_pages)):
        page = fetch_usage_page(
            cookie, cursor=cursor, org_id=org_id, target_user_id=target_user_id
        )
        pages += 1
        records.extend(page.records)
        if not page.has_more:
            break
        cursor = page.next_cursor
    return records, pages


def fetch_usage_summary(
    cookie: str, org_id: Optional[str] = None, target_user_id: Optional[str] = None
) -> dict[str, Any]:
    """拉取用量汇总 (按 billing-period 聚合)."""
    path = _with_query(
        PATH_USAGE_SUMMARY, {"orgId": org_id, "targetUserId": target_user_id}
    )
    data = _fetch(path, cookie)
    return data if isinstance(data, dict) else {}


def fetch_usage_charts(
    cookie: str, org_id: Optional[str] = None, target_user_id: Optional[str] = None
) -> list[Any]:
    """拉取服务端图表数据原始行 (个人账号需带 from/to, 否则返回空数组)."""
    path = _with_query(
        PATH_USAGE_CHARTS, {"orgId": org_id, "targetUserId": target_user_id}
    )
    data = _fetch(path, cookie)
    if isinstance(data, dict):
        rows = data.get("data")
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 5 分钟聚合桶 (唯一带「缓存 token」维度的数据源)
# ---------------------------------------------------------------------------

CHART_WINDOW_MINUTES = 1440  # 请求窗口取 1 天; 服务端只回窗口内「有数据」的最近约 7 个 5 分钟桶


@dataclass
class ChartBucket:
    """``/internal/usage/charts`` 的一个 (model × timeBucket) 聚合桶.

    实测: 桶粒度为 5 分钟; 11 个数值字段与 ``/internal/usage/summary`` 完全对账;
    比请求明细多出 ``cacheReadInputTokens`` / ``cacheCreationInputTokens`` /
    ``cacheSavings``, 是缓存命中率的唯一上游来源。
    """

    model: str
    provider: str
    time_bucket: str  # "2026-09-17 16:50:00" (UTC)
    requests: int
    tokens_in: int
    tokens_out: int
    tokens_total: int
    input_cost: float
    output_cost: float
    cache_cost: float
    cache_savings: float
    total_cost: float
    credits_total: float
    consumed_free: float
    consumed_monthly: float
    consumed_purchased: float
    consumed_total: float
    cache_read_tokens: int
    cache_creation_tokens: int

    @property
    def bucket_key(self) -> str:
        """同 (model, timeBucket) 的桶是累计值, 重复拉取应覆盖而非累加."""
        return f"{self.model}|{self.time_bucket}"

    def to_db_dict(self) -> dict[str, Any]:
        return {
            "bucket_key": self.bucket_key,
            "model": self.model,
            "provider": self.provider,
            "time_bucket": self.time_bucket,
            "requests": self.requests,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_total": self.tokens_total,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "cache_cost": self.cache_cost,
            "cache_savings": self.cache_savings,
            "total_cost": self.total_cost,
            "credits_total": self.credits_total,
            "consumed_free": self.consumed_free,
            "consumed_monthly": self.consumed_monthly,
            "consumed_purchased": self.consumed_purchased,
            "consumed_total": self.consumed_total,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


def parse_chart_row(raw: dict[str, Any]) -> Optional[ChartBucket]:
    """解析 charts 的一行; 缺 model/timeBucket 时返回 None."""
    model = str(raw.get("model") or "").strip()
    bucket = str(raw.get("timeBucket") or "").strip()
    if not model or not bucket:
        return None
    return ChartBucket(
        model=model,
        provider=str(raw.get("provider") or "").strip(),
        time_bucket=bucket,
        requests=_to_int(raw.get("requests")),
        tokens_in=_to_int(raw.get("tokensIn")),
        tokens_out=_to_int(raw.get("tokensOut")),
        tokens_total=_to_int(raw.get("tokensTotal")),
        input_cost=_to_float(raw.get("inputCost")),
        output_cost=_to_float(raw.get("outputCost")),
        cache_cost=_to_float(raw.get("cacheCost")),
        cache_savings=_to_float(raw.get("cacheSavings")),
        total_cost=_to_float(raw.get("totalCost")),
        credits_total=_to_float(raw.get("creditsTotal")),
        consumed_free=_to_float(raw.get("consumedFreeCredits")),
        consumed_monthly=_to_float(raw.get("consumedMonthlyCredits")),
        consumed_purchased=_to_float(raw.get("consumedPurchasedCredits")),
        consumed_total=_to_float(raw.get("consumedTotal")),
        cache_read_tokens=_to_int(raw.get("cacheReadInputTokens")),
        cache_creation_tokens=_to_int(raw.get("cacheCreationInputTokens")),
    )


def fetch_chart_buckets(
    cookie: str,
    window_minutes: int = CHART_WINDOW_MINUTES,
    org_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> list[ChartBucket]:
    """拉取 5 分钟聚合桶.

    必须显式传 ISO 8601 的 ``from``/``to`` (传 epoch 毫秒会 400, 不传返回空数组);
    服务端实际只回最近约 35 分钟 (7 个桶), 因此需要配合高频同步持续累积。
    """
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(minutes=max(5, int(window_minutes)))
    path = _with_query(
        PATH_USAGE_CHARTS,
        {
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": end.isoformat().replace("+00:00", "Z"),
            "orgId": org_id,
            "targetUserId": target_user_id,
        },
    )
    data = _fetch(path, cookie)
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    buckets: list[ChartBucket] = []
    for raw in rows:
        if isinstance(raw, dict):
            bucket = parse_chart_row(raw)
            if bucket is not None:
                buckets.append(bucket)
    return buckets


# ---------------------------------------------------------------------------
# 配额 / 账单
# ---------------------------------------------------------------------------


def fetch_credits(
    cookie: str, org_id: Optional[str] = None, target_user_id: Optional[str] = None
) -> dict[str, Any]:
    """拉取额度与窗口限制 (credits 原样返回)."""
    path = _with_query(PATH_CREDITS, {"orgId": org_id, "targetUserId": target_user_id})
    data = _fetch(path, cookie)
    return data if isinstance(data, dict) else {}


def fetch_subscription(
    cookie: str, org_id: Optional[str] = None, target_user_id: Optional[str] = None
) -> dict[str, Any]:
    """拉取订阅信息, 返回 data 字段 (无订阅返回 {})."""
    path = _with_query(
        PATH_SUBSCRIPTIONS, {"orgId": org_id, "targetUserId": target_user_id}
    )
    data = _fetch(path, cookie)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def fetch_orgs(cookie: str) -> list[dict[str, Any]]:
    """拉取当前用户所属组织列表."""
    data = _fetch(PATH_ORGS, cookie)
    if isinstance(data, dict):
        rows = data.get("organizations")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def fetch_models(cookie: str) -> list[dict[str, Any]]:
    """拉取模型目录 (用于展示模型友好名)."""
    data = _fetch(PATH_MODELS, cookie)
    if isinstance(data, dict):
        rows = data.get("models")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return data if isinstance(data, list) else []


def fetch_profile(cookie: str, login: str) -> dict[str, Any]:
    """拉取指定用户主页资料 (回填账号显示名/头像用).

    站点没有"当前用户"端点 (``/internal/me`` 等均为 404), 只能按 login 查;
    拿不到时返回 {} (不影响主流程).
    """
    login = (login or "").strip().strip("/")
    if not login:
        return {}
    try:
        data = _fetch(f"/internal/profile/{urllib.parse.quote(login)}", cookie)
    except CmdAPIError:
        return {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def _ms_to_iso(ms: Any) -> tuple[str, int]:
    """毫秒时间戳 -> (ISO8601, 距现在秒数); 无效值返回 ("", 0)."""
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return "", 0
    if value <= 0:
        return "", 0
    # 兼容秒级时间戳
    if value < 1e11:
        value *= 1000.0
    dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    remaining = int((dt - datetime.now(timezone.utc)).total_seconds())
    return dt.isoformat().replace("+00:00", "Z"), remaining


def _build_window(
    label: str, used: float, cap: float, reset_ms: Any, exceeded: bool = False
) -> QuotaWindow:
    reset_at, reset_in = _ms_to_iso(reset_ms)
    total = max(0.0, cap)
    remaining = max(0.0, total - max(0.0, used))
    return QuotaWindow(
        label=label,
        used=max(0.0, used),
        total=total,
        remaining=remaining,
        reset_at=reset_at,
        reset_in_sec=reset_in,
        exceeded=bool(exceeded) or (total > 0 and used >= total),
    )


def parse_quota(
    credits_payload: dict[str, Any],
    subscription: dict[str, Any],
    name: str = "Default",
    org_id: str = "",
) -> QuotaResult:
    """把 credits + subscriptions 响应组合为 QuotaResult."""
    now_iso = _now_iso()
    credits = credits_payload.get("credits") if isinstance(credits_payload.get("credits"), dict) else {}
    limits = (
        credits_payload.get("windowLimits")
        if isinstance(credits_payload.get("windowLimits"), dict)
        else {}
    )

    granted = _to_float(credits.get("monthlyCreditsGranted"))
    monthly_remaining = _to_float(credits.get("monthlyCredits"))
    purchased = _to_float(credits.get("purchasedCredits"))
    # freeCredits 才是独立的赠送额度; premiumMonthlyCredits / opensourceMonthlyCredits
    # 是 monthlyCredits 的内部拆分 (二者之和 == monthlyCredits), 重复计入会翻倍
    free = _to_float(credits.get("freeCredits"))

    plan_id = str(subscription.get("planId") or "")
    pinfo = plan_info(plan_id)
    # 实测: /alpha/billing/credits (API Key 模式) **不返回** monthlyCreditsGranted,
    # 只有 /internal 版本才有。缺失时回落到套餐映射 (额度仅供展示, 已标注来源)。
    granted_from_plan = False
    if granted <= 0 and pinfo.get("monthly_credits"):
        granted = float(pinfo["monthly_credits"])
        granted_from_plan = True

    # 月度额度: 授予额度缺失时回退为"剩余 + 已用" (以周期内消费反推)
    period_end = str(subscription.get("currentPeriodEnd") or "")
    # 月度额度: 授予额度缺失时回退为"剩余 + 已用" (以周期内消费反推)
    period_end = str(subscription.get("currentPeriodEnd") or "")
    period_start = str(subscription.get("currentPeriodStart") or "")
    days_left: Optional[int] = None
    if period_end:
        try:
            end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
            days_left = max(0, (end_dt - datetime.now(timezone.utc)).days)
        except (TypeError, ValueError):
            days_left = None

    windows: list[QuotaWindow] = []

    five = limits.get("fiveHour") if isinstance(limits.get("fiveHour"), dict) else {}
    if five:
        windows.append(
            _build_window(
                "5h",
                _to_float(five.get("used")),
                _to_float(five.get("cap")),
                five.get("resetAt"),
                bool(five.get("exceeded")),
            )
        )
    weekly = limits.get("weekly") if isinstance(limits.get("weekly"), dict) else {}
    if weekly:
        windows.append(
            _build_window(
                "Weekly",
                _to_float(weekly.get("used")),
                _to_float(weekly.get("cap")),
                weekly.get("resetAt"),
                bool(weekly.get("exceeded")),
            )
        )
    if granted > 0 or monthly_remaining > 0:
        monthly_reset_ms = 0
        if period_end:
            try:
                monthly_reset_ms = (
                    datetime.fromisoformat(period_end.replace("Z", "+00:00")).timestamp()
                    * 1000.0
                )
            except (TypeError, ValueError):
                monthly_reset_ms = 0
        windows.append(
            _build_window(
                "Monthly",
                max(0.0, granted - monthly_remaining),
                granted,
                monthly_reset_ms,
            )
        )

    total_remaining = monthly_remaining + purchased + free
    plan_id = str(subscription.get("planId") or "")
    pinfo = plan_info(plan_id)
    return QuotaResult(
        name=name,
        org_id=org_id,
        success=True,
        updated_at=now_iso,
        plan_id=plan_id,
        plan_name=pinfo.get("name", "") or "",
        plan_status=str(subscription.get("status") or ""),
        plan_monthly_credits=pinfo.get("monthly_credits"),
        period_start=period_start,
        period_end=period_end,
        days_left=days_left,
        monthly_granted=granted,
        monthly_granted_from_plan=granted_from_plan,
        monthly_remaining=monthly_remaining,
        purchased_remaining=purchased,
        free_remaining=free,
        total_remaining=total_remaining,
        windows=windows,
    )


def fetch_quota(
    cookie: str,
    org_id: Optional[str] = None,
    name: str = "Default",
    target_user_id: Optional[str] = None,
) -> QuotaResult:
    """拉取单账号配额 (失败时返回 success=False 的 QuotaResult)."""
    now_iso = _now_iso()
    if not (cookie or "").strip():
        return QuotaResult(
            name=name, org_id=org_id or "", success=False,
            updated_at=now_iso, error="未配置登录凭证",
        )
    try:
        credits = fetch_credits(cookie, org_id, target_user_id)
        try:
            subscription = fetch_subscription(cookie, org_id, target_user_id)
        except CmdAPIError:
            subscription = {}  # 无订阅属正常情况, 不影响额度卡片
        if not credits:
            raise CmdAPIError("额度接口返回空数据")
        return parse_quota(credits, subscription, name=name, org_id=org_id or "")
    except Exception as exc:  # noqa: BLE001
        return QuotaResult(
            name=name, org_id=org_id or "", success=False,
            updated_at=now_iso, error=str(exc),
        )


def check_auth(cookie: str) -> tuple[bool, str]:
    """校验 cookie 是否有效, 返回 (ok, 说明)."""
    if not build_cookie_header(cookie):
        return False, "凭证为空"
    try:
        fetch_usage_summary(cookie)
        return True, ""
    except AuthError as exc:
        return False, str(exc)
    except CmdAPIError as exc:
        return False, str(exc)


def usage_page_url(login: str = "") -> str:
    """构造官方用量页链接 (个人: /settings/usage; 组织: /<orgLogin>/settings/usage)."""
    login = (login or "").strip().strip("/")
    if login:
        return f"{SITE_BASE}/{urllib.parse.quote(login)}/settings/usage"
    return f"{SITE_BASE}/settings/usage"


# ---------------------------------------------------------------------------
# API Key 模式 (/alpha/* 端点)
#
# 与 /internal/* 的差异 (实测 + 官方 CLI 源码确认):
#   - /alpha/* 只接受 Authorization: Bearer <apiKey>, 用 cookie 会 401;
#   - /alpha/* 只提供聚合数据, **没有请求级明细**, 也没有 5 分钟缓存桶;
#   - 响应结构与 /internal 对应端点一致 (credits: {credits:{...}, windowLimits:{...}}),
#     因此可复用同一个 parse_quota。
# ---------------------------------------------------------------------------


def fetch_alpha_whoami(cred: str) -> dict[str, Any]:
    """GET /alpha/whoami -> {user:{userName}, org:{id,login}, orgLimits:[...]}."""
    data = _fetch(PATH_ALPHA_WHOAMI, cred, AUTH_APIKEY)
    return data if isinstance(data, dict) else {}


def fetch_alpha_credits(cred: str, org_id: Optional[str] = None) -> dict[str, Any]:
    """GET /alpha/billing/credits (结构同 /internal/billing/credits)."""
    path = _with_query(PATH_ALPHA_CREDITS, {"orgId": org_id})
    data = _fetch(path, cred, AUTH_APIKEY)
    return data if isinstance(data, dict) else {}


def fetch_alpha_subscription(cred: str, org_id: Optional[str] = None) -> dict[str, Any]:
    """GET /alpha/billing/subscriptions -> data 字段."""
    path = _with_query(PATH_ALPHA_SUBSCRIPTIONS, {"orgId": org_id})
    data = _fetch(path, cred, AUTH_APIKEY)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def fetch_alpha_summary(cred: str, org_id: Optional[str] = None) -> dict[str, Any]:
    """GET /alpha/usage/summary (按账单周期聚合)."""
    path = _with_query(PATH_ALPHA_SUMMARY, {"orgId": org_id})
    data = _fetch(path, cred, AUTH_APIKEY)
    return data if isinstance(data, dict) else {}


def fetch_profile(cookie: str, login: str) -> dict[str, Any]:
    """拉取指定用户主页资料 (回填账号显示名/头像用).

    站点没有"当前用户"端点 (``/internal/me`` 等均为 404), 只能按 login 查;
    拿不到时返回 {} (不影响主流程).
    """
    login = (login or "").strip().strip("/")
    if not login:
        return {}
    try:
        data = _fetch(PATH_PROFILE.format(login=urllib.parse.quote(login)), cookie)
    except CmdAPIError:
        return {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def fetch_quota_any(
    cred: str,
    auth_type: str = AUTH_COOKIE,
    org_id: Optional[str] = None,
    name: str = "Default",
    target_user_id: Optional[str] = None,
) -> QuotaResult:
    """按认证类型分派配额拉取.

    - cookie: ``/internal/billing/credits`` + ``/internal/billing/subscriptions``
    - apikey: ``/alpha/billing/credits`` + ``/alpha/billing/subscriptions``
    """
    if auth_type == AUTH_APIKEY:
        return fetch_quota_apikey(cred, org_id=org_id, name=name)
    return fetch_quota(cred, org_id=org_id, name=name, target_user_id=target_user_id)


def fetch_quota_apikey(cred: str, org_id: Optional[str] = None, name: str = "Default") -> QuotaResult:
    """API Key 模式下的配额拉取 (仅 /alpha/*, 无明细/无缓存桶)."""
    now_iso = _now_iso()
    if not (cred or "").strip():
        return QuotaResult(name=name, org_id=org_id or "", success=False,
                           updated_at=now_iso, error="未配置 API Key")
    try:
        credits = fetch_alpha_credits(cred, org_id)
        try:
            subscription = fetch_alpha_subscription(cred, org_id)
        except CmdAPIError:
            subscription = {}
        if not credits:
            raise CmdAPIError("额度接口返回空数据")
        return parse_quota(credits, subscription, name=name, org_id=org_id or "")
    except Exception as exc:  # noqa: BLE001
        return QuotaResult(name=name, org_id=org_id or "", success=False,
                           updated_at=now_iso, error=str(exc))


def check_auth_apikey(cred: str) -> tuple[bool, str]:
    """校验 API Key, 返回 (ok, 说明). 顺带回传 whoami 里的 login (见返回值第三项)."""
    if not (cred or "").strip():
        return False, "API Key 为空"
    try:
        fetch_alpha_credits(cred)
        return True, ""
    except AuthError as exc:
        return False, str(exc)
    except CmdAPIError as exc:
        return False, str(exc)


def apikey_identity(cred: str) -> dict[str, Any]:
    """用 API Key 拉身份信息, 返回 {login, org_id}; 失败返回 {}."""
    try:
        who = fetch_alpha_whoami(cred)
    except CmdAPIError:
        return {}
    org = who.get("org") if isinstance(who.get("org"), dict) else {}
    user = who.get("user") if isinstance(who.get("user"), dict) else {}
    return {
        "login": str(org.get("login") or user.get("userName") or "").strip(),
        "org_id": str(org.get("id") or "").strip(),
    }
