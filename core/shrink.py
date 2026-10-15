"""Size-targeted compression shared by every compress tool.

The UI's "How small?" controls become a byte budget here (shrink by a percentage, or
hit a typed-in size). Each engine then searches its own quality knob for the best
result that fits. This module also compresses Office files (by recompressing the
pictures inside them), zips anything else, and routes "Compress anything".
"""
import io
import shutil
import zipfile
from pathlib import Path

from .util import ext_of, human_size

UNITS = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}


def budget(src_size: int, params: dict):
    """Byte budget from the size controls, or None when the tool's own quality settings apply."""
    mode = params.get("size_mode", "quality")
    if mode == "percent":
        pct = min(99.0, max(1.0, float(params.get("reduce_pct") or 50)))
        return max(1, int(src_size * (100 - pct) / 100))
    if mode == "target":
        n = float(params.get("target_size") or 0)
        if n <= 0:
            raise ValueError("Enter a target size bigger than 0")
        return max(1, int(n * UNITS.get(params.get("target_unit", "MB"), UNITS["MB"])))
    return None


def search(encode, lo: int, hi: int, limit: int):
    """Binary-search knob in [lo, hi] (bigger = better & bigger) for the best output under limit.

    encode(knob) -> bytes. Returns (fitting bytes or None, smallest bytes seen)."""
    hit = smallest = None
    while lo <= hi:
        mid = (lo + hi) // 2
        data = encode(mid)
        if smallest is None or len(data) < len(smallest):
            smallest = data
        if len(data) <= limit:
            hit, lo = data, mid + 1
        else:
            hi = mid - 1
    return hit, smallest


def report(ctx, name: str, before: int, after: int, limit=None):
    """Tell the user what happened, especially when the budget couldn't be met."""
    if ctx is None:
        return
    pct = (1 - after / before) * 100 if before else 0
    pct = min(pct, 99) if after else pct  # "−100%" reads as "nothing left"
    msg = f"{name}: {human_size(before)} → {human_size(after)} ({'−' if pct >= 0 else '+'}{abs(pct):.0f}%)"
    if limit is not None and after > limit:
        msg += f" — couldn't get under {human_size(limit)}; this is as small as it goes"
    ctx.note(msg)


def already_fits(src: Path, out_dir: Path, limit, ctx, unique):
    """A file that's already under the target is copied as-is rather than re-encoded bigger."""
    size = src.stat().st_size
    if limit is None or size > limit:
        return None
    out = unique(out_dir, src.stem + "_compressed", ext_of(src) or "bin")
    shutil.copy2(src, out)
    if ctx:
        ctx.note(f"{src.name}: already {human_size(size)}, under the {human_size(limit)} target — copied unchanged")
    return [out]


# ---------------------------------------------------------------- Office documents

OFFICE = {"docx", "docm", "dotx", "xlsx", "xlsm", "pptx", "pptm", "ppsx", "potx", "odt", "ods", "odp", "odg", "epub"}
_PICS = {"jpg", "jpeg", "png", "bmp", "tif", "tiff"}
# (pixel scale, JPEG quality) from gentlest to harshest. Pictures keep their names and
# formats so the document's references stay valid; their on-page size is set by the
# document layout, so fewer pixels just means less detail, not a smaller picture.
OFFICE_RUNGS = [(1.0, 85), (1.0, 75), (0.85, 68), (0.75, 60), (0.6, 52), (0.5, 45), (0.4, 38), (0.3, 30), (0.22, 25)]


def _shrink_picture(data: bytes, ext: str, scale: float, quality: int) -> bytes:
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return data
    if scale < 1:
        w, h = im.size
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    if ext in ("jpg", "jpeg"):
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    elif ext == "png":
        if quality < 70:
            im = im.convert("RGBA").quantize(colors=256, method=Image.FASTOCTREE)
        im.save(buf, "PNG", optimize=True)
    elif ext == "bmp":
        im.save(buf, "BMP")
    else:
        im.save(buf, "TIFF", compression="tiff_lzw")
    out = buf.getvalue()
    return out if len(out) < len(data) else data


def _repack(entries, rung) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for info, data in entries:
            ext = info.filename.rsplit(".", 1)[-1].lower() if "." in info.filename else ""
            if rung and ext in _PICS:
                data = _shrink_picture(data, ext, *rung)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.external_attr = info.external_attr
            if info.filename == "mimetype":  # ODF/EPUB: must stay first and uncompressed
                z.writestr(zi, data, compress_type=zipfile.ZIP_STORED)
            else:
                z.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buf.getvalue()


def tool_compress_office(src: Path, out_dir: Path, params: dict, ctx, unique):
    size = src.stat().st_size
    limit = budget(size, params)
    if limit is None:
        limit = int(size * 0.6)
    done = already_fits(src, out_dir, limit, ctx, unique)
    if done:
        return done
    try:
        with zipfile.ZipFile(src) as z:
            entries = [(i, z.read(i)) for i in z.infolist()]
    except zipfile.BadZipFile:
        with open(src, "rb") as fh:
            if fh.read(2) == b"PK":  # a zip, just a broken one
                raise ValueError("This file is damaged (it can't be opened as a document)") from None
        raise ValueError("This looks like an old binary Office file (e.g. .doc/.xls). Save it as .docx/.xlsx first, or use ZIP.") from None
    ctx.sub_progress(0.1, f"Repacking {src.name}")
    data = _repack(entries, None)
    if len(data) > limit:
        rungs = OFFICE_RUNGS[::-1]  # search() wants bigger knob = better quality
        n = [0]

        def enc(k):
            n[0] += 1
            ctx.sub_progress(min(0.95, 0.1 + 0.2 * n[0]), f"Shrinking pictures in {src.name} (try {n[0]})")
            return _repack(entries, rungs[k])
        hit, smallest = search(enc, 0, len(rungs) - 1, limit)
        data = hit or min(data, smallest, key=len)
    out = unique(out_dir, src.stem + "_compressed", ext_of(src))
    out.write_bytes(data)
    report(ctx, src.name, size, len(data), limit)
    return [out]


# ---------------------------------------------------------------- anything else -> zip

def tool_zip(src: Path, out_dir: Path, params: dict, ctx, unique):
    size = src.stat().st_size
    limit = budget(size, params)
    out = unique(out_dir, src.name, "zip")
    ctx.sub_progress(0.2, f"Zipping {src.name}")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(src, src.name)
    report(ctx, src.name + " → .zip", size, out.stat().st_size, limit)
    return [out]


# ---------------------------------------------------------------- Compress anything

def tool_compress_any(src: Path, out_dir: Path, params: dict, ctx, unique):
    """Pick the right compressor for whatever was dropped in."""
    from . import conv_image, conv_media, conv_pdf
    ext = ext_of(src)
    if ext == "pdf":
        return conv_pdf.tool_compress(src, out_dir, params, ctx, unique)
    if ext in conv_image.RASTER_IN:
        return conv_image.tool_compress(src, out_dir, params, ctx, unique)
    if ext in conv_media.VIDEO:
        return conv_media.tool_compress_video(src, out_dir, params, ctx, unique)
    if ext in conv_media.AUDIO:
        return conv_media.tool_compress_audio(src, out_dir, params, ctx, unique)
    if ext in OFFICE:
        return tool_compress_office(src, out_dir, params, ctx, unique)
    return tool_zip(src, out_dir, params, ctx, unique)
