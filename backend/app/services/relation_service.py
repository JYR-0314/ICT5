# -*- coding: utf-8 -*-
"""任务二: 用户画像建模与关系分析服务(5 大业务场景)。

关系模型: 采购单位 —(发布)→ 公告 —(中标)→ 中标供应商
                                  └—(投标)→ 投标参与方
                                  └—(供货)→ 产品供应商(品牌)
"""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Announcement, Organization, Participation, TargetItem


# ---------------------------------------------------------------- 基础解析
def resolve_org(db: Session, query: str, kinds: tuple[str, ...] | None = None) -> Organization | None:
    """按名称解析主体: 优先规范化全名, 其次模糊匹配。"""
    q = (query or "").strip()
    if not q:
        return None
    org = db.scalar(select(Organization).where(
        Organization.norm_name == q).order_by(Organization.id))
    if org:
        return org
    stmt = select(Organization).where(Organization.norm_name.like(f"%{q}%"))
    if kinds:
        stmt = stmt.where(Organization.kind.in_(kinds))
    return db.scalar(stmt.order_by(Organization.id))


def org_participations(db: Session, org_id: int, role: str | None = None) -> list[Participation]:
    stmt = select(Participation).where(Participation.org_id == org_id)
    if role:
        stmt = stmt.where(Participation.role == role)
    return list(db.scalars(stmt))


def announcements_of(db: Session, org_id: int, role: str | None = None) -> list[Announcement]:
    parts = org_participations(db, org_id, role)
    ids = [p.announcement_id for p in parts]
    if not ids:
        return []
    return list(db.scalars(select(Announcement).where(Announcement.id.in_(ids))))


def _ann_dict(a: Announcement) -> dict:
    return {"announcement_id": a.id, "title": a.title, "project_name": a.project_name,
            "project_code": a.project_code, "publish_date": a.publish_date,
            "total_amount_wan": a.total_amount}


# ---------------------------------------------------------------- 场景 1
def scenario1_cooperation(db: Session, procurement_unit: str) -> dict:
    """指定采购单位: 合作中标供应商 + 产品供应商(合作次数/总金额)。"""
    org = resolve_org(db, procurement_unit, kinds=("procurement_unit",))
    if org is None:
        return {"matched": False, "procurement_unit": procurement_unit,
                "message": "未找到该采购单位", "cooperated_winners": [], "product_suppliers": []}

    anns = announcements_of(db, org.id, role="procurement_unit")
    ann_ids = [a.id for a in anns]
    if not ann_ids:
        return {"matched": True, "procurement_unit": org.norm_name,
                "cooperated_winners": [], "product_suppliers": [],
                "project_count": 0, "total_amount_wan": 0.0}

    # 中标供应商聚合
    winners: dict[int, dict] = {}
    for p in db.scalars(select(Participation).where(
            Participation.announcement_id.in_(ann_ids),
            Participation.role == "winner")):
        row = winners.setdefault(p.org_id, {"org_id": p.org_id, "organization": None,
                                            "cooperate_count": 0, "total_amount_wan": 0.0,
                                            "projects": []})
        row["cooperate_count"] += 1
        row["total_amount_wan"] += p.amount or 0
    # 产品供应商(品牌)聚合
    suppliers: dict[int, dict] = {}
    for p in db.scalars(select(Participation).where(
            Participation.announcement_id.in_(ann_ids),
            Participation.role == "product_supplier")):
        row = suppliers.setdefault(p.org_id, {"org_id": p.org_id, "organization": None,
                                              "cooperate_count": 0, "item_count": 0})
        row["cooperate_count"] += 1

    ann_by_id = {a.id: a for a in anns}
    win_list = []
    for row in winners.values():
        o = db.get(Organization, row["org_id"])
        row["organization"] = {"id": o.id, "name": o.norm_name} if o else None
        # 项目列表(取金额最高的 20 个)
        projs = [(p.announcement_id, p.amount) for p in db.scalars(
            select(Participation).where(Participation.announcement_id.in_(ann_ids),
                                        Participation.org_id == row["org_id"],
                                        Participation.role == "winner"))]
        projs.sort(key=lambda x: x[1] or 0, reverse=True)
        row["projects"] = [_ann_dict(ann_by_id[pid]) for pid, _ in projs[:20]]
        row["total_amount_wan"] = round(row["total_amount_wan"], 2)
        win_list.append(row)
    win_list.sort(key=lambda r: (r["cooperate_count"], r["total_amount_wan"]), reverse=True)

    sup_list = []
    for row in suppliers.values():
        o = db.get(Organization, row["org_id"])
        if o:
            row["organization"] = {"id": o.id, "name": o.norm_name}
            row["brand"] = o.norm_name
            sup_list.append(row)
    sup_list.sort(key=lambda r: r["cooperate_count"], reverse=True)

    return {"matched": True, "procurement_unit": org.norm_name,
            "project_count": len(ann_ids),
            "total_amount_wan": round(sum(a.total_amount or 0 for a in anns), 2),
            "cooperated_winners": win_list,
            "product_suppliers": sup_list}


# ---------------------------------------------------------------- 场景 2
def scenario2_frequent_bidders(db: Session, procurement_unit: str, top_n: int = 5) -> dict:
    """指定采购单位: TOP5 高频投标主体 + 高频协同投标主体组合。"""
    org = resolve_org(db, procurement_unit, kinds=("procurement_unit",))
    if org is None:
        return {"matched": False, "procurement_unit": procurement_unit,
                "message": "未找到该采购单位", "top_bidders": [], "top_co_bid_combos": []}
    ann_ids = [a.id for a in announcements_of(db, org.id, role="procurement_unit")]
    if not ann_ids:
        return {"matched": True, "procurement_unit": org.norm_name,
                "top_bidders": [], "top_co_bid_combos": [], "project_count": 0}

    # 参与投标主体频次(仅 role=bidder)
    freq: Counter = Counter()
    ann_bidders: dict[int, list[int]] = defaultdict(list)
    for p in db.scalars(select(Participation).where(
            Participation.announcement_id.in_(ann_ids),
            Participation.role == "bidder")):
        freq[p.org_id] += 1
        ann_bidders[p.announcement_id].append(p.org_id)

    top = []
    for org_id, cnt in freq.most_common(top_n):
        o = db.get(Organization, org_id)
        top.append({"organization": {"id": o.id, "name": o.norm_name} if o else None,
                    "bid_count": cnt})

    # 协同组合: 同一公告内任意两家投标方共同出现
    pair_cnt: Counter = Counter()
    for ids in ann_bidders.values():
        uq = sorted(set(ids))
        for i in range(len(uq)):
            for j in range(i + 1, len(uq)):
                pair_cnt[(uq[i], uq[j])] += 1

    combos = []
    for (a, b), cnt in pair_cnt.most_common():
        if cnt <= 1:
            break
        oa, ob = db.get(Organization, a), db.get(Organization, b)
        combos.append({"organization_a": {"id": oa.id, "name": oa.norm_name} if oa else None,
                       "organization_b": {"id": ob.id, "name": ob.norm_name} if ob else None,
                       "co_bid_count": cnt})
        if len(combos) >= top_n:
            break

    return {"matched": True, "procurement_unit": org.norm_name,
            "project_count": len(ann_ids), "top_bidders": top,
            "top_co_bid_combos": combos}


# ---------------------------------------------------------------- 场景 3
def scenario3_co_bidders(db: Session, supplier: str, top_n: int = 5) -> dict:
    """指定中标供应商: TOP5 共同竞标主体 + 全部参与投标主体(频次/总金额)。"""
    org = resolve_org(db, supplier)
    if org is None:
        return {"matched": False, "supplier": supplier, "message": "未找到该主体",
                "top_co_bidders": [], "all_participants": []}
    won_anns = announcements_of(db, org.id, role="winner")
    if not won_anns:
        return {"matched": True, "supplier": org.norm_name,
                "top_co_bidders": [], "all_participants": [], "project_count": 0}
    ann_ids = [a.id for a in won_anns]
    ann_by_id = {a.id: a for a in won_anns}

    partners: dict[int, dict] = {}
    for p in db.scalars(select(Participation).where(
            Participation.announcement_id.in_(ann_ids),
            Participation.org_id != org.id,
            Participation.role.in_(["winner", "bidder"]))):
        row = partners.setdefault(p.org_id, {"org_id": p.org_id, "count": 0,
                                             "total_amount_wan": 0.0, "projects": []})
        row["count"] += 1
        row["total_amount_wan"] += ann_by_id[p.announcement_id].total_amount or 0
        row["projects"].append(_ann_dict(ann_by_id[p.announcement_id]))

    rows = []
    for row in partners.values():
        o = db.get(Organization, row["org_id"])
        row["organization"] = {"id": o.id, "name": o.norm_name} if o else None
        row["total_amount_wan"] = round(row["total_amount_wan"], 2)
        row["projects"] = row["projects"][:10]
        rows.append(row)
    rows.sort(key=lambda r: (r["count"], r["total_amount_wan"]), reverse=True)

    return {"matched": True, "supplier": org.norm_name,
            "project_count": len(ann_ids),
            "top_co_bidders": rows[:top_n],
            "all_participants": rows}


# ---------------------------------------------------------------- 场景 4
def scenario4_common_units(db: Session, suppliers: list[str]) -> dict:
    """指定多个中标供应商: 与其均有合作关系的采购单位。"""
    resolved = []
    for s in suppliers:
        org = resolve_org(db, s)
        resolved.append((s, org))

    data = []
    for raw, org in resolved:
        if org is None:
            data.append({"query": raw, "matched": False})
            continue
        # 该中标供应商合作过的采购单位(金额取该供应商自身的各项目中标金额)
        units: dict[int, dict] = {}
        seen_ann: set[int] = set()
        for p in org_participations(db, org.id, role="winner"):
            if p.announcement_id in seen_ann:
                continue
            seen_ann.add(p.announcement_id)
            a = db.get(Announcement, p.announcement_id)
            if a is None or not a.procurement_org_id:
                continue
            row = units.setdefault(a.procurement_org_id,
                                   {"org_id": a.procurement_org_id, "count": 0,
                                    "total_amount_wan": 0.0})
            row["count"] += 1
            row["total_amount_wan"] += p.amount if p.amount is not None else (a.total_amount or 0)
        data.append({"query": raw, "matched": True,
                     "organization": {"id": org.id, "name": org.norm_name},
                     "units": units})

    if not any(d["matched"] for d in data):
        return {"matched": False, "message": "未找到任何中标供应商", "common_units": []}

    matched = [d for d in data if d["matched"]]
    common_ids: set[int] | None = None
    per_winner: dict[str, dict[int, dict]] = {}
    for d in matched:
        ids = set(d["units"].keys())
        per_winner[d["organization"]["name"]] = d["units"]
        common_ids = ids if common_ids is None else (common_ids & ids)

    # 每个共同采购单位: 与各中标供应商的合作频次/金额
    result_units = []
    for uid in sorted(common_ids or []):
        u = db.get(Organization, uid)
        per = {}
        total_cnt = total_amt = 0.0
        for wname, units in per_winner.items():
            row = units.get(uid)
            if row:
                per[wname] = {"cooperate_count": row["count"],
                              "total_amount_wan": round(row["total_amount_wan"], 2)}
                total_cnt += row["count"]
                total_amt += row["total_amount_wan"]
        result_units.append({
            "organization": {"id": u.id, "name": u.norm_name, "address": u.address} if u else None,
            "with_suppliers": per,
            "total_cooperate_count": total_cnt,
            "total_amount_wan": round(total_amt, 2),
            "supplier_count": len(matched),
        })

    result_units.sort(key=lambda r: (r["total_cooperate_count"], r["total_amount_wan"]), reverse=True)
    return {"matched": True, "suppliers": [d["organization"] for d in matched],
            "common_units": result_units}


# ---------------------------------------------------------------- 场景 5
def scenario5_common_projects(db: Session, suppliers: list[str]) -> dict:
    """指定多个中标供应商: 共同参与竞标的项目与结果。"""
    resolved = []
    for s in suppliers:
        org = resolve_org(db, s)
        if org is not None:
            parts = org_participations(db, org.id)
            ids = {p.announcement_id for p in parts}
            resolved.append({"query": s, "org": org, "ann_ids": ids})

    if not resolved:
        return {"matched": False, "message": "未找到任何中标供应商", "projects": []}

    common_ids: set[int] | None = None
    for r in resolved:
        common_ids = r["ann_ids"] if common_ids is None else (common_ids & r["ann_ids"])

    anns = list(db.scalars(select(Announcement).where(Announcement.id.in_(common_ids or []))))
    anns.sort(key=lambda a: a.publish_date or "", reverse=True)

    projects = []
    total_amount = 0.0
    for a in anns:
        roles = {}
        for r in resolved:
            p = db.scalar(select(Participation).where(
                Participation.announcement_id == a.id,
                Participation.org_id == r["org"].id))
            roles[r["org"].norm_name] = {"role": p.role if p else None,
                                         "amount_wan": p.amount,
                                         "package": p.package if p else ""}
        total_amount += a.total_amount or 0
        projects.append({**_ann_dict(a), "roles": roles,
                         "procurement_unit": a.procurement_org.norm_name if a.procurement_org else ""})

    return {"matched": True,
            "suppliers": [{"id": r["org"].id, "name": r["org"].norm_name} for r in resolved],
            "project_count": len(projects),
            "total_amount_wan": round(total_amount, 2),
            "projects": projects[:200]}
