# -*- coding: utf-8 -*-
"""任务二: 五大业务场景查询 API。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import relation_service as svc

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


def _wrap(data: dict, started: float) -> dict:
    data["query_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return {"code": 0, "message": "ok", "data": data}


@router.get("/1")
def scenario1(
    procurement_unit: str = Query(..., description="采购单位名称"),
    db: Session = Depends(get_db),
) -> dict:
    """采购单位 → 长期/大量合作的中标供应商、产品供应商(合作次数、交易总额)。"""
    started = time.perf_counter()
    return _wrap(svc.scenario1_cooperation(db, procurement_unit), started)


@router.get("/2")
def scenario2(
    procurement_unit: str = Query(..., description="采购单位名称"),
    top_n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """采购单位 → 历史项目中高频(TOP5)参与投标主体与高频协同投标主体组合。"""
    started = time.perf_counter()
    return _wrap(svc.scenario2_frequent_bidders(db, procurement_unit, top_n=top_n), started)


@router.get("/3")
def scenario3(
    supplier: str = Query(..., description="中标供应商名称"),
    top_n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """中标供应商 → 高频(TOP5)共同竞标主体与全部参与投标主体(频次、总金额)。"""
    started = time.perf_counter()
    return _wrap(svc.scenario3_co_bidders(db, supplier, top_n=top_n), started)


@router.get("/4")
def scenario4(
    suppliers: str = Query(..., description="中标供应商名称, 多个以英文逗号/顿号分隔"),
    db: Session = Depends(get_db),
) -> dict:
    """多个中标供应商 → 与其均存在合作关系的采购单位、合作频次及金额。"""
    started = time.perf_counter()
    names = [s.strip() for s in suppliers.replace("、", ",").split(",") if s.strip()]
    return _wrap(svc.scenario4_common_units(db, names), started)


@router.get("/5")
def scenario5(
    suppliers: str = Query(..., description="中标供应商名称, 多个以英文逗号/顿号分隔"),
    db: Session = Depends(get_db),
) -> dict:
    """多个中标供应商 → 共同参与竞标的项目信息与竞标结果(项目数、总金额)。"""
    started = time.perf_counter()
    names = [s.strip() for s in suppliers.replace("、", ",").split(",") if s.strip()]
    return _wrap(svc.scenario5_common_projects(db, names), started)
