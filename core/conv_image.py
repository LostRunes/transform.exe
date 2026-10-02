"""Raster/vector image conversions and image tools (Pillow, vtracer, PyMuPDF)."""
from pathlib import Path

from PIL import Image, ImageOps, features

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:
    HEIF = False

RASTER_IN = {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff", "ico", "tga", "ppm", "pgm", "pbm", "jfif", "dib"}
if HEIF:
    RASTER_IN |= {"heic", "heif"}
RASTER_OUT = {"jpg", "png", "webp", "bmp", "gif", "tiff", "ico", "tga"}
if features.check("avif"):
    RASTER_IN.add("avif")
    RASTER_OUT.add("avif")

PIL_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "bmp": "BMP", "gif": "GIF",
              "tiff": "TIFF", "tif": "TIFF", "ico": "ICO", "tga": "TGA", "avif": "AVIF"}
NO_ALPHA = {"jpg", "jpeg", "bmp"}


def _open(path) -> Image.Image:
    im = Image.open(path)
    return ImageOps.exif_transpose(im)  # honour camera rotation


def _flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[-1])
        return base
    return im.convert("RGB")


def save_image(im: Image.Image, out: Path, quality=90, strip=True):
    ext = out.suffix.lower().lstrip(".")
    fmt = PIL_FORMAT[ext]
    kw = {}
    if ext in NO_ALPHA:
        im = _flatten(im)
    elif im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        im = im.convert("RGBA")
    if fmt == "JPEG":
        kw.update(quality=int(quality), optimize=True, progressive=True)
    elif fmt == "WEBP":
        kw.update(quality=int(quality), method=6)
    elif fmt == "AVIF":
        kw.update(quality=int(quality))
    elif fmt == "PNG":
        kw.update(optimize=True)
    elif fmt == "ICO":
        side = min(256, max(im.size))
        kw.update(sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side])
    elif fmt == "TIFF":
        kw.update(compression="tiff_lzw")
    if not strip and "exif" in im.info:
        kw["exif"] = im.info["exif"]
    im.save(out, fmt, **kw)


def raster_to_raster(src: Path, out: Path, params: dict):
    im = _open(src)
    if getattr(im, "is_animated", False) and out.suffix.lower() in (".gif", ".webp"):
        frames = []
        try:
            while True:
                frames.append(im.copy())
                im.seek(im.tell() + 1)
        except EOFError:
            pass
        frames[0].save(out, save_all=True, append_images=frames[1:], loop=0,
                       duration=im.info.get("duration", 100))
        return [out]
    save_image(im, out, quality=params.get("quality", 90))
    return [out]


def raster_to_svg(src: Path, out: Path, params: dict):
    import vtracer
    tmp = out.with_suffix(".tmp.png")
    _open(src).convert("RGBA").save(tmp)
    try:
        mode = params.get("svg_mode", "color")
        vtracer.convert_image_to_svg_py(
            str(tmp), str(out),
            colormode="binary" if mode == "bw" else "color",
            mode="spline", filter_speckle=4, color_precision=6, layer_difference=16,
        )
    finally:
        tmp.unlink(missing_ok=True)
    return [out]


def svg_to_raster(src: Path, out: Path, params: dict):
    import pymupdf as fitz
    scale = float(params.get("scale", 2))
    with fitz.open(src) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
        tmp = out.with_suffix(".tmp.png")
        pix.save(tmp)
    im = Image.open(tmp)
    im.load()
    tmp.unlink(missing_ok=True)
    save_image(im, out, quality=params.get("quality", 92))
    return [out]


def svg_to_pdf(src: Path, out: Path, params: dict):
    import pymupdf as fitz
    with fitz.open(src) as doc:
        pdf = fitz.open("pdf", doc.convert_to_pdf())
        pdf.save(out)
    return [out]


def images_to_pdf(srcs: list[Path], out: Path, params: dict):
    """One PDF, one image per page. page_size: 'fit' (page = image) or 'a4'."""
    import pymupdf as fitz
    pdf = fitz.open()
    a4 = params.get("page_size", "fit") == "a4"
    margin = float(params.get("margin", 0))
    for src in srcs:
        im = _flatten(_open(src))
        tmp = out.parent / (out.stem + ".page.jpg")
        im.save(tmp, "JPEG", quality=int(params.get("quality", 92)))
        w, h = im.size
        if a4:
            pw, ph = (842, 595) if w > h else (595, 842)
        else:
            pw, ph = w * 72 / 96, h * 72 / 96
        page = pdf.new_page(width=pw, height=ph)
        box = fitz.Rect(margin, margin, pw - margin, ph - margin)
        page.insert_image(box, filename=str(tmp), keep_proportion=True)
        tmp.unlink(missing_ok=True)
    pdf.save(out, garbage=3, deflate=True)
    return [out]


def raster_to_pdf(src: Path, out: Path, params: dict):
    return images_to_pdf([src], out, params)


# ---------------- Image tools ----------------

def tool_compress(src: Path, out_dir: Path, params: dict, unique):
    im = _open(src)
    target = params.get("format", "keep")
    ext = src.suffix.lower().lstrip(".") if target == "keep" else target
    if ext not in RASTER_OUT:
        ext = "jpg"
    side = int(params.get("max_side") or 0)
    if side and max(im.size) > side:
        im.thumbnail((side, side), Image.LANCZOS)
    out = unique(out_dir, src.stem + "_compressed", ext)
    if ext == "png" and params.get("png_colors"):
        im = im.convert("RGBA").quantize(colors=int(params["png_colors"]), method=Image.FASTOCTREE)
    save_image(im, out, quality=params.get("quality", 75), strip=True)
    return [out]


def tool_resize(src: Path, out_dir: Path, params: dict, unique):
    im = _open(src)
    w, h = im.size
    mode = params.get("mode", "percent")
    if mode == "percent":
        f = float(params.get("percent", 50)) / 100
        size = (max(1, round(w * f)), max(1, round(h * f)))
    else:
        tw, th = int(params.get("width") or 0), int(params.get("height") or 0)
        if tw and not th:
            th = round(h * tw / w)
        elif th and not tw:
            tw = round(w * th / h)
        elif not tw and not th:
            tw, th = w, h
        if params.get("keep_ratio", True) and tw and th:
            im.thumbnail((tw, th), Image.LANCZOS)
            size = im.size
        else:
            size = (tw, th)
    im = im.resize(size, Image.LANCZOS)
    ext = src.suffix.lower().lstrip(".")
    out = unique(out_dir, f"{src.stem}_{size[0]}x{size[1]}", ext if ext in RASTER_OUT else "png")
    save_image(im, out, quality=95, strip=False)
    return [out]


def tool_transform(src: Path, out_dir: Path, params: dict, unique):
    im = _open(src)
    angle = int(params.get("rotate", 0))
    if angle:
        im = im.rotate(-angle, expand=True)
    if params.get("flip_h"):
        im = ImageOps.mirror(im)
    if params.get("flip_v"):
        im = ImageOps.flip(im)
    if params.get("grayscale"):
        im = ImageOps.grayscale(im)
    ext = src.suffix.lower().lstrip(".")
    out = unique(out_dir, src.stem + "_edited", ext if ext in RASTER_OUT else "png")
    save_image(im, out, quality=95, strip=bool(params.get("strip_metadata")))
    return [out]
