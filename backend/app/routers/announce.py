# -*- coding: utf-8 -*-
"""公告路由: 列表检索 + 详情。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Announcement, Organization, Participation
from ..schemas import AnnouncementDetail, Page

router = APIRouter(prefix="/api/v1/announcements", tags=["announcements"])


@router.get("", response_model=Page)
def list_announcements(
    keyword: str = Query("", description="标题/项目名称/编号 关键词"),
    procurement_unit: str = Query("", description="采购单位名称"),
    announce_type: str = Query("", description="公告类型"),
    from_date: str = Query("", description="发布日期起 YYYY-MM-DD"),
    to_date: str = Query("", description="发布日期止 YYYY-MM-DD"),
    min_amount: float | None = Query(None, description="总金额下限(万元)"),
    max_amount: float | None = Query(None, description="总金额上限(万元)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Announcement)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Announcement.title.like(like),
                              Announcement.project_name.like(like),
                              Announcement.project_code.like(like)))
    if procurement_unit:
        org = db.scalar(select(Organization).where(Organization.norm_name.like(f"%{procurement_unit}%")))
        if org is not None:
            stmt = stmt.where(Announcement.procurement_org_id == org.id)
        else:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
    if announce_type:
        stmt = stmt.where(Announcement.announce_type == announce_type)
    if from_date:
        stmt = stmt.where(Announcement.publish_date >= from_date)
    if to_date:
        stmt = stmt.where(Announcement.publish_date <= to_date)
    if min_amount is not None:
        stmt = stmt.where(Announcement.total_amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Announcement.total_amount <= max_amount)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Announcement.publish_date.desc(), Announcement.id.desc())
                           .offset((page - 1) * page_size).limit(page_size)))
    from ..schemas import AnnouncementOut
    items = [AnnouncementOut.model_validate(a).model_dump(mode="json") for a in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{ann_id}", response_model=AnnouncementDetail)
def announcement_detail(ann_id: int, db: Session = Depends(get_db)) -> Announcement:
    ann = db.scalar(
        select(Announcement)
        .where(Announcement.id == ann_id)
        .options(selectinload(Announcement.items), selectinload(Announcement.participations))
    )
    if ann is None:
        raise HTTPException(404, "公告不存在")
    # 惰性加载参与方主体
    _ = [p.organization for p in ann.participations]
    _ = ann.procurement_org
    return ann
