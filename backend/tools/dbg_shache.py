# -*- coding: utf-8 -*-
"""检查 t20260206_26158480 的表格2 键值解析。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")
from app.extraction.html_parser import AnnouncementHtmlParser, AnnouncementRecord
from app.extraction.utils import clean_text
from bs4 import BeautifulSoup
from pathlib import Path

p = AnnouncementHtmlParser()
base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
soup = BeautifulSoup((base / "t20260206_26158480.html").read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup
tb = content.find_all("table")[2]
print("looks_kvcell:", p._looks_kvcell(tb))
for r in tb.find_all("tr")[:6]:
    cells = [clean_text(c.get_text(" "))[:26] for c in r.find_all(["td", "th"])]
    print("  R:", " || ".join(cells))
print("=== direct kvcell parse ===")
rec = AnnouncementRecord()
p._parse_kvcell_table(tb, rec, source="html")
for it in rec.items[:6]:
    print("  ITEM:", it.product_name, "| brand:", it.brand, "| spec:", it.spec_model[:14], "| qty:", it.quantity, it.quantity_unit, "| up:", it.unit_price)
print("count:", len(rec.items))
