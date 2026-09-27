# -*- coding: utf-8 -*-
"""抽样分析公告 HTML 解析情况, 定位规则引擎的缺口。"""
from __future__ import annotations

import random
import sys
import io
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")

from app.extraction.html_parser import AnnouncementHtmlParser  # noqa: E402

HTML_DIR = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
parser = AnnouncementHtmlParser()
htmls = sorted(HTML_DIR.glob("*.html"))
print(f"total htmls: {len(htmls)}")

random.seed(42)
sample = random.sample(htmls, min(80, len(htmls)))

stats = Counter()
field_fill = Counter()
detail_rows = []
for h in sample:
    try:
        rec = parser.parse_file(str(h))
    except Exception as e:  # noqa: BLE001
        stats["EXCEPTION"] += 1
        detail_rows.append((h.name, "EXC", str(e)[:80], 0, 0, 0, 0))
        continue
    if not rec.items and not rec.winners and not rec.procurement_unit:
        stats["EMPTY"] += 1
    elif not rec.items:
        stats["NO_ITEMS"] += 1
    elif not rec.winners:
        stats["NO_WINNERS"] += 1
    else:
        stats["OK"] += 1
    # 7 字段填充
    for it in rec.items:
        for f in ("product_name", "category", "brand", "spec_model",
                  "unit_price", "quantity", "total_price"):
            v = getattr(it, f)
            if v not in (None, ""):
                field_fill[f] += 1
    detail_rows.append((h.name, rec.announce_type, rec.title[:14], len(rec.items),
                        len(rec.winners), len(rec.bidders),
                        rec.total_amount_wan if rec.total_amount_wan is not None else -1))

print("summary:", dict(stats))
print("field fill (of {} items):".format(sum(field_fill.values()) // 7 if field_fill else 0))
for f in ("product_name", "category", "brand", "spec_model", "unit_price", "quantity", "total_price"):
    print(f"  {f}: {field_fill[f]}")

print("\n--- sample rows (name | type | title | items | winners | bidders | total_wan) ---")
for r in detail_rows:
    print(" | ".join(str(x) for x in r))
