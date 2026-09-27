# -*- coding: utf-8 -*-
"""公告 HTML 解析: 把一条招采标讯公告转为结构化记录。

支持中国政府采购网(ccgp.gov.cn)详情页样式:
- 抬头/公告概要表格(div.table): 采购项目名称/品目/采购单位/总中标金额/公告时间...
- 正文(vF_detail_content): 项目编号、中标(成交)信息(段落式或表格式)、
  主要标的信息表格(7 字段)、参与投标方、评审/代理信息。
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from .utils import (PACKAGE_RE, ROLE_BIDDER_PATTERNS, clean_text,
                    detect_announce_type, is_company_like, normalize_org_name,
                    parse_amount, parse_number, parse_quantity)

# 序号/包号等垃圾名称
_JUNK_NAME_RE = re.compile(
    r"^(?:[\d.\-—－、]+|\s*0?\d+\s*包\s*|[（(]?[一二三四五六七八九十]{1,3}[）)]?|[-—－]+)$", re.I)
_ITEM_PKG_PREFIX_RE = re.compile(r"^(?:第?\s*\d+\s*[标段包区分包]\s*[:：]?\s*)")


def _clean_item_name(name: str) -> str:
    """清洗标的物名称: 去包前缀, 过滤序号垃圾。"""
    n = (name or "").strip()
    if not n or len(n) > 200:
        return ""
    if _JUNK_NAME_RE.match(n):
        return ""
    n = _ITEM_PKG_PREFIX_RE.sub("", n).strip()
    return n


@dataclass
class ItemRecord:
    """标的物记录(7 个关键字段)。"""
    product_name: str = ""          # 产品服务名称
    category: str = ""              # 品目
    brand: str = ""                 # 品牌(产品供应商)
    spec_model: str = ""            # 规格型号
    unit_price: float | None = None # 单价(元)
    quantity: float | None = None   # 数量
    quantity_text: str = ""         # 数量原文(含单位)
    quantity_unit: str = ""         # 计量单位
    total_price: float | None = None  # 总价(元)
    supplier_raw: str = ""          # 供应商原文(可能是 "第3包 xx：公司")
    supplier_norm: str = ""         # 规范化后的中标供应商名
    package: str = ""               # 标段/包号
    source: str = "html"            # html | attachment
    item_raw: str = ""              # 原始单元格文本
    seq: int = 0


@dataclass
class WinnerRecord:
    org_norm: str
    org_raw: str
    amount_wan: float | None = None
    package: str = ""


@dataclass
class AnnouncementRecord:
    """一条公告的完整抽取结果。"""
    html_file: str = ""
    attachment_file: str = ""
    title: str = ""
    project_name: str = ""
    project_code: str = ""
    announce_type: str = ""
    publish_date: str = ""
    total_amount_wan: float | None = None
    agency_name: str = ""
    procurement_unit: str = ""
    winners: list[WinnerRecord] = field(default_factory=list)
    bidders: list[str] = field(default_factory=list)          # 参与投标(未中标)主体
    items: list[ItemRecord] = field(default_factory=list)
    raw_text: str = ""
    parse_ms: int = 0

    @property
    def title_hash(self) -> str:
        return hashlib.sha256(self.title.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 表头映射

_NAME_KEYS = {"货物名称", "产品名称", "服务名称", "采购标的", "标的名称", "标的物",
              "货物及服务名称", "品目名称", "产品服务名称", "名称", "货物/服务名称",
              "主要标的", "采购内容"}
_SUPPLIER_KEYS = {"供应商名称", "中标供应商名称", "成交供应商名称", "供应商",
                  "中标供应商", "成交供应商"}
_BRAND_KEYS = {"货物品牌", "品牌", "产品品牌", "品牌（生产厂家）", "品牌(生产厂家)",
               "品牌/制造商", "生产厂商", "制造商"}
_SPEC_KEYS = {"货物型号", "规格型号", "型号", "规格", "技术规格", "配置",
              "型号规格", "货物规格型号"}
_QTY_KEYS = {"货物数量", "数量", "采购数量", "中标数量"}
_PRICE_KEYS = {"货物单价(元)", "货物单价（元）", "单价(元)", "单价（元）", "单价",
               "中标单价", "成交单价", "单价(元/套)", "单价(元/块)", "预算单价"}
_TOTAL_KEYS = {"总价", "总价(元)", "总价（元）", "投标总价", "总金额", "合计金额",
               "总报价", "中标总价", "成交总价", "小计"}

_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_CODE_RE = re.compile(r"(?:项目|招标|采购)编号\s*[:：]?\s*([A-Za-z0-9\-—_/]{4,})")

# 中标(成交)信息 小节标题(严格: 节号 + 中标/成交 + (（成交）) + 信息)
_WINNER_SEC_RE = re.compile(r"^[一二三四五六七八九十百\d]+[、.．]?\s*(?:中标|成交)(?:（成交）)?信息")
_WINNER_SEC_RE2 = re.compile(r"^(?:中标|成交)(?:（成交）)?信息")
# 主要标的信息 小节标题
_ITEMS_SEC_RE = re.compile(r"^[一二三四五六七八九十\d]+[、.．]?\s*主要标[\w（()）]{0,8}信息")
_SECTION_NUM_RE = re.compile(r"^[一二三四五六七八九十\d]+[、.．]")
# 中标供应商段落模式("供应商名称：X" 仅在 中标(成交)信息 小节内使用)
_WINNER_PARA_RE = re.compile(
    r"(?:中标供应商|成交供应商|中标人|成交人|中标（成交）供应商|中标（成交）人|供应商)"
    r"(?:名称)?(?:\s*[:：]\s*|\s+)(.+)$")
# 中标金额段落模式
_AMOUNT_PARA_RE = re.compile(
    r"(?:中标（成交）金额|中标金额|成交金额|中标价|成交价|中标（成交）总金额)"
    r"\s*[:：]?\s*(.+)$")
# 供应商名称+金额 同一段
_SUP_AMT_INLINE_RE = re.compile(
    r"(?:供应商名称|中标供应商|成交供应商|中标人|成交人)\s*[:：]\s*(.+?)[，,。;；]?\s*"
    r"(?:中标（成交）金额|中标金额|成交金额|中标价|成交价)\s*[:：]\s*(.+)$")


def _norm_date(s: str) -> str:
    m = _DATE_RE.search(s or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    s = clean_text(s)
    m = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", s)
    return m.group(0).replace("/", "-") if m else s[:20]


# ---------------------------------------------------------------- 解析器


class AnnouncementHtmlParser:
    """一条公告 HTML → AnnouncementRecord。"""

    def parse_file(self, path: str) -> AnnouncementRecord:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()
        return self.parse(html, html_file=path)

    def parse(self, html: str, *, html_file: str = "") -> AnnouncementRecord:
        t0 = time.perf_counter()
        rec = AnnouncementRecord(html_file=html_file)
        soup = BeautifulSoup(html, "lxml")
        self._parse_head(soup, rec)
        self._parse_summary_table(soup, rec)
        self._parse_content(soup, rec)
        # 末端清洗: 过滤序号/包号等垃圾名, 去掉名称前的"标段/包"前缀
        cleaned: list[ItemRecord] = []
        for it in rec.items:
            name = _clean_item_name(it.product_name)
            if not name:
                continue
            it.product_name = name
            if it.category and _JUNK_NAME_RE.match(it.category or ""):
                it.category = ""
            cleaned.append(it)
        rec.items = cleaned
        rec.parse_ms = int((time.perf_counter() - t0) * 1000)
        return rec

    # -- 头部(title / 类型 / 发布日期) --
    def _parse_head(self, soup: BeautifulSoup, rec: AnnouncementRecord) -> None:
        title_tag = soup.find("title")
        rec.title = clean_text(title_tag.get_text() if title_tag else "")
        if not rec.title:
            h2 = soup.select_one("div.vF_detail_header h2, h2.tc")
            rec.title = clean_text(h2.get_text() if h2 else "")
        rec.project_name = rec.title
        rec.announce_type = detect_announce_type(rec.title)
        meta = soup.find("meta", attrs={"name": "PubDate"})
        if meta and meta.get("content"):
            rec.publish_date = _norm_date(meta["content"])

    # -- 公告概要表格 --
    def _parse_summary_table(self, soup: BeautifulSoup, rec: AnnouncementRecord) -> None:
        table = soup.select_one("div.table table")
        if not table:
            return
        rows: dict[str, str] = {}
        for tr in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            i = 0
            while i + 1 < len(cells):
                label, value = cells[i], cells[i + 1]
                if label and value and not label.startswith(("公告信息", "联系人及联系方式")):
                    rows.setdefault(label, value)
                i += 2

        if not rec.publish_date:
            rec.publish_date = _norm_date(rows.get("公告时间", ""))
        rec.agency_name = rows.get("代理机构名称", "")
        if not rec.procurement_unit:
            rec.procurement_unit = rows.get("采购单位", "")
        amt = (rows.get("总中标金额", "") or rows.get("总成交金额", "") or rows.get("中标金额", ""))
        if amt and amt not in {"0", "0.0", "0.000000"}:
            rec.total_amount_wan = parse_amount(amt, to_wan=True)
        cat = rows.get("品目", "")
        if cat:
            rec.category_fallback = cat  # type: ignore[attr-defined]

    # -- 正文 --
    def _parse_content(self, soup: BeautifulSoup, rec: AnnouncementRecord) -> None:
        content = soup.select_one("div.vF_detail_content") or soup

        # 1) 项目编号 / 项目名称
        for p in content.find_all("p"):
            text = clean_text(p.get_text(" "))
            if _SECTION_NUM_RE.match(text) and "项目编号" in text:
                m = _CODE_RE.search(text)
                if m:
                    rec.project_code = m.group(1)
            elif _SECTION_NUM_RE.match(text) and "项目名称" in text:
                nm = text.split("项目名称", 1)[-1].lstrip("：: ")
                nm = re.sub(r"[（(].*$", "", nm).strip()
                if nm and len(nm) < 100:
                    rec.project_name = nm

        # 2) 中标(成交)信息: 段落式 + 表格式
        self._parse_winners(content, rec)
        self._parse_winner_tables(content, rec)

        # 3) 主要标的信息表格
        for table in content.find_all("table"):
            try:
                self._parse_target_table(table, rec, source="html")
            except Exception:  # noqa: BLE001 单表异常不阻断整篇
                continue

        # 3.5) 段落键值式标的物(名称/货物品牌/数量/单价... 逐行罗列)
        self._parse_paragraph_items(content, rec)

        # 3.6) 总中标成交金额兜底(正文段落)
        if rec.total_amount_wan is None or rec.total_amount_wan == 0:
            for p in content.find_all("p"):
                m = re.search(r"总中标(?:成交)?金额\s*[:：]\s*(.+?)\s*[，。]?\s*$", clean_text(p.get_text(" ")))
                if m:
                    v = parse_amount(m.group(1), to_wan=True)
                    if v:
                        rec.total_amount_wan = v
                        break

        # 4) 参与投标方(未中标) —— 规则匹配
        self._parse_bidders(content, rec)

        # 5) 采购单位兜底(正文"名 称：xxx")
        if not rec.procurement_unit:
            for p in content.find_all("p"):
                m = re.match(r"名\s*称\s*[:：]\s*(.+)", clean_text(p.get_text(" ")))
                if m and is_company_like(m.group(1)):
                    rec.procurement_unit = m.group(1)
                    break

        # 6) 正文纯文本(供检索/LLM 兜底)
        rec.raw_text = clean_text(content.get_text("\n"))

    # -- 中标(成交)信息(段落式) --
    def _parse_winners(self, content: Tag, rec: AnnouncementRecord) -> None:
        winner_section: list[str] | None = None
        for tag in content.find_all(["p", "h4", "h5"]):
            t = clean_text(tag.get_text(" "))
            if not t:
                continue
            tt = re.sub(r"\s+", "", t)   # 容忍 "三、 成交 信息 / 成交 金额" 空格
            if (_WINNER_SEC_RE.match(tt) or _WINNER_SEC_RE2.match(tt)) and "标的信息" not in tt:
                winner_section = []
                continue
            if winner_section is not None:
                if _ITEMS_SEC_RE.match(tt) or (tt.startswith(("四、", "4、", "五、", "5、")) and "标的信息" in tt):
                    break
                winner_section.append(tt)

        if winner_section:
            pending: str | None = None
            current_pkg = ""
            for t in winner_section:
                pm = re.match(r"(?:标段名称|标包名称|标包|包号|标段)\s*[:：]\s*(.+)$", t)
                if pm and not re.search(r"供应商(?:名称)?\s*[:：]|中标金额|成交金额", t):
                    current_pkg = pm.group(1).strip()
                    continue
                m = _SUP_AMT_INLINE_RE.search(t)
                if m:
                    self._add_winner(rec, m.group(1), parse_amount(m.group(2), to_wan=True),
                                     package=current_pkg)
                    pending = None
                    continue
                m = _WINNER_PARA_RE.search(t)
                if m:
                    pending = m.group(1).strip()
                    continue
                m = _AMOUNT_PARA_RE.search(t.replace(" ", ""))
                if m and pending:
                    self._add_winner(rec, pending, parse_amount(m.group(1), to_wan=True),
                                     package=current_pkg)
                    pending = None
            if pending:
                self._add_winner(rec, pending, None, package=current_pkg)
        if not rec.winners:
            self._parse_winners_global(content, rec)

    # -- 中标(成交)信息: 无小节标题时的全局兜底(供应商名称+相邻中标金额) --
    def _parse_winners_global(self, content: Tag, rec: AnnouncementRecord) -> None:
        paras = [re.sub(r"\s+", "", clean_text(p.get_text(" "))) for p in content.find_all("p")]
        for i, t in enumerate(paras):
            m = re.match(r"(?:成交|中标|预中标)?供应商名称\s*[:：]\s*(.+)$", t)
            if not m:
                continue
            raw = m.group(1).strip()
            if not is_company_like(raw):
                continue
            pkg = ""
            if i > 0:
                pm = re.match(r"(?:标段名称|标包|包号|标段)\s*[:：]\s*(.+)$", paras[i - 1])
                if pm:
                    pkg = pm.group(1).strip()
            amt = None
            for j in range(i + 1, min(i + 6, len(paras))):
                aj = _AMOUNT_PARA_RE.search(paras[j].replace(" ", ""))
                if aj:
                    amt = parse_amount(aj.group(1), to_wan=True)
                    break
                if re.match(r"供应商地址|地址\s*[:：]", paras[j]) or "供应商" not in paras[j]:
                    continue
                if "中标" in paras[j] or "成交" in paras[j] or "金额" in paras[j]:
                    continue
                break
            if amt is None:
                continue
            self._add_winner(rec, raw, amt, package=pkg)
        # 跨段落 "供应商名称： / 第一包：公司 / 中标金额： / 第一包：345.2万" 布局
        if rec.winners:
            return

        def _consec_pkg_list(start: int) -> dict[str, str]:
            out: dict[str, str] = {}
            for t in paras[start + 1:]:
                pm = re.match(r"(第?[一二三四五六七八九十\d]+包|[A-H]包)\s*[:：]\s*(.+)$", t)
                if pm:
                    out[pm.group(1)] = pm.group(2).strip()
                    continue
                break
            return out

        names_map: dict[str, str] = {}
        amts_map: dict[str, float] = {}
        for i, t in enumerate(paras):
            if re.fullmatch(r"供应商名称\s*[:：]\s*", t):
                names_map.update(_consec_pkg_list(i))
            elif re.fullmatch(r"(?:中标|成交)金额\s*[:：]\s*", t):
                for pkg, val in _consec_pkg_list(i).items():
                    v = parse_amount(val, to_wan=True)
                    if v is not None:
                        amts_map[pkg] = v
        for pkg, name in names_map.items():
            if not is_company_like(name):
                continue
            amt = amts_map.get(pkg)
            if amt is None:
                continue
            self._add_winner(rec, name, amt, package=pkg)

        # "合同包1:/采购包1: 服务类（潍坊文博广告有限公司）" 中标供应商在括号中(无金额)
        prev_pkg = ""
        for i, t in enumerate(paras):
            pm = re.match(r"(合同包|采购包|包)\d*\s*[:：]?\s*$", t)
            if pm:
                prev_pkg = t
                continue
            mm = re.search(r"[服务货物\w]*类（([^（）]{4,60})）", t)
            if not mm:
                continue
            sup = mm.group(1).strip()
            prev = paras[i - 1] if i > 0 else ""
            if is_company_like(sup) and (re.match(r"(合同包|采购包|包)\d*", t) or re.match(r"(合同包|采购包|包)\d*", prev) or prev_pkg):
                self._add_winner(rec, sup, None, package=prev_pkg)
                prev_pkg = ""
        return

    # -- 中标(成交)信息(表格式) --
    def _parse_winner_tables(self, content: Tag, rec: AnnouncementRecord) -> None:
        for table in content.find_all("table"):
            rows = table.find_all("tr")
            head = None
            head_cells: list[str] = []
            for tr in rows:
                cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
                flat = "".join(cells)
                has_sup0 = any(len(c) <= 12 and ("供应商" in c or "中标人" in c or "成交人" in c) for c in cells)
                # 未中标原因表 = 参与投标方(含评标结果等)
                if ("未中标" in flat and "原因" in flat) or ("未成交" in flat and "原因" in flat) or "评标结果" in flat:
                    if has_sup0:
                        self._parse_bidder_table(table, rec)
                        head = None  # 已处理, 不再当作中标表
                        break
                has_sup, has_amt, has_pkg = self._win_header_flags(cells)
                if not (has_sup and (has_amt or has_pkg)):
                    # 纯"供应商名称+地址/编码"表(中标供应商无金额) -> 供应商名单
                    if has_sup and not any(k in flat for k in ("审查", "原因")):
                        if any(len(c) <= 12 and "供应商" in c and "名称" in c for c in cells) \
                                and not any(k in flat for k in ("货物", "标的", "数量", "单价", "总价", "品牌")):
                            self._parse_winner_list_table(table, rec)
                            head = None
                            break
                    continue
                if "货物名称" in flat and "品牌" in flat:  # 标的物表, 跳过
                    continue
                head, head_cells = tr, cells
                break
            if head is None:
                # 行内键值对布局(标包/供应商名称/地址 按行排)
                self._parse_winner_kv_table(table, rec)
                continue

            idx_sup = next((i for i, c in enumerate(head_cells) if "供应商" in c or "中标人" in c or "成交人" in c), 0)
            idx_amt = next((i for i, c in enumerate(head_cells) if "金额" in c or "中标价" in c or "成交价" in c), None)
            idx_pkg = next((i for i, c in enumerate(head_cells) if "包号" in c or "标段" in c or "分包名称" in c), None)
            for tr in rows[1:]:
                vals = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
                if not vals or len(vals) <= max(i for i in (idx_sup, idx_amt, idx_pkg) if i is not None):
                    continue
                sup = vals[idx_sup] if idx_sup < len(vals) else ""
                if not sup or sup == "合计" or sup.startswith("小计"):
                    continue
                sup = re.sub(r"^(第?\d+\s*[包标段区]\s*[：:]?\s*)", "", sup).strip()
                if not is_company_like(sup):
                    continue
                amt = parse_amount(vals[idx_amt], to_wan=True) if idx_amt is not None and idx_amt < len(vals) else None
                pkg = vals[idx_pkg] if idx_pkg is not None and idx_pkg < len(vals) else ""
                self._add_winner(rec, sup, amt, package=pkg)

    # -- 行内键值对式中标信息表(如 [标 包, A, 供应商名称, X公司, 供应商地址, ...]) --
    def _parse_winner_kv_table(self, table: Tag, rec: AnnouncementRecord) -> bool:
        flat = "".join(clean_text(c.get_text(" ")) for c in table.find_all(["td", "th"]))
        flat = re.sub(r"\s+", "", flat)
        if re.search(r"(金额|得分|优惠率)\s*[:：]", flat):
            return False
        hit = False
        for tr in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ")).strip() for c in tr.find_all(["td", "th"])]
            for i, c in enumerate(cells):
                if c.replace(" ", "") not in ("供应商名称", "中标供应商名称", "成交供应商名称", "预中标供应商名称"):
                    continue
                sup = cells[i + 1].strip() if i + 1 < len(cells) else ""
                if not is_company_like(sup):
                    continue
                pkg = ""
                for j in range(max(0, i - 2), i):
                    if re.fullmatch(r"(?:标\s*包|包号|标段)[\s：:]*", cells[j]):
                        pkg = cells[j + 1].strip() if j + 1 < len(cells) else ""
                self._add_winner(rec, sup, None, package=pkg)
                hit = True
                break
        return hit

    # -- 中标供应商名单表(供应商名称 + 地址/编码 等, 无金额) --
    def _parse_winner_list_table(self, table: Tag, rec: AnnouncementRecord) -> None:
        rows = table.find_all("tr")
        head_cells: list[str] = []
        for tr in rows[:8]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if any(len(c) <= 12 and "供应商" in c for c in cells):
                head_cells = cells
                break
        if not head_cells:
            return
        idx_sup = next((i for i, c in enumerate(head_cells) if "供应商" in c), 0)
        idx_pkg = next((i for i, c in enumerate(head_cells) if "包号" in c or "标段" in c), None)
        for tr in rows[1:]:
            vals = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if not vals or idx_sup >= len(vals):
                continue
            sup = vals[idx_sup]
            if not sup or sup in {"合计", "小计", "供应商名称", "供应商"}:
                continue
            sup = re.sub(r"^(第?\d+\s*[包标段区]\s*[：:]?\s*)", "", sup).strip()
            if not is_company_like(sup):
                continue
            pkg = vals[idx_pkg] if idx_pkg is not None and idx_pkg < len(vals) else ""
            self._add_winner(rec, sup, None, package=pkg)

    # -- 参与投标方(表格: 供应商名称 + 未中标原因) --
    def _parse_bidder_table(self, table: Tag, rec: AnnouncementRecord) -> None:
        rows = table.find_all("tr")
        head_cells: list[str] = []
        for tr in rows[:8]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if any(len(c) <= 12 and ("供应商" in c or "单位名称" in c or "投标人" in c or "投标单位" in c) for c in cells):
                head_cells = cells
                break
        if not head_cells:
            return
        idx = next((i for i, c in enumerate(head_cells) if "供应商" in c or "单位名称" in c or "投标人" in c), None)
        if idx is None:
            return
        for tr in table.find_all("tr")[1:]:
            vals = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if idx >= len(vals):
                continue
            name = self._clean_bidder_name(vals[idx])
            if name and is_company_like(name) and name not in rec.bidders:
                rec.bidders.append(name)

    def _add_winner(self, rec: AnnouncementRecord, raw: str, amount_wan: float | None,
                    package: str = "") -> None:
        norm = normalize_org_name(raw)
        if not norm:
            return
        pkg = package or ""
        if not pkg:
            m = PACKAGE_RE.search(raw)
            pkg = m.group(0) if m else ""
        # 去重(同主体+同包号; 包号为空视为同包)
        for w in rec.winners:
            if w.org_norm == norm:
                if w.package != pkg and w.package and pkg:
                    continue
                if w.amount_wan is None and amount_wan is not None:
                    w.amount_wan = amount_wan
                elif w.amount_wan is not None and amount_wan is None:
                    pass  # 已有金额, 忽略无金额重复
                return
        rec.winners.append(WinnerRecord(org_norm=norm, org_raw=clean_text(raw),
                                        amount_wan=amount_wan, package=pkg))

    # -- 主要标的信息表格 --
    # 单元格内嵌键值对的"明确标的属性"标签(避免命中供应商名称/中标金额等)
    _KVCELL_ATTR_RE = re.compile(
        r"(?:货物名称|商品名称|货物品牌|品牌|货物规格型号|规格型号|型号|货物数量|数量|"
        r"货物单价|单价|货物总价|总价|品目|货物类别|类别|服务范围|服务要求|服务时间|"
        r"服务标准|服务期限|施工范围|项目概况|技术要求|名称)\s*[:：]")
    # 仅在无供应商上下文的明确键时才命中
    _KVCELL_STRICT_RE = re.compile(
        r"(?:货物名称|商品名称|货物品牌|货物规格型号|规格型号|货物数量|货物单价|单价|总价|"
        r"品牌|数量|服务范围|服务要求|服务时间|服务标准|服务期限|施工范围)\s*[:：]")
    # 键值标签必须位于单元格开头(允许 "A包/标段/货物" 前缀), 排除正文中的 "名称：" 等
    _KVCELL_CELL_RE = re.compile(
        r"^(?:[A-H一二三四五六七八九十]\s*包|第?\s*\d+\s*包|标段|标包|货物|商品|工程|服务)?"
        r"(?:货物名称|商品名称|货物品牌|品牌|规格型号|型号|数量|单价|总价|品目|类别|名称|"
        r"服务范围|服务要求|服务时间|服务标准|服务期限|施工范围)\s*[:：]")

    def _looks_kvcell(self, table: Tag) -> bool:
        for tr in table.find_all("tr")[:60]:
            for c in tr.find_all(["td", "th"]):
                cell = re.sub(r"\s+", "", clean_text(c.get_text(" ")))
                if cell and self._KVCELL_CELL_RE.match(cell):
                    return True
        return False

    @staticmethod
    def _win_header_flags(cells: list[str]) -> tuple[bool, bool, bool]:
        """中标表表头识别: 供应商/金额/包号 需是短单元(列头), 排除大文本单元格。"""
        has_sup = any(len(c) <= 12 and ("供应商" in c or "中标人" in c or "成交人" in c) for c in cells)
        has_amt = any(len(c) <= 12 and ("金额" in c or "中标价" in c or "成交价" in c) for c in cells)
        has_pkg = any(len(c) <= 12 and ("包号" in c or "标段" in c or "分包名称" in c or "标包" in c) for c in cells)
        return has_sup, has_amt, has_pkg

    # 丑化: 是不是"中标供应商|金额"表(中标信息表, 非标的物表)
    def _is_winner_table_like(self, table: Tag) -> bool:
        for tr in table.find_all("tr")[:10]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            has_sup, has_amt, has_pkg = self._win_header_flags(cells)
            if has_sup and (has_amt or has_pkg):
                return True
        return False

    def _parse_target_table(self, table: Tag, rec: AnnouncementRecord, *, source: str) -> None:
        # 中标(成交)信息表(供应商+金额)不属于标的物, 跳过
        if self._is_winner_table_like(table):
            return
        # 纯供应商名单表(资格审查/得分 等, 无名称/金额/数量列) -> 参与投标方
        head0 = None
        for tr in table.find_all("tr")[:8]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if any(len(c) <= 12 and ("供应商" in c or "投标人" in c) for c in cells):
                head0 = cells
                break
        if head0 is not None:
            flat = "".join(head0)
            has_sup, has_amt, has_pkg = self._win_header_flags(head0)
            has_namecol = any(k in flat for k in ("货物名称", "标的名称", "商品名称", "服务名称", "工程名称", "采购标的", "规格型号", "数量", "单价", "总价", "品牌", "品目"))
            if has_sup and not has_amt and not has_pkg and not has_namecol:
                self._parse_bidder_table(table, rec)
                return
        # 单元格内嵌键值对布局(如 "名称：X 品牌：Y 规格型号：Z 数量：N ...")
        if self._looks_kvcell(table):
            before = len(rec.items)
            self._parse_kvcell_table(table, rec, source=source)
            if len(rec.items) == before and self._find_header_row(table) is not None:
                # kvcell 解析为空(如 "品目名称|服务范围" 列式表被误判) -> 回退标准表头解析
                head_row = self._find_header_row(table)
            else:
                return
        else:
            head_row = self._find_header_row(table)
            if head_row is None:
                # 大段文本单元格(整张表 = 一段 kv 文本) -> 文本键值解析
                if self._prose_table(table):
                    self._parse_textkv_table(table, rec, source=source)
                else:
                    self._parse_loose_table(table, rec, source=source)
                return
        head_flat = "".join(clean_text(c.get_text(" ")) for c in head_row.find_all(["td", "th"]))
        if len(head_flat) > 120 and self._prose_table(table):
            # 表头是整段正文(单格含 "名称：.. 服务范围：.." 等), 走文本键值
            self._parse_textkv_table(table, rec, source=source)
            return
        col_map = self._map_columns(head_row)

        item_seq = max((i.seq for i in rec.items), default=0)
        for tr in table.find_all("tr")[1:]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if not self._row_has_data(tr):
                continue
            if cells and self._is_header_row_text(cells, col_map):
                continue
            data = {k: cells[idx] if idx is not None and idx < len(cells) else ""
                    for k, idx in col_map.items()}
            if not data.get("name"):
                # 部分布局"商品名称"列为空, 但整行即该项目(供应商+金额)
                if data.get("price") or data.get("total") or data.get("qty"):
                    data["name"] = rec.project_name
                else:
                    continue
            splitted = {k: self._split_values(v) for k, v in data.items()}
            # 仅当名称列本身以 "；/;/|/多空格" 切分多条时才多条目展开;
            # 服务范围/要求等描述列不得决定条目数(避免 4 行表膨胀成几十条)
            if len(splitted.get("name", [" "])) <= 1:
                n = 1
            else:
                n = max((len(v) for v in splitted.values()), default=1)
            for i in range(n):
                _get = lambda k, i=i: (splitted.get(k, [])[i]
                                       if i < len(splitted.get(k, [])) else data.get(k, ""))
                it = ItemRecord(source=source, seq=item_seq + 1)
                it.product_name = _get("name").strip("；;，,、 ")
                if not it.product_name or it.product_name.startswith("详见") \
                        or it.product_name in {"序号", "合计", "小计"}:
                    continue
                it.brand = _get("brand")
                it.spec_model = _get("spec")
                sup = data.get("supplier", "")
                if sup:
                    it.supplier_raw = sup
                    it.supplier_norm = normalize_org_name(sup)
                    m = PACKAGE_RE.search(sup)
                    it.package = m.group(0) if m else ""
                qty_text = _get("qty")
                it.quantity_text = qty_text
                it.quantity, it.quantity_unit = parse_quantity(qty_text)
                up = _get("price")
                it.unit_price = parse_amount(up) if up else None
                tp = _get("total")
                if tp:
                    it.total_price = parse_amount(tp)
                elif it.unit_price is not None and it.quantity:
                    it.total_price = round(it.unit_price * it.quantity, 2)
                it.category = getattr(rec, "category_fallback", "") or ""
                it.item_raw = " | ".join(cells)
                if it.supplier_norm and not any(w.org_norm == it.supplier_norm for w in rec.winners):
                    self._add_winner(rec, it.supplier_raw, None)
                rec.items.append(it)
                item_seq += 1

    def _parse_kvcell_table(self, table: Tag, rec: AnnouncementRecord, *, source: str) -> None:
        """表格单元格内嵌键值对: 兼容一行多键("名称: X 品牌: Y 数量: N")与
        纵向单键多行("名称: X" 下一行 "品牌: Y" ...)两种布局。"""
        item_seq = max((i.seq for i in rec.items), default=0)
        kv_labels = (r"标段名称|标包名称|货物名称|商品名称|货物品牌|品牌|货物规格型号|规格型号|型号|"
                     r"货物数量|数量|货物单价|单价|货物总价|总价|品目|货物类别|类别|服务范围|服务要求|"
                     r"服务时间|服务标准|服务期限|施工范围|技术要求|名称")
        kv_iter_re = re.compile(
            r"((?:" + kv_labels + r"))\s*[:：]\s*(.{0,160}?)"
            r"(?=\s*(?:" + kv_labels + r")\s*[:：]|$)")
        _NAME_LABELS = {"货物名称", "商品名称", "名称"}
        _PKG_LABELS = {"标段名称", "标包名称"}

        cur: ItemRecord | None = None          # 正在累积的纵向条目
        cur_pkg = ""
        pending_category = ""

        def _flush() -> None:
            nonlocal cur
            if cur is not None:
                rec.items.append(cur)
                cur = None

        def _make_item(name: str, pairs: dict[str, str]) -> ItemRecord:
            it = ItemRecord(source=source, seq=item_seq + 1)
            it.product_name = name
            pkg_val = pairs.get("标段名称") or pairs.get("标包名称") or cur_pkg
            if pkg_val and pkg_val != name:
                it.package = pkg_val
            if not it.package:
                pm = re.search(r"(?:(?:第?\s*[一二三四五六七八九十\d]+\s*|[A-H])\s*包\s*)", pairs.get("_full", "")[:24])
                if pm:
                    it.package = pm.group(0).strip()
            # 名称前一行 "货物类/服务类" 等纯文本作为品目
            it.category = pairs.get("品目") or pairs.get("货物类别") or pairs.get("类别") \
                or pending_category or getattr(rec, "category_fallback", "") or ""
            return it

        def _fill_attrs(it: ItemRecord, pairs: dict[str, str]) -> None:
            it.brand = pairs.get("货物品牌") or pairs.get("品牌") or it.brand
            it.spec_model = pairs.get("货物规格型号") or pairs.get("规格型号") or pairs.get("型号") or it.spec_model
            qty = pairs.get("货物数量") or pairs.get("数量") or ""
            if qty and qty not in {"详见附件", "详见招标文件", "详见磋商文件"}:
                it.quantity_text = qty
                it.quantity, it.quantity_unit = parse_quantity(qty)
            price = pairs.get("货物单价") or pairs.get("单价") or ""
            if price and price not in {"详见附件", "详见招标文件", "详见磋商文件"}:
                it.unit_price = parse_amount(price)
            total = pairs.get("货物总价") or pairs.get("总价") or ""
            if total and total not in {"详见附件", "详见招标文件", "详见磋商文件"}:
                it.total_price = parse_amount(total)
            if it.unit_price is not None and it.quantity and it.total_price is None:
                it.total_price = round(it.unit_price * it.quantity, 2)

        _ATTR_ROW_LABELS = {"货物品牌", "品牌", "货物规格型号", "规格型号", "型号", "数量", "货物数量",
                            "单价", "货物单价", "总价", "货物总价"}
        for tr in table.find_all("tr"):
            full = " ".join(clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"]))
            full = re.sub(r"\s+", "", full)
            if not full:
                continue
            # 供应商行(如"供应商名称：X 中标金额：Y")不是标的物行
            if re.search(r"供应商名称\s*[:：]", full) and not self._KVCELL_STRICT_RE.search(full):
                continue
            # 去掉供应商标签, 防止 "供应商名称：" 中的"名称"被当成标的名
            full = re.sub(r"(?:中标供应商|成交供应商|供应商)名称\s*[:：]", "", full)
            # "单价(元)：" -> "单价：" 等单位标注
            full = re.sub(r"[（(](?:元|万元)[）)]", "", full)
            pairs: dict[str, str] = {}
            for m in kv_iter_re.finditer(full):
                v = m.group(2).strip(" ，,、；;").strip()
                if v:
                    pairs.setdefault(m.group(1), v)
            if not pairs:
                # 纯文本行: "货物类"/"服务类" 作为待用品目
                if len(full) <= 8 and re.fullmatch(r"[\u4e00-\u9fff]{1,4}类", full):
                    pending_category = full
                continue
            name = pairs.get("货物名称") or pairs.get("商品名称") or pairs.get("名称")
            if name is None:
                # 仅包号行
                if all(lbl in _PKG_LABELS for lbl in pairs):
                    cur_pkg = next(iter(pairs.values()))
                    continue
                # 属性行(品牌/规格/数量/单价/总价/服务范围...) 填到当前条目
                if cur is not None:
                    _fill_attrs(cur, pairs)
                continue
            # 名称行
            if not name or name.startswith("详见") or name in {"-", "无", "详见附件", "详见招标文件", "详见磋商文件"}:
                continue
            _flush()
            cur = _make_item(name, {**pairs, "_full": full})
            _fill_attrs(cur, pairs)
            item_seq += 1
            # 行内含 品牌/数量/单价/总价/规格型号 -> 一行即完整条目
            if any(lbl in pairs for lbl in _ATTR_ROW_LABELS):
                _flush()
        _flush()

    def _prose_table(self, table: Tag) -> bool:
        """表中任意行出现单个超长单元格(>60字且含多个键值标签) -> 文本式键值表。"""
        for tr in table.find_all("tr")[:20]:
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if len(cells) != 1:
                continue
            t = re.sub(r"\s+", "", cells[0])
            if len(t) > 60 and len(re.findall(r"[:：]", t)) >= 2:
                return True
        return False

    def _parse_textkv_table(self, table: Tag, rec: AnnouncementRecord, *, source: str) -> None:
        """单格整段文本的键值表(如 服务 类 / 项目名称：X 服务范围：Y ...)。"""
        item_seq = max((i.seq for i in rec.items), default=0)
        kv_iter_re = re.compile(
            r"((?:项目名称|货物名称|商品名称|服务名称|标的名称|货物品牌|品牌|规格型号|型号|"
            r"数量|货物数量|单价|货物单价|总价|货物总价|品目|类别|服务范围|服务要求|服务时间|"
            r"服务标准|服务期限|施工范围|名称))"
            r"\s*[:：]\s*(.{0,160}?)(?=\s*(?:\1|项目名称|货物名称|商品名称|服务名称|标的名称|"
            r"货物品牌|品牌|规格型号|型号|数量|货物数量|单价|货物单价|总价|货物总价|品目|类别|"
            r"服务范围|服务要求|服务时间|服务标准|服务期限|施工范围|名称)\s*[:：]|$)")
        for tr in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            t = re.sub(r"\s+", "", " ".join(cells))
            t = re.sub(r"(?:中标供应商|成交供应商|供应商)名称\s*[:：]", "", t)
            t = re.sub(r"[（(](?:元|万元)[）)]", "", t)
            pairs: dict[str, str] = {}
            for m in kv_iter_re.finditer(t):
                v = m.group(2).strip(" ，,、；;").strip()
                if v and m.group(1) not in pairs:
                    pairs[m.group(1)] = v
            name = pairs.get("货物名称") or pairs.get("商品名称") or pairs.get("服务名称") \
                or pairs.get("标的名称") or pairs.get("项目名称") or pairs.get("名称")
            if not name or name.startswith("详见") or name in {"-", "无", "详见附件", "详见磋商文件"}:
                continue
            it = ItemRecord(source=source, seq=item_seq + 1)
            it.product_name = name
            it.category = pairs.get("品目") or pairs.get("类别") or getattr(rec, "category_fallback", "") or ""
            it.brand = pairs.get("货物品牌") or pairs.get("品牌") or ""
            it.spec_model = pairs.get("规格型号") or pairs.get("型号") or ""
            qty = pairs.get("数量") or pairs.get("货物数量") or ""
            if qty and qty not in {"详见附件", "详见磋商文件"}:
                it.quantity_text = qty
                it.quantity, it.quantity_unit = parse_quantity(qty)
            price = pairs.get("单价") or pairs.get("货物单价") or ""
            if price:
                it.unit_price = parse_amount(price)
            total = pairs.get("总价") or pairs.get("货物总价") or ""
            if total:
                it.total_price = parse_amount(total)
            elif it.unit_price is not None and it.quantity:
                it.total_price = round(it.unit_price * it.quantity, 2)
            rec.items.append(it)
            item_seq += 1

    def _parse_loose_table(self, table: Tag, rec: AnnouncementRecord, *, source: str) -> None:
        """无标准表头的表格(如"序号 名称 品牌 型号 数量 单价"布局简化)。"""
        item_seq = max((i.seq for i in rec.items), default=0)
        for tr in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c not in {"序号", "序号 "}]
            if len(cells) < 3:
                continue
            first = cells[0]
            if first in {"合计", "小计", "备注", "说明"} or len(first) > 60:
                continue
            it = ItemRecord(source=source, seq=item_seq + 1)
            it.product_name = first
            it.category = getattr(rec, "category_fallback", "") or ""
            for c in cells[1:]:
                if not it.brand and re.fullmatch(r"[\u4e00-\u9fffA-Za-z]{2,20}", c) and \
                        not any(k in c for k in ("型", "号", "套", "块", "台", "元", "名", "编")):
                    it.brand = c
                elif not it.spec_model and re.search(r"[A-Za-z0-9][A-Za-z0-9\-/.]{2,}", c):
                    it.spec_model = c
                elif it.quantity is None:
                    qv, qu = parse_quantity(c)
                    if qv is not None and qu in {"套", "台", "块", "个", "批", "次", "项", "米", "件", "人", "年", "组", "条", "只", "张", "名", "份", "期", "箱", "把", "架", "位", ""}:
                        it.quantity, it.quantity_unit = qv, qu
                        it.quantity_text = c
                elif it.unit_price is None and ("￥" in c or "¥" in c or "元" in c or re.fullmatch(r"[\d,]+\.\d{2}", c)):
                    it.unit_price = parse_amount(c)
            if it.product_name:
                rec.items.append(it)
                item_seq += 1

    # -- 段落键值式标的物(如"名称: X / 货物品牌: Y / 货物数量: N / 货物单价: P") --
    _KV_NAME_KEYS = ("名称", "货物名称", "商品名称", "采购标的名称", "标的名称", "产品名称", "服务名称")
    _KV_DESC_KEYS = ("货物品牌", "产品品牌", "品牌", "货物规格型号", "规格型号", "货物型号",
                     "产品规格型号", "型号", "货物数量", "采购数量", "数量", "货物单价",
                     "中标单价", "成交单价", "单价", "总价", "货物总价", "投标总价",
                     "合计金额", "品目", "货物类别", "类别", "服务范围", "服务要求",
                     "服务时间", "服务标准", "服务期限", "技术要求")
    _KV_LABEL_RE = re.compile(
        r"^((?:货物名称|商品名称|采购标的名称|标的名称|产品名称|服务名称|名称|"
        r"货物品牌|产品品牌|品牌|货物规格型号|规格型号|货物型号|产品规格型号|型号|"
        r"货物数量|采购数量|数量|货物单价|中标单价|成交单价|单价|总价|货物总价|投标总价|"
        r"合计金额|品目|货物类别|类别|服务范围|服务要求|服务时间|服务标准|服务期限|技术要求|"
        r"标包|标段))\s*[:：]\s*(.*)$")

    def _parse_paragraph_items(self, content: Tag, rec: AnnouncementRecord) -> None:
        paras = [clean_text(p.get_text(" ")) for p in content.find_all("p")]
        runs: list[list[tuple[str, str]]] = []
        cur_run: list[tuple[str, str]] = []
        items_section = False

        def _flush_run():
            nonlocal cur_run
            if cur_run:
                runs.append(cur_run)
                cur_run = []

        for t in paras:
            if not t:
                continue
            if _ITEMS_SEC_RE.match(t) or ("主要标的信息" in t and _SECTION_NUM_RE.match(t)):
                items_section = True
                _flush_run()
                continue
            if _SECTION_NUM_RE.match(t) and re.match(
                    r"^[一二三四五六七八九十\d]+[、.．]\s*(?:评审|评标|代理|公开招标|公告|合同|验收|补充|未|采购人|供应商|开标|定标)", t):
                items_section = False
                _flush_run()
                continue
            m = self._KV_LABEL_RE.match(t)
            if not m:
                _flush_run()
                continue
            label, value = m.group(1), m.group(2).strip()
            if label in ("标包", "标段"):
                _flush_run()
                cur_run.append((label, value))
            else:
                cur_run.append((label, value))
        _flush_run()

        item_seq = max((i.seq for i in rec.items), default=0)
        for run in runs:
            kv: dict[str, str] = {}
            for label, value in run:
                if label in ("标包", "标段"):
                    kv.setdefault("package", value)
                elif label in ("货物名称", "商品名称", "采购标的名称", "标的名称", "产品名称", "服务名称", "名称"):
                    kv.setdefault("name", value)
                elif label in self._KV_DESC_KEYS:
                    kv.setdefault(label, value)
            name = kv.get("name", "")
            if not name or name.startswith("详见") or name in {"-", "无", "详见附件", "详见招标文件", "详见磋商文件"}:
                continue
            n_desc = sum(1 for label, value in run if label in self._KV_DESC_KEYS)
            projectish = bool(re.search(r"(采购|项目|建设|服务|系统|平台|工程|运维|租赁|监测|调查|设备|维护|运行|软件开发|大数据|信息化|整治|治理|演练|保险|培训|监理|维保|改造|更新|提升|体检|测试|评估|咨询|委托|运营|管理)", name))
            valid = items_section or (n_desc >= 1 and not is_company_like(name)) or \
                    (n_desc == 0 and projectish and not is_company_like(name))
            if not valid:
                continue
            it = ItemRecord(source="html", seq=item_seq + 1)
            it.product_name = name
            it.package = kv.get("package", "")
            for label, value in run:
                if label in ("货物品牌", "产品品牌", "品牌") and value not in {"详见附件", "详见招标文件", "详见磋商文件", "无", "-"}:
                    it.brand = value
                elif label in ("货物规格型号", "规格型号", "货物型号", "产品规格型号", "型号") and value not in {"详见附件", "详见招标文件", "详见磋商文件", "无", "-"}:
                    it.spec_model = value
                elif label in ("货物数量", "采购数量", "数量"):
                    if value not in {"详见附件", "详见招标文件", "详见磋商文件", "无", "-"}:
                        it.quantity_text = value
                        it.quantity, it.quantity_unit = parse_quantity(value)
                elif label in ("货物单价", "中标单价", "成交单价", "单价"):
                    if value not in {"详见附件", "详见招标文件", "详见磋商文件", "无", "-"}:
                        it.unit_price = parse_amount(value)
                elif label in ("总价", "货物总价", "投标总价", "合计金额"):
                    if value not in {"详见附件", "详见招标文件", "详见磋商文件", "无", "-"}:
                        it.total_price = parse_amount(value)
                elif label in ("品目", "货物类别", "类别"):
                    it.category = value
            if it.total_price is None and it.unit_price is not None and it.quantity:
                it.total_price = round(it.unit_price * it.quantity, 2)
            if not it.category:
                it.category = getattr(rec, "category_fallback", "") or ""
            rec.items.append(it)
            item_seq += 1
    def _parse_bidders(self, content: Tag, rec: AnnouncementRecord) -> None:
        seen: set[str] = set()
        for p in content.find_all("p"):
            t = clean_text(p.get_text(" "))
            # 形如 "未中标供应商：A、B、C" / "未中标供应商的未中标原因: A:xx; B:yy"
            for m in re.finditer(
                    r"(?:未中标供应商|未成交供应商|参与投标(?:的|的供应商)?|投标供应商|"
                    r"其他供应商|参与报价(?:的)?(?:供应商)?|落选供应商|未通过[^：:]{0,12}审查(?:的)?(?:投标)?(?:供应商)?|"
                    r"候选(?:成交)?供应商|成交候选供应商|未中标(?:的)?(?:投标)?(?:供应商)?)"
                    r"[^：:]{0,6}[:：]\s*([^。\n]+)", t):
                names_tail = m.group(1)
                # 去掉 "未中标原因" 之类的尾注
                names_tail = re.sub(r"^(?:的)?未中标原因\s*[:：]?\s*", "", names_tail)
                for part in re.split(r"[;；、，,|]+", names_tail):
                    name = self._clean_bidder_name(part)
                    if name and is_company_like(name) and name not in seen:
                        seen.add(name)
                        rec.bidders.append(name)
            # 编号式列表: "1、 山东正大...： 综合评审得分较低。"
            for m in re.finditer(r"\d+\s*[、.．]\s*([\u4e00-\u9fffA-Za-z][^：:\n]{4,79})\s*[:：]", t):
                name = self._clean_bidder_name(m.group(1))
                if name and is_company_like(name) and name not in seen:
                    seen.add(name)
                    rec.bidders.append(name)
        # 补充: 跨段落列表(上一段标签, 下一段编号条目)
        paras = [clean_text(p.get_text(" ")) for p in content.find_all("p")]
        for i, t in enumerate(paras):
            if re.search(r"(?:未中标|未成交)供应商的(?:未)?(?:中标|成交)原因", t) and "：" not in t:
                for nxt in paras[i + 1:i + 12]:
                    for m in re.finditer(r"\d+\s*[、.．]\s*([\u4e00-\u9fffA-Za-z][^：:\n]{4,79})\s*[:：]", nxt):
                        name = self._clean_bidder_name(m.group(1))
                        if name and is_company_like(name) and name not in seen:
                            seen.add(name)
                            rec.bidders.append(name)

        # 补充: 没有标签冒号但段落以 "A公司、B公司" 列出的情况(如"（二）评审情况")
        for p in content.find_all("p"):
            t = clean_text(p.get_text(" "))
            if ROLE_BIDDER_PATTERNS.search(t) and "：" not in t:
                tail = t.split("：")[-1]
                for part in re.split(r"[、，,;；\s]+", tail):
                    name = self._clean_bidder_name(part)
                    if name and is_company_like(name) and name not in seen:
                        seen.add(name)
                        rec.bidders.append(name)

    @staticmethod
    def _clean_bidder_name(name: str) -> str:
        n = normalize_org_name(name)
        if not n:
            return ""
        # 去掉段首标签: A: / B: / 序号: 等
        n = re.sub(r"^[A-Za-z0-9]{1,4}[:：]\s*", "", n).strip()
        # 去掉尾部原因注记, 如 (综合评审得分较低) (未通过符合性审查)
        for _ in range(3):
            n2 = re.sub(r"[（(][^（()）]{1,40}[）)]\s*$", "", n).strip()
            if n2 == n:
                break
            n = n2
        n = re.sub(r"[（(][^（()）]*(?:得分|评审|不合格|不符合|未|放弃|废标|无效)[^（()）]*[）)]", "", n).strip()
        n = re.sub(r"[、，,;；\s]+$", "", n)
        # 去掉拼接在名称后的否决/原因尾注(未加括号的情况), 如 "XX公司综合评审得分较低" "XX公司未提供..."
        n = re.sub(
            r"(?:综合评审|技术评审|符合性评审|商务|技术)?(?:得分)?(?:较低|偏低|低|不合格|未通过|"
            r"未满足)[^、，。；\n]{0,16}$", "", n).strip()
        n = re.sub(r"(?:未提供|未提交|未按|未附|未附具|缺少)[^、，。；\n]{0,20}$", "", n).strip()
        n = re.sub(r"[、，,;；\s]+$", "", n)
        # 排除乱序/拼接垃圾: 残存分隔符、分数、序号头、多主体拼接、超长、套话
        if not n or len(n) > 30:
            return ""
        if re.search(r"[、，,;；\s（(]|\d+\.\d", n):
            return ""
        if re.search(r"[（(]\s*\d|上表|异议|公告期限届满|详见|咨询|联系电[话  ]|致各供应商|本项目信息公告发布于|政务信息|采购信息发布媒体", n):
            return ""
        if sum(1 for k in ("公司", "研究院", "学院", "大学", "中心", "局", "医院")
               if k in n) >= 3:
            return ""
        if not is_company_like(n):
            return ""
        return n

    # ----------------------------------------------------------------- helper
    @staticmethod
    def _find_header_row(table: Tag) -> Tag | None:
        """按表头关键词命中数打分, 避免大段标题单元格被误当表头。"""
        keywords = ("货物名称", "产品名称", "标的名称", "服务名称", "商品名称", "工程名称",
                    "规格型号", "数量", "单价", "总价", "品牌", "型号",
                    "供应商名称", "中标金额", "中标供应商", "名称")
        best: Tag | None = None
        best_score = 0
        for tr in table.find_all("tr"):
            flat = "".join(clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"]))
            score = sum(1 for k in keywords if k in flat)
            if score > best_score:
                best, best_score = tr, score
        return best if best_score > 0 else None

    @staticmethod
    def _map_columns(head_row: Tag) -> dict[str, int | None]:
        cells = [clean_text(c.get_text(" ")) for c in head_row.find_all(["td", "th"])]
        mapping: dict[str, int | None] = {"name": None, "supplier": None, "brand": None,
                                          "spec": None, "qty": None, "price": None, "total": None}
        for idx, t in enumerate(cells):
            if t in _NAME_KEYS or any(k in t for k in ("货物名称", "产品名称", "标的", "工程名称", "服务名称", "品目名称")):
                mapping["name"] = idx
            if t in _SUPPLIER_KEYS or "供应商名称" in t:
                mapping["supplier"] = idx
            if t in _BRAND_KEYS or "品牌" in t:
                mapping["brand"] = idx
            if t in _SPEC_KEYS or "规格" in t or ("型号" in t and mapping["spec"] is None):
                mapping["spec"] = idx
            if t in _QTY_KEYS or "数量" in t:
                mapping["qty"] = idx
            if t in _PRICE_KEYS or "单价" in t:
                mapping["price"] = idx
            if t in _TOTAL_KEYS or "总价" in t or "金额" in t:
                mapping["total"] = idx
        return mapping

    @staticmethod
    def _row_has_data(tr: Tag) -> bool:
        return any(clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"]))

    @staticmethod
    def _is_header_row_text(cells: list[str], col_map: dict) -> bool:
        if not cells:
            return True
        joined = "".join(cells)
        if cells[0] == "序号" or cells[0].startswith("序号"):
            return True
        return ("货物名称" in joined or "产品名称" in joined) and ("品牌" in joined or "数量" in joined)

    @staticmethod
    def _split_values(v: str) -> list[str]:
        if not v:
            return []
        parts = re.split(r"[；;]", v)
        return [p.strip(" 　，,、") for p in parts if p.strip()]
