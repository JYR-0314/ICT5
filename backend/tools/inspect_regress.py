# -*- coding: utf-8 -*-
"""检查回归文件的表格结构。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")

for name in ["t20260707_26890522.html", "t20260508_26523442.html", "t20260608_26706279.html", "t20260812_27123683.html"]:
    print("#" * 100)
    print("FILE:", name)
    soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    tables = content.find_all("table")
    print("tables:", len(tables))
    for i, tb in enumerate(tables[:4]):
        rows = tb.find_all("tr")
        print(f"  [table {i}] rows={len(rows)}")
        for tr in rows[:5]:
            cells = [c.get_text(" ", strip=True)[:45] for c in tr.find_all(["td", "th"])]
            print("     ", " || ".join(cells))
    print("--- paragraphs ---")
    for p in content.find_all("p")[:14]:
        t = p.get_text(" ", strip=True)
        if t:
            print("   P:", t[:100])
