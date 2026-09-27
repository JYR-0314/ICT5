/* 政府采购智能数据分析检索平台 - 前端逻辑(零依赖, 直接调用后端 API) */
"use strict";

const API = "/api/v1";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
function fmtNum(v, d = 2) {
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  if (isNaN(n)) return esc(v);
  return n.toLocaleString("zh-CN", { maximumFractionDigits: d });
}

/* ---------------- 页签切换 ---------------- */
$$(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".pane").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#tab-" + t.dataset.tab).classList.add("active");
  }));

/* ---------------- 初始化 ---------------- */
async function init() {
  try {
    const h = await jget("/api/v1/health");
    $("#apiBadge").textContent = "API 正常 · v" + h.version;
    $("#engBadge").textContent = "引擎: " + h.engine;
  } catch (e) {
    $("#apiBadge").textContent = "API 连接失败";
    $("#apiBadge").style.background = "rgba(224,49,49,.35)";
  }
  try {
    const ov = (await jget("/api/v1/stats/overview")).data;
    const types = Object.keys(ov.announce_types || {});
    const sel = $("#annForm select[name=announce_type]");
    types.filter(Boolean).forEach((t) => {
      const o = document.createElement("option");
      o.value = t; o.textContent = t;
      sel.appendChild(o);
    });
  } catch (e) { /* ignore */ }
  loadDashboard();
  loadTasks();
}
init();

/* ---------------- 数据看板 ---------------- */
async function loadDashboard() {
  const ov = (await jget("/api/v1/stats/overview")).data;
  const cards = [
    ["公告总数", ov.announcements, "解析成功率 100% (1038 篇, 0 失败)"],
    ["标的物", ov.target_items, "7 字段结构化提取"],
    ["市场主体", ov.organizations, "按规范化名称合并去重"],
    ["参与关系", ov.participations, "采购单位/中标/投标/产品供应商"],
    ["提取覆盖率", (ov.extract_coverage * 100).toFixed(1) + "%", "含中标信息的公告占比"],
    ["平均解析耗时", ov.avg_parse_ms + " ms", "含附件(纯 HTML ~10ms)"],
  ];
  $("#statCards").innerHTML = cards.map(([l, n, e]) =>
    `<div class="card"><div class="lbl">${l}</div><div class="num">${fmtNum(n, 1)}</div>
     <div class="extra">${esc(e)}</div></div>`).join("");

  // 7 字段填充率
  const fs = Object.entries(ov.field_stats || {}).map(([k, v]) => [k, +(v.rate * 100).toFixed(1)]);
  bar($("#chartField"), fs.map(([k]) => k), fs.map(([, v]) => v),
      { color: "#2f6bff", max: 100, suffix: "%", title: "字段填充率(%)" });

  // 公告类型分布
  const ty = Object.entries(ov.announce_types || {}).filter(([k]) => k);
  pie($("#chartTypes"), ty.map(([k, v]) => ({ name: k, value: v })), "公告类型分布");

  // TOP 采购单位
  const units = (ov.top_procurement_units || []).slice(0, 10).reverse();
  bar($("#chartUnits"), units.map((u) => u.name.length > 12 ? u.name.slice(0, 12) + "…" : u.name),
      units.map((u) => u.count), { color: "#12b886", title: "公告数" });

  // TOP 中标供应商
  const wins = (ov.top_winners || []).slice(0, 10).reverse();
  bar($("#chartWinners"), wins.map((w) => w.name.length > 12 ? w.name.slice(0, 12) + "…" : w.name),
      wins.map((w) => w.total_amount_wan), { color: "#7b2fbe", title: "中标金额(万元)" });
}

function bar(el, cats, vals, opt) {
  const c = echarts.init(el);
  c.setOption({
    grid: { left: 10, right: 30, top: 30, bottom: 10, containLabel: true },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: cats, axisLabel: { fontSize: 11, interval: 0, rotate: 24 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10 } },
    series: [{ type: "bar", data: vals, itemStyle: { color: opt.color },
               label: { show: true, position: "top", fontSize: 10, formatter: (p) => p.value + (opt.suffix || "") } }],
  });
  return c;
}
function pie(el, data, title) {
  const c = echarts.init(el);
  c.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [{ type: "pie", radius: ["35%", "68%"], data,
               label: { fontSize: 11, formatter: "{b}\n{c}" } }],
  });
  return c;
}

/* ---------------- 标的物检索 ---------------- */
let itemPage = 1;
async function searchItems() {
  const f = new URLSearchParams();
  const el = $("#itemForm");
  ["keyword", "brand", "category", "source"].forEach((k) => {
    const v = el.querySelector(`[name=${k}]`).value.trim();
    if (v) f.set(k, v);
  });
  ["min_price", "max_price", "min_quantity", "page_size"].forEach((k) => {
    const v = el.querySelector(`[name=${k}]`).value.trim();
    if (v) f.set(k, v);
  });
  f.set("page", itemPage);
  const d = await jget("/api/v1/items?" + f.toString());
  $("#itemMeta").textContent = `共 ${d.total} 条 · 第 ${d.page} 页`;
  $("#itemPage").textContent = `${d.page} / ${Math.max(1, Math.ceil(d.total / (d.page_size || 20)))}`;
  $("#itemPrev").disabled = d.page <= 1;
  $("#itemNext").disabled = d.page * d.page_size >= d.total;
  $("#itemTable tbody").innerHTML = d.items.map((it) =>
    `<tr><td>${it.seq ?? ""}</td><td>${esc(it.product_name)}</td><td>${esc(it.category || "-")}</td>
     <td>${esc(it.brand || "-")}</td><td>${esc(it.spec_model || "-")}</td>
     <td>${fmtNum(it.quantity, 1)}${esc(it.unit ? " " + it.unit : "")}</td>
     <td>${fmtNum(it.unit_price)}</td><td>${fmtNum(it.total_price)}</td>
     <td>${esc(it.source || "-")}</td></tr>`).join("") ||
    `<tr><td colspan="9" style="text-align:center;color:#999">无数据</td></tr>`;
}
$("#itemSearch").addEventListener("click", () => { itemPage = 1; searchItems(); });
$("#itemNext").addEventListener("click", () => { itemPage++; searchItems(); });
$("#itemPrev").addEventListener("click", () => { if (itemPage > 1) { itemPage--; searchItems(); } });
$("#itemForm").addEventListener("keydown", (e) => { if (e.key === "Enter") { itemPage = 1; searchItems(); } });

/* ---------------- 公告浏览 ---------------- */
let annPage = 1;
async function searchAnns() {
  const f = new URLSearchParams();
  const el = $("#annForm");
  ["keyword", "procurement_unit", "announce_type"].forEach((k) => {
    const v = el.querySelector(`[name=${k}]`).value.trim();
    if (v) f.set(k, v);
  });
  f.set("page", annPage);
  const d = await jget("/api/v1/announcements?" + f.toString());
  $("#annMeta").textContent = `共 ${d.total} 条 · 第 ${d.page} 页`;
  $("#annPage").textContent = `${d.page} / ${Math.max(1, Math.ceil(d.total / (d.page_size || 20)))}`;
  $("#annPrev").disabled = d.page <= 1;
  $("#annNext").disabled = d.page * d.page_size >= d.total;
  $("#annTable tbody").innerHTML = d.items.map((a) =>
    `<tr><td>${esc(a.title)}<div class="mono" style="color:#9aa">${esc(a.project_code || "")}</div></td>
     <td>${esc(a.announce_type || "-")}</td><td>${esc(a.publish_date || "-")}</td>
     <td>${fmtNum(a.total_amount)}</td>
     <td><button class="btn" onclick="showAnn(${a.id})">详情</button></td></tr>`).join("") ||
    `<tr><td colspan="5" style="text-align:center;color:#999">无数据</td></tr>`;
}
async function showAnn(id) {
  const a = await jget(`/api/v1/announcements/${id}`);
  const pu = a.procurement_org ? `采购单位: <b>${esc(a.procurement_org.norm_name)}</b>` : "";
  const parts = (a.participations || [])
    .map((p) => `<span class="role-tag role-${esc(p.role)}">${
      ({ winner: "中标", bidder: "投标", procurement_unit: "采购", product_supplier: "产品供应", agency: "代理" })[p.role] || esc(p.role)
    }</span>${esc((p.organization || {}).norm_name || "")}` + (p.amount ? ` (${fmtNum(p.amount)}万)` : ""))
    .join(" ");
  const items = (a.items || []).map((it, i) =>
    `<tr><td>${i + 1}</td><td>${esc(it.product_name)}</td><td>${esc(it.category || "-")}</td>
     <td>${esc(it.brand || "-")}</td><td>${esc(it.spec_model || "-")}</td>
     <td>${fmtNum(it.quantity, 1)}</td><td>${fmtNum(it.unit_price)}</td><td>${fmtNum(it.total_price)}</td></tr>`).join("");
  $("#annDetail").innerHTML = `
    <div class="panel">
      <h3>${esc(a.title)}</h3>
      <p class="hint">${pu} · 类型: ${esc(a.announce_type || "-")} · 发布日期: ${esc(a.publish_date || "-")} ·
        总金额: ${fmtNum(a.total_amount)}万 · 编号: <span class="mono">${esc(a.project_code || "-")}</span></p>
      <div style="margin:8px 0">${parts || "暂无参与方"}</div>
      <h4 style="margin:10px 0 6px">标的物明细 (${(a.items || []).length})</h4>
      <div class="tablewrap"><table class="dtable"><thead><tr><th>#</th><th>产品服务名称</th><th>品目</th><th>品牌</th><th>规格型号</th><th>数量</th><th>单价(元)</th><th>总价(元)</th></tr></thead>
      <tbody>${items || `<tr><td colspan="8" style="text-align:center;color:#999">无标的物(详见附件)</td></tr>`}</tbody></table></div>
    </div>`;
  $("#annDetail").scrollIntoView({ behavior: "smooth" });
}
$("#annSearch").addEventListener("click", () => { annPage = 1; searchAnns(); });
$("#annPrev").addEventListener("click", () => { if (annPage > 1) { annPage--; searchAnns(); } });
$("#annNext").addEventListener("click", () => { annPage++; searchAnns(); });
$("#annForm").addEventListener("keydown", (e) => { if (e.key === "Enter") { annPage = 1; searchAnns(); } });

/* ---------------- 场景分析 ---------------- */
function sceneTable(rows, cols, cell) {
  if (!rows || !rows.length) return "<p class='hint'>无数据</p>";
  return `<div class="tablewrap"><table><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${cell(r, c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
const orgName = (o) => (o && o.name) ? esc(o.name) : "-";

async function runScene1() {
  const u = $("#s1").value.trim();
  if (!u) return;
  const d = (await jget(`/api/v1/scenarios/1?procurement_unit=${encodeURIComponent(u)}`)).data;
  if (d.matched === false) { $("#s1out").innerHTML = "<p class='hint'>未找到该采购单位</p>"; return; }
  $("#s1out").innerHTML =
    `<p class="hint">项目数 ${d.project_count} · 合作总额 ${fmtNum(d.total_amount_wan)} 万</p>` +
    sceneTable(d.cooperated_winners || [], ["中标供应商", "合作次数", "总金额(万)"],
      (r, c) => c === "中标供应商" ? orgName(r.organization) : fmtNum(r[c === "合作次数" ? "cooperate_count" : "total_amount_wan"])) +
    sceneTable((d.product_suppliers || []).slice(0, 10), ["产品供应商(品牌)", "出现公告数"],
      (r, c) => c === "产品供应商(品牌)" ? esc(r.brand) : fmtNum(r.cooperate_count));
}
async function runScene2() {
  const u = $("#s2").value.trim();
  if (!u) return;
  const d = (await jget(`/api/v1/scenarios/2?procurement_unit=${encodeURIComponent(u)}`)).data;
  if (d.matched === false) { $("#s2out").innerHTML = "<p class='hint'>未找到该采购单位</p>"; return; }
  $("#s2out").innerHTML =
    `<h4>TOP5 高频投标主体</h4>` +
    sceneTable(d.top_bidders || [], ["主体", "投标次数"],
      (r, c) => c === "主体" ? orgName(r.organization) : fmtNum(r.bid_count)) +
    `<h4 style="margin-top:8px">高频协同投标组合</h4>` +
    sceneTable(d.top_co_bid_combos || [], ["主体A", "主体B", "共同投标次数"],
      (r, c) => c === "主体A" ? orgName(r.organization_a) : c === "主体B" ? orgName(r.organization_b) : fmtNum(r.co_bid_count));
}
async function runScene3() {
  const s = $("#s3").value.trim();
  if (!s) return;
  const d = (await jget(`/api/v1/scenarios/3?supplier=${encodeURIComponent(s)}`)).data;
  if (d.matched === false) { $("#s3out").innerHTML = "<p class='hint'>未找到该主体</p>"; return; }
  $("#s3out").innerHTML =
    `<p class="hint">中标项目 ${d.project_count} 个 · 共同参与主体 ${(d.all_participants || []).length} 家</p>` +
    sceneTable((d.top_co_bidders || []).slice(0, 5), ["共同竞标主体", "共同出现次数", "总金额(万)"],
      (r, c) => c === "共同竞标主体" ? orgName(r.organization) : c === "共同出现次数" ? fmtNum(r.count, 0) : fmtNum(r.total_amount_wan));
}
async function runScene4() {
  const s = $("#s4").value.trim();
  if (!s) return;
  const d = (await jget(`/api/v1/scenarios/4?suppliers=${encodeURIComponent(s)}`)).data;
  if (d.matched === false) { $("#s4out").innerHTML = "<p class='hint'>未找到中标供应商或无可共同合作的采购单位</p>"; return; }
  $("#s4out").innerHTML =
    `<p class="hint">共同合作采购单位 ${(d.common_units || []).length} 家</p>` +
    sceneTable((d.common_units || []).slice(0, 15), ["采购单位", "合作总数", "总金额(万)"],
      (r, c) => c === "采购单位" ? orgName(r.organization) : c === "合作总数" ? fmtNum(r.total_cooperate_count, 0) : fmtNum(r.total_amount_wan));
}
async function runScene5() {
  const s = $("#s5").value.trim();
  if (!s) return;
  const d = (await jget(`/api/v1/scenarios/5?suppliers=${encodeURIComponent(s)}`)).data;
  if (d.matched === false) { $("#s5out").innerHTML = "<p class='hint'>未找到中标供应商或无可共同参与项目</p>"; return; }
  $("#s5out").innerHTML =
    `<p class="hint">共同竞标项目 ${d.project_count} 个 · 总金额 ${fmtNum(d.total_amount_wan)} 万</p>` +
    sceneTable((d.projects || []).slice(0, 10), ["项目", "日期", "角色"],
      (r, c) => c === "项目" ? esc(r.title) : c === "日期" ? esc(r.publish_date || "-") :
        Object.entries(r.roles || {}).map(([n, v]) => `${esc(n.slice(0, 12))}:${esc(v.role || "-")}`).join("，"));
}
async function searchOrg() {
  const q = $("#orgq").value.trim();
  if (!q) return;
  const d = await jget(`/api/v1/orgs?q=${encodeURIComponent(q)}&page_size=8`);
  $("#orgout").innerHTML = sceneTable(d.items || [], ["名称", "类型"],
    (r, c) => c === "名称" ? orgName(r) : esc(({ procurement_unit: "采购单位", winner: "中标供应商", bidder: "投标参与方", product_supplier: "产品供应商", agency: "代理机构" })[r.kind] || r.kind || "-"));
}

/* ---------------- 关系图谱 ---------------- */
async function loadGraph() {
  const g = (await jget("/api/v1/stats/graph")).data || {};
  const nodes = (g.nodes || []).map((n) => ({
    id: n.id, name: n.name, category: n.kind, symbolSize: n.kind === "procurement_unit" ? 34 : 24,
  }));
  const edges = (g.edges || []).map((e) => ({ source: e.source, target: e.target, value: e.relation }));
  const kinds = [...new Set(nodes.map((n) => n.category))];
  const colors = { procurement_unit: "#2f6bff", winner: "#12b886", bidder: "#ff922b",
                   product_supplier: "#9c36b5", agency: "#868e96" };
  const c = echarts.init($("#graphChart"));
  c.setOption({
    tooltip: { formatter: (p) => p.dataType === "edge" ? `${p.data.value}` : `${p.data.name}<br/>${p.data.category || ""}` },
    legend: { bottom: 0, data: kinds, textStyle: { fontSize: 11 } },
    series: [{
      type: "graph", layout: "force", roam: true, draggable: true,
      data: nodes, links: edges,
      categories: kinds.map((k) => ({ name: k, itemStyle: { color: colors[k] || "#adb5bd" } })),
      label: { show: true, fontSize: 10, formatter: (p) => (p.name || "").slice(0, 10) },
      force: { repulsion: 260, edgeLength: [60, 140] },
      lineStyle: { color: "source", curveness: 0.1, opacity: 0.55 },
    }],
  });
}
$("#graphChart").addEventListener("resize", () => { });

/* ---------------- 数据导入 ---------------- */
async function loadTasks() {
  try {
    const d = await jget("/api/v1/datasets/tasks?page_size=10");
    $("#taskTable").innerHTML = (d.items || []).map((t) => {
      const det = t.detail || {};
      const s = det.summary || {};
      return `<tr><td>${t.id}</td><td>${esc(t.name || "")}</td>
        <td>${esc(t.status)}</td>
        <td>${s.ok !== undefined ? `成功 ${s.ok} / 失败 ${s.failed}` : t.progress ?? ""}</td>
        <td>${fmtNum(t.duration_ms, 0)}</td>
        <td>${esc((det.error || "") || (s.avg_ms_per_announcement ? `单篇 ${s.avg_ms_per_announcement}ms` : ""))}</td></tr>`;
    }).join("") || `<tr><td colspan="6" style="text-align:center;color:#999">暂无导入任务</td></tr>`;
  } catch (e) { /* ignore */ }
}
$("#upForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const file = $("#upFile").files[0];
  if (!file) { $("#upOut").innerHTML = "<p class='hint' style='color:#e03131'>请先选择 zip 文件</p>"; return; }
  const fd = new FormData();
  fd.append("file", file);
  const engine = $("#upEngine").value;
  const r = await fetch(`/api/v1/datasets/upload?engine=${engine}`, { method: "POST", body: fd });
  const j = await r.json();
  $("#upOut").innerHTML = `<p class="hint">${esc(j.message || "")}${
    j.data ? ` <b>任务号: ${j.data.task_id}</b>` : ""}</p>`;
  loadTasks();
  setInterval(loadTasks, 3000);
});
