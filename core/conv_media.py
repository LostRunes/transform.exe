"""Audio / video / GIF conversions and tools via ffmpeg, with live progress."""
import json
import os
import subprocess
from pathlib import Path

from .util import FFMPEG, FFPROBE, h264_args, has_x264, human_size as human

VIDEO = {"mp4", "mkv", "mov", "avi", "webm", "flv", "wmv", "m4v", "mpeg", "mpg", "3gp", "ts", "mts", "m2ts", "ogv", "vob"}
AUDIO = {"mp3", "wav", "aac", "flac", "ogg", "m4a", "opus", "wma", "aiff", "aif", "amr", "ac3", "mka"}
VIDEO_OUT = ["mp4", "mkv", "mov", "webm", "avi", "gif", "flv", "wmv", "mpeg", "3gp", "m4v", "ts"]
AUDIO_OUT = ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma", "aiff", "ac3"]

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class Cancelled(Exception):
    pass


def probe(path: Path) -> dict:
    """ffprobe-style info. Uses ffprobe when present, otherwise parses `ffmpeg -i` (so only ffmpeg.exe is required)."""
    if FFPROBE:
        r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        try:
            return json.loads(r.stdout)
        except Exception:
            return {}
    if not FFMPEG:
        return {}
    import re
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    info = {"format": {}, "streams": []}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if m:
        info["format"]["duration"] = str(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]))
    for line in r.stderr.splitlines():
        s = re.match(r"\s*Stream #\S+.*?: (Video|Audio):(.*)", line)
        if not s:
            continue
        stream = {"codec_type": s[1].lower()}
        if s[1] == "Video":
            size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", s[2])
            if size:
                stream.update(width=int(size[1]), height=int(size[2]))
        info["streams"].append(stream)
    return info


def duration_of(path: Path) -> float:
    try:
        return float(probe(path)["format"]["duration"])
    except Exception:
        return 0.0


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def run_ffmpeg(args: list[str], ctx, duration: float = 0.0, label: str = "", span=(0.0, 1.0)):
    """Run ffmpeg, stream progress into ctx, honour cancellation. span maps this run into part of the bar."""
    if not FFMPEG:
        raise RuntimeError("ffmpeg not found. Install it (winget install Gyan.FFmpeg) or drop ffmpeg.exe into ./bin")
    cmd = [FFMPEG, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    ctx.register_proc(proc)
    err_tail = []

    import threading

    def drain_err():
        for line in proc.stderr:
            err_tail.append(line)
            del err_tail[:-40]
    threading.Thread(target=drain_err, daemon=True).start()

    for line in proc.stdout:
        if ctx.cancelled:
            proc.kill()
            raise Cancelled()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=")[1]) / 1_000_000
                if duration > 0:
                    frac = span[0] + (span[1] - span[0]) * min(t / duration, 0.999)
                    ctx.sub_progress(frac, f"{label} {t:.0f}s / {duration:.0f}s")
            except ValueError:
                pass
    proc.wait()
    ctx.register_proc(None)
    if ctx.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        lines = [ln.strip() for ln in err_tail if ln.strip() and not ln.startswith((" ", "\t"))]
        raise RuntimeError("ffmpeg failed: " + " / ".join(lines[-3:] or ["unknown error"]))


def _quality_crf(params, default=23):
    return str(int(params.get("crf", default)))


def codec_args(fmt: str, params: dict, src_has_audio=True) -> list[str]:
    crf = _quality_crf(params)
    preset = params.get("preset", "medium")
    abr = params.get("audio_bitrate", "192k")
    if fmt in AUDIO_OUT:
        return ["-vn", *{
            "mp3": ["-c:a", "libmp3lame", "-b:a", abr],
            "wav": ["-c:a", "pcm_s16le"],
            "aiff": ["-c:a", "pcm_s16be"],
            "flac": ["-c:a", "flac"],
            "m4a": ["-c:a", "aac", "-b:a", abr],
            "aac": ["-c:a", "aac", "-b:a", abr],
            "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
            "opus": ["-c:a", "libopus", "-b:a", "128k"],
            "wma": ["-c:a", "wmav2", "-b:a", abr],
            "ac3": ["-c:a", "ac3", "-b:a", "384k"],
        }[fmt]]
    a = ["-c:a", "aac", "-b:a", "160k"]
    h264 = [*h264_args(crf, preset), "-pix_fmt", "yuv420p"]  # x264, or Windows' encoder in LGPL builds
    v = {
        "mp4": h264 + a + ["-movflags", "+faststart"],
        "m4v": h264 + a + ["-movflags", "+faststart"],
        "mov": h264 + a + ["-movflags", "+faststart"],
        "mkv": h264 + a,
        "flv": h264 + a,
        "ts": h264 + a,
        "3gp": [*h264_args(crf, preset), *(["-profile:v", "baseline"] if has_x264() else []), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "96k"],
        "webm": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", str(int(crf) + 8), "-b:v", "0", "-deadline", "good", "-cpu-used", "4",
                 "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
        "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-b:a", "192k"],
        "wmv": ["-c:v", "wmv2", "-q:v", "3", "-c:a", "wmav2", "-b:a", "192k"],
        "mpeg": ["-c:v", "mpeg2video", "-q:v", "3", "-c:a", "mp2", "-b:a", "192k"],
    }[fmt]
    if params.get("codec") == "h265" and fmt in ("mp4", "mkv", "mov", "m4v"):
        v = [*h264_args(int(crf) + 5, preset, hevc=True), "-pix_fmt", "yuv420p"] + a
    return v


def convert_media(src: Path, out: Path, params: dict, ctx):
    fmt = out.suffix.lower().lstrip(".")
    info = probe(src)
    streams = {s.get("codec_type") for s in info.get("streams", [])}
    if FFMPEG and not streams:  # (without ffmpeg, run_ffmpeg explains how to install it)
        raise ValueError("This file is damaged or isn't a video/audio file ffmpeg can read")
    if streams and fmt in AUDIO_OUT and "audio" not in streams:
        raise ValueError(f"{src.name} has no sound track, so there's no audio to save")
    dur = duration_of(src)
    if fmt == "gif":
        fps = float(params.get("fps") or 12)
        width = int(params.get("width") or 480)
        vf = (f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];"
              f"[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5")
        run_ffmpeg(["-i", str(src), "-vf", vf, "-loop", "0", str(out)], ctx, dur, "GIF")
        return [out]
    extra_in = []
    vf = []
    if fmt in VIDEO_OUT:
        vf = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]  # H.264 & co. need even dimensions (GIFs, odd-sized clips)
    if params.get("fast_copy") and fmt in ("mp4", "mkv", "mov", "m4v", "ts"):
        args = ["-i", str(src), "-map", "0", "-c", "copy", str(out)]
    else:
        args = [*extra_in, "-i", str(src), *codec_args(fmt, params)]
        if vf and fmt not in AUDIO_OUT:
            args += ["-vf", ",".join(vf)]
        args.append(str(out))
    run_ffmpeg(args, ctx, dur, "Encoding")
    return [out]


# ---------------- tools ----------------

# Short side of the picture, best first. Target-size encodes step down this ladder until
# each pixel gets enough bits to look like video rather than mush.
SHORT_SIDES = [2160, 1440, 1080, 720, 540, 480, 360, 240]


def _video_stream(info: dict):
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)


def _fps(stream) -> float:
    try:
        a, b = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate")).split("/")
        f = float(a) / float(b)
        return f if 1 <= f <= 240 else 30.0
    except Exception:
        return 30.0


def _auto_short_side(stream, video_k: int, h265: bool):
    """Largest short side (no upscaling) where the bitrate still gives a sane bits-per-pixel."""
    if not stream or not stream.get("width"):
        return None
    w, h = stream["width"], stream["height"]
    short, long_ = min(w, h), max(w, h)
    need = 0.035 if h265 else 0.05
    fps = _fps(stream)
    for side in SHORT_SIDES:
        if side > short:
            continue
        pixels = side * side * long_ / short
        if video_k * 1000 / (fps * pixels) >= need:
            return side if side < short else None
    return SHORT_SIDES[-1] if short > SHORT_SIDES[-1] else None


def tool_compress_video(src: Path, out_dir: Path, params: dict, ctx, unique):
    from .shrink import already_fits, budget, report
    size = src.stat().st_size
    limit = budget(size, params)
    done = already_fits(src, out_dir, limit, ctx, unique)
    if done:
        return done
    dur = duration_of(src)
    out = unique(out_dir, src.stem + "_compressed", "mp4")
    h265 = params.get("codec") == "h265"
    preset = params.get("preset", "medium")
    height = int(params.get("max_height") or 0)
    if height:
        vf = [f"scale=-2:'trunc(min({height},ih)/2)*2'"]
    else:
        vf = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]  # x264 with yuv420p refuses odd sizes

    if limit is None:
        crf = int(params.get("crf", 28)) + (4 if h265 else 0)
        args = ["-i", str(src), *h264_args(crf, preset, hevc=h265), "-pix_fmt", "yuv420p"]
        if vf:
            args += ["-vf", ",".join(vf)]
        args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
        run_ffmpeg(args, ctx, dur, "Compressing")
        report(ctx, src.name, size, out.stat().st_size)
        return [out]

    if not dur:
        raise ValueError("Couldn't read the video's length, so a target size can't be worked out")
    info = probe(src)
    vs = _video_stream(info)
    with_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    total_k = limit * 8 / 1000 / dur * 0.96  # leave ~4% for the MP4 container
    audio_k = int(min(128, max(24, total_k * 0.12))) if with_audio else 0
    video_k = int(total_k - audio_k)
    if video_k < 30:
        raise ValueError(f"{human(limit)} is too small for a {dur:.0f}s video: the picture would get under "
                         f"30 kbps. Try a bigger target, or trim the video first.")
    if not height and params.get("auto_res", True):
        side = _auto_short_side(vs, video_k, h265)
        if side:
            vf.append(f"scale='if(gt(iw,ih),-2,{side})':'if(gt(iw,ih),{side},-2)'")
            ctx.note(f"{src.name}: lowered to {side}p so {video_k} kbps still looks clean")
    audio = (["-c:a", "aac", "-b:a", f"{audio_k}k"] + (["-ac", "1"] if audio_k < 48 else [])) if with_audio else ["-an"]
    log = str(out_dir / f"{src.stem}_x264pass")

    for attempt in range(3):
        base = ["-i", str(src), *h264_args(preset=preset, hevc=h265, bitrate_k=video_k), "-pix_fmt", "yuv420p"]
        if has_x264():
            base += ["-maxrate", f"{int(video_k * 1.5)}k", "-bufsize", f"{video_k * 2}k"]
        if vf:
            base += ["-vf", ",".join(vf)]
        # x265's two-pass stats path can't hold a Windows drive colon, and Windows' own encoder has no
        # two-pass mode: both get one bitrate pass plus the size check below.
        if h265 or not has_x264():
            run_ffmpeg(base + [*audio, "-movflags", "+faststart", str(out)], ctx, dur,
                       f"Encoding (try {attempt + 1})")
        else:
            run_ffmpeg(base + ["-pass", "1", "-passlogfile", log, "-an", "-f", "null", os.devnull], ctx, dur,
                       "Pass 1 of 2", span=(0, 0.45))
            run_ffmpeg(base + ["-pass", "2", "-passlogfile", log, *audio, "-movflags", "+faststart", str(out)], ctx, dur,
                       "Pass 2 of 2", span=(0.45, 1))
        got = out.stat().st_size
        if got <= limit or video_k <= 30:
            break
        video_k = max(30, int(video_k * (limit / got) * 0.97))  # overshot: aim lower and go again
    for f in out_dir.glob(f"{src.stem}_x264pass*"):
        f.unlink(missing_ok=True)
    report(ctx, src.name, size, out.stat().st_size, limit)
    return [out]


# Formats that can take a bitrate. Anything else (WAV, FLAC, AIFF…) is lossless or odd and
# becomes MP3, since a lossless file can't be squeezed to an arbitrary size.
AUDIO_KEEP = {"mp3": "mp3", "m4a": "m4a", "aac": "m4a", "opus": "opus", "ogg": "ogg"}


OPUS_RATES = [48000, 24000, 16000, 12000, 8000]


def _audio_args(fmt: str, k: int, channels="auto", rate=0) -> list[str]:
    """Encoder flags for roughly k kbps. In "auto", drops to mono / a lower sample rate when bits get tight."""
    args = ["-vn", "-map_metadata", "0"]
    if channels == "mono" or (channels == "auto" and k < 40):
        args += ["-ac", "1"]
    elif channels == "stereo":
        args += ["-ac", "2"]
    if fmt == "mp3":
        k = max(8, min(320, k))
        if not rate and k < 32:  # MPEG-1 layer 3 bottoms out at 32 kbps; the lower sample rates go further
            rate = 22050 if k >= 12 else 11025
        args += ["-ar", str(rate)] if rate else []
        return args + ["-c:a", "libmp3lame", "-abr", "1", "-b:a", f"{k}k"]
    if fmt == "m4a":
        k = max(8, min(320, k))
        if not rate and k < 24:
            rate = 22050
        args += ["-ar", str(rate)] if rate else []
        return args + ["-c:a", "aac", "-b:a", f"{k}k"]
    k = max(6, min(256, k))  # opus / ogg (Opus in an Ogg container): only a few rates are legal
    if rate:
        args += ["-ar", str(min(OPUS_RATES, key=lambda r: abs(r - rate)))]
    return args + ["-c:a", "libopus", "-b:a", f"{k}k"]


def tool_compress_audio(src: Path, out_dir: Path, params: dict, ctx, unique):
    from .shrink import already_fits, budget, report
    size = src.stat().st_size
    limit = budget(size, params)
    done = already_fits(src, out_dir, limit, ctx, unique)
    if done:
        return done
    ext = src.suffix.lower().lstrip(".")
    want = params.get("format", "keep")
    fmt = AUDIO_KEEP.get(ext, "mp3") if want == "keep" else want
    if want == "keep" and fmt != ext and not (ext == "aac" and fmt == "m4a"):
        ctx.note(f"{src.name}: .{ext} can't be squeezed to a size, so it's saved as .{fmt}")
    dur = duration_of(src)
    out = unique(out_dir, src.stem + "_compressed", fmt)
    if limit is None:
        k = int(str(params.get("bitrate", "96")).rstrip("k"))
    else:
        if not dur:
            raise ValueError("Couldn't read the audio's length, so a target size can't be worked out")
        k = int(limit * 8 / 1000 / dur * 0.97)
        if k < 6:
            raise ValueError(f"{human(limit)} is too small for {dur:.0f}s of audio (it would need under 6 kbps)")
    for attempt in range(3):
        args = _audio_args(fmt, k, params.get("channels", "auto"), int(params.get("sample_rate") or 0))
        run_ffmpeg(["-i", str(src), *args, str(out)], ctx, dur, f"Encoding (try {attempt + 1})")
        got = out.stat().st_size
        if limit is None or got <= limit or k <= 6:
            break
        k = max(6, int(k * (limit / got) * 0.95))
    report(ctx, src.name, size, out.stat().st_size, limit)
    return [out]


def tool_trim(src: Path, out_dir: Path, params: dict, ctx, unique):
    start = str(params.get("start") or "0").strip()
    end = str(params.get("end") or "").strip()
    a, b, dur = _secs(start), _secs(end) if end else None, duration_of(src)
    if dur and a >= dur:
        raise ValueError(f"Start ({start}) is past the end of the clip ({dur:.1f}s long)")
    if b is not None and b <= a:
        raise ValueError(f"End ({end}) must be after start ({start})")
    ext = src.suffix.lower().lstrip(".")
    out = unique(out_dir, src.stem + "_trimmed", ext)
    args = ["-ss", str(a), "-i", str(src)]
    if end:
        args += ["-to", str(b - a)]
    if params.get("precise", True) and ext in ("mp4", "mkv", "mov", "m4v", "webm", "avi"):
        args += codec_args(ext if ext != "m4v" else "mp4", params)
    else:
        args += ["-c", "copy"]
    args.append(str(out))
    total = (min(b, dur) if b is not None and dur else b if b is not None else dur) - a
    run_ffmpeg(args, ctx, total, "Trimming")
    return [out]


def tool_resize_video(src: Path, out_dir: Path, params: dict, ctx, unique):
    h = int(params.get("height", 720))
    rotate = params.get("rotate", "none")
    vf = [f"scale=-2:{h}"]
    vf += {"90": ["transpose=1"], "180": ["transpose=1,transpose=1"], "270": ["transpose=2"], "none": []}[rotate]
    if params.get("speed") and float(params["speed"]) != 1:
        vf.append(f"setpts=PTS/{float(params['speed'])}")
    out = unique(out_dir, f"{src.stem}_{h}p", "mp4")
    args = ["-i", str(src), "-vf", ",".join(vf), *codec_args("mp4", params)]
    if params.get("speed") and float(params["speed"]) != 1:
        s = float(params["speed"])
        atempo = []
        while s > 2:
            atempo.append("atempo=2.0"); s /= 2
        while s < 0.5:
            atempo.append("atempo=0.5"); s /= 0.5
        atempo.append(f"atempo={s}")
        args += ["-af", ",".join(atempo)]
    args.append(str(out))
    run_ffmpeg(args, ctx, duration_of(src) / float(params.get("speed") or 1), "Processing")
    return [out]


def tool_mute(src: Path, out_dir: Path, params: dict, ctx, unique):
    ext = src.suffix.lower().lstrip(".")
    out = unique(out_dir, src.stem + "_muted", ext)
    run_ffmpeg(["-i", str(src), "-c:v", "copy", "-an", str(out)], ctx, duration_of(src), "Muting")
    return [out]


def tool_frames(src: Path, out_dir: Path, params: dict, ctx, unique):
    fps = str(params.get("fps") or "1").strip()
    try:
        ok = float(fps) > 0
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"Frames per second must be a number above 0 (e.g. 1, 0.5 or 24), not “{fps}”")
    fmt = params.get("format", "jpg")
    folder = unique(out_dir, src.stem + "_frames", "d").with_suffix("")
    folder.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(src), "-vf", f"fps={fps}", "-q:v", "2", str(folder / f"frame_%05d.{fmt}")],
               ctx, duration_of(src), "Extracting")
    return [folder]


def tool_concat(srcs: list[Path], out: Path, params: dict, ctx):
    """Join clips. Re-encodes so mixed sources work; scales all to the first clip's size."""
    info = probe(srcs[0])
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    is_audio = vs is None
    if not is_audio:
        no_video = [s.name for s in srcs[1:] if not _video_stream(probe(s))]
        if no_video:
            raise ValueError(f"Can't join audio-only files onto a video ({', '.join(no_video)}). "
                             "Put an audio file first to join everything as audio.")
        if not vs.get("width"):
            raise ValueError(f"Couldn't read the picture size of {srcs[0].name}")
    total = sum(duration_of(s) for s in srcs)
    args = []
    for s in srcs:
        args += ["-i", str(s)]
    if is_audio:
        filt = "".join(f"[{i}:a]" for i in range(len(srcs))) + f"concat=n={len(srcs)}:v=0:a=1[a]"
        args += ["-filter_complex", filt, "-map", "[a]", *codec_args(out.suffix.lstrip(".").lower(), params), str(out)]
    else:
        w, h = vs["width"] // 2 * 2, vs["height"] // 2 * 2  # H.264 needs even sizes
        parts, labels = [], ""
        for i, s in enumerate(srcs):
            parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                         f"setsar=1,fps=30,format=yuv420p[v{i}]")
            if has_audio(s):
                parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            else:
                d = duration_of(s)
                parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d}[a{i}]")
            labels += f"[v{i}][a{i}]"
        filt = ";".join(parts) + f";{labels}concat=n={len(srcs)}:v=1:a=1[v][a]"
        args += ["-filter_complex", filt, "-map", "[v]", "-map", "[a]", *codec_args("mp4", params), str(out)]
    run_ffmpeg(args, ctx, total, "Joining")
    return [out]


def tool_audio_tools(src: Path, out_dir: Path, params: dict, ctx, unique):
    """Volume / normalise / fade for audio (or a video's audio track)."""
    ext = src.suffix.lower().lstrip(".")
    af = []
    if params.get("normalize"):
        af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    vol = float(params.get("volume", 100))
    if vol != 100:
        af.append(f"volume={vol / 100}")
    fin = float(params.get("fade_in") or 0)
    if fin:
        af.append(f"afade=t=in:d={fin}")
    if not has_audio(src):
        raise ValueError(f"{src.name} has no sound track")
    out = unique(out_dir, src.stem + "_audio", ext if ext in AUDIO_OUT else "mp3")
    args = ["-i", str(src)]
    if af:
        args += ["-af", ",".join(af)]
    args += codec_args(out.suffix.lstrip("."), params) + [str(out)]
    run_ffmpeg(args, ctx, duration_of(src), "Processing")
    return [out]


def _secs(t: str) -> float:
    t = str(t).strip()
    if not t:
        return 0.0
    try:
        parts = [float(p) for p in t.split(":")]
    except ValueError:
        raise ValueError(f"Couldn't read the time “{t}”. Use seconds (e.g. 90 or 12.5) or h:mm:ss") from None
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s
