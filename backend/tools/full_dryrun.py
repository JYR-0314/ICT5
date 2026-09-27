# -*- coding: utf-8 -*-
"""全量(1038 条 HTML, 不含附件)解析压测: 统计成功率/7 字段提取率/耗时/失败样本。"""
from __future__ import annotations

import sys
import io
import time
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")

from app.extraction.html_parser import AnnouncementHtmlParser  # noqa: E402

HTML_DIR = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
parser = AnnouncementHtmlParser()
htmls = sorted(HTML_DIR.glob("*.html"))

t0 = time.time()
fails: list[tuple[str, str]] = []
no_winner: list[str] = []
no_items: list[str] = []
item_total = 0
winner_total = 0
bidder_total = 0
field_fill: Counter = Counter()
types = Counter()
times: list[int] = []
sample_items = 0

for h in htmls:
    try:
        rec = parser.parse_file(str(h))
    except Exception as e:  # noqa: BLE001
        fails.append((h.name, f"{type(e).__name__}: {e}"))
        continue
    types[rec.announce_type or "?"] += 1
    times.append(rec.parse_ms)
    n = len(rec.items)
    item_total += n
    sample_items += n
    winner_total += len(rec.winners)
    bidder_total += len(rec.bidders)
    if not rec.winners:
        no_winner.append(h.name)
    if not rec.items:
        no_items.append(h.name)
    for it in rec.items:
        for f in ("product_name", "category", "brand", "spec_model",
                  "unit_price", "quantity", "total_price"):
            v = getattr(it, f)
            if v not in (None, ""):
                field_fill[f] += 1

dt = time.time() - t0
print(f"total: {len(htmls)}, ok: {len(htmls) - len(fails)}, fail: {len(fails)}, "
      f"no_winner: {len(no_winner)}, no_items: {len(no_items)}")
print(f"time: {dt:.1f}s for {len(htmls)} docs, avg {dt / len(htmls) * 1000:.0f}ms/doc")
print(f"announce types: {dict(types)}")
print(f"items total: {item_total}, winners total: {winner_total}, bidders total: {bidder_total}")
print("field fill rates (of %d items):" % sample_items)
for f in ("product_name", "category", "brand", "spec_model", "unit_price", "quantity", "total_price"):
    print(f"  {f}: {field_fill[f]} ({field_fill[f] / sample_items * 100:.1f}%)")
print("\n--- fails ---")
for name, err in fails[:20]:
    print(" ", name, err)
print("\n--- no winners (first 15) ---")
for n in no_winner[:15]:
    print(" ", n)
print("\n--- no items (first 15) ---")
for n in no_items[:15]:
    print(" ", n)
