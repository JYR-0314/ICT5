# -*- coding: utf-8 -*-
"""逐步检查 winner-table 守卫条件。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")
from app.extraction.html_parser import AnnouncementHtmlParser
from app.extraction.utils import clean_text
from bs4 import BeautifulSoup
from pathlib import Path

p = AnnouncementHtmlParser()
base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
soup = BeautifulSoup((base / "t20260202_26140620.html").read_text(encoding="utf-8", errors="replace"), "lxml")
content = soup.select_one("div.vF_detail_content") or soup
tables = content.find_all("table")
tb = tables[1]
head = p._find_header_row(tb)
print("header found:", head is not None)
if head is not None:
    cells = [clean_text(c.get_text(" ")) for c in head.find_all(["td", "th"])]
    flat = "".join(cells)
    print("cells:", cells)
    print("flat:", flat[:80])
    print("has_sup:", any(("供应商" in c or "中标人" in c or "成交人" in c) for c in cells))
    print("has_amt:", any(("金额" in c or "中标价" in c or "成交价" in c) for c in cells))
    print("bidder-guard:", ("未中标原因" in flat or "未成交原因" in flat) and ("金额" not in flat or flat.count("金额") <= 1))
    print("kvcell guard:", p._looks_kvcell(tb))
    print("货物品牌 guard:", "货物名称" in flat and "品牌" in flat)
    # 数据行
    for tr in tb.find_all("tr")[1:3]:
        vals = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
        print("data row:", [v[:18] for v in vals])
