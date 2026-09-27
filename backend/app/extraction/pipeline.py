# -*- coding: utf-8 -*-
"""抽取流水线: 公告 HTML + 附件 ZIP → 结构化 AnnouncementRecord。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .attachments import (AttachmentParser, extract_item_lines,
                          extract_winners_from_text)
from .category import infer_category
from .html_parser import (AnnouncementHtmlParser, AnnouncementRecord,
                          ItemRecord, WinnerRecord)
from .llm_engine import llm_extract_json, record_from_llm
from .utils import is_company_like, normalize_org_name
from ..config import settings


@dataclass
class PipelineResult:
    record: AnnouncementRecord | None = None
    status: str = "ok"                # ok | partial | error
    message: str = ""
    duration_ms: int = 0
    attachments: list = field(default_factory=list)   # AttachmentResult.files


class ExtractionPipeline:
    """一次公告(html + zip)的完整抽取。"""

    def __init__(self, *, engine: str | None = None) -> None:
        self.engine = engine or settings.extraction_engine
        self.html_parser = AnnouncementHtmlParser()
        self.attachment_parser = AttachmentParser(libreoffice=settings.libreoffice_path)

    def run(self, html_path: str | Path, attachment_path: str | Path | None) -> PipelineResult:
        t0 = time.perf_counter()
        result = PipelineResult()
        html_path = Path(html_path)

        if not html_path.exists():
            result.status = "error"
            result.message = f"html 不存在: {html_path}"
            return result

        try:
            rec = self.html_parser.parse_file(str(html_path))
        except Exception as e:  # noqa: BLE001
            result.status = "error"
            result.message = f"html 解析失败: {e}"
            result.duration_ms = int((time.perf_counter() - t0) * 1000)
            return result

        attachment_text = ""
        if attachment_path and Path(attachment_path).exists():
            try:
                att = self.attachment_parser.parse(Path(attachment_path))
                result.attachments = att.files
                attachment_text = att.all_text
            except Exception as e:  # noqa: BLE001
                rec.status_extra = f"附件解析失败: {e}"  # type: ignore[attr-defined]

        # ---- 附件中标供应商补充(仅当 html 未抽到中标方; 避免招标文件正文误报) ----
        if attachment_text and not rec.winners:
            have: set[str] = set()
            for w in extract_winners_from_text(attachment_text):
                norm = normalize_org_name(w["org_raw"])
                if not norm or norm in have:
                    continue
                if not is_company_like(w["org_raw"]):
                    continue
                rec.winners.append(WinnerRecord(
                    org_norm=norm, org_raw=w["org_raw"],
                    amount_wan=w["amount_wan"], package=w["package"]))
                have.add(norm)

        # ---- 附件标的物行补充(按名称与 html 结果合并去重) ----
        if attachment_text:
            html_by_name = {i.product_name: i for i in rec.items}
            for line in extract_item_lines(attachment_text):
                name = line.get("product_name")
                if not name:
                    continue
                if name in html_by_name:
                    # 同名: 用附件补齐缺失字段
                    it = html_by_name[name]
                    for attr in ("brand", "spec_model", "quantity", "quantity_text",
                                 "quantity_unit", "unit_price", "total_price"):
                        if not getattr(it, attr) and line.get(attr):
                            setattr(it, attr, line.get(attr))
                    if it.unit_price is not None and it.quantity and it.total_price is None:
                        it.total_price = round(it.unit_price * it.quantity, 2)
                    continue
                rec.items.append(self._line_to_item(line, source="attachment"))

        # ---- 标的物去重(同名+同包+同数值视为重复) ----
        if rec.items:
            seen: set[tuple] = set()
            uniq: list[ItemRecord] = []
            for it in rec.items:
                key = (it.product_name, it.package, it.unit_price, it.quantity, it.brand)
                if key not in seen:
                    seen.add(key)
                    uniq.append(it)
            rec.items = uniq

        # ---- 品目推断(公告未注明品目且名称可识别时) ----
        if rec.items:
            for it in rec.items:
                if not it.category:
                    it.category = infer_category(it.product_name)

        # ---- 大模型增强 ----
        if self.engine in {"llm", "hybrid"}:
            try:
                data = llm_extract_json(rec.raw_text or rec.title, attachment_text)
                llm_rec = record_from_llm(data)
                if self.engine == "llm":
                    rec = llm_rec
                else:
                    self._merge_llm(rec, llm_rec)
            except Exception as e:  # noqa: BLE001
                result.message += f"LLM 抽取失败(已回退规则): {e}"

        # ---- 状态评估 ----
        if announcement_empty(rec):
            result.status = "error"
            result.message = (result.message + "; 未抽取到任何有效字段").strip("; ")
        elif not rec.items and not rec.winners:
            result.status = "partial"
            result.message = (result.message + "; 缺少标的物与中标供应商").strip("; ")
        else:
            result.status = "ok"

        result.record = rec
        result.duration_ms = int((time.perf_counter() - t0) * 1000)
        return result

    @staticmethod
    def _line_to_item(line: dict, *, source: str) -> ItemRecord:
        it = ItemRecord(source=source)
        it.product_name = str(line.get("product_name", ""))
        it.brand = str(line.get("brand", ""))
        it.spec_model = str(line.get("spec_model", ""))
        it.quantity = line.get("quantity")
        it.quantity_text = str(line.get("quantity_text", ""))
        it.quantity_unit = str(line.get("quantity_unit", ""))
        it.unit_price = line.get("unit_price")
        it.total_price = line.get("total_price")
        if it.unit_price is not None and it.quantity:
            it.total_price = round(it.unit_price * it.quantity, 2)
        return it

    @staticmethod
    def _merge_llm(rule_rec: AnnouncementRecord, llm_rec: AnnouncementRecord) -> None:
        """规则结果为主, 用 LLM 补缺失字段。"""
        if not rule_rec.project_name and llm_rec.project_name:
            rule_rec.project_name = llm_rec.project_name
        if not rule_rec.project_code and llm_rec.project_code:
            rule_rec.project_code = llm_rec.project_code
        if not rule_rec.procurement_unit and llm_rec.procurement_unit:
            rule_rec.procurement_unit = llm_rec.procurement_unit
        if rule_rec.total_amount_wan is None and llm_rec.total_amount_wan is not None:
            rule_rec.total_amount_wan = llm_rec.total_amount_wan
        rule_names = {w.org_norm for w in rule_rec.winners}
        for w in llm_rec.winners:
            if w.org_norm not in rule_names:
                rule_rec.winners.append(w)
        for b in llm_rec.bidders:
            if b not in rule_rec.bidders:
                rule_rec.bidders.append(b)
        # 标的物: 主体名相同的合并补字段
        llm_by_name = {i.product_name: i for i in llm_rec.items}
        for it in rule_rec.items:
            other = llm_by_name.get(it.product_name)
            if not other:
                continue
            for attr in ("category", "brand", "spec_model", "unit_price", "quantity",
                         "quantity_text", "quantity_unit", "total_price"):
                if not getattr(it, attr) and getattr(other, attr):
                    setattr(it, attr, getattr(other, attr))
            if not it.supplier_norm:
                it.supplier_norm = other.supplier_norm


def announcement_empty(rec: AnnouncementRecord) -> bool:
    return not (rec.title or rec.project_name or rec.procurement_unit or
                rec.winners or rec.items)
