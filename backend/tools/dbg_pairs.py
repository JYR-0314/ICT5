# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")
from app.extraction.html_parser import AnnouncementHtmlParser, AnnouncementRecord
from app.extraction.utils import clean_text
from bs4 import BeautifulSoup
from pathlib import Path

p = AnnouncementHtmlParser()
base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
soup = BeautifulSoup((base / "t20260212_26176961.html").read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup
tb = content.find_all("table")[0]

kv_labels = (r"标段名称|标包名称|货物名称|商品名称|货物品牌|品牌|货物规格型号|规格型号|型号|"
             r"货物数量|数量|货物单价|单价|货物总价|总价|品目|货物类别|类别|服务范围|服务要求|"
             r"服务时间|服务标准|服务期限|施工范围|技术要求|名称")
kv_iter_re = re.compile(
    r"((?:" + kv_labels + r"))\s*[:：]\s*([^：:]{0,120}?)"
    r"(?=\s*(?:" + kv_labels + r")\s*[:：]|$)")
for tr in tb.find_all("tr"):
    full = " ".join(clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"]))
    full = re.sub(r"\s+", "", full)
    pairs = {}
    for m in kv_iter_re.finditer(full):
        v = m.group(2).strip(" ，,、；;").strip()
        if v:
            pairs.setdefault(m.group(1), v)
    print(repr(full[:36]), "=>", {k: (pairs[k][:12] if len(pairs[k]) > 12 else pairs[k]) for k in pairs})
