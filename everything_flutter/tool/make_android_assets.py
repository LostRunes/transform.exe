"""Generate Dr. Doc's Android launcher icons and Google Play graphics from ../packaging/logo.png.

    python tool/make_android_assets.py

Writes:
  android/app/src/main/res/mipmap-*/ic_launcher.png              legacy icons (pre-Android 8)
  android/app/src/main/res/mipmap-*/ic_launcher_foreground.png   adaptive icon layers
  android/app/src/main/res/mipmap-*/ic_launcher_monochrome.png   Android 13+ themed icon
  android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml
  android/app/src/main/res/values/ic_launcher_background.xml
  store/play-icon-512.png, store/feature-graphic-1024x500.png    Play Console uploads
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent          # everything_flutter/
LOGO = HERE.parent / "packaging" / "logo.png"
RES = HERE / "android" / "app" / "src" / "main" / "res"
STORE = HERE / "store"
FONTS = HERE / "assets" / "fonts"

BG_TOP, BG_BOTTOM = (232, 220, 255), (197, 210, 255)   # the app's day-sky lilac -> periwinkle
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def load():
    im = Image.open(LOGO).convert("RGBA")
    solid = im.getchannel("A").point(lambda v: 255 if v > 40 else 0)  # ignore faint stray pixels
    full = im.crop(solid.getbbox())
    face = im.crop((290, 130, 920, 760))  # square around the face: reads well when small
    return full, feather(face)


def feather(img, inner=0.40, outer=0.50):
    """Fade a square crop out towards a circle, so no hard cut edges show in round icons."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    px = mask.load()
    cx, cy, r = w / 2, h / 2, min(w, h)
    for y in range(h):
        for x in range(w):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / r
            px[x, y] = 255 if d <= inner else 0 if d >= outer else round(255 * (outer - d) / (outer - inner))
    out = img.copy()
    out.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), mask))
    return out


def gradient(w, h):
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)) + (255,)
        for x in range(w):
            px[x, y] = c
    return g


def fit(src, box):
    s = src.copy()
    s.thumbnail((box, box), Image.LANCZOS)
    return s


def centred(canvas, img, dy=0):
    canvas.alpha_composite(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2 + dy))
    return canvas


def rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main():
    full, face = load()
    for name, d in DENSITIES.items():
        folder = RES / f"mipmap-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        # adaptive layers are 108dp; the launcher shows the middle 72dp, masks can cut down to a 66dp circle
        fg_size = round(108 * d)
        fg = centred(Image.new("RGBA", (fg_size, fg_size), (0, 0, 0, 0)), fit(face, round(fg_size * 0.70)))
        fg.save(folder / "ic_launcher_foreground.png", optimize=True)
        # themed icon: the dark outlines (eyes, face, clipboard) in white; Android tints it
        lum = fg.convert("L")
        lines = Image.composite(lum.point(lambda v: 255 if v < 110 else 0), Image.new("L", fg.size, 0),
                                fg.getchannel("A").point(lambda v: 255 if v > 200 else 0))
        mono = Image.new("RGBA", fg.size, (255, 255, 255, 0))
        mono.putalpha(lines)
        mono.save(folder / "ic_launcher_monochrome.png", optimize=True)
        # legacy 48dp icon: rounded square background + face
        size = round(48 * d)
        legacy = rounded(centred(gradient(size, size), fit(face, round(size * 0.86))), round(size * 0.22))
        legacy.save(folder / "ic_launcher.png", optimize=True)

    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background" />\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
        '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />\n'
        '</adaptive-icon>\n', encoding="utf-8")
    (RES / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        '    <color name="ic_launcher_background">#DCD8FF</color>\n</resources>\n', encoding="utf-8")

    # ---- Google Play: 512x512 icon (Play rounds the corners itself) and 1024x500 feature graphic
    STORE.mkdir(exist_ok=True)
    centred(gradient(512, 512), fit(full, 450)).convert("RGB").save(STORE / "play-icon-512.png", optimize=True)

    fg = gradient(1024, 500)
    logo = fit(full, 430)
    fg.alpha_composite(logo, (60, (500 - logo.height) // 2))
    draw = ImageDraw.Draw(fg)
    title = ImageFont.truetype(str(FONTS / "Silkscreen-Bold.ttf"), 78)
    body = ImageFont.truetype(str(FONTS / "Nunito.ttf"), 30)
    ink = (64, 62, 130)
    draw.text((540, 150), "Dr. Doc", font=title, fill=ink)
    for i, line in enumerate(["Convert, compress & scan", "to PDF, all on your phone.", "No uploads. No ads."]):
        draw.text((544, 260 + i * 44), line, font=body, fill=(70, 70, 140))
    fg.convert("RGB").save(STORE / "feature-graphic-1024x500.png", optimize=True)
    print("android icons + Play graphics written")


if __name__ == "__main__":
    main()
