# -*- coding: utf-8 -*-
"""抽查 no_items 文件: 是真实无标的 or 漏解析。"""
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
names = sys.argv[1:] or ["t20260301_26206506.html", "t20260408_26370560.html",
                         "t20260410_26386311.html", "t20260206_26158480.html",
                         "t20260304_26217439.html", "t20260508_26523656.html"]
for name in names:
    soup = BeautifulSoup((base / name).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    print("=====", name)
    for i, tb in enumerate(content.find_all("table")):
        if p._looks_kvcell(tb):
            label = "kvcell"
        else:
            label = "std"
        rows = tb.find_all("tr")
        sample = " || ".join(clean_text(c.get_text(" "))[:14] for c in rows[0].find_all(["td", "th"]))[:70] if rows else ""
        print(f"   table{i}[{label} rows={len(rows)}]: {sample}")
    paras = [clean_text(x.get_text(" ")) for x in content.find_all(["p", "h4", "h5"])]
    kv = [t[:40] for t in paras if t and any(k in t for k in ("品牌", "规格型号", "数量", "单价", "货物名称", "名称："))][:5]
    for s in kv:
        print("   P:", s)
