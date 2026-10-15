"""Raster/vector image conversions and image tools (Pillow, vtracer, PyMuPDF)."""
import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError, features

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
    try:
        im = Image.open(path)
        if getattr(im, "n_frames", 1) > 1:
            # Animations / multi-page TIFFs: exif_transpose would return a copy of frame 1 only.
            return im
        im.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ValueError(f"Can't read this image: it's damaged, empty or not really a .{Path(path).suffix.lstrip('.').lower()} file ({e})") from None
    if im.mode in ("I", "I;16", "I;16L", "I;16B", "I;16N"):
        im = im.convert("I").point(lambda v: v * (1 / 256)).convert("L")  # 16-bit grey; a plain convert clips to white
    return ImageOps.exif_transpose(im)  # honour camera rotation


def _frames(im: Image.Image):
    """Every frame of an animation (or page of a multi-page TIFF) as RGBA, plus per-frame durations."""
    frames, durations = [], []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        fr = im
        if fr.mode in ("I", "I;16", "I;16L", "I;16B", "I;16N"):
            fr = fr.convert("I").point(lambda v: v * (1 / 256)).convert("L")
        frames.append(fr.convert("RGBA"))
        durations.append(im.info.get("duration", 100))
    im.seek(0)
    return frames, durations


def _multi(im: Image.Image, ext: str) -> bool:
    """True when im has several frames and ext can hold them all."""
    return getattr(im, "n_frames", 1) > 1 and ext in ("gif", "webp", "tiff")


def _save_frames(frames, durations, out, quality=90, ext=None):
    """Save a list of frames to a path, or to a file object when ext is given."""
    ext = ext or out.suffix.lower().lstrip(".")
    if ext == "gif":
        frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], loop=0, duration=durations, disposal=2)
    elif ext == "webp":
        frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], loop=0, duration=durations,
                       quality=int(quality), method=4)
    else:  # multi-page TIFF
        frames[0].save(out, "TIFF", save_all=True, append_images=frames[1:], compression="tiff_lzw")


def _flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[-1])
        return base
    return im.convert("RGB")


def save_image(im: Image.Image, out, quality=90, strip=True, ext=None):
    """Save to a path, or to a file object when ext is given."""
    ext = ext or out.suffix.lower().lstrip(".")
    fmt = PIL_FORMAT[ext]
    kw = {}
    if ext in NO_ALPHA:
        im = _flatten(im)
    elif im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        im = im.convert("RGBA")
    elif im.mode == "P" and "transparency" in im.info and fmt not in ("PNG", "GIF", "WEBP"):
        im = im.convert("RGBA")  # TIFF/TGA/ICO/AVIF ignore a palette's transparent index
    elif im.mode == "LA" and fmt == "GIF":
        im = im.convert("RGBA")  # GIF would drop LA's alpha entirely
    if fmt == "JPEG":
        kw.update(quality=int(quality), optimize=True, progressive=True)
    elif fmt == "WEBP":
        kw.update(quality=int(quality), method=6)
    elif fmt == "AVIF":
        kw.update(quality=int(quality))
    elif fmt == "PNG":
        kw.update(optimize=True)
    elif fmt == "ICO":
        if max(im.size) < 16:  # smaller than the smallest icon size: there'd be no image in the file at all
            im = im.resize((16, 16), Image.NEAREST)
        side = min(256, max(im.size))
        kw.update(sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side])
    elif fmt == "TIFF":
        kw.update(compression="tiff_lzw")
    if not strip and "exif" in im.info:
        kw["exif"] = im.info["exif"]
    im.save(out, fmt, **kw)


def raster_to_raster(src: Path, out: Path, params: dict):
    im = _open(src)
    quality = params.get("quality") or 90
    ext = out.suffix.lower().lstrip(".")
    pages = getattr(im, "n_frames", 1)
    if _multi(im, ext) and (ext == "tiff") == (im.format == "TIFF"):  # animation -> animation, pages -> pages
        _save_frames(*_frames(im), out, quality)
        return [out]
    if pages > 1 and im.format == "TIFF":  # multi-page TIFF -> one picture per page, like PDF -> images
        outs = []
        for i, fr in enumerate(_frames(im)[0]):
            target = out.with_name(f"{out.stem}_p{i + 1}{out.suffix}")
            save_image(fr, target, quality=quality)
            outs.append(target)
        return outs
    save_image(im, out, quality=quality)
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
    margin = max(0.0, float(params.get("margin") or 0))
    for src in srcs:
        opened = _open(src)
        # every page of a multi-page TIFF (a scan); an animation contributes its first frame
        pages = _frames(opened)[0] if opened.format == "TIFF" and getattr(opened, "n_frames", 1) > 1 else [opened]
        for page_im in pages:
            im = _flatten(page_im)
            tmp = out.parent / (out.stem + ".page.jpg")
            im.save(tmp, "JPEG", quality=int(params.get("quality") or 92))
            w, h = im.size
            if a4:
                pw, ph = (842, 595) if w > h else (595, 842)
            else:
                pw, ph = w * 72 / 96, h * 72 / 96
            m = min(margin, pw / 2 - 1, ph / 2 - 1)  # a margin bigger than the page leaves no room for the picture
            page = pdf.new_page(width=pw, height=ph)
            box = fitz.Rect(m, m, pw - m, ph - m) if m > 0 else page.rect
            page.insert_image(box, filename=str(tmp), keep_proportion=True)
            tmp.unlink(missing_ok=True)
    pdf.save(out, garbage=3, deflate=True)
    return [out]


def raster_to_pdf(src: Path, out: Path, params: dict):
    return images_to_pdf([src], out, params)


# ---------------- Image tools ----------------

LOSSY = {"jpg", "webp", "avif"}


def _encode(im: Image.Image, ext: str, quality=90, png_colors=0) -> bytes:
    if ext == "png" and png_colors:
        im = im.convert("RGBA").quantize(colors=int(png_colors), method=Image.FASTOCTREE)
    buf = io.BytesIO()
    save_image(im, buf, quality=quality, strip=True, ext=ext)
    return buf.getvalue()


def fit_image(im: Image.Image, ext: str, limit: int, png_colors=0) -> bytes:
    """Best-looking encode of im that fits in limit bytes.

    Lossy formats search quality first; if even the lowest quality is too big (or the
    format is lossless) the picture is scaled down and the search repeats."""
    from .shrink import search
    smallest = None
    cur = im
    for _ in range(10):
        if ext in LOSSY:
            hit, low = search(lambda q: _encode(cur, ext, q), 5, 95, limit)
        else:
            hit = low = None
            for colors in ([png_colors or 0, 256] if ext == "png" else [0]):
                d = _encode(cur, ext, 95, colors)
                low = d if low is None or len(d) < len(low) else low
                if len(d) <= limit:
                    hit = d
                    break
        if hit:
            return hit
        if smallest is None or len(low) < len(smallest):
            smallest = low
        # Pixels scale with area, so step the sides by the square root of what's left to shed.
        f = max(0.35, min(0.9, (limit / len(low)) ** 0.5 * 0.95))
        w, h = cur.size
        if w * f < 8 or h * f < 8:
            break
        cur = cur.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
    return smallest


def _fit_gif(src: Path, limit: int) -> bytes:
    """Animated GIF: scale every frame and cut the palette until it fits."""
    frames, durations = _frames(Image.open(src))
    smallest = None
    f = 1.0
    for colors in (256, 128, 64, 64, 32, 32, 32, 32):
        w, h = frames[0].size
        size = (max(1, round(w * f)), max(1, round(h * f)))
        scaled = [fr.resize(size, Image.LANCZOS).quantize(colors=colors, method=Image.FASTOCTREE) for fr in frames]
        buf = io.BytesIO()
        scaled[0].save(buf, "GIF", save_all=True, append_images=scaled[1:], loop=0, duration=durations, optimize=True, disposal=2)
        d = buf.getvalue()
        if smallest is None or len(d) < len(smallest):
            smallest = d
        if len(d) <= limit:
            return d
        f *= max(0.4, min(0.9, (limit / len(d)) ** 0.5 * 0.95))
    return smallest


def _anim_bytes(frames, durations, ext, quality) -> bytes:
    buf = io.BytesIO()
    _save_frames(frames, durations, buf, quality, ext=ext)
    return buf.getvalue()


def _pages_bytes(frames, quality) -> bytes:
    """Multi-page TIFF with JPEG-compressed pages (what scanners do)."""
    buf = io.BytesIO()
    pages = [_flatten(f) for f in frames]
    pages[0].save(buf, "TIFF", save_all=True, append_images=pages[1:], compression="jpeg", quality=int(quality))
    return buf.getvalue()


def tool_compress(src: Path, out_dir: Path, params: dict, ctx, unique):
    from .shrink import already_fits, budget, report, search
    size = src.stat().st_size
    limit = budget(size, params)
    done = already_fits(src, out_dir, limit, ctx, unique)
    if done:
        return done
    im = _open(src)
    target = params.get("format", "keep")
    ext = src.suffix.lower().lstrip(".") if target == "keep" else target
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff"}.get(ext, ext)
    if ext not in RASTER_OUT:
        ext = "jpg"
    side = int(params.get("max_side") or 0)
    quality = params.get("quality") or 75
    out = unique(out_dir, src.stem + "_compressed", ext)
    png_colors = int(params.get("png_colors") or 0) if ext == "png" else 0
    if _multi(im, ext):  # keep every frame of an animation / every page of a multi-page TIFF
        frames, durations = _frames(im)
        if side and max(frames[0].size) > side:
            for fr in frames:
                fr.thumbnail((side, side), Image.LANCZOS)
        if ext == "gif" and limit is not None:
            data = _fit_gif(src, limit)
        else:
            if ext == "tiff":
                enc = lambda q: _pages_bytes(frames, q)  # noqa: E731
            else:
                enc = lambda q: _anim_bytes(frames, durations, ext, q)  # noqa: E731
            if limit is None:
                data = enc(quality)
            else:
                ctx.sub_progress(0.1, f"Finding the best quality for {src.name}")
                hit, low = search(enc, 5, 95, limit)
                data = hit or low
        out.write_bytes(data)
        report(ctx, src.name, size, out.stat().st_size, limit)
        return [out]
    if side and max(im.size) > side:
        im.thumbnail((side, side), Image.LANCZOS)
    if limit is None:
        out.write_bytes(_encode(im, ext, quality, png_colors))
    else:
        ctx.sub_progress(0.1, f"Finding the best quality for {src.name}")
        data = fit_image(im, ext, limit, png_colors)
        out.write_bytes(data)
    report(ctx, src.name, size, out.stat().st_size, limit)
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
        if params.get("keep_ratio", True) and int(params.get("width") or 0) and int(params.get("height") or 0):
            f = min(tw / w, th / h)  # fit inside the box (thumbnail() rounded 100 down to 99 and never enlarged)
            size = (max(1, round(w * f)), max(1, round(h * f)))
        else:
            size = (tw, th)
    ext = src.suffix.lower().lstrip(".")
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff"}.get(ext, ext)
    out = unique(out_dir, f"{src.stem}_{size[0]}x{size[1]}", ext if ext in RASTER_OUT else "png")
    if _multi(im, ext):
        frames, durations = _frames(im)
        _save_frames([fr.resize(size, Image.LANCZOS) for fr in frames], durations, out, 95)
        return [out]
    im = im.resize(size, Image.LANCZOS)
    save_image(im, out, quality=95, strip=False)
    return [out]


def tool_transform(src: Path, out_dir: Path, params: dict, unique):
    im = _open(src)
    angle = int(params.get("rotate") or 0)

    def edit(im):
        if angle:
            im = im.rotate(-angle, expand=True)
        if params.get("flip_h"):
            im = ImageOps.mirror(im)
        if params.get("flip_v"):
            im = ImageOps.flip(im)
        if params.get("grayscale"):
            gray = ImageOps.grayscale(im)
            if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:  # keep the see-through parts
                gray = Image.merge("LA", (gray, im.convert("RGBA").getchannel("A")))
            im = gray
        return im
    ext = src.suffix.lower().lstrip(".")
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff"}.get(ext, ext)
    out = unique(out_dir, src.stem + "_edited", ext if ext in RASTER_OUT else "png")
    if _multi(im, ext):
        frames, durations = _frames(im)
        _save_frames([edit(fr) for fr in frames], durations, out, 95)
        return [out]
    save_image(edit(im), out, quality=95, strip=bool(params.get("strip_metadata")))
    return [out]
