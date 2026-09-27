# -*- coding: utf-8 -*-
"""Pydantic 响应模型(核心结构; 场景查询为动态 dict 直接输出)。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    norm_name: str
    kind: str
    address: str = ""
    contact: str = ""


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    announcement_id: int
    seq: int = 0
    source: str = "html"
    product_name: str = ""
    category: str = ""
    brand: str = ""
    spec_model: str = ""
    unit: str = ""
    quantity: Optional[float] = None
    quantity_text: str = ""
    unit_price: Optional[float] = None
    total_price: Optional[float] = None


class ParticipationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    announcement_id: int
    role: str
    package: str = ""
    amount: Optional[float] = None
    organization: Optional[OrgOut] = None


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    project_name: str = ""
    project_code: str = ""
    announce_type: str = ""
    publish_date: str = ""
    total_amount: Optional[float] = None
    agency_name: str = ""
    status: str = "ok"
    parse_ms: int = 0
    created_at: datetime


class AnnouncementDetail(AnnouncementOut):
    procurement_org: Optional[OrgOut] = None
    items: list[ItemOut] = []
    participations: list[ParticipationOut] = []


class Page(BaseModel):
    items: list[Any] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str = ""
    status: str = "queued"
    total: int = 0
    ok: int = 0
    failed: int = 0
    duration_ms: int = 0
    detail: Any = None


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None
