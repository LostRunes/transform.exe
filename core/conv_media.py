"""Audio / video / GIF conversions and tools via ffmpeg, with live progress."""
import json
import os
import subprocess
from pathlib import Path

from .util import FFMPEG, FFPROBE

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


def run_ffmpeg(args: list[str], ctx, duration: float = 0.0, label: str = ""):
    """Run ffmpeg, stream progress into ctx, honour cancellation."""
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
                    ctx.sub_progress(min(t / duration, 0.999), f"{label} {t:.0f}s / {duration:.0f}s")
            except ValueError:
                pass
    proc.wait()
    ctx.register_proc(None)
    if ctx.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + "".join(err_tail[-12:]))


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
    h264 = ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p"]
    v = {
        "mp4": h264 + a + ["-movflags", "+faststart"],
        "m4v": h264 + a + ["-movflags", "+faststart"],
        "mov": h264 + a + ["-movflags", "+faststart"],
        "mkv": h264 + a,
        "flv": h264 + a,
        "ts": h264 + a,
        "3gp": ["-c:v", "libx264", "-profile:v", "baseline", "-crf", crf, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k"],
        "webm": ["-c:v", "libvpx-vp9", "-crf", str(int(crf) + 8), "-b:v", "0", "-deadline", "good", "-cpu-used", "4",
                 "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
        "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-b:a", "192k"],
        "wmv": ["-c:v", "wmv2", "-q:v", "3", "-c:a", "wmav2", "-b:a", "192k"],
        "mpeg": ["-c:v", "mpeg2video", "-q:v", "3", "-c:a", "mp2", "-b:a", "192k"],
    }[fmt]
    if params.get("codec") == "h265" and fmt in ("mp4", "mkv", "mov", "m4v"):
        v = ["-c:v", "libx265", "-preset", preset, "-crf", str(int(crf) + 5), "-pix_fmt", "yuv420p", "-tag:v", "hvc1"] + a
    return v


def convert_media(src: Path, out: Path, params: dict, ctx):
    fmt = out.suffix.lower().lstrip(".")
    dur = duration_of(src)
    if fmt == "gif":
        fps = int(params.get("fps", 12))
        width = int(params.get("width", 480))
        vf = (f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];"
              f"[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5")
        run_ffmpeg(["-i", str(src), "-vf", vf, "-loop", "0", str(out)], ctx, dur, "GIF")
        return [out]
    src_ext = src.suffix.lower().lstrip(".")
    extra_in = []
    vf = []
    if src_ext == "gif" and fmt in VIDEO_OUT:
        extra_in = []
        vf = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]  # h264 needs even dimensions
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

def tool_compress_video(src: Path, out_dir: Path, params: dict, ctx, unique):
    dur = duration_of(src)
    out = unique(out_dir, src.stem + "_compressed", "mp4")
    vf = []
    height = int(params.get("max_height") or 0)
    if height:
        vf.append(f"scale=-2:'min({height},ih)'")
    codec = "libx265" if params.get("codec") == "h265" else "libx264"
    args = ["-i", str(src), "-c:v", codec, "-preset", params.get("preset", "medium"), "-pix_fmt", "yuv420p"]
    target_mb = float(params.get("target_mb") or 0)
    if target_mb and dur:
        audio_k = 96
        video_k = max(100, int(target_mb * 8192 / dur - audio_k))
        args += ["-b:v", f"{video_k}k", "-maxrate", f"{int(video_k * 1.5)}k", "-bufsize", f"{video_k * 2}k"]
    else:
        crf = int(params.get("crf", 28)) + (4 if codec == "libx265" else 0)
        args += ["-crf", str(crf)]
    if codec == "libx265":
        args += ["-tag:v", "hvc1"]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-c:a", "aac", "-b:a", "96k" if target_mb else "128k", "-movflags", "+faststart", str(out)]
    run_ffmpeg(args, ctx, dur, "Compressing")
    return [out]


def tool_trim(src: Path, out_dir: Path, params: dict, ctx, unique):
    start = params.get("start") or "0"
    end = params.get("end") or ""
    ext = src.suffix.lower().lstrip(".")
    out = unique(out_dir, src.stem + "_trimmed", ext)
    args = ["-ss", start, "-i", str(src)]
    if end:
        args += ["-to", str(_secs(end) - _secs(start))]
    if params.get("precise", True) and ext in ("mp4", "mkv", "mov", "m4v", "webm", "avi"):
        args += codec_args(ext if ext != "m4v" else "mp4", params)
    else:
        args += ["-c", "copy"]
    args.append(str(out))
    total = (_secs(end) if end else duration_of(src)) - _secs(start)
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
    fps = params.get("fps", "1")
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
    total = sum(duration_of(s) for s in srcs)
    args = []
    for s in srcs:
        args += ["-i", str(s)]
    if is_audio:
        filt = "".join(f"[{i}:a]" for i in range(len(srcs))) + f"concat=n={len(srcs)}:v=0:a=1[a]"
        args += ["-filter_complex", filt, "-map", "[a]", *codec_args(out.suffix.lstrip(".").lower(), params), str(out)]
    else:
        w, h = vs["width"], vs["height"]
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
    parts = [float(p) for p in t.split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s
