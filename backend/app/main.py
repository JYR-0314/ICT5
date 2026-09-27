# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

运行: uvicorn app.main:app --host 0.0.0.0 --port 8000
或:   python -m app.cli serve --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db

APP_NAME = "行业数据分析引擎 · 面向行业数据的智能实体挖掘与关系建模"
APP_VERSION = "1.0.0"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        description=(
            "赛题五后端：任务一(公告/附件实体自动化提取) + "
            "任务二(采购单位-中标供应商-投标参与方关系建模与 5 大业务场景) + "
            "任务三(数据集上传、自动解析入库、全字段检索与统计)。"
        ),
        version=APP_VERSION,
        lifespan=_lifespan,
        docs_url="/docs",
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .routers import announce, datasets, items, orgs, scenarios, stats

    app.include_router(datasets.router)
    app.include_router(announce.router)
    app.include_router(items.router)
    app.include_router(orgs.router)
    app.include_router(scenarios.router)
    app.include_router(stats.router)

    # 内置可视化平台(任务三演示环境, 同端口托管)
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/platform", include_in_schema=False)
        def platform() -> FileResponse:
            return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "engine": settings.extraction_engine,
            "llm_enabled": settings.llm_enabled,
            "docs": "/docs",
            "platform": "/platform",
            "health": "/api/v1/health",
            "api_prefix": "/api/v1",
        }

    @app.get("/api/v1/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": APP_VERSION, "engine": settings.extraction_engine}

    return app


app = create_app()
