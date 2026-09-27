# -*- coding: utf-8 -*-
"""便捷启动脚本。

用法:
    python run.py                 # 启动 API(默认 0.0.0.0:8000, 文档 /docs)
    python run.py --port 8080
    python run.py --engine llm    # 切到大模型抽取引擎(需配置 LLM_API_KEY)
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="赛题五后端启动器")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--engine", choices=["rule", "llm", "hybrid"], default=None,
                        help="实体抽取引擎(default: rule, 离线可用; llm/hybrid 需 LLM_API_KEY)")
    args = parser.parse_args()

    if args.engine:
        os.environ["EXTRACTION_ENGINE"] = args.engine

    import uvicorn
    from app.config import Settings

    # 用默认配置启动 (避免在 import 时重复解析)
    host = args.host or os.getenv("DSH_HOST", "0.0.0.0")
    port = args.port or int(os.getenv("DSH_PORT", "8000"))
    print(f"启动行业数据分析引擎后端 -> http://{host}:{port}  (文档: /docs)")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
