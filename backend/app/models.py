# -*- coding: utf-8 -*-
"""ORM 数据模型(任务一抽取结果表 + 任务二关系模型表)。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now()


class Organization(Base):
    """市场主体: 采购单位 / 中标供应商 / 投标参与方 / 产品供应商 / 代理机构。"""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)          # 原文名称
    norm_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)  # 规范化名称(去包号/去空格)
    kind: Mapped[str] = mapped_column(String(30), default="unknown")        # 主要角色(示意)
    address: Mapped[str] = mapped_column(String(500), default="")
    contact: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    participations: Mapped[list["Participation"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("norm_name", name="uq_org_norm_name"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization {self.norm_name} [{self.kind}]>"


class Announcement(Base):
    """招采标讯公告(任务一/任务二的公告主表)。"""
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    title_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_name: Mapped[str] = mapped_column(String(600), default="")
    project_code: Mapped[str] = mapped_column(String(200), default="", index=True)
    announce_type: Mapped[str] = mapped_column(String(50), default="")      # 中标公告/成交公告/更正公告...
    publish_date: Mapped[str] = mapped_column(String(30), default="", index=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 万元
    agency_name: Mapped[str] = mapped_column(String(300), default="")
    procurement_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True)
    html_file: Mapped[str] = mapped_column(String(500), default="")
    attachment_file: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")           # ok/partial/error
    parse_ms: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default="")                 # 公告正文(供检索/复现)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    items: Mapped[list["TargetItem"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan")
    participations: Mapped[list["Participation"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan")
    procurement_org: Mapped[Organization | None] = relationship(
        foreign_keys=[procurement_org_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Announcement {self.id} {self.title[:30]}>"


class TargetItem(Base):
    """标的物(任务一 7 字段提取结果)。"""
    __tablename__ = "target_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="html")         # html | attachment

    product_name: Mapped[str] = mapped_column(String(600), default="")      # 产品服务名称
    category: Mapped[str] = mapped_column(String(300), default="", index=True)  # 品目
    brand: Mapped[str] = mapped_column(String(300), default="", index=True)     # 品牌(产品供应商)
    spec_model: Mapped[str] = mapped_column(String(500), default="")        # 规格型号
    unit: Mapped[str] = mapped_column(String(50), default="")               # 计量单位(套/块/台...)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)    # 数量(数值)
    quantity_text: Mapped[str] = mapped_column(String(50), default="")      # 数量原文(4套)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 单价(元)
    total_price: Mapped[float | None] = mapped_column(Float, nullable=True) # 总价(元)
    item_raw: Mapped[str] = mapped_column(Text, default="")                 # 原始文本片段

    announcement: Mapped[Announcement] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_items_name", "product_name"),
        Index("ix_items_brand", "brand"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TargetItem {self.id} {self.product_name} {self.brand}>"


class Participation(Base):
    """公告×主体 参与关系(任务二关系模型核心边表)。"""
    __tablename__ = "participations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), index=True)  # winner|bidder|product_supplier|agency
    package: Mapped[str] = mapped_column(String(100), default="")   # 标段/包号
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 中标金额(万元)
    note: Mapped[str] = mapped_column(String(300), default="")

    announcement: Mapped[Announcement] = relationship(back_populates="participations")
    organization: Mapped[Organization] = relationship(back_populates="participations")

    __table_args__ = (
        UniqueConstraint("announcement_id", "org_id", "role", "package",
                         name="uq_participation"),
        Index("ix_participation_org_role", "org_id", "role"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Participation {self.announcement_id} {self.role} {self.organization.norm_name}>"


class IngestTask(Base):
    """数据集导入任务记录(含处理速率统计)。"""
    __tablename__ = "ingest_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
