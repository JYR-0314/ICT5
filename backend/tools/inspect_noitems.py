# -*- coding: utf-8 -*-
"""查看无标的物公告的内容结构。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")

for name in ["t20260507_26519724.html", "t20260410_26386256.html", "t20260805_27080645.html"]:
    print("#" * 100)
    print("FILE:", name)
    soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    tables = content.find_all("table")
    print("tables:", len(tables))
    for i, tb in enumerate(tables[:4]):
        rows = tb.find_all("tr")
        print(f"  [table {i}] {len(rows)} rows")
        for tr in rows[:4]:
            cells = [c.get_text(" ", strip=True)[:40] for c in tr.find_all(["td", "th"])]
            if any(cells):
                print("     ", " | ".join(cells))
    print("--- paragraphs ---")
    for p in content.find_all("p")[:40]:
        t = p.get_text(" ", strip=True)
        if t:
            print("   P:", t[:110])
