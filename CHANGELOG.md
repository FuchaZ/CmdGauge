# Changelog

> 每个版本对应一个 GitHub Release；exe 一律在 `app/__init__.py` 的 `__version__` 改完之后重新打包。

## v1.0.4

**托盘与关闭行为修正**

- **点 × 不再直接退出进程**：关闭窗口统一改为隐藏到系统托盘，「完全退出」走托盘图标右键菜单
- 拦截原生关闭：Alt+F4 / 任务栏缩略图关闭 / 窗口系统菜单关闭，同样合并为「隐藏到托盘」
- **修复托盘就绪判定**：原实现启动托盘线程后**立刻**认为托盘可用，若图标实际没显示出来，窗口一隐藏就再没有入口能叫回来（用户只能去任务管理器杀进程）；现在等 pystray 的 `icon.visible` 真正为真才置 `_tray_ready`（3 秒超时并落日志）
- 托盘图标文件缺失不再静默失败，改为写入 `%TEMP%\cmdgauge_main.log`；`close()` 的两个分支也各记一条日志，便于日后定位
- **技术要点（别再踩）**：不要用 pywebview 的 `closing` 事件来取消关闭 —— `Event.set()` 把 handler 丢进**新线程**异步执行，却**立即**读取返回值，`args.Cancel` 永远不会被赋值（实测结论 `TRUE_DOES_NOT_CANCEL`）。正确做法是订阅 `win.native`（WinForms `BrowserForm`）的 .NET `FormClosing`，它在 UI 线程同步触发（实测结论 `FORMCLOSING_CANCELS`）

## v1.0.3

**多账号配额全覆盖 + 会话保活**

- **新增后端常驻调度线程**：定时同步与配额刷新改由后端守护线程驱动。原实现依赖前端 `setInterval`，窗口最小化到系统托盘后 WebView2 会节流定时器，同步与配额刷新会一起停摆
- **每轮刷新全部账号的配额**：原实现只刷活跃账号，其余账号要手动打开「账户总览」页才会更新
- **会话保活**：定期调用 better-auth 会话端点 `GET /auth/get-session` 触发滑动续期（实测 `expiresIn=7d` / `updateAge=24h`，且续期不轮换 token，因此无需回写 cookie）
- **有效期可视化**：设置页账号行与账户总览卡片显示「登录剩余 N 天」，≤4 天标黄、≤2 天标红、已过期标红；API Key 账号不显示（无会话概念）
- **非活跃账号可直接重新登录**：前端先切到目标账号再拉起登录窗口，避免新凭证被写进别的账号
- 设置变更（同步开关 / 间隔）即时生效，不再等下一个调度周期
- 手动同步会重置调度心跳，避免紧随其后重复同步一次

## v1.0.2

**修复高 DPI 拖动不跟手、SQLite 连接按请求泄漏、本地服务任意文件读取等 8 项**

- 高 DPI / 缩放屏拖窗口不跟手（`MouseEvent.screenX/screenY` 是 DIP，前端统一 × `devicePixelRatio` 换算为物理像素）
- SQLite 连接按请求泄漏（HTTP/1.1 keep-alive + 线程连接回收；实测 50 请求泄 50 条 → 0）
- 本地静态服务可读任意本机文件（路径穿越校验 + Host 白名单）
- 账号级联删除留孤儿数据、settings 并发丢更新、单个账号坏 cookie 卡死多账号同步、鼠标手势残留等

## v1.0.1

**修复登录态丢失**

- `db.data_dir()` 的并发写探测不稳定，导致数据目录漂移、同一进程出现两个数据库；改为进程内缓存 + 双检锁 + 唯一探测文件名

## v1.0.0

**首次发布**

- 从 [GoGauge](https://github.com/yphyphyph/opencode-go-gauge) 移植骨架（本地 HTTP 服务 + SQLite + WebView 登录 + 托盘 + 双主题双语前端），数据层替换为 Command Code 官方接口
- 双认证（浏览器 session cookie / API Key）、5 分钟聚合桶带来的缓存指标、多账号、免安装单文件 exe
