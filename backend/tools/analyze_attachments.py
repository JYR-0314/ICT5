# -*- coding: utf-8 -*-
"""统计附件 zip 内部文件格式分布与体积。"""
from __future__ import annotations

import io
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FILE_DIR = Path(r"E:\code\dsh-work\benchmark\file\赛题五.基准测试数据_file")
zips = sorted(FILE_DIR.glob("*.zip"))
print("attachment zips:", len(zips))

ext_count: Counter = Counter()
multi_file = 0
empty = 0
bad = 0
size_total = 0
by_ext_size: Counter = Counter()
examples: dict[str, str] = {}

for zf in zips:
    try:
        with zipfile.ZipFile(zf) as z:
            entries = [i for i in z.infolist() if not i.is_dir()]
            inner_exts = []
            for i in entries:
                ext = Path(i.filename).suffix.lower()
                ext_count[ext or "(none)"] += 1
                by_ext_size[ext or "(none)"] += i.file_size
                inner_exts.append(ext)
                if ext not in examples:
                    examples[ext or "(none)"] = zf.name
            size_total += sum(i.file_size for i in entries)
            if len(entries) == 0:
                empty += 1
            elif len(entries) > 1:
                multi_file += 1
    except Exception as e:  # noqa: BLE001
        bad += 1
        print("BAD:", zf.name, e)

print("inner file ext counts:", dict(ext_count.most_common(20)))
print("total inner size: %.1f MB" % (size_total / 1e6))
print("multi-file zips:", multi_file, "| empty zips:", empty, "| bad zips:", bad)
print("per-ext size (MB):", {k: round(v / 1e6, 1) for k, v in by_ext_size.most_common(12)})
print("examples:", examples)
