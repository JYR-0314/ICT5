# -*- coding: utf-8 -*-
"""深度追踪单个文件: 段落级 + 表头行。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")
from app.extraction.html_parser import AnnouncementHtmlParser, AnnouncementRecord, _WINNER_SEC_RE, _ITEMS_SEC_RE
from app.extraction.utils import clean_text
from bs4 import BeautifulSoup
from pathlib import Path

p = AnnouncementHtmlParser()
base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
name = sys.argv[1] if len(sys.argv) > 1 else "t20260410_26384854.html"
soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup

print("### sections / winner-ish paragraphs")
for tag in content.find_all(["p", "h4", "h5"]):
    t = clean_text(tag.get_text(" "))
    if "中标" in t or "成交" in t or "供应商" in t or "金额" in t:
        print(f"  [{tag.name}] {t[:70]}")
print("### tables")
for i, tb in enumerate(content.find_all("table")):
    print(f"  table {i}: kvcell={p._looks_kvcell(tb)}")
    for r in tb.find_all("tr")[:5]:
        cells = [clean_text(c.get_text(" "))[:16] for c in r.find_all(["td", "th"])]
        print("     R:", " || ".join(cells))
