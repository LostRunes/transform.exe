"""Everything Converter — local, offline file conversion & toolbox.
Run:  python app.py   (or double-click Start.bat)"""
import io
import os
import shutil
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from core import cleanup, jobs, pdf_editor, registry
from core.util import DEFAULT_OUTPUT, UPLOADS, ext_of, human_size, open_in_explorer, pick_files, pick_folder

WEB = Path(__file__).parent / "web"
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = None  # no upload limit — your disk is the limit
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # always serve the latest UI files


# ---------------------------------------------------------------- safety: local use only
@app.before_request
def guard():
    host = (request.host or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        abort(403)  # blocks DNS-rebinding attacks
    if request.method == "POST" and request.headers.get("X-Local-App") != "1":
        abort(403)  # blocks cross-site form posts (custom header can't be sent cross-origin)


def ok(data=None, **kw):
    return jsonify({"ok": True, **(data or {}), **kw})


@app.errorhandler(Exception)
def on_error(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify({"ok": False, "error": str(e)}), code


def file_info(p: str):
    path = Path(p)
    st = path.stat()
    return {"path": str(path), "name": path.name, "ext": registry.norm(ext_of(path)), "size": st.st_size,
            "size_h": human_size(st.st_size), "is_dir": path.is_dir()}


# ---------------------------------------------------------------- static UI
@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:name>")
def static_files(name):
    return send_from_directory(WEB, name)


# ---------------------------------------------------------------- meta
@app.get("/api/caps")
def caps():
    exts = set(registry.EDGES) | {d for v in registry.EDGES.values() for d in v}
    return ok(caps=registry.capabilities(), tools=registry.public_tools(), convert_params=registry.CONVERT_PARAMS,
              default_output=str(DEFAULT_OUTPUT), inputs=registry.known_inputs(),
              categories={e: registry.category(e) for e in exts}, aliases=registry.ALIASES)


@app.post("/api/targets")
def targets():
    exts = request.json.get("exts", [])
    return ok(targets={e: registry.targets_for(e) for e in exts})


# ---------------------------------------------------------------- files
@app.post("/api/pick/files")
def api_pick_files():
    return ok(files=[file_info(p) for p in pick_files()])


@app.post("/api/pick/folder")
def api_pick_folder():
    return ok(path=pick_folder(request.json.get("title", "Choose folder") if request.is_json else "Choose folder"))


@app.post("/api/fileinfo")
def api_fileinfo():
    out = []
    for p in request.json.get("paths", []):
        p = p.strip().strip('"')
        if os.path.isfile(p):
            out.append(file_info(p))
        elif os.path.isdir(p):  # a folder: add every file inside (non-recursive)
            out += [file_info(str(c)) for c in sorted(Path(p).iterdir()) if c.is_file()]
    return ok(files=out)


@app.post("/api/upload")
def api_upload():
    """Drag & drop fallback. Files stream to disk in chunks, so size isn't limited by RAM."""
    saved = []
    for f in request.files.getlist("files"):
        folder = UPLOADS / uuid.uuid4().hex[:8]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / Path(f.filename).name
        with open(dest, "wb") as fh:
            shutil.copyfileobj(f.stream, fh, 4 << 20)
        saved.append(file_info(str(dest)))
    return ok(files=saved)


@app.get("/api/thumb")
def api_thumb():
    p = request.args["path"]
    ext = registry.norm(ext_of(p))
    if ext == "pdf":
        return send_file(io.BytesIO(pdf_editor.thumb(p, 0)), mimetype="image/png")
    from PIL import Image, ImageOps
    from core.conv_image import RASTER_IN
    if ext not in RASTER_IN and ext != "jpg":
        abort(404)
    im = ImageOps.exif_transpose(Image.open(p))
    im.thumbnail((160, 160))
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.post("/api/open")
def api_open():
    path = request.json["path"]
    if not os.path.exists(path):
        Path(path).mkdir(parents=True, exist_ok=True)  # e.g. output folder not created yet
    open_in_explorer(path, reveal=request.json.get("reveal", True))
    return ok()


# ---------------------------------------------------------------- jobs
@app.post("/api/convert")
def api_convert():
    d = request.json
    job = jobs.start_convert(d["items"], d.get("out_dir") or str(DEFAULT_OUTPUT), d.get("params", {}))
    return ok(job=job.to_dict())


@app.post("/api/tool")
def api_tool():
    d = request.json
    job = jobs.start_tool(d["tool"], d["paths"], d.get("out_dir") or str(DEFAULT_OUTPUT), d.get("params", {}))
    return ok(job=job.to_dict())


@app.get("/api/jobs")
def api_jobs():
    return ok(jobs=[j.to_dict() for j in sorted(jobs.JOBS.values(), key=lambda j: -j.created)])


@app.post("/api/jobs/<jid>/cancel")
def api_cancel(jid):
    jobs.JOBS[jid].cancel()
    return ok()


@app.post("/api/jobs/clear")
def api_jobs_clear():
    for jid in [k for k, j in jobs.JOBS.items() if j.status not in ("running", "queued")]:
        jobs.JOBS.pop(jid, None)
    return ok()


# ---------------------------------------------------------------- PDF editor
@app.get("/api/pdf/info")
def api_pdf_info():
    return ok(pdf_editor.info(request.args["path"]))


@app.get("/api/pdf/page")
def api_pdf_page():
    png = pdf_editor.render(request.args["path"], int(request.args.get("page", 0)), float(request.args.get("zoom", 1.5)))
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=0)


@app.get("/api/pdf/text")
def api_pdf_text():
    return ok(lines=pdf_editor.text_lines(request.args["path"], int(request.args.get("page", 0))))


@app.post("/api/pdf/save")
def api_pdf_save():
    d = request.json
    src = Path(d["path"])
    out_dir = Path(d.get("out_dir") or DEFAULT_OUTPUT)

    def work(job):
        tmp = job.work / f"{src.stem}_edited.pdf"
        job.message = "Applying edits…"
        res = pdf_editor.apply_edits(str(src), str(tmp), d["edits"])
        return jobs._deliver(res, out_dir)
    job = jobs.start_callable(f"Save edited {src.name}", work)
    return ok(job=job.to_dict())


# ---------------------------------------------------------------- clean-up
@app.get("/api/clean/overview")
def api_clean_overview():
    return ok(cleanup.overview(), disks=cleanup.disk_usage())


@app.post("/api/clean/app")
def api_clean_app():
    return ok(cleanup.clear_app_cache())


@app.post("/api/clean/temp")
def api_clean_temp():
    d = request.json
    return ok(cleanup.clean_temp(d["paths"], float(d.get("min_age_hours", 24))))


@app.post("/api/clean/recycle-bin")
def api_clean_rb():
    return ok(cleanup.empty_recycle_bin())


@app.post("/api/clean/scan")
def api_clean_scan():
    d = request.json
    folder = d["folder"]
    if not os.path.isdir(folder):
        raise ValueError("Folder not found")
    kind = d["kind"]
    if kind == "duplicates":
        return ok(cleanup.find_duplicates(folder, int(d.get("min_kb", 1)) * 1024))
    if kind == "large":
        return ok(cleanup.find_large(folder, min_mb=float(d.get("min_mb", 50))))
    if kind == "empty":
        return ok(cleanup.find_empty_dirs(folder))
    raise ValueError("Unknown scan")


@app.post("/api/clean/recycle")
def api_clean_recycle():
    return ok(cleanup.recycle(request.json["paths"]))


# ---------------------------------------------------------------- launch
def free_port(preferred=8765):
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port")


def open_window(url):
    """Open as a chromeless app window when Edge/Chrome is available, else the default browser."""
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for exe in candidates:
            if os.path.exists(exe):
                subprocess.Popen([exe, f"--app={url}", "--window-size=1320,880"])
                return
    webbrowser.open(url)


if __name__ == "__main__":
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Everything Converter running at {url}\n  Output folder: {DEFAULT_OUTPUT}\n  Close this window to quit.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, open_window, args=[url]).start()
    from waitress import serve
    serve(app, host="127.0.0.1", port=port, threads=12, max_request_body_size=1 << 50,
          channel_timeout=3600, inbuf_overflow=1 << 22)
