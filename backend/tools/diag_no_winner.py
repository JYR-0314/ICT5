# -*- coding: utf-8 -*-
"""批量诊断 no_winner 文件: 打印每文件的中标线索。"""
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

names = [n.name for n in sorted(base.glob("*.html"))]
recs = []
for f in sorted(base.glob("*.html")):
    try:
        r = p.parse_file(str(f))
    except Exception:
        r = None
    recs.append((f.name, r))

nw = [n for n, r in recs if r is not None and len(r.winners) == 0]
print("no_winner:", len(nw))
for fname in nw:
    soup = BeautifulSoup((base / fname).read_text(encoding="utf-8", errors="replace"), "lxml")
    content = soup.select_one("div.vF_detail_content") or soup
    paras = [clean_text(x.get_text(" ")) for x in content.find_all(["p", "h4", "h5"])]
    has_sec = any(("中标" in t and "信息" in t and "标的" not in t) for t in paras)
    sup_paras = [t[:46] for t in paras if "供应商" in t and "名称" in t]
    hdr = soup.find("h1") or soup.find("title")
    title = clean_text(hdr.get_text(" "))[:44] if hdr else ""
    tbl_sup = 0
    tbl_amt = 0
    for tb in content.find_all("table"):
        flat = "".join(clean_text(c.get_text(" ")) for r_ in tb.find_all("tr")[:4] for c in r_.find_all(["td", "th"]))
        if "供应商" in flat:
            tbl_sup = 1
        if "金额" in flat or "中标价" in flat:
            tbl_amt = 1
    print(f"\n== {fname} | {title}")
    print(f"   section={has_sec} tbl_sup={tbl_sup} tbl_amt={tbl_amt} suplines:")
    for s in sup_paras[:3]:
        print("     ", s)
