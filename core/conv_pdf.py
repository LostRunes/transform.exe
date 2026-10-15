"""PDF conversions and tools (PyMuPDF / pdf2docx)."""
from pathlib import Path

import pymupdf as fitz

from .util import parse_ranges


def open_pdf(src, password=None) -> fitz.Document:
    """fitz.open, but with messages people can act on instead of "document closed or encrypted".
    password=None means "must not be locked"; otherwise it's tried on a locked file."""
    try:
        doc = fitz.open(src)
    except fitz.EmptyFileError:
        raise ValueError("This file is empty (0 bytes)") from None
    except (fitz.FileDataError, RuntimeError):
        raise ValueError("This PDF is damaged or isn't really a PDF") from None
    if doc.needs_pass:
        if password is None:
            doc.close()
            raise ValueError("This PDF is password-protected. Use “Remove password” (PDF tools) first.")
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("Wrong password" if password else "Enter the PDF's current password")
    if doc.page_count == 0:
        doc.close()
        raise ValueError("This PDF has no pages (it may be damaged)")
    return doc


def _pages(spec, n: int) -> list[int]:
    """parse_ranges with an explanation instead of a crash or a silently empty result."""
    try:
        pages = parse_ranges(spec, n)
    except ValueError:
        raise ValueError(f"Couldn't read the pages “{spec}”. Use numbers and ranges like 1-3, 5, 8-") from None
    if not pages:
        raise ValueError(f"There's no page “{spec}”: this PDF has {n} page{'' if n == 1 else 's'}")
    return pages


_UNI_FONT = None


def _font_for(page, text: str, base: str):
    """(fontname, width function). The built-in fonts only cover Latin-1, so e.g. CJK or ✓ would print as
    dots; those get MuPDF's Unicode fallback font embedded (subset on save)."""
    global _UNI_FONT
    if all(ord(ch) < 256 for ch in text):
        return base, lambda s, size: fitz.get_text_length(s, fontname=base, fontsize=size)
    _UNI_FONT = _UNI_FONT or fitz.Font("cjk")
    page.insert_font(fontname="F_uni", fontbuffer=_UNI_FONT.buffer)
    return "F_uni", lambda s, size: _UNI_FONT.text_length(s, fontsize=size)


def _save_with_fonts(doc, out):
    try:
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(out, garbage=3, deflate=True)


# ---------------- conversions ----------------

def pdf_to_raster(src: Path, out: Path, params: dict):
    """One image per page. Single-page PDFs give exactly `out`."""
    dpi = max(10, min(1200, int(params.get("dpi") or 150)))
    fmt = out.suffix.lower().lstrip(".")
    outs = []
    with open_pdf(src) as doc:
        pages = _pages(params.get("pages", ""), doc.page_count)
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


NO_TEXT = "This PDF has no selectable text (it's probably a scan or pictures of pages), so there's nothing to extract"


def pdf_to_text(src: Path, out: Path, params: dict):
    with open_pdf(src) as doc:
        text = "\n\n".join(page.get_text("text", sort=True) for page in doc)
    if not text.strip():
        raise ValueError(NO_TEXT)
    out.write_text(text, encoding="utf-8")
    return [out]


def pdf_to_html(src: Path, out: Path, params: dict):
    with open_pdf(src) as doc:
        body = "\n".join(page.get_text("xhtml") for page in doc)
    out.write_text(f"<!doctype html><meta charset='utf-8'><body>{body}</body>", encoding="utf-8")
    return [out]


def pdf_to_md(src: Path, out: Path, params: dict):
    with open_pdf(src) as doc:
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
    if not parts:
        raise ValueError(NO_TEXT)
    out.write_text("\n\n".join(parts), encoding="utf-8")
    return [out]


def pdf_to_docx(src: Path, out: Path, params: dict):
    from pdf2docx import Converter
    open_pdf(src).close()  # clear message for locked / damaged files
    cv = Converter(str(src))
    try:
        cv.convert(str(out))
    finally:
        cv.close()
    return [out]


def html_to_pdf(src: Path, out: Path, params: dict, html: str | None = None):
    """Offline HTML -> PDF using PyMuPDF's Story layout engine."""
    if html is None:
        from .conv_doc import read_text
        html = read_text(src)
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
        try:
            if s.suffix.lower() == ".pdf":
                with open_pdf(s) as d:
                    result.insert_pdf(d)
            else:  # images & other fitz-openable docs get converted on the fly
                with fitz.open(s) as d, fitz.open("pdf", d.convert_to_pdf()) as conv:
                    result.insert_pdf(conv)
        except Exception as e:
            raise ValueError(f"{s.name}: {e}") from None
    result.save(out, garbage=3, deflate=True)
    return [out]


def tool_split(src: Path, out_dir: Path, params: dict, unique):
    outs = []
    with open_pdf(src) as doc:
        mode = params.get("mode", "every")
        n = doc.page_count
        if mode == "every":
            groups = [[i] for i in range(n)]
        elif mode == "chunks":
            k = max(1, int(params.get("chunk") or 2))
            groups = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
        else:  # ranges: "1-3; 4-6; 7-"
            groups = [_pages(g, n) for g in (params.get("ranges") or "").split(";") if g.strip()]
            if not groups:
                raise ValueError("Type the ranges to split out, e.g. 1-3; 4-10; 11-")
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
    with open_pdf(src) as doc:
        action = params.get("action", "extract")
        if action == "delete" and not (params.get("pages") or "").strip():
            raise ValueError("Type the pages to delete, e.g. 2, 5-7")
        spec = _pages(params.get("pages", ""), doc.page_count)
        if action == "delete":
            keep = [i for i in range(doc.page_count) if i not in set(spec)]
            if not keep:
                raise ValueError("That would delete every page")
        else:
            keep = spec
        doc.select(keep)
        out = unique(out_dir, f"{src.stem}_{action}", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


def tool_rotate(src: Path, out_dir: Path, params: dict, unique):
    with open_pdf(src) as doc:
        angle = int(params.get("angle", 90))
        for i in _pages(params.get("pages", ""), doc.page_count):
            p = doc[i]
            p.set_rotation((p.rotation + angle) % 360)
        out = unique(out_dir, src.stem + "_rotated", "pdf")
        doc.save(out, garbage=3, deflate=True)
    return [out]


LEVELS = {"low": (200, 85), "medium": (150, 70), "high": (96, 50), "extreme": (72, 35)}
# Picture resolution / JPEG quality, best first, for size-targeted compression.
LADDER = [(220, 85), (180, 80), (150, 72), (130, 65), (110, 58), (96, 50), (80, 42), (72, 35), (60, 30), (50, 25), (40, 20)]


def _pdf_bytes(src: Path, dpi=None, quality=None) -> bytes:
    """Re-save src with images downsampled to dpi (None = structural clean-up only)."""
    with fitz.open(src) as doc:
        if dpi:
            try:
                doc.rewrite_images(dpi_threshold=dpi + 20, dpi_target=dpi, quality=quality, lossy=True,
                                   lossless=True, bitonal=True, color=True, gray=True)
            except AttributeError:
                pass  # very old PyMuPDF: structural compression only
        try:
            doc.subset_fonts()
        except Exception:
            pass
        doc.scrub(metadata=False, xml_metadata=True, thumbnails=True, reset_fields=False,
                  reset_responses=False, javascript=False, attached_files=False, clean_pages=True,
                  embedded_files=False, hidden_text=False, redactions=False, redact_images=0,
                  remove_links=False)
        return doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1, clean=True)


def _flattened(src: Path, dpi: int, quality: int) -> bytes:
    """Every page becomes one JPEG. Last resort: text stops being selectable."""
    out = fitz.open()
    with fitz.open(src) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes("jpg", jpg_quality=quality))
    data = out.tobytes(garbage=4, deflate=True)
    out.close()
    return data


def tool_compress(src: Path, out_dir: Path, params: dict, ctx, unique):
    from .shrink import already_fits, budget, report, search
    open_pdf(src).close()  # clear message for locked / damaged files
    size = src.stat().st_size
    limit = budget(size, params)
    done = already_fits(src, out_dir, limit, ctx, unique)
    if done:
        return done
    if limit is None:
        data = _pdf_bytes(src, *LEVELS[params.get("level", "medium")])
    else:
        ctx.sub_progress(0.05, f"Repacking {src.name}")
        data = _pdf_bytes(src)
        if len(data) > limit:
            rungs = LADDER[::-1]  # search() wants bigger knob = better quality
            tries = [0]

            def enc(k):
                tries[0] += 1
                ctx.sub_progress(min(0.9, 0.1 + 0.15 * tries[0]), f"Shrinking images in {src.name} (try {tries[0]})")
                return _pdf_bytes(src, *rungs[k])
            hit, smallest = search(enc, 0, len(rungs) - 1, limit)
            data = hit or min(data, smallest, key=len)
        if len(data) > limit and params.get("flatten"):
            ctx.sub_progress(0.9, f"Flattening pages of {src.name}")
            hit, smallest = search(lambda k: _flattened(src, *rungs[k]), 0, len(rungs) - 1, limit)
            data = hit or min(data, smallest, key=len)
    out = unique(out_dir, src.stem + "_compressed", "pdf")
    out.write_bytes(data)
    report(ctx, src.name, size, len(data), limit)
    return [out]


def tool_watermark(src: Path, out_dir: Path, params: dict, unique):
    text = params.get("text") or "CONFIDENTIAL"
    opacity = float(params.get("opacity") or 0.15)
    size = float(params.get("size") or 60)
    color = _hex(params.get("color", "#ff0000"))
    with open_pdf(src) as doc:
        for page in doc:
            r = page.rect  # as displayed; drawing happens in unrotated coordinates, hence the derotation below
            font, width = _font_for(page, text, "hebo")
            tw = width(text, size)
            center = fitz.Point(r.width / 2, r.height / 2)
            mat = fitz.Matrix(-45 if params.get("diagonal", True) else 0)
            page.insert_text(fitz.Point(center.x - tw / 2, center.y + size / 3) * page.derotation_matrix, text,
                             fontsize=size, fontname=font, color=color, fill_opacity=opacity, stroke_opacity=opacity,
                             rotate=page.rotation, morph=(center * page.derotation_matrix, mat), overlay=True)
        out = unique(out_dir, src.stem + "_watermarked", "pdf")
        _save_with_fonts(doc, out)
    return [out]


def tool_page_numbers(src: Path, out_dir: Path, params: dict, unique):
    fmt = params.get("format") or "{n} / {total}"
    pos = params.get("position", "bottom-center")
    size = float(params.get("size") or 10)
    with open_pdf(src) as doc:
        total = doc.page_count
        for i, page in enumerate(doc):
            label = fmt.replace("{n}", str(i + 1)).replace("{total}", str(total))
            r = page.rect  # as displayed (rotation applied)
            font, width = _font_for(page, label, "helv")
            tw = width(label, size)
            y = 28 if pos.startswith("top") else r.height - 20
            x = {"left": 36, "center": (r.width - tw) / 2, "right": r.width - 36 - tw}[pos.split("-")[1]]
            page.insert_text(fitz.Point(x, y) * page.derotation_matrix, label, fontsize=size, fontname=font,
                             color=(0.2, 0.2, 0.2), rotate=page.rotation)
        out = unique(out_dir, src.stem + "_numbered", "pdf")
        _save_with_fonts(doc, out)
    return [out]


def tool_protect(src: Path, out_dir: Path, params: dict, unique):
    pw = params.get("password") or ""
    if not pw:
        raise ValueError("Enter a password")
    with open_pdf(src) as doc:
        out = unique(out_dir, src.stem + "_protected", "pdf")
        doc.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pw, owner_pw=pw,
                 permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_ACCESSIBILITY)
    return [out]


def tool_unlock(src: Path, out_dir: Path, params: dict, unique):
    with open_pdf(src, password=params.get("password") or "") as doc:
        out = unique(out_dir, src.stem + "_unlocked", "pdf")
        doc.save(out, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    return [out]


def tool_extract_images(src: Path, out_dir: Path, params: dict, unique):
    outs = []
    seen = set()
    with open_pdf(src) as doc:
        for pno, page in enumerate(doc):
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                info = doc.extract_image(xref)
                if not info or info["width"] < int(params.get("min_size") or 0):
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
