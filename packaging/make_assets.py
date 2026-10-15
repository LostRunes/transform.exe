"""Generate the app icon (.ico) and every MSIX / Microsoft Store logo from packaging/logo.png.

Usage:  .venv\\Scripts\\python packaging\\make_assets.py [out_dir]     (default: packaging/assets)
Writes  <out>/drdoc.ico  and  <out>/msix/*.png  using the standard MSIX qualifier naming
(Square44x44Logo.scale-200.png, Square44x44Logo.targetsize-32_altform-unplated.png, ...), so MakeAppx/MakePri and
the Store pick the right file. Idempotent: output is regenerated every run.
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "packaging" / "logo.png"  # the Dr. Doc product logo (transparent PNG)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "assets"

SCALES = (100, 125, 150, 200, 400)
# name: (base width, base height, content fraction of the shorter side)
TILES = {
    "Square44x44Logo": (44, 44, 0.92),
    "Square150x150Logo": (150, 150, 0.66),
    "Wide310x150Logo": (310, 150, 0.70),
    "Square310x310Logo": (310, 310, 0.62),
    "SmallTile": (71, 71, 0.72),
    "StoreLogo": (50, 50, 0.92),
    "SplashScreen": (620, 300, 0.62),
}
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)


def load():
    im = Image.open(SRC).convert("RGBA")
    # crop to the visible artwork; the PNG has faint stray pixels out to its edges
    solid = im.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    full = im.crop(solid.getbbox())
    # small sizes (<= 48 px): a square around the face reads far better than the whole scene
    head = im.crop((290, 130, 920, 760))
    return full, head


def place(src: Image.Image, w: int, h: int, frac: float) -> Image.Image:
    """src centred on a transparent w×h canvas, fitting inside frac of the box."""
    box = max(1, int(round(min(w, h) * frac)))
    s = src.copy()
    s.thumbnail((box * 4, box * 4), Image.LANCZOS)  # keep ratio
    ratio = min(box / s.width, box / s.height)
    s = s.resize((max(1, round(s.width * ratio)), max(1, round(s.height * ratio))), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(s, ((w - s.width) // 2, (h - s.height) // 2))
    return canvas


def main():
    full, head = load()
    msix = OUT / "msix"
    msix.mkdir(parents=True, exist_ok=True)
    for old in msix.glob("*.png"):
        old.unlink()
    for name, (bw, bh, frac) in TILES.items():
        for sc in SCALES:
            w, h = round(bw * sc / 100), round(bh * sc / 100)
            src = head if max(w, h) <= 48 else full
            place(src, w, h, frac).save(msix / f"{name}.scale-{sc}.png", optimize=True)
    for ts in TARGET_SIZES:
        src = head if ts <= 48 else full
        img = place(src, ts, ts, 0.96)
        img.save(msix / f"Square44x44Logo.targetsize-{ts}.png", optimize=True)
        img.save(msix / f"Square44x44Logo.targetsize-{ts}_altform-unplated.png", optimize=True)
        img.save(msix / f"Square44x44Logo.targetsize-{ts}_altform-lightunplated.png", optimize=True)
    # unqualified fallbacks referenced from the manifest when no resources.pri is present
    for name in TILES:
        (msix / f"{name}.png").write_bytes((msix / f"{name}.scale-100.png").read_bytes())

    # multi-size .ico for the exe and window
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [place(head if s <= 48 else full, s, s, 0.98) for s in sizes]
    frames[-1].save(OUT / "drdoc.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    # 300x300 store listing logo + a big PNG handy for the listing / website
    place(full, 300, 300, 0.86).save(OUT / "store-logo-300.png", optimize=True)
    place(full, 1080, 1080, 0.86).save(OUT / "store-logo-1080.png", optimize=True)
    print(f"assets written to {OUT}  ({len(list(msix.glob('*.png')))} msix images)")


if __name__ == "__main__":
    main()
