# -*- coding: utf-8 -*-
"""追踪表格分支决策。"""
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

for name in ["t20260707_26890522.html", "t20260508_26523442.html"]:
    soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    print("=" * 90, name)
    for i, tb in enumerate(content.find_all("table")):
        hit = any(p._KVCELL_RE.search(clean_text(c.get_text(" ")))
                  for tr in tb.find_all("tr")[:3] for c in tr.find_all("td"))
        hdr = p._find_header_row(tb)
        print(f"table {i}: kvcell_hit={hit} header={'Y' if hdr is not None else 'N'}")
        if hdr is not None:
            cells = [clean_text(c.get_text(" "))[:20] for c in hdr.find_all(["td", "th"])]
            print("   header:", " | ".join(cells))
        # 第一行完整文本
        tr0 = tb.find_all("tr")[0]
        print("   row0:", " || ".join(clean_text(c.get_text(" "))[:60] for c in tr0.find_all(["td", "th"])))
