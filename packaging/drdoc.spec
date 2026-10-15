# PyInstaller spec for the Dr. Doc desktop app (onedir, windowed).
# Normally run by packaging\build_msix.ps1:
#   .venv\Scripts\pyinstaller packaging\drdoc.spec --noconfirm --distpath <dist> --workpath <work>
# Whole folders (web/, core/) are collected at build time, so new feature files are picked up automatically.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "packaging" / "assets" / "drdoc.ico"

datas = [(str(ROOT / "web"), "web")]
if ICON.exists():
    datas.append((str(ICON), "assets"))
binaries = []
hiddenimports = ["app"] + collect_submodules("core")

# Packages with data files / native libs / lazy imports — collect everything.
for pkg in ("pymupdf", "fitz", "pillow_heif", "vtracer", "pdf2docx", "docx", "openpyxl", "xlrd", "odf",
            "markdown", "send2trash", "waitress", "flask", "webview", "clr_loader", "pythonnet", "proxy_tools", "bottle"):
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:  # package not installed — the feature that needs it degrades gracefully
        print(f"[drdoc.spec] skip {pkg}: {e}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "clr", "win32com", "win32com.client", "win32com.client.gencache", "pythoncom", "pywintypes", "win32api",
    "win32con", "win32gui", "winreg", "pandas", "openpyxl.cell._writer", "PIL.ImageOps", "PIL.features",
    "webview.platforms.winforms", "webview.platforms.edgechromium",
]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "IPython", "jupyter", "notebook", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android",
              "webview.platforms.cef"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DrDoc",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    version=os.environ.get("DRDOC_VERSION_FILE") or None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DrDoc")
