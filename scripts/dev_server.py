"""开发/测试专用: 起本地 HTTP 服务 (随机端口), 打桩上游接口 + 造演示数据, 打印访问地址.

用途: 浏览器 E2E / 手工调试 UI, 不触网、不碰真实数据目录.
运行: python scripts/dev_server.py --seed --seconds 600
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp(prefix="cmdgauge-dev-")
os.environ["CMDGAUGE_DATA"] = _tmpdir

from app import db, server  # noqa: E402
from app.commandcode_api import QuotaResult, QuotaWindow  # noqa: E402


def _fake_quota(cred=None, auth_type="cookie", org_id=None, name="Default",  # noqa: ARG001
                target_user_id=None):
    now_ms = int(time.time() * 1000)
    return QuotaResult(
        name=name or "Default", success=True, updated_at="",
        plan_id="individual-go", plan_name="Individual Go",
        windows=[
            QuotaWindow(label="5h", used=1.2, total=10.0, remaining=8.8, reset_in_sec=3600),
            QuotaWindow(label="Weekly", used=12.0, total=100.0, remaining=88.0, reset_in_sec=86400),
            QuotaWindow(label="Monthly", used=25.0, total=100.0, remaining=75.0, reset_in_sec=864000),
        ],
    )


def _rec(uid, hours_ago, model, inp, outp, cost, status="completed", duration=1200):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {
        "usg_id": uid, "created_at": ts, "model": model,
        "input_tokens": inp, "output_tokens": outp, "duration_ms": duration,
        "status": status, "mode": "agent", "type": "api",
        "input_cost": cost * 0.2, "output_cost": cost * 0.6, "cache_cost": 0.001,
        "cost_usd": cost, "trace_id": None,
    }


def seed() -> None:
    a1 = db.add_account("ck-demo-1", login="alice", switch=True)
    a2 = db.add_account("ck-demo-2", login="bob", switch=False)
    now = datetime.now(timezone.utc)
    models = ["deepseek/deepseek-v4.1-flash", "moonshotai/Kimi-K3", "gpt-5.6-luna"]
    recs = []
    for d in range(30):
        for i in range(3):
            h_ago = d * 24 + i * 3
            recs.append(_rec(
                f"demo-{d}-{i}", h_ago, models[(d + i) % 3],
                inp=1000 + d * 37, outp=200 + i * 11, cost=0.02 + (d % 7) * 0.01,
                status="completed" if (d + i) % 5 else "failed",
            ))
    db.insert_usage_records(recs, a1)
    db.insert_usage_records(recs[:20], a2)
    # 5 分钟聚合桶 (缓存维度): 最近 35 分钟, 2 个模型
    buckets = []
    for m, tin, cr in ((models[0], 98765, 81234), (models[1], 45321, 31200)):
        ts = (now - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:00")
        buckets.append({
            "bucket_key": f"{m}|{ts}", "model": m, "provider": "p", "time_bucket": ts,
            "requests": 12, "tokens_in": tin, "tokens_out": 3210, "tokens_total": tin + 3210,
            "input_cost": 0.02, "output_cost": 0.05, "cache_cost": 0.01,
            "cache_savings": 0.42, "total_cost": 0.08, "credits_total": 0.08,
            "consumed_free": 0.0, "consumed_monthly": 0.08, "consumed_purchased": 0.0,
            "consumed_total": 0.08, "cache_read_tokens": cr, "cache_creation_tokens": 400,
        })
    db.insert_usage_buckets(buckets, a1)
    db.save_session_info(a1, expires_at=(now + timedelta(days=6)).isoformat())
    db.save_session_info(a2, expires_at=(now + timedelta(days=1)).isoformat())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="造演示数据")
    ap.add_argument("--seconds", type=int, default=3600)
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    server.fetch_quota_any = _fake_quota
    if args.seed:
        seed()
    host, port = server.start_server(port=args.port, with_scheduler=False)
    print(json.dumps({"url": f"http://{host}:{port}/", "datadir": _tmpdir}), flush=True)
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_server()
        db.close_db()


if __name__ == "__main__":
    main()
