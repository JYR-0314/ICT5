# -*- coding: utf-8 -*-
"""市场主体路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Announcement, Organization, Participation, TargetItem
from ..schemas import OrgOut, Page

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


@router.get("", response_model=Page)
def list_orgs(
    query: str = Query("", description="名称关键词"),
    kind: str = Query("", description="procurement_unit|winner|bidder|product_supplier|agency"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Organization)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(Organization.norm_name.like(like), Organization.name.like(like)))
    if kind:
        stmt = stmt.where(Organization.kind == kind)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Organization.id.desc())
                           .offset((page - 1) * page_size).limit(page_size)))
    items = [OrgOut.model_validate(o).model_dump(mode="json") for o in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{org_id}", response_model=OrgOut)
def org_detail(org_id: int, db: Session = Depends(get_db)) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "主体不存在")
    return org


@router.get("/{org_id}/profile")
def org_profile(org_id: int, db: Session = Depends(get_db)) -> dict:
    """主体画像: 基本档案 + 中标/投标/合作统计 + 项目清单。"""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "主体不存在")

    parts = list(db.scalars(select(Participation).where(Participation.org_id == org_id)))
    ann_ids = {p.announcement_id for p in parts}
    anns = list(db.scalars(select(Announcement).where(Announcement.id.in_(ann_ids or [0]))))
    ann_by_id = {a.id: a for a in anns}

    role_stats: dict[str, dict] = {}
    for p in parts:
        st = role_stats.setdefault(p.role, {"count": 0, "total_amount_wan": 0.0})
        st["count"] += 1
        st["total_amount_wan"] += p.amount or 0
    for k in role_stats:
        role_stats[k]["total_amount_wan"] = round(role_stats[k]["total_amount_wan"], 2)

    # 关联采购单位(合作过的)
    coop_units: dict[int, dict] = {}
    for a in anns:
        if a.procurement_org_id:
            row = coop_units.setdefault(a.procurement_org_id, {"org_id": a.procurement_org_id,
                                                               "count": 0, "total_amount_wan": 0.0})
            row["count"] += 1
            row["total_amount_wan"] += a.total_amount or 0
    units_out = []
    for uid, row in sorted(coop_units.items(),
                           key=lambda kv: (kv[1]["count"], kv[1]["total_amount_wan"]), reverse=True)[:20]:
        u = db.get(Organization, uid)
        units_out.append({"organization": {"id": u.id, "name": u.norm_name} if u else None,
                          "cooperate_count": row["count"],
                          "total_amount_wan": round(row["total_amount_wan"], 2)})

    # 项目清单
    projects = []
    for p in parts[:200]:
        a = ann_by_id.get(p.announcement_id)
        if a is None:
            continue
        projects.append({
            "announcement_id": a.id, "title": a.title, "project_code": a.project_code,
            "publish_date": a.publish_date, "role": p.role, "package": p.package,
            "amount_wan": p.amount,
            "procurement_unit": a.procurement_org.norm_name if a.procurement_org else ""})
    projects.sort(key=lambda x: x["publish_date"] or "", reverse=True)

    return {"id": org.id, "name": org.norm_name, "original_names": org.name, "kind": org.kind,
            "address": org.address, "contact": org.contact,
            "role_stats": role_stats, "project_count": len(anns),
            "cooperated_units": units_out, "projects": projects}
