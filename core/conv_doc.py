"""Document conversions: Word/Excel/PowerPoint via local MS Office (if installed),
plus pure-Python fallbacks for docx/md/txt/html."""
import html as htmllib
import sys
import threading
from pathlib import Path

from . import conv_pdf

_office_lock = threading.Lock()


def _office_available(prog_id: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id))
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


HAS_WORD = _office_available("Word.Application")
HAS_EXCEL = _office_available("Excel.Application")
HAS_POWERPOINT = _office_available("PowerPoint.Application")

# Word SaveAs2 format codes
WORD_FORMATS = {"pdf": 17, "docx": 16, "doc": 0, "rtf": 6, "odt": 23, "txt": 7, "html": 10, "xps": 18}
WORD_IN = {"doc", "docx", "docm", "dot", "dotx", "rtf", "odt", "wpd", "wps"}
EXCEL_IN = {"xls", "xlsx", "xlsm", "xlsb", "ods"}
PPT_IN = {"ppt", "pptx", "pptm", "pps", "ppsx", "odp"}


def _com(fn):
    """Run an Office automation call with COM initialised on this thread."""
    import pythoncom
    with _office_lock:
        pythoncom.CoInitialize()
        try:
            return fn()
        finally:
            pythoncom.CoUninitialize()


def word_convert(src: Path, out: Path, params: dict):
    fmt = out.suffix.lower().lstrip(".")

    def run():
        import win32com.client
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            doc = word.Documents.Open(str(src.resolve()), ConfirmConversions=False, ReadOnly=True,
                                      AddToRecentFiles=False, Visible=False)
            try:
                if fmt == "pdf":
                    doc.ExportAsFixedFormat(str(out.resolve()), 17, OptimizeFor=0)
                else:
                    doc.SaveAs2(str(out.resolve()), FileFormat=WORD_FORMATS[fmt])
            finally:
                doc.Close(False)
        finally:
            word.Quit()
    _com(run)
    return [out]


def excel_to_pdf(src: Path, out: Path, params: dict):
    def run():
        import win32com.client
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        try:
            wb = xl.Workbooks.Open(str(src.resolve()), ReadOnly=True, UpdateLinks=0)
            try:
                for ws in wb.Worksheets:  # fit each sheet to page width
                    try:
                        ws.PageSetup.Zoom = False
                        ws.PageSetup.FitToPagesWide = 1
                        ws.PageSetup.FitToPagesTall = False
                    except Exception:
                        pass
                wb.ExportAsFixedFormat(0, str(out.resolve()))
            finally:
                wb.Close(False)
        finally:
            xl.Quit()
    _com(run)
    return [out]


def ppt_to_pdf(src: Path, out: Path, params: dict):
    def run():
        import win32com.client
        pp = win32com.client.DispatchEx("PowerPoint.Application")
        try:
            pres = pp.Presentations.Open(str(src.resolve()), ReadOnly=True, Untitled=False, WithWindow=False)
            try:
                pres.SaveAs(str(out.resolve()), 32)  # ppSaveAsPDF
            finally:
                pres.Close()
        finally:
            pp.Quit()
    _com(run)
    return [out]


def ppt_to_pptx(src: Path, out: Path, params: dict):
    def run():
        import win32com.client
        pp = win32com.client.DispatchEx("PowerPoint.Application")
        try:
            pres = pp.Presentations.Open(str(src.resolve()), ReadOnly=True, Untitled=False, WithWindow=False)
            try:
                pres.SaveAs(str(out.resolve()), 24)  # ppSaveAsOpenXMLPresentation
            finally:
                pres.Close()
        finally:
            pp.Quit()
    _com(run)
    return [out]


# ---------------- pure-Python fallbacks ----------------

def docx_to_html(src: Path, out: Path, params: dict):
    """Basic but dependable: headings, paragraphs (bold/italic), lists, tables."""
    import docx
    d = docx.Document(str(src))
    parts = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = docx.text.paragraph.Paragraph(child, d)
            runs = []
            for r in p.runs:
                t = htmllib.escape(r.text)
                if r.bold:
                    t = f"<b>{t}</b>"
                if r.italic:
                    t = f"<i>{t}</i>"
                if r.underline:
                    t = f"<u>{t}</u>"
                runs.append(t)
            text = "".join(runs)
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") and style[-1:].isdigit():
                n = min(int(style[-1]), 6)
                parts.append(f"<h{n}>{text}</h{n}>")
            elif style == "title":
                parts.append(f"<h1>{text}</h1>")
            elif "list" in style:
                parts.append(f"<ul><li>{text}</li></ul>")
            else:
                parts.append(f"<p>{text or '&nbsp;'}</p>")
        elif tag == "tbl":
            t = docx.table.Table(child, d)
            rows = []
            for row in t.rows:
                cells = "".join(f"<td>{htmllib.escape(c.text)}</td>" for c in row.cells)
                rows.append(f"<tr>{cells}</tr>")
            parts.append("<table>" + "".join(rows) + "</table>")
    html = "<!doctype html><html><head><meta charset='utf-8'></head><body>" + "\n".join(parts) + "</body></html>"
    out.write_text(html.replace("</ul>\n<ul>", ""), encoding="utf-8")
    return [out]


def docx_to_txt(src: Path, out: Path, params: dict):
    import docx
    d = docx.Document(str(src))
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append("\t".join(c.text for c in row.cells))
    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]


def docx_to_pdf_fallback(src: Path, out: Path, params: dict):
    tmp = out.with_suffix(".tmp.html")
    docx_to_html(src, tmp, params)
    try:
        conv_pdf.html_to_pdf(tmp, out, params)
    finally:
        tmp.unlink(missing_ok=True)
    return [out]


def md_to_html(src: Path, out: Path, params: dict):
    import markdown
    body = markdown.markdown(src.read_text(encoding="utf-8", errors="replace"),
                             extensions=["tables", "fenced_code", "sane_lists", "toc"])
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{htmllib.escape(src.stem)}</title>"
                   f"</head><body>{body}</body></html>", encoding="utf-8")
    return [out]


def txt_to_html(src: Path, out: Path, params: dict):
    text = htmllib.escape(src.read_text(encoding="utf-8", errors="replace"))
    out.write_text(f"<!doctype html><meta charset='utf-8'><body><pre style='white-space:pre-wrap'>{text}</pre></body>",
                   encoding="utf-8")
    return [out]


def html_to_txt(src: Path, out: Path, params: dict):
    import re
    raw = src.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</tr>", "\n", raw)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", raw))
    out.write_text(re.sub(r"\n{3,}", "\n\n", text).strip(), encoding="utf-8")
    return [out]


def txt_to_docx(src: Path, out: Path, params: dict):
    import docx
    d = docx.Document()
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        d.add_paragraph(line)
    d.save(str(out))
    return [out]


def md_to_docx(src: Path, out: Path, params: dict):
    import re
    import docx
    d = docx.Document()
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            d.add_heading(m.group(2), level=len(m.group(1)))
        elif re.match(r"^\s*[-*+]\s+", line):
            d.add_paragraph(re.sub(r"^\s*[-*+]\s+", "", line), style="List Bullet")
        elif re.match(r"^\s*\d+\.\s+", line):
            d.add_paragraph(re.sub(r"^\s*\d+\.\s+", "", line), style="List Number")
        elif line.strip():
            p = d.add_paragraph()
            for chunk in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", line):
                if chunk.startswith("**") and chunk.endswith("**"):
                    p.add_run(chunk[2:-2]).bold = True
                elif chunk.startswith("*") and chunk.endswith("*") and len(chunk) > 1:
                    p.add_run(chunk[1:-1]).italic = True
                else:
                    p.add_run(chunk)
    d.save(str(out))
    return [out]


def html_to_md(src: Path, out: Path, params: dict):
    import re
    raw = src.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|head).*?</\1>", "", raw)
    for n in range(6, 0, -1):
        raw = re.sub(rf"(?is)<h{n}[^>]*>(.*?)</h{n}>", lambda m: "\n" + "#" * n + " " + m.group(1) + "\n", raw)
    raw = re.sub(r"(?is)<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", raw)
    raw = re.sub(r"(?is)<(i|em)[^>]*>(.*?)</\1>", r"*\2*", raw)
    raw = re.sub(r"(?is)<a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", r"[\2](\1)", raw)
    raw = re.sub(r"(?is)<li[^>]*>", "\n- ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</tr>", "\n\n", raw)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", raw))
    out.write_text(re.sub(r"\n{3,}", "\n\n", text).strip() + "\n", encoding="utf-8")
    return [out]
