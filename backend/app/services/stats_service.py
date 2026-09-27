# -*- coding: utf-8 -*-
"""统计服务: 平台概览 + 知识图谱导出。"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Announcement, Organization, Participation, TargetItem


def overview(db: Session) -> dict:
    ann_cnt = db.scalar(select(func.count(Announcement.id))) or 0
    item_cnt = db.scalar(select(func.count(TargetItem.id))) or 0
    org_cnt = db.scalar(select(func.count(Organization.id))) or 0
    part_cnt = db.scalar(select(func.count(Participation.id))) or 0

    # 提取覆盖率: 有标的物的公告占比
    with_items = db.scalar(select(func.count(func.distinct(TargetItem.announcement_id)))) or 0
    coverage = round(with_items / ann_cnt, 4) if ann_cnt else 0.0

    avg_parse = db.scalar(select(func.avg(Announcement.parse_ms))) or 0

    # 抽取字段覆盖率(7 字段 + 建模字段)
    field_stats = {}
    checks = {
        "product_name": TargetItem.product_name != "",
        "category": TargetItem.category != "",
        "brand": TargetItem.brand != "",
        "spec_model": TargetItem.spec_model != "",
        "unit_price": TargetItem.unit_price.is_not(None),
        "quantity": TargetItem.quantity.is_not(None),
        "total_price": TargetItem.total_price.is_not(None),
    }
    for field, cond in checks.items():
        c = db.scalar(select(func.count(TargetItem.id)).where(cond)) or 0
        field_stats[field] = {"filled": c, "rate": round(c / item_cnt, 4) if item_cnt else 0.0}

    # 主体角色分布
    kind_cnt = dict(db.execute(
        select(Organization.kind, func.count(Organization.id)).group_by(Organization.kind)).all())

    # 公告类型分布
    type_cnt = dict(db.execute(
        select(Announcement.announce_type, func.count(Announcement.id))
        .group_by(Announcement.announce_type)).all())

    # 采购单位 TOP10
    unit_rows = db.execute(
        select(Announcement.procurement_org_id, func.count(Announcement.id))
        .where(Announcement.procurement_org_id.is_not(None))
        .group_by(Announcement.procurement_org_id)
        .order_by(func.count(Announcement.id).desc()).limit(10)).all()
    top_units = []
    for org_id, cnt in unit_rows:
        o = db.get(Organization, org_id)
        top_units.append({"id": org_id, "name": o.norm_name if o else f"#{org_id}", "count": cnt})

    # 中标供应商 TOP10(按中标金额)
    win_rows = db.execute(
        select(Participation.org_id, func.count(Participation.id),
               func.sum(Participation.amount))
        .where(Participation.role == "winner")
        .group_by(Participation.org_id)
        .order_by(func.sum(Participation.amount).desc()).limit(10)).all()
    top_winners = []
    for org_id, cnt, amt in win_rows:
        o = db.get(Organization, org_id)
        top_winners.append({"id": org_id, "name": o.norm_name if o else f"#{org_id}",
                            "win_count": cnt, "total_amount_wan": round(float(amt or 0), 2)})

    return {
        "announcements": ann_cnt, "target_items": item_cnt,
        "organizations": org_cnt, "participations": part_cnt,
        "extract_coverage": coverage,
        "avg_parse_ms": round(float(avg_parse or 0), 1),
        "field_stats": field_stats,
        "org_kinds": kind_cnt,
        "announce_types": type_cnt,
        "top_procurement_units": top_units,
        "top_winners": top_winners,
    }


def graph_export(db: Session, *, max_nodes: int = 160) -> dict:
    """输出图数据(节点+边), 供前端图谱可视化。

    取"高频参与主体 + 采购单位枢纽"构成节点集, 保证关系丰富、可读性强。
    """
    # 1) 按参与次数取 TOP 主体
    rows = db.execute(
        select(Participation.org_id, func.count(Participation.id))
        .group_by(Participation.org_id)
        .order_by(func.count(Participation.id).desc()).limit(max_nodes)).all()
    org_ids = {r[0] for r in rows if r[0] is not None}
    # 2) 补充采购单位(关系枢纽, 即使参与不多也要展示)
    pu_ids = {r[0] for r in db.execute(
        select(Announcement.procurement_org_id, func.count(Announcement.id))
        .where(Announcement.procurement_org_id.is_not(None))
        .group_by(Announcement.procurement_org_id)
        .order_by(func.count(Announcement.id).desc()).limit(max_nodes // 2)).all()}
    for pid in pu_ids:
        if len(org_ids) < max_nodes:
            org_ids.add(pid)
    orgs = list(db.scalars(select(Organization).where(Organization.id.in_(org_ids))))
    nodes = []
    for o in orgs:
        nodes.append({"id": f"org-{o.id}", "name": o.norm_name, "kind": o.kind})

    parts = list(db.scalars(select(Participation).where(
        Participation.org_id.in_(org_ids)).order_by(Participation.announcement_id)))
    edges: list[dict] = []
    seen: set[tuple] = set()
    # 采购单位 → 中标供应商 / 投标方 / 产品供应商
    for p in parts:
        if p.org_id not in org_ids:
            continue
        a = db.get(Announcement, p.announcement_id)
        if a is None or not a.procurement_org_id or a.procurement_org_id not in org_ids:
            continue
        key = ("cooperate" if p.role == "winner" else
               "bid" if p.role == "bidder" else "supply" if p.role == "product_supplier" else None)
        if key is None:
            continue
        if (a.procurement_org_id, p.org_id, key) in seen:
            continue
        seen.add((a.procurement_org_id, p.org_id, key))
        edges.append({"source": f"org-{a.procurement_org_id}", "target": f"org-{p.org_id}",
                      "relation": key, "announcement_id": a.id,
                      "amount_wan": p.amount})

    return {"nodes": nodes, "edges": edges}
