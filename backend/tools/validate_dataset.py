# -*- coding: utf-8 -*-
"""全量入库后验证: 统计概况 + 5 大业务场景在真实数据上的结果。"""
from __future__ import annotations

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\code\dsh-work\backend")

import time
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def main() -> int:
    payload = client.get("/api/v1/stats/overview").json()
    ov = payload.get("data", payload)
    print("== 统计概览 ==")
    for k, v in ov.items():
        print(f"  {k}: {v}")

    # 场景1/2: 采购单位(取公告最多的单位)
    units = sorted(ov.get("top_procurement_units") or [],
                   key=lambda u: u.get("count", 0), reverse=True)
    unit = (units[0] if units else {}).get("name", "")
    print("\n== 场景验证(采购单位: %s) ==" % unit or "(无)")
    if unit:
        s1 = client.get("/api/v1/scenarios/1", params={"procurement_unit": unit}).json()["data"]
        wins, sups = s1.get("cooperated_winners", []), s1.get("product_suppliers", [])
        print("场景1: 合作中标供应商 =", len(wins), "| 产品供应商 =", len(sups),
              "| 项目数 =", s1.get("project_count"), "| 总额 =", s1.get("total_amount_wan"))
        for w in wins[:3]:
            print("   -", (w.get("organization") or {}).get("name", "")[:22], "x",
                  w.get("cooperate_count"), "次, 金额", w.get("total_amount_wan"))
        for p in sups[:3]:
            print("   * 产品供应商:", p.get("brand", "")[:16], "x", p.get("cooperate_count"))

        s2 = client.get("/api/v1/scenarios/2", params={"procurement_unit": unit}).json()["data"]
        print("场景2: TOP5 高频投标 =", len(s2.get("top_bidders", [])),
              "| 协同组合 =", len(s2.get("top_co_bid_combos", [])))
        for b in (s2.get("top_bidders") or [])[:3]:
            print("   -", (b.get("organization") or {}).get("name", "")[:16], "x", b.get("bid_count"))
        for c in (s2.get("top_co_bid_combos") or [])[:3]:
            print("   o", (c.get("organization_a") or {}).get("name", "")[:14], "+",
                  (c.get("organization_b") or {}).get("name", "")[:14], "x", c.get("co_bid_count"))

    # 场景3: 中标供应商(取中标次数最多的主体)
    top_winners = ov.get("top_winners") or []
    sup = (top_winners[0] if top_winners else {}).get("name", "")
    print("\n== 场景3(中标供应商: %s) ==" % sup or "(无)")
    if sup:
        s3 = client.get("/api/v1/scenarios/3", params={"supplier": sup}).json()["data"]
        print("场景3: TOP5 共同竞标 =", len(s3.get("top_co_bidders", [])),
              "| 全部参与主体 =", len(s3.get("all_participants", [])),
              "| 项目数 =", s3.get("project_count"))
        for cb in (s3.get("top_co_bidders") or [])[:3]:
            print("   -", (cb.get("organization") or {}).get("name", "")[:20], "x",
                  cb.get("count"), "次, 金额", cb.get("total_amount_wan"))

    # 场景4/5: 两个中标供应商
    if len(top_winners) >= 2:
        a, b = top_winners[0]["name"], top_winners[1]["name"]
        print("\n== 场景4/5(中标供应商: %s / %s) ==" % (a[:14], b[:14]))
        s4 = client.get("/api/v1/scenarios/4", params={"suppliers": f"{a},{b}"}).json()["data"]
        print("场景4: 共同合作采购单位 =", len(s4.get("common_units", [])))
        for u in (s4.get("common_units") or [])[:3]:
            print("   -", (u.get("organization") or {}).get("name", "")[:22], "x",
                  u.get("total_cooperate_count"), "次, 金额", u.get("total_amount_wan"))
        s5 = client.get("/api/v1/scenarios/5", params={"suppliers": f"{a},{b}"}).json()["data"]
        print("场景5: 共同竞标项目 =", s5.get("project_count"), "| 总额 =",
              s5.get("total_amount_wan"), "万")
        for pr in (s5.get("projects") or [])[:3]:
            print("   -", (pr.get("title") or "")[:24], "| 角色:",
                  {k[:6]: (v.get("role") or "?")[:4] for k, v in (pr.get("roles") or {}).items()})

    # 检索性能抽查
    t0 = time.perf_counter()
    items = client.get("/api/v1/items", params={"q": "服务", "page_size": 20}).json()
    dt = (time.perf_counter() - t0) * 1000
    n = sum(len(x) for x in (items.get("items") or [])) if isinstance(items.get("items"), list) else 0
    print("\n== 检索抽查: /api/v1/items?q=服务 ==")
    print(f"  返回 {len(items.get('items') or [])} 条, 响应 {dt:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
