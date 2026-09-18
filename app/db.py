"""SQLite 存储与聚合查询 (Command Code 版, 多账号).

与原 GoGauge 的差异 (见 DESIGN.md):
- ``usage_records`` 去掉 provider / reasoning / cache-token / key / session /
  plan 这些 Command Code 不提供的维度, 改为 duration_ms / status / mode / type
  与 input/output/cache 三段成本;
- ``accounts.token`` 存浏览器 session cookie, ``login`` / ``org_id`` 记录身份,
  用于展示与构造官方用量页链接;
- 「会话统计」改为「按天统计」(没有 session 维度)。

账号模型: ``settings.payload.active_account_id`` 指向活跃账号, 所有用量记录通过
``usage_records.account_id`` 归属账号, 同步状态 ``usage_sync_state`` 按账号一行。
兼容约定: 未显式传 account_id 时一律作用于活跃账号。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Optional

# 连接按线程隔离: 服务端是 ThreadingHTTPServer, 每个请求一个线程, 而 sqlite3
# 连接不是线程安全的 (并发 execute/commit 会互相破坏游标与事务状态, 表现为
# "bad parameter or other API misuse" / "cannot commit - no transaction is active"
# / fetchone() 返回 None 等)。原 GoGauge 用单条全局连接 + check_same_thread=False,
# 在自动同步与前端轮询并发时必然出错。这里改为每线程一条连接 + WAL + busy_timeout。
_local = threading.local()
_ALL_CONNS: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()  # 保护 _ALL_CONNS 与 schema 初始化
_schema_ready = False
_data_dir_override: Optional[str] = None
_resolved_data_dir: Optional[str] = None  # data_dir 解析结果缓存 (进程内稳定)

DB_FILENAME = "cmdgauge.db"
ENV_DATA_DIR = "CMDGAUGE_DATA"


def set_data_dir(path: str) -> None:
    global _data_dir_override, _resolved_data_dir
    _data_dir_override = path
    _resolved_data_dir = None  # 覆盖后需重新解析


def _default_data_dir() -> str:
    """数据目录 (进程内只解析一次, 结果缓存).

    必须缓存: 原实现每次调用都做一次「写探测」(创建/删除 .write-test), 而本函数
    会被 HTTP 线程 / 同步线程 / 登录 watcher 线程**并发调用** —— 并发探测会互相
    踩到同一个临时文件而间歇性失败, 于是回退到 ``%LOCALAPPDATA%``, 导致同一个
    进程内出现**两个数据库** (登录写进 A、读取读 B), 表现为「登录后重启又要求登录」。
    """
    global _resolved_data_dir
    if _resolved_data_dir:
        return _resolved_data_dir
    # 双检锁: 只让一个线程真正解析. 否则并发时多个线程会各自解析一次,
    # 而写探测在并发下不稳定, 导致同进程内返回不同路径 (库分裂)。
    with _conn_lock:
        if _resolved_data_dir:
            return _resolved_data_dir
        _resolved_data_dir = _resolve_data_dir()
        return _resolved_data_dir


def _resolve_data_dir() -> str:
    if _data_dir_override:
        return os.path.abspath(_data_dir_override)
    if os.environ.get(ENV_DATA_DIR):
        return os.path.abspath(os.environ[ENV_DATA_DIR])
    # 单文件 exe: 优先 exe 同目录 data/, 不可写则回退到 LOCALAPPDATA
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate = os.path.join(exe_dir, "data")
        try:
            os.makedirs(candidate, exist_ok=True)
            # 探测文件名带 pid+线程号: 并发调用时不会互相踩到同一个临时文件
            # (原实现用固定名, 多线程同时创建/删除会大量失败并误判为不可写)
            probe = os.path.join(
                candidate, f".write-test-{os.getpid()}-{threading.get_ident()}"
            )
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return candidate
        except OSError as exc:
            _log_dir_fallback(f"exe 同目录 {candidate} 不可写 ({exc})")
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(local, "CmdGauge", "data")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


def _log_dir_fallback(reason: str) -> None:
    """数据目录回退时落盘记录 (便于诊断「两个库」类问题)."""
    try:
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "cmdgauge_datadir.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} fallback to LOCALAPPDATA: {reason}\n")
    except OSError:
        pass


def data_dir() -> str:
    return _default_data_dir()


def db_path() -> str:
    return os.path.join(data_dir(), DB_FILENAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    """取当前线程的数据库连接 (首次调用时建连并初始化 schema)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")  # 多连接写入冲突时等待而非立即报错
    _local.conn = conn
    with _conn_lock:
        _ALL_CONNS.append(conn)
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """schema 初始化/迁移只跑一次 (用锁串行化, 避免多线程同时建表改表)."""
    global _schema_ready
    if _schema_ready:
        return
    with _conn_lock:
        if _schema_ready:
            return
        _init_schema(conn)
        _schema_ready = True


def close_db() -> None:
    """关闭本进程打开的全部连接 (并允许下次重新初始化 schema)."""
    global _schema_ready
    with _conn_lock:
        for conn in _ALL_CONNS:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        _ALL_CONNS.clear()
        _schema_ready = False
    _local.conn = None


# ---------------------------------------------------------------------------
# schema 初始化
# ---------------------------------------------------------------------------


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_records (
          usg_id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          model TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          status TEXT,
          mode TEXT,
          type TEXT,
          input_cost REAL NOT NULL DEFAULT 0,
          output_cost REAL NOT NULL DEFAULT 0,
          cache_cost REAL NOT NULL DEFAULT 0,
          cost_usd REAL NOT NULL DEFAULT 0,
          trace_id TEXT,
          synced_at TEXT NOT NULL,
          account_id INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_records(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_usage_account_time
          ON usage_records(account_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL DEFAULT 'Default',
          login TEXT NOT NULL DEFAULT '',
          org_id TEXT NOT NULL DEFAULT '',
          token TEXT NOT NULL DEFAULT '',
          auth_type TEXT NOT NULL DEFAULT 'cookie',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage_sync_state (
          account_id INTEGER PRIMARY KEY,
          last_sync_at TEXT,
          last_sync_status TEXT,
          last_sync_error TEXT,
          last_inserted_count INTEGER NOT NULL DEFAULT 0,
          deepest_page_fetched INTEGER NOT NULL DEFAULT -1,
          total_records INTEGER NOT NULL DEFAULT 0,
          oldest_record_at TEXT,
          newest_record_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          payload TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        -- 上游 5 分钟聚合桶: 唯一带「缓存 token」维度的数据源
        -- (/internal/usage/charts)。同 (model, timeBucket) 的桶是累计值,
        -- 重复拉取用覆盖式 upsert。
        CREATE TABLE IF NOT EXISTS usage_buckets (
          bucket_key TEXT NOT NULL,
          account_id INTEGER NOT NULL DEFAULT 1,
          model TEXT NOT NULL,
          provider TEXT,
          time_bucket TEXT NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          tokens_in INTEGER NOT NULL DEFAULT 0,
          tokens_out INTEGER NOT NULL DEFAULT 0,
          tokens_total INTEGER NOT NULL DEFAULT 0,
          input_cost REAL NOT NULL DEFAULT 0,
          output_cost REAL NOT NULL DEFAULT 0,
          cache_cost REAL NOT NULL DEFAULT 0,
          cache_savings REAL NOT NULL DEFAULT 0,
          total_cost REAL NOT NULL DEFAULT 0,
          credits_total REAL NOT NULL DEFAULT 0,
          consumed_free REAL NOT NULL DEFAULT 0,
          consumed_monthly REAL NOT NULL DEFAULT 0,
          consumed_purchased REAL NOT NULL DEFAULT 0,
          consumed_total REAL NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          synced_at TEXT NOT NULL,
          PRIMARY KEY (bucket_key, account_id)
        );

        CREATE INDEX IF NOT EXISTS idx_bucket_account_time
          ON usage_buckets(account_id, time_bucket DESC);

        -- 账号级账单周期汇总快照 (/alpha/usage/summary 或 /internal/usage/summary)。
        -- API Key 模式没有请求明细, 只能靠它填充「用量概览」。
        CREATE TABLE IF NOT EXISTS account_summaries (
          account_id INTEGER PRIMARY KEY,
          payload TEXT NOT NULL,
          period_basis TEXT,
          updated_at TEXT NOT NULL
        );
        """
    )
    if conn.execute("SELECT id FROM settings WHERE id = 1").fetchone() is None:
        conn.execute(
            "INSERT INTO settings (id, payload, updated_at) VALUES (1, '{}', ?)",
            (_now_iso(),),
        )
        conn.commit()

    # 存量列补充 (老库升级用)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(usage_records)").fetchall()}
    for col, ddl in (
        ("duration_ms", "ALTER TABLE usage_records ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0"),
        ("status", "ALTER TABLE usage_records ADD COLUMN status TEXT"),
        ("mode", "ALTER TABLE usage_records ADD COLUMN mode TEXT"),
        ("type", "ALTER TABLE usage_records ADD COLUMN type TEXT"),
        ("input_cost", "ALTER TABLE usage_records ADD COLUMN input_cost REAL NOT NULL DEFAULT 0"),
        ("output_cost", "ALTER TABLE usage_records ADD COLUMN output_cost REAL NOT NULL DEFAULT 0"),
        ("cache_cost", "ALTER TABLE usage_records ADD COLUMN cache_cost REAL NOT NULL DEFAULT 0"),
        ("trace_id", "ALTER TABLE usage_records ADD COLUMN trace_id TEXT"),
        ("account_id", "ALTER TABLE usage_records ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1"),
    ):
        if col not in cols:
            conn.execute(ddl)

    acc_cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    for col, ddl in (
        ("login", "ALTER TABLE accounts ADD COLUMN login TEXT NOT NULL DEFAULT ''"),
        ("org_id", "ALTER TABLE accounts ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"),
        ("auth_type", "ALTER TABLE accounts ADD COLUMN auth_type TEXT NOT NULL DEFAULT 'cookie'"),
    ):
        if col not in acc_cols:
            conn.execute(ddl)

    # 全新库: 种子默认空账号 (未登录态). 用固定 id=1 + OR IGNORE,
    # 保证多线程同时首次建库时不会重复插入.
    if conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0:
        now = _now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO accounts (id, name, login, org_id, token, created_at, updated_at)"
            " VALUES (1, 'Default', '', '', '', ?, ?)",
            (now, now),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# settings payload 底层读写
# ---------------------------------------------------------------------------


def _raw_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT payload FROM settings WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["payload"])
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _write_payload(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE settings SET payload = ?, updated_at = ? WHERE id = 1",
        (json.dumps(data, ensure_ascii=False), _now_iso()),
    )


# ---------------------------------------------------------------------------
# 活跃账号
# ---------------------------------------------------------------------------


def _persist_active(conn: sqlite3.Connection, account_id: int) -> None:
    data = _raw_payload(conn)
    data["active_account_id"] = int(account_id)
    _write_payload(conn, data)
    conn.commit()


def get_active_account_id() -> int:
    """当前活跃账号 id; 无任何账号时返回 0.

    偏好已登录账号: 存储的活跃账号若未登录, 自动让位给最小的已登录账号。
    """
    conn = get_db()
    aid = _raw_payload(conn).get("active_account_id")
    logged_row = conn.execute(
        "SELECT MIN(id) AS i FROM accounts WHERE TRIM(token) != ''"
    ).fetchone()
    logged_min = int(logged_row["i"]) if logged_row and logged_row["i"] is not None else 0
    if isinstance(aid, int) and aid > 0:
        row = conn.execute("SELECT token FROM accounts WHERE id = ?", (aid,)).fetchone()
        if row is not None:
            if row["token"].strip():
                return aid
            if logged_min:
                _persist_active(conn, logged_min)
                return logged_min
            return aid
    if logged_min:
        _persist_active(conn, logged_min)
        return logged_min
    row = conn.execute("SELECT MIN(id) AS i FROM accounts").fetchone()
    fallback = int(row["i"]) if row and row["i"] is not None else 0
    if fallback:
        _persist_active(conn, fallback)
    return fallback


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id:
        return int(account_id)
    return get_active_account_id()


def set_active_account(account_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT id FROM accounts WHERE id = ?", (int(account_id),)).fetchone()
    if row is None:
        return False
    _persist_active(conn, int(account_id))
    return True


# ---------------------------------------------------------------------------
# 账号 CRUD / 凭证
# ---------------------------------------------------------------------------


def _account_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "login": row["login"] or "",
        "org_id": row["org_id"] or "",
        "auth_type": (row["auth_type"] or "cookie") if "auth_type" in row.keys() else "cookie",
        "has_token": bool(row["token"].strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_account() -> dict[str, Any]:
    aid = get_active_account_id()
    if not aid:
        return {}
    row = get_db().execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    return _account_dict(row) if row else {}


def list_accounts() -> list[dict[str, Any]]:
    rows = get_db().execute("SELECT * FROM accounts ORDER BY id ASC").fetchall()
    return [_account_dict(r) for r in rows]


def count_accounts() -> int:
    return int(get_db().execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"])


def count_logged_in_accounts() -> int:
    row = get_db().execute(
        "SELECT COUNT(*) AS c FROM accounts WHERE TRIM(token) != ''"
    ).fetchone()
    return int(row["c"])


def _ensure_state_row(conn: sqlite3.Connection, account_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO usage_sync_state (account_id, deepest_page_fetched) VALUES (?, -1)",
        (account_id,),
    )


def save_token(token: str, login: str = "", org_id: str = "", auth_type: str = "cookie") -> None:
    """重新登录语义: 更新活跃账号的凭证与认证类型, 并重置其同步游标."""
    conn = get_db()
    aid = get_active_account_id()
    if not aid:
        return
    conn.execute(
        """UPDATE accounts SET token = ?, login = ?, org_id = ?, auth_type = ?, updated_at = ?
           WHERE id = ?""",
        (token.strip(), (login or "").strip(), (org_id or "").strip(),
         auth_type or "cookie", _now_iso(), aid),
    )
    _ensure_state_row(conn, aid)
    conn.execute(
        "UPDATE usage_sync_state SET deepest_page_fetched = -1 WHERE account_id = ?", (aid,)
    )
    conn.commit()


def get_token() -> str:
    aid = get_active_account_id()
    if not aid:
        return ""
    row = get_db().execute("SELECT token FROM accounts WHERE id = ?", (aid,)).fetchone()
    return row["token"] if row else ""


def get_login_hint() -> str:
    """活跃账号的登录名/组织名 (用于构造官方用量页链接)."""
    aid = get_active_account_id()
    if not aid:
        return ""
    row = get_db().execute("SELECT login FROM accounts WHERE id = ?", (aid,)).fetchone()
    return (row["login"] or "") if row else ""


def get_account_credentials(account_id: int) -> tuple[str, str, str, str]:
    """读取任意账号凭证, 返回 (credential, login, org_id, auth_type).

    credential 在 cookie 模式下是 Cookie 串, 在 apikey 模式下是 API Key。
    """
    row = get_db().execute(
        "SELECT token, login, org_id, auth_type FROM accounts WHERE id = ?", (int(account_id),)
    ).fetchone()
    if row is None:
        return "", "", "", "cookie"
    return (
        (row["token"] or "").strip(),
        (row["login"] or ""),
        (row["org_id"] or ""),
        (row["auth_type"] or "cookie"),
    )


def get_credential_any(account_id: int) -> tuple[str, str, str, str]:
    """get_account_credentials 的别名 (语义更清晰: 不一定是 cookie)."""
    return get_account_credentials(account_id)


def add_account(
    token: str, login: str = "", org_id: str = "", auth_type: str = "cookie", switch: bool = True
) -> int:
    """添加新账号; 同凭证视为同一账号, 更新身份后返回其 id."""
    conn = get_db()
    token = (token or "").strip()
    login = (login or "").strip()
    org_id = (org_id or "").strip()
    auth_type = auth_type or "cookie"
    existing = (
        conn.execute(
            "SELECT id FROM accounts WHERE TRIM(token) = ? ORDER BY id LIMIT 1", (token,)
        ).fetchone()
        if token
        else None
    )
    if existing is not None:
        aid = int(existing["id"])
        conn.execute(
            "UPDATE accounts SET login = ?, org_id = ?, auth_type = ?, updated_at = ? WHERE id = ?",
            (login, org_id, auth_type, _now_iso(), aid),
        )
        if switch:
            _persist_active(conn, aid)
        else:
            conn.commit()
        return aid
    nxt = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM accounts").fetchone()["n"]
    name = login[:50] if login else f"User {nxt}"
    now = _now_iso()
    cur = conn.execute(
        """INSERT INTO accounts (name, login, org_id, token, auth_type, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, login, org_id, token, auth_type, now, now),
    )
    aid = int(cur.lastrowid or nxt)
    _ensure_state_row(conn, aid)
    if switch:
        _persist_active(conn, aid)
    else:
        conn.commit()
    return aid


def rename_account(account_id: int, name: str) -> bool:
    name = (name or "").strip()[:50]
    if not name:
        return False
    conn = get_db()
    cur = conn.execute(
        "UPDATE accounts SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now_iso(), int(account_id)),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_account(account_id: int) -> int:
    """删除账号及其本地全部数据 (级联), 返回剩余账号数."""
    conn = get_db()
    aid = int(account_id)
    conn.execute("DELETE FROM usage_records WHERE account_id = ?", (aid,))
    conn.execute("DELETE FROM usage_sync_state WHERE account_id = ?", (aid,))
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    remaining = int(conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"])
    active = _raw_payload(conn).get("active_account_id")
    if active == aid:
        nxt = conn.execute("SELECT MIN(id) AS i FROM accounts").fetchone()["i"]
        if nxt is not None:
            _persist_active(conn, int(nxt))
        else:
            data = _raw_payload(conn)
            data.pop("active_account_id", None)
            _write_payload(conn, data)
            conn.commit()
    conn.commit()
    return remaining


def clear_account() -> None:
    """退出登录当前活跃账号: 清除凭证与本地缓存数据 (保留账号行)."""
    conn = get_db()
    aid = get_active_account_id()
    if not aid:
        return
    conn.execute("DELETE FROM usage_records WHERE account_id = ?", (aid,))
    conn.execute(
        "UPDATE accounts SET token = '', updated_at = ? WHERE id = ?",
        (_now_iso(), aid),
    )
    _ensure_state_row(conn, aid)
    conn.execute(
        "UPDATE usage_sync_state SET last_sync_status = NULL, last_sync_error = NULL,"
        " last_inserted_count = 0, deepest_page_fetched = -1, total_records = 0,"
        " oldest_record_at = NULL, newest_record_at = NULL WHERE account_id = ?",
        (aid,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 用量记录写入 / 同步状态
# ---------------------------------------------------------------------------


def insert_usage_records(
    records: list[dict[str, Any]], account_id: Optional[int] = None
) -> int:
    """批量写入 (归属指定/活跃账号), 按 usg_id upsert; 返回新增条数."""
    if not records:
        return 0
    aid = _resolve_account_id(account_id)
    conn = get_db()
    synced_at = _now_iso()
    stmt = (
        "INSERT INTO usage_records (usg_id, created_at, model, input_tokens, output_tokens,"
        " duration_ms, status, mode, type, input_cost, output_cost, cache_cost, cost_usd,"
        " trace_id, synced_at, account_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(usg_id) DO UPDATE SET"
        " input_tokens = excluded.input_tokens,"
        " output_tokens = excluded.output_tokens,"
        " duration_ms = excluded.duration_ms,"
        " status = excluded.status,"
        " mode = excluded.mode,"
        " type = excluded.type,"
        " input_cost = excluded.input_cost,"
        " output_cost = excluded.output_cost,"
        " cache_cost = excluded.cache_cost,"
        " cost_usd = excluded.cost_usd,"
        " synced_at = excluded.synced_at"
    )
    inserted = 0
    try:
        conn.execute("BEGIN")
        for rec in records:
            existed = (
                conn.execute(
                    "SELECT 1 FROM usage_records WHERE usg_id = ?", (rec["usg_id"],)
                ).fetchone()
                is not None
            )
            conn.execute(
                stmt,
                (
                    rec["usg_id"],
                    rec["created_at"],
                    rec["model"],
                    int(rec.get("input_tokens") or 0),
                    int(rec.get("output_tokens") or 0),
                    int(rec.get("duration_ms") or 0),
                    rec.get("status"),
                    rec.get("mode"),
                    rec.get("type"),
                    float(rec.get("input_cost") or 0.0),
                    float(rec.get("output_cost") or 0.0),
                    float(rec.get("cache_cost") or 0.0),
                    float(rec.get("cost_usd") or 0.0),
                    rec.get("trace_id"),
                    synced_at,
                    aid,
                ),
            )
            if not existed:
                inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return inserted


def get_sync_state(account_id: Optional[int] = None) -> dict[str, Any]:
    aid = _resolve_account_id(account_id)
    if not aid:
        return {}
    row = get_db().execute(
        "SELECT * FROM usage_sync_state WHERE account_id = ?", (aid,)
    ).fetchone()
    if row is None:
        return {}
    return {
        "last_sync_at": row["last_sync_at"],
        "last_sync_status": row["last_sync_status"],
        "last_sync_error": row["last_sync_error"],
        "last_inserted_count": row["last_inserted_count"],
        "deepest_page_fetched": row["deepest_page_fetched"],
        "total_records": row["total_records"],
        "oldest_record_at": row["oldest_record_at"],
        "newest_record_at": row["newest_record_at"],
    }


def update_sync_state(
    status: str,
    error: Optional[str] = None,
    inserted: int = 0,
    account_id: Optional[int] = None,
    pages: int = 0,
) -> None:
    aid = _resolve_account_id(account_id)
    if not aid:
        return
    conn = get_db()
    _ensure_state_row(conn, aid)
    conn.execute(
        """UPDATE usage_sync_state
           SET last_sync_at = ?, last_sync_status = ?, last_sync_error = ?,
               last_inserted_count = last_inserted_count + ?,
               deepest_page_fetched = CASE WHEN deepest_page_fetched < ?
                                           THEN ? ELSE deepest_page_fetched END
           WHERE account_id = ?""",
        (_now_iso(), status, error, inserted, pages, pages, aid),
    )
    _refresh_sync_totals(conn, aid)
    conn.commit()


def _refresh_sync_totals(conn: sqlite3.Connection, account_id: int) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS total, MIN(created_at) AS oldest, MAX(created_at) AS newest"
        " FROM usage_records WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    conn.execute(
        "UPDATE usage_sync_state SET total_records = ?, oldest_record_at = ?, newest_record_at = ?"
        " WHERE account_id = ?",
        (row["total"], row["oldest"], row["newest"], account_id),
    )


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS: dict[str, Any] = {
    "sync_interval_sec": 300,  # 自动增量同步间隔 (1/5/15/30 分钟)
    "window_days": 60,  # 本地保留窗口: 30/60/90/180, None=全部
    "auto_sync": True,  # 自动增量同步开关
    "show_accounts_panel": False,  # 账户总览面板开关
}


def prune_old_records(window_days: int | None, account_id: Optional[int] = None) -> int:
    """按保留窗口裁剪过期记录与聚合桶, 返回删除的明细条数. window_days=None 时不裁剪."""
    if window_days is None:
        return 0
    aid = _resolve_account_id(account_id)
    if not aid:
        return 0
    window_days = max(1, min(int(window_days), 3650))
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM usage_records WHERE account_id = ?"
        " AND datetime(created_at) < datetime('now', ?)",
        (aid, f"-{window_days} days"),
    )
    conn.execute(
        "DELETE FROM usage_buckets WHERE account_id = ?"
        " AND datetime(time_bucket) < datetime('now', ?)",
        (aid, f"-{window_days} days"),
    )
    conn.commit()
    return cur.rowcount


def get_settings() -> dict[str, Any]:
    merged = dict(_DEFAULT_SETTINGS)
    merged.update({k: v for k, v in _raw_payload(get_db()).items() if k in _DEFAULT_SETTINGS})
    return merged


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    conn = get_db()
    raw = _raw_payload(conn)
    current = dict(_DEFAULT_SETTINGS)
    current.update({k: v for k, v in raw.items() if k in _DEFAULT_SETTINGS})
    for key in _DEFAULT_SETTINGS:
        if key not in payload:
            continue
        value = payload[key]
        if key == "sync_interval_sec":
            if value is None:
                continue
            try:
                current[key] = max(30, min(int(value), 3600))
            except (TypeError, ValueError):
                pass
        elif key == "window_days":
            # None / 空串 / "all" 均表示不裁剪 (原实现被外层 is not None 挡掉, 导致
            # 前端选「所有」不生效, 这里显式支持)
            if value is None or value == "" or str(value).lower() in ("all", "所有"):
                current[key] = None
            else:
                try:
                    current[key] = max(1, min(int(value), 3650))
                except (TypeError, ValueError):
                    pass
        elif key in ("auto_sync", "show_accounts_panel"):
            if value is None:
                continue
            current[key] = bool(value)
        else:
            current[key] = value
    out = dict(raw)
    out.update(current)
    _write_payload(conn, out)
    conn.commit()
    return current


# ---------------------------------------------------------------------------
# 聚合查询
# ---------------------------------------------------------------------------

_NUM_DAYS_RE = re.compile(r"^(\d+)d$")

# 时间列可参数化: usage_records 用 created_at, usage_buckets 用 time_bucket
_PERIOD_CLAUSES = {
    "5h": "datetime({col}) >= datetime('now', '-5 hours')",
    "today": "substr(datetime({col}, 'localtime'), 1, 10) = date('now', 'localtime')",
}

# 明细/聚合共用的成本与 Token 汇总表达式
_SUM_SQL = """
    COUNT(*) AS request_count,
    SUM(CASE WHEN status IS NULL OR status = '' OR status = 'completed' THEN 0 ELSE 1 END)
        AS failed_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(input_tokens + output_tokens) AS total_tokens,
    SUM(input_cost) AS total_input_cost,
    SUM(output_cost) AS total_output_cost,
    SUM(cache_cost) AS total_cache_cost,
    SUM(cost_usd) AS total_cost_usd,
    AVG(duration_ms) AS avg_duration_ms
"""


def _period_where(period: str, col: str = "created_at") -> tuple[str, list[Any]]:
    """构造时间范围 WHERE 片段. col 指定时间列 (明细用 created_at, 聚合桶用 time_bucket)."""
    clauses: list[str] = []
    params: list[Any] = []
    if period in _PERIOD_CLAUSES:
        clauses.append(_PERIOD_CLAUSES[period].format(col=col))
    elif period != "all":
        days = 30
        match = _NUM_DAYS_RE.match(period or "")
        if match:
            days = max(1, int(match.group(1)))
        clauses.append(f"datetime({col}) >= datetime('now', ?)")
        params.append(f"-{days} days")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _account_filter(where: str, params: list[Any], aid: int) -> tuple[str, list[Any]]:
    if where:
        return where + " AND account_id = ?", params + [aid]
    return "WHERE account_id = ?", params + [aid]


def _metrics_from_row(row: sqlite3.Row | None) -> dict[str, Any]:
    """把 _SUM_SQL 的结果行整理为对外口径 (含成功率与缓存成本占比)."""
    if row is None or row["request_count"] is None:
        return {
            "request_count": 0, "failed_count": 0, "success_count": 0, "success_rate": 0.0,
            "total_input_tokens": 0, "total_output_tokens": 0, "total_tokens": 0,
            "total_input_cost": 0.0, "total_output_cost": 0.0, "total_cache_cost": 0.0,
            "total_cost_usd": 0.0, "avg_cost_usd": 0.0, "avg_duration_ms": 0,
            "cache_cost_ratio": 0.0,
        }
    requests = int(row["request_count"] or 0)
    failed = int(row["failed_count"] or 0)
    cache_cost = float(row["total_cache_cost"] or 0.0)
    input_cost = float(row["total_input_cost"] or 0.0)
    total_cost = float(row["total_cost_usd"] or 0.0)
    billable_input = input_cost + cache_cost
    return {
        "request_count": requests,
        "failed_count": failed,
        "success_count": max(0, requests - failed),
        "success_rate": round((requests - failed) / requests * 100.0, 2) if requests else 0.0,
        "total_input_tokens": int(row["total_input_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
        "total_input_cost": round(input_cost, 6),
        "total_output_cost": round(float(row["total_output_cost"] or 0.0), 6),
        "total_cache_cost": round(cache_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_usd": round(total_cost / requests, 8) if requests else 0.0,
        "avg_duration_ms": int(row["avg_duration_ms"] or 0),
        "cache_cost_ratio": round(cache_cost / billable_input * 100.0, 2) if billable_input else 0.0,
    }


def totals(period: str = "30d", account_id: Optional[int] = None) -> dict[str, Any]:
    """总览指标."""
    where, params = _period_where(period)
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    row = get_db().execute(
        f"SELECT {_SUM_SQL}, COUNT(DISTINCT model) AS model_count FROM usage_records {where}",
        params,
    ).fetchone()
    data = _metrics_from_row(row)
    data["model_count"] = int(row["model_count"] or 0) if row is not None else 0
    return data


def model_stats(period: str = "30d", account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """按模型聚合."""
    where, params = _period_where(period)
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    rows = get_db().execute(
        f"""SELECT model, {_SUM_SQL}
            FROM usage_records
            {where}
            GROUP BY model
            ORDER BY SUM(cost_usd) DESC""",
        params,
    ).fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        item = _metrics_from_row(r)
        item["model"] = r["model"]
        result.append(item)
    return result


def daily_stats(days: int = 30, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """每日聚合 (无数据的日子补 0, 便于画趋势)."""
    days = max(1, min(days, 365))
    aid = _resolve_account_id(account_id)
    rows = get_db().execute(
        f"""SELECT substr(datetime(created_at, 'localtime'), 1, 10) AS date, {_SUM_SQL}
            FROM usage_records
            WHERE account_id = ?
              AND substr(datetime(created_at, 'localtime'), 1, 10) >= date('now', 'localtime', ?)
            GROUP BY substr(datetime(created_at, 'localtime'), 1, 10)
            ORDER BY date ASC""",
        (aid, f"-{days} days"),
    ).fetchall()
    by_date = {r["date"]: r for r in rows}
    result: list[dict[str, Any]] = []
    today = datetime.now()
    for offset in range(days - 1, -1, -1):
        day = (today.toordinal() - offset)
        date_str = datetime.fromordinal(day).strftime("%Y-%m-%d")
        r = by_date.get(date_str)
        item = _metrics_from_row(r)
        item["date"] = date_str
        result.append(item)
    return result


def today_trend(account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """今日 24 小时趋势 (本地时区, 无数据补 0)."""
    aid = _resolve_account_id(account_id)
    rows = get_db().execute(
        """SELECT CAST(strftime('%H', datetime(created_at, 'localtime')) AS INTEGER) AS h,
                  SUM(input_tokens) AS input,
                  SUM(output_tokens) AS output,
                  COUNT(*) AS requests,
                  SUM(cost_usd) AS cost
           FROM usage_records
           WHERE account_id = ?
             AND substr(datetime(created_at, 'localtime'), 1, 10) = date('now', 'localtime')
           GROUP BY h""",
        (aid,),
    ).fetchall()
    by_hour = {int(r["h"]): r for r in rows}
    result: list[dict[str, Any]] = []
    for h in range(24):
        r = by_hour.get(h)
        result.append(
            {
                "hour": f"{h:02d}:00",
                "input": int(r["input"]) if r else 0,
                "output": int(r["output"]) if r else 0,
                "requests": int(r["requests"]) if r else 0,
                "cost": round(float(r["cost"] or 0.0), 6) if r else 0.0,
            }
        )
    return result


# ---------------------------------------------------------------------------
# 分页查询
# ---------------------------------------------------------------------------


def usage_records_page(
    page: int = 1,
    page_size: int = 20,
    model: Optional[str] = None,
    days: Optional[int] = None,
    status: Optional[str] = None,
    account_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], int]:
    """用量明细分页 (按时间倒序), 返回 (records, total)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where: list[str] = []
    params: list[Any] = []
    if model:
        where.append("model = ?")
        params.append(model)
    if days:
        where.append("datetime(created_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    where_sql, params = _account_filter(where_sql, params, _resolve_account_id(account_id))
    conn = get_db()
    total = int(
        conn.execute(
            f"SELECT COUNT(*) AS c FROM usage_records {where_sql}", params
        ).fetchone()["c"]
    )
    rows = conn.execute(
        f"SELECT * FROM usage_records {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records = [
        {
            "usg_id": r["usg_id"],
            "created_at": r["created_at"],
            "model": r["model"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "total_tokens": (r["input_tokens"] or 0) + (r["output_tokens"] or 0),
            "duration_ms": r["duration_ms"],
            "status": r["status"] or "",
            "mode": r["mode"] or "",
            "type": r["type"] or "",
            "input_cost": r["input_cost"],
            "output_cost": r["output_cost"],
            "cache_cost": r["cache_cost"],
            "cost_usd": r["cost_usd"],
        }
        for r in rows
    ]
    return records, total


def day_stats_page(
    page: int = 1,
    page_size: int = 10,
    days: Optional[int] = None,
    account_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], int]:
    """按天聚合分页 (替代原「会话统计」), 返回 (records, total)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    where: list[str] = []
    params: list[Any] = []
    if days:
        where.append("datetime(created_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    where_sql, params = _account_filter(where_sql, params, _resolve_account_id(account_id))
    day_expr = "substr(datetime(created_at, 'localtime'), 1, 10)"
    conn = get_db()
    total = int(
        conn.execute(
            f"SELECT COUNT(DISTINCT {day_expr}) AS c FROM usage_records {where_sql}", params
        ).fetchone()["c"]
    )
    rows = conn.execute(
        f"""SELECT {day_expr} AS day, {_SUM_SQL}, COUNT(DISTINCT model) AS model_count
            FROM usage_records
            {where_sql}
            GROUP BY {day_expr}
            ORDER BY day DESC
            LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records: list[dict[str, Any]] = []
    for r in rows:
        item = _metrics_from_row(r)
        item["day"] = r["day"]
        item["model_count"] = int(r["model_count"] or 0)
        records.append(item)
    return records, total


def list_models(account_id: Optional[int] = None) -> list[str]:
    where, params = _account_filter("", [], _resolve_account_id(account_id))
    rows = get_db().execute(
        f"SELECT DISTINCT model FROM usage_records {where} ORDER BY model", params
    ).fetchall()
    return [r["model"] for r in rows]


# ---------------------------------------------------------------------------
# 5 分钟聚合桶 (缓存 token 维度)
# ---------------------------------------------------------------------------


def insert_usage_buckets(
    buckets: list[dict[str, Any]], account_id: Optional[int] = None
) -> int:
    """写入手付的 5 分钟聚合桶, 返回新增桶数.

    同 (model, timeBucket) 的桶是**累计值** (桶内请求还在累积), 因此用覆盖式
    upsert: 后拉到的值直接覆盖旧值, 绝不能累加, 否则会重复计数。
    """
    if not buckets:
        return 0
    aid = _resolve_account_id(account_id)
    if not aid:
        return 0
    conn = get_db()
    synced_at = _now_iso()
    stmt = (
        "INSERT INTO usage_buckets (bucket_key, account_id, model, provider, time_bucket,"
        " requests, tokens_in, tokens_out, tokens_total, input_cost, output_cost, cache_cost,"
        " cache_savings, total_cost, credits_total, consumed_free, consumed_monthly,"
        " consumed_purchased, consumed_total, cache_read_tokens, cache_creation_tokens, synced_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(bucket_key, account_id) DO UPDATE SET"
        " provider = excluded.provider,"
        " requests = excluded.requests,"
        " tokens_in = excluded.tokens_in,"
        " tokens_out = excluded.tokens_out,"
        " tokens_total = excluded.tokens_total,"
        " input_cost = excluded.input_cost,"
        " output_cost = excluded.output_cost,"
        " cache_cost = excluded.cache_cost,"
        " cache_savings = excluded.cache_savings,"
        " total_cost = excluded.total_cost,"
        " credits_total = excluded.credits_total,"
        " consumed_free = excluded.consumed_free,"
        " consumed_monthly = excluded.consumed_monthly,"
        " consumed_purchased = excluded.consumed_purchased,"
        " consumed_total = excluded.consumed_total,"
        " cache_read_tokens = excluded.cache_read_tokens,"
        " cache_creation_tokens = excluded.cache_creation_tokens,"
        " synced_at = excluded.synced_at"
    )
    inserted = 0
    try:
        conn.execute("BEGIN")
        for b in buckets:
            existed = (
                conn.execute(
                    "SELECT 1 FROM usage_buckets WHERE bucket_key = ? AND account_id = ?",
                    (b["bucket_key"], aid),
                ).fetchone()
                is not None
            )
            conn.execute(
                stmt,
                (
                    b["bucket_key"], aid, b["model"], b.get("provider"), b["time_bucket"],
                    int(b.get("requests") or 0),
                    int(b.get("tokens_in") or 0),
                    int(b.get("tokens_out") or 0),
                    int(b.get("tokens_total") or 0),
                    float(b.get("input_cost") or 0.0),
                    float(b.get("output_cost") or 0.0),
                    float(b.get("cache_cost") or 0.0),
                    float(b.get("cache_savings") or 0.0),
                    float(b.get("total_cost") or 0.0),
                    float(b.get("credits_total") or 0.0),
                    float(b.get("consumed_free") or 0.0),
                    float(b.get("consumed_monthly") or 0.0),
                    float(b.get("consumed_purchased") or 0.0),
                    float(b.get("consumed_total") or 0.0),
                    int(b.get("cache_read_tokens") or 0),
                    int(b.get("cache_creation_tokens") or 0),
                    synced_at,
                ),
            )
            if not existed:
                inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return inserted


def _empty_cache_stats() -> dict[str, Any]:
    return {
        "requests": 0, "tokens_in": 0, "tokens_out": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "cache_savings": 0.0, "cache_cost": 0.0,
        "hit_rate": 0.0, "miss_tokens": 0,
        "bucket_count": 0, "since": None, "until": None,
    }


def cache_stats(period: str = "30d", account_id: Optional[int] = None) -> dict[str, Any]:
    """缓存指标 (来自 5 分钟聚合桶).

    命中率 = cache_read_tokens / tokens_in (与 goat-gauge 同口径);
    miss_tokens = tokens_in - cache_read_tokens。
    注意: 桶只覆盖上游窗口内「有数据」的部分, 覆盖率随本机同步累积。
    """
    where, params = _period_where(period, col="time_bucket")
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    row = get_db().execute(
        f"""SELECT COUNT(*) AS bucket_count,
                   SUM(requests) AS requests,
                   SUM(tokens_in) AS tokens_in,
                   SUM(tokens_out) AS tokens_out,
                   SUM(cache_read_tokens) AS cache_read_tokens,
                   SUM(cache_creation_tokens) AS cache_creation_tokens,
                   SUM(cache_savings) AS cache_savings,
                   SUM(cache_cost) AS cache_cost,
                   MIN(time_bucket) AS since,
                   MAX(time_bucket) AS until
            FROM usage_buckets {where}""",
        params,
    ).fetchone()
    if row is None or not row["bucket_count"]:
        return _empty_cache_stats()
    tokens_in = int(row["tokens_in"] or 0)
    cache_read = int(row["cache_read_tokens"] or 0)
    return {
        "requests": int(row["requests"] or 0),
        "tokens_in": tokens_in,
        "tokens_out": int(row["tokens_out"] or 0),
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
        "cache_savings": round(float(row["cache_savings"] or 0.0), 6),
        "cache_cost": round(float(row["cache_cost"] or 0.0), 6),
        "hit_rate": round(cache_read / tokens_in * 100.0, 2) if tokens_in else 0.0,
        "miss_tokens": max(0, tokens_in - cache_read),
        "bucket_count": int(row["bucket_count"]),
        "since": row["since"],
        "until": row["until"],
    }


def model_cache_stats(period: str = "30d", account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """按模型的缓存指标 (供统计页模型排行展示命中率)."""
    where, params = _period_where(period, col="time_bucket")
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    rows = get_db().execute(
        f"""SELECT model,
                   SUM(requests) AS requests,
                   SUM(tokens_in) AS tokens_in,
                   SUM(cache_read_tokens) AS cache_read_tokens,
                   SUM(cache_creation_tokens) AS cache_creation_tokens,
                   SUM(cache_savings) AS cache_savings
            FROM usage_buckets {where}
            GROUP BY model
            ORDER BY SUM(tokens_in) DESC""",
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        tokens_in = int(r["tokens_in"] or 0)
        cache_read = int(r["cache_read_tokens"] or 0)
        out.append(
            {
                "model": r["model"],
                "requests": int(r["requests"] or 0),
                "tokens_in": tokens_in,
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": int(r["cache_creation_tokens"] or 0),
                "cache_savings": round(float(r["cache_savings"] or 0.0), 6),
                "hit_rate": round(cache_read / tokens_in * 100.0, 2) if tokens_in else 0.0,
                "miss_tokens": max(0, tokens_in - cache_read),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 账号级账单汇总快照 (API Key 模式的唯一数据来源)
# ---------------------------------------------------------------------------


def save_account_summary(summary: dict[str, Any], account_id: Optional[int] = None) -> None:
    """保存账单周期汇总快照 (原始 JSON + periodBasis)."""
    if not summary:
        return
    aid = _resolve_account_id(account_id)
    if not aid:
        return
    conn = get_db()
    conn.execute(
        """INSERT INTO account_summaries (account_id, payload, period_basis, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(account_id) DO UPDATE SET
             payload = excluded.payload,
             period_basis = excluded.period_basis,
             updated_at = excluded.updated_at""",
        (
            aid,
            json.dumps(summary, ensure_ascii=False),
            str(summary.get("periodBasis") or ""),
            _now_iso(),
        ),
    )
    conn.commit()


def get_account_summary(account_id: Optional[int] = None) -> dict[str, Any]:
    """读取账单周期汇总快照; 无记录返回 {}."""
    aid = _resolve_account_id(account_id)
    if not aid:
        return {}
    row = get_db().execute(
        "SELECT payload, period_basis, updated_at FROM account_summaries WHERE account_id = ?",
        (aid,),
    ).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row["payload"])
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    data["_period_basis"] = row["period_basis"] or data.get("periodBasis", "")
    data["_updated_at"] = row["updated_at"]
    return data


def summary_as_totals(summary: dict[str, Any]) -> dict[str, Any]:
    """把账单汇总映射成与 ``totals()`` 同名的指标字典 (供概览卡片直接使用).

    注意: 这是**账单周期累计**, 不随首页时间范围(今天/7天/30天)变化, 调用方需标注。
    """
    if not summary:
        return {}
    requests = int(summary.get("totalCount") or 0)
    failed = int(summary.get("failedCount") or 0)
    completed = int(summary.get("completedCount") or (requests - failed))
    tokens_in = int(summary.get("totalTokensIn") or 0)
    tokens_out = int(summary.get("totalTokensOut") or 0)
    total_cost = float(summary.get("totalCost") or 0.0)
    return {
        "request_count": requests,
        "failed_count": failed,
        "success_count": max(0, completed),
        "success_rate": round(float(summary.get("successRate") or 0.0), 2),
        "total_input_tokens": tokens_in,
        "total_output_tokens": tokens_out,
        "total_tokens": int(summary.get("totalTokens") or (tokens_in + tokens_out)),
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_usd": round(float(summary.get("averageCost") or 0.0), 8),
        # 账单汇总不含成本拆分 / 耗时 / 缓存维度
        "total_input_cost": 0.0,
        "total_output_cost": 0.0,
        "total_cache_cost": 0.0,
        "cache_cost_ratio": 0.0,
        "avg_duration_ms": 0,
        "model_count": 0,
        "period_basis": str(summary.get("periodBasis") or summary.get("_period_basis") or ""),
    }
