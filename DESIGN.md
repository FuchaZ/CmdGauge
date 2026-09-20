# CmdGauge 移植设计说明

从 [opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge)（GoGauge）移植到 Command Code，
沿用其技术栈与整体骨架（Python + pywebview/WebView2 + SQLite + 本地 HTTP + Chart.js + pystray），
替换数据源与数据模型。

> **文档订正记录（v1.1）**：初版曾写「接口不提供缓存 token 维度、命中率无法计算」，
> 这是**错的** —— `/internal/usage/charts` 带 `from`/`to` 时会返回
> `cacheReadInputTokens` / `cacheCreationInputTokens` / `cacheSavings`。
> 该发现来自同类项目 [goat-gauge](https://github.com/langjinusi985360/goat-gauge)，
> 已实测证实并据此新增 `usage_buckets` 存储与缓存指标展示。

## 1. 数据源（实测确认）

API 域名 `https://api.commandcode.ai`，存在**两套端点族**：

### A. `/internal/*` —— 网站自用，cookie 认证

| 用途 | 端点 | 备注 |
|---|---|---|
| 请求明细（游标分页） | `GET /internal/usage?limit=&cursor=&orgId=&targetUserId=` | 见下方限制 |
| 用量汇总 | `GET /internal/usage/summary` | 按账单周期 |
| **5 分钟聚合桶** | `GET /internal/usage/charts?from=<ISO8601>&to=<ISO8601>` | **缓存 token 唯一来源** |
| 额度 / 窗口 | `GET /internal/billing/credits` | 5h / weekly 窗口 + 月度额度 |
| 订阅 | `GET /internal/billing/subscriptions` | planId / 账单周期 |
| 组织 | `GET /internal/orgs` | 个人账号为空 |
| 模型目录 | `GET /internal/models` | 71 个模型 |
| 用户资料 | `GET /internal/profile/{login}` | 站点无「当前用户」端点 |

### B. `/alpha/*` —— 官方 CLI 自用，`Authorization: Bearer <apiKey>`

| 用途 | 端点 |
|---|---|
| 身份 | `GET /alpha/whoami` |
| 额度 | `GET /alpha/billing/credits` |
| 订阅 | `GET /alpha/billing/subscriptions` |
| 汇总 | `GET /alpha/usage/summary` |

`/alpha/*` 用 cookie 会 401（其 CORS 也不允许凭据，所以官网从不这样调）；
`/internal/*` 用 API Key 亦不可用。两者是**互斥**的认证通道。

### 能力边界（全部实测）

| 限制 | 说明与本面板对策 |
|---|---|
| 明细窗口固定 `{days: 1, entries: 100}` | `days`/`since`/`window`/`range`/`period` 参数**全部被忽略**，`limit` 上限 100（超出 400）。→ **增量同步 + 本地 SQLite 累积**，长期运行即得完整历史 |
| charts 窗口极小 | `from`/`to` 必须是 ISO 8601（传 epoch 毫秒 → 400）；不传或只传一个 → 空数组；且服务端只回窗口内**有数据**的最近约 7 个桶（5 分钟粒度，跨度约 35 分钟）。→ 每次同步都拉（默认 5 分钟一次）以连续累积 |
| 明细项无 session / key / reasoning 维度 | 只有 token 数、三段成本与耗时。→ 「会话历史」改为**「每日用量」** |
| `/alpha/*` 无请求级明细 | 官方 CLI 只做聚合。→ API Key 模式下**明确降级**：仅额度与汇总，不产生明细与缓存指标（UI 已标注） |
| 月度窗口非 API 字段 | API 无月度窗口对象，`monthlyCreditsGranted` 直接给出额度，故无需从 plan 映射反推 |

## 2. 数据模型映射

### `usage_records`（请求级明细）

| 原字段 (GoGauge) | 新字段 (CmdGauge) | 来源 |
|---|---|---|
| `usg_id` / `created_at` | 同名 | `id` / `createdAt` |
| `model` | 同名 | `meta.model` |
| `input_tokens` / `output_tokens` | 同名 | `tokensIn` / `tokensOut`（字符串→int） |
| `cost_usd` | 同名 | `meta.totalCost` |
| — | `input_cost` / `output_cost` / `cache_cost` | `meta.inputCost` / `outputCost` / `cacheCost` |
| — | `duration_ms` / `status` / `mode` / `type` | `durationTotal` / 同名字段 |
| `reasoning_tokens`、`cache_read_tokens`、`cache_write_*`、`key_id`、`session_id`、`plan`、`provider` | — | **明细项不提供**（缓存维度改由 `usage_buckets` 提供） |

### `usage_buckets`（5 分钟聚合桶，缓存 token 维度）

主键 `(bucket_key, account_id)`，`bucket_key = model|timeBucket`。
字段：`requests`、`tokens_in/out/total`、`input/output/cache/total_cost`、
`cache_savings`、`cache_read_tokens`、`cache_creation_tokens`、
`consumed_free/monthly/purchased/total`、`credits_total`。

**同桶是累计值**，重复拉取必须**覆盖式 upsert**（累加会重复计数）。
实测 11 个数值字段与 `/internal/usage/summary` 完全对账。

### 缓存口径

- 命中率 = `cache_read_tokens / tokens_in`
- 未命中 = `tokens_in − cache_read_tokens`
- `cache_savings` = 上游给出的「因缓存省下的金额」（实测可达总花费的 10 倍以上）
- 桶尚未覆盖到某区间时，UI 显示「—」而非误导性的 0%

### 认证与账号

`accounts.auth_type ∈ {cookie, apikey}`，`token` 字段在两种模式下分别存 Cookie 串 / API Key；
`login` / `org_id` 用于展示与构造官方用量页链接。

### 配额窗口（实时拉取，30s 缓存，不落库）

| 卡片 | 数据 |
|---|---|
| 5 小时窗口 | `windowLimits.fiveHour.{used, cap, exceeded, resetAt}` |
| 每周窗口 | `windowLimits.weekly.*` |
| 月度额度 | `credits.monthlyCreditsGranted`（额度）/ `credits.monthlyCredits`（剩余） |

### 套餐映射

`PLAN_INFO`（社区从官方 CLI 逆推，**仅用于展示**）：
`individual-go`=10、`goat`=70、`pro`=30、`pro-v1`=80、`provider`=15、`max`=150、`ultra`=300、`teams-pro`=40。
真实额度一律以 `monthlyCreditsGranted` 为准（实测 `individual-go` = 10，与之吻合）。

## 3. 页面范围

| 页面 | 处置 |
|---|---|
| 主页 | 3 张配额卡 + 6 张概览卡（含**缓存命中率**）+ 今日 24h 趋势 |
| 用量统计 | 4 总卡 + **8 格** Token/成本构成（输入/输出/总TOKEN/缓存读/缓存写/缓存节省/输入成本/输出成本）+ 模型排行（带命中率）+ 三线趋势 |
| 使用记录 | 每日用量（按天聚合）+ 请求明细，支持模型/状态筛选 |
| 账户总览 | 多账号配额与用量聚合 |
| 设置 | 同步间隔 / 本地保留范围 / 自动同步 / 主题 / 语言 / 官方用量页 / 账号管理（浏览器登录 + API Key） |

## 4. 同步策略

- 明细：`limit=100` 起，`nextCursor` 翻页到底（最多 20 页防失控），按 `usg_id` upsert。
- 聚合桶：每次同步都拉最近 1 天窗口，按 `(bucket_key, account_id)` **覆盖式** upsert 以累积历史。
- 本地保留范围（30/60/90/180 天 / 所有）同时裁剪明细与桶。
- API Key 账号跳过明细与桶同步，仅标记同步完成后由 dashboard 拉配额。
- **定时由后端常驻调度线程驱动**（`cmdgauge-sched`），不再依赖前端 `setInterval`；每轮先**顺序刷新全部已登录账号的配额**（单账号失败不中断），再跑增量同步。会话保活另行每 6 小时探测一次，不受 `auto_sync` 开关影响。

## 5. 已验证 / 降级项

### API Key 模式（已用真实 key 实测）

认证格式 `Authorization: Bearer <key>` 已确认（key 形如 `user_...`）。实测结论：

| 端点 | 结果 |
|---|---|
| `/alpha/whoami` | OK → `{success, user:{id,name,email,userName}, org:null}`，据此回填 login |
| `/alpha/billing/credits` | OK，但**不含** `monthlyCreditsGranted`（`/internal` 版本才有） |
| `/alpha/billing/subscriptions` | OK，结构与 `/internal` 一致 |
| `/alpha/usage/summary` | OK，数值与 `/internal/usage/summary` **完全一致** |
| `/internal/*` + Bearer | **全部 401** → 双通道互斥，API Key 拿不到明细与缓存桶 |

**因此**：额度缺失时回落套餐映射（`monthly_granted_from_plan=true` 会在 API 响应里标出，
UI 对月度卡标注「额度按套餐估算」）；两模式的 5h/weekly/monthly 数值实测完全一致。

### 其他降级项

- `/internal/api-keys/list` 返回 404，未纳入。
- `usage_buckets` 只能覆盖「本机同步时上游窗口内存在的数据」，关机期间产生的桶无法补回。
- charts 端点窗口约 35 分钟，长时间不开机就会缺该时段的缓存指标（明细同理）。

## 6. 修复记录（v1.1）

| 现象 | 根因 | 修复 |
|---|---|---|
| 浏览器登录卡在「正在重定向到已授权应用」页 | OAuth 的 `redirect_uri` 落在 **`api.commandcode.ai/auth/callback`**，而 watcher 用 `SITE_HOST in url` 判断，把 api 子域误认为「已回到站点」，于是只反复查 cookie、**永远不进兜底分支** | 新增 `host_of` / `needs_nudge`：api 子域一律视为自动流程页；GitHub 仅在「重定向回应用」页干预；卡住超时后先点击页面上的 setup/continue 链接，无效则导航回站点。日志改为记录**所有** URL 变化与 cookie 名单，便于定位 |
| API Key 登录后「用量概览」全是 0（但月度额度有值） | `/alpha/usage/summary` 本来有数据却从未被使用；且 `/alpha/billing/credits` **不返回** `monthlyCreditsGranted`（只有 `/internal` 版本才有），导致月度卡片 `used = granted(0) − 剩余` 被夹成 0 | 新增 `account_summaries` 表与 `summary_as_totals`：apikey 同步时保存账单汇总，dashboard 据此兜底并返回 `totals_source`；额度缺失时回落套餐映射并标记 `monthly_granted_from_plan`，UI 标注「额度按套餐估算」 |
| 程序窗口无法调整大小 | `frameless=True` → WinForms `FormBorderStyle.None`，系统不再提供边框拖拽 | 前端 6px 边缘热区捕获拖拽（捕获阶段先于标题栏拖动逻辑）+ 后端 `resize_by` → `SetWindowPos`；几何计算抽成纯函数 `_compute_resized_rect` 并夹紧 `WINDOW_MIN_SIZE` |

## 7. 修复记录（v1.0.2）

| 现象 | 根因 | 修复 |
|---|---|---|
| **高 DPI/缩放屏拖窗口不跟手**（窗口只以鼠标 1/scale 速度移动，实测 1.375 屏上 300px 拖动只走 218px） | Chromium/WebView2 的 `MouseEvent.screenX/screenY` 是 **DIP(逻辑像素)**，而 `move_by`/`resize_by` 按 `GetWindowRect` 的**物理像素**直接累加；v1.0.1 注释「screenX 已是物理像素」的假设错误（实测本机 system DPI=1.25 而显示器有效缩放=1.375，两者还不同） | 前端增量统一 **× `devicePixelRatio`** 换算为物理像素，浮点累积 + 发整数 + 小数余量留到下帧（无取整漂移）；`app.js` bindTitlebar/bindWindowResize。SendInput 实测修复后 300px 拖动窗口走 300px（±取整 ≤3px） |
| mouseup 丢失后「幽灵拖动」/拖动与缩放同时残留 | mousemove 不校验 `e.buttons`，无 blur 兜底；`#user-menu` 内的 div 菜单项还会误触发窗口拖动 | mousemove 检测 `!(e.buttons & 1)` 即终止手势；补 `window.blur` 终止；mousedown 过滤选择器加 `#user-menu` |
| **SQLite 连接按请求泄漏**（实测 50 请求泄 50 条，永不回收 → 长驻句柄耗尽） | `_Handler` 未设 `protocol_version`（HTTP/1.0 每请求一线程），线程内连接被 `_ALL_CONNS` 永久持有；同步/配额 worker 线程同理 | `_Handler` 改 `HTTP/1.1` keep-alive（线程与线程内连接复用）+ `finish()` 里 `db.close_thread_conn()`；sync/quota worker 与登录 watcher 线程退出时同样回收。实测 50 请求 → 0 常驻连接 |
| 静态服务可读任意本机文件（`GET /C:/...`） | `os.path.join` 遇盘符绝对路径/UNC 整体重置，仅挡 `..` 无效；且无 Host 校验（DNS rebinding 面） | `_static_response` 解析后强制路径位于资源根内（realpath 前缀校验）；新增 `_host_allowed`（仅 127.0.0.1/localhost/::1）于所有入口校验 Host |
| delete_account / 退出登录留孤儿数据 | `usage_buckets` / `account_summaries` 无外键，级联删除管不到 | 两处显式 `DELETE FROM usage_buckets / account_summaries` |
| settings 并发读-改-写丢更新 | 整包 JSON 无锁并发覆盖 | 新增 `_settings_lock` 串行化 `_persist_active` 与 `save_settings`；`get_active_account_id` 自动回落路径改「值变化才写」防写放大 |
| 一个账号 cookie 过期 → 多账号自动同步整个卡死 | incremental 循环遇错即 return，剩余账号不再同步 | 改为继续同步全部账号，结束时汇总：全部失败 `ok=False`（同时修掉 full 模式唯一目标失败仍 `ok=True` 的假成功），部分失败 `ok=True, partial=True, errors=[...]` |
| 杂项 | —— | 未知 /api 路由返回 JSON 404；请求体 Content-Length 加固（非法/超大 400，上限 1MiB）；handler `timeout=120` 防永久阻塞；汇率拉取失败只短路 5 分钟（原失败被当新鲜缓存 6 小时）并加并发去重锁；`_ensure_quota_async` 防重入检查原子化；`bool("false")` 严格转换；logout/delete 与在飞同步互斥（409）；前端：更新弹窗 `latest/current` 转义、quota null 重试上限、轮询持续失败自恢复、`repeat` 负数保护、模型筛选失联回退、sparkline NaN、`fmtMoney` 负数、主题切换后总览图表与记录页图标刷新、`showModal` onOk 可保持弹窗（API Key 空输入不再丢）、启动失败自动重试、`commandcode_api.py` 重复 `fetch_profile` 去重 |

## 8. 多账号配额全覆盖 + 会话保活（v1.0.3）

### 问题一：配额刷新只覆盖活跃账号，且定时器在前端

`sync_all_async` 调的是无参 `_ensure_quota_async()`，而无参时只取 `get_active_account_id()`；其余账号配额唯一的新鲜化路径是**手动打开「账户总览」页**（只有 `/api/accounts/overview` 会逐账号触发）。更根本的是**定时器在前端**：自动同步由 `app.js` 的 `setInterval` 驱动（`POST /api/sync`），窗口最小化到系统托盘后 WebView2 会节流定时器 —— 同步与配额刷新一起停摆。

**修复**：新增后端常驻调度线程 `cmdgauge-sched`（`server._scheduler_worker`）。

| 任务 | 周期 | 受 `auto_sync` 控制 |
|---|---|---|
| 全账号配额刷新（顺序执行，单账号失败不中断） | `sync_interval_sec` | 是 |
| 全账号增量同步 | `sync_interval_sec` | 是 |
| 会话保活探测 | 6 小时 | **否**（关掉自动同步的账号同样会掉线） |

- `PUT /api/settings` 后调 `wake_scheduler()` 立即打断等待重算，不必等下一个 tick
- 手动 `POST /api/sync` 同时更新调度心跳，避免紧接着又自动同步一次
- 前端定时器降级为**纯 UI 刷新**（只 `loadDashboard`，不再发 `/api/sync`）
- `start_server(with_scheduler=False)` 供冒烟测试隔离（调度线程会真实访问上游）

### 问题二：会话到期只能手动重登，且非活跃账号根本没法重登

实测站点是 **better-auth 滑动会话**：

| 字段 | 实测值 |
|---|---|
| `session.createdAt` | `2026-09-18T15:42:55Z` |
| `session.updatedAt` | `2026-09-19T15:43:24Z`（= createdAt + 24h01m） |
| `session.expiresAt` | `2026-09-26T15:43:24Z`（= updatedAt + 7d） |

即 `expiresIn = 7d` / `updateAge = 24h`。续期响应**只下发 `session_data`（`Max-Age=300`），不轮换 `session_token`** —— 客户端**不需要**回写 `Set-Cookie`，旧 cookie 串可以一直用。端点真实路径是 `{API_BASE}/auth/get-session`（`basePath` 是 `/auth`），未登录时返回 `200` + 字面量 `null`。

**实现**：
- `commandcode_api.fetch_session_info()` → `SessionInfo(status=ok|expired|na|error)` + 权威 `expiresAt`；**调用它本身就是保活**
- `accounts` 表新增 `session_expires_at` / `session_checked_at`（新建库建表 + 老库 `ALTER TABLE` 两条路径）
- 探测失败只刷 `checked_at`、**保留上次已知有效期**（免得 UI 从「还剩 3 天」莫名退回「未知」）
- UI `sessionBadgeHtml()`：设置页账号行与总览卡片显示「登录剩余 N 天」，≤4 天标黄、≤2 天标红、已过期标红；API Key 账号不显示
- 非活跃账号补 `relogin`：前端先 `switch` 再拉起登录窗 —— 因为 `db.save_token` 作用于**活跃账号**，不切会把新凭证盖到别的账号上
- `startLoginWatch` 的变更签名加入 `updated_at`，否则重登一个「本来就有 token」的账号时检测不到登录完成
