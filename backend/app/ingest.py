# -*- coding: utf-8 -*-
"""入库引擎: 公告记录 → 数据库(任务一结果表 + 任务二关系模型)。

- 市场主体(Organizations)按规范化名称合并;
- 公告(Announcements)按标题哈希去重(支持重复导入覆盖更新);
- 参与关系(Participations)支持 采购单位/中标供应商/投标参与方/产品供应商 四类角色。
"""
from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .extraction.html_parser import AnnouncementRecord, ItemRecord, WinnerRecord
from .extraction.pipeline import ExtractionPipeline, PipelineResult
from .models import Announcement, IngestTask, Organization, Participation, TargetItem
from .config import settings

# 角色优先级(用于合并企业时标注主要角色)
_KIND_PRIORITY = {"procurement_unit": 5, "winner": 4, "bidder": 3,
                  "product_supplier": 2, "agency": 1, "unknown": 0}


# ---------------------------------------------------------------- 数据集发现
@dataclass
class DatasetUnit:
    index: int
    html: Path
    attachment: Path | None


def _match_zip_for_html(html: Path, zips: list[Path]) -> Path | None:
    stem = html.stem
    for z in zips:
        if z.stem == stem:
            return z
    # 附件包文件名可能为 "附件-<stem>" / "attachment-<stem>"
    for z in zips:
        if stem in z.stem and z.suffix.lower() == ".zip":
            return z
    return None


def discover_dataset(path: str | Path) -> (list[DatasetUnit], Path | None):
    """解析数据集目录/压缩包, 返回 (公告单元列表, 临时目录或 None)。

    目录内一层 html + 同名 zip; 也支持每篇公告一个子目录。
    """
    path = Path(path)
    tmpdir: Path | None = None
    if path.is_file() and path.suffix.lower() == ".zip":
        tmpdir = Path(tempfile.mkdtemp(prefix="dsh_ds_"))
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(tmpdir)
        except zipfile.BadZipFile:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise ValueError(f"不是有效的 zip 文件: {path}")
        path = tmpdir

    htmls = sorted(p for p in path.rglob("*.html") if p.is_file())
    zips = sorted(p for p in path.rglob("*.zip") if p.is_file())
    units: list[DatasetUnit] = []
    used_zips: set[Path] = set()
    for i, h in enumerate(htmls, start=1):
        zip_match = _match_zip_for_html(h, zips)
        if zip_match:
            used_zips.add(zip_match)
        else:
            # 同目录恰好一个 zip(或多个但同名前缀匹配失败时取同目录第一个)
            siblings = [z for z in zips if z.parent == h.parent and z not in used_zips]
            zip_match = siblings[0] if len(siblings) == 1 else None
        units.append(DatasetUnit(index=i, html=h, attachment=zip_match))
    return units, tmpdir


# ---------------------------------------------------------------- 单条入库
def upsert_organization(db: Session, name: str, kind: str = "unknown",
                        address: str = "", contact: str = "") -> Organization | None:
    name = (name or "").strip()
    if not name:
        return None
    org = db.scalar(select(Organization).where(Organization.norm_name == name))
    if org is None:
        org = Organization(name=name, norm_name=name, kind=kind,
                           address=address or "", contact=contact or "")
        db.add(org)
        db.flush()
    else:
        if _KIND_PRIORITY.get(kind, 0) > _KIND_PRIORITY.get(org.kind or "unknown", 0):
            org.kind = kind
        if address and not org.address:
            org.address = address
        if contact and not org.contact:
            org.contact = contact
    return org


def _apply_winners(db: Session, ann: Announcement, rec: AnnouncementRecord,
                   added: set[tuple[int, str, str]]) -> None:
    if not rec.winners:
        return
    for w in rec.winners:
        org = upsert_organization(db, w.org_norm, kind="winner")
        if org is None:
            continue
        key = (org.id, "winner", w.package or "")
        if key in added:
            continue
        added.add(key)
        db.add(Participation(announcement_id=ann.id, org_id=org.id, role="winner",
                             package=w.package or "", amount=w.amount_wan))


def _apply_bidders(db: Session, ann: Announcement, rec: AnnouncementRecord,
                   added: set[tuple[int, str, str]]) -> None:
    for name in rec.bidders:
        org = upsert_organization(db, name, kind="bidder")
        if org is None:
            continue
        key = (org.id, "bidder", "")
        if key in added:
            continue
        added.add(key)
        db.add(Participation(announcement_id=ann.id, org_id=org.id, role="bidder"))


def _apply_items(db: Session, ann: Announcement, rec: AnnouncementRecord,
                 added: set[tuple[int, str, str]]) -> None:
    # 覆盖式更新: 先删旧标的物
    for old in db.scalars(select(TargetItem).where(TargetItem.announcement_id == ann.id)):
        db.delete(old)
    db.flush()

    winner_by_pkg: dict[str, WinnerRecord] = {}
    for w in rec.winners:
        winner_by_pkg.setdefault(w.package or "", w)

    for it in rec.items:
        item = TargetItem(
            announcement_id=ann.id, seq=it.seq, source=it.source,
            product_name=it.product_name or "", category=it.category or "",
            brand=it.brand or "", spec_model=it.spec_model or "",
            unit=it.quantity_unit or "", quantity=it.quantity,
            quantity_text=it.quantity_text or "",
            unit_price=it.unit_price, total_price=it.total_price,
            item_raw=it.item_raw[:2000] or "",
        )
        db.add(item)

        # 产品供应商(品牌)关系
        brand = (it.brand or "").strip()
        if brand and brand not in {"无", "-", "/"}:
            porg = upsert_organization(db, brand, kind="product_supplier")
            if porg is not None:
                key = (porg.id, "product_supplier", "")
                if key not in added:
                    added.add(key)
                    db.add(Participation(announcement_id=ann.id, org_id=porg.id,
                                         role="product_supplier", note=it.product_name))
        if it.supplier_norm:
            s_org = upsert_organization(db, it.supplier_norm, kind="winner")
            if s_org is not None:
                pkg = it.package or ""
                w = winner_by_pkg.get(pkg)
                key = (s_org.id, "winner", pkg)
                if key not in added:
                    added.add(key)
                    db.add(Participation(announcement_id=ann.id, org_id=s_org.id,
                                         role="winner", package=pkg,
                                         amount=w.amount_wan if w else None))


def persist_record(db: Session, rec: AnnouncementRecord, *,
                   html_path: str = "", zip_path: str = "",
                   status: str = "ok", parse_ms: int = 0) -> Announcement:
    """把 AnnouncementRecord 写入数据库(幂等)。"""
    # 公告主体
    ann = db.scalar(select(Announcement).where(Announcement.title_hash == rec.title_hash))
    if ann is None:
        ann = Announcement(title_hash=rec.title_hash, title=rec.title)
        db.add(ann)
    ann.title = rec.title
    ann.project_name = rec.project_name or rec.title
    ann.project_code = rec.project_code
    ann.announce_type = rec.announce_type
    ann.publish_date = rec.publish_date
    ann.total_amount = rec.total_amount_wan
    ann.agency_name = rec.agency_name
    ann.html_file = html_path
    ann.attachment_file = zip_path
    ann.status = status
    ann.parse_ms = parse_ms
    ann.raw_text = rec.raw_text[:20000]
    db.flush()

    # 采购单位
    if rec.procurement_unit:
        porg = upsert_organization(db, rec.procurement_unit, kind="procurement_unit")
        if porg is not None:
            ann.procurement_org_id = porg.id
            exists = db.scalar(select(Participation).where(
                Participation.announcement_id == ann.id,
                Participation.org_id == porg.id,
                Participation.role == "procurement_unit",
            ))
            if exists is None:
                db.add(Participation(announcement_id=ann.id, org_id=porg.id,
                                     role="procurement_unit"))
    # 代理机构
    if rec.agency_name:
        aorg = upsert_organization(db, rec.agency_name, kind="agency")
        if aorg is not None:
            exists = db.scalar(select(Participation).where(
                Participation.announcement_id == ann.id,
                Participation.org_id == aorg.id,
                Participation.role == "agency"))
            if exists is None:
                db.add(Participation(announcement_id=ann.id, org_id=aorg.id, role="agency"))

    # 先清理旧参与关系(保留采购单位/代理), 再重建中标/投标/产品供应商
    for p in db.scalars(select(Participation).where(
            Participation.announcement_id == ann.id,
            Participation.role.in_(["winner", "bidder", "product_supplier"]))):
        db.delete(p)
    db.flush()

    added: set[tuple[int, str, str]] = set()
    _apply_winners(db, ann, rec, added)
    _apply_bidders(db, ann, rec, added)
    _apply_items(db, ann, rec, added)
    db.flush()
    return ann


# ---------------------------------------------------------------- 批量入库
def ingest_one(db: Session, unit: DatasetUnit, *, engine: str | None = None) -> tuple[bool, str, int]:
    html = unit.html
    zipf = unit.attachment
    pipe = ExtractionPipeline(engine=engine)
    res: PipelineResult = pipe.run(html, zipf)
    try:
        if res.record is not None and res.status != "error":
            ann = persist_record(db, res.record,
                                 html_path=str(html),
                                 zip_path=str(zipf) if zipf else "",
                                 status=res.status, parse_ms=res.duration_ms)
            db.commit()
            return True, f"ann#{ann.id} {ann.title[:20]}", res.duration_ms
        db.rollback()
        return False, res.message or "empty record", res.duration_ms
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return False, f"入库失败: {e}", res.duration_ms


def run_ingest_task(task_id: int, dataset_path: str, *, engine: str | None = None) -> None:
    """后台任务: 处理整个数据集, 更新 IngestTask 进度。"""
    db = SessionLocal()
    task = db.get(IngestTask, task_id)
    if task is None:
        db.close()
        return
    t0 = time.perf_counter()
    task.status = "running"
    db.commit()
    tmpdir: Path | None = None
    try:
        units, tmpdir = discover_dataset(dataset_path)
        task.total = len(units)
        db.commit()
        ok = failed = 0
        detail: list[dict] = []
        timeouts = []
        for unit in units:
            try:
                success, msg, ms = ingest_one(db, unit, engine=engine)
                timeouts.append(ms)
                if success:
                    ok += 1
                else:
                    failed += 1
                detail.append({"index": unit.index, "html": unit.html.name,
                               "ok": success, "msg": msg[:120], "ms": ms})
                task.ok, task.failed = ok, failed
                task.detail = detail[-500:]
                db.commit()
            except Exception as e:  # noqa: BLE001
                failed += 1
                detail.append({"index": unit.index, "html": unit.html.name, "ok": False,
                               "msg": str(e)[:120], "ms": 0})
                task.ok, task.failed = ok, failed
                db.commit()
        task.status = "done"
        task.duration_ms = int((time.perf_counter() - t0) * 1000)
        avg = sum(timeouts) / len(timeouts) if timeouts else 0
        task.detail = {"summary": {"ok": ok, "failed": failed,
                                   "avg_ms_per_announcement": round(avg, 1)},
                       "items": detail[-500:]}
        db.commit()
    except Exception as e:  # noqa: BLE001
        task.status = "failed"
        task.detail = {"error": str(e)}
        db.commit()
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        db.close()


DEF_ENGINE = settings.extraction_engine
