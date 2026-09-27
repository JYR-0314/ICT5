# -*- coding: utf-8 -*-
"""大模型抽取引擎(OpenAI 兼容接口, 适配 Qwen / DeepSeek 等国产开源大模型)。

通过环境变量配置:
    LLM_BASE_URL  默认 https://dashscope.aliyuncs.com/compatible-mode/v1
    LLM_API_KEY   必填
    LLM_MODEL     默认 qwen-plus

与规则引擎配合使用:
    EXTRACTION_ENGINE=rule   (默认, 纯规则, 离线可用)
    EXTRACTION_ENGINE=llm    (每条公告调用一次大模型)
    EXTRACTION_ENGINE=hybrid (规则优先, 大模型补充缺失的主休/标的物)
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import settings
from .html_parser import AnnouncementRecord, ItemRecord, WinnerRecord
from .utils import clean_text, normalize_org_name, parse_amount, parse_number, parse_quantity

SYSTEM_PROMPT = """你是政府采购招投标领域的资深信息抽取专家。请从用户提供的【公告文本】中抽取结构化信息，严格遵守以下要求：
1. 只输出 JSON, 不要输出任何解释文字。
2. JSON 结构必须为:
{
  "project_name": "项目名称(如与公告标题一致可复用)",
  "project_code": "项目编号或招标编号(没有则空字符串)",
  "procurement_unit": "采购单位/招标人名称",
  "publish_date": "公告发布日期 YYYY-MM-DD(没有则空字符串)",
  "total_amount_wan": 总中标金额(单位:万元, 数字或null),
  "agency_name": "采购代理机构名称(没有则空字符串)",
  "winners": [{"name": "中标供应商全称", "amount_wan": 中标金额(万元,数字或null), "package": "包号(如'第3包',没有则空字符串)"}],
  "bidders": ["参与投标但未中标的供应商全称"],
  "items": [{"product_name": "产品服务名称", "category": "品目", "brand": "品牌/产品供应商",
             "spec_model": "规格型号", "unit_price": 单价(元,数字或null),
             "quantity": 数量(数字或null), "quantity_text": "数量原文如'4套'",
             "total_price": 总价(元,数字或null), "supplier": "提供该标的的中标供应商(可选)"}]
}
3. 金额统一换算：单价、总价用"元"，中标金额、总中标金额用"万元"；提取不到一律为 null。
4. 供应商名称要去掉"第X包 xxx："这类包号前缀, 保留公司全称。
5. items 中的"品牌"是指产品品牌/生产厂家, 若只提供规格型号没有品牌则品牌为空字符串。
"""


def _build_user_prompt(html_text: str, attachment_text: str | None = None,
                       chunk_no: int = 0, chunk_total: int = 0) -> str:
    parts = []
    if chunk_total > 1:
        parts.append(f"【公告文本 第{chunk_no}/{chunk_total}块】")
    else:
        parts.append("【公告文本】")
    parts.append(html_text)
    if attachment_text:
        if chunk_total > 1:
            parts.append(f"\n【附件文本 第{chunk_no}/{chunk_total}块】")
        else:
            parts.append("\n【附件文本】")
        parts.append(attachment_text)
    if chunk_total > 1:
        parts.append("\n注意：这是分块文本之一。项目名称/项目编号/采购单位等公告级字段只在第 1 块填写；"
                     "其余块只提取本块中出现的 items/winners/bidders，不要编造本块没有的内容。")
    parts.append("\n请严格按照格式输出 JSON。")
    return "\n".join(parts)


def _chunk_text(text: str, *, limit: int = 9000, max_chunks: int = 4) -> list[str]:
    """按行边界切块, 避免超过模型上下文; 超长只取前 max_chunks 块。"""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and cur:
            chunks.append("".join(cur))
            cur, size = [], 0
            if len(chunks) >= max_chunks:
                break
        cur.append(line)
        size += len(line)
    if cur and len(chunks) < max_chunks:
        chunks.append("".join(cur))
    if not chunks:
        chunks = [text[: limit * max_chunks]]
    return chunks


def _call_model(payload: dict) -> dict[str, Any]:
    """单次调用大模型, 失败自动重试 1 次。"""
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=settings.llm_timeout) as client:
                resp = client.post(payload["_url"], json=payload["_body"],
                                   headers=payload["_headers"])
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", content, re.S)
                if m:
                    return json.loads(m.group(0))
                raise ValueError(f"模型返回非 JSON: {content[:200]}")
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"大模型调用失败(已重试): {last_err}")


def _merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """分块结果合并: 公告级字段取首个非空, 条目类字段拼接去重。"""
    merged: dict[str, Any] = {}
    items: list[Any] = []
    winners: list[Any] = []
    bidders: list[str] = []
    seen_w: set[str] = set()
    seen_b: set[str] = set()
    for r in results:
        if not isinstance(r, dict):
            continue
        for k in ("project_name", "project_code", "procurement_unit", "publish_date",
                  "total_amount_wan", "agency_name"):
            if k not in merged and r.get(k):
                merged[k] = r[k]
        for it in r.get("items") or []:
            if isinstance(it, dict) and it.get("product_name"):
                items.append(it)
        for w in r.get("winners") or []:
            if not isinstance(w, dict) or not w.get("name"):
                continue
            key = f"{w.get('name')}|{w.get('package')}"
            if key not in seen_w:
                seen_w.add(key)
                winners.append(w)
        for b in r.get("bidders") or []:
            if isinstance(b, str) and b and b not in seen_b:
                seen_b.add(b)
                bidders.append(b)
    merged["items"] = items
    merged["winners"] = winners
    merged["bidders"] = bidders
    return merged


def llm_extract_json(html_text: str, attachment_text: str | None = None) -> dict[str, Any]:
    """调用大模型, 长文本自动分块抽取后合并。失败抛出异常。"""
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置, 无法使用大模型引擎")
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    body_template = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    html_chunks = _chunk_text(html_text or "")
    att_chunks = _chunk_text(attachment_text or "", max_chunks=2)
    n = len(html_chunks) + len(att_chunks)

    if n <= 1:
        body = dict(body_template)
        body["messages"] = body["messages"] + [{
            "role": "user",
            "content": _build_user_prompt(html_chunks[0] if html_chunks else "",
                                          att_chunks[0] if att_chunks else None)}]
        payload = {"_url": url, "_body": body, "_headers": headers}
        return _call_model(payload)

    # 分块模式: html 块优先, 附件块依次并入
    results: list[dict[str, Any]] = []
    n = len(html_chunks) + len(att_chunks)
    for i, chunk in enumerate(html_chunks):
        body = dict(body_template)
        body["messages"] = body["messages"] + [{
            "role": "user", "content": _build_user_prompt(chunk, None, i + 1, n)}]
        results.append(_call_model({"_url": url, "_body": body, "_headers": headers}))
    for i, chunk in enumerate(att_chunks, start=len(html_chunks)):
        body = dict(body_template)
        body["messages"] = body["messages"] + [{
            "role": "user", "content": _build_user_prompt("", chunk, i + 1, n)}]
        results.append(_call_model({"_url": url, "_body": body, "_headers": headers}))
    return _merge_results(results)


def record_from_llm(data: dict[str, Any], *, html_file: str = "", attachment_file: str = "") -> AnnouncementRecord:
    """把大模型输出转换为 AnnouncementRecord。"""
    rec = AnnouncementRecord(html_file=html_file, attachment_file=attachment_file)
    rec.title = clean_text(str(data.get("project_name") or ""))
    rec.project_name = rec.title
    rec.project_code = clean_text(str(data.get("project_code") or ""))
    rec.procurement_unit = normalize_org_name(str(data.get("procurement_unit") or ""))
    rec.publish_date = clean_text(str(data.get("publish_date") or ""))
    rec.agency_name = clean_text(str(data.get("agency_name") or ""))
    try:
        rec.total_amount_wan = float(data["total_amount_wan"]) if data.get("total_amount_wan") is not None else None
    except (TypeError, ValueError):
        rec.total_amount_wan = None

    for w in data.get("winners") or []:
        if not isinstance(w, dict):
            continue
        name = normalize_org_name(str(w.get("name") or ""))
        if not name:
            continue
        try:
            amt = float(w["amount_wan"]) if w.get("amount_wan") is not None else None
        except (TypeError, ValueError):
            amt = None
        rec.winners.append(WinnerRecord(org_norm=name, org_raw=name,
                                        amount_wan=amt, package=clean_text(str(w.get("package") or ""))))

    for b in data.get("bidders") or []:
        name = normalize_org_name(str(b))
        if name and name not in rec.bidders:
            rec.bidders.append(name)

    for i, it in enumerate(data.get("items") or []):
        if not isinstance(it, dict):
            continue
        item = ItemRecord(source="html", seq=i + 1)
        item.product_name = clean_text(str(it.get("product_name") or ""))
        if not item.product_name:
            continue
        item.category = clean_text(str(it.get("category") or ""))
        item.brand = clean_text(str(it.get("brand") or ""))
        item.spec_model = clean_text(str(it.get("spec_model") or ""))
        try:
            item.unit_price = float(it["unit_price"]) if it.get("unit_price") is not None else None
        except (TypeError, ValueError):
            item.unit_price = None
        try:
            item.quantity = float(it["quantity"]) if it.get("quantity") is not None else None
        except (TypeError, ValueError):
            item.quantity = None
        item.quantity_text = clean_text(str(it.get("quantity_text") or ""))
        if item.quantity_text:
            _, unit = parse_quantity(item.quantity_text)
            item.quantity_unit = unit
        try:
            item.total_price = float(it["total_price"]) if it.get("total_price") is not None else None
        except (TypeError, ValueError):
            item.total_price = None
        sup = normalize_org_name(str(it.get("supplier") or ""))
        if sup:
            item.supplier_norm = sup
        rec.items.append(item)
    return rec
