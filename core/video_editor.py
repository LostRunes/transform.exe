"""Video editor backend: media probing, preview proxies, thumbnails, waveforms and the export graph.

A project is plain JSON (also saved as .drdocvideo):
  media: [{id, path, kind: video|audio|image, duration, width, height, fps, has_audio}]
  clips: main track, laid end to end. {id, media, in, out, dur (images), speed, volume, muted,
         fade_in, fade_out, rotate, crop:{t,b,l,r} (fractions), eq:{brightness, contrast, saturation},
         trans:{type: none|crossfade, dur}}   (trans = transition from the previous clip into this one)
  texts: [{id, text, start, end, x, y (0..1 within the free space), size (% of frame height), color, box}]
  music: [{id, media, start, in, out, volume, fade_in, fade_out}]
  music_mode: mix | duck | replace
The timeline maths (clip_dur / layout) is mirrored in web/video.js, keep both in sync.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .conv_media import NO_WINDOW, codec_args, probe, run_ffmpeg
from .util import APP_DIR, FFMPEG, WORKSPACE, ext_of, h264_args

VIDEO_EXT = {"mp4", "mkv", "mov", "avi", "webm", "flv", "wmv", "m4v", "mpeg", "mpg", "3gp", "ts", "mts", "m2ts", "ogv", "vob", "gif"}
AUDIO_EXT = {"mp3", "wav", "aac", "flac", "ogg", "m4a", "opus", "wma", "aiff", "aif", "amr", "ac3", "mka"}
IMAGE_EXT = {"png", "jpg", "jpeg", "jfif", "webp", "bmp", "tif", "tiff"}

# What Chromium / WebView2 can play natively; anything else gets a low-res H.264 proxy.
PLAY_CONTAINERS = {"mp4", "m4v", "mov", "webm"}
PLAY_VCODECS = {"h264", "vp8", "vp9", "av1"}
PLAY_ACODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le", "pcm_u8"}
PLAY_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "aac", "flac", "opus"}
PLAY_IMAGE_EXT = {"png", "jpg", "jpeg", "jfif", "webp", "bmp"}

CACHE = WORKSPACE / "video_proxy"
SR = 48000  # export audio sample rate
AFMT = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def kind_of(path) -> str | None:
    e = ext_of(path)
    return "video" if e in VIDEO_EXT else "audio" if e in AUDIO_EXT else "image" if e in IMAGE_EXT else None


# ------------------------------------------------------------------ probing

def _rotation(stream) -> int:
    rot = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot and stream.get("tags", {}).get("rotate"):
        rot = int(stream["tags"]["rotate"])
    return rot % 360


def _rate(s) -> float:
    try:
        a, b = str(s.get("avg_frame_rate") or s.get("r_frame_rate")).split("/")
        f = float(a) / float(b)
        return round(f, 3) if 1 <= f <= 240 else 30.0
    except Exception:
        return 30.0


def media_info(path: str) -> dict:
    """Everything the editor needs to know about one file. Raises if it isn't usable media."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    kind = kind_of(p)
    if not kind:
        raise ValueError(f"{p.name}: not a video, audio or image file")
    info = probe(p)
    streams = info.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    as_ = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    if kind == "video" and not vs:
        kind = "audio" if as_ else None  # e.g. an .mp4 that only holds audio
    if kind == "audio" and not as_:
        kind = None
    if not kind:
        raise ValueError(f"{p.name}: no playable streams found")
    w = h = 0
    rot = 0
    if vs:
        w, h = int(vs.get("width") or 0), int(vs.get("height") or 0)
        rot = _rotation(vs)
        if rot in (90, 270):
            w, h = h, w  # ffmpeg and the browser both auto-rotate, so report the displayed size
    e = ext_of(p)
    if kind == "video":
        playable = (e in PLAY_CONTAINERS and vs.get("codec_name") in PLAY_VCODECS
                    and vs.get("pix_fmt", "yuv420p") in ("yuv420p", "yuvj420p")
                    and (not as_ or as_.get("codec_name") in PLAY_ACODECS))
    elif kind == "audio":
        playable = e in PLAY_AUDIO_EXT and as_.get("codec_name") in PLAY_ACODECS | {"pcm_s16be", "mp3float"}
    else:
        playable = e in PLAY_IMAGE_EXT
        dur = 0.0
    st = p.stat()
    return {"path": str(p), "name": p.name, "kind": kind, "duration": round(dur, 3), "width": w, "height": h,
            "fps": _rate(vs) if vs else 0, "has_audio": bool(as_) and kind != "image", "rotation": rot,
            "vcodec": vs.get("codec_name") if vs else None, "acodec": as_.get("codec_name") if as_ else None,
            "playable": bool(playable), "size": st.st_size}


# ------------------------------------------------------------------ cache: proxies, thumbs, waveforms

def _key(path: str, extra="") -> str:
    st = os.stat(path)
    raw = f"{os.path.abspath(path).lower()}|{st.st_mtime_ns}|{st.st_size}|{extra}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def proxy_path(path: str) -> Path:
    kind = kind_of(path)
    ext = {"video": "mp4", "audio": "m4a", "image": "jpg"}[kind]
    return CACHE / f"{_key(path)}.{ext}"


def make_proxy(path: str, ctx) -> Path:
    """Low-res H.264/AAC copy for preview only (never delivered as an output)."""
    out = proxy_path(path)
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    kind = kind_of(path)
    info = media_info(path)
    if kind == "video":
        args = ["-i", path, "-map", "0:v:0", "-map", "0:a:0?", "-vf", r"scale=-2:min(540\,ih),format=yuv420p",
                *h264_args(27, "veryfast"), "-g", "15", "-c:a", "aac", "-b:a", "128k",
                "-ac", "2", "-movflags", "+faststart", str(tmp)]
    elif kind == "audio":
        args = ["-i", path, "-vn", "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(tmp)]
    else:
        args = ["-i", path, "-frames:v", "1", "-vf", r"scale=min(1920\,iw):-2", "-q:v", "3", str(tmp)]
    run_ffmpeg(args, ctx, info["duration"], "Preparing preview")
    os.replace(tmp, out)
    return out


def thumb(path: str, t: float = 0.0, height: int = 90) -> bytes:
    """A JPEG frame grab, cached on disk."""
    height = max(24, min(360, int(height)))
    f = CACHE / "thumbs" / f"{_key(path, f'{t:.2f}:{height}')}.jpg"
    if f.exists():
        return f.read_bytes()
    f.parent.mkdir(parents=True, exist_ok=True)
    seek = ["-ss", f"{max(0.0, t):.3f}"] if kind_of(path) == "video" and t > 0 else []
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", *seek, "-i", path, "-frames:v", "1",
           "-vf", f"scale=-2:{height},format=yuvj420p", "-f", "image2", "-c:v", "mjpeg", "-q:v", "5", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, timeout=60)
    if not r.stdout and seek:  # seeking past the end: fall back to the first frame
        return thumb(path, 0.0, height)
    if not r.stdout:
        raise RuntimeError("Couldn't grab a frame")
    f.write_bytes(r.stdout)
    return r.stdout


def waveform(path: str, per_sec: int = 20) -> dict:
    """Peak envelope (0..1) for drawing audio clips, cached as JSON."""
    f = CACHE / "waves" / f"{_key(path, str(per_sec))}.json"
    if f.exists():
        return json.loads(f.read_text())
    import numpy as np
    rate = 4000
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, timeout=600)
    a = np.abs(np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)) / 32768.0
    step = rate // per_sec
    n = len(a) // step
    peaks = a[: n * step].reshape(n, step).max(axis=1) if n else np.zeros(0)
    top = float(peaks.max()) if n else 1.0
    data = {"per_sec": per_sec, "peaks": [round(float(x) / (top or 1), 3) for x in peaks]}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data))
    return data


# ------------------------------------------------------------------ timeline maths (mirrors video.js)

def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def clip_speed(c) -> float:
    return min(4.0, max(0.25, _f(c.get("speed"), 1.0)))


def clip_dur(c) -> float:
    if c.get("kind") == "image":
        return max(0.1, _f(c.get("dur"), 4.0))
    return max(0.04, (_f(c.get("out")) - _f(c.get("in"))) / clip_speed(c))


def layout(clips) -> tuple[list[tuple[float, float, float]], float]:
    """[(start, dur, xfade_in)] per clip and the total length. Crossfades overlap neighbours."""
    out, t, prev = [], 0.0, None
    for i, c in enumerate(clips):
        d = clip_dur(c)
        xd = 0.0
        tr = c.get("trans") or {}
        if i and tr.get("type") == "crossfade":
            xd = max(0.0, min(_f(tr.get("dur"), 1.0), prev / 2, d / 2))
            xd = round(xd, 3)
        start = max(0.0, t - xd)
        out.append((start, d, xd))
        t, prev = start + d, d
    return out, t


# ------------------------------------------------------------------ filter escaping

def esc_value(s: str) -> str:
    """Quote a filter option value so ffmpeg reads it back literally (both escaping levels).
    Level 1 (option parser): wrap in '…', a literal ' becomes '\\''.
    Level 2 (filtergraph parser): backslash-escape \\ ' [ ] , ; so level 1 survives."""
    lvl1 = "'" + str(s).replace("'", "'\\''") + "'"
    return "".join("\\" + ch if ch in "\\'[],;" else ch for ch in lvl1)


def font_file() -> str:
    for f in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
              str(APP_DIR / "web" / "fonts" / "Nunito.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if os.path.exists(f):
            return f.replace("\\", "/")
    raise RuntimeError("No font found for text overlays")


def _hex(c, default="ffffff") -> str:
    c = str(c or "").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return "0x" + (c if len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c) else default)


def _atempo(speed: float) -> list[str]:
    """atempo only takes 0.5–2.0 per stage with good quality, so chain stages."""
    out, s = [], speed
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    while s > 2.0:
        out.append("atempo=2")
        s /= 2.0
    if abs(s - 1.0) > 1e-4:
        out.append(f"atempo={s:.6g}")
    return out


def _even(x) -> int:
    return max(2, int(round(x / 2)) * 2)


# ------------------------------------------------------------------ export

AUDIO_ONLY = {"mp3", "wav"}
FORMATS = {"mp4", "webm", "mov", "gif", "mp3", "wav"}


def visual_size(c, m) -> tuple[float, float]:
    """Displayed size of a clip after crop + rotate (before fitting to the frame)."""
    w, h = max(2, m.get("width") or 1280), max(2, m.get("height") or 720)
    cr = c.get("crop") or {}
    w *= max(0.05, 1 - _f(cr.get("l")) - _f(cr.get("r")))
    h *= max(0.05, 1 - _f(cr.get("t")) - _f(cr.get("b")))
    if int(_f(c.get("rotate"))) % 180 == 90:
        w, h = h, w
    return w, h


def export_size(project, settings) -> tuple[int, int, float]:
    media = {m["id"]: m for m in project.get("media", [])}
    clips = [c for c in project.get("clips", []) if c.get("media") in media]
    first = next(((c, media[c["media"]]) for c in clips if media[c["media"]]["kind"] in ("video", "image")), None)
    sw, sh = visual_size(*first) if first else (1920, 1080)
    fps_s = str(settings.get("fps") or "source")
    if fps_s == "source":
        v = next((media[c["media"]] for c in clips if media[c["media"]]["kind"] == "video"), None)
        fps = min(60.0, (v or {}).get("fps") or 30.0)
    else:
        fps = min(120.0, max(1.0, _f(fps_s, 30)))
    aspect = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "4:5": 4 / 5}.get(settings.get("aspect"), sw / sh)
    res = str(settings.get("resolution") or "source")
    if res == "custom":
        w, h = _even(_f(settings.get("width"), 1920)), _even(_f(settings.get("height"), 1080))
    else:
        short = {"2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}.get(res)
        if short is None:  # source: keep the first clip's size (fit to the chosen aspect)
            short = min(sw, sh) if settings.get("aspect") in (None, "", "keep") else min(sw, sh, max(sw, sh) / max(aspect, 1 / aspect))
        if aspect >= 1:
            w, h = _even(short * aspect), _even(short)
        else:
            w, h = _even(short), _even(short / aspect)
    if settings.get("format") == "gif" and max(w, h) > 640 and res != "custom":
        k = 640 / max(w, h)
        w, h = _even(w * k), _even(h * k)
    if settings.get("format") == "gif":
        fps = min(fps, 15.0)
    return min(w, 7680), min(h, 7680), round(fps, 3)


def build_export(project: dict, settings: dict, out_path: Path, work: Path) -> tuple[list[str], float]:
    """Return (ffmpeg args, output duration) that render the whole project in a single filter graph."""
    fmt = settings.get("format", "mp4")
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format: {fmt}")
    audio_only = fmt in AUDIO_ONLY
    want_audio = fmt != "gif"
    media = {m["id"]: m for m in project.get("media", [])}
    clips = [dict(c, kind=media[c["media"]]["kind"]) for c in project.get("clips", []) if c.get("media") in media]
    for c in clips:  # stale projects may point past the end of a (changed) source: clamp so durations stay exact
        sd = _f(media[c["media"]].get("duration"))
        if c["kind"] != "image" and sd > 0:
            c["out"] = min(_f(c.get("out"), sd), sd)
            c["in"] = max(0.0, min(_f(c.get("in")), c["out"] - 0.05))
    music = [m for m in project.get("music", []) if m.get("media") in media and _f(m.get("out")) > _f(m.get("in"))]
    for c in clips:
        if not os.path.exists(media[c["media"]]["path"]):
            raise FileNotFoundError("Missing source: " + media[c["media"]]["path"])
    if not clips and not (audio_only and music):
        raise ValueError("The timeline is empty: add a clip first")
    if not audio_only and not any(c["kind"] in ("video", "image") for c in clips):
        raise ValueError("Add a video or image clip to export a video (or pick MP3/WAV)")

    W, H, F = export_size(project, settings)
    pos, total = layout(clips)
    if not clips:
        total = max(_f(m.get("start")) + (_f(m["out"]) - _f(m["in"])) for m in music)
    music_mode = project.get("music_mode", "mix")
    fit = settings.get("fit", "pad")

    args: list[str] = []
    graph: list[str] = []
    n_in = 0

    def add_input(*opts):
        nonlocal n_in
        args.extend(opts)
        n_in += 1
        return n_in - 1

    # ---- per-clip streams
    vlabels, alabels = [], []
    for i, c in enumerate(clips):
        m = media[c["media"]]
        start, D, _ = pos[i]
        speed = clip_speed(c)
        src_in, src_out = max(0.0, _f(c.get("in"))), _f(c.get("out"))
        fi = min(_f(c.get("fade_in")), D / 2)
        fo = min(_f(c.get("fade_out")), D / 2)
        if c["kind"] == "image":
            k = add_input("-loop", "1", "-framerate", f"{F:g}", "-t", f"{D + 0.5:.3f}", "-i", m["path"])
        else:
            k = add_input("-ss", f"{src_in:.3f}", "-t", f"{src_out - src_in + 0.1:.3f}", "-i", m["path"])
        if not audio_only:
            v = [f"[{k}:v]setpts=PTS-STARTPTS"]
            cr = c.get("crop") or {}
            l, r, t, b = (min(0.45, max(0.0, _f(cr.get(x)))) for x in "lrtb")
            if l or r or t or b:
                v.append(f"crop=w=iw*{1 - l - r:.4f}:h=ih*{1 - t - b:.4f}:x=iw*{l:.4f}:y=ih*{t:.4f}")
            rot = int(_f(c.get("rotate"))) % 360
            v += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(rot, [])
            eq = c.get("eq") or {}
            br, co, sa = _f(eq.get("brightness")), _f(eq.get("contrast"), 1), _f(eq.get("saturation"), 1)
            if abs(br) > 1e-3 or abs(co - 1) > 1e-3 or abs(sa - 1) > 1e-3:
                v.append(f"eq=brightness={br:.3f}:contrast={co:.3f}:saturation={sa:.3f}")
            if c["kind"] != "image" and abs(speed - 1) > 1e-4:
                v.append(f"setpts=PTS/{speed:.5f}")
            if fit == "crop":
                v.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H}")
            else:
                v.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
            v += ["setsar=1", f"fps={F:g}", "format=yuv420p",
                  "tpad=stop_mode=clone:stop=-1", f"trim=duration={D:.3f}", "setpts=PTS-STARTPTS", "settb=AVTB"]  # same timebase everywhere for xfade
            if fi > 0:
                v.append(f"fade=t=in:st=0:d={fi:.3f}")
            if fo > 0:
                v.append(f"fade=t=out:st={D - fo:.3f}:d={fo:.3f}")
            graph.append(",".join(v) + f"[v{i}]")
            vlabels.append(f"[v{i}]")
        if want_audio:
            vol = 0.0 if c.get("muted") else max(0.0, min(2.0, _f(c.get("volume"), 1.0)))
            if music_mode == "replace":
                vol = 0.0
            if c["kind"] != "image" and m.get("has_audio") and vol > 0:
                a = [f"[{k}:a]{AFMT}", "asetpts=PTS-STARTPTS", *_atempo(speed), "apad",
                     f"atrim=duration={D:.3f}", "asetpts=PTS-STARTPTS"]
                if abs(vol - 1) > 1e-3:
                    a.append(f"volume={vol:.3f}")
                if fi > 0:
                    a.append(f"afade=t=in:st=0:d={fi:.3f}")
                if fo > 0:
                    a.append(f"afade=t=out:st={D - fo:.3f}:d={fo:.3f}")
                graph.append(",".join(a) + f"[a{i}]")
            else:
                graph.append(f"anullsrc=r={SR}:cl=stereo,atrim=duration={D:.3f}[a{i}]")
            alabels.append(f"[a{i}]")

    # ---- join clips: concat runs without transitions, crossfade between runs
    vmain = amain = None
    if clips:
        runs, cur = [], []
        for i in range(len(clips)):
            if i and pos[i][2] > 0:
                runs.append(cur)
                cur = []
            cur.append(i)
        runs.append(cur)
        joined = []
        for ri, run in enumerate(runs):
            dur = pos[run[-1]][0] + pos[run[-1]][1] - pos[run[0]][0]
            vl = al = None
            if len(run) == 1:
                vl = vlabels[run[0]] if vlabels else None
                al = alabels[run[0]] if alabels else None
            else:
                ins = "".join((vlabels[i] if vlabels else "") + (alabels[i] if alabels else "") for i in run)
                outs = []
                if vlabels:
                    outs.append(f"[rv{ri}]")
                if alabels:
                    outs.append(f"[ra{ri}]")
                graph.append(f"{ins}concat=n={len(run)}:v={1 if vlabels else 0}:a={1 if alabels else 0}{''.join(outs)}")
                vl = f"[rv{ri}]" if vlabels else None
                al = f"[ra{ri}]" if alabels else None
            joined.append((vl, al, pos[run[0]][2]))
        vmain, amain, _ = joined[0]
        acc = pos[runs[0][-1]][0] + pos[runs[0][-1]][1]
        for ri in range(1, len(joined)):
            vl, al, xd = joined[ri]
            run = runs[ri]
            offset = pos[run[0]][0]  # = acc - xd
            if vmain:
                graph.append(f"{vmain}{vl}xfade=transition=fade:duration={xd:.3f}:offset={offset:.3f}[xv{ri}]")
                vmain = f"[xv{ri}]"
            if amain:
                graph.append(f"{amain}{al}acrossfade=d={xd:.3f}:c1=tri:c2=tri[xa{ri}]")
                amain = f"[xa{ri}]"
            acc = pos[run[-1]][0] + pos[run[-1]][1]

    # ---- text overlays (drawn on the joined video)
    texts = [t for t in project.get("texts", []) if str(t.get("text", "")).strip() and _f(t.get("end")) > _f(t.get("start"))]
    if vmain and texts:
        font = esc_value(font_file())
        parts = []
        for t in texts:
            size = max(8, int(H * max(1.0, _f(t.get("size"), 6)) / 100))
            fx, fy = min(1, max(0, _f(t.get("x"), 0.5))), min(1, max(0, _f(t.get("y"), 0.9)))
            s, e = max(0.0, _f(t.get("start"))), _f(t.get("end"))
            txt = str(t["text"]).replace("\r\n", "\n").replace("\r", "\n")
            d = (f"drawtext=fontfile={font}:expansion=none:text={esc_value(txt)}:fontsize={size}"
                 f":fontcolor={_hex(t.get('color'))}:line_spacing={max(2, size // 6)}"
                 f":x=(w-text_w)*{fx:.4f}:y=(h-text_h)*{fy:.4f}:enable=between(t\\,{s:.3f}\\,{e:.3f})")
            if t.get("box"):
                d += f":box=1:boxcolor={_hex(t.get('box_color'), '000000')}@0.55:boxborderw={max(4, size // 3)}"
            else:
                d += f":borderw={max(1, size // 16)}:bordercolor=black@0.7"
            parts.append(d)
        graph.append(vmain + ",".join(parts) + "[vtxt]")
        vmain = "[vtxt]"

    # ---- music bus
    if want_audio:
        if amain is None:
            graph.append(f"anullsrc=r={SR}:cl=stereo,atrim=duration={total:.3f}[asil]")
            amain = "[asil]"
        mlabels = []
        for j, mu in enumerate(music):
            mm = media[mu["media"]]
            if not os.path.exists(mm["path"]):
                raise FileNotFoundError("Missing music: " + mm["path"])
            mi, mo = max(0.0, _f(mu.get("in"))), _f(mu.get("out"))
            st = _f(mu.get("start"))
            if st < 0:  # starts before 0: skip the hidden part
                mi, st = mi - st, 0.0
            L = mo - mi
            if L <= 0.05 or st >= total:
                continue
            k = add_input("-ss", f"{mi:.3f}", "-t", f"{L:.3f}", "-i", mm["path"])
            a = [f"[{k}:a]{AFMT}", "asetpts=PTS-STARTPTS", f"atrim=duration={L:.3f}"]
            vol = max(0.0, min(2.0, _f(mu.get("volume"), 1.0)))
            if abs(vol - 1) > 1e-3:
                a.append(f"volume={vol:.3f}")
            fi, fo = min(_f(mu.get("fade_in")), L / 2), min(_f(mu.get("fade_out")), L / 2)
            if fi > 0:
                a.append(f"afade=t=in:st=0:d={fi:.3f}")
            if fo > 0:
                a.append(f"afade=t=out:st={L - fo:.3f}:d={fo:.3f}")
            if st > 0:
                a.append(f"adelay=delays={int(round(st * 1000))}:all=1")
            graph.append(",".join(a) + f"[m{j}]")
            mlabels.append(f"[m{j}]")
        if mlabels:
            if len(mlabels) > 1:
                graph.append(f"{''.join(mlabels)}amix=inputs={len(mlabels)}:duration=longest:normalize=0[mbus0]")
            else:
                graph.append(f"{mlabels[0]}anull[mbus0]")
            graph.append(f"[mbus0]apad=whole_dur={total:.3f},atrim=duration={total:.3f}[mbus]")
            if music_mode == "replace":
                graph.append(f"{amain}anullsink")  # original audio is dropped
                amain = "[mbus]"
            elif music_mode == "duck":
                graph.append(f"{amain}asplit=2[amx][asc]")
                graph.append("[mbus][asc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=400:makeup=1[mduck]")
                graph.append("[amx][mduck]amix=inputs=2:duration=first:normalize=0[amixed]")
                amain = "[amixed]"
            else:
                graph.append(f"{amain}[mbus]amix=inputs=2:duration=first:normalize=0[amixed]")
                amain = "[amixed]"

    # ---- range + final trim
    rs, re_ = 0.0, total
    rng = settings.get("range")
    if rng:
        rs = min(max(0.0, _f(rng[0])), total)
        re_ = min(max(rs, _f(rng[1], total)), total)
        if re_ - rs < 0.1:
            raise ValueError("The export range is too short")
    out_dur = re_ - rs
    if vmain:
        v = f"{vmain}trim=start={rs:.3f}:end={re_:.3f},setpts=PTS-STARTPTS"
        if fmt == "gif":
            v += ",split[g1][g2];[g1]palettegen=stats_mode=diff:max_colors=200[pal];[g2][pal]paletteuse=dither=bayer:bayer_scale=4"
        graph.append(v + "[vout]")
    if want_audio:
        graph.append(f"{amain}atrim=start={rs:.3f}:end={re_:.3f},asetpts=PTS-STARTPTS[aout]")

    fc = ";".join(graph)
    if len(fc) > 7000:  # Windows command lines max out at 32k chars: hand long graphs over as a file
        gp = work / "graph.txt"
        gp.write_text(fc, encoding="utf-8")
        args += ["-/filter_complex", str(gp)]
    else:
        args += ["-filter_complex", fc]
    if audio_only:
        args += ["-map", "[aout]", *codec_args(fmt, {"audio_bitrate": "192k"})]
    elif fmt == "gif":
        args += ["-map", "[vout]", "-loop", "0"]
    else:
        args += ["-map", "[vout]", "-map", "[aout]", *codec_args(fmt, {"crf": int(_f(settings.get("crf"), 21)), "preset": settings.get("preset", "fast")})]
        args += ["-r", f"{F:g}"]
    args += ["-t", f"{out_dur:.3f}", str(out_path)]
    return args, out_dur


def export(project: dict, settings: dict, ctx, work: Path, name: str = "edited") -> list[Path]:
    fmt = settings.get("format", "mp4")
    safe = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "edited"
    out = work / f"{safe}.{fmt}"
    args, dur = build_export(project, settings, out, work)
    ctx.sub_progress(0.0, "Rendering…")
    run_ffmpeg(args, ctx, dur, "Rendering")
    ctx.note(f"{out.name}: {dur:.1f}s" + ("" if fmt in AUDIO_ONLY else f", {'x'.join(map(str, export_size(project, settings)[:2]))}"))
    return [out]
