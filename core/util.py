"""Shared helpers: paths, naming, native file pickers, ffmpeg lookup."""
import os
import shutil
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
# Scratch space lives outside OneDrive/Desktop so multi-GB temp files never get synced.
WORKSPACE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "EverythingConverter"
UPLOADS = WORKSPACE / "uploads"   # drag & drop files land here
TMP = WORKSPACE / "tmp"           # intermediate files for chained conversions
for d in (UPLOADS, TMP):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_OUTPUT = Path.home() / "Downloads" / "Everything Converter"


def ext_of(p) -> str:
    return Path(p).suffix.lower().lstrip(".")


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    """Return folder/stem.ext, adding ' (1)', ' (2)'... so nothing is overwritten."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}.{ext}"
    i = 1
    while candidate.exists():
        candidate = folder / f"{stem} ({i}).{ext}"
        i += 1
    return candidate


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def folder_size(folder: Path) -> int:
    total = 0
    for root, _, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def find_binary(name: str):
    """Locate ffmpeg/ffprobe: bundled ./bin first, then PATH."""
    local = APP_DIR / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if local.exists():
        return str(local)
    return shutil.which(name)


FFMPEG = find_binary("ffmpeg")
FFPROBE = find_binary("ffprobe")


def parse_ranges(spec: str, page_count: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based page indexes. Empty spec = all pages."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(page_count))
    pages = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else page_count
            step = 1 if end >= start else -1
            pages.extend(range(start - 1, end - 1 + step, step))
        else:
            pages.append(int(part) - 1)
    return [p for p in pages if 0 <= p < page_count]


def open_in_explorer(path: str, reveal: bool = True):
    p = Path(path)
    if sys.platform == "win32":
        if p.is_file() and not reveal:
            os.startfile(str(p))  # noqa — open with the default app
        elif p.is_file():
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # noqa
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p if p.is_dir() else p.parent)])


# ---------- Native pickers (run Tk in its own thread, one dialog at a time) ----------
_picker_lock = threading.Lock()


def _run_tk(fn):
    result = {}

    def worker():
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        try:
            result["value"] = fn(root)
        finally:
            root.destroy()

    with _picker_lock:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    return result.get("value")


# A desktop shell (e.g. the Microsoft Store build) can register native dialogs here:
# NATIVE_DIALOGS["files"]() -> list[str], NATIVE_DIALOGS["folder"](title) -> str | None
NATIVE_DIALOGS: dict = {}


def pick_files() -> list[str]:
    if "files" in NATIVE_DIALOGS:
        return [str(Path(p)) for p in (NATIVE_DIALOGS["files"]() or [])]
    from tkinter import filedialog
    paths = _run_tk(lambda root: filedialog.askopenfilenames(parent=root, title="Choose files"))
    return [str(Path(p)) for p in (paths or [])]


def pick_folder(title="Choose folder") -> str | None:
    if "folder" in NATIVE_DIALOGS:
        p = NATIVE_DIALOGS["folder"](title)
        return str(Path(p)) if p else None
    from tkinter import filedialog
    p = _run_tk(lambda root: filedialog.askdirectory(parent=root, title=title))
    return str(Path(p)) if p else None
