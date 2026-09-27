# -*- coding: utf-8 -*-
"""附件解析器: zip 解压 + doc/docx/xlsx/pdf/pptx 文本抽取。

- .docx: python-docx (段落+表格)
- .xlsx: openpyxl (全部工作表)
- .pdf : pypdf
- .pptx: python-pptx(可选)
- .doc : 优先 LibreOffice 转换; 失败则保存原始路径供 LLM/OCR 兜底
- 图片 : 可选 paddleocr(未安装时仅登记)

同时提供从纯文本中抽取"标的物行"的启发式规则(用于附件表格)。
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .utils import clean_text, parse_amount, parse_number, parse_quantity

try:
    import docx  # python-docx
except Exception:  # pragma: no cover
    docx = None

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    import pptx  # python-pptx
except Exception:  # pragma: no cover
    pptx = None

try:
    import paddleocr  # 可选 OCR
except Exception:  # pragma: no cover
    paddleocr = None


@dataclass
class FileText:
    name: str
    text: str
    kind: str = "text"            # text | table | error
    error: str = ""


@dataclass
class AttachmentResult:
    files: list[FileText] = field(default_factory=list)
    error: str = ""

    @property
    def all_text(self) -> str:
        return "\n".join(f.text for f in self.files)


_SUPPORTED = {".docx": "_read_docx", ".xlsx": "_read_xlsx", ".pdf": "_read_pdf",
              ".pptx": "_read_pptx", ".doc": "_read_doc", ".txt": "_read_txt"}


class AttachmentParser:
    def __init__(self, libreoffice: str = "soffice") -> None:
        self._lo = shutil.which(libreoffice) or libreoffice

    # ------------------------------------------------------------ 入口
    def parse(self, archive_path: str | Path) -> AttachmentResult:
        path = Path(archive_path)
        res = AttachmentResult()
        if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
            self._parse_zip_stream(path, res, depth=0)
        else:
            self._parse_single(path, res)
        return res

    def _parse_zip_stream(self, src, res: AttachmentResult, *, depth: int) -> None:
        """支持嵌套压缩包(外层 zip 内含 zip/docx/pdf...), 深度受限。"""
        if depth > 3:
            return
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            res.error = res.error or "not-a-zip"
            return
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            ext = Path(name).suffix.lower()
            if ext == ".zip":
                try:
                    raw = zf.read(info)
                    self._parse_zip_stream(io.BytesIO(raw), res, depth=depth + 1)
                except Exception as e:  # noqa: BLE001
                    res.files.append(FileText(name=name, text="", error=f"nested-zip: {e}"))
                continue
            if ext not in _SUPPORTED and ext not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}:
                continue
            try:
                raw = zf.read(info)
                if ext in _SUPPORTED:
                    self._parse_bytes(name, ext, raw, res)
                else:
                    self._ocr_image(name, raw, res)
            except Exception as e:  # noqa: BLE001
                res.files.append(FileText(name=name, text="", error=str(e)))

    def _parse_single(self, path: Path, res: AttachmentResult) -> None:
        ext = path.suffix.lower()
        if ext in _SUPPORTED:
            try:
                self._parse_bytes(path.name, ext, path.read_bytes(), res)
            except Exception as e:  # noqa: BLE001
                res.files.append(FileText(name=path.name, text="", error=str(e)))
        elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".gif"}:
            self._ocr_image(path.name, path.read_bytes(), res)

    def _parse_bytes(self, name: str, ext: str, raw: bytes, res: AttachmentResult) -> None:
        fn = getattr(self, _SUPPORTED.get(ext, ""))

        # 对 doc 的 LibreOffice 转换需要落盘
        if ext == ".doc":
            tmp = self._tmp_write(name, raw)
            try:
                fn(tmp, res, name=name)
            finally:
                tmp.unlink(missing_ok=True)
            return
        if ext == ".pdf":
            import io
            fn(io.BytesIO(raw), res, name=name)  # type: ignore[call-arg]
            return
        import io
        fn(io.BytesIO(raw), res, name=name)  # type: ignore[call-arg]

    def _tmp_write(self, name: str, raw: bytes) -> Path:
        import tempfile
        fd, p = tempfile.mkstemp(suffix=Path(name).suffix or ".doc")
        with open(p, "wb") as f:
            f.write(raw)
        import os
        os.close(fd)
        return Path(p)

    # ------------------------------------------------------------ 各格式
    def _read_txt(self, stream, res: AttachmentResult, name: str = "") -> None:
        data = stream.read()
        try:
            text = clean_text(data.decode("utf-8"))
        except UnicodeDecodeError:
            text = clean_text(data.decode("gbk", errors="replace"))
        res.files.append(FileText(name=name, text=text))

    def _read_docx(self, stream, res: AttachmentResult, name: str = "") -> None:
        if docx is None:
            res.files.append(FileText(name=name, text="", error="python-docx missing"))
            return
        d = docx.Document(stream)
        parts: list[str] = []
        for p in d.paragraphs:
            if p.text.strip():
                parts.append(p.text.strip())
        for table in d.tables:
            for row in table.rows:
                cells = [clean_text(c.text) for c in row.cells]
                # 去重(合并单元格会重复)
                seen: list[str] = []
                for c in cells:
                    if not seen or seen[-1] != c:
                        seen.append(c)
                if seen:
                    parts.append(" | ".join(c for c in seen if c))
        res.files.append(FileText(name=name, text="\n".join(parts), kind="table" if d.tables else "text"))

    def _read_xlsx(self, stream, res: AttachmentResult, name: str = "") -> None:
        if openpyxl is None:
            res.files.append(FileText(name=name, text="", error="openpyxl missing"))
            return
        wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
        parts: list[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                vals = [clean_text(str(c)) for c in row if c is not None and str(c).strip()]
                if vals:
                    parts.append(" | ".join(vals))
        res.files.append(FileText(name=name, text="\n".join(parts), kind="table"))

    def _read_pdf(self, stream, res: AttachmentResult, name: str = "") -> None:
        if PdfReader is None:
            res.files.append(FileText(name=name, text="", error="pypdf missing"))
            return
        import logging
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(stream)
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        res.files.append(FileText(name=name, text="\n".join(parts)))

    def _read_pptx(self, stream, res: AttachmentResult, name: str = "") -> None:
        if pptx is None:
            res.files.append(FileText(name=name, text="", error="python-pptx missing"))
            return
        prs = pptx.Presentation(stream)
        parts: list[str] = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = "".join(run.text for run in para.runs).strip()
                        if t:
                            parts.append(t)
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        parts.append(" | ".join(clean_text(c.text) for c in row.cells))
        res.files.append(FileText(name=name, text="\n".join(parts)))

    def _read_doc(self, path: Path, res: AttachmentResult, name: str = "") -> None:
        """旧版 .doc: 尝试 LibreOffice 文本转换。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.txt"
            try:
                subprocess.run(
                    [self._lo, "--headless", "--convert-to", "txt:Text (encoded):UTF8",
                     "--outdir", td, str(path)],
                    capture_output=True, timeout=60, check=False)
                if out.exists():
                    res.files.append(FileText(name=name, text=clean_text(out.read_text(encoding="utf-8", errors="replace"))))
                    return
            except Exception as e:  # noqa: BLE001
                res.files.append(FileText(name=name, text="", error=f"doc-convert: {e}"))
                return
        res.files.append(FileText(name=name, text="", error="doc-convert: libreoffice unavailable"))

    def _ocr_image(self, name: str, raw: bytes, res: AttachmentResult) -> None:
        if paddleocr is None:
            res.files.append(FileText(name=name, text="", error="ocr-missing"))
            return
        res.files.append(FileText(name=name, text="", error="ocr-not-configured"))


# ---------------------------------------------------------------- 从文本抽标的物行
_LINE_SPLIT_RE = re.compile(r"\s{2,}|\s\|\s|\t|；|;")
_TOKEN_QTY_RE = re.compile(r"^\d+(\.\d+)?\s*(套|台|块|个|批|次|项|米|件|人|年|组|条|只|张|位|名|份|期|箱|把|架)$")

_WIN_SUP_RE = re.compile(
    r"(?:中标供应商名称|成交供应商名称|预中标供应商名称|中标单位|成交单位|中标供应商|"
    r"成交供应商|中标人|成交人|拟中标人|中选单位|供应商名称)\s*[:：]\s*([^，。；\n]{2,60})")
_WIN_AMOUNT_RE = re.compile(
    r"(?:中标|成交|合同|中标（成交）)?(?:金额|总金额|价格|总价|报价|价)\s*[:：]?\s*"
    r"(?:人民币)?(?:￥|¥)?\s*([\d,，]+(?:\.\d+)?)\s*(万元|万|元)")
_WIN_PKG_RE = re.compile(r"(?:包号|标包|标段|分包|采购包|合同包)[^\d\n]{0,4}([A-Ha-h一二三四五六七八九十\d]+)")


def extract_winners_from_text(text: str) -> list[dict]:
    """从附件文本(中标通知书/结果确认/开标一览表等)中抽取中标供应商与金额。"""
    wins: list[dict] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        m = _WIN_SUP_RE.search(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1).strip(" ：:")
        name = re.sub(r"^(第?\d+\s*[包标段区]\s*[：:]?\s*)", "", name)
        if len(name) < 2 or "详见" in name:
            i += 1
            continue
        amount = None
        pkg = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            am = _WIN_AMOUNT_RE.search(lines[j])
            if am:
                unit = am.group(2)
                val = float(am.group(1).replace(",", "").replace("，", ""))
                amount = val if unit in ("万元", "万") else val / 10000.0
                break
        pm = _WIN_PKG_RE.search(lines[i])
        if pm:
            pkg = pm.group(1)
        wins.append({"org_raw": name, "amount_wan": amount, "package": pkg})
        i += 1
    # 去重
    seen: set[str] = set()
    out: list[dict] = []
    for w in wins:
        k = w["org_raw"] + "|" + str(w["amount_wan"])
        if k in seen:
            continue
        seen.add(k)
        out.append(w)
    return out


def extract_item_lines(text: str) -> list[dict]:
    """启发式: 从附件纯文本中找出形如 '名称 品牌 型号 数量 单价' 的行。"""
    items: list[dict] = []
    for line in text.splitlines():
        line = clean_text(line)
        if not line or len(line) < 6:
            continue
        if _LINE_SPLIT_RE.search(line) is None:
            continue
        toks = [t.strip() for t in _LINE_SPLIT_RE.split(line) if t.strip() and t.strip() != "|"]
        if len(toks) < 3:
            continue
        # 首 token 应为中文名称
        if not re.match(r"^[\u4e00-\u9fffA-Za-z0-9（）()\-–—·./]+$", toks[0]):
            continue
        if re.match(r"^[\d,]+\.?\d*$", toks[0]):
            continue
        rec: dict = {"product_name": toks[0], "brand": "", "spec_model": "",
                     "quantity": None, "quantity_text": "", "quantity_unit": "",
                     "unit_price": None, "total_price": None}
        for t in toks[1:]:
            q = _TOKEN_QTY_RE.match(t)
            qv = parse_number(t)
            if rec["unit_price"] is None and ("￥" in t or "¥" in t or "元" in t) and qv is not None:
                rec["unit_price"] = parse_amount(t)
                continue
            if q and rec["quantity"] is None:
                rec["quantity"], rec["quantity_unit"] = parse_quantity(t)
                rec["quantity_text"] = t
                continue
            if rec["spec_model"] == "" and re.search(r"[A-Za-z][A-Za-z0-9\-/.]{2,}", t):
                rec["spec_model"] = t
                continue
            if rec["brand"] == "" and re.fullmatch(r"[\u4e00-\u9fff]{2,12}", t):
                rec["brand"] = t
        if rec["unit_price"] is None and rec["quantity"] is None and rec["spec_model"] == "":
            continue
        items.append(rec)
    return items
