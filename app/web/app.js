/* CmdGauge - Command Code 用量仪表盘 (首页/用量统计/使用记录/设置/关于) + 双主题 + 中英国际化
   移植自 GoGauge (opencode-go-gauge), 数据层改为 Command Code /internal/* 接口 */
"use strict";

const $ = (id) => document.getElementById(id);

/* ================= 国际化 ================= */
const I18N = {
  zh: {
    syncing: "同步中", themeDark: "暗色", themeLight: "亮色", refresh: "刷新",
    homeTitle: "用量统计总览", today: "今天", d7: "近7天", d30: "近30天", all: "全部",
    overviewTitle: "用量概览", followRange: "数据跟随时间范围",
    todayTrend: "今日趋势", hours24: "24 小时",
    statsTitle: "用量统计", tokenBreakdown: "Token 与成本构成",
    modelUsage: "模型用量", input: "输入", output: "输出", cost: "成本",
    usageTrend: "用量趋势", usageRecords: "使用记录", allModels: "全部模型",
    recordsPage: "使用记录", allStatus: "全部状态",
    statusCompleted: "已完成", statusFailed: "失败",
    dayUsage: "每日用量", colDay: "日期", colSuccessRate: "成功率",
    colTotalTokens: "总 TOKEN", colDuration: "耗时", colStatus: "状态",
    accountOverview: "账户总览", costTrend7d: "7 日费用趋势对比",
    todayTotalReq: "今日总请求", todayTotalTokens: "今日总 TOKEN",
    todayTotalCost: "今日总费用", todayTotalInput: "今日总输入",
    activeAccount: "当前活跃", quotaNotReady: "额度获取中…",
    overviewPanel: "账户总览面板", overviewPanelDesc: "侧边栏显示多账户总览入口，聚合展示各账户配额与用量",
    setUpdate: "软件更新", currentVersion: "当前版本", checkUpdate: "检查更新",
    checkUpdateDesc: "检查 GitHub 上是否有新版本", checkUpdateBtn: "检查更新",
    checkingUpdate: "检查中…", updateFound: "发现新版本", updateNone: "已是最新版本",
    updateFailed: "检查更新失败", goDownload: "前往下载",
    colTime: "时间", colModel: "模型", colInput: "输入", colOutput: "输出",
    colCost: "费用", colRequests: "请求", colPlan: "套餐",
    prev: "上一页", next: "下一页",
    settingsTitle: "设置", setAccount: "Command Code 账户", setLoginState: "登录状态",
    setLoginMethod: "登录方式",
    loginMethodDesc: "内置浏览器 (WebView2) 打开 commandcode.ai 登录页，自动捕获会话凭证",
    relogin: "重新登录", setLogout: "退出登录", logoutDesc: "清除本地凭证与缓存数据", logout: "退出登录",
    setAutoSync: "自动同步", autoSync: "自动增量同步", autoSyncDesc: "按间隔拉取最新用量记录",
    syncInterval: "同步间隔", syncIntervalDesc: "多久自动同步一次",
    min1: "1 分钟", min5: "5 分钟", min15: "15 分钟", min30: "30 分钟",
    syncRange: "本地保留范围",
    syncRangeDesc: "本地数据保留窗口；\"所有\"= 不裁剪。官方接口只提供最近 1 天明细，历史靠本机累积",
    d30short: "30天", d60: "60天", d90: "90天", d180: "180天",
    fullSync: "立即全量同步", fullSyncDesc: "重新拉取窗口内记录，补全数据", startFullSync: "开始全量同步",
    setAppearance: "外观", theme: "主题", themeDesc: "亮色 / 深色，顶栏按钮快捷切换",
    light: "浅色", dark: "深色", currency: "默认货币", currencyDesc: "费用主显示货币（实时汇率）",
    language: "语言 / Language", languageDesc: "界面显示语言",
    setData: "数据", dataDir: "数据目录", syncInfo: "同步记录",
    officialPage: "官方用量页", openInBrowser: "在浏览器打开",
    aboutTitle: "关于", aboutIntro: "简介",
    introText: "是一款本地优先的 Command Code 用量面板：额度窗口、Token 与成本构成、模型排行、每日用量与请求明细整理在同一处，打开即见。所有数据仅保存在本地，登录凭证只用于同步官方接口。",
    aboutFeatures: "功能", feat1: "额度窗口实时监控（5 小时 / 每周 / 每月）",
    feat2: "今日用量与 24 小时趋势", feat3: "各模型 Token 与成本排行、用量趋势",
    feat4: "请求级明细与每日汇总，支持模型/状态筛选", feat5: "自动同步数据（本地累积历史），无需手动刷新",
    aboutLinks: "链接", dataSource: "数据来源", aboutThanks: "致谢",
    thanksText: "界面基于", thanksText2: "移植。",
    pageFoot: "{version} · CmdGauge · 数据仅保存在本地 · 数据来自 Command Code",
    loginTitle: "连接 Command Code",
    welcomeDesc: "本地优先的 Command Code 用量仪表盘 — 额度窗口、Token 与成本构成、模型排行、请求明细，打开即见。",
    welcomeFeat1: "额度实时监控（5 小时 / 每周 / 每月）",
    welcomeFeat2: "Token / 成本 / 耗时全维度统计与 24 小时趋势",
    welcomeFeat3: "数据仅保存在本机，安全私密",
    loginBtn: "立即登录",
    loginNote: "点击后将打开 commandcode.ai 官方登录页完成登录。",
    apikeyLogin: "使用 API Key 登录", apikeyTitle: "使用 API Key 登录",
    apikeyHint: "API Key 模式仅能获取额度与账单汇总 —— 官方 /alpha 接口不含请求级明细、每日用量与缓存指标。想要完整功能请用浏览器登录。",
    apikeyPlaceholder: "粘贴 Command Code API Key",
    apikeyEmpty: "请填写 API Key", apikeyInvalid: "API Key 无效或已过期",
    apikeyOk: "API Key 登录成功",
    authCookie: "浏览器会话", authApikey: "API Key",
    apikeyLimited: "API Key 模式：无请求明细与缓存指标",
    quitApp: "退出应用",
    w5h: "5 小时窗口", wWeekly: "每周窗口", wMonthly: "每月额度",
    remaining: "剩余", used: "已用", resetsIn: "重置于", resetsAt: "重置于",
    totalTokens: "总 TOKEN", totalRequests: "总请求", totalCost: "总费用",
    cacheCost: "缓存成本", cacheCostRatio: "缓存成本占比", ofInputCost: "占输入成本",
    cacheHitRate: "缓存命中率", cacheRead: "缓存读", cacheWrite: "缓存写",
    cacheSavings: "缓存节省", missTokens: "未命中",
    cacheNoData: "暂无缓存数据，随同步累积", fromBuckets: "来自上游 5 分钟聚合桶",
    planEstimated: "额度按套餐估算",
    billingPeriodHint: "账单周期累计（API Key 模式无请求明细）",
    noHourlyData: "API Key 模式无逐小时数据",
    noModelData: "API Key 模式无按模型数据",
    successRate: "成功率", successCount: "成功", failedCount: "失败",
    avgDuration: "平均耗时", avgCost: "平均成本",
    inputCost: "输入成本", outputCost: "输出成本",
    generated: "生成", dailyAvg: "日均", requestsUnit: "次请求",
    currentRange: "当前范围", avgPer: "均", perReq: "/次",
    noData: "暂无记录", loadFailed: "加载失败", totalN: "共", items: "条",
    pageOf: "第", ofPages: "页", pages: "页",
    loggedIn: "已登录", notLoggedIn: "未登录",
    lastSync: "上次同步", records: "条记录", updatedAt: "更新于",
    justNow: "刚刚", minAgo: "分钟前", hrAgo: "小时前", dayAgo: "天前", never: "从未同步",
    dUnit: "天", hUnit: "小时", mUnit: "分钟", soon: "即将重置",
    confirm: "确认", cancel: "取消", ok: "确定",
    fullSyncConfirm: "将重新拉取窗口内的用量记录并补齐本地数据，确定开始？", startSync: "开始同步",
    reloginConfirmNew: "将打开官方登录页重新登录当前账号，确定？",
    logoutConfirm: "退出将清除本地凭证与全部缓存数据，确定退出？", quit: "退出",
    quotaFail: "额度获取失败", retryTip: "点击右上角刷新重试",
    syncIntervalSet: "同步间隔已设为", syncRangeUpdated: "本地保留范围已更新",
    trendHint: "30 天", billingPeriod: "账单周期", daysLeft: "天后重置",
    plan: "套餐", monthlyGranted: "月度额度",
    setUsers: "用户管理", addUser: "添加用户", addUserTip: "登录新的 Command Code 账号并保存到本机",
    userSwitchTip: "切换用户", userCountTip: "已登录用户数",
    switchTo: "切换", currentUserBadge: "当前", renameBtn: "重命名", deleteUser: "删除",
    renameTitle: "重命名用户", save: "保存", deleteUserTitle: "删除用户",
    deleteUserConfirm: "确定删除用户「{name}」？其本地用量数据与同步记录将一并清除，且无法恢复。",
    userDeleted: "用户已删除", userRenamed: "已重命名", switchedAccount: "已切换账号",
    noUsers: "暂无账号，点击右上角「添加用户」登录",
    loggedOut: "已退出登录",
    logoutUserConfirm: "将退出「{name}」并清除其本地用量数据与同步记录，确定？",
    authExpired: "登录已过期，请重新登录",
  },
  en: {
    syncing: "Syncing", themeDark: "Dark", themeLight: "Light", refresh: "Refresh",
    homeTitle: "Usage Overview", today: "Today", d7: "7 Days", d30: "30 Days", all: "All",
    overviewTitle: "Usage Overview", followRange: "Follows selected range",
    todayTrend: "Today's Trend", hours24: "24 Hours",
    statsTitle: "Usage Stats", tokenBreakdown: "Tokens & Cost",
    modelUsage: "Model Usage", input: "Input", output: "Output", cost: "Cost",
    usageTrend: "Usage Trend", usageRecords: "Usage Records", allModels: "All Models",
    recordsPage: "Records", allStatus: "All Status",
    statusCompleted: "Completed", statusFailed: "Failed",
    dayUsage: "Daily Usage", colDay: "Date", colSuccessRate: "Success",
    colTotalTokens: "Total Tokens", colDuration: "Latency", colStatus: "Status",
    accountOverview: "Accounts Overview", costTrend7d: "7-Day Cost Trend",
    todayTotalReq: "Today Requests", todayTotalTokens: "Today Tokens",
    todayTotalCost: "Today Cost", todayTotalInput: "Today Input",
    activeAccount: "Active", quotaNotReady: "Fetching quota…",
    overviewPanel: "Accounts Panel", overviewPanelDesc: "Show multi-account overview entry in sidebar",
    setUpdate: "Software Update", currentVersion: "Current Version", checkUpdate: "Check Updates",
    checkUpdateDesc: "Check GitHub for new versions", checkUpdateBtn: "Check Updates",
    checkingUpdate: "Checking…", updateFound: "New Version Available", updateNone: "You're up to date",
    updateFailed: "Check failed", goDownload: "Go to Download",
    colTime: "Time", colModel: "Model", colInput: "Input", colOutput: "Output",
    colCost: "Cost", colRequests: "Requests", colPlan: "Plan",
    prev: "Prev", next: "Next",
    settingsTitle: "Settings", setAccount: "Command Code Account", setLoginState: "Login Status",
    setLoginMethod: "Login Method",
    loginMethodDesc: "Built-in browser (WebView2) opens commandcode.ai and captures the session automatically",
    relogin: "Re-login", setLogout: "Logout", logoutDesc: "Clear local credentials and cached data", logout: "Logout",
    setAutoSync: "Auto Sync", autoSync: "Auto incremental sync", autoSyncDesc: "Fetch latest usage records at interval",
    syncInterval: "Sync Interval", syncIntervalDesc: "How often to auto sync",
    min1: "1 min", min5: "5 min", min15: "15 min", min30: "30 min",
    syncRange: "Local Retention",
    syncRangeDesc: "Local data retention window; \"All\" = never prune. The official API only serves the last day, history accumulates locally",
    d30short: "30d", d60: "60d", d90: "90d", d180: "180d",
    fullSync: "Full Sync Now", fullSyncDesc: "Re-fetch records in window to fill gaps", startFullSync: "Start Full Sync",
    setAppearance: "Appearance", theme: "Theme", themeDesc: "Light / Dark, quick toggle in top bar",
    light: "Light", dark: "Dark", currency: "Currency", currencyDesc: "Primary currency for costs (live FX rate)",
    language: "Language", languageDesc: "Interface language",
    setData: "Data", dataDir: "Data Directory", syncInfo: "Sync History",
    officialPage: "Official Usage Page", openInBrowser: "Open in Browser",
    aboutTitle: "About", aboutIntro: "Intro",
    introText: "is a local-first Command Code usage dashboard: quota windows, tokens & cost breakdown, model ranking, daily usage and request records in one place. All data stays on your machine; credentials are only used to sync official APIs.",
    aboutFeatures: "Features", feat1: "Quota window monitoring (5h / weekly / monthly)",
    feat2: "Today's usage with 24-hour trend", feat3: "Per-model token & cost ranking and trend",
    feat4: "Request records and daily rollups with model/status filters", feat5: "Auto sync — history accumulates locally",
    aboutLinks: "Links", dataSource: "Data source", aboutThanks: "Thanks",
    thanksText: "UI ported from", thanksText2: ".",
    pageFoot: "{version} · CmdGauge · Local-only data · Data from Command Code",
    loginTitle: "Connect Command Code",
    welcomeDesc: "A local-first Command Code usage dashboard — quota windows, tokens & cost, model ranking and request records in one place.",
    welcomeFeat1: "Real-time quota monitoring (5h / weekly / monthly)",
    welcomeFeat2: "Full token / cost / latency stats with 24-hour trend",
    welcomeFeat3: "All data stays on your machine — private & safe",
    loginBtn: "Login Now",
    loginNote: "Clicking opens the official commandcode.ai sign-in page.",
    apikeyLogin: "Sign in with API Key", apikeyTitle: "Sign in with API Key",
    apikeyHint: "API Key mode only reaches quota and billing aggregates — the official /alpha endpoints expose no per-request records, daily rollups or cache metrics. Use browser sign-in for full features.",
    apikeyPlaceholder: "Paste your Command Code API Key",
    apikeyEmpty: "API Key is required", apikeyInvalid: "API Key is invalid or expired",
    apikeyOk: "Signed in with API Key",
    authCookie: "Browser session", authApikey: "API Key",
    apikeyLimited: "API Key mode: no request records or cache metrics",
    quitApp: "Quit App",
    w5h: "5-Hour Window", wWeekly: "Weekly Window", wMonthly: "Monthly Credits",
    remaining: "Remaining", used: "Used", resetsIn: "Resets in", resetsAt: "Resets",
    totalTokens: "Total Tokens", totalRequests: "Requests", totalCost: "Total Cost",
    cacheCost: "Cache Cost", cacheCostRatio: "Cache Cost Share", ofInputCost: "of input cost",
    cacheHitRate: "Cache Hit Rate", cacheRead: "Cache Read", cacheWrite: "Cache Write",
    cacheSavings: "Cache Saved", missTokens: "Missed",
    cacheNoData: "No cache data yet — accumulates with sync", fromBuckets: "from upstream 5-min buckets",
    planEstimated: "credits estimated from plan",
    billingPeriodHint: "Billing-period totals (API Key mode has no request records)",
    noHourlyData: "No hourly data in API Key mode",
    noModelData: "No per-model data in API Key mode",
    successRate: "Success Rate", successCount: "Succeeded", failedCount: "Failed",
    avgDuration: "Avg Latency", avgCost: "Avg Cost",
    inputCost: "Input Cost", outputCost: "Output Cost",
    generated: "generated", dailyAvg: "daily avg", requestsUnit: "requests",
    currentRange: "current range", avgPer: "avg", perReq: "/req",
    noData: "No records", loadFailed: "Failed to load", totalN: "Total", items: "records",
    pageOf: "Page", ofPages: "of", pages: "pages",
    loggedIn: "Logged in", notLoggedIn: "Not logged in",
    lastSync: "Last sync", records: "records", updatedAt: "Updated",
    justNow: "just now", minAgo: "min ago", hrAgo: "hr ago", dayAgo: "d ago", never: "Never synced",
    dUnit: "d", hUnit: "h", mUnit: "m", soon: "resets soon",
    confirm: "Confirm", cancel: "Cancel", ok: "OK",
    fullSyncConfirm: "This will re-fetch records in the window and fill local data. Continue?", startSync: "Start Sync",
    reloginConfirmNew: "This opens the official sign-in page to re-login the current account. Continue?",
    logoutConfirm: "This will clear local credentials and all cached data. Continue?", quit: "Logout",
    quotaFail: "Quota fetch failed", retryTip: "Click refresh in top bar to retry",
    syncIntervalSet: "Sync interval set to", syncRangeUpdated: "Local retention updated",
    trendHint: "30 days", billingPeriod: "Billing period", daysLeft: "days to reset",
    plan: "Plan", monthlyGranted: "Monthly credits",
    setUsers: "User Management", addUser: "Add User", addUserTip: "Sign in with another Command Code account",
    userSwitchTip: "Switch user", userCountTip: "Logged-in users",
    switchTo: "Switch", currentUserBadge: "Active", renameBtn: "Rename", deleteUser: "Delete",
    renameTitle: "Rename User", save: "Save", deleteUserTitle: "Delete User",
    deleteUserConfirm: "Delete user \"{name}\"? Their local usage data and sync history will be removed permanently.",
    userDeleted: "User deleted", userRenamed: "Renamed", switchedAccount: "Account switched",
    noUsers: "No accounts yet — click \"Add User\" to sign in",
    loggedOut: "Signed out",
    logoutUserConfirm: "Sign out \"{name}\" and remove their local usage data and sync history?",
    authExpired: "Session expired — please sign in again",
  },
};
let lang = "zh";
function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N.zh[key] || key; }

let state = {
  page: "home",
  range: "today",
  statsRange: "7d",
  modelDim: "input",
  data: null,
  exchangeRate: 7.0,
  currency: "USD",
  darkMode: false,
  syncTimer: null,
  quotaRetryTimer: null,
  ovRetryTimer: null,
  records: { page: 1, pageSize: 7, total: 0, model: "", status: "" },
  days: { page: 1, pageSize: 7, total: 0 },
  settings: { sync_interval_sec: 300, window_days: 60, auto_sync: true },
};

const COLOR = { input: "#4f8ef7", output: "#22c55e", cost: "#d97706", cache: "#06b6d4", requests: "#7c5cf6" };
const QUOTA_LABEL = { "5h": () => t("w5h"), "Weekly": () => t("wWeekly"), "Monthly": () => t("wMonthly") };
const QUOTA_CLS = { "5h": "c-rolling", "Weekly": "c-week", "Monthly": "c-month" };
const PLAN_NAMES = {
  "individual-go": "Individual Go", "individual-pro": "Individual Pro",
  "individual-max": "Individual Max", "team": "Team", "org": "Organization",
};

/* ---------------- 格式化 ---------------- */
function fmtTokens(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n));
}
function fmtInt(n) { return Number(n || 0).toLocaleString("en-US"); }
/* Command Code 按美元计费且单次成本常小到 1e-5, 分档保留精度 */
function fmtMoney(usd) {
  usd = Number(usd) || 0;
  const sign = usd < 0 ? "-" : "";
  const v = Math.abs(usd);
  if (state.currency === "CNY") {
    const c = v * state.exchangeRate;
    if (c >= 1) return sign + "¥" + c.toFixed(2);
    if (c >= 0.01) return sign + "¥" + c.toFixed(4);
    if (c > 0) return sign + "¥" + c.toFixed(6);
    return "¥0";
  }
  if (v >= 1) return sign + "$" + v.toFixed(2);
  if (v >= 0.01) return sign + "$" + v.toFixed(4);
  if (v > 0) return sign + "$" + v.toFixed(6);
  return "$0";
}
/* 毫秒耗时 (接口 durationTotal 单位 ms) */
function fmtMs(ms) {
  ms = Math.max(0, Number(ms) || 0);
  if (ms < 1000) return Math.round(ms) + " ms";
  const s = ms / 1000;
  if (s < 60) return s.toFixed(1) + " s";
  const m = Math.floor(s / 60);
  return m + "m " + Math.round(s % 60) + "s";
}
/* 秒级倒计时 */
function fmtDur(sec) {
  sec = Math.max(0, Number(sec) || 0);
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return d + " " + t("dUnit") + " " + h + " " + t("hUnit");
  if (h > 0) return h + " " + t("hUnit") + " " + m + " " + t("mUnit");
  if (m > 0) return m + " " + t("mUnit");
  return t("soon");
}
function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function fmtDate(day) {
  if (!day) return "—";
  const d = new Date(day + "T00:00:00");
  if (isNaN(d)) return String(day);
  const pad = (x) => String(x).padStart(2, "0");
  const wd = lang === "zh" ? "日一二三四五六"[d.getDay()] : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()];
  return lang === "zh"
    ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 周${wd}`
    : `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${wd}`;
}
function fmtRelative(iso) {
  if (!iso) return t("never");
  const d = new Date(iso);
  if (isNaN(d)) return t("never");
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return t("justNow");
  if (diff < 3600) return Math.floor(diff / 60) + " " + t("minAgo");
  if (diff < 86400) return Math.floor(diff / 3600) + " " + t("hrAgo");
  return Math.floor(diff / 86400) + " " + t("dayAgo");
}
function fmtPercent(v, digits = 1) { return (Number(v) || 0).toFixed(digits) + "%"; }
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const resp = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!resp.ok) {
    let msg = "HTTP " + resp.status;
    try { const b = await resp.json(); if (b && b.error) msg = b.error; } catch (e) { /* 无 body 或非 JSON 时保持默认 */ }
    throw new Error(msg);
  }
  return resp.json();
}

/* ---------------- 语言切换 ---------------- */
function applyLang(l) {
  lang = l === "en" ? "en" : "zh";
  try { localStorage.setItem("cmdgauge-lang", lang); } catch (e) { /* ignore */ }
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll("#set-lang-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === lang));
  // 版本号唯一来源为后端 /api/version (app/__init__.py)
  const ver = APP_VERSION ? "v" + APP_VERSION : "CmdGauge";
  const aboutSub = document.getElementById("about-sub");
  if (aboutSub) aboutSub.textContent = `${ver} · Command Code Usage Panel`;
  const pf = document.querySelector('[data-i18n="pageFoot"]');
  if (pf) pf.textContent = t("pageFoot").replace("{version}", ver);
  const sv = document.getElementById("set-version");
  if (sv) sv.textContent = APP_VERSION ? `v${APP_VERSION}` : "—";
  if (state.data) {
    renderAll(state.data);
    renderSettings();
    loadRecords().catch(() => {});
    loadDays().catch(() => {});
  }
}

/* ---------------- 弹框 / Toast ---------------- */
function showModal({ title = t("confirm"), message = "", okText = t("ok"), cancelText = t("cancel"), danger = false, onOk }) {
  const overlay = $("modal-overlay");
  $("modal-title").textContent = title;
  $("modal-message").innerHTML = message;
  $("modal-ok").textContent = okText;
  $("modal-cancel").textContent = cancelText;
  $("modal-cancel").hidden = !cancelText;
  const icon = $("modal-icon");
  icon.className = "modal-icon" + (danger ? " danger" : "");
  icon.textContent = danger ? "⚠" : "?";
  overlay.hidden = false;
  const cleanup = () => { overlay.hidden = true; $("modal-ok").onclick = null; $("modal-cancel").onclick = null; };
  // onOk 返回 false 表示校验未通过: 保持弹窗打开 (输入不丢)
  $("modal-ok").onclick = async () => {
    let keepOpen = false;
    if (onOk) keepOpen = (await onOk()) === false;
    if (!keepOpen) cleanup();
  };
  $("modal-cancel").onclick = () => { cleanup(); };
}
function toast(msg, type = "ok") {
  const wrap = $("toast-wrap");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 3200);
}

/* ---------------- 标题栏 ---------------- */
async function pywebviewApi() {
  try { if (window.pywebview && window.pywebview.api) return window.pywebview.api; } catch (e) { /* ignore */ }
  return null;
}
function bindTitlebar() {
  $("tb-min").addEventListener("click", async () => { const a = await pywebviewApi(); if (a) a.minimize(); });
  $("tb-close").addEventListener("click", async () => { const a = await pywebviewApi(); if (a) a.close(); });
  $("tb-theme").addEventListener("click", () => applyDarkMode(document.documentElement.dataset.theme !== "dark"));

  /* 标题栏拖动 (自实现, 替代 pywebview easy_drag):
     Chromium/WebView2 的 e.screenX/screenY 是 DIP(逻辑像素), 而后端 move_by 用
     GetWindowRect/SetWindowPos 的物理像素坐标系 —— 增量必须乘 devicePixelRatio
     换算, 否则高 DPI/缩放屏上窗口只以鼠标的 1/scale 速度移动 ("不跟手")。
     物理像素以浮点累积、发整数、留小数余量到下一帧, 保证无取整漂移。 */
  let drag = null;
  let pending = { x: 0, y: 0 };  // 物理像素 (含小数余量)
  let rafId = null;
  function cancelDrag() {
    drag = null;
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    flushDrag();
  }
  function flushDrag() {
    rafId = null;
    if (!pending.x && !pending.y) return;
    const dx = Math.round(pending.x), dy = Math.round(pending.y);
    pending.x -= dx; pending.y -= dy;  // 保留小数余量
    if (!dx && !dy) return;
    pywebviewApi().then((a) => { if (a && a.move_by) a.move_by(dx, dy); });
  }
  document.querySelector(".tb").addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, a, #user-menu")) return;
    drag = { lx: e.screenX, ly: e.screenY, dpr: window.devicePixelRatio || 1 };
    pending = { x: 0, y: 0 };
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    if (!(e.buttons & 1)) { cancelDrag(); return; }  // 按键已释放(mouseup 丢失): 终止幽灵拖动
    pending.x += (e.screenX - drag.lx) * drag.dpr;
    pending.y += (e.screenY - drag.ly) * drag.dpr;
    drag.lx = e.screenX;
    drag.ly = e.screenY;
    if (!rafId) rafId = requestAnimationFrame(flushDrag);
  });
  window.addEventListener("mouseup", cancelDrag);
  window.addEventListener("blur", cancelDrag);  // alt-tab/弹窗抢焦点时 mouseup 会丢
}

/* ---------------- 窗口边缘调整大小 ----------------
   frameless 窗口在 Windows 上失去系统边框, 系统不再提供边缘拖拽, 因此在前端
   捕获窗口边缘的拖拽并在后端用 SetWindowPos 实现 (与标题栏拖动 move_by 同源):
   mousedown 用捕获阶段先于标题栏拖动逻辑触发, 命中边缘时 stopPropagation 阻止
   窗口拖动; mousemove 累积增量 (DIP × devicePixelRatio → 物理像素, 同 move_by),
   rAF 合并后调用 resize_by。 */
const RESIZE_EDGE_PX = 6;
const EDGE_CURSOR = {
  n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
  ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize",
};
let resizeEdge = "";
let resizeLast = { lx: 0, ly: 0 };
let resizePending = { x: 0, y: 0 };  // 物理像素 (含小数余量)
let resizeDpr = 1;
let resizeRaf = null;

function edgeAt(x, y) {
  const w = window.innerWidth, h = window.innerHeight;
  let e = "";
  if (y <= RESIZE_EDGE_PX) e += "n";
  else if (y >= h - RESIZE_EDGE_PX) e += "s";
  if (x <= RESIZE_EDGE_PX) e += "w";
  else if (x >= w - RESIZE_EDGE_PX) e += "e";
  return e;
}
function flushResize() {
  resizeRaf = null;
  if (!resizeEdge || (!resizePending.x && !resizePending.y)) return;
  const dx = Math.round(resizePending.x), dy = Math.round(resizePending.y);
  resizePending.x -= dx; resizePending.y -= dy;  // 保留小数余量
  if (!dx && !dy) return;
  const edge = resizeEdge;
  pywebviewApi().then((a) => { if (a && a.resize_by) a.resize_by(edge, dx, dy); });
}
function cancelResize() {
  if (!resizeEdge) return;
  resizeEdge = "";
  if (resizeRaf) { cancelAnimationFrame(resizeRaf); resizeRaf = null; }
  flushResize();
}
function bindWindowResize() {
  window.addEventListener("mousemove", (e) => {
    if (!resizeEdge) {
      document.documentElement.style.cursor = EDGE_CURSOR[edgeAt(e.clientX, e.clientY)] || "";
      return;
    }
    if (!(e.buttons & 1)) { cancelResize(); return; }  // mouseup 丢失兜底
    document.documentElement.style.cursor = EDGE_CURSOR[resizeEdge] || "";
    resizePending.x += (e.screenX - resizeLast.lx) * resizeDpr;
    resizePending.y += (e.screenY - resizeLast.ly) * resizeDpr;
    resizeLast.lx = e.screenX;
    resizeLast.ly = e.screenY;
    if (!resizeRaf) resizeRaf = requestAnimationFrame(flushResize);
  });
  window.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const edge = edgeAt(e.clientX, e.clientY);
    if (!edge) return;
    resizeEdge = edge;
    resizeDpr = window.devicePixelRatio || 1;
    resizeLast = { lx: e.screenX, ly: e.screenY };
    resizePending = { x: 0, y: 0 };
    e.preventDefault();
    e.stopPropagation();  // 阻止标题栏拖动
  }, true);  // 捕获阶段: 先于 .tb 的 mousedown
  window.addEventListener("mouseup", cancelResize);
  window.addEventListener("blur", cancelResize);
}

/* ---------------- 主题 / 货币 ---------------- */
function applyDarkMode(on) {
  state.darkMode = on;
  document.documentElement.dataset.theme = on ? "dark" : "light";
  $("tb-theme").innerHTML = `◐ <span data-i18n="${on ? "themeLight" : "themeDark"}">${on ? t("themeLight") : t("themeDark")}</span>`;
  try { localStorage.setItem("cmdgauge-dark", on ? "1" : "0"); } catch (e) { /* ignore */ }
  syncThemePills();
  refreshIcons();
  rerenderCharts();
}
function syncThemePills() {
  document.querySelectorAll("#set-theme-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === (state.darkMode ? "dark" : "light")));
}
function applyCurrency(cur) {
  state.currency = cur === "CNY" ? "CNY" : "USD";
  document.querySelectorAll("#set-currency-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === state.currency));
  try { localStorage.setItem("cmdgauge-currency", state.currency); } catch (e) { /* ignore */ }
  if (!state.data) return;
  rerenderCharts();
  renderUsageBlocks(state.data.quota);
  renderOverview(state.data.totals, state.data.cache);
  renderStatsTotal(state.data.totals);
  renderDetail6(state.data.totals, state.data.cache);
  loadRecords().catch(() => {});
  loadDays().catch(() => {});
  if (state.page === "overview") loadOverview(true).catch(() => {});
}

/* ---------------- 页面路由 ---------------- */
function switchPage(page) {
  state.page = page;
  document.querySelectorAll(".page").forEach((p) => (p.hidden = true));
  $("page-" + page).hidden = false;
  document.querySelectorAll(".side-item").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "home" || page === "stats") loadDashboard();
  if (page === "overview") loadOverview().catch(() => {});
  if (page === "records") { loadDays().catch(() => {}); loadRecords().catch(() => {}); }
  if (page === "settings") renderSettings();
}

/* ---------------- 骨架屏 ---------------- */
function renderSkeletons() {
  const sBlock = `<div class="ub skeleton"><div class="sk-line w40"></div><div class="sk-line w20 lg"></div><div class="sk-bar"></div><div class="sk-line w60"></div></div>`;
  $("usage-blocks").innerHTML = sBlock.repeat(3);
  const sKpi = `<div class="card kpi skeleton"><div class="sk-line w30"></div><div class="sk-line w40 lg"></div><div class="sk-line w50"></div></div>`;
  $("overview-grid").innerHTML = sKpi.repeat(6);
  const trendBox = document.querySelector(".today-trend .chart-box");
  if (trendBox) trendBox.classList.add("sk-box");
  if (!$("stats-total-cards").innerHTML) $("stats-total-cards").innerHTML = sKpi.repeat(4);
  if (!$("stats-detail6").innerHTML) $("stats-detail6").innerHTML = `<div class="tc skeleton"><div class="sk-line w40"></div><div class="sk-line w50 lg"></div><div class="sk-line w30"></div></div>`.repeat(6);
}

/* ---------------- 数据加载 ---------------- */
let loadSeq = 0;
async function loadDashboard(quiet = false) {
  const seq = ++loadSeq;
  if (!state.data) renderSkeletons();
  showLoading(true);
  try {
    const range = state.page === "stats" ? state.statsRange : state.range;
    const data = await api(`/api/dashboard?range=${range}`);
    if (seq !== loadSeq) return;
    renderAll(data);
    showLoading(false);
  } catch (e) {
    if (seq === loadSeq) showLoading(false);
    if (!quiet) console.error("dashboard load failed", e);
  }
}
function showLoading(show) { $("top-loading").hidden = !show; }

/* ---------------- 首页: 额度块 ---------------- */
function renderUsageBlocks(quota) {
  const row = $("usage-blocks");
  if (!quota || !quota.success) {
    if (quota && !quota.success) {
      clearTimeout(state.quotaRetryTimer);
      state.quotaRetryCount = 0;
      row.innerHTML = `<div class="ub ub-error">${t("quotaFail")}：${escapeHtml(quota.error || "?")}，${t("retryTip")}</div>`;
      return;
    }
    // quota 为 null (未登录/接口不可用): 有限次重试, 避免每 5 秒永久轮询
    if (state.quotaRetryTimer) clearTimeout(state.quotaRetryTimer);
    if ((state.quotaRetryCount || 0) >= 5) {
      state.quotaRetryCount = 0;
      return;  // 停止重试, 保留骨架; 下次 loadDashboard 会重新开始
    }
    state.quotaRetryCount = (state.quotaRetryCount || 0) + 1;
    state.quotaRetryTimer = setTimeout(() => loadDashboard(true), 5000);
    row.innerHTML = `<div class="ub skeleton"><div class="sk-line w40"></div><div class="sk-line w20 lg"></div><div class="sk-bar"></div><div class="sk-line w60"></div></div>`.repeat(3);
    return;
  }
  state.quotaRetryCount = 0;
  if (state.quotaRetryTimer) { clearTimeout(state.quotaRetryTimer); state.quotaRetryTimer = null; }
  // API Key 模式上游不返回 monthlyCreditsGranted, 后端回落到套餐映射 —— UI 需标明
  const monthlyEstimated = quota.monthly_granted_from_plan === true;
  const blocks = [];
  for (const w of quota.windows || []) {
    const pct = Math.max(0, Math.min(100, Number(w.used_percent) || 0));
    const reset = w.reset_in_sec > 0
      ? `${t("resetsIn")} ${fmtDur(w.reset_in_sec)}`
      : (w.exceeded ? t("used") : "—");
    const note = w.label === "Monthly" && monthlyEstimated ? ` · ${t("planEstimated")}` : "";
    blocks.push(`
      <div class="ub ${QUOTA_CLS[w.label] || "c-month"}">
        <div class="ub-head"><span class="ub-l">${(QUOTA_LABEL[w.label] || (() => escapeHtml(w.label)))()}</span><span class="ub-rem">${t("remaining")} ${fmtMoney(w.remaining)}</span></div>
        <div class="ub-bar"><div class="ub-bar-fill" style="width:${pct}%"></div></div>
        <div class="ub-meta"><span>${t("used")} ${fmtMoney(w.used)} / ${fmtMoney(w.total)} · ${fmtPercent(pct)}${note}</span><span>${reset}</span></div>
      </div>`);
  }
  if (!blocks.length) {
    blocks.push(`<div class="ub ub-error">${t("quotaNotReady")}</div>`);
  }
  row.innerHTML = blocks.join("");
}

/* ---------------- 首页: 用量概览 6 格 ---------------- */
function renderOverview(totals, cache) {
  totals = totals || {};
  cache = cache || {};
  const reqs = Number(totals.request_count) || 0;
  // 缓存命中率来自上游 5 分钟聚合桶; 桶尚未覆盖到该区间时显示「—」而非误导性的 0%
  const hasCache = Number(cache.bucket_count) > 0;
  const cacheCard = hasCache
    ? {
        cls: "c-cyan",
        l: t("cacheHitRate"),
        v: fmtPercent(cache.hit_rate),
        s: `${t("cacheRead")} ${fmtTokens(cache.cache_read_tokens)} · ${t("missTokens")} ${fmtTokens(cache.miss_tokens)}`,
      }
    : { cls: "c-cyan", l: t("cacheHitRate"), v: "—", s: t("cacheNoData") };
  const cards = [
    { cls: "c-amber", l: t("totalCost"), v: fmtMoney(totals.total_cost_usd), s: `${t("avgPer")} ${fmtMoney(totals.avg_cost_usd)}${t("perReq")}` },
    { cls: "c-slate", l: t("totalRequests"), v: fmtInt(reqs), s: `${t("currentRange")} · ${fmtInt(totals.model_count)} ${lang === "zh" ? "个模型" : "models"}` },
    { cls: "c-blue", l: t("totalTokens"), v: fmtTokens(totals.total_tokens), s: `${t("input")} ${fmtTokens(totals.total_input_tokens)} · ${t("output")} ${fmtTokens(totals.total_output_tokens)}` },
    cacheCard,
    { cls: "c-green", l: t("successRate"), v: fmtPercent(totals.success_rate), s: `${t("successCount")} ${fmtInt(totals.success_count)} · ${t("failedCount")} ${fmtInt(totals.failed_count)}` },
    { cls: "c-violet", l: t("avgDuration"), v: fmtMs(totals.avg_duration_ms), s: `${fmtInt(reqs)} ${t("requestsUnit")}` },
  ];
  $("overview-grid").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div><div class="kpi-s">${c.s}</div></div>`).join("");
}

/* ---------------- 首页: 今日趋势 24h ---------------- */
let cToday = null;
function chartToday(trend) {
  const canvas = $("today-chart");
  if (cToday) cToday.destroy();
  const box = canvas ? canvas.parentElement : null;
  if (box) box.classList.remove("sk-box");
  if (!trend || !trend.length) { cToday = null; return; }
  cToday = new Chart(canvas, {
    type: "bar",
    data: {
      labels: trend.map((d) => d.hour),
      datasets: [
        { label: t("input"), data: trend.map((d) => d.input), backgroundColor: COLOR.input, borderRadius: 2, barPercentage: 0.8 },
        { label: t("output"), data: trend.map((d) => d.output), backgroundColor: COLOR.output, borderRadius: 2, barPercentage: 0.8 },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
      },
    },
  });
  cToday.resize();
}

/* ---------------- 统计页: 4 总卡 + 6 明细 ---------------- */
function renderStatsTotal(totals) {
  totals = totals || {};
  const cards = [
    { cls: "c-amber", l: t("totalCost"), v: fmtMoney(totals.total_cost_usd), s: `${t("avgPer")} ${fmtMoney(totals.avg_cost_usd)}${t("perReq")}` },
    { cls: "c-slate", l: t("totalRequests"), v: fmtInt(totals.request_count), s: `${t("currentRange")} · ${fmtPercent(totals.success_rate)} ${t("successRate")}` },
    { cls: "c-blue", l: t("totalTokens"), v: fmtTokens(totals.total_tokens), s: `${t("input")} ${fmtTokens(totals.total_input_tokens)} · ${t("output")} ${fmtTokens(totals.total_output_tokens)}` },
    { cls: "c-violet", l: t("avgDuration"), v: fmtMs(totals.avg_duration_ms), s: `${fmtInt(totals.request_count)} ${t("requestsUnit")}` },
  ];
  $("stats-total-cards").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div><div class="kpi-s">${c.s}</div></div>`).join("");
}
function renderDetail6(totals, cache) {
  totals = totals || {};
  cache = cache || {};
  const tokens = Number(totals.total_tokens) || 0;
  const inTok = Number(totals.total_input_tokens) || 0;
  const outTok = Number(totals.total_output_tokens) || 0;
  const buckets = Number(cache.bucket_count) || 0;
  const noCache = t("cacheNoData");
  const cards = [
    { l: t("input"), v: fmtTokens(inTok), s: tokens ? fmtPercent(inTok / tokens * 100) : "0%" },
    { l: t("output"), v: fmtTokens(outTok), s: tokens ? fmtPercent(outTok / tokens * 100) : "0%" },
    { l: t("totalTokens"), v: fmtTokens(tokens), s: `${fmtInt(totals.request_count)} ${t("requestsUnit")}` },
    {
      l: t("cacheRead"),
      v: buckets ? fmtTokens(cache.cache_read_tokens) : "—",
      s: buckets ? `${t("cacheHitRate")} ${fmtPercent(cache.hit_rate)}` : noCache,
    },
    {
      l: t("cacheWrite"),
      v: buckets ? fmtTokens(cache.cache_creation_tokens) : "—",
      s: buckets ? `${t("missTokens")} ${fmtTokens(cache.miss_tokens)}` : noCache,
    },
    {
      l: t("cacheSavings"),
      v: buckets ? fmtMoney(cache.cache_savings) : "—",
      s: buckets ? t("fromBuckets") : noCache,
    },
    { l: t("inputCost"), v: fmtMoney(totals.total_input_cost), s: `${t("cacheCost")} ${fmtMoney(totals.total_cache_cost)}` },
    { l: t("outputCost"), v: fmtMoney(totals.total_output_cost), s: `${t("cacheCostRatio")} ${fmtPercent(totals.cache_cost_ratio)}` },
  ];
  $("stats-detail6").innerHTML = cards.map((c) => `
    <div class="tc"><div class="tc-l">${c.l}</div><div class="tc-v">${c.v}</div><div class="tc-s">${c.s}</div></div>`).join("");
}

/* ---------------- 统计页: 模型用量 ---------------- */
let cModel = null;
function chartModel(models) {
  const canvas = $("mr-chart");
  if (cModel) cModel.destroy();
  if (!models || !models.length) { cModel = null; $("mr-list").innerHTML = ""; return; }
  const dim = state.modelDim;
  const getVal = (m) => (dim === "input" ? m.total_input_tokens : dim === "output" ? m.total_output_tokens : m.total_cost_usd);
  const fmt = dim === "cost" ? (v) => fmtMoney(v) : fmtTokens;
  const sorted = [...models].sort((a, b) => getVal(b) - getVal(a));
  const top = sorted.slice(0, 6);
  const total = sorted.reduce((s, m) => s + getVal(m), 0);
  const palette = [COLOR.input, COLOR.output, COLOR.cost, COLOR.cache, COLOR.requests, "#ec4899"];
  cModel = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: top.map((m) => m.model),
      datasets: [{ data: top.map(getVal), backgroundColor: palette, borderWidth: 2, borderColor: cssVar("--card") }],
    },
    options: {
      responsive: false, maintainAspectRatio: false, cutout: "60%",
      plugins: {
        legend: { position: "right", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => ` ${it.label}: ${fmt(it.parsed)}${total ? ` (${((it.parsed / total) * 100).toFixed(1)}%)` : ""}` } },
      },
    },
  });
  cModel.resize();
  $("mr-list").innerHTML = sorted.slice(0, 3).map((m, i) => `
    <div class="mr-item"><span class="mr-rank">#${i + 1}</span>
    <span class="mr-name">${modelIcon(m.model)}<span class="txt">${escapeHtml(m.model)}</span></span>
    <span class="mr-sub">${fmtInt(m.request_count)} ${t("requestsUnit")}${m.hit_rate != null ? ` · ${t("cacheHitRate")} ${fmtPercent(m.hit_rate)}` : ""}</span>
    <span class="mr-cost">${fmtMoney(m.total_cost_usd)}</span></div>`).join("");
}

/* ---------------- 统计页: 用量趋势 ---------------- */
let cTrend = null;
function chartTrend(trend) {
  const canvas = $("trend-chart");
  if (cTrend) cTrend.destroy();
  if (!trend || !trend.length) { cTrend = null; return; }
  cTrend = new Chart(canvas, {
    data: {
      labels: trend.map((d) => d.date.slice(5)),
      datasets: [
        { type: "line", label: t("totalCost"), data: trend.map((d) => d.total_cost_usd), borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { type: "line", label: t("totalRequests"), data: trend.map((d) => d.request_count), borderColor: COLOR.output, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y1", borderDash: [4, 3] },
        { type: "line", label: t("totalTokens"), data: trend.map((d) => d.total_tokens), borderColor: COLOR.requests, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y2" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: {
          callbacks: {
            label: (item) => {
              if (item.dataset.label === t("totalTokens")) return ` ${item.dataset.label}: ${fmtTokens(item.parsed.y)}`;
              if (item.dataset.label === t("totalRequests")) return ` ${item.dataset.label}: ${fmtInt(item.parsed.y)}`;
              return ` ${item.dataset.label}: ${fmtMoney(item.parsed.y)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 } } },
        y2: { position: "right", display: false },
      },
    },
  });
  cTrend.resize();
}

/* ---------------- 每日用量 ---------------- */
let daySeq = 0;
async function loadDays() {
  const seq = ++daySeq;
  const body = $("day-body");
  const PAGE = state.days.pageSize;
  try {
    const q = new URLSearchParams({ page: state.days.page, page_size: PAGE });
    const data = await api(`/api/usage/days?${q}`);
    if (seq !== daySeq) return;
    state.days.total = data.total;
    $("day-count").textContent = `${t("totalN")} ${fmtInt(data.total)} ${t("dUnit")}`;
    if (!data.records.length) {
      body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:20px">${t("noData")}</td></tr>`;
    } else {
      let html = data.records.map((d) => `
        <tr><td>${escapeHtml(fmtDate(d.day))}</td>
        <td class="num">${fmtInt(d.request_count)}</td>
        <td class="num">${fmtPercent(d.success_rate)}</td>
        <td class="num">${fmtTokens(d.total_input_tokens)}</td>
        <td class="num">${fmtTokens(d.total_output_tokens)}</td>
        <td class="num">${fmtTokens(d.total_tokens)}</td>
        <td class="num">${fmtMs(d.avg_duration_ms)}</td>
        <td class="num">${fmtMoney(d.total_cost_usd)}</td></tr>`).join("");
      if (data.records.length < PAGE) {
        html += ('<tr>' + '<td>&nbsp;</td>'.repeat(8) + '</tr>').repeat(Math.max(0, PAGE - data.records.length));
      }
      body.innerHTML = html;
    }
    const totalPages = Math.max(1, Math.ceil(data.total / PAGE));
    $("day-pager").textContent = `${t("pageOf")} ${state.days.page} / ${totalPages} ${t("pages")}`;
    $("day-prev").disabled = state.days.page <= 1;
    $("day-next").disabled = state.days.page >= totalPages;
  } catch (e) {
    if (seq === daySeq) body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--red);padding:20px">${t("loadFailed")}: ${escapeHtml(e.message)}</td></tr>`;
  }
}

/* ---------------- 使用记录 ---------------- */
let recSeq = 0;
async function loadRecords() {
  const seq = ++recSeq;
  const body = $("records-body");
  const PAGE = state.records.pageSize;
  try {
    const q = new URLSearchParams({ page: state.records.page, page_size: PAGE });
    if (state.records.model) q.set("model", state.records.model);
    if (state.records.status) q.set("status", state.records.status);
    const data = await api(`/api/usage/records?${q}`);
    if (seq !== recSeq) return;
    state.records.total = data.total;
    const sel = $("rec-model-filter");
    sel.innerHTML = '<option value="">' + t("allModels") + '</option>' + data.models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
    sel.value = state.records.model || "";
    if (sel.value !== (state.records.model || "")) {
      // 当前筛选的模型已不在列表中 (被清理/改名): 同步回 state, 避免界面与查询条件脱节
      state.records.model = "";
      state.records.page = 1;
    }
    const ssel = $("rec-status-filter");
    if (ssel) ssel.value = state.records.status || "";
    $("rec-count").textContent = `${t("totalN")} ${fmtInt(data.total)} ${t("items")}`;
    if (!data.records.length) {
      body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:24px">${t("noData")}</td></tr>`;
    } else {
      let html = data.records.map((r) => {
        const ok = !r.status || r.status === "completed";
        return `
        <tr><td>${fmtDateTime(r.created_at)}</td>
        <td><span class="model-cell">${modelIcon(r.model)}${escapeHtml(r.model)}</span></td>
        <td class="num">${fmtTokens(r.input_tokens)}</td>
        <td class="num">${fmtTokens(r.output_tokens)}</td>
        <td class="num">${fmtTokens(r.total_tokens)}</td>
        <td class="num">${fmtMs(r.duration_ms)}</td>
        <td><span class="badge ${ok ? "ok" : "no"}">${escapeHtml(r.status || "—")}</span></td>
        <td class="num">${fmtMoney(r.cost_usd)}</td></tr>`;
      }).join("");
      if (data.records.length < PAGE) {
        html += ('<tr>' + '<td>&nbsp;</td>'.repeat(8) + '</tr>').repeat(Math.max(0, PAGE - data.records.length));
      }
      body.innerHTML = html;
    }
    const totalPages = Math.max(1, Math.ceil(data.total / PAGE));
    $("rec-pager").textContent = `${t("pageOf")} ${state.records.page} / ${totalPages} ${t("pages")}`;
    $("pg-prev").disabled = state.records.page <= 1;
    $("pg-next").disabled = state.records.page >= totalPages;
  } catch (e) {
    if (seq === recSeq) body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--red);padding:24px">${t("loadFailed")}: ${escapeHtml(e.message)}</td></tr>`;
  }
}

/* ---------------- 模型图标 ----------------
   Command Code 的模型 id 形如 "deepseek/deepseek-v4.1-flash"、"moonshotai/Kimi-K3"、
   "gpt-5.6-luna", 先按关键字匹配到图标, 未命中回落到 default.svg */
const MODEL_ICONS = [
  [/deepseek/i, "deepseek"],
  [/glm|zhipu/i, "glm"],
  [/kimi|moonshot/i, "kimi"],
  [/minimax|abab/i, "minimax"],
  [/qwen|tongyi/i, "qwen"],
  [/mimo/i, "mimo"],
  [/grok|x-?ai/i, "grok"],
  [/llama|meta/i, "meta"],
  [/hunyuan|\bhy\d?/i, "hy"],
  [/gpt|openai|o[1-9][\s-]|codex/i, "gpt"],
];
function modelIcon(m) {
  const s = String(m || "");
  const dark = document.documentElement.dataset.theme === "dark";
  let name = "default";
  for (const [re, icon] of MODEL_ICONS) {
    if (re.test(s)) { name = icon; break; }
  }
  const themed = dark && ["gpt", "grok", "mimo"].includes(name) ? `${name}-color` : name;
  return `<img src="icons/${themed}.svg" alt="${escapeHtml(m)}" title="${escapeHtml(m)}" data-model="${escapeHtml(m)}" style="width:16px;height:16px">`;
}
function refreshIcons() {
  if (!document.getElementById("page-stats").hidden) chartModel(state.data?.models);
  // 记录页的模型图标带主题变体 (暗色 -color.svg), 切主题时就地重建
  if (!document.getElementById("page-records").hidden) {
    document.querySelectorAll("#records-body img[data-model]").forEach((img) => {
      img.outerHTML = modelIcon(img.dataset.model);
    });
  }
}

/* ---------------- 组装 ---------------- */
function renderAll(data) {
  state.data = data;
  if (data.exchange_rate?.usd_cny) state.exchangeRate = data.exchange_rate.usd_cny;
  // 口径提示: API Key 模式只有账单周期汇总 (无明细/逐小时/按模型)
  const billingOnly = data.totals_source === "billing-period";
  const ovHint = $("ov-hint");
  if (ovHint) ovHint.textContent = billingOnly ? t("billingPeriodHint") : t("followRange");
  const todayHint = $("today-hint");
  if (todayHint) todayHint.textContent = billingOnly ? t("noHourlyData") : t("hours24");
  renderUsageBlocks(data.quota);
  renderOverview(data.totals, data.cache);
  const homeVisible = !document.getElementById("page-home").hidden;
  const statsVisible = !document.getElementById("page-stats").hidden;
  // 只重建当前可见页面的图表 (hidden 页面 canvas 尺寸为 0, 创建会失败)
  if (homeVisible) chartToday(data.today_trend);
  if (statsVisible) {
    renderStatsTotal(data.totals);
    renderDetail6(data.totals, data.cache);
    chartModel(data.models);
    chartTrend(data.trend);
    $("trend-hint").textContent = t("trendHint");
  }
  $("tb-sync").textContent = data.logged_in
    ? `${t("lastSync")} ${fmtRelative(data.sync?.last_sync_at)} · ${fmtInt(data.sync?.total_records || 0)} ${t("records")}`
    : t("notLoggedIn");
  const accLabel = data.account_name || data.account?.login || "";
  $("tb-login").innerHTML = data.logged_in ? `<b>${t("loggedIn")}</b>${accLabel ? " · " + escapeHtml(accLabel) : ""}` : t("notLoggedIn");
  $("tb-login").style.color = data.logged_in ? "" : "var(--red)";
  $("tb-login").title = t("userSwitchTip");
  const uc = $("tb-user-count");
  if (uc) {
    uc.hidden = !(Number(data.accounts_logged_in) > 0);
    uc.textContent = String(data.accounts_logged_in ?? 0);
    uc.title = t("userCountTip");
  }
  const st = data.server_time || "";
  if (st) $("tb-updated").textContent = `${t("updatedAt")} ${st.slice(0, 16).replace("T", " ")}`;
  renderSyncBanner(data.progress);
  renderSettingsSyncProgress(data.progress);
}

/* ---------------- 同步 ---------------- */
async function startSync(mode) {
  $("tb-refresh").disabled = true;
  $("btn-full-sync").disabled = true;
  try { await api("/api/sync?mode=" + mode, { method: "POST" }); } catch (e) { console.error(e); }
  pollUntilIdle();
}
function pollUntilIdle() {
  if (state.syncTimer) clearInterval(state.syncTimer);
  let failures = 0;
  state.syncTimer = setInterval(async () => {
    try {
      const st = await api("/api/state");
      failures = 0;
      renderSyncBanner(st.progress);
      renderSettingsSyncProgress(st.progress);
      if (!st.progress.running) {
        clearInterval(state.syncTimer); state.syncTimer = null;
        $("tb-refresh").disabled = false;
        $("btn-full-sync").disabled = false;
        await loadDashboard();
        if (state.page === "settings") renderSettings();
        if (state.page === "overview") loadOverview(true).catch(() => {});
      }
    } catch (e) {
      // /api/state 持续不可达: 退出轮询并恢复按钮, 避免永久禁用
      if (++failures >= 4) {
        clearInterval(state.syncTimer); state.syncTimer = null;
        $("tb-refresh").disabled = false;
        $("btn-full-sync").disabled = false;
        toast(t("loadFailed"), "err");
      }
    }
  }, 2500);
}
function renderSyncBanner(progress) {
  $("sync-indicator").hidden = !(progress && progress.running);
}
function renderSettingsSyncProgress(progress) {
  if (!progress || !progress.running) {
    $("set-sync-progress-desc").textContent = t("fullSyncDesc");
    $("set-sync-progress-val").textContent = "";
    return;
  }
  $("set-sync-progress-desc").textContent = `${t("syncing")}${progress.account ? " · " + progress.account : ""}`;
  $("set-sync-progress-val").textContent = `${t("totalN")} ${fmtInt(progress.inserted)}`;
  $("btn-full-sync").disabled = true;
  $("tb-refresh").disabled = true;
  if (!state.syncTimer) pollUntilIdle();
}

/* ---------------- 账户总览面板 (多账户聚合) ---------------- */
let ovSeq = 0;
let cOvTrendChart = null;
const OV_COLORS = ["#7c5cf6", "#4f8ef7", "#22c55e", "#d97706", "#06b6d4", "#ec4899"];

function applyOverviewPanel(show) {
  const btn = document.getElementById("side-overview");
  if (btn) btn.hidden = !show;
  if (!show && state.page === "overview") switchPage("home");
}

async function loadOverview(quiet = false) {
  const seq = ++ovSeq;
  if (!quiet) {
    const sKpi = `<div class="card kpi skeleton"><div class="sk-line w30"></div><div class="sk-line w40 lg"></div><div class="sk-line w50"></div></div>`;
    $("ov-summary-cards").innerHTML = sKpi.repeat(4);
    $("ov-accounts").innerHTML = `<div class="card ov-acc skeleton" style="height:140px"></div>`.repeat(2);
  }
  try {
    const data = await api("/api/accounts/overview");
    if (seq !== ovSeq) return;
    if (data.exchange_rate?.usd_cny) state.exchangeRate = data.exchange_rate.usd_cny;
    renderAccountOverview(data);
    const missing = (data.accounts || []).some((a) => a.logged_in && !a.quota);
    clearTimeout(state.ovRetryTimer);
    if (missing) state.ovRetryTimer = setTimeout(() => { if (state.page === "overview") loadOverview(true); }, 5000);
  } catch (e) {
    if (!quiet) toast(e.message || t("loadFailed"), "err");
  }
}

function renderAccountOverview(data) {
  const accounts = (data.accounts || []).map((a, i) => ({ ...a, color: OV_COLORS[i % OV_COLORS.length] }));
  const sum = accounts.reduce((acc, a) => {
    const tt = a.today || {};
    acc.req += tt.request_count || 0;
    acc.in += tt.total_input_tokens || 0;
    acc.out += tt.total_output_tokens || 0;
    acc.tok += tt.total_tokens || 0;
    acc.cost += tt.total_cost_usd || 0;
    return acc;
  }, { req: 0, in: 0, out: 0, tok: 0, cost: 0 });
  const cards = [
    { cls: "c-violet", l: t("todayTotalReq"), v: fmtInt(sum.req) },
    { cls: "c-blue", l: t("todayTotalTokens"), v: fmtTokens(sum.tok) },
    { cls: "c-cyan", l: t("todayTotalInput"), v: fmtTokens(sum.in) },
    { cls: "c-amber", l: t("todayTotalCost"), v: fmtMoney(sum.cost) },
  ];
  $("ov-summary-cards").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");

  chartOvTrend(accounts);

  $("ov-accounts").innerHTML = accounts.length
    ? accounts.map((a) => renderAccountCard(a)).join("")
    : `<div class="card ov-acc"><div class="ov-quota-empty">${t("noUsers")}</div></div>`;
}

function renderAccountCard(a) {
  let quotaHtml;
  const q = a.quota;
  if (q && q.success && (q.windows || []).length) {
    quotaHtml = `<div class="ov-quota-grid">${q.windows.map((w) => {
      const pct = Math.max(0, Math.min(100, Number(w.used_percent) || 0));
      return `<div class="ub ${QUOTA_CLS[w.label] || "c-month"} ov-ub">
        <div class="ub-head"><span class="ub-l">${(QUOTA_LABEL[w.label] || (() => escapeHtml(w.label)))()}</span><span class="ub-rem">${t("remaining")} ${fmtMoney(w.remaining)}</span></div>
        <div class="ub-bar"><div class="ub-bar-fill" style="width:${pct}%"></div></div>
        <div class="ub-meta"><span>${t("used")} ${fmtMoney(w.used)} / ${fmtMoney(w.total)}</span><span>${w.reset_in_sec > 0 ? t("resetsIn") + " " + fmtDur(w.reset_in_sec) : fmtPercent(pct)}</span></div>
      </div>`;
    }).join("")}</div>`;
  } else {
    quotaHtml = `<div class="ov-quota-empty">${q && q.error ? escapeHtml(t("quotaFail") + "：" + q.error) : t("quotaNotReady")}</div>`;
  }
  const tt = a.today || {};
  const spark = sparklineSvg((a.today_trend || []).map((d) => (Number(d.input) || 0) + (Number(d.output) || 0)), a.color);
  // 套餐名优先用后端映射 (quota.plan_name), 回退到前端兜底表/原始 planId
  const plan = q?.plan_name || (q?.plan_id ? (PLAN_NAMES[q.plan_id] || q.plan_id) : "");
  return `<div class="card ov-acc">
    <div class="ov-acc-head">
      <span class="ov-acc-name">${escapeHtml(a.name)}</span>
      <span class="ov-acc-badges">${a.active ? `<span class="plan-badge">${t("activeAccount")}</span>` : ""}${plan ? `<span class="plan-badge">${escapeHtml(plan)}</span>` : ""}${a.auth_type === "apikey" ? `<span class="plan-badge">${t("authApikey")}</span>` : ""}</span>
      <span class="ov-acc-sync">${t("lastSync")} ${fmtRelative(a.last_sync_at)}</span>
    </div>
    ${quotaHtml}
    <div class="tc-grid ov-today">
      <div class="tc"><div class="tc-l">${t("totalRequests")}</div><div class="tc-v">${fmtInt(tt.request_count)}</div></div>
      <div class="tc"><div class="tc-l">${t("input")}</div><div class="tc-v">${fmtTokens(tt.total_input_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("output")}</div><div class="tc-v">${fmtTokens(tt.total_output_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("colTotalTokens")}</div><div class="tc-v">${fmtTokens(tt.total_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("colCost")}</div><div class="tc-v">${fmtMoney(tt.total_cost_usd)}</div></div>
      <div class="tc"><div class="tc-l">${t("todayTrend")}</div><div class="tc-v ov-spark">${spark}</div></div>
    </div>
  </div>`;
}

/* 24h 迷你趋势: 纯 SVG 折线 (无 Chart 实例, 轻量随卡片渲染) */
function sparklineSvg(values, color) {
  const w = 120, h = 30, n = values.length;
  if (!n) return `<svg viewBox="0 0 ${w} ${h}" class="spark"></svg>`;
  const max = Math.max(...values, 1);
  const step = n > 1 ? w / (n - 1) : w;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`);
  return `<svg viewBox="0 0 ${w} ${h}" class="spark" preserveAspectRatio="none">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="0,${h} ${pts.join(" ")} ${w},${h}" fill="${color}" opacity="0.12" stroke="none"/>
  </svg>`;
}

/* 7 日费用对比: 全部账号合计为 总费用/请求/Token 三条线 */
function chartOvTrend(accounts) {
  const canvas = $("ov-trend-chart");
  if (!canvas) return;
  if (cOvTrendChart) { cOvTrendChart.destroy(); cOvTrendChart = null; }
  const dated = accounts.filter((a) => (a.daily7 || []).length);
  if (!dated.length) return;
  const dateSet = new Set();
  dated.forEach((a) => a.daily7.forEach((d) => dateSet.add(d.date)));
  const labels = [...dateSet].sort();
  const costSum = {}, reqSum = {}, tokSum = {};
  dated.forEach((a) => a.daily7.forEach((d) => {
    costSum[d.date] = (costSum[d.date] || 0) + (d.total_cost_usd || 0);
    reqSum[d.date] = (reqSum[d.date] || 0) + (d.request_count || 0);
    tokSum[d.date] = (tokSum[d.date] || 0) + (d.total_tokens || 0);
  }));
  cOvTrendChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: t("totalCost"), data: labels.map((dt) => costSum[dt] || 0), borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { label: t("totalRequests"), data: labels.map((dt) => reqSum[dt] || 0), borderColor: COLOR.output, borderWidth: 2, pointRadius: 1.5, tension: 0.3, borderDash: [4, 3], yAxisID: "y1" },
        { label: t("totalTokens"), data: labels.map((dt) => tokSum[dt] || 0), borderColor: COLOR.requests, borderWidth: 2, pointRadius: 1.5, tension: 0.3, borderDash: [4, 3], yAxisID: "y2" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => it.dataset.label === t("totalRequests") ? ` ${it.dataset.label}: ${fmtInt(it.parsed.y)}` : it.dataset.label === t("totalTokens") ? ` ${it.dataset.label}: ${fmtTokens(it.parsed.y)}` : ` ${it.dataset.label}: ${fmtMoney(it.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 7 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 } } },
        y2: { position: "right", display: false },
      },
    },
  });
  cOvTrendChart.resize();
}

/* ---------------- 设置页 ---------------- */
async function renderSettings() {
  try {
    const st = await api("/api/state");
    $("set-sync-info").textContent = st.sync && st.sync.last_sync_at
      ? `${t("lastSync")} ${fmtDateTime(st.sync.last_sync_at)} (${st.sync.last_sync_status || "-"}) · ${t("totalN")} ${fmtInt(st.sync.total_records || 0)} ${t("items")}`
      : t("never");
    $("set-datadir").textContent = st.datadir || "—";
    const urlEl = $("set-official-url");
    if (urlEl) urlEl.textContent = st.usage_page_url || "—";
    const link = $("about-usage-link");
    if (link && st.usage_page_url) link.href = st.usage_page_url;
    const settings = await api("/api/settings");
    state.settings = settings;
    syncSettingsPills();
    $("set-auto-sync").checked = settings.auto_sync !== false;
    $("set-overview-panel").checked = settings.show_accounts_panel === true;
    await fetchAccounts();
  } catch (e) { /* ignore */ }
}
function syncSettingsPills() {
  const s = state.settings;
  document.querySelectorAll("#set-interval-pills .pill").forEach((b) => b.classList.toggle("active", Number(b.dataset.v) === Number(s.sync_interval_sec)));
  document.querySelectorAll("#set-window-pills .pill").forEach((b) => b.classList.toggle("active", (s.window_days == null ? "all" : String(s.window_days)) === b.dataset.v));
}

/* ---------------- 多用户: 顶栏切换器 ---------------- */
let loginWatchTimer = null;
function startLoginWatch() {
  stopLoginWatch();
  let baseline = "";
  const startedAt = Date.now();
  const poll = async () => {
    if (Date.now() - startedAt > 5 * 60 * 1000) { stopLoginWatch(); return; }
    try {
      const r = await api("/api/accounts");
      const sig = JSON.stringify((r.accounts || []).map((a) => [a.id, a.has_token, a.name])) + "|" + r.active_id;
      if (!baseline) { baseline = sig; return; }
      if (sig !== baseline) {
        stopLoginWatch();
        await loadDashboard();
        if (state.page === "settings") renderSettings().catch(() => {});
        else if (state.page === "records") { loadDays().catch(() => {}); loadRecords().catch(() => {}); }
        if (state.page === "overview") loadOverview(true).catch(() => {});
      }
    } catch (e) { /* ignore */ }
  };
  poll();
  loginWatchTimer = setInterval(poll, 2000);
}
function stopLoginWatch() {
  if (loginWatchTimer) { clearInterval(loginWatchTimer); loginWatchTimer = null; }
}

async function toggleUserMenu(force) {
  const menu = $("user-menu");
  if (!menu) return;
  const show = force !== undefined ? force : menu.hidden;
  if (!show) { menu.hidden = true; return; }
  try {
    const r = await api("/api/accounts");
    renderUserMenu((r.accounts || []).filter((a) => a.has_token), r.active_id);
    menu.hidden = false;
  } catch (e) { toast(t("loadFailed"), "err"); }
}
function renderUserMenu(accounts, activeId) {
  const menu = $("user-menu");
  menu.innerHTML = (accounts.length ? accounts.map((a) => `
    <div class="um-item" data-id="${a.id}">
      <span class="um-check">${a.id === activeId ? "✓" : ""}</span>
      <span class="um-meta">
        <span class="um-name">${escapeHtml(a.name)}</span>
        <span class="um-ws">${escapeHtml(a.login || "—")}${a.has_token ? "" : " · " + t("notLoggedIn")}</span>
      </span>
    </div>`).join("") : `<div class="um-item um-empty">${t("noUsers")}</div>`) +
    `<div class="um-item um-manage" id="um-manage"><span class="um-check">⚙</span><span class="um-meta"><span class="um-name">${t("setUsers")}</span></span></div>`;
  menu.querySelectorAll(".um-item[data-id]").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = Number(el.dataset.id);
      toggleUserMenu(false);
      if (id === activeId) return;
      try {
        await api("/api/accounts/switch", { method: "POST", body: JSON.stringify({ id }) });
        toast(t("switchedAccount"));
        await loadDashboard();
        if (state.page === "settings") renderSettings().catch(() => {});
        else if (state.page === "records") { loadDays().catch(() => {}); loadRecords().catch(() => {}); }
        if (state.page === "overview") loadOverview(true).catch(() => {});
      } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    });
  });
  const mg = $("um-manage");
  if (mg) mg.addEventListener("click", () => { toggleUserMenu(false); switchPage("settings"); });
}

/* ---------------- 多用户: 设置页列表 ---------------- */
async function fetchAccounts() {
  const r = await api("/api/accounts");
  renderUsersList(r.accounts || [], r.active_id);
}
function renderUsersList(accounts, activeId) {
  const box = $("users-list");
  if (!box) return;
  const users = (accounts || []).filter((a) => a.has_token);
  if (!users.length) {
    box.innerHTML = `<div class="hint" style="padding:12px 16px">${t("noUsers")}</div>`;
    return;
  }
  box.innerHTML = users.map((a) => {
    const isActive = a.id === activeId;
    const actions = isActive
      ? `<button class="btn" data-act="relogin">${t("relogin")}</button>
         <button class="btn" data-act="rename">${t("renameBtn")}</button>
         <button class="btn btn-danger" data-act="logout">${t("logout")}</button>`
      : `<button class="btn" data-act="switch">${t("switchTo")}</button>
         <button class="btn" data-act="rename">${t("renameBtn")}</button>
         <button class="btn btn-danger" data-act="delete">${t("deleteUser")}</button>`;
    return `
    <div class="user-row${isActive ? " active" : ""}" data-id="${a.id}">
      <div class="ur-meta">
        <div class="ur-name">${escapeHtml(a.name)}${isActive ? `<span class="badge ok ur-badge">${t("currentUserBadge")}</span>` : ""}</div>
        <div class="ur-ws">${escapeHtml(a.login || "—")} · ${t("loggedIn")} · ${a.auth_type === "apikey" ? t("authApikey") : t("authCookie")}</div>
      </div>
      <div class="ur-actions">${actions}</div>
    </div>`;
  }).join("");
}
async function onUserRowAction(id, act) {
  if (act === "switch") {
    try {
      await api("/api/accounts/switch", { method: "POST", body: JSON.stringify({ id }) });
      toast(t("switchedAccount"));
      await loadDashboard();
      renderSettings().catch(() => {});
      if (state.page === "overview") loadOverview(true).catch(() => {});
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    return;
  }
  if (act === "relogin") {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("relogin"); return; }
    try {
      await api("/api/relogin", { method: "POST", body: "{}" });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    return;
  }
  if (act === "logout") {
    const accounts = (await api("/api/accounts").catch(() => ({ accounts: [] }))).accounts || [];
    const acc = accounts.find((x) => x.id === id);
    showModal({
      title: t("logout"), danger: true,
      message: escapeHtml(t("logoutUserConfirm").replace("{name}", acc ? acc.name : "")),
      okText: t("confirm"),
      onOk: async () => {
        try {
          await api("/api/logout", { method: "POST", body: "{}" });
          toast(t("loggedOut"));
          const r = await api("/api/accounts").catch(() => ({ accounts: [] }));
          renderUsersList(r.accounts || [], r.active_id);
          await loadDashboard();
          if (state.page === "overview") loadOverview(true).catch(() => {});
          if (!(r.accounts || []).some((x) => x.has_token)) showLoginOverlay(true);
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
    return;
  }
  const accounts = (await api("/api/accounts").catch(() => ({ accounts: [] }))).accounts || [];
  const acc = accounts.find((x) => x.id === id);
  if (act === "rename") {
    let renamed = acc ? acc.name : "";
    showModal({
      title: t("renameTitle"),
      message: `<input id="rename-input" class="select" maxlength="50" value="${escapeHtml(renamed)}">`,
      okText: t("save"),
      onOk: async () => {
        try {
          await api("/api/accounts/rename", { method: "POST", body: JSON.stringify({ id, name: renamed }) });
          toast(t("userRenamed"));
          renderSettings().catch(() => {});
          loadDashboard(true);
          if (state.page === "overview") loadOverview(true).catch(() => {});
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
    const input = $("rename-input");
    if (input) {
      input.addEventListener("input", () => { renamed = input.value; });
      input.focus();
    }
    return;
  }
  if (act === "delete") {
    showModal({
      title: t("deleteUserTitle"), danger: true,
      message: escapeHtml(t("deleteUserConfirm").replace("{name}", acc ? acc.name : `#${id}`)),
      okText: t("confirm"),
      onOk: async () => {
        try {
          const r = await api("/api/accounts/delete", { method: "POST", body: JSON.stringify({ id }) });
          toast(t("userDeleted"));
          await loadDashboard();
          renderSettings().catch(() => {});
          if (state.page === "overview") loadOverview(true).catch(() => {});
          if ((r.remaining ?? 1) === 0) showLoginOverlay(true);
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
  }
}

/* ---------------- API Key 登录 (备选认证) ---------------- */

/* 提示输入 API Key → 交给后端校验 (/api/login/apikey)。仅 /alpha/* 可用,
   因此功能限于额度与汇总: 官方该组接口没有请求级明细与缓存桶。 */
function promptApiKey(mode = "relogin") {
  let key = "";
  showModal({
    title: t("apikeyTitle"),
    message: `<div class="hint" style="margin-bottom:8px;line-height:1.5">${t("apikeyHint")}</div>`
      + `<input id="apikey-input" class="select" style="width:100%" `
      + `placeholder="${escapeHtml(t("apikeyPlaceholder"))}" autocomplete="off">`,
    okText: t("ok"),
    onOk: async () => {
      const value = key.trim();
      if (!value) { toast(t("apikeyEmpty"), "err"); return false; }  // 校验未过: 留在弹窗
      try {
        await api(`/api/login/apikey?mode=${mode}`, {
          method: "POST",
          body: JSON.stringify({ key: value }),
        });
        toast(t("apikeyOk"));
        showLoginOverlay(false);
        await loadDashboard();
        renderSettings().catch(() => {});
        if (state.page === "overview") loadOverview(true).catch(() => {});
      } catch (e) {
        toast(e.message || t("apikeyInvalid"), "err");
      }
    },
  });
  const input = $("apikey-input");
  if (input) {
    input.addEventListener("input", () => { key = input.value; });
    input.focus();
  }
}

/* ---------------- 登录状态 ---------------- */
let loginPollTimer = null;
function showLoginOverlay(show) {
  $("login-overlay").hidden = !show;
  if (show) {
    if (loginPollTimer) clearInterval(loginPollTimer);
    loginPollTimer = setInterval(async () => {
      try {
        const st = await api("/api/state");
        if (st.logged_in) {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          showLoginOverlay(false);
          await loadDashboard();
          renderSettings().catch(() => {});
          if (state.page === "overview") loadOverview(true).catch(() => {});
        }
      } catch (e) { /* ignore */ }
    }, 2000);
  } else if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
}
let stateRetryCount = 0;
async function checkState() {
  try {
    const st = await api("/api/state");
    stateRetryCount = 0;
    if (!st.logged_in) { showLoginOverlay(true); return; }
    showLoginOverlay(false);
    if (st.progress && st.progress.running) pollUntilIdle();
    await loadDashboard();
  } catch (e) {
    console.error("state check failed", e);
    // 启动时后端尚未就绪: 有限次自动重试, 避免首屏永久空白
    if (++stateRetryCount <= 10) setTimeout(checkState, 3000);
  }
}

/* 登录成功通知 (后端 evaluate_js 触发): 就地刷新数据/顶栏/账户列表 */
window.cmdgaugeOnLoginSuccess = async function () {
  try {
    const st = await api("/api/state");
    if (st.logged_in) showLoginOverlay(false);
  } catch (e) { /* ignore */ }
  loadDashboard().catch(() => {});
  if (state.page === "settings") renderSettings().catch(() => {});
  else if (state.page === "records") { loadDays().catch(() => {}); loadRecords().catch(() => {}); }
};

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  document.querySelectorAll(".side-item").forEach((btn) => btn.addEventListener("click", () => switchPage(btn.dataset.page)));

  document.querySelectorAll("#home-pills .pill").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#home-pills .pill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.range = b.dataset.r; loadDashboard();
  }));
  document.querySelectorAll("#stats-pills .pill").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#stats-pills .pill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.statsRange = b.dataset.r; loadDashboard();
  }));
  $("mr-dim").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#mr-dim button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.modelDim = b.dataset.dim;
    if (state.data) chartModel(state.data.models);
  });
  $("tb-refresh").addEventListener("click", () => startSync("incremental"));
  $("btn-full-sync").addEventListener("click", () => {
    showModal({ title: t("fullSync"), message: t("fullSyncConfirm"), okText: t("startSync"), onOk: () => startSync("full") });
  });
  $("pg-prev").addEventListener("click", () => { if (state.records.page > 1) { state.records.page--; loadRecords(); } });
  $("pg-next").addEventListener("click", () => { state.records.page++; loadRecords(); });
  $("day-prev").addEventListener("click", () => { if (state.days.page > 1) { state.days.page--; loadDays(); } });
  $("day-next").addEventListener("click", () => { state.days.page++; loadDays(); });
  $("rec-model-filter").addEventListener("change", (e) => { state.records.model = e.target.value; state.records.page = 1; loadRecords(); });
  const sfil = $("rec-status-filter");
  if (sfil) sfil.addEventListener("change", (e) => { state.records.status = e.target.value; state.records.page = 1; loadRecords(); });
  const obtn = $("btn-open-official");
  if (obtn) obtn.addEventListener("click", () => { api("/api/open/usage", { method: "POST" }).catch(() => {}); });

  $("btn-check-update").addEventListener("click", async () => {
    const btn = $("btn-check-update");
    const desc = $("set-update-desc");
    const prevText = btn.textContent;
    btn.disabled = true;
    btn.textContent = t("checkingUpdate");
    try {
      const r = await api("/api/update/check");
      if (r.error) throw new Error(r.error);
      if (r.has_update) {
        desc.textContent = `${t("updateFound")} ${r.latest}`;
        showModal({
          title: t("updateFound"),
          message: `<b>${escapeHtml(r.latest)}</b> (${t("currentVersion")} v${escapeHtml(r.current)})<br><br>${escapeHtml((r.notes || "").slice(0, 300)) || ""}`,
          okText: t("goDownload"),
          onOk: () => { api("/api/update/open", { method: "POST" }).catch(() => {}); },
        });
      } else {
        desc.textContent = `${t("updateNone")} (v${r.current})`;
        toast(t("updateNone"));
      }
    } catch (e) {
      desc.textContent = `${t("updateFailed")}: ${t("checkUpdateDesc")}`;
      showModal({ title: t("updateFailed"), message: escapeHtml(e.message || ""), okText: t("ok") });
    } finally {
      btn.disabled = false;
      btn.textContent = prevText;
    }
  });

  document.querySelectorAll("#set-interval-pills .pill").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ sync_interval_sec: Number(b.dataset.v) }) });
    state.settings = await api("/api/settings");
    syncSettingsPills(); restartAutoSync(); toast(`${t("syncIntervalSet")} ${b.textContent}`);
  }));
  document.querySelectorAll("#set-window-pills .pill").forEach((b) => b.addEventListener("click", async () => {
    const v = b.dataset.v === "all" ? null : Number(b.dataset.v);
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ window_days: v }) });
    state.settings = await api("/api/settings");
    syncSettingsPills();
    toast(t("syncRangeUpdated"));
  }));
  document.querySelectorAll("#set-theme-pills .pill").forEach((b) => b.addEventListener("click", () => applyDarkMode(b.dataset.v === "dark")));
  document.querySelectorAll("#set-currency-pills .pill").forEach((b) => b.addEventListener("click", () => applyCurrency(b.dataset.v)));
  document.querySelectorAll("#set-lang-pills .pill").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.v)));
  $("set-auto-sync").addEventListener("change", (e) => {
    state.settings.auto_sync = e.target.checked;
    api("/api/settings", { method: "PUT", body: JSON.stringify({ auto_sync: e.target.checked }) }).catch(() => {});
    restartAutoSync();
  });
  $("set-overview-panel").addEventListener("change", (e) => {
    state.settings.show_accounts_panel = e.target.checked;
    api("/api/settings", { method: "PUT", body: JSON.stringify({ show_accounts_panel: e.target.checked }) }).catch(() => {});
    applyOverviewPanel(e.target.checked);
  });

  $("tb-login").addEventListener("click", () => toggleUserMenu());
  document.addEventListener("click", (e) => {
    const menu = $("user-menu");
    if (menu && !menu.hidden && !e.target.closest(".user-switch")) toggleUserMenu(false);
  });
  $("btn-add-user").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("add"); return; }
    try {
      await api("/api/accounts/add", { method: "POST", body: "{}" });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
  });
  $("users-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const row = e.target.closest(".user-row");
    if (!row) return;
    onUserRowAction(Number(row.dataset.id), btn.dataset.act).catch((err) => toast(String(err.message || err), "err"));
  });
  $("btn-login").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login(); return; }
    $("btn-login").disabled = true;
    $("btn-login").textContent = t("loginBtn") + "…";
    await api("/api/relogin", { method: "POST" });
  });
  $("btn-quit-app").addEventListener("click", async () => {
    const a = await pywebviewApi();
    if (a) a.quit();
  });
  // API Key 登录入口 (欢迎页 / 设置页)
  const apkLogin = $("btn-login-apikey");
  if (apkLogin) apkLogin.addEventListener("click", () => promptApiKey("relogin"));
  const apkAdd = $("btn-add-apikey");
  if (apkAdd) apkAdd.addEventListener("click", () => promptApiKey("add"));
  bindTitlebar();
  bindWindowResize();
}

/* ---------------- 自动同步 ---------------- */
let autoSyncTimer = null;
function restartAutoSync() {
  if (autoSyncTimer) clearInterval(autoSyncTimer);
  if (state.settings.auto_sync === false) return;
  const sec = Math.max(30, Number(state.settings?.sync_interval_sec) || 300) * 1000;
  autoSyncTimer = setInterval(() => {
    const prog = state.data && state.data.progress;
    if (!prog || !prog.running) startSync("incremental");
  }, sec);
}

/* ---------------- 图表辅助 ---------------- */
function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim() || "#8a94a8";
}
function rerenderCharts() {
  if (!state.data) return;
  if (!document.getElementById("page-home").hidden) chartToday(state.data.today_trend);
  if (!document.getElementById("page-stats").hidden) {
    chartModel(state.data.models);
    chartTrend(state.data.trend);
  }
  if (!document.getElementById("page-overview").hidden) {
    // 总览页: 账号卡片已渲染过时重建 (chartOvTrend 依赖 accounts, 从卡片数据重取)
    loadOverview(true).catch(() => {});
  }
}

/* 窗口尺寸变化: 长防抖 (250ms) 后执行一次轻量 chart.resize()
   (只处理可见页图表 — hidden 页面容器尺寸为 0, resize() 会死循环卡死) */
function safeResize(chart) {
  if (!chart || !chart.canvas) return;
  const box = chart.canvas.parentElement;
  if (box && box.clientWidth > 0 && box.clientHeight > 0) chart.resize();
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!document.getElementById("page-home").hidden) safeResize(cToday);
    if (!document.getElementById("page-stats").hidden) {
      safeResize(cModel);
      safeResize(cTrend);
    }
    if (!document.getElementById("page-overview").hidden) safeResize(cOvTrendChart);
  }, 250);
});

/* ---------------- 启动 ---------------- */
let APP_VERSION = "";
(async function init() {
  let dark = false, cur = "USD", l = "zh";
  try {
    dark = localStorage.getItem("cmdgauge-dark") === "1";
    cur = localStorage.getItem("cmdgauge-currency") || "USD";
    l = localStorage.getItem("cmdgauge-lang") || "zh";
  } catch (e) { /* ignore */ }
  try { const v = await api("/api/version"); APP_VERSION = v.version || ""; } catch (e) { /* ignore */ }
  applyLang(l);
  applyDarkMode(dark);
  applyCurrency(cur);
  bindEvents();
  try { state.settings = await api("/api/settings"); } catch (e) { /* ignore */ }
  syncSettingsPills();
  $("set-auto-sync").checked = state.settings.auto_sync !== false;
  $("set-overview-panel").checked = state.settings.show_accounts_panel === true;
  applyOverviewPanel(state.settings.show_accounts_panel === true);
  await checkState();
  restartAutoSync();
})();
