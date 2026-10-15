"""HTTP routes for the "Docs & sheets" screen (web/office.js). All under /api/office/…"""
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import office_editor as oe
from .util import DEFAULT_OUTPUT, ext_of, unique_path

bp = Blueprint("office", __name__)

# (source path, format) -> the edited copy we wrote last time, so "Save" keeps updating one copy
_COPIES: dict = {}


def ok(**kw):
    return jsonify({"ok": True, **kw})


def _body():
    return request.get_json(silent=True) or {}


def _out_dir(d) -> Path:
    return Path(d.get("out_dir") or DEFAULT_OUTPUT)


def _caps():
    from . import conv_doc
    return {"word": conv_doc.HAS_WORD, "excel": conv_doc.HAS_EXCEL, "powerpoint": conv_doc.HAS_POWERPOINT}


NEW_DIR = oe.TMP / "office_new"


def _is_new(p: Path) -> bool:
    try:
        return NEW_DIR.resolve() in p.resolve().parents
    except OSError:
        return False


def _dest(src: str, fmt: str, mode: str, out_dir: Path, writable_same: bool) -> Path:
    """Where a save goes. 'overwrite' = the original file (same format only); otherwise an '(edited)' copy."""
    src_p = Path(src)
    if mode == "overwrite" and _is_new(src_p):
        raise ValueError("This is a new document: use Save to put it in the output folder.")
    if mode == "overwrite":
        if not writable_same:
            raise ValueError(f"Can't write .{fmt} over the original .{ext_of(src_p)}. Use Save or Save as instead.")
        return src_p
    key = (str(src_p).lower(), fmt, str(out_dir).lower())
    prev = _COPIES.get(key)
    if prev and prev.exists():
        return prev
    dest = unique_path(out_dir, src_p.stem if _is_new(src_p) else f"{src_p.stem} (edited)", fmt)
    _COPIES[key] = dest
    return dest


@bp.get("/api/office/caps")
def caps():
    return ok(caps=_caps(), doc_formats=list(oe.DOC_SAVE_FORMATS), sheet_formats=list(oe.SHEET_SAVE_FORMATS))


@bp.post("/api/office/open")
def open_file():
    d = _body()
    path = (d.get("path") or "").strip().strip('"')
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("File not found: " + path)
    kind = oe.kind_of(path)
    base = {"kind": kind, "path": path, "name": Path(path).name, "ext": ext_of(path), "caps": _caps()}
    if kind == "doc":
        return ok(**base, **oe.open_document(path))
    if kind == "sheet":
        s = oe.open_sheet(path)
        if s.status == "error":
            oe.close_session(s.id)
            raise ValueError(s.error)
        return ok(**base, sheet=s.meta())
    if kind == "slides":
        return ok(**base, **oe.open_slides(path))
    if kind == "pdf":
        from . import pdf_editor
        return ok(**base, pages=pdf_editor.info(path)["pages"])
    raise ValueError(f"Docs & sheets can't open .{ext_of(path)} files. Try DOCX, XLSX, CSV, PPTX, PDF, TXT or MD.")


@bp.post("/api/office/new")
def new_document():
    """A blank A4 .docx in temp space; the first Save puts 'New document.docx' in the output folder."""
    import uuid
    import docx
    from docx.shared import Mm
    folder = NEW_DIR / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "New document.docx"
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Mm(25.4)
    d.save(str(path))
    return ok(file={"path": str(path), "name": path.name, "ext": "docx", "size_h": "", "temp": True})


# ------------------------------------------------------------------ documents
@bp.post("/api/office/doc/save")
def doc_save():
    d = _body()
    src = d.get("path") or ""
    fmt = (d.get("format") or ext_of(src) or "docx").lower().lstrip(".")
    if fmt == "htm":
        fmt = "html"
    if fmt not in oe.DOC_SAVE_FORMATS:
        raise ValueError(f"Can't save a document as .{fmt}")
    mode = d.get("mode", "copy")
    src_ext = ext_of(src)
    same = fmt == src_ext or (fmt == "html" and src_ext == "htm") or (fmt == "md" and src_ext == "markdown")
    if same and fmt in ("doc", "rtf", "odt") and not _caps()["word"]:
        same = False
    dest = _dest(src, fmt, mode, _out_dir(d), same)
    out = oe.save_document(src, d.get("html") or "", fmt, dest, d.get("page"), d.get("font"))
    return ok(path=str(out), name=out.name)


# ------------------------------------------------------------------ spreadsheets
@bp.get("/api/office/sheet/meta")
def sheet_meta():
    return ok(sheet=oe.get_session(request.args["sid"]).meta())


@bp.get("/api/office/sheet/rows")
def sheet_rows():
    s = oe.get_session(request.args["sid"])
    return ok(**s.rows(int(request.args.get("sheet", 0)), int(request.args.get("start", 0)),
                       int(request.args.get("count", 200))))


@bp.post("/api/office/sheet/rows")
def sheet_rows_by_index():
    d = _body()
    s = oe.get_session(d["sid"])
    return ok(**s.rows(int(d.get("sheet", 0)), indices=d.get("indices") or []))


PUBLIC_OPS = {"set", "fmt", "insert", "delete", "sort", "add_sheet", "delete_sheet", "rename_sheet", "col_width", "freeze"}


@bp.post("/api/office/sheet/op")
def sheet_op():
    d = _body()
    s = oe.get_session(d["sid"])
    op = d.get("op") or {}
    if op.get("type") not in PUBLIC_OPS:
        raise ValueError("Unknown edit")
    s.apply(op)
    return ok(sheet=s.meta())


@bp.post("/api/office/sheet/undo")
def sheet_undo():
    s = oe.get_session(_body()["sid"])
    s.do_undo()
    return ok(sheet=s.meta())


@bp.post("/api/office/sheet/redo")
def sheet_redo():
    s = oe.get_session(_body()["sid"])
    s.do_redo()
    return ok(sheet=s.meta())


@bp.post("/api/office/sheet/search")
def sheet_search():
    d = _body()
    s = oe.get_session(d["sid"])
    col = d.get("col")
    return ok(rows=s.search(int(d.get("sheet", 0)), d.get("q", ""), None if col is None else int(col)))


@bp.post("/api/office/sheet/range")
def sheet_range():
    d = _body()
    s = oe.get_session(d["sid"])
    return ok(values=s.range_text(int(d.get("sheet", 0)), int(d["r1"]), int(d["c1"]), int(d["r2"]), int(d["c2"]),
                                  raw=bool(d.get("raw"))))


@bp.post("/api/office/sheet/save")
def sheet_save():
    d = _body()
    s = oe.get_session(d["sid"])
    if s.status != "ready":
        raise ValueError("Still loading the workbook. Try again in a moment.")
    src_ext = s.ext
    fmt = (d.get("format") or (src_ext if src_ext in ("xlsx", "xlsm", "csv", "tsv") else "xlsx")).lower().lstrip(".")
    if fmt not in oe.SHEET_SAVE_FORMATS:
        raise ValueError(f"Can't save a spreadsheet as .{fmt}")
    same = fmt == src_ext and fmt in ("xlsx", "xlsm", "csv", "tsv")
    dest = _dest(str(s.path), fmt, d.get("mode", "copy"), _out_dir(d), same)
    out = s.write(fmt, dest, int(d.get("sheet", 0)))
    return ok(path=str(out), name=out.name, sheet=s.meta())


@bp.post("/api/office/sheet/print")
def sheet_print():
    d = _body()
    s = oe.get_session(d["sid"])
    html, notes = s.table_html([s.ws(int(d.get("sheet", 0)))], int(d.get("max_rows", 5000)))
    return ok(html=html, notes=notes)


@bp.post("/api/office/export_copy")
def export_copy():
    """Copy the PDF that PowerPoint made for the slide viewer into the output folder."""
    import shutil
    d = _body()
    src = Path(d.get("path") or "").resolve()
    allowed = (oe.TMP / "office_slides").resolve()
    if allowed not in src.parents or not src.is_file():
        raise PermissionError("Only the slide preview PDF can be exported this way")
    dest = unique_path(_out_dir(d), Path(d.get("name") or src.stem).stem, "pdf")
    shutil.copyfile(src, dest)
    return ok(path=str(dest), name=dest.name)


@bp.post("/api/office/sheet/close")
def sheet_close():
    oe.close_session(_body().get("sid"))
    return ok()
