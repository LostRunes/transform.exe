"""Background job queue with progress, logs and cancellation."""
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import registry
from .conv_media import Cancelled
from .util import TMP, ext_of, unique_path

_pool = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, "Job"] = {}


class Job:
    def __init__(self, title, n_items):
        self.id = uuid.uuid4().hex[:10]
        self.title = title
        self.status = "queued"
        self.n = max(1, n_items)
        self.i = 0
        self.sub = 0.0
        self.message = "Waiting…"
        self.outputs: list[str] = []
        self.errors: list[str] = []
        self.created = time.time()
        self.finished = None
        self.cancelled = False
        self._proc = None
        self.work = TMP / self.id
        self.work.mkdir(parents=True, exist_ok=True)

    # ctx API used by converters
    def register_proc(self, proc):
        self._proc = proc

    def sub_progress(self, frac, msg=None):
        self.sub = frac
        if msg:
            self.message = msg

    def cancel(self):
        self.cancelled = True
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass

    def to_dict(self):
        return {"id": self.id, "title": self.title, "status": self.status, "message": self.message,
                "progress": 1.0 if self.status in ("done", "error") else min(1.0, (self.i + self.sub) / self.n),
                "outputs": self.outputs, "errors": self.errors, "created": self.created, "finished": self.finished}


def _deliver(paths, out_dir: Path) -> list[str]:
    """Move results from the job's work dir into the output folder without overwriting anything."""
    delivered = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        if p.is_dir():
            dest = out_dir / p.name
            n = 1
            while dest.exists():
                dest = out_dir / f"{p.name} ({n})"
                n += 1
        else:
            dest = unique_path(out_dir, p.stem, p.suffix.lstrip("."))
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        delivered.append(str(dest))
    return delivered


def _work_unique(folder, stem, ext):
    return unique_path(folder, stem, ext)


def _run(job: Job, body):
    job.status = "running"
    try:
        body()
        job.status = "error" if job.errors and not job.outputs else "done"
        if job.status == "done":
            job.message = f"Finished — {len(job.outputs)} file(s)" + (f", {len(job.errors)} failed" if job.errors else "")
        else:
            job.message = "Failed"
    except Cancelled:
        job.status, job.message = "cancelled", "Cancelled"
    except Exception as e:
        traceback.print_exc()
        job.status, job.message = "error", str(e)
        job.errors.append(str(e))
    finally:
        job.finished = time.time()
        shutil.rmtree(job.work, ignore_errors=True)


def submit(job: Job, body):
    JOBS[job.id] = job
    _pool.submit(_run, job, body)
    return job


# ------------------------------------------------------------------ convert

def start_convert(items: list[dict], out_dir: str, params: dict) -> Job:
    """items: [{path, target}]"""
    out = Path(out_dir)
    job = Job(f"Convert {len(items)} file(s)", len(items))

    def body():
        for idx, it in enumerate(items):
            if job.cancelled:
                raise Cancelled()
            job.i, job.sub = idx, 0
            src = Path(it["path"])
            target = registry.norm(it["target"])
            job.message = f"{src.name} → {target.upper()}"
            try:
                chain = registry.find_path(ext_of(src), target)
                if not chain:
                    raise ValueError(f"No route from .{ext_of(src)} to .{target}")
                current = [src]
                step_dir = job.work / f"f{idx}"
                for n, (a, b, fn, needs_ctx) in enumerate(chain):
                    step_dir_n = step_dir / str(n)
                    step_dir_n.mkdir(parents=True, exist_ok=True)
                    nxt = []
                    for f in current:
                        o = step_dir_n / f"{src.stem}.{b}"
                        res = fn(f, o, params, job) if needs_ctx else fn(f, o, params)
                        nxt.extend(res)
                    current = nxt
                job.outputs += _deliver(current, out)
            except Cancelled:
                raise
            except Exception as e:
                traceback.print_exc()
                job.errors.append(f"{src.name}: {e}")
        job.i, job.sub = job.n, 0
    return submit(job, body)


# ------------------------------------------------------------------ tools

def start_tool(tool_id: str, paths: list[str], out_dir: str, params: dict) -> Job:
    tool = registry.TOOLS_BY_ID[tool_id]
    fn = tool["fn"]
    out = Path(out_dir)
    srcs = [Path(p) for p in paths]
    job = Job(f"{tool['name']} ({len(srcs)} file(s))", 1 if tool["multi"] else len(srcs))

    def body():
        if tool["multi"]:
            if len(srcs) < 1:
                raise ValueError("Add at least one file")
            ext = params.get("out_fmt") or tool.get("out_ext") or ext_of(srcs[0])
            if tool_id == "vid_concat" and ext_of(srcs[0]) in registry.conv_media.AUDIO:
                ext = ext_of(srcs[0]) if ext_of(srcs[0]) in registry.conv_media.AUDIO_OUT else "mp3"
            suffix = {"pdf_merge": "merged", "vid_concat": "joined"}.get(tool_id, "combined")
            o = job.work / f"{srcs[0].stem}_{suffix}.{ext}"
            job.message = tool["name"] + "…"
            res = fn(srcs, o, params, job) if tool["ctx"] else fn(srcs, o, params)
            job.outputs += _deliver(res, out)
            return
        for idx, src in enumerate(srcs):
            if job.cancelled:
                raise Cancelled()
            job.i, job.sub = idx, 0
            job.message = f"{tool['name']}: {src.name}"
            try:
                if tool["ctx"]:
                    res = fn(src, job.work, params, job, _work_unique)
                else:
                    res = fn(src, job.work, params, _work_unique)
                job.outputs += _deliver(res, out)
            except Cancelled:
                raise
            except Exception as e:
                traceback.print_exc()
                job.errors.append(f"{src.name}: {e}")
        job.i = job.n
    return submit(job, body)


def start_callable(title: str, fn) -> Job:
    """Generic job for one-off work (e.g. saving the PDF editor). fn(job) -> list[paths]"""
    job = Job(title, 1)

    def body():
        job.outputs += [str(p) for p in fn(job)]
    return submit(job, body)
