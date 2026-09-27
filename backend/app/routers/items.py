# -*- coding: utf-8 -*-
"""标的物路由: 7 字段全字段检索 / 筛选 / 查看(任务三平台核心检索)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Announcement, TargetItem
from ..schemas import Page

router = APIRouter(prefix="/api/v1/items", tags=["items"])


@router.get("", response_model=Page)
def search_items(
    keyword: str = Query("", description="任意字段关键词"),
    product_name: str = Query(""),
    category: str = Query("", description="品目"),
    brand: str = Query("", description="品牌/产品供应商"),
    spec_model: str = Query("", description="规格型号"),
    source: str = Query("", description="html|attachment"),
    min_price: float | None = Query(None, description="单价下限(元)"),
    max_price: float | None = Query(None, description="单价上限(元)"),
    min_total: float | None = Query(None, description="总价下限(元)"),
    min_quantity: float | None = Query(None, description="数量下限"),
    announce_type: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(TargetItem, Announcement.title, Announcement.project_name,
                  Announcement.announce_type, Announcement.publish_date).join(
        Announcement, Announcement.id == TargetItem.announcement_id)

    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            TargetItem.product_name.like(like), TargetItem.brand.like(like),
            TargetItem.spec_model.like(like), TargetItem.category.like(like),
            Announcement.title.like(like)))
    if product_name:
        stmt = stmt.where(TargetItem.product_name.like(f"%{product_name}%"))
    if category:
        stmt = stmt.where(TargetItem.category.like(f"%{category}%"))
    if brand:
        stmt = stmt.where(TargetItem.brand.like(f"%{brand}%"))
    if spec_model:
        stmt = stmt.where(TargetItem.spec_model.like(f"%{spec_model}%"))
    if source:
        stmt = stmt.where(TargetItem.source == source)
    if min_price is not None:
        stmt = stmt.where(TargetItem.unit_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(TargetItem.unit_price <= max_price)
    if min_total is not None:
        stmt = stmt.where(TargetItem.total_price >= min_total)
    if min_quantity is not None:
        stmt = stmt.where(TargetItem.quantity >= min_quantity)
    if announce_type:
        stmt = stmt.where(Announcement.announce_type == announce_type)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(TargetItem.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for it, title, pname, atype, pdate in rows:
        d = {k: getattr(it, k) for k in
             ("id", "announcement_id", "seq", "source", "product_name", "category",
              "brand", "spec_model", "unit", "quantity", "quantity_text",
              "unit_price", "total_price")}
        d["announcement_title"] = title
        d["announcement_project"] = pname
        d["announce_type"] = atype
        d["publish_date"] = pdate
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{item_id}")
def item_detail(item_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        select(TargetItem, Announcement).join(Announcement, Announcement.id == TargetItem.announcement_id)
        .where(TargetItem.id == item_id)).first()
    if row is None:
        raise HTTPException(404, "标的物不存在")
    it, ann = row
    d = {k: getattr(it, k) for k in
         ("id", "announcement_id", "seq", "source", "product_name", "category",
          "brand", "spec_model", "unit", "quantity", "quantity_text", "unit_price",
          "total_price", "item_raw")}
    d["announcement"] = {"id": ann.id, "title": ann.title, "project_code": ann.project_code,
                         "publish_date": ann.publish_date, "total_amount_wan": ann.total_amount}
    return d
