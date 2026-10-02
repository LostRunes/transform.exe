"""Cut a character out of its paper background and save web-ready mascot PNGs.

Usage:  .venv\Scripts\python tools\make_mascot.py            (processes every image in web/assets/source)
Source images named mascot-light.* / mascot-dark.* become web/assets/mascot-light.png / mascot-dark.png.
The sticker-sheet "SVG PNG JPG PDF" bubbles at the bottom are cropped away automatically."""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "assets" / "source"
OUT = ROOT / "web" / "assets"


def cutout(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # drop the format-bubbles row: cut at the first fully blank row below 60% height
    gray = im.convert("L")
    cut = h
    for y in range(int(h * 0.6), h):
        if all(gray.getpixel((x, y)) >= 200 for x in range(0, w, 3)):
            cut = y
            break
    im = im.crop((0, 0, w, cut))
    # "paper" = bright and unsaturated
    px = im.load()
    mask = Image.new("L", im.size, 0)
    mp = mask.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y]
            if min(r, g, b) > 205 and max(r, g, b) - min(r, g, b) < 22:
                mp[x, y] = 255
    # keep only paper connected to the border (white areas inside the character stay)
    for seed in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1),
                 (im.width // 2, 0), (0, im.height // 2), (im.width - 1, im.height // 2), (im.width // 2, im.height - 1)]:
        if mask.getpixel(seed) == 255:
            ImageDraw.floodfill(mask, seed, 128)
    bg = mask.point(lambda v: 255 if v == 128 else 0)
    bg = bg.filter(ImageFilter.MaxFilter(3))          # eat the light halo
    alpha = ImageChops.invert(bg).filter(ImageFilter.GaussianBlur(0.8))
    out = im.convert("RGBA")
    out.putalpha(alpha)
    return out.crop(out.getbbox())


def main():
    sources = sorted(p for p in SRC.iterdir() if p.stem.startswith("mascot")) if SRC.exists() else []
    if not sources:
        sys.exit(f"Put mascot-light.png / mascot-dark.png in {SRC}")
    for p in sources:
        im = cutout(p)
        im.thumbnail((520, 520), Image.LANCZOS)
        im.save(OUT / f"{p.stem}.png", optimize=True)
        sm = im.copy(); sm.thumbnail((96, 96), Image.LANCZOS)
        sm.save(OUT / f"{p.stem}-sm.png", optimize=True)
        print("made", OUT / f"{p.stem}.png", im.size)


if __name__ == "__main__":
    main()
