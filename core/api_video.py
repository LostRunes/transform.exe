"""HTTP routes for the video editor (registered automatically by app.py)."""
import io
import json
import mimetypes
import os
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

from . import jobs, video_editor as ve
from .util import DEFAULT_OUTPUT, unique_path

bp = Blueprint("video", __name__)
PROJECT_EXT = "drdocvideo"
_proxy_jobs: dict[str, str] = {}  # media path -> job id while a proxy is being made


def ok(data=None, **kw):
    return jsonify({"ok": True, **(data or {}), **kw})


def _media_path(raw: str) -> str:
    """Only serve existing media/image files (the server is local-only, but stay tidy)."""
    p = (raw or "").strip().strip('"')
    if not p or not os.path.isfile(p) or not ve.kind_of(p):
        abort(404)
    return p


# ---------------------------------------------------------------- media info
@bp.post("/api/video/info")
def info():
    out, errors = [], []
    for p in request.json.get("paths", []):
        try:
            m = ve.media_info(p)
            m["proxy_ready"] = m["playable"] or ve.proxy_path(p).exists()
            out.append(m)
        except Exception as e:
            errors.append(f"{Path(p).name}: {e}")
    return ok(media=out, errors=errors)


@bp.get("/api/video/media")
def media():
    """Stream a source file (or its preview proxy) with HTTP Range support for <video>/<audio>."""
    p = _media_path(request.args.get("path"))
    if request.args.get("proxy"):
        pp = ve.proxy_path(p)
        if not pp.exists():
            abort(404)
        p = str(pp)
    mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
    if p.lower().endswith((".mov", ".m4v")):
        mime = "video/mp4"  # Chromium plays H.264 .mov fine but is picky about the quicktime type
    return send_file(p, mimetype=mime, conditional=True, max_age=0)


@bp.get("/api/video/thumb")
def thumb():
    p = _media_path(request.args.get("path"))
    data = ve.thumb(p, float(request.args.get("t", 0) or 0), int(request.args.get("h", 90) or 90))
    return send_file(io.BytesIO(data), mimetype="image/jpeg", max_age=3600)


@bp.get("/api/video/wave")
def wave():
    return ok(ve.waveform(_media_path(request.args.get("path"))))


# ---------------------------------------------------------------- preview proxies
@bp.post("/api/video/proxy")
def proxy_start():
    p = _media_path(request.json.get("path"))
    if ve.proxy_path(p).exists():
        return ok(ready=True)
    jid = _proxy_jobs.get(p)
    if jid and jid in jobs.JOBS and jobs.JOBS[jid].status in ("queued", "running"):
        return ok(ready=False, job=jid)

    def work(job):
        ve.make_proxy(p, job)
        job.note(f"Preview ready for {Path(p).name}")
        return []  # proxies stay in the cache, nothing to deliver
    job = jobs.start_callable(f"Preview copy of {Path(p).name}", work)
    _proxy_jobs[p] = job.id
    return ok(ready=False, job=job.id)


@bp.get("/api/video/proxy")
def proxy_status():
    p = _media_path(request.args.get("path"))
    if ve.proxy_path(p).exists():
        return ok(ready=True, status="done")
    j = jobs.JOBS.get(_proxy_jobs.get(p, ""))
    return ok(ready=False, status=j.status if j else "none", progress=j.to_dict()["progress"] if j else 0,
              error=(j.errors[-1] if j and j.errors else None))


# ---------------------------------------------------------------- export
@bp.post("/api/video/export")
def export():
    d = request.json
    project, settings = d["project"], d.get("settings", {})
    out_dir = Path(d.get("out_dir") or DEFAULT_OUTPUT)
    name = d.get("name") or "edited"
    # Validate up front so obvious mistakes come back as an error toast instead of a failed job.
    ve.build_export(project, settings, Path("check." + settings.get("format", "mp4")), jobs.TMP)

    def work(job):
        res = ve.export(project, settings, job, job.work, name)
        return jobs._deliver(res, out_dir)
    job = jobs.start_callable(f"Export {name}.{settings.get('format', 'mp4')}", work)
    return ok(job=job.to_dict())


# ---------------------------------------------------------------- projects
@bp.post("/api/video/project/save")
def project_save():
    d = request.json
    out_dir = Path(d.get("out_dir") or DEFAULT_OUTPUT)
    name = "".join(ch for ch in (d.get("name") or "my video") if ch not in '<>:"/\\|?*').strip() or "my video"
    target = d.get("path")  # re-save to the same project file when we have one
    if target and Path(target).suffix.lower() == "." + PROJECT_EXT and Path(target).parent.is_dir():
        dest = Path(target)
    else:
        dest = unique_path(out_dir, name, PROJECT_EXT)
    data = dict(d["project"], app="Dr. Doc video editor", version=1)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, dest)
    return ok(path=str(dest))


@bp.post("/api/video/project/load")
def project_load():
    p = Path(request.json["path"])
    if p.suffix.lower() != "." + PROJECT_EXT:
        raise ValueError("Not a .drdocvideo project file")
    data = json.loads(p.read_text(encoding="utf-8"))
    missing = []
    for m in data.get("media", []):
        if not os.path.isfile(m.get("path", "")):
            m["missing"] = True
            missing.append(m.get("name") or m.get("path"))
        else:
            m.pop("missing", None)
            m["proxy_ready"] = m.get("playable") or ve.proxy_path(m["path"]).exists()
    return ok(project=data, path=str(p), missing=missing)
