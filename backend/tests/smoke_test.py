# -*- coding: utf-8 -*-
"""端到端冒烟测试(官方样例数据集)。

运行:  python tests/smoke_test.py
使用 FastAPI TestClient 在内存内完成: 建库 → 导入样例 → 全接口校验。
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# 使用独立临时数据库, 不污染正式库
import os
tmp = tempfile.mkdtemp(prefix="dsh_test_")
os.environ["DSH_DATA_DIR"] = tmp

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

FAIL = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name} {extra}")
    if not cond:
        FAIL.append(name)


def make_dataset_zip() -> Path:
    """用官方样例(html+zip 附件)构造一个数据集压缩包。"""
    root = BACKEND.parent / "sample_dataset"
    html = next(root.glob("*.html"))
    attach = next(root.glob("*.zip"))
    out = Path(tmp) / "dataset.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(html, html.name)
        zf.write(attach, attach.name)
    return out


def main() -> int:
    # ---- 任务三: 上传数据集 → 自动解析入库 ----
    ds = make_dataset_zip()
    r = client.post("/api/v1/datasets/upload?engine=rule",
                    files={"file": ("dataset.zip", ds.read_bytes(),
                                    "application/zip")})
    check("上传触发后台任务", r.status_code == 200 and r.json()["data"]["task_id"] > 0)
    task_id = r.json()["data"]["task_id"]

    import time
    for _ in range(60):
        t = client.get(f"/api/v1/datasets/tasks/{task_id}").json()
        if t["status"] in ("done", "failed"):
            break
        time.sleep(1)
    check("导入任务完成", t["status"] == "done", f"-> {t['status']}")
    check("导入成功数 = 1", t["ok"] == 1, f"-> ok={t['ok']} failed={t['failed']}")

    # ---- 任务一: 标的物 7 字段 ----
    items = client.get("/api/v1/items?page_size=50").json()["items"]
    check("标的物 = 3 条", len(items) == 3, f"-> {len(items)}")
    by_name = {i["product_name"]: i for i in items}
    frame = by_name.get("光跳纤架")
    check("7 字段齐全(示例行)", frame and all(frame.get(k) not in (None, "", False) for k in
          ("product_name", "category", "brand", "spec_model", "unit_price", "quantity", "total_price")),
          f"-> { {k: frame.get(k) for k in ('brand','spec_model','quantity','unit_price','total_price')} if frame else None }")
    check("单价 = 319300 元", frame and frame["unit_price"] == 319300.0)
    check("数量 = 4 套", frame and frame["quantity"] == 4.0 and frame["unit"] == "套")

    # ---- 任务一: 公告级字段 ----
    anns = client.get("/api/v1/announcements").json()["items"]
    check("公告 = 1 条", len(anns) == 1)
    a = client.get(f"/api/v1/announcements/{anns[0]['id']}").json()
    check("采购单位抽取", a["procurement_org"]["norm_name"] == "中央广播电视总台")
    check("总金额 = 325.031 万", a["total_amount"] == 325.031)
    winners = {p["organization"]["norm_name"] for p in a["participations"] if p["role"] == "winner"}
    check("中标供应商 = 2 家", winners == {"北京万迪科信息技术有限公司", "北京智为视媒科技有限公司"})

    # ---- 任务二: 5 大业务场景 ----
    pu = "中央广播电视总台"
    s1 = client.get("/api/v1/scenarios/1", params={"procurement_unit": pu}).json()["data"]
    check("场景1 合作供应商数 = 2", len(s1["cooperated_winners"]) == 2)
    check("场景1 合作总额 = 325.03 万", abs(s1["total_amount_wan"] - 325.03) < 0.01)
    check("场景1 产品供应商含康普/创维",
          {s["brand"] for s in s1["product_suppliers"]} == {"康普", "创维"})

    s2 = client.get("/api/v1/scenarios/2", params={"procurement_unit": pu}).json()["data"]
    check("场景2 返回结构", "top_bidders" in s2 and "top_co_bid_combos" in s2)

    w1 = "北京万迪科信息技术有限公司"
    w2 = "北京智为视媒科技有限公司"
    s3 = client.get("/api/v1/scenarios/3", params={"supplier": w1}).json()["data"]
    check("场景3 共同竞标主体 = 1", len(s3["top_co_bidders"]) == 1 and
          s3["top_co_bidders"][0]["organization"]["name"] == w2)

    s4 = client.get("/api/v1/scenarios/4", params={"suppliers": f"{w1},{w2}"}).json()["data"]
    check("场景4 共同采购单位 = 中央广播电视总台", len(s4["common_units"]) == 1 and
          s4["common_units"][0]["organization"]["name"] == pu)
    check("场景4 各供应商金额精确",
          s4["common_units"][0]["with_suppliers"][w1]["total_amount_wan"] == 243.13 and
          s4["common_units"][0]["with_suppliers"][w2]["total_amount_wan"] == 81.9)

    s5 = client.get("/api/v1/scenarios/5", params={"suppliers": f"{w1},{w2}"}).json()["data"]
    check("场景5 共同项目 = 1 个/总额 325.03 万", s5["project_count"] == 1 and
          abs(s5["total_amount_wan"] - 325.03) < 0.01)

    # ---- 统计 / 图谱 ----
    ov = client.get("/api/v1/stats/overview").json()["data"]
    check("统计: 覆盖率 = 1.0", ov["extract_coverage"] == 1.0)
    g = client.get("/api/v1/stats/graph").json()["data"]
    check("图谱节点 >= 6", len(g["nodes"]) >= 6 and len(g["edges"]) >= 4)

    print("-" * 60)
    if FAIL:
        print(f"结果: {len(FAIL)} 项失败 -> {FAIL}")
        return 1
    print("结果: 全部通过 (ALL PASSED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
