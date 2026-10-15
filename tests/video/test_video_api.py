"""HTTP tests for /api/video/* using Flask's test client.
Run:  .venv\\Scripts\\python.exe tests\\video\\test_video_api.py [media_dir]   (run test_video_export.py first to create media)"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import app as server  # noqa: E402
from core import jobs, video_editor as ve  # noqa: E402

MEDIA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "drdoc_video_test"
OUT = MEDIA / "api_out"
OUT.mkdir(parents=True, exist_ok=True)
H = {"X-Local-App": "1"}
c = server.app.test_client()
R = []


def check(name, cond, info=""):
    R.append((name, bool(cond), info))


def post(path, body):
    return c.post(path, json=body, headers=H, base_url="http://127.0.0.1")


def get(path, **kw):
    return c.get(path, base_url="http://127.0.0.1", **kw)


def wait_job(jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = jobs.JOBS[jid]
        if j.status in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    return jobs.JOBS[jid]


paths = [str(MEDIA / n) for n in ("a1080.mp4", "clip.mkv", "pic.png", "song.mp3", "r720rot.mp4")]
r = post("/api/video/info", {"paths": paths + [str(MEDIA / "nope.txt")]})
d = r.get_json()
check("info: 5 media + 1 error", r.status_code == 200 and len(d["media"]) == 5 and len(d["errors"]) == 1, d.get("errors"))
media = {Path(m["path"]).name: m for m in d["media"]}
check("info: kinds", [media[n]["kind"] for n in ("a1080.mp4", "pic.png", "song.mp3")] == ["video", "image", "audio"])
check("info: rotated clip is portrait", (media["r720rot.mp4"]["width"], media["r720rot.mp4"]["height"]) == (720, 1280))

check("POST without header is 403", c.post("/api/video/info", json={"paths": []}, base_url="http://127.0.0.1").status_code == 403)
check("foreign host is 403", c.get("/api/video/media?path=" + paths[0], base_url="http://evil.com").status_code == 403)

# range requests for <video>
r = get("/api/video/media", query_string={"path": paths[0]}, headers={"Range": "bytes=0-99"})
check("media: Range -> 206 + 100 bytes", r.status_code == 206 and len(r.data) == 100 and r.headers.get("Content-Type") == "video/mp4", r.status_code)
r = get("/api/video/media", query_string={"path": paths[0]})
check("media: full file 200 + Accept-Ranges", r.status_code == 200 and r.headers.get("Accept-Ranges") == "bytes")
check("media: non-media path 404", get("/api/video/media", query_string={"path": str(ROOT / "app.py")}).status_code == 404)

r = get("/api/video/thumb", query_string={"path": paths[0], "t": 1, "h": 60})
check("thumb: jpeg", r.status_code == 200 and r.data[:2] == b"\xff\xd8", r.status_code)
r = get("/api/video/thumb", query_string={"path": paths[2], "h": 60})
check("thumb: image file", r.status_code == 200 and r.data[:2] == b"\xff\xd8")
r = get("/api/video/wave", query_string={"path": paths[3]})
w = r.get_json()
check("wave: ~20 peaks/sec", r.status_code == 200 and abs(len(w["peaks"]) - 12 * 20) <= 2 and max(w["peaks"]) == 1.0, len(w.get("peaks", [])))

# proxy for the mkv (unplayable in the browser)
pp = ve.proxy_path(paths[1])
if pp.exists():
    pp.unlink()
r = post("/api/video/proxy", {"path": paths[1]})
d = r.get_json()
check("proxy: job started", d.get("ready") is False and d.get("job"))
j = wait_job(d["job"])
check("proxy: job done", j.status == "done", j.errors)
d = get("/api/video/proxy", query_string={"path": paths[1]}).get_json()
check("proxy: status ready", d["ready"] is True)
r = get("/api/video/media", query_string={"path": paths[1], "proxy": 1}, headers={"Range": "bytes=0-1023"})
check("proxy: served as mp4 with Range", r.status_code == 206 and r.headers.get("Content-Type") == "video/mp4")
check("proxy: second POST is instant", post("/api/video/proxy", {"path": paths[1]}).get_json()["ready"] is True)

# export job end to end
ids = {n: "m" + str(i) for i, n in enumerate(media)}
proj = {"media": [dict(m, id=ids[n]) for n, m in media.items()],
        "clips": [{"id": "c1", "media": ids["a1080.mp4"], "kind": "video", "in": 1, "out": 3, "speed": 1, "volume": 1},
                  {"id": "c2", "media": ids["pic.png"], "kind": "image", "dur": 2, "trans": {"type": "crossfade", "dur": 0.5}},
                  {"id": "c3", "media": ids["clip.mkv"], "kind": "video", "in": 0, "out": 2, "speed": 2, "volume": 1}],
        "texts": [{"id": "t1", "text": "Hello: 'world' 100%", "start": 0, "end": 2, "x": 0.5, "y": 0.5, "size": 8, "color": "#ff00ff", "box": True}],
        "music": [{"id": "mu", "media": ids["song.mp3"], "start": 0.5, "in": 0, "out": 10, "volume": 0.7, "fade_out": 1}],
        "music_mode": "duck"}
settings = {"format": "mp4", "resolution": "480p", "aspect": "9:16", "fps": "25", "crf": 28}
r = post("/api/video/export", {"project": proj, "settings": settings, "out_dir": str(OUT), "name": "api test"})
d = r.get_json()
check("export: job started", r.status_code == 200 and d["ok"], d)
j = wait_job(d["job"]["id"])
check("export: job done with output", j.status == "done" and j.outputs and Path(j.outputs[0]).exists(), (j.status, j.errors))
if j.outputs:
    from core.conv_media import probe
    info = probe(Path(j.outputs[0]))
    dur = float(info["format"]["duration"])
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    check("export: duration 2+2+1-0.5 = 4.5s", abs(dur - 4.5) <= 0.2, dur)
    check("export: 480x854 vertical", (v["width"], v["height"]) == (480, 854), (v["width"], v["height"]))
    check("export: has notes", bool(j.notes), j.notes)
r = post("/api/video/export", {"project": {"media": [], "clips": []}, "settings": settings, "out_dir": str(OUT)})
check("export: empty timeline -> error JSON", r.status_code == 500 and r.get_json()["ok"] is False and "empty" in r.get_json()["error"])

# export cancel
long_proj = dict(proj, clips=[dict(proj["clips"][0], id=f"c{i}") for i in range(40)], texts=[], music=[])
d = post("/api/video/export", {"project": long_proj, "settings": {"format": "webm", "resolution": "1080p"}, "out_dir": str(OUT), "name": "cancel me"}).get_json()
time.sleep(1.5)
post(f"/api/jobs/{d['job']['id']}/cancel", {})
j = wait_job(d["job"]["id"])
check("export: cancel works", j.status == "cancelled", j.status)

# projects
r = post("/api/video/project/save", {"project": proj, "name": "My: video?", "out_dir": str(OUT)})
d = r.get_json()
check("project: saved with safe name", d["ok"] and d["path"].endswith(".drdocvideo") and "My video" in Path(d["path"]).name, d.get("path"))
saved = d["path"]
r2 = post("/api/video/project/save", {"project": proj, "name": "My: video?", "out_dir": str(OUT)}).get_json()
check("project: second save doesn't overwrite", r2["path"] != saved, r2["path"])
r3 = post("/api/video/project/save", {"project": proj, "name": "x", "out_dir": str(OUT), "path": saved}).get_json()
check("project: re-save to its own file", r3["path"] == saved)
d = post("/api/video/project/load", {"path": saved}).get_json()
check("project: load round-trip", d["ok"] and len(d["project"]["clips"]) == 3 and d["missing"] == [])
broken = json.loads(Path(saved).read_text())
broken["media"][0]["path"] = str(MEDIA / "gone.mp4")
bp = OUT / "broken.drdocvideo"
bp.write_text(json.dumps(broken))
d = post("/api/video/project/load", {"path": str(bp)}).get_json()
check("project: missing media reported", len(d["missing"]) == 1 and d["project"]["media"][0].get("missing"))
check("project: wrong extension rejected", post("/api/video/project/load", {"path": paths[0]}).status_code == 500)

check("static: /web/video.js served", get("/web/video.js").status_code == 200)
check("static: /web/video.css served", get("/web/video.css").status_code == 200)

print("\n==== video editor API tests ====")
for name, good, info in R:
    print(f"{'PASS' if good else 'FAIL'}  {name}" + ("" if good else f"   -> {info}"))
fails = sum(1 for x in R if not x[1])
print(f"{len(R) - fails}/{len(R)} passed")
sys.exit(1 if fails else 0)
