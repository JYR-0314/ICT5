# -*- coding: utf-8 -*-
"""数据集上传与导入任务。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..ingest import run_ingest_task
from ..models import IngestTask
from ..schemas import Page, TaskOut

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    engine: str = Query("rule", description="rule|llm|hybrid"),
    db: Session = Depends(get_db),
) -> dict:
    """接收 zip 数据集(规范: 内含 html 公告 + 同名附件 zip), 异步自动解析入库。"""
    if engine not in {"rule", "llm", "hybrid"}:
        raise HTTPException(400, "engine 只能是 rule/llm/hybrid")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "仅支持 zip 格式的数据集压缩包")
    try:
        raw = await file.read()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"文件读取失败: {e}") from e

    save_dir = settings.upload_dir
    save_dir.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}_{file.filename}"
    path = save_dir / name
    path.write_bytes(raw)

    task = IngestTask(name=file.filename or name, status="queued")
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id

    def _bg() -> None:
        run_ingest_task(task_id, str(path), engine=engine)

    threading.Thread(target=_bg, daemon=True).start()
    return {"code": 0, "message": "上传成功, 后台自动解析中", "data": {"task_id": task_id}}


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> IngestTask:
    task = db.get(IngestTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/tasks", response_model=Page)
def list_tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func
    total = db.scalar(select(func.count(IngestTask.id))) or 0
    rows = list(db.scalars(
        select(IngestTask).order_by(IngestTask.id.desc())
        .offset((page - 1) * page_size).limit(page_size)))
    items = [TaskOut.model_validate(t).model_dump(mode="json") for t in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
