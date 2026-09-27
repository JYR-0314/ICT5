# -*- coding: utf-8 -*-
"""Inspect the sample announcement HTML structure."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup

with open(r"E:\code\dsh-work\input\sample.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "lxml")

print("TITLE:", soup.title.get_text(strip=True) if soup.title else None)
print("=" * 80)

# Announcement summary table (公告概要)
for table in soup.select("div.table table"):
    print("---- summary table ----")
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        print(" | ".join(cells))

print("=" * 80)
# Main content tables (主要标的信息)
for i, table in enumerate(soup.select("div.vF_detail_content table")):
    print(f"---- content table {i} ----")
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        print(" | ".join(cells))

print("=" * 80)
# Main content paragraphs
content = soup.select_one("div.vF_detail_content")
if content:
    for p in content.find_all("p", recursive=False):
        t = p.get_text(" ", strip=True)
        if t:
            print("P:", t[:300])
