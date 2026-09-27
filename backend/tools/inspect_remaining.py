# -*- coding: utf-8 -*-
"""检查剩余无中标供应商/无标的物公告的失败原因。"""
from __future__ import annotations

import re
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")

for name in ["t20260203_26142958.html", "t20260212_26176961.html", "t20260310_26250892.html"]:
    print("#" * 100)
    print("FILE:", name)
    soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    print("--- paragraphs with 中标/成交/供应商 ---")
    for p in content.find_all("p"):
        t = p.get_text(" ", strip=True)
        if t and any(k in t for k in ("中标", "成交", "供应商", "名称")):
            print("   P:", t[:120])
    tables = content.find_all("table")
    print("tables:", len(tables))
    for i, tb in enumerate(tables[:3]):
        flat = " "
        rows = tb.find_all("tr")
        for tr in rows[:6]:
            flat += " | ".join(c.get_text(" ", strip=True)[:20] for c in tr.find_all(["td", "th"])) + " "
        print(f"  [table {i}] rows={len(rows)}: {flat[:260]}")
