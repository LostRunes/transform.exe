"""Backend for the visual PDF editor.

The browser works in *display* coordinates (the page as you see it, in PDF points, rotation applied).
PyMuPDF's drawing/redaction APIs use unrotated page coordinates, so we convert with the page's
derotation matrix on the way in and the rotation matrix on the way out."""
import base64
import os
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz

from .conv_pdf import open_pdf

FONT_DIR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
FONT_FILES = {  # (family, bold) -> windows TTF (full Unicode); base-14 fallback otherwise
    ("sans", False): ("arial.ttf", "helv"), ("sans", True): ("arialbd.ttf", "hebo"),
    ("serif", False): ("times.ttf", "tiro"), ("serif", True): ("timesbd.ttf", "tibo"),
    ("mono", False): ("cour.ttf", "cour"), ("mono", True): ("courbd.ttf", "cobo"),
}


@lru_cache(maxsize=None)
def _glyphs(spec: str) -> fitz.Font:
    return fitz.Font(fontfile=spec) if spec.endswith(".ttf") else fitz.Font(spec)


def _font(page, family, bold, text=""):
    ttf, base = FONT_FILES.get((family, bool(bold)), FONT_FILES[("sans", False)])
    path = FONT_DIR / ttf
    f = {"fontname": f"F_{family}_{int(bool(bold))}", "fontfile": str(path)} if path.exists() else {"fontname": base}
    font = _glyphs(str(path) if path.exists() else base)
    if any(not font.has_glyph(ord(ch)) for ch in text if not ch.isspace()):
        # e.g. Japanese, Chinese, ✓: Arial/Times have no glyphs for them and they'd come out blank.
        # MuPDF's built-in fallback font covers them (and Latin), and is subset on save.
        page.insert_font(fontname="F_fallback", fontbuffer=_glyphs("cjk").buffer)
        return {"fontname": "F_fallback"}
    return f


def _rgb(h):
    if h is None or h == "" or h == "none":
        return None
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def info(path: str):
    with open_pdf(path) as doc:  # explains locked / empty / damaged files
        return {"pages": [{"w": p.rect.width, "h": p.rect.height} for p in doc], "count": doc.page_count}


def render(path: str, page: int, zoom: float) -> bytes:
    with open_pdf(path) as doc:
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
        return pix.tobytes("png")


def thumb(path: str, page: int) -> bytes:
    with open_pdf(path) as doc:
        p = doc[page]
        z = 140 / max(p.rect.width, 1)
        return p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).tobytes("png")


def text_lines(path: str, page: int):
    """Editable text lines on a page, in display coordinates."""
    out = []
    with open_pdf(path) as doc:
        p = doc[page]
        rot = p.rotation_matrix
        d = p.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                if line.get("dir", (1, 0)) != (1, 0) and abs(line["dir"][1]) > 0.01:
                    continue  # skip rotated/vertical text lines
                bbox = fitz.Rect(line["bbox"])
                s0 = spans[0]
                font = s0["font"].lower()
                family = "mono" if ("cour" in font or "mono" in font) else \
                         "serif" if ("times" in font or "serif" in font and "sans" not in font or "georgia" in font) else "sans"
                out.append({
                    "ubbox": list(bbox),
                    "bbox": list(bbox * rot),
                    "text": "".join(s["text"] for s in line["spans"]),
                    "size": round(s0["size"], 2),
                    "color": "#%06x" % s0["color"],
                    "bold": bool(s0["flags"] & 16) or "bold" in font,
                    "italic": bool(s0["flags"] & 2),
                    "family": family,
                    "uorigin": list(s0["origin"]),
                })
    return out


def _to_u(page, x, y):
    return fitz.Point(x, y) * page.derotation_matrix


def _rect_u(page, r):
    x0, y0, x1, y1 = r
    return fitz.Rect(_to_u(page, x0, y0), _to_u(page, x1, y1)).normalize()


def apply_edits(src: str, out: str, edits: list[dict]):
    with open_pdf(src) as doc:  # always closed, so a failed save never leaves the original locked
        _apply(doc, edits)
        try:
            doc.subset_fonts()  # embedded TTFs shrink from ~1 MB each to just the glyphs used
        except Exception:
            pass
        doc.save(out, garbage=3, deflate=True)
    return [Path(out)]


def _apply(doc, edits: list[dict]):
    by_page: dict[int, list] = {}
    for e in edits:
        by_page.setdefault(int(e["page"]), []).append(e)

    for pno, items in by_page.items():
        if not 0 <= pno < doc.page_count:
            raise ValueError(f"There are edits for page {pno + 1}, but this PDF has {doc.page_count} pages")
        page = doc[pno]
        rot = page.rotation

        # 1) text replacement / deletion: remove the original glyphs first (keeps images & vector art)
        redactions = [e for e in items if e["type"] in ("replace", "delete_text")]
        for e in redactions:
            r = fitz.Rect(e["ubbox"])
            page.add_redact_annot(r + (-0.5, -0.5, 0.5, 0.5), fill=False)
        if redactions:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
        for e in items:
            if e["type"] == "replace" and e.get("text", "").strip():
                f = _font(page, e.get("family", "sans"), e.get("bold"), e["text"])
                page.insert_text(fitz.Point(e["uorigin"]), e["text"], fontsize=float(e["size"]),
                                 color=_rgb(e.get("color", "#000000")), **f)  # same direction as the original line

        # 2) everything drawn on top
        for e in items:
            t = e["type"]
            stroke = _rgb(e.get("stroke", "#000000"))
            fill = _rgb(e.get("fill"))
            width = float(e.get("width", 2))
            opacity = float(e.get("opacity", 1))
            if t == "text":
                f = _font(page, e.get("family", "sans"), e.get("bold"), e["text"])
                size = float(e.get("size", 14))
                lines = e["text"].split("\n")
                for i, line in enumerate(lines):
                    # (x, y) is the top-left of the box (CSS line-height 1.2): baseline ≈ top + size
                    origin = _to_u(page, e["x"], e["y"] + size * (1.0 + 1.2 * i))
                    page.insert_text(origin, line, fontsize=size, color=_rgb(e.get("color", "#000000")),
                                     rotate=rot, fill_opacity=opacity, **f)
            elif t == "whiteout":
                page.draw_rect(_rect_u(page, e["rect"]), color=None, fill=_rgb(e.get("fill", "#ffffff")), overlay=True)
            elif t == "rect":
                page.draw_rect(_rect_u(page, e["rect"]), color=stroke, fill=fill, width=width,
                               stroke_opacity=opacity, fill_opacity=opacity)
            elif t == "ellipse":
                page.draw_oval(_rect_u(page, e["rect"]), color=stroke, fill=fill, width=width,
                               stroke_opacity=opacity, fill_opacity=opacity)
            elif t == "highlight":
                page.draw_rect(_rect_u(page, e["rect"]), color=None, fill=_rgb(e.get("fill", "#ffeb3b")),
                               fill_opacity=0.4, overlay=True)
            elif t in ("line", "arrow"):
                p1, p2 = _to_u(page, *e["p1"]), _to_u(page, *e["p2"])
                page.draw_line(p1, p2, color=stroke, width=width, stroke_opacity=opacity)
                if t == "arrow":
                    import math
                    ang = math.atan2(p2.y - p1.y, p2.x - p1.x)
                    head = max(8, width * 4)
                    for da in (math.pi * 0.85, -math.pi * 0.85):
                        q = fitz.Point(p2.x + head * math.cos(ang + da), p2.y + head * math.sin(ang + da))
                        page.draw_line(p2, q, color=stroke, width=width, stroke_opacity=opacity)
            elif t == "pen":
                pts = [_to_u(page, x, y) for x, y in e["points"]]
                if len(pts) > 1:
                    page.draw_polyline(pts, color=stroke, width=width, stroke_opacity=opacity, closePath=False)
            elif t == "image":
                data = e["data"].split(",", 1)[1] if "," in e["data"] else e["data"]
                page.insert_image(_rect_u(page, e["rect"]), stream=base64.b64decode(data), keep_proportion=False,
                                  rotate=-rot % 360 if rot else 0, overlay=True)
