# -*- coding: utf-8 -*-
"""命令行入口。

用法:
    python -m app.cli ingest <数据集目录或zip> [--engine rule|llm|hybrid] [--limit N]
    python -m app.cli stats
    python -m app.cli reset
    python -m app.cli serve [--port 8000]
"""
from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import func, select

from .config import settings
from .database import SessionLocal, init_db
from .models import Announcement, IngestTask, Organization, TargetItem


def cmd_ingest(args: argparse.Namespace) -> int:
    init_db()
    from .ingest import discover_dataset, ingest_one

    units, tmpdir = discover_dataset(args.path)
    if args.limit:
        units = units[: args.limit]
    print(f"发现公告 {len(units)} 篇 | 引擎: {args.engine}")
    db = SessionLocal()
    t0 = time.perf_counter()
    ok = failed = 0
    total_ms = 0
    for u in units:
        success, msg, ms = ingest_one(db, u, engine=args.engine)
        total_ms += ms
        mark = "OK " if success else "ERR"
        print(f"[{mark}] #{u.index:>3} {u.html.name:<60} {ms:>6}ms  {msg}")
        ok += success
        failed += 0 if success else 1
    elapsed = time.perf_counter() - t0
    avg = total_ms / len(units) if units else 0
    print("-" * 80)
    print(f"完成: 成功 {ok} / 失败 {failed} | 总耗时 {elapsed:.1f}s | "
          f"单篇平均 {avg:.0f}ms")
    db.close()
    return 0 if failed == 0 else 1


def cmd_stats(_args: argparse.Namespace) -> int:
    init_db()
    db = SessionLocal()
    ann_cnt = db.scalar(select(func.count(Announcement.id))) or 0
    item_cnt = db.scalar(select(func.count(TargetItem.id))) or 0
    org_cnt = db.scalar(select(func.count(Organization.id))) or 0
    task_cnt = db.scalar(select(func.count(IngestTask.id))) or 0
    print(f"公告: {ann_cnt}  标的物: {item_cnt}  主体: {org_cnt}  导入任务: {task_cnt}")
    db.close()
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    db_path = settings.data_dir / "dsh.db"
    if db_path.exists():
        db_path.unlink()
    init_db()
    print(f"已重置数据库: {db_path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    init_db()
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=args.port or settings.port,
                reload=settings.reload, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dsh-backend", description="赛题五后端 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="导入数据集")
    p_ingest.add_argument("path", help="数据集目录或 zip 压缩包")
    p_ingest.add_argument("--engine", choices=["rule", "llm", "hybrid"], default=settings.extraction_engine)
    p_ingest.add_argument("--limit", type=int, default=None)
    p_ingest.set_defaults(fn=cmd_ingest)

    p_stats = sub.add_parser("stats", help="统计")
    p_stats.set_defaults(fn=cmd_stats)

    p_reset = sub.add_parser("reset", help="重置数据库")
    p_reset.set_defaults(fn=cmd_reset)

    p_serve = sub.add_parser("serve", help="启动 API 服务")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(fn=cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
