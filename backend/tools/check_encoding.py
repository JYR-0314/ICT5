# -*- coding: utf-8 -*-
"""检查数据集 HTML 编码分布。"""
from __future__ import annotations

import re
import sys
import io
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

base = Path(r"E:\code\dsh-work\benchmark\html\赛题五.基准测试数据_html")
encs = Counter()
gbk_candidates = []
for f in sorted(base.glob("*.html")):
    raw = f.read_bytes()[:2048]
    m = re.search(rb"charset\s*=\s*[\"\x27]?([\w-]+)", raw, re.I)
    if m:
        encs[m.group(1).decode().lower()] += 1
    else:
        try:
            (f.read_bytes()).decode("utf-8")
            encs["utf8(no-meta)"] += 1
        except UnicodeDecodeError:
            gbk_candidates.append(f.name)
            encs["gbk(no-meta)"] += 1

print("charsets:", dict(encs))
print("gbk candidates count:", len(gbk_candidates))
for n in gbk_candidates[:15]:
    print("  GBK:", n)
