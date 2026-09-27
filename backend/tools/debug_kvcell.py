# -*- coding: utf-8 -*-
"""调试 t20260212 的 kvcell 解析。"""
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
soup = BeautifulSoup((base / "t20260212_26176961.html").read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup
tables = content.find_all("table")
print("tables:", len(tables))
for i, tb in enumerate(tables):
    print(f"--- table {i} ---")
    print("looks_kvcell:", p._looks_kvcell(tb))
    rows = tb.find_all("tr")
    print("rows:", len(rows))
    for r in rows[0:3]:
        cells = [clean_text(c.get_text(" "))[:50] for c in r.find_all(["td", "th"])]
        print("   cells:", " || ".join(cells))
rec = AnnouncementRecord()
p._parse_kvcell_table(tables[0], rec, source="html")
print("kvcell items:", len(rec.items))
for it in rec.items[:5]:
    print("   ", it.product_name, "|", it.brand, "|", it.spec_model, "|", it.quantity, it.quantity_unit, "|", it.unit_price, "|", it.total_price)
