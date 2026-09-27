# -*- coding: utf-8 -*-
"""统计与图谱路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import stats_service

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    """平台概览统计(数据量/覆盖率/字段填充率/排行)。"""
    return {"code": 0, "message": "ok", "data": stats_service.overview(db)}


@router.get("/graph")
def graph(max_nodes: int = Query(200, ge=10, le=2000),
          db: Session = Depends(get_db)) -> dict:
    """知识图谱数据(供前端 ECharts/vis.js 可视化)。"""
    return {"code": 0, "message": "ok", "data": stats_service.graph_export(db, max_nodes=max_nodes)}
