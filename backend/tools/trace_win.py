# -*- coding: utf-8 -*-
"""按文件追踪表格与中标供应商抽取过程。"""
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

name = sys.argv[1] if len(sys.argv) > 1 else "t20260202_26140620.html"
soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup
tables = content.find_all("table")
print("tables:", len(tables))
for i, tb in enumerate(tables):
    print(f"table {i}: looks_kvcell={p._looks_kvcell(tb)}")
    for r in tb.find_all("tr")[:5]:
        cells = [clean_text(c.get_text(" "))[:22] for c in r.find_all(["td", "th"])]
        print("   R:", " || ".join(cells))
rec = AnnouncementRecord()
p._parse_winners(content, rec)
print("after _parse_winners:", [(w.org_norm[:18], w.amount_wan, repr(w.package)) for w in rec.winners])
p._parse_winner_tables(content, rec)
print("after _parse_winner_tables:", [(w.org_norm[:18], w.amount_wan, repr(w.package)) for w in rec.winners])
