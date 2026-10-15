"""Routes for the file organiser: big previews, file details, and building PDFs in any grouping."""
import io
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from . import jobs, organize
from .util import DEFAULT_OUTPUT

bp = Blueprint("organize", __name__)


@bp.get("/api/organize/thumb")
def thumb():
    size = max(64, min(1600, int(request.args.get("size", 320))))
    png = organize.thumb(request.args["path"], size, int(request.args.get("page", 0)))
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=300)


@bp.post("/api/organize/info")
def info():
    return jsonify({"ok": True, "files": {p: organize.describe(p) for p in request.json.get("paths", [])}})


@bp.post("/api/organize/build")
def build():
    """items: [{path, rotate, pages}] in order; mode: single | each | groups."""
    d = request.json
    items = d["items"]
    if not items:
        raise ValueError("Add some files first")
    mode = d.get("mode", "single")
    n = len(items)
    if mode == "single":
        groups = [list(range(n))]
    elif mode == "each":
        groups = [[i] for i in range(n)]
    else:
        groups = organize.parse_groups(d.get("groups", ""), n, d.get("leftovers", "each"))
    params = d.get("params", {})
    out_dir = Path(d.get("out_dir") or DEFAULT_OUTPUT)
    base = (d.get("name") or "").strip()
    title = f"Make {len(groups)} PDF{'s' if len(groups) > 1 else ''} from {n} file(s)"

    def work(job):
        outs = []
        for gi, g in enumerate(groups):
            if job.cancelled:
                break
            name = organize.group_name(items, g, len(groups), base)
            out = job.work / f"{name}.pdf"
            span = (gi / len(groups), (gi + 1) / len(groups))
            organize.build([items[i] for i in g], out, params, job.work / f"g{gi}",
                           progress=lambda f, m: job.sub_progress(span[0] + (span[1] - span[0]) * f, m))
            outs += jobs._deliver([out], out_dir)
            job.note(f"{Path(outs[-1]).name}: files {', '.join(str(i + 1) for i in g)}")
        return outs
    job = jobs.start_callable(title, work)
    return jsonify({"ok": True, "job": job.to_dict()})
