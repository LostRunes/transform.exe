"""Docs & sheets editor backend.

Documents: DOCX <-> HTML converters (python-docx + raw WordprocessingML), plus TXT / MD / HTML / ODT / DOC / RTF
(the last three through Word when it's installed). The browser edits HTML; saving rebuilds the DOCX from that HTML,
using the original file as the template so page setup, headers/footers and style definitions survive.

Spreadsheets: see SheetSession below. The loaded openpyxl workbook stays in memory and every edit is applied to it
directly, so saving writes a copy of the original workbook with only the touched cells changed."""
from __future__ import annotations

import base64
import copy
import csv
import datetime as dt
import html as htmllib
import io
import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

from .util import TMP, ext_of, unique_path

DOC_EXTS = {"docx", "docm", "dotx", "doc", "rtf", "odt", "txt", "md", "markdown", "html", "htm"}
SHEET_EXTS = {"xlsx", "xlsm", "xltx", "xls", "ods", "csv", "tsv"}
SLIDE_EXTS = {"pptx", "ppt", "pptm", "pps", "ppsx", "odp"}
PDF_EXTS = {"pdf"}


def kind_of(path) -> str:
    e = ext_of(path)
    if e in DOC_EXTS:
        return "doc"
    if e in SHEET_EXTS:
        return "sheet"
    if e in SLIDE_EXTS:
        return "slides"
    if e in PDF_EXTS:
        return "pdf"
    return "unsupported"


def _office():
    from . import conv_doc
    return conv_doc


def _replace_into(tmp: Path, dest: Path):
    """Move a finished temp file onto dest; explains the usual 'file is open in Word/Excel' failure."""
    try:
        os.replace(tmp, dest)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise PermissionError(f"Couldn't write {dest.name}: it's probably open in another program. Close it and try again.")


# =====================================================================================================================
# DOCX -> HTML
# =====================================================================================================================
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "v": "urn:schemas-microsoft-com:vml",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}


def _q(tag: str) -> str:
    p, t = tag.split(":")
    return f"{{{NS[p]}}}{t}"


def _local(el) -> str:
    t = el.tag
    return t.split("}")[-1] if isinstance(t, str) else ""


def _wval(el, name="val"):
    return None if el is None else el.get(_q("w:" + name))


def _on(el) -> bool:
    """WordprocessingML toggle property (<w:b/>, <w:b w:val="0"/>…)."""
    if el is None:
        return False
    v = _wval(el)
    return v is None or v.lower() not in ("0", "false", "off", "none")


HIGHLIGHT = {"yellow": "#ffff00", "green": "#00ff00", "cyan": "#00ffff", "magenta": "#ff00ff", "blue": "#0000ff",
             "red": "#ff0000", "darkBlue": "#000080", "darkCyan": "#008080", "darkGreen": "#008000",
             "darkMagenta": "#800080", "darkRed": "#800000", "darkYellow": "#808000", "darkGray": "#808080",
             "lightGray": "#c0c0c0", "black": "#000000", "white": "#ffffff"}
HIGHLIGHT_BY_HEX = {v: k for k, v in HIGHLIGHT.items()}
ALIGN_IN = {"center": "center", "right": "right", "end": "right", "both": "justify", "distribute": "justify",
            "left": "left", "start": "left"}
EMU_PER_PX = 9525
PB = "\x00PB\x00"   # page-break sentinel inside a paragraph's html


def _esc(s: str) -> str:
    return htmllib.escape(s, quote=False)


def _attr(s: str) -> str:
    return htmllib.escape(s, quote=True)


class DocxReader:
    def __init__(self, path):
        import docx
        self.doc = docx.Document(str(path))
        self.part = self.doc.part
        self.styles = self._read_styles()
        self.numbering = self._read_numbering()

    # ---------------- styles & numbering
    def _read_styles(self):
        out = {}
        root = self.doc.styles.element
        for st in root.findall(_q("w:style")):
            sid = st.get(_q("w:styleId"))
            name = _wval(st.find(_q("w:name"))) or sid or ""
            ppr = st.find(_q("w:pPr"))
            num = None
            jc = None
            if ppr is not None:
                npr = ppr.find(_q("w:numPr"))
                if npr is not None:
                    num = (_wval(npr.find(_q("w:numId"))), int(_wval(npr.find(_q("w:ilvl"))) or 0))
                jc = _wval(ppr.find(_q("w:jc")))
            rpr = st.find(_q("w:rPr"))
            out[sid] = {"name": name, "lname": name.lower(), "based": _wval(st.find(_q("w:basedOn"))), "num": num,
                        "jc": jc, "type": st.get(_q("w:type")), "rpr": rpr}
        return out

    def _style_chain(self, sid):
        seen = []
        while sid and sid in self.styles and sid not in seen:
            seen.append(sid)
            sid = self.styles[sid]["based"]
        return [self.styles[s] for s in seen]

    def _read_numbering(self):
        nums = {}
        try:
            root = self.part.numbering_part.element
        except Exception:
            return nums
        abstract = {}
        for an in root.findall(_q("w:abstractNum")):
            lv = {}
            for l in an.findall(_q("w:lvl")):
                lv[int(l.get(_q("w:ilvl")) or 0)] = _wval(l.find(_q("w:numFmt"))) or "decimal"
            abstract[an.get(_q("w:abstractNumId"))] = lv
        for n in root.findall(_q("w:num")):
            nid = n.get(_q("w:numId"))
            aid = _wval(n.find(_q("w:abstractNumId")))
            nums[nid] = abstract.get(aid, {})
        return nums

    def default_font(self):
        """(family, size_pt) from docDefaults / Normal / theme."""
        family, size = None, None
        root = self.doc.styles.element
        rpr = root.find(f"{_q('w:docDefaults')}/{_q('w:rPrDefault')}/{_q('w:rPr')}")
        theme_font = None
        for r in [rpr] + [s["rpr"] for s in self._style_chain("Normal") if s["rpr"] is not None][::-1]:
            if r is None:
                continue
            f = r.find(_q("w:rFonts"))
            if f is not None:
                family = f.get(_q("w:ascii")) or family
                if f.get(_q("w:asciiTheme")):
                    theme_font = f.get(_q("w:asciiTheme"))
            sz = _wval(r.find(_q("w:sz")))
            if sz:
                size = int(sz) / 2
        if not family and theme_font:
            family = self._theme_font("major" if "major" in theme_font.lower() else "minor")
        return family or "Calibri", size or 11

    def _theme_font(self, which):
        try:
            for rel in self.part.rels.values():
                if rel.reltype.endswith("/theme"):
                    from lxml import etree
                    root = etree.fromstring(rel.target_part.blob)
                    el = root.find(f".//{{{NS['a']}}}{which}Font/{{{NS['a']}}}latin")
                    if el is not None:
                        return el.get("typeface")
        except Exception:
            pass
        return None

    def page(self):
        try:
            s = self.doc.sections[-1]
            pt = lambda v, d: round(v / 12700, 1) if v is not None else d
            return {"w": pt(s.page_width, 612), "h": pt(s.page_height, 792), "mt": pt(s.top_margin, 72),
                    "mb": pt(s.bottom_margin, 72), "ml": pt(s.left_margin, 72), "mr": pt(s.right_margin, 72)}
        except Exception:
            return {"w": 612, "h": 792, "mt": 72, "mb": 72, "ml": 72, "mr": 72}

    # ---------------- body
    def to_html(self) -> str:
        return self._blocks(self.doc.element.body)

    def _blocks(self, parent) -> str:
        items = []  # ("p", html, (tag, level) | None) / ("x", html)
        self._collect(parent, items)
        return self._assemble(items)

    def _collect(self, parent, items):
        for ch in parent.iterchildren():
            t = _local(ch)
            if t == "p":
                items.extend(self._para(ch))
            elif t == "tbl":
                items.append(("x", self._table(ch), None))
            elif t in ("sdt",):
                c = ch.find(_q("w:sdtContent"))
                if c is not None:
                    self._collect(c, items)
            elif t in ("customXml", "ins", "smartTag"):
                self._collect(ch, items)

    def _assemble(self, items) -> str:
        out, stack = [], []  # stack of [tag, level]
        for kind, html, li in items:
            if li is None:
                while stack:
                    out.append(f"</li></{stack.pop()[0]}>")
                out.append(html)
                continue
            tag, lvl, li_st = li
            while stack and stack[-1][1] > lvl:
                out.append(f"</li></{stack.pop()[0]}>")
            if stack and stack[-1][1] == lvl and stack[-1][0] != tag:
                out.append(f"</li></{stack.pop()[0]}>")
            if not stack or stack[-1][1] < lvl:
                out.append(f"<{tag}><li{li_st}>")
                stack.append([tag, lvl])
            else:
                out.append(f"</li><li{li_st}>")
            out.append(html)
        while stack:
            out.append(f"</li></{stack.pop()[0]}>")
        return "".join(out)

    def _para(self, p):
        ppr = p.find(_q("w:pPr"))
        sid = _wval(ppr.find(_q("w:pStyle"))) if ppr is not None else None
        sid = sid or "Normal"
        chain = self._style_chain(sid)
        names = [s["lname"] for s in chain]
        tag, cls = "p", ""
        for n in names:
            m = re.match(r"heading (\d)", n)
            if m:
                tag = "h" + str(min(int(m.group(1)), 6))
                break
            if n == "title":
                tag, cls = "h1", "title"
                break
            if n == "subtitle":
                tag, cls = "h2", "subtitle"
                break
            if "quote" in n:
                tag = "blockquote"
                break
            if n in ("code", "html preformatted", "macro text", "source code", "code block", "plain text"):
                tag = "pre"
                break
        styles = []
        jc = _wval(ppr.find(_q("w:jc"))) if ppr is not None else None
        if not jc:
            jc = next((s["jc"] for s in chain if s["jc"]), None)
        if jc and ALIGN_IN.get(jc, "left") != "left":
            styles.append(f"text-align:{ALIGN_IN[jc]}")
        # list?
        li = None
        num = None
        if ppr is not None and ppr.find(_q("w:numPr")) is not None:
            npr = ppr.find(_q("w:numPr"))
            nid = _wval(npr.find(_q("w:numId")))
            lvl = int(_wval(npr.find(_q("w:ilvl"))) or 0)
            if nid and nid != "0":
                num = (nid, lvl)
        else:
            num = next((s["num"] for s in chain if s["num"]), None)
            if num is None:
                m = next((re.match(r"list (bullet|number)(?: (\d))?$", n) for n in names if re.match(r"list (bullet|number)", n)), None)
                if m:
                    li = ("ul" if m.group(1) == "bullet" else "ol", int(m.group(2) or 1) - 1)
        if num:
            fmt = self.numbering.get(num[0], {}).get(num[1], "bullet")
            lvl = num[1]
            # "List Bullet 2"-style paragraphs carry their depth in the style name, not in ilvl
            m = next((re.match(r"list (?:bullet|number|continue)? ?(\d)$", n) for n in names if re.match(r"list (?:bullet|number|continue)? ?(\d)$", n)), None)
            if m and lvl == 0:
                lvl = int(m.group(1)) - 1
            li = ("ul" if fmt in ("bullet", "none") else "ol", lvl)
        if li is None and ppr is not None:
            ind = ppr.find(_q("w:ind"))
            left = _wval(ind, "left") or _wval(ind, "start") if ind is not None else None
            if left and left.lstrip("-").isdigit() and int(left) > 0:
                styles.append(f"margin-left:{int(left) / 20:g}pt")
        page_before = ppr is not None and _on(ppr.find(_q("w:pageBreakBefore")))
        is_hr = False
        if ppr is not None:
            bdr = ppr.find(_q("w:pBdr"))
            if bdr is not None and bdr.find(_q("w:bottom")) is not None:
                is_hr = True
        inner = self._inline(p)
        if tag == "pre":
            inner = inner.replace("<br>", "\n")
        out = []
        if page_before:
            out.append(("x", '<div class="page-break" contenteditable="false"></div>', None))
        text_only = re.sub(r"<[^>]+>", "", inner.replace(PB, "")).strip()
        if is_hr and not text_only and "<img" not in inner:
            out.append(("x", "<hr>", None))
            return out
        st = f' style="{";".join(styles)}"' if styles else ""
        cl = f' class="{cls}"' if cls else ""
        parts = inner.split(PB)
        for i, part in enumerate(parts):
            if i:
                out.append(("x", '<div class="page-break" contenteditable="false"></div>', None))
            empty = not re.sub(r"<[^>]+>", "", part).strip() and "<img" not in part
            if empty and len(parts) > 1:
                continue
            body = part if not empty else "<br>"
            if li:
                out.append(("p", body, (li[0], li[1], st)))
            else:
                out.append(("p", f"<{tag}{cl}{st}>{body}</{tag}>", None))
        return out

    # ---------------- runs
    def _inline(self, el) -> str:
        segs = []  # list of (fmt_key_tuple, href, html)
        self._walk_inline(el, segs, None)
        # merge adjacent segments with identical formatting and link
        merged = []
        for fmt, href, html in segs:
            if merged and merged[-1][0] == fmt and merged[-1][1] == href and html != PB and merged[-1][2] != PB:
                merged[-1][2] += html
            else:
                merged.append([fmt, href, html])
        out = []
        i = 0
        while i < len(merged):
            fmt, href, html = merged[i]
            if href:
                group = []
                while i < len(merged) and merged[i][1] == href:
                    # the link look (blue + underline) comes from the <a>; don't bake it into spans
                    f = tuple((k, v) for k, v in merged[i][0] if k != "u" and not (k == "color" and v in ("#0563c1", "#0000ff")))
                    group.append(self._wrap(f, merged[i][2]))
                    i += 1
                out.append(f'<a href="{_attr(href)}">{"".join(group)}</a>')
                continue
            out.append(html if html == PB else self._wrap(fmt, html))
            i += 1
        return "".join(out)

    def _walk_inline(self, el, segs, href):
        for ch in el.iterchildren():
            t = _local(ch)
            if t == "r":
                self._run(ch, segs, href)
            elif t == "hyperlink":
                link = href
                rid = ch.get(_q("r:id"))
                if rid and rid in self.part.rels:
                    link = self.part.rels[rid].target_ref
                elif ch.get(_q("w:anchor")):
                    link = "#" + ch.get(_q("w:anchor"))
                self._walk_inline(ch, segs, link)
            elif t in ("ins", "smartTag", "customXml", "fldSimple", "sdtContent", "dir", "bdo"):
                self._walk_inline(ch, segs, href)
            elif t == "sdt":
                c = ch.find(_q("w:sdtContent"))
                if c is not None:
                    self._walk_inline(c, segs, href)

    def _run_fmt(self, r):
        rpr = r.find(_q("w:rPr"))
        f = {}
        if rpr is None:
            return ()
        rs = _wval(rpr.find(_q("w:rStyle")))
        if rs:
            ln = self.styles.get(rs, {}).get("lname", rs.lower())
            if ln in ("strong",):
                f["b"] = 1
            if ln in ("emphasis",):
                f["i"] = 1
            srpr = self.styles.get(rs, {}).get("rpr")
            if srpr is not None:
                self._rpr_into(srpr, f)
        self._rpr_into(rpr, f)
        return tuple(sorted(f.items()))

    def _rpr_into(self, rpr, f):
        for tag, key in (("b", "b"), ("i", "i"), ("strike", "s"), ("dstrike", "s")):
            el = rpr.find(_q("w:" + tag))
            if el is not None:
                if _on(el):
                    f[key] = 1
                else:
                    f.pop(key, None)
        u = rpr.find(_q("w:u"))
        if u is not None:
            if (_wval(u) or "single") != "none":
                f["u"] = 1
            else:
                f.pop("u", None)
        va = _wval(rpr.find(_q("w:vertAlign")))
        if va in ("superscript", "subscript"):
            f["va"] = "sup" if va == "superscript" else "sub"
        sz = _wval(rpr.find(_q("w:sz")))
        if sz and sz.isdigit():
            f["sz"] = int(sz) / 2
        col = _wval(rpr.find(_q("w:color")))
        if col and col.lower() != "auto" and re.fullmatch(r"[0-9A-Fa-f]{6}", col):
            f["color"] = "#" + col.lower()
        hl = _wval(rpr.find(_q("w:highlight")))
        if hl and hl in HIGHLIGHT:
            f["bg"] = HIGHLIGHT[hl]
        shd = rpr.find(_q("w:shd"))
        if shd is not None and "bg" not in f:
            fill = _wval(shd, "fill")
            if fill and re.fullmatch(r"[0-9A-Fa-f]{6}", fill):
                f["bg"] = "#" + fill.lower()
        fonts = rpr.find(_q("w:rFonts"))
        if fonts is not None and fonts.get(_q("w:ascii")):
            f["font"] = fonts.get(_q("w:ascii"))

    @staticmethod
    def _wrap(fmt, html):
        if not html:
            return ""
        d = dict(fmt)
        css = []
        if "font" in d:
            css.append(f"font-family:{_attr(d['font'])}")
        if "sz" in d:
            css.append(f"font-size:{d['sz']:g}pt")
        if "color" in d:
            css.append(f"color:{d['color']}")
        if "bg" in d:
            css.append(f"background-color:{d['bg']}")
        if css:
            html = f'<span style="{";".join(css)}">{html}</span>'
        for k, tag in (("va", None), ("s", "s"), ("u", "u"), ("i", "i"), ("b", "b")):
            if k == "va" and "va" in d:
                html = f"<{d['va']}>{html}</{d['va']}>"
            elif tag and d.get(k):
                html = f"<{tag}>{html}</{tag}>"
        return html

    def _run(self, r, segs, href):
        fmt = self._run_fmt(r)
        for ch in r.iterchildren():
            t = _local(ch)
            if t in ("t", "delText") and t == "t":
                txt = ch.text or ""
                html = _esc(txt).replace("\t", '<span class="tab">\t</span>')
                # keep runs of spaces visible in the browser
                html = re.sub(r"  +", lambda m: " " + "&nbsp;" * (len(m.group()) - 1), html)
                segs.append((fmt, href, html))
            elif t == "tab":
                segs.append((fmt, href, '<span class="tab">\t</span>'))
            elif t in ("br", "cr"):
                if _wval(ch, "type") == "page":
                    segs.append(((), None, PB))
                else:
                    segs.append((fmt, href, "<br>"))
            elif t == "noBreakHyphen":
                segs.append((fmt, href, "-"))
            elif t == "sym":
                code = _wval(ch, "char")
                try:
                    segs.append((fmt, href, _esc(chr(int(code, 16)))))
                except Exception:
                    pass
            elif t == "drawing":
                for blip in ch.iter(_q("a:blip")):
                    rid = blip.get(_q("r:embed")) or blip.get(_q("r:link"))
                    ext = next(ch.iter(_q("wp:extent")), None)
                    w = int(ext.get("cx")) / EMU_PER_PX if ext is not None else None
                    hgt = int(ext.get("cy")) / EMU_PER_PX if ext is not None else None
                    img = self._img(rid, w, hgt)
                    if img:
                        segs.append(((), href, img))
            elif t == "pict" or t == "object":
                for im in ch.iter(_q("v:imagedata")):
                    img = self._img(im.get(_q("r:id")), None, None)
                    if img:
                        segs.append(((), href, img))

    def _img(self, rid, w, hgt):
        if not rid or rid not in self.part.rels:
            return ""
        rel = self.part.rels[rid]
        if rel.is_external:
            return ""
        part = rel.target_part
        ct = part.content_type or "image/png"
        blob = part.blob
        if ct in ("image/x-emf", "image/x-wmf", "image/emf", "image/wmf", "image/tiff"):
            try:  # browsers can't show these; convert to PNG (Pillow handles WMF/EMF on Windows)
                from PIL import Image
                im = Image.open(io.BytesIO(blob))
                buf = io.BytesIO()
                im.save(buf, "PNG")
                blob, ct = buf.getvalue(), "image/png"
            except Exception:
                pass
        src = f"data:{ct};base64," + base64.b64encode(blob).decode()
        size = f' style="width:{w:.0f}px;height:{hgt:.0f}px"' if w and hgt else ""
        return f'<img src="{src}"{size}>'

    # ---------------- tables
    def _table(self, tbl) -> str:
        rows = []
        for tr in tbl.findall(_q("w:tr")):
            cells, col = [], 0
            trpr = tr.find(_q("w:trPr"))
            gb = trpr.find(_q("w:gridBefore")) if trpr is not None else None
            if gb is not None:
                col += int(_wval(gb) or 0)
            tcs = []
            for ch in tr.iterchildren():
                if _local(ch) == "tc":
                    tcs.append(ch)
                elif _local(ch) == "sdt":
                    c = ch.find(_q("w:sdtContent"))
                    if c is not None:
                        tcs += c.findall(_q("w:tc"))
            header = trpr is not None and trpr.find(_q("w:tblHeader")) is not None
            for tc in tcs:
                tcpr = tc.find(_q("w:tcPr"))
                span, vm, bg = 1, None, None
                if tcpr is not None:
                    gs = tcpr.find(_q("w:gridSpan"))
                    span = int(_wval(gs) or 1) if gs is not None else 1
                    v = tcpr.find(_q("w:vMerge"))
                    if v is not None:
                        vm = "restart" if _wval(v) == "restart" else "continue"
                    shd = tcpr.find(_q("w:shd"))
                    fill = _wval(shd, "fill") if shd is not None else None
                    if fill and re.fullmatch(r"[0-9A-Fa-f]{6}", fill) and fill.lower() != "ffffff":
                        bg = "#" + fill.lower()
                cells.append({"col": col, "span": span, "vm": vm, "tc": tc, "bg": bg, "th": header})
                col += span
            rows.append(cells)
        # rowspans from vertical merges
        for ri, cells in enumerate(rows):
            for c in cells:
                c["rowspan"] = 1
                if c["vm"] == "restart":
                    n = 1
                    for nxt in rows[ri + 1:]:
                        m = next((x for x in nxt if x["col"] == c["col"]), None)
                        if m is not None and m["vm"] == "continue":
                            n += 1
                        else:
                            break
                    c["rowspan"] = n
        out = ["<table><tbody>"]
        for cells in rows:
            out.append("<tr>")
            for c in cells:
                if c["vm"] == "continue":
                    continue
                attrs = ""
                if c["span"] > 1:
                    attrs += f' colspan="{c["span"]}"'
                if c["rowspan"] > 1:
                    attrs += f' rowspan="{c["rowspan"]}"'
                if c["bg"]:
                    attrs += f' style="background-color:{c["bg"]}"'
                tag = "th" if c["th"] else "td"
                inner = self._blocks(c["tc"]) or "<p><br></p>"
                out.append(f"<{tag}{attrs}>{inner}</{tag}>")
            out.append("</tr>")
        out.append("</tbody></table>")
        return "".join(out)


def docx_to_html(path) -> dict:
    rd = DocxReader(path)
    fam, size = rd.default_font()
    return {"html": rd.to_html() or "<p><br></p>", "page": rd.page(), "font": {"family": fam, "size": size}}


# =====================================================================================================================
# HTML -> DOCX
# =====================================================================================================================
BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "ul", "ol", "li", "table", "hr",
              "section", "article", "header", "footer", "main", "aside", "nav", "figure", "figcaption", "address",
              "center", "dl", "dt", "dd", "form", "fieldset", "details", "summary", "body", "html"}
SKIP_TAGS = {"script", "style", "head", "title", "meta", "link", "noscript", "template", "iframe", "object", "embed",
             "button", "input", "select", "textarea", "svg", "canvas", "video", "audio"}
HEADING_STYLE = {f"h{i}": f"Heading {i}" for i in range(1, 7)}


def parse_html(html: str):
    import lxml.html
    html = (html or "").replace("​", "")
    root = lxml.html.fromstring(f"<div>{html}</div>") if html.strip() else lxml.html.fromstring("<div></div>")
    body = root.find(".//body")
    return body if body is not None else root


def _css(el) -> dict:
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _color(v):
    """CSS colour -> 'RRGGBB' or None."""
    if not v:
        return None
    v = v.strip().lower()
    named = {"black": "000000", "white": "ffffff", "red": "ff0000", "green": "008000", "blue": "0000ff",
             "yellow": "ffff00", "gray": "808080", "grey": "808080", "orange": "ffa500", "purple": "800080",
             "navy": "000080", "teal": "008080", "maroon": "800000", "silver": "c0c0c0", "lime": "00ff00",
             "aqua": "00ffff", "cyan": "00ffff", "magenta": "ff00ff", "fuchsia": "ff00ff", "olive": "808000"}
    if v in named:
        return named[v]
    m = re.fullmatch(r"#([0-9a-f]{3})", v)
    if m:
        return "".join(c * 2 for c in m.group(1))
    m = re.fullmatch(r"#([0-9a-f]{6})([0-9a-f]{2})?", v)
    if m:
        return m.group(1)
    m = re.fullmatch(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+%?))?\s*\)", v)
    if m:
        if m.group(4) not in (None, "1", "100%") and float(m.group(4).rstrip("%")) == 0:
            return None  # fully transparent
        return "".join(f"{min(255, int(x)):02x}" for x in m.group(1, 2, 3))
    return None


def _length_pt(v, base=12.0):
    if not v:
        return None
    v = v.strip().lower()
    m = re.fullmatch(r"(-?[\d.]+)\s*(pt|px|em|rem|%|in|cm|mm)?", v)
    if not m:
        keywords = {"xx-small": 7, "x-small": 7.5, "small": 10, "medium": 12, "large": 13.5, "x-large": 18,
                    "xx-large": 24, "xxx-large": 36}
        return keywords.get(v)
    n, u = float(m.group(1)), m.group(2) or "px"
    return {"pt": n, "px": n * 0.75, "em": n * base, "rem": n * 12, "%": n * base / 100, "in": n * 72,
            "cm": n * 72 / 2.54, "mm": n * 72 / 25.4}[u]


FONT_SIZE_ATTR = {"1": 7.5, "2": 10, "3": 12, "4": 13.5, "5": 18, "6": 24, "7": 36}


class DocxWriter:
    def __init__(self, template=None, page=None):
        import docx
        from docx.shared import Pt
        self.docx = docx
        if template:
            self.doc = docx.Document(str(template))
            body = self.doc.element.body
            for ch in list(body):
                if _local(ch) != "sectPr":
                    body.remove(ch)
        else:
            self.doc = docx.Document()
            sec = self.doc.sections[0]
            p = page or {"w": 595.3, "h": 841.9, "mt": 72, "mb": 72, "ml": 72, "mr": 72}
            sec.page_width, sec.page_height = Pt(p["w"]), Pt(p["h"])
            sec.top_margin, sec.bottom_margin = Pt(p["mt"]), Pt(p["mb"])
            sec.left_margin, sec.right_margin = Pt(p["ml"]), Pt(p["mr"])
        sec = self.doc.sections[-1]
        try:
            self.text_width_emu = int(sec.page_width - sec.left_margin - sec.right_margin)
        except Exception:
            self.text_width_emu = int(Pt(468))
        self._abstract = {}
        self._links = {}
        self._last_link = None
        self.cur = None  # current paragraph
        self.cur_space = True  # last char written was whitespace (for collapsing)

    # ---------------- styles
    def style(self, name):
        from docx.enum.style import WD_STYLE_TYPE
        from docx.shared import Pt
        try:
            return self.doc.styles[name]
        except KeyError:
            pass
        st = self.doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        try:
            st.base_style = self.doc.styles["Normal"]
        except KeyError:
            pass
        m = re.match(r"Heading (\d)", name)
        if name == "Code":
            st.font.name = "Consolas"
            st.font.size = Pt(10)
            st.paragraph_format.space_after = Pt(0)
        elif name == "Quote":
            st.font.italic = True
        elif name == "Title":
            st.font.size = Pt(26)
        elif m:
            st.font.bold = True
            st.font.size = Pt({1: 16, 2: 13, 3: 12}.get(int(m.group(1)), 11))
        return st

    # ---------------- numbering
    def _abstract_id(self, kind):
        if kind in self._abstract:
            return self._abstract[kind]
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        numbering = self.doc.part.numbering_part.element
        ids = [int(a.get(_q("w:abstractNumId"))) for a in numbering.findall(_q("w:abstractNum"))]
        aid = max(ids + [0]) + 1
        lvls = []
        for i in range(9):
            if kind == "ul":
                fmt, text = "bullet", ["•", "◦", "▪"][i % 3]
            else:
                fmt = ["decimal", "lowerLetter", "lowerRoman"][i % 3]
                text = f"%{i + 1}."
            lvls.append(
                f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
                f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
                f'<w:pPr><w:ind w:left="{720 * (i + 1)}" w:hanging="360"/></w:pPr></w:lvl>')
        el = parse_xml(f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{aid}">'
                       f'<w:multiLevelType w:val="hybridMultilevel"/>{"".join(lvls)}</w:abstractNum>')
        first_num = numbering.find(_q("w:num"))
        if first_num is not None:
            first_num.addprevious(el)
        else:
            numbering.append(el)
        self._abstract[kind] = aid
        return aid

    def new_num(self, kind, start=1):
        numbering = self.doc.part.numbering_part.element
        num = numbering.add_num(self._abstract_id(kind))
        for i in range(9):
            num.add_lvlOverride(ilvl=i).add_startOverride(start if i == 0 else 1)
        return num.numId

    # ---------------- paragraphs
    def new_para(self, box, style="Normal", align=None, indent_pt=None, num=None):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt
        p = box.add_paragraph()
        if style and style != "Normal":
            p.style = self.style(style)
        if align:
            p.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT,
                           "justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "left": WD_ALIGN_PARAGRAPH.LEFT}.get(align)
        if indent_pt:
            p.paragraph_format.left_indent = Pt(indent_pt)
        if num:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            ppr = p._p.get_or_add_pPr()
            npr = OxmlElement("w:numPr")
            il = OxmlElement("w:ilvl")
            il.set(qn("w:val"), str(num[1]))
            ni = OxmlElement("w:numId")
            ni.set(qn("w:val"), str(num[0]))
            npr.append(il)
            npr.append(ni)
            ppr.append(npr)
        self.cur = p
        self.cur_space = True
        return p

    def end_para(self):
        if self.cur is not None:
            runs = self.cur.runs
            if runs and runs[-1].text.endswith(" "):
                runs[-1].text = runs[-1].text.rstrip(" ")
        self.cur = None

    # ---------------- runs
    def add_text(self, text, fmt, pre=False):
        if self.cur is None:
            return
        if not pre:
            text = re.sub(r"[ \n\r\f\v]+", " ", text)
            if self.cur_space:
                text = text.lstrip(" ")
            if not text:
                return
        text = text.replace("\xa0", " ")
        if pre and "\n" in text:
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if i:
                    self._run("", fmt).add_break()
                if line:
                    self._run(line, fmt)
        else:
            self._run(text, fmt)
        self.cur_space = text.endswith((" ", "\t", "\n"))

    def _run(self, text, fmt):
        from docx.enum.text import WD_COLOR_INDEX
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
        r = self.cur.add_run(text)
        f = r.font
        if fmt.get("b"):
            f.bold = True
        if fmt.get("i"):
            f.italic = True
        if fmt.get("u") or fmt.get("href"):
            f.underline = True
        if fmt.get("s"):
            f.strike = True
        if fmt.get("sup"):
            f.superscript = True
        if fmt.get("sub"):
            f.subscript = True
        if fmt.get("size"):
            f.size = Pt(round(fmt["size"] * 2) / 2)
        if fmt.get("font"):
            name = fmt["font"].split(",")[0].strip().strip("'\"")
            if name and name.lower() not in ("inherit", "initial", "sans-serif", "serif", "monospace"):
                f.name = name
                rf = r._r.get_or_add_rPr().find(qn("w:rFonts"))
                if rf is not None:
                    rf.set(qn("w:eastAsia"), name)
                    rf.set(qn("w:cs"), name)
            elif name.lower() == "monospace":
                f.name = "Consolas"
        color = fmt.get("color") or ("0563c1" if fmt.get("href") else None)
        if color:
            f.color.rgb = RGBColor.from_string(color.upper())
        bg = fmt.get("bg")
        if bg:
            hl = HIGHLIGHT_BY_HEX.get("#" + bg)
            if hl:
                f.highlight_color = getattr(WD_COLOR_INDEX, {
                    "yellow": "YELLOW", "green": "BRIGHT_GREEN", "cyan": "TURQUOISE", "magenta": "PINK",
                    "blue": "BLUE", "red": "RED", "darkBlue": "DARK_BLUE", "darkCyan": "TEAL", "darkGreen": "GREEN",
                    "darkMagenta": "VIOLET", "darkRed": "DARK_RED", "darkYellow": "DARK_YELLOW",
                    "darkGray": "GRAY_50", "lightGray": "GRAY_25", "black": "BLACK", "white": "WHITE"}[hl])
            else:
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), bg.upper())
                r._r.get_or_add_rPr().append(shd)
        href = fmt.get("href")
        if href:
            self._linkify(r, href)
        return r

    def _linkify(self, run, href):
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        last = run._r.getprevious()
        if self._last_link and last is not None and last is self._last_link[0] and self._last_link[1] == href:
            last.append(run._r)
            return
        hl = OxmlElement("w:hyperlink")
        if href.startswith("#"):
            hl.set(qn("w:anchor"), href[1:])
        else:
            if href not in self._links:
                self._links[href] = self.doc.part.relate_to(href, RT.HYPERLINK, is_external=True)
            hl.set(qn("r:id"), self._links[href])
        run._r.addprevious(hl)
        hl.append(run._r)
        self._last_link = (hl, href)

    def add_break(self, page=False):
        from docx.enum.text import WD_BREAK
        if self.cur is None:
            return
        r = self.cur.add_run()
        r.add_break(WD_BREAK.PAGE if page else WD_BREAK.LINE)
        self.cur_space = True

    def add_image(self, src, css, attrs):
        from docx.shared import Emu
        data = None
        if src.startswith("data:"):
            try:
                head, b64 = src.split(",", 1)
                data = base64.b64decode(b64) if ";base64" in head else bytes(htmllib.unescape(b64), "utf-8")
            except Exception:
                return
        elif os.path.isfile(src):
            data = Path(src).read_bytes()
        if not data:
            return
        stream = io.BytesIO(data)
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            nat_w, nat_h = im.size
            if im.format not in ("PNG", "JPEG", "GIF", "BMP", "TIFF"):
                buf = io.BytesIO()
                im.save(buf, "PNG")
                stream = io.BytesIO(buf.getvalue())
        except Exception:
            return
        w = _length_pt(css.get("width")) if css.get("width", "").strip().endswith(("px", "pt", "in", "cm", "mm")) else None
        if w is None and (attrs.get("width") or "").isdigit():
            w = int(attrs["width"]) * 0.75
        hgt = _length_pt(css.get("height")) if css.get("height", "").strip().endswith(("px", "pt", "in", "cm", "mm")) else None
        if hgt is None and (attrs.get("height") or "").isdigit():
            hgt = int(attrs["height"]) * 0.75
        pct = re.fullmatch(r"([\d.]+)%", css.get("width", "").strip())
        if pct:
            w = self.text_width_emu / 12700 * float(pct.group(1)) / 100
            hgt = None
        if w is None:
            w = nat_w * 0.75
        if hgt is None:
            hgt = w * nat_h / max(nat_w, 1)
        w_emu, h_emu = int(w * 12700), int(hgt * 12700)
        if w_emu > self.text_width_emu:  # fit to the text column
            h_emu = int(h_emu * self.text_width_emu / w_emu)
            w_emu = self.text_width_emu
        if self.cur is None:
            return
        self.cur.add_run().add_picture(stream, width=Emu(w_emu), height=Emu(h_emu))
        self.cur_space = False

    def hr_para(self, box):
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        p = self.new_para(box)
        p._p.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/></w:pBdr>'))
        self.end_para()

    # ---------------- tree walk
    def write(self, root):
        self.blocks(root, self.doc, {"style": "Normal"})
        self.end_para()
        self._cleanup_rels()

    def _cleanup_rels(self):
        """Drop images/links of the template's old body that are no longer referenced."""
        xml = self.doc.element.xml
        used = set(re.findall(r'r:(?:id|embed|link)="([^"]+)"', xml))
        for rid, rel in list(self.doc.part.rels.items()):
            if rid not in used and (rel.reltype.endswith("/image") or rel.reltype.endswith("/hyperlink")):
                del self.doc.part.rels[rid]

    def blocks(self, el, box, ctx):
        """Walk el's children; inline content gathers into paragraphs, block elements start new ones."""
        if el.text:
            self._inline_text(el.text, box, ctx)
        for ch in el:
            tag = ch.tag.lower() if isinstance(ch.tag, str) else None
            if tag is None:  # comment / PI
                if ch.tail:
                    self._inline_text(ch.tail, box, ctx)
                continue
            if tag in SKIP_TAGS:
                pass
            elif tag in BLOCK_TAGS:
                self.end_para()
                self.block(ch, box, ctx)
                self.end_para()
            else:
                if self.cur is None:
                    self._open(box, ctx)
                self.inline(ch, box, ctx, ctx.get("fmt", {}))
            if ch.tail:
                self._inline_text(ch.tail, box, ctx)

    def _open(self, box, ctx):
        self.new_para(box, ctx.get("style", "Normal"), ctx.get("align"), ctx.get("indent"), ctx.get("num"))

    def _inline_text(self, text, box, ctx):
        if self.cur is None:
            if not ctx.get("pre") and not text.strip(" \n\r\t\f\v"):
                return
            self._open(box, ctx)
        self.add_text(text, ctx.get("fmt", {}), pre=ctx.get("pre"))

    def _para_ctx(self, el, ctx):
        css = _css(el)
        c = dict(ctx)
        al = (css.get("text-align") or el.get("align") or "").lower()
        if al in ("center", "right", "justify", "left"):
            c["align"] = al
        ml = _length_pt(css.get("margin-left") or css.get("padding-left"))
        if ml and ml > 0 and not ctx.get("num"):
            c["indent"] = (ctx.get("indent") or 0) + ml
        c["fmt"] = self._fmt_from(el, ctx.get("fmt", {}))
        return c

    def block(self, el, box, ctx):
        tag = el.tag.lower()
        cls = (el.get("class") or "").split()
        if tag == "div" and "page-break" in cls:
            self.new_para(box, ctx.get("style", "Normal"))
            self.add_break(page=True)
            self.end_para()
            return
        if tag == "hr":
            self.hr_para(box)
            return
        if tag == "table":
            self.table(el, box, ctx)
            return
        if tag in ("ul", "ol"):
            self.list(el, box, ctx, 0 if not ctx.get("list_level_next") else ctx["list_level_next"])
            return
        c = self._para_ctx(el, ctx)
        if tag in HEADING_STYLE:
            c["style"] = "Title" if "title" in cls and tag == "h1" else "Subtitle" if "subtitle" in cls else HEADING_STYLE[tag]
        elif tag == "blockquote":
            c["style"] = "Quote"
        elif tag == "pre":
            c["style"] = "Code"
            c["pre"] = True
        elif tag == "li":  # stray li outside a list
            c.setdefault("num", (self.new_num("ul"), 0))
        elif tag in ("dt",):
            c["fmt"] = {**c["fmt"], "b": 1}
        elif tag in ("dd",):
            c["indent"] = (c.get("indent") or 0) + 36
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "dt", "dd", "figcaption", "summary", "li"):
            self.new_para(box, c.get("style", "Normal"), c.get("align"), c.get("indent"), c.get("num"))
            has_inline = False
            if el.text:
                self.add_text(el.text, c["fmt"], pre=c.get("pre"))
            for ch in el:
                t = ch.tag.lower() if isinstance(ch.tag, str) else None
                if t is None or t in SKIP_TAGS:
                    pass
                elif t in BLOCK_TAGS:  # block nested in a paragraph (e.g. <p><div>) -> new paragraph
                    self.end_para()
                    sub = dict(c)
                    sub.pop("num", None)
                    self.block(ch, box, sub)
                    self.end_para()
                    self.new_para(box, c.get("style", "Normal"), c.get("align"), c.get("indent"))
                else:
                    self.inline(ch, box, c, c["fmt"])
                    has_inline = True
                if ch.tail:
                    if self.cur is None:
                        self.new_para(box, c.get("style", "Normal"), c.get("align"), c.get("indent"))
                    self.add_text(ch.tail, c["fmt"], pre=c.get("pre"))
            self.end_para()
            # drop a trailing empty paragraph created after a nested block
            return
        # generic containers (div, blockquote, section…): their children inherit style
        self.blocks(el, box, c)
        self.end_para()

    def list(self, el, box, ctx, level):
        tag = el.tag.lower()
        start = int(el.get("start")) if (el.get("start") or "").isdigit() else 1
        parent_num = ctx.get("list_num")
        if parent_num and parent_num[1] == tag:
            num_id = parent_num[0]
        else:
            num_id = self.new_num(tag, start)
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None:
                continue
            if t in ("ul", "ol"):  # Chrome puts nested lists straight inside the list
                sub = dict(ctx)
                sub["list_num"] = (num_id, tag) if t == tag else None
                self.list(ch, box, sub, level + 1)
                continue
            if t != "li":
                self.end_para()
                self.block(ch, box, ctx) if t in BLOCK_TAGS else None
                continue
            self.list_item(ch, box, ctx, num_id, tag, level)

    def list_item(self, li, box, ctx, num_id, tag, level):
        c = self._para_ctx(li, ctx)
        c.pop("indent", None)
        c["style"] = "List Paragraph"
        self.end_para()
        self.new_para(box, "List Paragraph", c.get("align"), None, (num_id, level))
        first = True

        def ensure():
            nonlocal first
            if self.cur is None:
                # continuation paragraph inside the same item: indent instead of a new number
                self.new_para(box, "List Paragraph", c.get("align"), 36 * (level + 1))
        if li.text:
            self.add_text(li.text, c["fmt"])
        for ch in li:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None or t in SKIP_TAGS:
                pass
            elif t in ("ul", "ol"):
                self.end_para()
                sub = dict(ctx)
                sub["list_num"] = (num_id, tag) if t == tag else None
                self.list(ch, box, sub, level + 1)
            elif t in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"):
                # first paragraph of an item fills the numbered paragraph
                if self.cur is not None and not self.cur.runs and first:
                    sub = self._para_ctx(ch, c)
                    if ch.text:
                        self.add_text(ch.text, sub["fmt"])
                    for g in ch:
                        if isinstance(g.tag, str) and g.tag.lower() not in SKIP_TAGS:
                            if g.tag.lower() in BLOCK_TAGS:
                                self.end_para()
                                self.block(g, box, sub)
                            else:
                                ensure()
                                self.inline(g, box, sub, sub["fmt"])
                        if g.tail:
                            ensure()
                            self.add_text(g.tail, sub["fmt"])
                    self.end_para()
                else:
                    self.end_para()
                    sub = dict(c)
                    sub["indent"] = 36 * (level + 1)
                    sub.pop("num", None)
                    self.block(ch, box, sub)
            elif t in BLOCK_TAGS:
                self.end_para()
                self.block(ch, box, c)
            else:
                ensure()
                self.inline(ch, box, c, c["fmt"])
            first = False
            if ch.tail and ch.tail.strip():
                ensure()
                self.add_text(ch.tail, c["fmt"])
        self.end_para()

    def _fmt_from(self, el, fmt):
        f = dict(fmt)
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag in ("b", "strong") or tag in ("th",):
            f["b"] = 1
        if tag in ("i", "em", "cite", "var", "dfn"):
            f["i"] = 1
        if tag in ("u", "ins"):
            f["u"] = 1
        if tag in ("s", "strike", "del"):
            f["s"] = 1
        if tag == "sup":
            f["sup"], f["sub"] = 1, 0
        if tag == "sub":
            f["sub"], f["sup"] = 1, 0
        if tag in ("code", "kbd", "samp", "tt"):
            f["font"] = "Consolas"
        if tag == "mark":
            f["bg"] = "ffff00"
        if tag == "font":
            if el.get("face"):
                f["font"] = el.get("face")
            if el.get("size") in FONT_SIZE_ATTR:
                f["size"] = FONT_SIZE_ATTR[el.get("size")]
            if _color(el.get("color")):
                f["color"] = _color(el.get("color"))
        css = _css(el)
        fw = css.get("font-weight", "")
        if fw in ("bold", "bolder") or (fw.isdigit() and int(fw) >= 600):
            f["b"] = 1
        elif fw in ("normal", "lighter") or (fw.isdigit() and int(fw) < 600):
            f.pop("b", None)
        fs = css.get("font-style", "")
        if fs in ("italic", "oblique"):
            f["i"] = 1
        elif fs == "normal":
            f.pop("i", None)
        td = css.get("text-decoration", "") + " " + css.get("text-decoration-line", "")
        if "underline" in td:
            f["u"] = 1
        if "line-through" in td:
            f["s"] = 1
        if css.get("vertical-align") in ("super", "sub"):
            f["sup" if css["vertical-align"] == "super" else "sub"] = 1
        if css.get("font-size"):
            sz = _length_pt(css["font-size"], fmt.get("size") or 11)
            if sz and 1 <= sz <= 400:
                f["size"] = sz
        if css.get("font-family"):
            f["font"] = css["font-family"]
        if _color(css.get("color")):
            f["color"] = _color(css.get("color"))
        bg = _color(css.get("background-color") or css.get("background"))
        if bg and bg != "ffffff":
            f["bg"] = bg
        return f

    def inline(self, el, box, ctx, fmt):
        tag = el.tag.lower()
        if tag in SKIP_TAGS:
            return
        if tag == "br":
            if self.cur is None:
                self._open(box, ctx)
            self.add_break()
            return
        if tag == "img":
            if self.cur is None:
                self._open(box, ctx)
            self.add_image(el.get("src") or "", _css(el), el.attrib)
            return
        if tag == "span" and "tab" in (el.get("class") or "").split():
            if self.cur is None:
                self._open(box, ctx)
            self._run("\t", fmt)
            self.cur_space = True
            return
        f = self._fmt_from(el, fmt)
        if tag == "a" and el.get("href") and not el.get("href", "").lower().startswith("javascript:"):
            f["href"] = el.get("href")
        if el.text:
            self.add_text(el.text, f, pre=ctx.get("pre"))
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None:
                pass
            elif t in BLOCK_TAGS:  # block inside inline (sloppy html): treat as line break
                self.end_para()
                self.block(ch, box, ctx)
                self._open(box, ctx)
            else:
                self.inline(ch, box, ctx, f)
            if ch.tail:
                if self.cur is None:
                    self._open(box, ctx)
                self.add_text(ch.tail, f, pre=ctx.get("pre"))

    def table(self, el, box, ctx):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        trs = [tr for tr in el.iter("tr") if tr.xpath("ancestor::table[1]")[0] is el]
        if not trs:
            return
        # grid placement (colspan/rowspan)
        occ = {}
        placed = []
        for ri, tr in enumerate(trs):
            ci = 0
            for td in tr:
                if not isinstance(td.tag, str) or td.tag.lower() not in ("td", "th"):
                    continue
                while (ri, ci) in occ:
                    ci += 1
                cs = max(1, int(td.get("colspan")) if (td.get("colspan") or "").isdigit() else 1)
                rs = max(1, int(td.get("rowspan")) if (td.get("rowspan") or "").isdigit() else 1)
                rs = min(rs, len(trs) - ri)
                for dr in range(rs):
                    for dc in range(cs):
                        occ[(ri + dr, ci + dc)] = True
                placed.append((ri, ci, rs, cs, td))
                ci += cs
        nrows = len(trs)
        ncols = max(c for _, c in occ) + 1
        self.end_para()
        tbl = box.add_table(rows=nrows, cols=ncols)
        try:
            tbl.style = self.doc.styles["Table Grid"]
        except KeyError:
            self._borders(tbl)
        for ri, ci, rs, cs, td in placed:
            cell = tbl.cell(ri, ci)
            if rs > 1 or cs > 1:
                cell = cell.merge(tbl.cell(ri + rs - 1, ci + cs - 1))
            bg = _color(_css(td).get("background-color") or td.get("bgcolor"))
            if bg and bg != "ffffff":
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), bg.upper())
                cell._tc.get_or_add_tcPr().append(shd)
            sub = {"style": "Normal", "fmt": self._fmt_from(td, {})}
            al = (_css(td).get("text-align") or td.get("align") or "").lower()
            if al in ("center", "right", "justify"):
                sub["align"] = al
            cb = _CellBox(cell)
            self.blocks(td, cb, sub)
            self.end_para()
            cb.finish()

    def _borders(self, tbl):
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        borders = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                          for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        tbl._tbl.tblPr.append(parse_xml(f'<w:tblBorders {nsdecls("w")}>{borders}</w:tblBorders>'))

    def save(self, out):
        self.doc.save(str(out))


class _CellBox:
    """Lets the writer add paragraphs/tables to a table cell, reusing the cell's initial empty paragraph."""

    def __init__(self, cell):
        self.cell = cell
        self.fresh = list(cell.paragraphs)

    def add_paragraph(self):
        while self.fresh:
            p = self.fresh.pop(0)
            if not p.text and not p._p.xpath(".//w:drawing"):
                return p
        return self.cell.add_paragraph()

    def add_table(self, rows, cols):
        self.fresh = []
        t = self.cell.add_table(rows, cols)
        return t

    def finish(self):
        # remove leftover empty paragraphs beyond the first (keep at least one paragraph)
        ps = self.cell.paragraphs
        for p in self.fresh:
            if len(self.cell.paragraphs) > 1 and p in ps and not p.text:
                p._p.getparent().remove(p._p)


def html_to_docx(html: str, out: Path, template=None, page=None):
    w = DocxWriter(template, page)
    w.write(parse_html(html))
    w.save(out)
    return out


# =====================================================================================================================
# HTML -> TXT / MD / full HTML ; other formats -> HTML
# =====================================================================================================================
def _text_of(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext()))


def _inline_text(el) -> str:
    """Text of an inline element; <br> becomes a newline."""
    out = [el.text or ""]
    for ch in el:
        t = ch.tag.lower() if isinstance(ch.tag, str) else None
        if t == "br":
            out.append("\n")
        elif t == "img":
            out.append("[image]")
        elif t and t not in SKIP_TAGS:
            out.append(_inline_text(ch))
        out.append(ch.tail or "")
    return "".join(out)


def html_to_text(html: str) -> str:
    root = parse_html(html)
    lines = []

    def walk(el, indent="", list_tag=None):
        buf = []

        def flush():
            for part in "".join(buf).split("\n"):
                s = re.sub(r"[ \r\f\v]+", " ", part).strip(" ")
                if s:
                    lines.append(indent + s)
            buf.clear()
        buf.append(el.text or "")
        n = 0
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None or t in SKIP_TAGS:
                pass
            elif t in ("ul", "ol"):
                flush()
                walk(ch, indent + ("  " if list_tag else ""), t)
            elif t == "li":
                flush()
                n += 1
                start = len(lines)
                walk(ch, indent, "li")
                if len(lines) > start:
                    mark = f"{n}. " if list_tag == "ol" else "- "
                    lines[start] = indent + mark + lines[start][len(indent):]
            elif t == "table":
                flush()
                for tr in ch.iter("tr"):
                    lines.append(indent + "\t".join(re.sub(r"\s+", " ", _inline_text(td)).strip()
                                                    for td in tr if isinstance(td.tag, str) and td.tag.lower() in ("td", "th")))
            elif t == "hr":
                flush()
                lines.append(indent + "-" * 40)
            elif t == "div" and "page-break" in (ch.get("class") or ""):
                flush()
                lines.append("\f")
            elif t == "pre":
                flush()
                lines.extend(indent + l for l in "".join(ch.itertext()).split("\n"))
            elif t in BLOCK_TAGS:
                flush()
                walk(ch, indent, list_tag)
            elif t == "img":
                buf.append("[image]")
            else:
                buf.append(_inline_text(ch))
            buf.append(ch.tail or "")
        flush()
    walk(root)
    return "\n".join(lines) + "\n"


def html_to_md(html: str) -> str:
    root = parse_html(html)
    out = []

    def inline(el) -> str:
        s = _esc_md(el.text or "")
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None or t in SKIP_TAGS:
                pass
            elif t == "br":
                s += "  \n"
            elif t == "img":
                s += f"![{ch.get('alt') or ''}]({ch.get('src') or ''})"
            else:
                inner = inline(ch)
                css = _css(ch)
                if inner.strip():
                    lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", inner, re.S).groups()
                    if t in ("b", "strong") or css.get("font-weight") in ("bold", "700", "800", "900"):
                        core = f"**{core}**"
                    if t in ("i", "em") or css.get("font-style") == "italic":
                        core = f"*{core}*"
                    if t in ("s", "strike", "del") or "line-through" in css.get("text-decoration", ""):
                        core = f"~~{core}~~"
                    if t == "code":
                        core = f"`{''.join(ch.itertext())}`"
                    if t == "a" and ch.get("href"):
                        core = f"[{core}]({ch.get('href')})"
                    inner = lead + core + trail
                s += inner
            s += _esc_md(ch.tail or "")
        return s

    def para(el) -> str:
        s = inline(el).replace("  \n", "\x01")  # keep hard line breaks
        s = re.sub(r"\s+", " ", s).strip()
        return s.replace("\x01", "  \n").replace("  \n ", "  \n")

    def walk(el, depth=0):
        if el.text and el.text.strip():
            out.append(_esc_md(el.text.strip()))
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t is None or t in SKIP_TAGS:
                pass
            elif t in HEADING_STYLE:
                n = int(t[1])
                out.append("#" * n + " " + para(ch))
            elif t in ("p", "dt", "dd", "figcaption", "address"):
                out.append(para(ch))
            elif t == "blockquote":
                txt = para(ch) if not any(isinstance(c.tag, str) and c.tag.lower() in BLOCK_TAGS for c in ch) else None
                if txt is None:
                    sub = []
                    out_len = len(out)
                    walk(ch, depth)
                    sub = out[out_len:]
                    del out[out_len:]
                    txt = "\n\n".join(sub)
                out.append("\n".join("> " + l for l in txt.split("\n")))
            elif t == "pre":
                out.append("```\n" + "".join(ch.itertext()).rstrip("\n") + "\n```")
            elif t in ("ul", "ol"):
                out.append(lst(ch, 0))
            elif t == "table":
                out.append(table_md(ch))
            elif t == "hr":
                out.append("---")
            elif t == "div" and "page-break" in (ch.get("class") or ""):
                out.append('<div style="page-break-after:always"></div>')
            elif t in BLOCK_TAGS:
                walk(ch, depth)
            else:
                s = para_like(ch)
                if s:
                    out.append(s)
            if ch.tail and ch.tail.strip():
                out.append(_esc_md(ch.tail.strip()))

    def para_like(el):
        wrapper = parse_html("")
        wrapper.append(copy.deepcopy(el))
        return para(wrapper)

    def lst(el, depth) -> str:
        lines = []
        n = int(el.get("start")) if (el.get("start") or "").isdigit() else 1
        tag = el.tag.lower()
        for ch in el:
            t = ch.tag.lower() if isinstance(ch.tag, str) else None
            if t in ("ul", "ol"):
                lines.append(lst(ch, depth + 1))
                continue
            if t != "li":
                continue
            nested = [c for c in ch if isinstance(c.tag, str) and c.tag.lower() in ("ul", "ol")]
            tmp = copy.deepcopy(ch)
            for c in list(tmp):
                if isinstance(c.tag, str) and c.tag.lower() in ("ul", "ol"):
                    tmp.remove(c)
            marker = f"{n}." if tag == "ol" else "-"
            lines.append("    " * depth + f"{marker} " + para(tmp))
            n += 1
            for c in nested:
                lines.append(lst(c, depth + 1))
        return "\n".join(lines)

    def table_md(el) -> str:
        rows = []
        for tr in el.iter("tr"):
            rows.append([para(td).replace("|", "\\|") for td in tr if isinstance(td.tag, str) and td.tag.lower() in ("td", "th")])
        if not rows:
            return ""
        w = max(len(r) for r in rows)
        rows = [r + [""] * (w - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * w]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    walk(root)
    return "\n\n".join(x for x in out if x is not None and x != "").strip() + "\n"


def _esc_md(s: str) -> str:
    return re.sub(r"([*_`\[\]])", r"\\\1", s)


PAGE_CSS = """
body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.35;max-width:820px;margin:40px auto;padding:0 20px;color:#111}
h1.title{font-size:26pt;font-weight:400}
table{border-collapse:collapse;margin:6pt 0}td,th{border:1px solid #888;padding:4px 7px;vertical-align:top}
td>p,th>p{margin:0}blockquote{margin:8pt 24pt;font-style:italic;color:#444}
pre{font-family:Consolas,monospace;font-size:10pt;background:#f5f5f5;padding:6pt;white-space:pre-wrap}
img{max-width:100%}.page-break{page-break-after:always;break-after:page;height:0}
.tab{white-space:pre}
"""


def html_document(body_html: str, title: str, font=None) -> str:
    css = PAGE_CSS
    if font:
        css += f"body{{font-family:'{font.get('family', 'Calibri')}',Arial,sans-serif;font-size:{font.get('size', 11)}pt}}"
    return (f"<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{_esc(title)}</title>"
            f"<style>{css}</style></head><body>\n{body_html}\n</body></html>\n")


def sanitize_html(html: str) -> str:
    """Strip scripts, styles, event handlers & external embeds from an HTML file opened for editing."""
    import lxml.html
    try:
        doc = lxml.html.document_fromstring(html)
    except Exception:
        return _esc(html)
    body = doc.find("body")
    if body is None:
        body = doc
    for bad in list(body.iter("script", "style", "link", "meta", "iframe", "object", "embed", "form", "input",
                               "button", "select", "textarea", "noscript", "template", "base")):
        if bad.getparent() is not None:
            bad.drop_tree()
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        for a in list(el.attrib):
            al = a.lower()
            v = el.attrib[a]
            if al.startswith("on") or al == "contenteditable":
                del el.attrib[a]
            elif al == "class":
                keep = [c for c in v.split() if c in ("page-break", "title", "subtitle", "tab")]
                if keep:
                    el.attrib[a] = " ".join(keep)
                else:
                    del el.attrib[a]
            elif al in ("href", "src") and v.strip().lower().startswith(("javascript:", "vbscript:")):
                del el.attrib[a]
    inner = (body.text and _esc(body.text) or "") + "".join(lxml.html.tostring(c, encoding="unicode") for c in body)
    return inner


def text_to_html(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.strip() == "\f":
            out.append('<div class="page-break" contenteditable="false"></div>')
            continue
        h = _esc(line).replace("\t", '<span class="tab">\t</span>')
        h = re.sub(r"  +", lambda m: " " + "&nbsp;" * (len(m.group()) - 1), h)
        out.append(f"<p>{h or '<br>'}</p>")
    return "".join(out) or "<p><br></p>"


def read_text(path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def odt_to_html(path) -> str:
    """Best effort ODT reader (headings, paragraphs, lists, tables as text) when Word isn't available."""
    from odf import teletype
    from odf.opendocument import load
    from odf.namespaces import TEXTNS, TABLENS
    doc = load(str(path))
    out = []

    def walk(node, list_depth=0):
        for ch in node.childNodes:
            q = getattr(ch, "qname", None)
            if not q:
                continue
            ns, name = q
            if ns == TEXTNS and name == "h":
                lvl = min(int(ch.getAttribute("outlinelevel") or 1), 6)
                out.append(f"<h{lvl}>{_esc(teletype.extractText(ch))}</h{lvl}>")
            elif ns == TEXTNS and name == "p":
                out.append(f"<p>{_esc(teletype.extractText(ch)) or '<br>'}</p>")
            elif ns == TEXTNS and name == "list":
                out.append("<ul>")
                for item in ch.childNodes:
                    out.append("<li>")
                    walk(item, list_depth + 1)
                    out.append("</li>")
                out.append("</ul>")
            elif ns == TABLENS and name == "table":
                out.append("<table><tbody>")
                for row in ch.getElementsByType(__import__("odf.table", fromlist=["TableRow"]).TableRow):
                    out.append("<tr>" + "".join(f"<td>{_esc(teletype.extractText(c))}</td>" for c in row.childNodes
                                                if getattr(c, "qname", ("", ""))[1] == "table-cell") + "</tr>")
                out.append("</tbody></table>")
            elif ns == TEXTNS and name in ("section", "list-item", "list-header"):
                walk(ch, list_depth)
    walk(doc.text)
    return "".join(out).replace("<li><p>", "<li>").replace("</p></li>", "</li>")


def open_document(path) -> dict:
    """Any supported document -> {html, page, font, note?}."""
    p = Path(path)
    e = ext_of(p)
    page = {"w": 595.3, "h": 841.9, "mt": 72, "mb": 72, "ml": 72, "mr": 72}
    font = {"family": "Calibri", "size": 11}
    if e in ("docx", "docm", "dotx"):
        return docx_to_html(p)
    if e in ("doc", "rtf", "odt"):
        cd = _office()
        if cd.HAS_WORD:
            tmp = TMP / f"office_{uuid.uuid4().hex[:8]}.docx"
            cd.word_convert(p, tmp, {})
            try:
                d = docx_to_html(tmp)
            finally:
                tmp.unlink(missing_ok=True)
            d["note"] = f"Converted from .{e} with Microsoft Word."
            return d
        if e == "odt":
            return {"html": odt_to_html(p), "page": page, "font": font,
                    "note": "Opened without Microsoft Word: only text, headings, lists and tables are kept."}
        if e == "rtf":
            txt = re.sub(r"\\par[d]?", "\n", read_text(p))
            txt = re.sub(r"\{\\\*[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", txt)
            return {"html": text_to_html(txt), "page": page, "font": font,
                    "note": "Opened without Microsoft Word: formatting was dropped."}
        raise ValueError("Opening .doc files needs Microsoft Word. Convert it to DOCX first.")
    if e in ("txt",):
        return {"html": text_to_html(read_text(p)), "page": page, "font": {"family": "Consolas", "size": 10.5}}
    if e in ("md", "markdown"):
        import markdown
        body = markdown.markdown(read_text(p), extensions=["tables", "fenced_code", "sane_lists"])
        return {"html": body or "<p><br></p>", "page": page, "font": font}
    if e in ("html", "htm"):
        return {"html": sanitize_html(read_text(p)) or "<p><br></p>", "page": page, "font": font}
    raise ValueError(f"Can't open .{e} as a document")


DOC_SAVE_FORMATS = ("docx", "pdf", "html", "txt", "md", "rtf", "odt", "doc")


def save_document(src: str, html: str, fmt: str, dest: Path, page=None, font=None) -> Path:
    """Write the edited HTML to dest in fmt. Uses the original DOCX as a template when there is one."""
    src_p = Path(src) if src else None
    se = ext_of(src_p) if src_p else ""
    tmp = TMP / f"office_{uuid.uuid4().hex[:8]}.{fmt}"
    title = src_p.stem if src_p else "document"
    try:
        if fmt in ("docx", "pdf", "rtf", "odt", "doc"):
            template = src_p if se in ("docx", "docm", "dotx") and src_p.exists() else None
            docx_tmp = tmp if fmt == "docx" else tmp.with_suffix(".docx")
            html_to_docx(html, docx_tmp, template, page)
            if fmt != "docx":
                cd = _office()
                if cd.HAS_WORD:
                    cd.word_convert(docx_tmp, tmp, {})
                    docx_tmp.unlink(missing_ok=True)
                elif fmt == "pdf":
                    docx_tmp.unlink(missing_ok=True)
                    html_to_pdf_file(html, tmp, page, font)
                else:
                    docx_tmp.unlink(missing_ok=True)
                    raise ValueError(f"Saving as .{fmt} needs Microsoft Word. Save as DOCX instead.")
        elif fmt in ("html", "htm"):
            tmp.write_text(html_document(html, title, font), encoding="utf-8")
        elif fmt == "txt":
            tmp.write_text(html_to_text(html), encoding="utf-8")
        elif fmt in ("md", "markdown"):
            tmp.write_text(html_to_md(html), encoding="utf-8")
        else:
            raise ValueError(f"Unknown format: {fmt}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _replace_into(tmp, dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)


def html_to_pdf_file(html: str, out: Path, page=None, font=None):
    """HTML -> PDF with PyMuPDF's Story (no Word needed). Data-URI images are written to a temp folder first."""
    import pymupdf as fitz
    page = page or {"w": 595.3, "h": 841.9, "mt": 72, "mb": 72, "ml": 72, "mr": 72}
    work = TMP / f"office_pdf_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        n = [0]

        def unpack(m):
            head, b64 = m.group(2).split(",", 1)
            ext = (re.search(r"image/(\w+)", head) or [None, "png"])[1].replace("jpeg", "jpg")
            n[0] += 1
            name = f"img{n[0]}.{ext}"
            (work / name).write_bytes(base64.b64decode(b64))
            return f'{m.group(1)}"{name}"'
        body = re.sub(r'(src=)"(data:image/[^"]+)"', unpack, html)
        body = body.replace('<div class="page-break" contenteditable="false"></div>', '<p style="page-break-before:always"></p>')
        fam = (font or {}).get("family", "sans-serif")
        css = (f"body{{font-family:sans-serif;font-size:{(font or {}).get('size', 11)}pt;line-height:1.35}}"
               "table{border-collapse:collapse}td,th{border:1px solid #888;padding:3px 5px}"
               "h1.title{font-size:26pt;font-weight:normal}blockquote{font-style:italic;margin-left:24pt}"
               "pre{font-family:monospace;font-size:9.5pt}")
        story = fitz.Story(html=f"<body>{body}</body>", user_css=css, archive=str(work))
        mediabox = fitz.Rect(0, 0, page["w"], page["h"])
        where = mediabox + (page["ml"], page["mt"], -page["mr"], -page["mb"])
        writer = fitz.DocumentWriter(str(out))
        more = True
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
        writer.close()
        fam  # noqa
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return out


# =====================================================================================================================
# Slides & PDFs (read-only)
# =====================================================================================================================
def open_slides(path) -> dict:
    import hashlib
    from . import pdf_editor
    p = Path(path)
    e = ext_of(p)
    cd = _office()
    if cd.HAS_POWERPOINT:
        st = p.stat()
        key = hashlib.md5(f"{p.resolve()}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:16]
        out = TMP / "office_slides" / f"{key}.pdf"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(f"{key}_{uuid.uuid4().hex[:6]}.pdf")
            cd.ppt_to_pdf(p, tmp, {})
            os.replace(tmp, out)
        return {"mode": "pdf", "pdf": str(out), "pages": pdf_editor.info(str(out))["pages"]}
    if e in ("pptx", "pptm", "ppsx"):
        return {"mode": "text", "slides": pptx_extract(p),
                "note": "PowerPoint isn't installed, so this shows each slide's text and pictures only."}
    raise ValueError(f"Viewing .{e} files needs Microsoft PowerPoint. Save it as .pptx to see its text here.")


def pptx_extract(path) -> list[dict]:
    """Slide text + pictures straight from the PPTX XML (no python-pptx needed)."""
    from lxml import etree
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    RN = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    PR = "http://schemas.openxmlformats.org/package/2006/relationships"
    slides = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        def rels(part):
            folder, name = part.rsplit("/", 1)
            rp = f"{folder}/_rels/{name}.rels"
            if rp not in names:
                return {}
            out = {}
            for r in etree.fromstring(z.read(rp)).iter(f"{{{PR}}}Relationship"):
                tgt = r.get("Target")
                full = tgt if r.get("TargetMode") == "External" else os.path.normpath(f"{folder}/{tgt}").replace("\\", "/")
                out[r.get("Id")] = (r.get("Type"), full)
            return out
        pres = etree.fromstring(z.read("ppt/presentation.xml"))
        prels = rels("ppt/presentation.xml")
        order = [prels[s.get(f"{{{RN}}}id")][1] for s in pres.iter(f"{{{P}}}sldId") if s.get(f"{{{RN}}}id") in prels]
        for i, part in enumerate(order, 1):
            root = etree.fromstring(z.read(part))
            paras = []
            for para in root.iter(f"{{{A}}}p"):
                t = "".join(x.text or "" for x in para.iter(f"{{{A}}}t")).strip()
                if t:
                    paras.append(t)
            images = []
            srels = rels(part)
            for blip in root.iter(f"{{{A}}}blip"):
                rid = blip.get(f"{{{RN}}}embed")
                if rid in srels and srels[rid][1] in names:
                    data = z.read(srels[rid][1])
                    ext = srels[rid][1].rsplit(".", 1)[-1].lower()
                    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "bmp": "bmp"}.get(ext)
                    if mime and len(data) < 4_000_000:
                        images.append(f"data:image/{mime};base64," + base64.b64encode(data).decode())
            slides.append({"n": i, "title": paras[0] if paras else f"Slide {i}", "paras": paras[1:], "images": images})
    return slides


# =====================================================================================================================
# Spreadsheets
# =====================================================================================================================
MISSING = object()
THEME_COLORS = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
                "0563C1", "954F72"]
SHEET_SAVE_FORMATS = ("xlsx", "xlsm", "csv", "tsv", "ods", "json", "pdf")


def _col_letter(i: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(i)


def _col_index(s: str) -> int:
    from openpyxl.utils import column_index_from_string
    return column_index_from_string(s.upper())


def _hex(c):
    """openpyxl Color -> '#rrggbb' (rgb, theme with tint, indexed)."""
    if c is None:
        return None
    try:
        if c.type == "rgb" and isinstance(c.rgb, str) and len(c.rgb) >= 6:
            return "#" + c.rgb[-6:].lower()
        if c.type == "theme" and c.theme is not None and c.theme < len(THEME_COLORS):
            rgb = [int(THEME_COLORS[c.theme][i:i + 2], 16) for i in (0, 2, 4)]
            t = c.tint or 0
            rgb = [round(x + (255 - x) * t) if t > 0 else round(x * (1 + t)) for x in rgb]
            return "#" + "".join(f"{max(0, min(255, x)):02x}" for x in rgb)
        if c.type == "indexed" and c.indexed is not None:
            from openpyxl.styles.colors import COLOR_INDEX
            if c.indexed < len(COLOR_INDEX) and c.indexed not in (64, 65):
                return "#" + COLOR_INDEX[c.indexed][-6:].lower()
    except Exception:
        pass
    return None


def _num_str(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "#NUM!"
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def _date_str(v) -> str:
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d") if (v.hour, v.minute, v.second) == (0, 0, 0) else v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, dt.timedelta):
        s = int(v.total_seconds())
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return str(v)


DATE_TOK = re.compile(r'yyyy|yy|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|am/pm|a/p|"[^"]*"|\\.|\[[^\]]*\]|.', re.I)


def _fmt_date(v, nf):
    if not nf or nf.lower() in ("general", "@") or isinstance(v, dt.timedelta):
        return _date_str(v)
    if isinstance(v, dt.time):
        v = dt.datetime.combine(dt.date(1900, 1, 1), v)
    elif not isinstance(v, dt.datetime):
        v = dt.datetime.combine(v, dt.time())
    toks = DATE_TOK.findall(nf.split(";")[0])
    if not any(t.lower()[0] in "ymdhs" for t in toks if t and t[0].isalpha()):
        return _date_str(v)  # a number format on a date: show the date
    ampm = any(t.lower() in ("am/pm", "a/p") for t in toks)
    out = []
    for i, t in enumerate(toks):
        tl = t.lower()
        if tl in ("mm", "m"):
            prev = next((x.lower() for x in reversed(toks[:i]) if x[:1].isalpha()), "")
            nxt = next((x.lower() for x in toks[i + 1:] if x[:1].isalpha()), "")
            if prev.startswith("h") or nxt.startswith("s"):
                out.append(f"{v.minute:02d}" if tl == "mm" else str(v.minute))
            else:
                out.append(f"{v.month:02d}" if tl == "mm" else str(v.month))
        elif tl == "yyyy":
            out.append(f"{v.year:04d}")
        elif tl == "yy":
            out.append(f"{v.year % 100:02d}")
        elif tl == "mmmmm":
            out.append(v.strftime("%B")[0])
        elif tl == "mmmm":
            out.append(v.strftime("%B"))
        elif tl == "mmm":
            out.append(v.strftime("%b"))
        elif tl == "dddd":
            out.append(v.strftime("%A"))
        elif tl == "ddd":
            out.append(v.strftime("%a"))
        elif tl == "dd":
            out.append(f"{v.day:02d}")
        elif tl == "d":
            out.append(str(v.day))
        elif tl in ("hh", "h"):
            hr = (v.hour % 12 or 12) if ampm else v.hour
            out.append(f"{hr:02d}" if tl == "hh" else str(hr))
        elif tl in ("ss", "s"):
            out.append(f"{v.second:02d}" if tl == "ss" else str(v.second))
        elif tl == "am/pm":
            out.append("AM" if v.hour < 12 else "PM")
        elif tl == "a/p":
            out.append("A" if v.hour < 12 else "P")
        elif t.startswith('"'):
            out.append(t[1:-1])
        elif t.startswith("\\"):
            out.append(t[1:])
        elif t.startswith("[") or t in ("_", "*"):
            pass
        else:
            out.append(t)
    return "".join(out)


def _fmt_num(v, nf):
    if not nf or nf.lower() in ("general", "@"):
        if isinstance(v, float) and not v.is_integer():
            return f"{v:.10g}"
        return _num_str(v)
    sec = nf.split(";")
    s = sec[0]
    if v < 0 and len(sec) >= 2:
        s = sec[1]
        v = abs(v)
    elif v == 0 and len(sec) >= 3:
        s = sec[2]
    s = re.sub(r"\[\$([^\]-]*)[^\]]*\]", r"\1", s)  # [$€-407] -> €
    s = re.sub(r"\[[^\]]*\]", "", s)               # [Red], [>=100] …
    s = re.sub(r"_.", " ", s)
    s = re.sub(r"\*.", "", s)
    lits = []
    s = re.sub(r'"([^"]*)"|\\(.)', lambda m: lits.append(m.group(1) if m.group(1) is not None else m.group(2)) or chr(0xE000 + len(lits) - 1), s)
    if "%" in s:
        v *= 100
    m = re.search(r"[0#?][0#?,]*(?:\.([0#?]+))?", s)
    if not m:
        out = s
    else:
        dec = len(m.group(1) or "")
        e = re.search(r"E[+-]0*", s, re.I)
        if e:
            out = s[:m.start()] + f"{v:.{dec}E}" + s[e.end():]
        else:
            num = f"{v:,.{dec}f}" if "," in m.group(0) else f"{v:.{dec}f}"
            out = s[:m.start()] + num + s[m.end():]
    out = re.sub("[-]", lambda mm: lits[ord(mm.group()) - 0xE000], out)
    return out.strip() if out.strip() else _num_str(v)


def fmt_value(v, nf=None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return _fmt_date(v, nf)
    if isinstance(v, (int, float)):
        try:
            return _fmt_num(v, nf)
        except Exception:
            return _num_str(v)
    return str(v)


def _edit_text(v) -> str:
    """What the cell editor shows for a stored value."""
    if v is None:
        return ""
    if isinstance(v, (bool, int, float)):
        return _num_str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return _date_str(v)
    s = str(v)
    if s.startswith("'") or _parse_input(s)[1] != "s":
        return "'" + s  # text that would otherwise turn into a number/date/formula
    return s


NUM_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
THOUSANDS_RE = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?")
DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def _parse_input(text):
    """Typed text -> (value, data_type, number_format_hint). A leading ' forces text, = makes a formula."""
    if text is None or text == "":
        return None, "n", None
    if not isinstance(text, str):
        return text, "n", None
    t = text
    if t.startswith("'"):
        return t[1:], "s", None
    if t.startswith("=") and len(t) > 1:
        return t, "f", None
    st = t.strip()
    if st.upper() in ("TRUE", "FALSE"):
        return st.upper() == "TRUE", "b", None
    if NUM_RE.fullmatch(st):
        int_part = st.lstrip("+-").split(".")[0].split("e")[0].split("E")[0]
        if len(int_part) > 1 and int_part.startswith("0"):
            return t, "s", None  # 007, 0042: codes, keep as text
        if re.fullmatch(r"[+-]?\d+", st):
            n = int(st)
            return (n if abs(n) < 2 ** 53 else float(n)), "n", None
        return float(st), "n", None
    if THOUSANDS_RE.fullmatch(st):
        return float(st.replace(",", "")), "n", "#,##0" + (".00" if "." in st else "")
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)%", st):
        return float(st[:-1]) / 100, "n", "0%" if "." not in st else "0.00%"
    m = DATE_RE.fullmatch(st)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if m.group(4):
                return dt.datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)), "d", "yyyy-mm-dd hh:mm"
            return dt.datetime(y, mo, d), "d", "yyyy-mm-dd"
        except ValueError:
            pass
    return t, "s", None


# ---------------------------------------------------------------- formula references
REF_RE = re.compile(
    r"(?<![\w.$!:'\"])((?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?(\$?)([A-Za-z]{1,3})(\$?)(\d+)"
    r"(?::(\$?)([A-Za-z]{1,3})(\$?)(\d+))?(?![\w(!])")
STR_SPLIT = re.compile(r'("(?:[^"]|"")*")')


def _sheet_name(prefix, host: str) -> str:
    if not prefix:
        return host
    n = prefix[:-1]
    return n[1:-1].replace("''", "'") if n.startswith("'") else n


def _quote_sheet(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][\w.]*", name) and not re.fullmatch(r"[A-Za-z]{1,3}\d+", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _map_refs(formula: str, fn) -> str:
    parts = STR_SPLIT.split(formula)
    for i in range(0, len(parts), 2):
        parts[i] = REF_RE.sub(fn, parts[i])
    return "".join(parts)


def _shift_span(a, b, kind, k, n):
    """Shift index span [a, b] (b None = single) for an insert/delete of n at k (1-based). None = deleted."""
    if kind == "insert":
        return (a + n if a >= k else a), ((b if b is not None else a) + n if (b if b is not None else a) >= k else (b if b is not None else a))
    last = k + n - 1
    if b is None or a == b:
        if k <= a <= last:
            return None
        v = a - n if a > last else a
        return v, v
    if a >= k and b <= last:
        return None
    na = a if a < k else (k if a <= last else a - n)
    nb = b if b < k else (k - 1 if b <= last else b - n)
    return (na, nb) if na <= nb else None


def shift_formula(formula, host, target, axis, kind, k, n):
    def fix(m):
        if _sheet_name(m.group(1), host) != target:
            return m.group(0)
        c1, r1 = _col_index(m.group(3)), int(m.group(5))
        rng = m.group(7) is not None
        c2, r2 = (_col_index(m.group(7)), int(m.group(9))) if rng else (c1, r1)
        if axis == "row":
            res = _shift_span(r1, r2 if rng else None, kind, k, n)
            if res is None:
                return "#REF!"
            r1, r2 = res
        else:
            res = _shift_span(c1, c2 if rng else None, kind, k, n)
            if res is None:
                return "#REF!"
            c1, c2 = res
        s = f"{m.group(1) or ''}{m.group(2)}{_col_letter(c1)}{m.group(4)}{r1}"
        if rng:
            s += f":{m.group(6)}{_col_letter(c2)}{m.group(8)}{r2}"
        return s
    return _map_refs(formula, fix)


def rename_in_formula(formula, old, new):
    def fix(m):
        if m.group(1) and _sheet_name(m.group(1), "") == old:
            return _quote_sheet(new) + "!" + m.group(0)[len(m.group(1)):]
        return m.group(0)
    return _map_refs(formula, fix)


# ---------------------------------------------------------------- tiny formula evaluator
class Unsupported(Exception):
    pass


class XlError(Exception):
    pass


EVAL_TOKEN = re.compile(r"""(?:
 (?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)(?![\w(])
|(?P<func>[A-Za-z_][\w.]*)\s*\(
|(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
|(?P<op>[-+*/^(),%])
)""", re.X)
FUNCS = {"SUM", "AVERAGE", "MIN", "MAX", "COUNT"}


class Evaluator:
    """+ - * / ^ % and SUM/AVERAGE/MIN/MAX/COUNT over A1 refs & ranges. Anything else -> Unsupported."""

    def __init__(self, sess):
        self.s = sess
        self.memo = {}
        self.active = set()

    def cell(self, ws, r, c):
        key = (id(ws), r, c)
        if key in self.memo:
            return self.memo[key]
        cell = ws._cells.get((r, c))
        if cell is None:
            return None
        v = cell._value
        if cell.data_type == "f" and isinstance(v, str):
            if key in self.active:
                raise XlError("#CIRC!")
            self.active.add(key)
            try:
                try:
                    v = Evaluator.formula(self._child(), ws, v)
                except Unsupported:
                    v = self.s.cache.get(id(ws), {}).get((r, c))
            finally:
                self.active.discard(key)
            if isinstance(v, str) and v.startswith("#"):
                v = XlError(v)
        elif cell.data_type == "e":
            v = XlError(str(v))
        self.memo[key] = v
        return v

    def _child(self):
        ch = Evaluator(self.s)
        ch.memo, ch.active = self.memo, self.active
        return ch

    def formula(self, ws, text):
        src = (text[1:] if text.startswith("=") else text).strip()
        toks = []
        pos = 0
        while pos < len(src):
            if src[pos].isspace():
                pos += 1
                continue
            m = EVAL_TOKEN.match(src, pos)
            if not m or m.end() == pos:
                raise Unsupported(src[pos:])
            kind = m.lastgroup
            toks.append((kind, m.group(kind)))
            pos = m.end()
        self.toks, self.i, self.ws = toks, 0, ws
        try:
            v = self.expr()
            if self.i != len(self.toks):
                raise Unsupported("trailing")
            v = self.scalar(v)
            return 0 if v is None else v
        except XlError as e:
            return str(e)
        except ZeroDivisionError:
            return "#DIV/0!"
        except (OverflowError, ValueError):
            return "#NUM!"

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def expr(self):
        v = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            r = self.num(self.term())
            v = self.num(v) + r if op == "+" else self.num(v) - r
        return v

    def term(self):
        v = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            r = self.num(self.unary())
            if op == "*":
                v = self.num(v) * r
            else:
                if r == 0:
                    raise XlError("#DIV/0!")
                v = self.num(v) / r
        return v

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return -self.num(self.unary())
        if self.peek() == ("op", "+"):
            self.take()
            return self.num(self.unary())
        return self.power()

    def power(self):
        v = self.postfix()
        if self.peek() == ("op", "^"):
            self.take()
            v = self.num(v) ** self.num(self.unary())
        return v

    def postfix(self):
        v = self.atom()
        while self.peek() == ("op", "%"):
            self.take()
            v = self.num(v) / 100
        return v

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return float(val)
        if kind == "ref":
            return self.ref(val)
        if kind == "func":
            name = val.upper()
            if name not in FUNCS:
                raise Unsupported(name)
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    args.append(self.expr())
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            if self.take() != ("op", ")"):
                raise Unsupported(")")
            return self.call(name, args)
        if (kind, val) == ("op", "("):
            v = self.expr()
            if self.take() != ("op", ")"):
                raise Unsupported(")")
            return v
        raise Unsupported(str(val))

    def ref(self, text):
        sheet = None
        if "!" in text:
            pre, text = text.rsplit("!", 1)
            sheet = _sheet_name(pre + "!", "")
        ws = self.ws
        if sheet is not None:
            if sheet not in self.s.wb.sheetnames:
                raise XlError("#REF!")
            ws = self.s.wb[sheet]
        parts = text.replace("$", "").split(":")
        m1 = re.fullmatch(r"([A-Za-z]+)(\d+)", parts[0])
        c1, r1 = _col_index(m1.group(1)), int(m1.group(2))
        if len(parts) == 1:
            return ("cell", self.cell(ws, r1, c1))
        m2 = re.fullmatch(r"([A-Za-z]+)(\d+)", parts[1])
        c2, r2 = _col_index(m2.group(1)), int(m2.group(2))
        r1, r2 = sorted((r1, r2))
        c1, c2 = sorted((c1, c2))
        r2 = min(r2, max(self.s.dims(ws)[0], r1))
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 2_000_000:
            raise Unsupported("range too big")
        return ("range", [self.cell(ws, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)])

    def scalar(self, v):
        if isinstance(v, tuple):
            if v[0] == "range":
                raise XlError("#VALUE!")
            v = v[1]
        if isinstance(v, XlError):
            raise v
        return v

    def num(self, v):
        v = self.scalar(v)
        if v is None:
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            try:
                return float(v.strip())
            except ValueError:
                raise XlError("#VALUE!")
        raise Unsupported(type(v).__name__)  # dates etc.

    def call(self, name, args):
        nums = []
        for a in args:
            if isinstance(a, tuple) and a[0] == "range":
                for x in a[1]:
                    if isinstance(x, XlError):
                        raise x
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        nums.append(x)
                    elif isinstance(x, (dt.date, dt.datetime, dt.time)):
                        raise Unsupported("date")
            else:
                x = self.scalar(a)
                if name == "COUNT":
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        nums.append(x)
                else:
                    nums.append(self.num(x))
        if name == "SUM":
            return sum(nums)
        if name == "COUNT":
            return len(nums)
        if name == "AVERAGE":
            if not nums:
                raise XlError("#DIV/0!")
            return sum(nums) / len(nums)
        if name == "MIN":
            return min(nums) if nums else 0
        if name == "MAX":
            return max(nums) if nums else 0
        raise Unsupported(name)


# ---------------------------------------------------------------- session
SESSIONS: dict = {}
_sessions_lock = threading.Lock()
MAX_SESSIONS = 4
PAGE_MAX = 2000
RECALC_LIMIT = 20000


def _clean_value(v):
    """pandas/numpy scalars -> plain python, NaN -> None."""
    if v is None:
        return None
    try:
        import pandas as pd
        if v is pd.NaT:
            return None
        if isinstance(v, pd.Timestamp):
            return v.to_pydatetime()
    except Exception:
        pass
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
        return int(v)
    return v


def _csv_value(s: str):
    """Keep CSV text exact: only clean numbers become numbers (so '007' stays text)."""
    if s == "":
        return None
    if s.strip() != s:
        return s
    if re.fullmatch(r"-?(0|[1-9]\d{0,14})", s):
        return int(s)
    if re.fullmatch(r"-?(0|[1-9]\d*)\.\d+", s) and len(s) < 17:
        f = float(s)
        if repr(f) == s:
            return f
    return s


def _style_of(cell):
    """cell._style, creating the default StyleArray openpyxl leaves as None on fresh cells."""
    if cell._style is None:
        from openpyxl.styles.cell_style import StyleArray
        cell._style = StyleArray()
    return cell._style


def _invert(perm, r0):
    inv = [0] * len(perm)
    for i, old in enumerate(perm):
        inv[old - r0] = r0 + i
    return inv


class SheetSession:
    def __init__(self, path):
        self.id = uuid.uuid4().hex[:12]
        self.path = Path(path)
        self.ext = ext_of(self.path)
        self.status = "loading"
        self.error = None
        self.started = time.time()
        self.wb = None
        self.cache = {}         # id(ws) -> {(r, c): cached value of a formula cell}
        self._dims = {}         # id(ws) -> [max_row, max_col]
        self._styles = {}       # style tuple -> css-ish dict
        self.formulas = None    # [(ws, r, c)] of formula cells, None = rebuild
        self.preview = None
        self.lock = threading.RLock()
        self.undo, self.redo = [], []
        self.state = self.saved_state = 0
        self._counter = 0
        self.csv = {"delimiter": "\t" if self.ext == "tsv" else ",", "encoding": "utf-8-sig"}
        self.saved_paths = {}
        self.has_drawings = False
        self.notes = []
        self.last_used = time.time()

    # ---------------- loading
    def load(self):
        try:
            e = self.ext
            if e in ("xlsx", "xlsm", "xltx", "xltm"):
                self._load_xlsx()
            elif e in ("xls", "ods"):
                self._load_frames()
            elif e in ("csv", "tsv"):
                self._load_csv()
            else:
                raise ValueError(f"Can't open .{e} as a spreadsheet")
            for ws in self.wb.worksheets:
                self.dims(ws)
            self.status = "ready"
        except Exception as ex:  # noqa
            self.error = str(ex) or ex.__class__.__name__
            self.status = "error"

    def _load_xlsx(self):
        import openpyxl
        with zipfile.ZipFile(self.path) as z:
            names = z.namelist()
        self.has_drawings = any(n.startswith(("xl/drawings/", "xl/charts/", "xl/pivotTables/", "xl/media/")) for n in names)
        self.wb = openpyxl.load_workbook(self.path, keep_vba=self.ext in ("xlsm", "xltm"), keep_links=True)
        spans = {}
        for ws in self.wb.worksheets:
            rows = [r for (r, c), cell in ws._cells.items() if cell.data_type == "f"]
            if rows:
                spans[ws.title] = (min(rows), max(rows))
        if spans:  # cached results of formulas (what Excel last calculated)
            wbv = openpyxl.load_workbook(self.path, data_only=True, read_only=True, keep_links=False)
            try:
                for title, (r1, r2) in spans.items():
                    ws = self.wb[title]
                    cache = self.cache.setdefault(id(ws), {})
                    cells = ws._cells
                    for r, row in enumerate(wbv[title].iter_rows(min_row=r1, max_row=r2, values_only=True), start=r1):
                        for c, v in enumerate(row, start=1):
                            cell = cells.get((r, c))
                            if cell is not None and cell.data_type == "f" and v is not None:
                                cache[(r, c)] = v
            finally:
                wbv.close()

    def _load_frames(self):
        import openpyxl
        import pandas as pd
        engine = {"xls": "xlrd", "ods": "odf"}[self.ext]
        frames = pd.read_excel(self.path, sheet_name=None, header=None, engine=engine)
        self.wb = openpyxl.Workbook()
        self.wb.remove(self.wb.active)
        for name, df in frames.items():
            ws = self.wb.create_sheet(str(name)[:31] or "Sheet")
            for row in df.itertuples(index=False):
                ws.append([_clean_value(v) for v in row])
        if not self.wb.worksheets:
            self.wb.create_sheet("Sheet1")
        self.notes.append(f"Opened from .{self.ext}: values only (formulas and formatting aren't read from this format).")

    def _load_csv(self):
        import openpyxl
        raw = self.path.read_bytes()
        text, enc = None, "utf-8"
        for cand in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(cand)
                enc = cand
                break
            except UnicodeDecodeError:
                continue
        if enc == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            enc = "utf-8"
        delim = "\t" if self.ext == "tsv" else ","
        if self.ext == "csv":
            try:
                delim = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
            except csv.Error:
                pass
        self.csv = {"delimiter": delim, "encoding": enc}
        self.wb = openpyxl.Workbook()
        ws = self.wb.active
        ws.title = (self.path.stem[:31] or "Sheet1").translate({ord(ch): "_" for ch in "[]:*?/\\"})
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delim):
            ws.append([_csv_value(v) for v in row])

    def make_preview(self, rows=200):
        """Quick read-only look at the first rows while the full workbook loads."""
        try:
            if self.ext in ("xlsx", "xlsm", "xltx", "xltm"):
                import openpyxl
                wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
                try:
                    ws = wb.active or wb.worksheets[0]
                    data = [[fmt_value(v) for v in r] for _, r in zip(range(rows), ws.iter_rows(values_only=True))]
                    self.preview = {"name": ws.title, "rows": data, "total": ws.max_row or len(data), "sheets": wb.sheetnames}
                finally:
                    wb.close()
            elif self.ext in ("csv", "tsv"):
                with open(self.path, encoding="utf-8-sig", errors="replace", newline="") as f:
                    data = [r for _, r in zip(range(rows), csv.reader(f, delimiter="\t" if self.ext == "tsv" else ","))]
                self.preview = {"name": self.path.stem, "rows": data, "total": None, "sheets": [self.path.stem]}
        except Exception:
            self.preview = None

    # ---------------- helpers
    def ws(self, idx):
        if self.status != "ready":
            raise ValueError("Still loading the workbook. Try again in a moment.")
        try:
            return self.wb.worksheets[int(idx)]
        except (IndexError, ValueError, TypeError):
            raise ValueError("That sheet doesn't exist any more")

    def dims(self, ws):
        d = self._dims.get(id(ws))
        if d is None:
            keys = ws._cells.keys()
            d = [max((k[0] for k in keys), default=0), max((k[1] for k in keys), default=0)]
            self._dims[id(ws)] = d
        return d

    def _grow(self, ws, r, c):
        d = self.dims(ws)
        if r > d[0]:
            d[0] = r
        if c > d[1]:
            d[1] = c

    def style_info(self, cell):
        key = tuple(_style_of(cell))
        d = self._styles.get(key)
        if d is not None:
            return d
        d = {}
        try:
            f = cell.font
            if f.b:
                d["b"] = 1
            if f.i:
                d["i"] = 1
            if f.u and f.u != "none":
                d["u"] = 1
            if f.strike:
                d["s"] = 1
            col = _hex(f.color)
            if col and col != "#000000":
                d["color"] = col
            if f.sz and float(f.sz) != 11:
                d["sz"] = float(f.sz)
            fill = cell.fill
            if fill is not None and fill.fill_type == "solid":
                fc = _hex(fill.fgColor)
                if fc:
                    d["fill"] = fc
            al = cell.alignment
            if al is not None:
                if al.horizontal in ("left", "center", "right", "justify", "centerContinuous"):
                    d["al"] = "center" if al.horizontal == "centerContinuous" else al.horizontal
                if al.wrap_text:
                    d["wrap"] = 1
            nf = cell.number_format
            if nf and nf != "General":
                d["nf"] = nf
        except Exception:
            pass
        self._styles[key] = d
        return d

    def encode(self, ws, cell, cache, styles, smap):
        v = cell._value
        st = self.style_info(cell)
        if v is None and not st:
            return None
        out = {}
        nf = st.get("nf")
        if cell.data_type == "f":
            ftxt = v if isinstance(v, str) else (getattr(v, "text", None) or str(v))
            if not str(ftxt).startswith("="):
                ftxt = "=" + str(ftxt)
            out["f"] = ftxt
            cv = cache.get((cell.row, cell.column), MISSING)
            if cv is MISSING:
                out["v"] = ftxt
                out["x"] = 1  # can't calculate this one here; Excel will
            else:
                out["v"] = fmt_value(cv, nf)
                if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                    out["n"] = 1
        else:
            out["v"] = fmt_value(v, nf)
            if isinstance(v, (int, float, dt.datetime, dt.date)) and not isinstance(v, bool):
                out["n"] = 1
            e = _edit_text(v)
            if e != out["v"]:
                out["e"] = e
        if st:
            k = id(st)
            if k not in smap:
                smap[k] = len(styles)
                styles.append(st)
            out["s"] = smap[k]
        return out

    # ---------------- reading
    def meta(self):
        out = {"sid": self.id, "status": self.status, "error": self.error, "name": self.path.name, "ext": self.ext,
               "elapsed": round(time.time() - self.started, 1), "notes": self.notes}
        if self.status != "ready":
            out["preview"] = self.preview
            return out
        sheets = []
        for ws in self.wb.worksheets:
            mr, mc = self.dims(ws)
            ncols = max(mc, 26) + 30
            widths = {}
            for key, dim in ws.column_dimensions.items():
                try:
                    if dim.width and (dim.customWidth or dim.width != 13):
                        lo, hi = dim.min or _col_index(key), dim.max or _col_index(key)
                        for c in range(lo, min(hi, ncols) + 1):
                            widths[c - 1] = 0 if dim.hidden else max(24, round(dim.width * 7 + 5))
                except Exception:
                    pass
            fr = 0
            m = re.fullmatch(r"([A-Z]+)(\d+)", str(ws.freeze_panes or ""))
            if m:
                fr = int(m.group(2)) - 1
            sheets.append({"name": ws.title, "rows": mr, "cols": mc, "widths": widths,
                           "merged": [[m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1] for m in ws.merged_cells.ranges],
                           "frozen": fr})
        act = self.wb.active
        out.update(sheets=sheets, active=self.wb.worksheets.index(act) if act in self.wb.worksheets else 0,
                   dirty=self.state != self.saved_state, can_undo=bool(self.undo), can_redo=bool(self.redo),
                   has_drawings=self.has_drawings)
        return out

    def rows(self, si, start=0, count=200, indices=None):
        ws = self.ws(si)
        mr, mc = self.dims(ws)
        cells = ws._cells
        cache = self.cache.get(id(ws), {})
        styles, smap = [], {}
        if indices is not None:
            rng = [int(i) for i in indices][:PAGE_MAX]
        else:
            rng = range(max(0, start), min(mr, start + min(count, PAGE_MAX)))
        out = []
        for r0 in rng:
            r = r0 + 1
            row = []
            if r <= mr:
                for c in range(1, mc + 1):
                    cell = cells.get((r, c))
                    row.append(None if cell is None else self.encode(ws, cell, cache, styles, smap))
                while row and row[-1] is None:
                    row.pop()
            out.append(row)
        return {"rows": out, "styles": styles}

    def value_of(self, ws, r, c):
        cell = ws._cells.get((r, c))
        if cell is None:
            return None
        if cell.data_type == "f":
            v = self.cache.get(id(ws), {}).get((r, c), MISSING)
            return cell._value if v is MISSING else v
        return cell._value

    def display(self, ws, r, c):
        cell = ws._cells.get((r, c))
        if cell is None:
            return ""
        return fmt_value(self.value_of(ws, r, c), cell.number_format)

    def range_text(self, si, r1, c1, r2, c2, raw=False):
        ws = self.ws(si)
        mr, mc = self.dims(ws)
        r2, c2 = min(r2, mr - 1), min(c2, mc - 1)
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 2_000_000:
            raise ValueError("That selection is too big to copy (over 2 million cells).")
        out = []
        for r in range(r1 + 1, r2 + 2):
            row = []
            for c in range(c1 + 1, c2 + 2):
                if raw:
                    cell = ws._cells.get((r, c))
                    row.append("" if cell is None else (cell._value if cell.data_type == "f" else _edit_text(cell._value)))
                else:
                    row.append(self.display(ws, r, c))
            out.append(row)
        return out

    def search(self, si, q, col=None):
        ws = self.ws(si)
        q = (q or "").strip().lower()
        if not q:
            return list(range(self.dims(ws)[0]))
        hits = set()
        cache = self.cache.get(id(ws), {})
        for (r, c), cell in ws._cells.items():
            if col is not None and c != col + 1:
                continue
            v = cell._value
            if v is None:
                continue
            if cell.data_type == "f":
                v = cache.get((r, c), v)
            if q in (v.lower() if isinstance(v, str) else fmt_value(v, cell.number_format).lower()):
                hits.add(r - 1)
        return sorted(hits)

    # ---------------- editing (every edit returns its inverse, which is itself an edit)
    def _snap(self, ws, r, c):
        cell = ws._cells.get((r, c))
        if cell is None:
            return (r, c, None)
        return (r, c, (cell._value, cell.data_type, tuple(_style_of(cell)), self.cache.get(id(ws), {}).get((r, c), MISSING)))

    def _restore(self, ws, items):
        from openpyxl.styles.cell_style import StyleArray
        cache = self.cache.setdefault(id(ws), {})
        for r, c, data in items:
            if data is None:
                ws._cells.pop((r, c), None)
                cache.pop((r, c), None)
                continue
            v, dtype, style, cv = data
            cell = ws._cells.get((r, c)) or ws.cell(row=r, column=c)
            cell._value = v
            cell.data_type = dtype
            cell._style = StyleArray(style)
            if cv is MISSING:
                cache.pop((r, c), None)
            else:
                cache[(r, c)] = cv
            self._grow(ws, r, c)

    def apply(self, op: dict):
        with self.lock:
            inv = self._apply(op)
            self.undo.append((inv, self.state))
            if len(self.undo) > 200:
                self.undo.pop(0)
            self.redo.clear()
            self._counter += 1
            self.state = self._counter
            return inv

    def do_undo(self):
        with self.lock:
            if not self.undo:
                return False
            inv, prev = self.undo.pop()
            back = self._apply(inv)
            self.redo.append((back, self.state))
            self.state = prev
            return True

    def do_redo(self):
        with self.lock:
            if not self.redo:
                return False
            inv, nxt = self.redo.pop()
            back = self._apply(inv)
            self.undo.append((back, self.state))
            self.state = nxt
            return True

    def _apply(self, op):
        t = op["type"]
        if t in ("add_sheet", "_remove_sheet", "_insert_sheet", "delete_sheet", "rename_sheet"):
            return self._sheet_op(op)
        ws = op["ws"] if "ws" in op else self.ws(op.get("sheet", 0))
        if t == "set":
            return self._set(ws, op["cells"])
        if t == "_restore":
            inv = [self._snap(ws, r, c) for r, c, _ in op["items"]]
            self._restore(ws, op["items"])
            self._recalc(ws, [(r, c) for r, c, _ in op["items"]])
            return {"type": "_restore", "ws": ws, "items": inv}
        if t == "fmt":
            return self._fmt(ws, op)
        if t in ("insert", "delete"):
            return self._struct(ws, op["axis"], t, int(op["at"]), max(1, int(op.get("n", 1))))
        if t == "_unstruct":
            return self._unstruct(ws, op)
        if t == "sort":
            return self._sort(ws, int(op["col"]), bool(op.get("asc", True)), bool(op.get("header", False)))
        if t == "_permute":
            self._permute(ws, op["r0"], op["perm"])
            return {"type": "_permute", "ws": ws, "r0": op["r0"], "perm": _invert(op["perm"], op["r0"])}
        if t == "col_width":
            c = int(op["col"]) + 1
            letter = _col_letter(c)
            had = letter in ws.column_dimensions and ws.column_dimensions[letter].width
            old = ws.column_dimensions[letter].width if had else None
            px = op.get("px")
            if px is None:
                if letter in ws.column_dimensions:
                    del ws.column_dimensions[letter]
            else:
                ws.column_dimensions[letter].width = round(max(1.0, (float(px) - 5) / 7), 2)
            return {"type": "col_width", "ws": ws, "col": c - 1, "px": None if old is None else old * 7 + 5}
        if t == "freeze":
            old = ws.freeze_panes
            rows = int(op.get("rows", 0))
            ws.freeze_panes = f"A{rows + 1}" if rows > 0 else None
            m = re.fullmatch(r"[A-Z]+(\d+)", str(old or ""))
            return {"type": "freeze", "ws": ws, "rows": int(m.group(1)) - 1 if m else 0}
        raise ValueError(f"Unknown edit: {t}")

    def _set(self, ws, cells):
        from openpyxl.cell.cell import MergedCell
        items, touched = [], []
        if len(cells) > 2_000_000:
            raise ValueError("Too many cells in one edit")
        cache = self.cache.setdefault(id(ws), {})
        for r0, c0, text in cells:
            r, c = int(r0) + 1, int(c0) + 1
            if r < 1 or c < 1 or c > 16384 or r > 1048576:
                continue
            cell = ws._cells.get((r, c))
            if isinstance(cell, MergedCell):
                continue
            v, dtype, nf = _parse_input(text if text is None or isinstance(text, str) else str(text))
            if cell is None and v is None:
                continue
            items.append(self._snap(ws, r, c))
            if cell is None:
                cell = ws.cell(row=r, column=c)
            cell._value = v
            cell.data_type = dtype if v is not None else "n"
            if nf and cell.number_format == "General":
                cell.number_format = nf
            cache.pop((r, c), None)
            touched.append((r, c))
            self._grow(ws, r, c)
            if dtype == "f" and self.formulas is not None:
                self.formulas.append((ws, r, c))
        self._recalc(ws, touched)
        return {"type": "_restore", "ws": ws, "items": items}

    def _fmt(self, ws, op):
        from copy import copy as cp
        from openpyxl.cell.cell import MergedCell
        from openpyxl.styles import PatternFill
        mr, mc = self.dims(ws)
        r1, c1 = int(op["r1"]) + 1, int(op["c1"]) + 1
        r2, c2 = min(int(op["r2"]) + 1, max(mr, r1)), min(int(op["c2"]) + 1, max(mc, c1))
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 3_000_000:
            raise ValueError("That range is too big to format at once")
        p = op.get("patch", {})
        items = []
        fonts, aligns, fills = {}, {}, {}
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = ws._cells.get((r, c))
                if isinstance(cell, MergedCell):
                    continue
                items.append(self._snap(ws, r, c))
                if cell is None:
                    cell = ws.cell(row=r, column=c)
                if any(k in p for k in ("b", "i", "u", "color")):
                    fid = _style_of(cell).fontId
                    nf = fonts.get(fid)
                    if nf is None:
                        f = cp(cell.font)
                        if "b" in p:
                            f.b = bool(p["b"])
                        if "i" in p:
                            f.i = bool(p["i"])
                        if "u" in p:
                            f.u = "single" if p["u"] else None
                        if "color" in p:
                            f.color = p["color"].lstrip("#").upper() if p["color"] else None
                        fonts[fid] = nf = f
                    cell.font = nf
                if "fill" in p:
                    col = (p["fill"] or "").lstrip("#").upper()
                    if col not in fills:
                        fills[col] = PatternFill("solid", fgColor=col) if col else PatternFill(fill_type=None)
                    cell.fill = fills[col]
                if "al" in p:
                    aid = _style_of(cell).alignmentId
                    a = aligns.get(aid)
                    if a is None:
                        a = cp(cell.alignment)
                        a.horizontal = p["al"] or None
                        aligns[aid] = a
                    cell.alignment = a
                if "nf" in p:
                    cell.number_format = p["nf"] or "General"
                self._grow(ws, r, c)
        return {"type": "_restore", "ws": ws, "items": items}

    def _all_formulas(self):
        out = []
        for w in self.wb.worksheets:
            for (r, c), cell in w._cells.items():
                if cell.data_type == "f" and isinstance(cell._value, str):
                    out.append((w, r, c, cell._value))
        return out

    def _struct(self, ws, axis, kind, at, n):
        from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
        k = at + 1
        snap = {"formulas": self._all_formulas(), "merges": [str(m) for m in ws.merged_cells.ranges],
                "cache": {key: dict(v) for key, v in self.cache.items()},
                "widths": {key: (d.width, d.hidden) for key, d in ws.column_dimensions.items()} if axis == "col" else None,
                "cells": None}
        if kind == "delete":
            pos = 0 if axis == "row" else 1
            snap["cells"] = [self._snap(ws, r, c) for (r, c) in list(ws._cells) if k <= (r, c)[pos] < k + n]
        new_merges = []
        for m in list(ws.merged_cells.ranges):
            lo, hi = (m.min_row, m.max_row) if axis == "row" else (m.min_col, m.max_col)
            if kind == "insert":
                if lo >= k:
                    lo, hi = lo + n, hi + n
                elif hi >= k:
                    hi += n
            else:
                res = _shift_span(lo, hi, "delete", k, n)
                if res is None:
                    continue
                lo, hi = res
            if axis == "row":
                new_merges.append(CellRange(min_col=m.min_col, max_col=m.max_col, min_row=lo, max_row=hi))
            else:
                new_merges.append(CellRange(min_col=lo, max_col=hi, min_row=m.min_row, max_row=m.max_row))
        ws.merged_cells = MultiCellRange()
        if axis == "row":
            (ws.insert_rows if kind == "insert" else ws.delete_rows)(k, n)
        else:
            (ws.insert_cols if kind == "insert" else ws.delete_cols)(k, n)
        ws.merged_cells = MultiCellRange([m for m in new_merges if m.size["rows"] * m.size["columns"] > 1])
        self._fix_merged_cells(ws)
        for w in self.wb.worksheets:
            for cell in w._cells.values():
                if cell.data_type == "f" and isinstance(cell._value, str):
                    cell._value = shift_formula(cell._value, w.title, ws.title, axis, kind, k, n)
        cache = self.cache.get(id(ws))
        if cache:
            moved = {}
            for (r, c), v in cache.items():
                idx = r if axis == "row" else c
                if kind == "insert":
                    idx2 = idx + n if idx >= k else idx
                else:
                    if k <= idx < k + n:
                        continue
                    idx2 = idx - n if idx >= k + n else idx
                moved[(idx2, c) if axis == "row" else (r, idx2)] = v
            self.cache[id(ws)] = moved
        if axis == "col":
            self._shift_widths(ws, kind, k, n)
        self._dims.pop(id(ws), None)
        self.formulas = None
        self._recalc_all()
        return {"type": "_unstruct", "ws": ws, "axis": axis, "kind": kind, "at": at, "n": n, "snap": snap}

    def _shift_widths(self, ws, kind, k, n):
        from openpyxl.worksheet.dimensions import ColumnDimension
        old = {}
        for key, d in list(ws.column_dimensions.items()):
            lo, hi = d.min or _col_index(key), d.max or _col_index(key)
            for c in range(lo, hi + 1):
                old[c] = (d.width, d.hidden)
        ws.column_dimensions.clear()
        for c, (w, hidden) in old.items():
            if kind == "insert":
                c2 = c + n if c >= k else c
            else:
                if k <= c < k + n:
                    continue
                c2 = c - n if c >= k + n else c
            letter = _col_letter(c2)
            ws.column_dimensions[letter] = ColumnDimension(ws, index=letter, width=w, hidden=hidden)

    def _fix_merged_cells(self, ws):
        """Keep the MergedCell placeholders in sync with ws.merged_cells after rows/cols move."""
        from openpyxl.cell.cell import MergedCell
        covered = set()
        for m in ws.merged_cells.ranges:
            for r in range(m.min_row, m.max_row + 1):
                for c in range(m.min_col, m.max_col + 1):
                    if (r, c) != (m.min_row, m.min_col):
                        covered.add((r, c))
        for key, cell in list(ws._cells.items()):
            if isinstance(cell, MergedCell) and key not in covered:
                del ws._cells[key]
        for key in covered:
            if not isinstance(ws._cells.get(key), MergedCell):
                ws._cells[key] = MergedCell(ws, row=key[0], column=key[1])

    def _unstruct(self, ws, op):
        from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
        from openpyxl.worksheet.dimensions import ColumnDimension
        axis, kind, at, n, snap = op["axis"], op["kind"], op["at"], op["n"], op["snap"]
        k = at + 1
        ws.merged_cells = MultiCellRange()
        if kind == "insert":  # undo an insert -> remove the band again
            (ws.delete_rows if axis == "row" else ws.delete_cols)(k, n)
        else:                 # undo a delete -> open the band and put the cells back
            (ws.insert_rows if axis == "row" else ws.insert_cols)(k, n)
            self._restore(ws, snap["cells"] or [])
        ws.merged_cells = MultiCellRange([CellRange(s) for s in snap["merges"]])
        self._fix_merged_cells(ws)
        for w, r, c, text in snap["formulas"]:
            cell = w._cells.get((r, c)) or w.cell(row=r, column=c)
            cell._value = text
            cell.data_type = "f"
        self.cache = {key: dict(v) for key, v in snap["cache"].items()}
        if snap["widths"] is not None:
            ws.column_dimensions.clear()
            for key, (w, hidden) in snap["widths"].items():
                ws.column_dimensions[key] = ColumnDimension(ws, index=key, width=w, hidden=hidden)
        self._dims.pop(id(ws), None)
        self.formulas = None
        return {"type": kind, "ws": ws, "axis": axis, "at": at, "n": n}

    def _sort(self, ws, col, asc, header):
        mr, mc = self.dims(ws)
        r0 = 2 if header else 1
        if mr < r0 + 1:
            raise ValueError("Nothing to sort")
        for m in ws.merged_cells.ranges:
            if m.max_row >= r0:
                raise ValueError("Can't sort a range that contains merged cells.")
        c = col + 1
        filled, blank = [], []
        for r in range(r0, mr + 1):
            v = self.value_of(ws, r, c)
            (blank if v is None or v == "" else filled).append((r, v))

        def key(item):
            v = item[1]
            if isinstance(v, bool):
                return (2, int(v), "")
            if isinstance(v, (int, float)):
                return (0, v, "")
            if isinstance(v, dt.datetime):
                return (0, v.timestamp(), "")
            if isinstance(v, dt.date):
                return (0, dt.datetime.combine(v, dt.time()).timestamp(), "")
            return (1, 0, str(v).lower())
        filled.sort(key=key, reverse=not asc)
        perm = [r for r, _ in filled] + [r for r, _ in blank]
        self._permute(ws, r0, perm)
        return {"type": "_permute", "ws": ws, "r0": r0, "perm": _invert(perm, r0)}

    def _permute(self, ws, r0, perm):
        newpos = {old: r0 + i for i, old in enumerate(perm)}
        cells = ws._cells
        moved = {}
        for key in [key for key in cells if key[0] in newpos]:
            cell = cells.pop(key)
            cell.row = newpos[key[0]]
            moved[(cell.row, key[1])] = cell
        cells.update(moved)
        cache = self.cache.get(id(ws))
        if cache:
            self.cache[id(ws)] = {(newpos.get(r, r), c): v for (r, c), v in cache.items()}
        self.formulas = None

    def _sheet_op(self, op):
        wb = self.wb
        t = op["type"]
        if t == "add_sheet":
            base = (op.get("name") or "Sheet").strip()[:31] or "Sheet"
            name, i = base, 1
            while name.lower() in (n.lower() for n in wb.sheetnames):
                i += 1
                name = f"{base[:27]}{i}"
            ws = wb.create_sheet(title=name)
            return {"type": "_remove_sheet", "ws": ws}
        if t in ("delete_sheet", "_remove_sheet"):
            ws = op.get("ws") or self.ws(op["sheet"])
            if len(wb.worksheets) <= 1:
                raise ValueError("A workbook needs at least one sheet")
            idx = wb._sheets.index(ws)
            wb._sheets.remove(ws)
            wb.active = 0
            return {"type": "_insert_sheet", "ws": ws, "index": idx}
        if t == "_insert_sheet":
            wb._sheets.insert(op["index"], op["ws"])
            return {"type": "_remove_sheet", "ws": op["ws"]}
        if t == "rename_sheet":
            ws = op.get("ws") or self.ws(op["sheet"])
            new = (op.get("name") or "").strip()
            if not new or len(new) > 31 or re.search(r"[\[\]:*?/\\]", new):
                raise ValueError("Sheet names need 1-31 characters and can't use [ ] : * ? / \\")
            if new.lower() != ws.title.lower() and new.lower() in (n.lower() for n in wb.sheetnames):
                raise ValueError("There's already a sheet with that name")
            old = ws.title
            ws.title = new
            for w in wb.worksheets:
                for cell in w._cells.values():
                    if cell.data_type == "f" and isinstance(cell._value, str) and "!" in cell._value:
                        cell._value = rename_in_formula(cell._value, old, new)
            return {"type": "rename_sheet", "ws": ws, "name": old}
        raise ValueError(t)

    # ---------------- recalculation of the formulas we understand
    def _formula_index(self):
        if self.formulas is None:
            self.formulas = [(w, r, c) for w, r, c, _ in self._all_formulas()]
        return self.formulas

    def _recalc(self, ws, touched):
        idx = self._formula_index()
        if len(idx) > RECALC_LIMIT:  # huge formula sheets: only the edited cells
            idx = [(ws, r, c) for r, c in touched if getattr(ws._cells.get((r, c)), "data_type", None) == "f"]
        self._eval_targets(idx)

    def _recalc_all(self):
        idx = self._formula_index()
        if len(idx) <= RECALC_LIMIT:
            self._eval_targets(idx)

    def _eval_targets(self, targets):
        ev = Evaluator(self)
        for w, r, c in targets:
            cell = w._cells.get((r, c))
            if cell is None or cell.data_type != "f" or not isinstance(cell._value, str):
                continue
            key = (id(w), r, c)
            if key in ev.memo:
                v = ev.memo[key]
                v = str(v) if isinstance(v, XlError) else v
            else:
                try:
                    v = Evaluator.formula(ev._child(), w, cell._value)
                except (Unsupported, RecursionError):
                    continue
                ev.memo[key] = XlError(v) if isinstance(v, str) and v.startswith("#") else v
            if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
                v = int(v)
            self.cache.setdefault(id(w), {})[(r, c)] = v

    # ---------------- saving
    def write(self, fmt, dest: Path, sheet=0):
        with self.lock:
            tmp = TMP / f"office_{uuid.uuid4().hex[:8]}.{fmt}"
            try:
                if fmt in ("xlsx", "xlsm", "xltx"):
                    self._write_xlsx(tmp, fmt)
                elif fmt in ("csv", "tsv"):
                    ws = self.ws(sheet)
                    same = self.ext in ("csv", "tsv")
                    delim = "\t" if fmt == "tsv" else (self.csv["delimiter"] if self.ext == "csv" else ",")
                    enc = self.csv["encoding"] if same else "utf-8-sig"
                    with open(tmp, "w", encoding=enc, newline="") as f:
                        w = csv.writer(f, delimiter=delim, lineterminator="\r\n")
                        for row in self._values(ws):
                            w.writerow([_cell_text(v) for v in row])
                elif fmt == "ods":
                    import pandas as pd
                    with pd.ExcelWriter(tmp, engine="odf") as xw:
                        for ws in self.wb.worksheets:
                            pd.DataFrame(list(self._values(ws)) or [[None]]).to_excel(xw, sheet_name=ws.title, header=False, index=False)
                elif fmt == "json":
                    data = {}
                    for ws in self.wb.worksheets:
                        rows = list(self._values(ws))
                        if not rows:
                            data[ws.title] = []
                            continue
                        head = [str(h) if h not in (None, "") else _col_letter(i + 1) for i, h in enumerate(rows[0])]
                        data[ws.title] = [{head[i]: (_date_str(v) if isinstance(v, (dt.date, dt.time, dt.timedelta)) else v)
                                           for i, v in enumerate(r)} for r in rows[1:]]
                    out = data if len(data) > 1 else next(iter(data.values()))
                    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                elif fmt == "pdf":
                    self._write_pdf(tmp)
                else:
                    raise ValueError(f"Can't save a sheet as .{fmt}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                _replace_into(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
            if fmt != "pdf":
                self.saved_state = self.state
            return dest

    def _write_xlsx(self, tmp, fmt):
        wb = self.wb
        vba = getattr(wb, "vba_archive", None)
        template = wb.template
        try:
            if fmt == "xlsx":
                wb.vba_archive = None
                wb.template = False
            wb.calculation.fullCalcOnLoad = True  # openpyxl can't store results; Excel recalculates on open
            wb.save(tmp)
        finally:
            wb.vba_archive = vba
            wb.template = template

    def _values(self, ws):
        mr, mc = self.dims(ws)
        for r in range(1, mr + 1):
            yield [self.value_of(ws, r, c) for c in range(1, mc + 1)]

    def table_html(self, sheets, max_rows=5000):
        parts, notes = [], []
        for ws in sheets:
            mr, mc = self.dims(ws)
            merged, covered = {}, set()
            for m in ws.merged_cells.ranges:
                merged[(m.min_row, m.min_col)] = (m.max_row - m.min_row + 1, m.max_col - m.min_col + 1)
                for r in range(m.min_row, m.max_row + 1):
                    for c in range(m.min_col, m.max_col + 1):
                        if (r, c) != (m.min_row, m.min_col):
                            covered.add((r, c))
            rows = []
            for r in range(1, min(mr, max_rows) + 1):
                tds = []
                for c in range(1, mc + 1):
                    if (r, c) in covered:
                        continue
                    cell = ws._cells.get((r, c))
                    st = self.style_info(cell) if cell is not None else {}
                    css = []
                    if st.get("b"):
                        css.append("font-weight:bold")
                    if st.get("i"):
                        css.append("font-style:italic")
                    if st.get("fill"):
                        css.append(f"background:{st['fill']}")
                    if st.get("color"):
                        css.append(f"color:{st['color']}")
                    v = self.value_of(ws, r, c)
                    if st.get("al"):
                        css.append(f"text-align:{st['al']}")
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        css.append("text-align:right")
                    span = merged.get((r, c))
                    attrs = (f' rowspan="{span[0]}" colspan="{span[1]}"' if span else "") + (f' style="{";".join(css)}"' if css else "")
                    tds.append(f"<td{attrs}>{_esc(self.display(ws, r, c))}</td>")
                rows.append("<tr>" + "".join(tds) + "</tr>")
            if mr > max_rows:
                notes.append(f"{ws.title}: only the first {max_rows:,} of {mr:,} rows")
            parts.append(f"<h3>{_esc(ws.title)}</h3><table>{''.join(rows)}</table>")
        return "".join(parts), notes

    def _write_pdf(self, tmp):
        cd = _office()
        if cd.HAS_EXCEL:
            x = tmp.with_suffix(".xlsx")
            try:
                self._write_xlsx(x, "xlsx")
                cd.excel_to_pdf(x, tmp, {})
            finally:
                x.unlink(missing_ok=True)
            return
        from .conv_pdf import html_to_pdf
        body, notes = self.table_html(self.wb.worksheets, 3000)
        self.notes = list(dict.fromkeys(self.notes + notes))
        wide = max(self.dims(ws)[1] for ws in self.wb.worksheets) > 6
        html_to_pdf(None, tmp, {"orientation": "landscape" if wide else "portrait"}, html=f"<body>{body}</body>")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.date, dt.time, dt.timedelta)):
        return _date_str(v)
    if isinstance(v, (int, float, bool)):
        return _num_str(v)
    return str(v)


def open_sheet(path, wait=1.5) -> SheetSession:
    s = SheetSession(path)
    with _sessions_lock:
        SESSIONS[s.id] = s
        if len(SESSIONS) > MAX_SESSIONS:  # forget the oldest sessions without unsaved edits
            for sid, old in sorted(SESSIONS.items(), key=lambda kv: kv[1].last_used):
                if len(SESSIONS) <= MAX_SESSIONS:
                    break
                if sid != s.id and old.state == old.saved_state:
                    SESSIONS.pop(sid, None)
    size = s.path.stat().st_size
    big = size > (1_000_000 if s.ext in ("xlsx", "xlsm", "xltx", "xltm") else 8_000_000)
    if big:  # show the first rows right away; the full (editable) load runs in the background
        s.make_preview()
    th = threading.Thread(target=s.load, daemon=True)
    th.start()
    if not big:
        th.join(wait)
        if th.is_alive():
            s.make_preview()
    return s


def get_session(sid) -> SheetSession:
    s = SESSIONS.get(sid)
    if s is None:
        raise ValueError("This spreadsheet session has expired. Open the file again.")
    s.last_used = time.time()
    return s


def close_session(sid):
    SESSIONS.pop(sid, None)
