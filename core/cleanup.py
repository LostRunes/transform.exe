"""Clean-up: app cache, Windows temp files, duplicate / large / empty-folder finders.
Everything the user picks goes to the Recycle Bin, except temp files, which are deleted outright."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from send2trash import send2trash

from .util import TMP, UPLOADS, folder_size, human_size

SKIP_DIRS = {"$Recycle.Bin", "System Volume Information", "Windows", "Program Files", "Program Files (x86)",
             "ProgramData", "AppData", ".git", "node_modules", "__pycache__", ".venv"}


def temp_locations():
    locs = {Path(tempfile.gettempdir())}
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"
    if win.exists():
        locs.add(win)
    la = os.environ.get("LOCALAPPDATA")
    if la:
        for sub in ("CrashDumps", r"Microsoft\Windows\INetCache", r"D3DSCache"):
            p = Path(la) / sub
            if p.exists():
                locs.add(p)
    return sorted(locs)


def overview():
    app = folder_size(UPLOADS) + folder_size(TMP)
    temps = []
    for loc in temp_locations():
        size, count = 0, 0
        for root, _, files in os.walk(loc):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                    count += 1
                except OSError:
                    pass
        temps.append({"path": str(loc), "size": size, "size_h": human_size(size), "files": count})
    return {"app_cache": app, "app_cache_h": human_size(app), "temp": temps, "recycle_bin": recycle_bin_size()}


def clear_app_cache():
    freed = folder_size(UPLOADS) + folder_size(TMP)
    for d in (UPLOADS, TMP):
        for child in d.iterdir():
            try:
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            except OSError:
                pass  # in use by a running job
    return {"freed": freed, "freed_h": human_size(freed)}


def clean_temp(paths: list[str], min_age_hours: float = 24):
    """Delete temp files older than min_age_hours. Files in use are skipped silently."""
    allowed = {str(p) for p in temp_locations()}
    cutoff = time.time() - min_age_hours * 3600
    freed = deleted = skipped = 0
    for base in paths:
        if base not in allowed:
            continue
        for root, dirs, files in os.walk(base, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    st = os.stat(fp)
                    if st.st_mtime > cutoff:
                        skipped += 1
                        continue
                    os.remove(fp)
                    freed += st.st_size
                    deleted += 1
                except OSError:
                    skipped += 1
            if root != base:
                try:
                    os.rmdir(root)  # only succeeds when empty
                except OSError:
                    pass
    return {"freed": freed, "freed_h": human_size(freed), "deleted": deleted, "skipped": skipped}


def recycle_bin_size():
    if os.name != "nt":
        return None
    try:
        import ctypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        return {"size": info.i64Size, "size_h": human_size(info.i64Size), "items": info.i64NumItems}
    except Exception:
        return None


def empty_recycle_bin():
    import ctypes
    before = recycle_bin_size() or {"size": 0}
    # flags: no confirmation, no progress UI, no sound
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return {"freed": before["size"], "freed_h": human_size(before["size"])}


def _walk(folder: Path):
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            yield p, st


def find_duplicates(folder: str, min_size=1024, ctx=None):
    by_size = defaultdict(list)
    for p, st in _walk(Path(folder)):
        if st.st_size >= min_size:
            by_size[st.st_size].append(p)
    candidates = [g for g in by_size.values() if len(g) > 1]

    def digest(path, limit=None):
        h = hashlib.blake2b(digest_size=20)
        with open(path, "rb") as fh:
            read = 0
            while chunk := fh.read(1 << 20):
                h.update(chunk)
                read += len(chunk)
                if limit and read >= limit:
                    break
        return h.hexdigest()

    groups = []
    total = len(candidates)
    for i, group in enumerate(candidates):
        if ctx:
            ctx.sub_progress(i / max(1, total), f"Hashing {i}/{total} size groups")
            if ctx.cancelled:
                break
        quick = defaultdict(list)
        for p in group:  # first 64 KB, then full hash only for real candidates
            try:
                quick[digest(p, 1 << 16)].append(p)
            except OSError:
                pass
        for q in quick.values():
            if len(q) < 2:
                continue
            full = defaultdict(list)
            for p in q:
                try:
                    full[digest(p)].append(p)
                except OSError:
                    pass
            for same in full.values():
                if len(same) > 1:
                    size = os.path.getsize(same[0])
                    same.sort(key=lambda p: (os.path.getmtime(p), len(p)))  # oldest first = "original"
                    groups.append({"size": size, "size_h": human_size(size), "files": same,
                                   "wasted": size * (len(same) - 1)})
    groups.sort(key=lambda g: -g["wasted"])
    wasted = sum(g["wasted"] for g in groups)
    return {"groups": groups, "wasted": wasted, "wasted_h": human_size(wasted)}


def find_large(folder: str, top=200, min_mb=50):
    items = []
    for p, st in _walk(Path(folder)):
        if st.st_size >= min_mb * 1024 * 1024:
            items.append({"path": p, "size": st.st_size, "size_h": human_size(st.st_size),
                          "modified": st.st_mtime})
    items.sort(key=lambda x: -x["size"])
    return {"files": items[:top]}


def find_empty_dirs(folder: str):
    empty = []
    for root, dirs, files in os.walk(folder, topdown=False):
        if Path(root).name in SKIP_DIRS:
            continue
        try:
            if not os.listdir(root) and root != folder:
                empty.append(root)
        except OSError:
            pass
    return {"folders": empty}


def recycle(paths: list[str]):
    done, failed, freed = [], [], 0
    for p in paths:
        try:
            size = os.path.getsize(p) if os.path.isfile(p) else 0
            send2trash(os.path.normpath(p))
            done.append(p)
            freed += size
        except Exception as e:
            failed.append({"path": p, "error": str(e)})
    return {"recycled": done, "failed": failed, "freed": freed, "freed_h": human_size(freed)}


def disk_usage():
    out = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                try:
                    u = shutil.disk_usage(root)
                    out.append({"drive": root, "total": u.total, "free": u.free, "used": u.used,
                                "total_h": human_size(u.total), "free_h": human_size(u.free)})
                except OSError:
                    pass
    else:
        u = shutil.disk_usage("/")
        out.append({"drive": "/", "total": u.total, "free": u.free, "used": u.used,
                    "total_h": human_size(u.total), "free_h": human_size(u.free)})
    return out
