"""PDF conversions and tools (PyMuPDF / pdf2docx)."""
from pathlib import Path

import pymupdf as fitz

from .util import parse_ranges


# ---------------- conversions ----------------

def pdf_to_raster(src: Path, out: Path, params: dict):
    """One image per page. Single-page PDFs give exactly `out`."""
    dpi = int(params.get("dpi", 150))
    fmt = out.suffix.lower().lstrip(".")
    outs = []
    with fitz.open(src) as doc:
        pages = parse_ranges(params.get("pages", ""), doc.page_count)
        for i in pages:
            pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
            target = out if len(pages) == 1 else out.with_name(f"{out.stem}_p{i + 1}{out.suffix}")
            if fmt in ("png", "jpg", "jpeg", "pnm", "pbm", "ppm", "psd"):
                pix.save(target, jpg_quality=int(params.get("quality", 90))) if fmt in ("jpg", "jpeg") else pix.save(target)
            else:  # hand off to Pillow for webp/tiff/bmp/gif/...
                from .conv_image import save_image
                save_image(pix.pil_image(), target, quality=params.get("quality", 90))
            outs.append(target)
    return outs


def pdf_to_text(src: Path, out: Path, params: dict):
    with fitz.open(src) as doc:
        text = "\n\n".join(page.get_text("text", sort=True) for page in doc)
    out.write_text(text, encoding="utf-8")
    return [out]


def pdf_to_html(src: Path, out: Path, params: dict):
    with fitz.open(src) as doc:
        body = "\n".join(page.get_text("xhtml") for page in doc)
    out.write_text(f"<!doctype html><meta charset='utf-8'><body>{body}</body>", encoding="utf-8")
    return [out]


def pdf_to_md(src: Path, out: Path, params: dict):
    with fitz.open(src) as doc:
        parts = []
        for page in doc:
            for b in page.get_text("dict", sort=True)["blocks"]:
                if b.get("type") != 0:
                    continue
                spans = [s for l in b["lines"] for s in l["spans"]]
                text = " ".join(s["text"].strip() for s in spans if s["text"].strip())
                if not text:
                    continue
                size = max(s["size"] for s in spans)
                bold = all(s["flags"] & 16 for s in spans)
                if size >= 18:
                    parts.append("# " + text)
                elif size >= 14 or (bold and len(text) < 90):
                    parts.append("## " + text)
                else:
                    parts.append(text)
    out.write_text("\n\n".join(parts), encoding="utf-8")
    return [out]


def pdf_to_docx(src: Path, out: Path, params: dict):
    from pdf2docx import Converter
    cv = Converter(str(src))
    try:
        cv.convert(str(out))
    finally:
        cv.close()
    return [out]


def html_to_pdf(src: Path, out: Path, params: dict, html: str | None = None):
    """Offline HTML -> PDF using PyMuPDF's Story layout engine."""
    if html is None:
        html = Path(src).read_text(encoding="utf-8", errors="replace")
    css = ("body{font-family:sans-serif;font-size:11pt;line-height:1.4} table{border-collapse:collapse}"
           " td,th{border:1px solid #999;padding:3px 5px;font-size:9pt} th{background:#eee} pre,code{font-family:monospace}")
    story = fitz.Story(html=html, user_css=css, archive=str(Path(src).parent) if src else None)
    landscape = params.get("orientation") == "landscape"
    mediabox = fitz.paper_rect("a4-l" if landscape else "a4")
    where = mediabox + (40, 40, -40, -40)
    writer = fitz.DocumentWriter(str(out))
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return [out]


# ---------------- tools ----------------

def tool_merge(srcs: list[Path], out: Path, params: dict):
    result = fitz.open()
    for s in srcs:
        if s.suffix.lower() == ".pdf":
            with fitz.open(s) as d:
                result.insert_pdf(d)
        else:  # images & other fitz-openable docs get converted on the fly
            with fitz.open(s) as d:
                result.insert_pdf(fitz.open("pdf", d.convert_to_pdf()))
    result.save(out, garbage=3, deflate=True)
    return [out]


def tool_split(src: Path, out_dir: Path, params: dict, unique):
    outs = []
    with fitz.open(src) as doc:
        mode = params.get("mode", "every")
        n = doc.page_count
        if mode == "every":
            groups = [[i] for i in range(n)]
        elif mode == "chunks":
            k = max(1, int(params.get("chunk", 2)))
            groups = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
        else:  # ranges: "1-3; 4-6; 7-"
            groups = [parse_ranges(g, n) for g in params.get("ranges", "").split(";") if g.strip()]
        for g in groups:
            if not g:
                continue
            part = fitz.open()
            for i in g:
                part.insert_pdf(doc, from_page=i, to_page=i)
            label = f"p{g[0] + 1}" if len(g) == 1 else f"p{g[0] + 1}-{g[-1] + 1}"
            out = unique(out_dir, f"{src.stem}_{label}", "pdf")
            part.save(out, garbage=3, deflate=True)
            outs.append(out)
    return outs


def tool_select_pages(src: Path, out_dir: Path, params: dict, unique):
    """Extract / delete / reorder pages, all with one page-spec."""
    with fitz.open(src) as doc:
        spec = parse_ranges(params.get("pages", ""), doc.page_count)
        action = params.get("action", "extract")
        if action == "delete":
            keep = [i for i in range(doc.page_count) if i not in set(spec)]
        else:
            keep = spec
        doc.select(keep)
        out = unique(out_dir, f"{src.stem}_{action}", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


def tool_rotate(src: Path, out_dir: Path, params: dict, unique):
    with fitz.open(src) as doc:
        angle = int(params.get("angle", 90))
        for i in parse_ranges(params.get("pages", ""), doc.page_count):
            p = doc[i]
            p.set_rotation((p.rotation + angle) % 360)
        out = unique(out_dir, src.stem + "_rotated", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


def tool_compress(src: Path, out_dir: Path, params: dict, unique):
    level = params.get("level", "medium")
    dpi, quality = {"low": (200, 85), "medium": (150, 70), "high": (96, 50), "extreme": (72, 35)}[level]
    with fitz.open(src) as doc:
        try:
            doc.rewrite_images(dpi_threshold=dpi + 20, dpi_target=dpi, quality=quality, lossy=True,
                               lossless=True, bitonal=True, color=True, gray=True)
        except AttributeError:
            pass  # very old PyMuPDF: structural compression only
        doc.subset_fonts()
        doc.scrub(metadata=False, xml_metadata=True, thumbnails=True, reset_fields=False,
                  reset_responses=False, javascript=False, attached_files=False, clean_pages=True,
                  embedded_files=False, hidden_text=False, redactions=False, redact_images=0,
                  remove_links=False)
        out = unique(out_dir, src.stem + "_compressed", "pdf")
        doc.save(out, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1, clean=True)
    return [out]


def tool_watermark(src: Path, out_dir: Path, params: dict, unique):
    text = params.get("text") or "CONFIDENTIAL"
    opacity = float(params.get("opacity", 0.15))
    size = float(params.get("size", 60))
    color = _hex(params.get("color", "#ff0000"))
    with fitz.open(src) as doc:
        for page in doc:
            r = page.rect
            tw = fitz.get_text_length(text, fontname="hebo", fontsize=size)
            center = fitz.Point(r.width / 2, r.height / 2)
            mat = fitz.Matrix(-45 if params.get("diagonal", True) else 0)
            page.insert_text(fitz.Point(center.x - tw / 2, center.y + size / 3), text, fontsize=size,
                             fontname="hebo", color=color, fill_opacity=opacity, stroke_opacity=opacity,
                             morph=(center, mat), overlay=True)
        out = unique(out_dir, src.stem + "_watermarked", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


def tool_page_numbers(src: Path, out_dir: Path, params: dict, unique):
    fmt = params.get("format", "{n} / {total}")
    pos = params.get("position", "bottom-center")
    size = float(params.get("size", 10))
    with fitz.open(src) as doc:
        total = doc.page_count
        for i, page in enumerate(doc):
            label = fmt.replace("{n}", str(i + 1)).replace("{total}", str(total))
            r = page.rect
            tw = fitz.get_text_length(label, fontname="helv", fontsize=size)
            y = 28 if pos.startswith("top") else r.height - 20
            x = {"left": 36, "center": (r.width - tw) / 2, "right": r.width - 36 - tw}[pos.split("-")[1]]
            page.insert_text((x, y), label, fontsize=size, fontname="helv", color=(0.2, 0.2, 0.2))
        out = unique(out_dir, src.stem + "_numbered", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


def tool_protect(src: Path, out_dir: Path, params: dict, unique):
    pw = params.get("password") or ""
    if not pw:
        raise ValueError("Enter a password")
    with fitz.open(src) as doc:
        out = unique(out_dir, src.stem + "_protected", "pdf")
        doc.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pw, owner_pw=pw,
                 permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_ACCESSIBILITY)
    return [out]


def tool_unlock(src: Path, out_dir: Path, params: dict, unique):
    with fitz.open(src) as doc:
        if doc.needs_pass and not doc.authenticate(params.get("password") or ""):
            raise ValueError("Wrong password")
        out = unique(out_dir, src.stem + "_unlocked", "pdf")
        doc.save(out, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    return [out]


def tool_extract_images(src: Path, out_dir: Path, params: dict, unique):
    outs = []
    seen = set()
    with fitz.open(src) as doc:
        for pno, page in enumerate(doc):
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                info = doc.extract_image(xref)
                if not info or info["width"] < int(params.get("min_size", 32)):
                    continue
                out = unique(out_dir, f"{src.stem}_p{pno + 1}_img{xref}", info["ext"])
                out.write_bytes(info["image"])
                outs.append(out)
    if not outs:
        raise ValueError("No embedded images found")
    return outs


def _hex(h: str):
    h = (h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
