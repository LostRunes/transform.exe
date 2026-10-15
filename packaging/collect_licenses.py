"""Write THIRD-PARTY-NOTICES.txt: licence name + full licence texts of every Python package bundled in the build,
plus Python itself and the fonts. Run by build_msix.ps1 (so it always matches what was actually frozen).

Usage: python packaging\\collect_licenses.py <output.txt>
"""
import importlib.metadata as md
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# build tools - not shipped in the app
SKIP = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "fire", "termcolor"}
FLAG = {  # copyleft components that need attention before publishing (see store/LICENSES/README.md)
    "pymupdf": "AGPL-3.0 (or Artifex commercial licence) - SEE store/LICENSES/README.md",
    "pillow_heif": "BSD-3-Clause source, but the binary wheel is GPLv2 (bundles x265) - SEE store/LICENSES/README.md",
    "odfpy": "tri-licensed Apache-2.0 / GPL-2.0 / LGPL-2.1 - used under Apache-2.0",
}
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "LICENSES_BUNDLED", "LICENSE-3RD-PARTY")


def licence_of(d):
    m = d.metadata
    name = (m.get("License-Expression") or "").strip()
    if not name:
        lic = (m.get("License") or "").strip()
        name = lic.splitlines()[0][:120] if lic and len(lic) < 400 else ""
    if not name:
        cls = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
        name = " / ".join(cls)
    return name or "see licence text"


def licence_files(d):
    out = []
    for f in d.files or []:
        fname = Path(str(f)).name.upper()
        if any(fname.startswith(n) for n in LICENSE_NAMES) and ("dist-info" in str(f) or "/" in str(f).replace("\\", "/")):
            p = Path(d.locate_file(f))
            if p.is_file() and p.stat().st_size < 400_000 and p not in out:
                out.append(p)
    return out


def main(dest: Path):
    dists = sorted({d.metadata["Name"].lower(): d for d in md.distributions()}.values(), key=lambda d: d.metadata["Name"].lower())
    parts, index = [], []
    for d in dists:
        key = d.metadata["Name"].lower().replace("-", "_")
        if d.metadata["Name"].lower() in SKIP:
            continue
        lic = FLAG.get(key, licence_of(d))
        url = d.metadata.get("Home-page") or next((u.split(",", 1)[-1].strip() for u in (d.metadata.get_all("Project-URL") or [])), "")
        index.append(f"  {d.metadata['Name']:<26} {d.version:<14} {lic}")
        body = [f"{'=' * 78}\n{d.metadata['Name']} {d.version}\nLicence: {lic}\n{('Project: ' + url) if url else ''}\n"]
        for p in licence_files(d):
            body.append(f"--- {p.name} ---\n{p.read_text(encoding='utf-8', errors='replace').strip()}\n")
        parts.append("\n".join(body))
    py_lic = Path(sys.base_prefix) / "LICENSE.txt"
    if py_lic.exists():
        index.insert(0, f"  {'Python':<26} {sys.version.split()[0]:<14} PSF-2.0")
        parts.insert(0, f"{'=' * 78}\nPython {sys.version.split()[0]}\nLicence: PSF-2.0\n\n{py_lic.read_text(encoding='utf-8', errors='replace')}")
    for f in sorted((ROOT / "web" / "fonts").glob("OFL-*.txt")):
        font = f.stem.replace("OFL-", "")
        index.append(f"  {font + ' (font)':<26} {'':<14} SIL Open Font License 1.1")
        parts.append(f"{'=' * 78}\n{font} font\nLicence: SIL Open Font License 1.1\n\n{f.read_text(encoding='utf-8', errors='replace')}")
    index.append(f"  {'FFmpeg (bin/ffmpeg.exe)':<26} {'':<14} LGPL-2.1+ or GPL (depends on the build bundled) - see bin/FFMPEG-README.txt")
    index.append(f"  {'Microsoft Edge WebView2':<26} {'':<14} system component, not redistributed")

    header = ("Dr. Doc - third-party software notices\n"
              "Dr. Doc bundles the open-source components listed below. Their licence texts follow.\n"
              "Generated automatically by packaging/collect_licenses.py at build time.\n\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n".join(index) + "\n\n\n" + "\n\n".join(parts), encoding="utf-8")
    print(f"wrote {dest} ({len(index)} components)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "store" / "LICENSES" / "THIRD-PARTY-NOTICES.txt")
