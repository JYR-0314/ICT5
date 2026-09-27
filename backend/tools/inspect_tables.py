# -*- coding: utf-8 -*-
"""查看指定公告的表格/段落结构。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

HTML_DIR = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")

for name in ["t20260304_26217046.html", "t20260301_26206506.html", "t20260707_26890217.html"]:
    print("#" * 100)
    print("FILE:", name)
    soup = BeautifulSoup((HTML_DIR / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    # 概要表
    st = soup.select_one("div.table table")
    if st:
        print("--- summary ---")
        for tr in st.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells:
                print(" | ".join(cells)[:200])
    # 正文段落(含 供应商/中标/成交 关键词)
    content = soup.select_one("div.vF_detail_content")
    if content:
        print("--- paragraphs w/ keywords ---")
        for p in content.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t and any(k in t for k in ("供应商", "中标", "成交", "项目编号", "金额")):
                print("  P:", t[:160])
        print("--- tables (first 6) ---")
        for i, tb in enumerate(content.find_all("table")[:6]):
            rows = tb.find_all("tr")[:5]
            print(f"  [table {i}] {len(tb.find_all('tr'))} rows")
            for tr in rows:
                cells = [c.get_text(" ", strip=True)[:30] for c in tr.find_all(["td", "th"])]
                if any(cells):
                    print("     ", " | ".join(cells))
