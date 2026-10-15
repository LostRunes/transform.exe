"""Build PDFs from an ordered, hand-arranged list of files (the iLovePDF-style organiser).

Each item is {path, rotate, pages}. Items can be images, SVGs, PDFs, or anything the
conversion graph can turn into a PDF (Word, Excel, Markdown…). The output can be one
combined PDF, one PDF per item, or custom groups like "1-3, 4, 5-8".
"""
import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageOps

from . import registry
from .conv_image import RASTER_IN, _flatten
from .util import ext_of, parse_ranges

PAGE_SIZES = {"a4": (595, 842), "letter": (612, 792)}


# ---------------------------------------------------------------- previews

def thumb(path: str, size: int = 320, page: int = 0) -> bytes:
    """PNG preview of an image, SVG or PDF page, longest side = size."""
    ext = registry.norm(ext_of(path))
    if ext in ("pdf", "svg"):
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("Password-protected PDF")
            p = doc[min(page, doc.page_count - 1)]
            z = size / max(p.rect.width, p.rect.height, 1)
            return p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).tobytes("png")
    if ext not in RASTER_IN:
        raise ValueError("No preview for this file type")
    im = ImageOps.exif_transpose(Image.open(path))
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, "PNG")
    return buf.getvalue()


def describe(path: str) -> dict:
    """What the organiser shows under a card: page count for documents, pixels for images."""
    ext = registry.norm(ext_of(path))
    try:
        if ext in ("pdf", "svg"):
            with fitz.open(path) as doc:
                return {"pages": doc.page_count, "locked": bool(doc.needs_pass)}
        if ext in RASTER_IN:
            with Image.open(path) as im:
                w, h = ImageOps.exif_transpose(im).size
            return {"pages": 1, "w": w, "h": h}
    except Exception as e:
        return {"pages": 0, "error": str(e)}
    return {"pages": None, "convertible": bool(registry.find_path(ext, "pdf"))}


# ---------------------------------------------------------------- grouping

def parse_groups(spec: str, n: int, leftovers: str = "each") -> list[list[int]]:
    """'1-3, 4, 5-8' -> [[0,1,2],[3],[4..7]] (each comma part is one PDF).

    Items not mentioned become one PDF each (leftovers="each"), or are left out ("skip")."""
    groups, used = [], set()
    for part in (spec or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        idx = parse_ranges(part, n)
        if not idx:
            raise ValueError(f"“{part}” doesn't match any file (there are {n})")
        groups.append(idx)
        used.update(idx)
    if leftovers == "each":
        rest = [i for i in range(n) if i not in used]
        # keep the PDFs in list order: interleave leftovers where they sit
        singles = [[i] for i in rest]
        groups = sorted(groups + singles, key=lambda g: min(g))
    if not groups:
        raise ValueError("Type which files go together, e.g. 1-3, 4, 5-8")
    return groups


# ---------------------------------------------------------------- building

def _image_page(doc, path: Path, rotate: int, params: dict):
    im = ImageOps.exif_transpose(Image.open(path))
    if getattr(im, "is_animated", False):
        im.seek(0)
    if rotate:
        im = im.rotate(-rotate, expand=True)
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    buf = io.BytesIO()
    if has_alpha and params.get("keep_transparency"):
        im.convert("RGBA").save(buf, "PNG")
    else:
        _flatten(im).save(buf, "JPEG", quality=int(params.get("quality", 92)))
    w, h = im.size
    size = params.get("page_size", "fit")
    margin = float(params.get("margin") or 0)
    if size in PAGE_SIZES:
        pw, ph = PAGE_SIZES[size]
        if w > h:  # landscape photo on a landscape page
            pw, ph = ph, pw
    else:
        pw, ph = w * 72 / 96 + 2 * margin, h * 72 / 96 + 2 * margin
    page = doc.new_page(width=pw, height=ph)
    page.insert_image(fitz.Rect(margin, margin, pw - margin, ph - margin), stream=buf.getvalue(), keep_proportion=True)


def _insert_pdf(doc, src_doc, rotate: int, pages: str):
    if src_doc.needs_pass:
        raise ValueError("is password-protected. Remove the password first (PDF tools → Remove password).")
    want = parse_ranges(pages or "", src_doc.page_count)
    if not want:
        raise ValueError(f"has no pages matching “{pages}”")
    for i in want:
        doc.insert_pdf(src_doc, from_page=i, to_page=i)
        if rotate:
            p = doc[-1]
            p.set_rotation((p.rotation + rotate) % 360)


def _to_pdf_first(path: Path, work: Path, params: dict) -> Path:
    """Run anything else (DOCX, XLSX, MD…) through the conversion graph to a PDF."""
    chain = registry.find_path(ext_of(path), "pdf")
    if not chain:
        raise ValueError("can't be turned into a PDF")
    current = [path]
    for n, (_a, b, fn, needs_ctx) in enumerate(chain):
        step = work / f"step{n}"
        step.mkdir(parents=True, exist_ok=True)
        nxt = []
        for f in current:
            o = step / f"{path.stem}.{b}"
            nxt += fn(f, o, params, None) if needs_ctx else fn(f, o, params)
        current = nxt
    return Path(current[0])


def build(items: list[dict], out: Path, params: dict, work: Path, progress=None):
    doc = fitz.open()
    for k, it in enumerate(items):
        path = Path(it["path"])
        if progress:
            progress(k / max(1, len(items)), f"Adding {path.name}")
        ext = registry.norm(ext_of(path))
        rotate = int(it.get("rotate") or 0) % 360
        try:
            if ext in RASTER_IN:
                _image_page(doc, path, rotate, params)
            elif ext in ("pdf", "svg"):
                with fitz.open(path) as src:
                    if ext == "svg":
                        src = fitz.open("pdf", src.convert_to_pdf())
                    _insert_pdf(doc, src, rotate, it.get("pages", ""))
            else:
                with fitz.open(_to_pdf_first(path, work / f"conv{k}", params)) as src:
                    _insert_pdf(doc, src, rotate, it.get("pages", ""))
        except ValueError as e:
            raise ValueError(f"{path.name} {e}" if str(e)[:1].islower() else f"{path.name}: {e}") from None
    if not doc.page_count:
        raise ValueError("Nothing to put in the PDF")
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    return out


def group_name(items: list[dict], group: list[int], total_groups: int, base: str) -> str:
    first = Path(items[group[0]]["path"]).stem
    if base:
        return base if total_groups == 1 else f"{base} {group[0] + 1}" + (f"-{group[-1] + 1}" if len(group) > 1 else "")
    if len(group) == 1:
        return first
    return f"{first} + {len(group) - 1} more"
