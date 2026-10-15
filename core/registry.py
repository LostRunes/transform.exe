"""The conversion graph (any format -> any format via chained steps) and the tool catalogue."""
from collections import deque

from . import conv_data, conv_doc, conv_image, conv_media, conv_pdf, shrink
from .conv_image import RASTER_IN, RASTER_OUT

ALIASES = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "htm": "html", "markdown": "md", "aif": "aiff", "mpg": "mpeg",
           "yml": "yaml"}


def norm(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return ALIASES.get(ext, ext)


# edges[src] = {dst: (fn, needs_ctx)}
EDGES: dict[str, dict] = {}


def edge(srcs, dsts, fn, ctx=False, override=False):
    for s in srcs:
        s = norm(s)
        for d in dsts:
            d = norm(d)
            if s == d:
                continue
            slot = EDGES.setdefault(s, {})
            if override or d not in slot:
                slot[d] = (fn, ctx)


# ---------- images ----------
edge(RASTER_IN, RASTER_OUT, conv_image.raster_to_raster)
edge(RASTER_IN, ["pdf"], conv_image.raster_to_pdf)
edge(RASTER_IN, ["svg"], conv_image.raster_to_svg)
edge(["svg"], RASTER_OUT, conv_image.svg_to_raster)
edge(["svg"], ["pdf"], conv_image.svg_to_pdf)

# ---------- media (gif is both an image and a video source) ----------
MEDIA_IN = conv_media.VIDEO | {"gif"}
edge(MEDIA_IN, conv_media.VIDEO_OUT, conv_media.convert_media, ctx=True, override=True)
edge(conv_media.VIDEO, conv_media.AUDIO_OUT, conv_media.convert_media, ctx=True)
edge(conv_media.AUDIO, conv_media.AUDIO_OUT, conv_media.convert_media, ctx=True)
# gif -> gif/webp stays in Pillow (keeps animation, no re-encode needed)
edge(["gif"], ["webp", "png", "jpg"], conv_image.raster_to_raster, override=True)

# ---------- pdf ----------
edge(["pdf"], ["png", "jpg", "webp", "tiff", "bmp", "gif"], conv_pdf.pdf_to_raster)
edge(["pdf"], ["txt"], conv_pdf.pdf_to_text)
edge(["pdf"], ["html"], conv_pdf.pdf_to_html)
edge(["pdf"], ["md"], conv_pdf.pdf_to_md)
edge(["pdf"], ["docx"], conv_pdf.pdf_to_docx)

# ---------- office documents ----------
if conv_doc.HAS_WORD:
    edge(conv_doc.WORD_IN, ["pdf", "docx", "rtf", "odt", "txt", "html", "doc"], conv_doc.word_convert)
    edge(["html"], ["docx", "rtf", "odt", "doc"], conv_doc.word_convert)
    edge(["txt"], ["docx", "rtf", "odt", "doc"], conv_doc.word_convert)
edge(["docx", "docm"], ["html"], conv_doc.docx_to_html)
edge(["docx", "docm"], ["txt"], conv_doc.docx_to_txt)
edge(["docx", "docm"], ["pdf"], conv_doc.docx_to_pdf_fallback)
edge(["md"], ["html"], conv_doc.md_to_html)
edge(["md"], ["docx"], conv_doc.md_to_docx)
edge(["txt"], ["html"], conv_doc.txt_to_html)
edge(["txt"], ["docx"], conv_doc.txt_to_docx)
edge(["html"], ["pdf"], conv_pdf.html_to_pdf)
edge(["html"], ["txt"], conv_doc.html_to_txt)
edge(["html"], ["md"], conv_doc.html_to_md)
def _copy_text(src, out, params):
    """txt <-> md: same text, any input encoding, saved as UTF-8."""
    text = conv_doc.read_text(src)
    if not text.strip():
        raise ValueError("This file is empty")
    out.write_text(text, encoding="utf-8")
    return [out]


edge(["txt"], ["md"], _copy_text)
edge(["md"], ["txt"], _copy_text)

if conv_doc.HAS_POWERPOINT:
    edge(conv_doc.PPT_IN, ["pdf"], conv_doc.ppt_to_pdf)
    edge(["ppt", "pps", "odp"], ["pptx"], conv_doc.ppt_to_pptx)

# ---------- spreadsheets / data ----------
TABLE_IN = {"csv", "tsv", "xlsx", "xlsm", "xls", "json", "xml", "ods"}
edge(TABLE_IN, conv_data.DATA_OUT, conv_data.convert_table)
if conv_doc.HAS_EXCEL:
    edge(conv_doc.EXCEL_IN | {"csv"}, ["pdf"], conv_doc.excel_to_pdf)
edge(TABLE_IN, ["pdf"], conv_data.table_to_pdf)


# Multi-step routes may only pass *through* these formats (keeps chains sensible & lossless-ish).
HUBS = {"pdf", "html", "png", "docx"}
DOC_FMTS = {"pdf", "docx", "doc", "docm", "rtf", "odt", "txt", "html", "md", "wpd", "wps", "dot", "dotx",
            "ppt", "pptx", "pptm", "pps", "ppsx", "odp"}


def category(ext: str) -> str:
    if ext == "gif":
        return "gif"
    if ext == "svg" or ext in RASTER_IN or ext in RASTER_OUT:
        return "image"
    if ext in conv_media.VIDEO or ext in conv_media.VIDEO_OUT:
        return "video"
    if ext in conv_media.AUDIO or ext in conv_media.AUDIO_OUT:
        return "audio"
    if ext in TABLE_IN or ext in conv_data.DATA_OUT - {"html", "md"}:
        return "data"
    if ext in DOC_FMTS:
        return "doc"
    return "other"


ALLOWED = {  # source category -> target categories that make sense
    "image": {"image", "gif", "doc_pdf"},
    "gif": {"image", "gif", "video", "doc_pdf"},
    "video": {"video", "gif", "audio"},
    "audio": {"audio"},
    "doc": {"doc", "image", "gif"},
    "data": {"data", "doc", "image"},
}


def _allowed(src: str, dst: str) -> bool:
    sc, dc = category(src), category(dst)
    allowed = ALLOWED.get(sc, set())
    if dst == "pdf" and "doc_pdf" in allowed:
        return True
    if sc == "image" and dst == "svg" or sc == "doc" and dst == "svg":
        return True
    return dc in allowed


def _search(src: str, max_hops=3):
    """BFS from src through hub formats; returns {dst: [steps]}"""
    routes = {}
    q = deque([(src, [])])
    seen = {src}
    while q:
        node, path = q.popleft()
        if len(path) >= max_hops:
            continue
        for nxt, (fn, ctx) in EDGES.get(node, {}).items():
            if nxt in seen:
                continue
            seen.add(nxt)
            step = path + [(node, nxt, fn, ctx)]
            routes[nxt] = step
            if nxt in HUBS:
                q.append((nxt, step))
    return {d: s for d, s in routes.items() if len(s) == 1 or _allowed(src, d)}


def find_path(src_ext: str, dst_ext: str):
    src, dst = norm(src_ext), norm(dst_ext)
    return _search(src).get(dst) if src != dst else None


def targets_for(src_ext: str) -> list[str]:
    routes = _search(norm(src_ext))
    return sorted(routes, key=lambda e: (len(routes[e]), e))


def known_inputs() -> list[str]:
    return sorted(EDGES)


# ---------- tool catalogue (the UI builds forms from these) ----------
IMG = sorted(RASTER_IN)
VID = sorted(conv_media.VIDEO | {"gif"})
AV = sorted(conv_media.VIDEO | conv_media.AUDIO)
AUD = sorted(conv_media.AUDIO | conv_media.VIDEO)
TABLE = sorted(TABLE_IN)


def P(name, label, type="text", default=None, **kw):
    return {"name": name, "label": label, "type": type, "default": default, **kw}


PAGES = P("pages", "Pages (e.g. 1-3, 5, 8-; blank = all)", "text", "")


def SIZE(quality_label=None, default="percent"):
    """The shared "How small?" controls: a % slider, or a typed-in target size."""
    opts = [["percent", "Shrink by a percentage"], ["target", "Hit a target size"]]
    if quality_label:
        opts.append(["quality", quality_label])
    return [P("size_mode", "How small?", "select", default, options=opts),
            P("reduce_pct", "Make it smaller by (%)", "range", 50, min=5, max=95, step=5, show_if={"size_mode": "percent"}),
            P("target_size", "Target size (at most)", "number", 1, step="any", show_if={"size_mode": "target"}),
            P("target_unit", "Unit", "select", "MB", options=[["KB", "KB"], ["MB", "MB"], ["GB", "GB"]],
              show_if={"size_mode": "target"})]


QUALITY = {"size_mode": "quality"}
SIZED = {"size_mode": ["percent", "target"]}

TOOLS = [
    # ---- PDF ----
    dict(id="pdf_merge", cat="PDF", name="Merge PDFs", icon="⊕", multi=True, inputs=["pdf"] + IMG + ["svg"],
         desc="Combine files into one PDF in the order listed (drag to reorder). Images are added as pages.",
         out_ext="pdf", fn=conv_pdf.tool_merge, params=[]),
    dict(id="pdf_split", cat="PDF", name="Split PDF", icon="✂", inputs=["pdf"], fn=conv_pdf.tool_split,
         desc="Split into single pages, fixed-size chunks or custom ranges.",
         params=[P("mode", "Split mode", "select", "every", options=[["every", "Every page"], ["chunks", "Every N pages"], ["ranges", "Custom ranges"]]),
                 P("chunk", "N pages per file", "number", 2, show_if={"mode": "chunks"}),
                 P("ranges", "Ranges separated by ; (e.g. 1-3; 4-10; 11-)", "text", "", show_if={"mode": "ranges"})]),
    dict(id="pdf_pages", cat="PDF", name="Extract / delete / reorder pages", icon="☰", inputs=["pdf"],
         fn=conv_pdf.tool_select_pages, desc="Keep, remove or reorder pages. Reorder: list pages in the new order, e.g. 3,1,2,4-",
         params=[P("action", "Action", "select", "extract", options=[["extract", "Keep only these / reorder"], ["delete", "Delete these pages"]]),
                 P("pages", "Pages (e.g. 1-3, 5, 8-)", "text", "")]),
    dict(id="pdf_rotate", cat="PDF", name="Rotate pages", icon="↻", inputs=["pdf"], fn=conv_pdf.tool_rotate,
         params=[P("angle", "Angle", "select", "90", options=[["90", "90° clockwise"], ["180", "180°"], ["270", "90° counter-clockwise"]]), PAGES]),
    dict(id="pdf_compress", cat="PDF", name="Compress PDF", icon="⇲", inputs=["pdf"], fn=conv_pdf.tool_compress, ctx=True,
         desc="Shrink by a percentage or to an exact size: downsamples images, subsets fonts and strips junk.",
         params=[*SIZE("Pick a compression level"),
                 P("level", "Compression", "select", "medium", options=[["low", "Light (best quality)"], ["medium", "Balanced"], ["high", "Strong"], ["extreme", "Extreme (smallest)"]], show_if=QUALITY),
                 P("flatten", "If still too big, flatten pages to images (text stops being selectable)", "checkbox", False, show_if=SIZED)]),
    dict(id="pdf_watermark", cat="PDF", name="Watermark", icon="⌘", inputs=["pdf"], fn=conv_pdf.tool_watermark,
         params=[P("text", "Text", "text", "CONFIDENTIAL"), P("size", "Font size", "number", 60),
                 P("color", "Colour", "color", "#ff0000"), P("opacity", "Opacity", "range", 0.15, min=0.05, max=1, step=0.05),
                 P("diagonal", "Diagonal", "checkbox", True)]),
    dict(id="pdf_numbers", cat="PDF", name="Add page numbers", icon="#", inputs=["pdf"], fn=conv_pdf.tool_page_numbers,
         params=[P("format", "Format ({n}, {total})", "text", "{n} / {total}"),
                 P("position", "Position", "select", "bottom-center", options=[[p, p] for p in ["bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left"]]),
                 P("size", "Font size", "number", 10)]),
    dict(id="pdf_protect", cat="PDF", name="Password-protect", icon="🔒", inputs=["pdf"], fn=conv_pdf.tool_protect,
         params=[P("password", "Password", "password", "")]),
    dict(id="pdf_unlock", cat="PDF", name="Remove password", icon="🔓", inputs=["pdf"], fn=conv_pdf.tool_unlock,
         params=[P("password", "Current password", "password", "")]),
    dict(id="pdf_images", cat="PDF", name="Extract embedded images", icon="▣", inputs=["pdf"], fn=conv_pdf.tool_extract_images,
         params=[P("min_size", "Ignore images narrower than (px)", "number", 32)]),
    # ---- Images ----
    dict(id="img_compress", cat="Image", name="Compress images", icon="⇲", inputs=IMG, fn=conv_image.tool_compress, ctx=True,
         desc="Shrink by a percentage or to an exact size (e.g. under 200 KB), or pick a quality yourself.",
         params=[*SIZE("Set the quality myself"),
                 P("quality", "Quality", "range", 75, min=10, max=100, step=1, show_if=QUALITY),
                 P("max_side", "Max width/height in px (0 = keep)", "number", 0),
                 P("format", "Output format", "select", "keep", options=[["keep", "Same as input"], ["jpg", "JPG"], ["webp", "WebP (smaller)"], ["png", "PNG"]] + ([["avif", "AVIF (smallest)"]] if "avif" in RASTER_OUT else [])),
                 P("png_colors", "PNG palette colours (0 = full colour)", "number", 0, show_if={"format": "png"})]),
    dict(id="img_resize", cat="Image", name="Resize images", icon="⤢", inputs=IMG, fn=conv_image.tool_resize,
         params=[P("mode", "Resize by", "select", "percent", options=[["percent", "Percentage"], ["pixels", "Exact pixels"]]),
                 P("percent", "Percent", "range", 50, min=5, max=400, step=5, show_if={"mode": "percent"}),
                 P("width", "Width px (blank = auto)", "number", "", show_if={"mode": "pixels"}),
                 P("height", "Height px (blank = auto)", "number", "", show_if={"mode": "pixels"}),
                 P("keep_ratio", "Keep aspect ratio (fit inside)", "checkbox", True, show_if={"mode": "pixels"})]),
    dict(id="img_edit", cat="Image", name="Rotate / flip / grayscale", icon="↻", inputs=IMG, fn=conv_image.tool_transform,
         params=[P("rotate", "Rotate", "select", "0", options=[["0", "None"], ["90", "90° clockwise"], ["180", "180°"], ["270", "90° counter-clockwise"]]),
                 P("flip_h", "Flip horizontally", "checkbox", False), P("flip_v", "Flip vertically", "checkbox", False),
                 P("grayscale", "Black & white", "checkbox", False), P("strip_metadata", "Strip EXIF/GPS metadata", "checkbox", True)]),
    dict(id="img_to_pdf", cat="Image", name="Images → one PDF", icon="⊕", multi=True, inputs=IMG, out_ext="pdf",
         fn=conv_image.images_to_pdf, desc="Every image becomes a page, in the listed order.",
         params=[P("page_size", "Page size", "select", "fit", options=[["fit", "Fit to image"], ["a4", "A4"]]),
                 P("margin", "Margin (pt)", "number", 0), P("quality", "JPEG quality", "range", 92, min=30, max=100, step=1)]),
    # ---- Video / audio ----
    dict(id="vid_compress", cat="Video & Audio", name="Compress video", icon="⇲", inputs=VID, fn=conv_media.tool_compress_video, ctx=True,
         desc="Shrink by a percentage or to an exact size (two-pass, so it lands on target), or pick a quality.",
         params=[*SIZE("Set the quality myself"),
                 P("crf", "Quality (lower = better, bigger)", "range", 28, min=18, max=40, step=1, show_if=QUALITY),
                 P("max_height", "Max resolution", "select", "0", options=[["0", "Keep"], ["2160", "4K"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["360", "360p"]]),
                 P("auto_res", "Lower the resolution if the size is tight (looks far better)", "checkbox", True, show_if=SIZED),
                 P("codec", "Codec", "select", "h264", options=[["h264", "H.264 (plays everywhere)"], ["h265", "H.265 (≈40% smaller, slower)"]]),
                 P("preset", "Speed", "select", "medium", options=[["veryfast", "Fast"], ["medium", "Balanced"], ["slow", "Slow (smaller)"]])]),
    dict(id="aud_compress", cat="Video & Audio", name="Compress audio", icon="♫", inputs=sorted(conv_media.AUDIO),
         fn=conv_media.tool_compress_audio, ctx=True,
         desc="Shrink songs, voice notes and podcasts by a percentage or to an exact size.",
         params=[*SIZE("Pick a bitrate"),
                 P("bitrate", "Bitrate", "select", "96", options=[[b, b + " kbps"] for b in ["32", "48", "64", "96", "128", "160", "192"]], show_if=QUALITY),
                 P("format", "Save as", "select", "keep", options=[["keep", "Same as input (WAV/FLAC → MP3)"], ["mp3", "MP3"], ["m4a", "M4A (AAC)"], ["opus", "Opus (smallest)"]]),
                 P("channels", "Channels", "select", "auto", options=[["auto", "Automatic (mono when the size is tight)"], ["stereo", "Keep stereo"], ["mono", "Mono (half the data)"]]),
                 P("sample_rate", "Sample rate", "select", "0", options=[["0", "Automatic"], ["48000", "48 kHz"], ["44100", "44.1 kHz (CD)"], ["32000", "32 kHz"], ["22050", "22 kHz (voice)"], ["16000", "16 kHz (calls)"]])]),
    dict(id="vid_trim", cat="Video & Audio", name="Trim / cut", icon="✂", inputs=AV, fn=conv_media.tool_trim, ctx=True,
         params=[P("start", "Start (s or hh:mm:ss)", "text", "0"), P("end", "End (blank = to the end)", "text", ""),
                 P("precise", "Frame-accurate (re-encode; off = instant)", "checkbox", True)]),
    dict(id="vid_resize", cat="Video & Audio", name="Resize / rotate / speed", icon="⤢", inputs=VID, fn=conv_media.tool_resize_video, ctx=True,
         params=[P("height", "Height", "select", "720", options=[[h, h + "p"] for h in ["2160", "1440", "1080", "720", "480", "360", "240"]]),
                 P("rotate", "Rotate", "select", "none", options=[["none", "None"], ["90", "90° clockwise"], ["180", "180°"], ["270", "90° counter-clockwise"]]),
                 P("speed", "Speed", "select", "1", options=[["0.5", "0.5×"], ["0.75", "0.75×"], ["1", "1×"], ["1.25", "1.25×"], ["1.5", "1.5×"], ["2", "2×"], ["4", "4×"]])]),
    dict(id="vid_concat", cat="Video & Audio", name="Join clips", icon="⊕", multi=True, inputs=AV, fn=conv_media.tool_concat, ctx=True,
         out_ext="mp4", desc="Joins videos (or audio files) in order. Mixed sizes are letterboxed to match the first."),
    dict(id="vid_mute", cat="Video & Audio", name="Remove audio", icon="🔇", inputs=VID, fn=conv_media.tool_mute, ctx=True, params=[]),
    dict(id="vid_frames", cat="Video & Audio", name="Video → image frames", icon="▦", inputs=VID, fn=conv_media.tool_frames, ctx=True,
         params=[P("fps", "Frames per second to grab", "text", "1"), P("format", "Format", "select", "jpg", options=[["jpg", "JPG"], ["png", "PNG"]])]),
    dict(id="aud_tools", cat="Video & Audio", name="Volume / normalise audio", icon="♪", inputs=AUD, fn=conv_media.tool_audio_tools, ctx=True,
         params=[P("volume", "Volume %", "range", 100, min=10, max=400, step=5), P("normalize", "Normalise loudness", "checkbox", False),
                 P("fade_in", "Fade in (seconds)", "number", 0)]),
    # ---- Compress (anything) ----
    dict(id="compress_any", cat="Compress", name="Compress anything", icon="⇲", inputs=["*"], fn=shrink.tool_compress_any, ctx=True,
         desc="Drop photos, videos, audio, PDFs, Word/Excel/PowerPoint files or anything else. Each one is squeezed with the right engine; other files are zipped.",
         params=SIZE() + [P("flatten", "PDFs: if still too big, flatten pages to images", "checkbox", False)]),
    dict(id="doc_compress", cat="Compress", name="Compress Office documents", icon="▤", fn=shrink.tool_compress_office, ctx=True,
         inputs=sorted(shrink.OFFICE),
         desc="Word, Excel, PowerPoint and OpenDocument files: recompresses the pictures inside and repacks the file.",
         params=SIZE()),
    # ---- Data ----
    dict(id="data_merge", cat="Data", name="Merge spreadsheets", icon="⊕", multi=True, inputs=TABLE, fn=conv_data.tool_merge_tables,
         out_ext="xlsx", desc="Stack rows from several CSV/Excel/JSON files into one sheet.",
         params=[P("out_fmt", "Save as", "select", "xlsx", options=[["xlsx", "Excel"], ["csv", "CSV"], ["json", "JSON"]]),
                 P("add_source", "Add a 'source' column", "checkbox", True)]),
]
for t in TOOLS:
    t.setdefault("params", [])
    t.setdefault("multi", False)
    t.setdefault("ctx", False)
    t.setdefault("desc", "")
TOOLS_BY_ID = {t["id"]: t for t in TOOLS}


def public_tools():
    return [{k: v for k, v in t.items() if k != "fn"} for t in TOOLS]


def capabilities():
    from .util import FFMPEG
    return {"word": conv_doc.HAS_WORD, "excel": conv_doc.HAS_EXCEL, "powerpoint": conv_doc.HAS_POWERPOINT,
            "ffmpeg": bool(FFMPEG), "heic": conv_image.HEIF, "avif": "avif" in RASTER_OUT}


# Params for the Convert tab, shown depending on the target format
CONVERT_PARAMS = {
    "image": [P("quality", "Quality", "range", 90, min=10, max=100, step=1)],
    "svg": [P("svg_mode", "Tracing", "select", "color", options=[["color", "Colour"], ["bw", "Black & white"]])],
    "from_pdf_image": [P("dpi", "Resolution (DPI)", "number", 150), PAGES],
    "video": [P("crf", "Quality (lower = better)", "range", 23, min=16, max=36, step=1),
              P("preset", "Speed", "select", "medium", options=[["veryfast", "Fast"], ["medium", "Balanced"], ["slow", "Slow (smaller)"]]),
              P("fast_copy", "Fast remux, no re-encode (only if codecs fit the container)", "checkbox", False)],
    "gif": [P("fps", "GIF frames per second", "number", 12), P("width", "GIF width px", "number", 480)],
    "audio": [P("audio_bitrate", "Bitrate", "select", "192k", options=[["128k", "128 kbps"], ["192k", "192 kbps"], ["256k", "256 kbps"], ["320k", "320 kbps"]])],
}
