# -*- coding: utf-8 -*-
"""文本/金额/数量/主体名 规范化工具。"""
from __future__ import annotations

import re

# ---- 通用文本 ----

_WS_RE = re.compile(r"\s+")
_FULL_SPACE_RE = re.compile(r"[\u3000\u00a0]")


def clean_text(s: str | None) -> str:
    """去除空白、全角空格、控制符。"""
    if not s:
        return ""
    s = _FULL_SPACE_RE.sub(" ", str(s))
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = _WS_RE.sub(" ", s)
    return s.strip(" \t\r\n|;；")


# ---- 金额/数字 ----

_NUM_WAN_RE = re.compile(
    r"[（(]?\s*(万元|元)\s*[）)]?|￥|¥|人民币"
)
_NUM_CLEAN_RE = re.compile(r"[^\d.\-%]")
_RANGE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[-~—至]\s*(-?\d+(?:\.\d+)?)$")

_CN_DIGITS = {"零": 0, "〇": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
              "陆": 6, "柒": 7, "捌": 8, "玖": 9, "一": 1, "二": 2, "两": 2,
              "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"拾": 10, "佰": 100, "仟": 1000, "十": 10, "百": 100, "千": 1000}


def cn_amount_to_yuan(text: str) -> float | None:
    """中文大写金额 → 元。如 '叁佰贰拾伍万零叁佰壹拾元整' -> 3250310.0。"""
    if not any(ch in _CN_DIGITS or ch in _CN_UNITS or ch in {"万", "億", "元", "圆"} for ch in text):
        return None
    main = text.replace("人民币", "").replace("大写", "").replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    for marker in ("元", "圆"):
        idx = main.find(marker)
        if idx > 0:
            main = main[:idx]
            break
    if not any(ch in _CN_DIGITS or ch in _CN_UNITS or ch in {"万", "萬", "亿", "億"} for ch in main):
        return None
    total = 0.0
    section = 0.0
    number = 0
    for ch in main:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            number = number or 1
            section += number * _CN_UNITS[ch]
            number = 0
        elif ch in {"万", "萬"}:
            section = (section + number) * 10000
            total += section
            section = 0
            number = 0
        elif ch in {"亿", "億"}:
            section = (section + number) * 1e8
            total += section
            section = 0
            number = 0
    return total + section + number


def parse_number(text: str | None) -> float | None:
    """从文本中提取第一个数值(用于数量)。如 '4套'->4, '2,300.50'->2300.5。"""
    if not text:
        return None
    t = _NUM_CLEAN_RE.sub("", str(text))
    if not t:
        return None
    try:
        v = float(t)
        return v
    except ValueError:
        return None


def parse_amount(text: str | None, *, to_wan: bool = False) -> float | None:
    """解析金额。

    - 中文数字金额: 12345.67 元 / 12345.67(元) / ￥12,345.67
    - 万元金额: 243.1310000（万元） / ￥325.031000 万元（人民币）
    - to_wan=False 时返回元; to_wan=True 时返回万元(用于公告总金额/中标金额)。
    """
    if not text:
        return None
    t = clean_text(text)
    t = _NUM_WAN_RE.sub(" ", t)
    m = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", t)
    if m:
        try:
            v = float(m.group().replace(",", ""))
        except ValueError:
            v = None
    else:
        # 中文大写金额兜底
        v = cn_amount_to_yuan(text or "")
    if v is None:
        return None
    is_wan = ("万元" in text) or bool(re.search(r"[\d.]+\s*万(?!元)", text))
    if is_wan:
        return v if to_wan else v * 10000
    return v / 10000 if to_wan else v


# ---- 数量(含单位) ----

_QTY_RE = re.compile(r"^\s*([\d.,]+)\s*([^\d，。；;、,]*)$")


def parse_quantity(text: str | None) -> tuple[float | None, str]:
    """返回 (数值, 单位)。'4套'->(4,'套')  '52块'->(52,'块')。"""
    if not text:
        return None, ""
    m = _QTY_RE.match(clean_text(text))
    if not m:
        return None, clean_text(text)
    try:
        v = float(m.group(1).replace(",", "").strip("."))
    except ValueError:
        v = None
    return v, m.group(2).strip()


# ---- 主体(公司/单位)名称规范化 ----

_ORG_STRIP_RE = re.compile(
    r"^(第\s*\d+\s*[包标段区]|包\s*\d+|标段\s*\d+|包号|采购包\s*\d+|包\d+)?\s*"
)
# 形如 "第3包 总控光配线系统：北京万迪科信息技术有限公司" 或
#     "供应商名称：xxx" "中标供应商：xxx" "成交供应商：xxx"
_PREFIX_COLON_RE = re.compile(
    r"^(?:[^:：]{0,20}?(?:供应商|中标人|成交人|投标人))?\s*[:：]\s*"
)
_TAIL_NOISE_RE = re.compile(r"(（联合体）|\(联合体\)|联合体|（包\d+）|\(包\d+\)|供应商名单|有限责任公司$){0,1}")


def normalize_org_name(raw: str | None) -> str:
    """把公告里出现的各种写法归一为可检索的公司名。

    例: '第3包 总控光配线系统：北京万迪科信息技术有限公司'
        -> '北京万迪科信息技术有限公司'
    """
    if not raw:
        return ""
    name = clean_text(raw)
    if not name:
        return ""
    # 联合体中标: 只保留牵头单位名("XX(联合体成员：A、B)" -> "XX")
    name = re.sub(r"[（(]联合体成员[^（()）]*[）)]\s*$", "", name)
    name = re.sub(r"[（(]联合体[^（()）]*[）)]\s*$", "", name)
    # 尾部包/标段注记: "XX（二标段）" -> "XX"
    name = re.sub(r"[（(]第?\s*[一二三四五六七八九十\d]+\s*[标段包区分包][^（()）]*[）)]\s*$", "", name)
    # 取冒号/分号后的主体名(前置说明段去除)
    parts = re.split(r"[:：]", name)
    name = parts[-1].strip()
    # 去掉包号前缀
    name = _ORG_STRIP_RE.sub("", name).strip()
    name = _PREFIX_COLON_RE.sub("", name).strip()
    # 去掉常见后缀噪音(如 "...供应商名单")
    name = re.sub(r"(?:供应商|评审专家|专家)名单\s*$", "", name).strip()
    name = re.sub(r"[、，,;；\s]+$", "", name)
    # 全角/半角括号统一并保留
    name = name.replace("（", "(").replace("）", ")")
    if not name:
        return ""
    # 若还残留 "第X包" 前缀则再删一次
    name = re.sub(r"^第?\s*\d+\s*[包标段区]?\s*", "", name).strip()
    return name


def is_company_like(name: str) -> bool:
    """粗略判断是否为法人主体名(用于过滤非公司行)。"""
    if not name:
        return False
    if re.fullmatch(r"第?\d+\s*[包标段区]", name):
        return False
    return len(name) >= 2 and (
        "公司" in name or "研究院" in name or "设计院" in name or "勘察院" in name
        or "测绘院" in name or "科学院" in name or "监测院" in name or "规划院" in name
        or "工程院" in name or "总院" in name or "大学" in name or "学院" in name
        or "中学" in name or "小学" in name or "幼儿园" in name or "医院" in name
        or "中心" in name or "局" in name or "部" in name or "集团" in name
        or "事务所" in name or "银行" in name or "学校" in name or "出版社" in name
        or "报社" in name or "杂志社" in name or "通讯社" in name or "电视台" in name
        or "学会" in name or "协会" in name or "联合会" in name or "理事会" in name
        or "委员会" in name or "总队" in name or "支队" in name or "大队" in name
        or "中队" in name or "合作社" in name or "农场" in name or "牧场" in name
        or "林场" in name or "基地" in name or "馆" in name or "所" in name
    )


_COMPANY_TOKEN_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()]+?(?:公司|研究院|设计院|勘察院|测绘院|科学院|监测院|规划院|"
    r"工程院|总院|事务所|有限公司|有限责任公司|股份公司|大学|学院|医院|中学|小学|幼儿园|"
    r"中心|集团|出版社|报社|电视台|学会|协会|联合会|委员会|总局|总队|支队|大队|中队|合作社|"
    r"农场|牧场|林场|基地|气象局|地质局|人民政府|财政局|教育局|公安局|信息中心|服务中心)")


def extract_company_names(text: str, *, limit: int = 50) -> list[str]:
    """从正文中抽取疑似法人主体名(去重、保序)。"""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _COMPANY_TOKEN_RE.finditer(text):
        name = m.group(0)
        if len(name) < 4 or len(name) > 40:
            continue
        if name in seen:
            continue
        if any(k in name for k in ("项目", "招标", "采购", "名称")):
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


# ---- 常见角色/标题模式 ----

ROLE_WINNER_PATTERNS = re.compile(
    r"(中标供应商|中标人|成交供应商|成交人|第一中标候选人|预中标人|"
    r"候选供应商|推荐供应商|拟中标人)\s*[:：]?"
)
ROLE_BIDDER_PATTERNS = re.compile(
    r"(未中标供应商|未成交供应商|参与投标|投标供应商|参与报价|"
    r"其他供应商|落选供应商|未通过(?:资格性|符合性)?审查|评审未通过|"
    r"候选成交供应商|成交候选供应商|投标单位|参与方|开标一览表)"
)

ANNOUNCE_TYPES = ("中标公告", "成交公告", "更正公告", "招标公告", "竞争性磋商公告",
                  "竞争性谈判公告", "询价公告", "单一来源采购公示", "资格预审公告",
                  "废标公告", "流标公告", "结果公告", "终止公告", "中标结果公告",
                  "成交结果公告", "公开招标公告", "采购公告", "比选公告")


def detect_announce_type(title: str) -> str:
    """从标题尾部识别公告类型。"""
    t = clean_text(title)
    for typ in ANNOUNCE_TYPES:
        if t.endswith(typ):
            return typ
    for typ in ANNOUNCE_TYPES:  # 非尾部也尝试
        if typ in t:
            return typ
    return ""

# 包号/标段提取, 如 "第3包" "包1" "采购包2"
PACKAGE_RE = re.compile(r"(第?\s*\d+\s*[包标段]|包\s*\d+|[包标段]\s*\d+|采购包\s*\d+)")
