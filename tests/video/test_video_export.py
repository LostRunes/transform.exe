"""Video editor backend tests: real ffmpeg exports checked with ffprobe.
Run:  .venv\\Scripts\\python.exe tests\\video\\test_video_export.py [media_dir]
media_dir defaults to a temp folder; test media is generated there with ffmpeg lavfi."""
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core import video_editor as ve  # noqa: E402
from core.util import FFMPEG, FFPROBE  # noqa: E402

MEDIA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "drdoc_video_test"
OUT = MEDIA / "out"
OUT.mkdir(parents=True, exist_ok=True)


def gen_media():
    ff = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    want = {
        "a1080.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=6", "-f", "lavfi", "-i", "sine=f=440:d=6",
                      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"],
        "r720.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=25:d=5", "-f", "lavfi", "-i", "sine=f=660:d=5",
                     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"],
        "noaudio.mp4": ["-f", "lavfi", "-i", "testsrc=s=640x480:r=24:d=4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an"],
        "clip.mkv": ["-f", "lavfi", "-i", "mandelbrot=s=800x600:r=30", "-f", "lavfi", "-i", "sine=f=300:d=4", "-t", "4", "-c:v", "mpeg4", "-c:a", "mp3"],
        "pic.png": ["-f", "lavfi", "-i", "testsrc2=s=1000x1000", "-frames:v", "1"],
        "song.mp3": ["-f", "lavfi", "-i", "sine=f=220:d=12,volume=0.5", "-c:a", "libmp3lame"],
    }
    for name, a in want.items():
        if not (MEDIA / name).exists():
            subprocess.run([*ff, *a, str(MEDIA / name)], check=True)
    rot = MEDIA / "r720rot.mp4"
    if not rot.exists():  # portrait phone clip: 1280x720 stored, rotated 90° on display
        subprocess.run([*ff, "-display_rotation:v:0", "90", "-i", str(MEDIA / "r720.mp4"), "-c", "copy", str(rot)], check=True)


def ffprobe(p):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)


class Ctx:  # stand-in for a jobs.Job
    cancelled = False
    def register_proc(self, p): pass
    def sub_progress(self, f, m=None): pass
    def note(self, m): self.last_note = m


M = {}


def media(name):
    if name not in M:
        info = ve.media_info(str(MEDIA / name))
        info["id"] = "m" + str(len(M))
        M[name] = info
    return M[name]


def clip(name, i=0, o=None, **kw):
    m = media(name)
    c = {"id": f"c{time.perf_counter_ns()}", "media": m["id"], "in": i, "out": o if o is not None else m["duration"],
         "speed": 1, "volume": 1}
    if m["kind"] == "image":
        c["dur"] = kw.pop("dur", 3)
    c.update(kw)
    return c


def project(clips, texts=(), music=(), mode="mix"):
    return {"media": list(M.values()), "clips": list(clips), "texts": list(texts), "music": list(music), "music_mode": mode}


RESULTS = []


def case(name, proj, settings, expect_dur, size=None, streams=("video", "audio")):
    t0 = time.time()
    fmt = settings.get("format", "mp4")
    out = OUT / f"{name}.{fmt}"
    try:
        args, dur = ve.build_export(proj, settings, out, OUT)
        assert abs(dur - expect_dur) < 0.05, f"planned duration {dur:.3f} != {expect_dur:.3f}"
        from core.conv_media import run_ffmpeg
        run_ffmpeg(args, Ctx(), dur)
        info = ffprobe(out)
        got = float(info["format"]["duration"])
        kinds = sorted({s["codec_type"] for s in info["streams"]})
        assert abs(got - expect_dur) <= 0.2 + (0.1 if fmt == "gif" else 0), f"duration {got:.3f} != {expect_dur:.3f}"
        assert kinds == sorted(streams), f"streams {kinds} != {sorted(streams)}"
        if size:
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            assert (v["width"], v["height"]) == size, f"size {v['width']}x{v['height']} != {size}"
        RESULTS.append((name, True, f"{got:.2f}s {kinds} ({time.time() - t0:.1f}s)"))
    except Exception as e:
        RESULTS.append((name, False, str(e).strip().splitlines()[-1][:300] if str(e).strip() else repr(e)))
        traceback.print_exc()


def unit_checks():
    # escaping: the value must come back literally through both ffmpeg parsing levels
    tricky = "it's 50% \"done\": yes\\no [a], b; c"
    v = ve.esc_value(tricky)
    assert "\\'" in v and "\\[" in v and "\\," in v
    assert ve._atempo(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert ve._atempo(4.0) == ["atempo=2", "atempo=2"]
    assert ve._atempo(1.0) == []
    pos, total = ve.layout([{"in": 0, "out": 4, "speed": 1}, {"in": 0, "out": 4, "speed": 2, "trans": {"type": "crossfade", "dur": 5}}])
    assert pos[1][2] == 1.0 and abs(total - 5.0) < 1e-6, (pos, total)  # crossfade clamped to half the shorter clip
    m = ve.media_info(str(MEDIA / "r720rot.mp4"))
    assert (m["width"], m["height"]) == (720, 1280) and m["rotation"] in (90, 270), m
    assert ve.media_info(str(MEDIA / "clip.mkv"))["playable"] is False
    assert ve.media_info(str(MEDIA / "a1080.mp4"))["playable"] is True
    assert ve.media_info(str(MEDIA / "pic.png"))["kind"] == "image"
    RESULTS.append(("unit: escaping/atempo/layout/probe", True, "ok"))


def main():
    gen_media()
    try:
        unit_checks()
    except Exception as e:
        traceback.print_exc()
        RESULTS.append(("unit checks", False, repr(e)))

    A, R, N, K, P, S = "a1080.mp4", "r720rot.mp4", "noaudio.mp4", "clip.mkv", "pic.png", "song.mp3"
    hd = {"format": "mp4", "resolution": "720p", "aspect": "16:9", "fps": "30", "crf": 30, "preset": "ultrafast"}
    case("trim", project([clip(A, 1, 4)]), hd, 3.0, (1280, 720))
    case("split_two_parts", project([clip(A, 0, 2.5), clip(A, 2.5, 6)]), hd, 6.0)
    case("speed_half_and_double", project([clip(A, 0, 2, speed=0.5), clip(R, 0, 4, speed=2)]), hd, 6.0)
    case("speed_quarter_and_4x", project([clip(A, 0, 1, speed=0.25), clip(A, 0, 4, speed=4)]), hd, 5.0)
    case("mute_and_volume", project([clip(A, 0, 2, muted=True), clip(R, 0, 2, volume=1.8)]), hd, 4.0)
    case("image_and_noaudio", project([clip(P, dur=2.5), clip(N, 0, 4), clip(K, 0, 2)]), hd, 8.5)
    case("text_tricky", project([clip(A, 0, 4)], texts=[
        {"text": 'it\'s 50% "done": yes\\no', "start": 0.5, "end": 3, "x": 0.5, "y": 0.9, "size": 7, "color": "#ffcc00", "box": True},
        {"text": "line one\nline two [a], b; c=d", "start": 1, "end": 4, "x": 0.1, "y": 0.1, "size": 5, "color": "#fff"}]), hd, 4.0)
    case("crossfade", project([clip(A, 0, 3), clip(R, 0, 3, trans={"type": "crossfade", "dur": 1}),
                               clip(N, 0, 3, trans={"type": "crossfade", "dur": 0.5}), clip(P, dur=2)]), hd, 11 - 1.5)
    case("music_duck", project([clip(A, 0, 6), clip(N, 0, 4)], music=[
        {"id": "mu1", "media": media(S)["id"], "start": 1, "in": 2, "out": 12, "volume": 0.8, "fade_in": 1, "fade_out": 2}], mode="duck"), hd, 10.0)
    case("music_mix_two_songs", project([clip(A, 0, 5)], music=[
        {"id": "mu1", "media": media(S)["id"], "start": 0, "in": 0, "out": 3, "volume": 1},
        {"id": "mu2", "media": media(S)["id"], "start": 2.5, "in": 5, "out": 12, "volume": 1.5}], mode="mix"), hd, 5.0)
    case("music_replace", project([clip(A, 0, 4)], music=[
        {"id": "mu1", "media": media(S)["id"], "start": 0, "in": 0, "out": 12}], mode="replace"), hd, 4.0)
    case("mixed_res_rot_crop_eq_fade", project([
        clip(A, 0, 2, rotate=90, crop={"t": 0.1, "b": 0.1, "l": 0.2, "r": 0}, eq={"brightness": 0.1, "contrast": 1.3, "saturation": 0.5}, fade_in=0.5),
        clip(R, 0, 2, rotate=180, fade_out=0.7), clip(K, 1, 3, rotate=270), clip(P, dur=1.5, crop={"t": 0, "b": 0, "l": 0.2, "r": 0.2})]),
        {**hd, "resolution": "source", "aspect": "keep", "fps": "source"}, 7.5)
    case("vertical_9x16", project([clip(A, 0, 2), clip(R, 0, 2)]), {**hd, "aspect": "9:16", "resolution": "1080p"}, 4.0, (1080, 1920))
    case("square_fill", project([clip(A, 0, 2), clip(R, 0, 2)]), {**hd, "aspect": "1:1", "resolution": "480p", "fit": "crop"}, 4.0, (480, 480))
    case("custom_size_mov", project([clip(K, 0, 3)]), {**hd, "format": "mov", "resolution": "custom", "width": 854, "height": 480}, 3.0, (854, 480))
    case("webm", project([clip(A, 0, 2), clip(N, 0, 1)]), {**hd, "format": "webm", "resolution": "360p"}, 3.0)
    case("gif", project([clip(A, 0, 2), clip(P, dur=1)]), {**hd, "format": "gif", "resolution": "source", "aspect": "keep", "fps": "30"}, 3.0, (640, 360), ("video",))
    case("audio_only_mp3", project([clip(A, 0, 3), clip(P, dur=1), clip(N, 0, 2)], music=[
        {"id": "mu1", "media": media(S)["id"], "start": 0, "in": 0, "out": 12, "volume": 0.5}], mode="duck"), {"format": "mp3"}, 6.0, None, ("audio",))
    case("audio_only_wav_crossfade", project([clip(A, 0, 3), clip(R, 0, 3, trans={"type": "crossfade", "dur": 1})]), {"format": "wav"}, 5.0, None, ("audio",))
    case("music_only_mp3", project([], music=[{"id": "mu1", "media": media(S)["id"], "start": 1, "in": 0, "out": 4}]), {"format": "mp3"}, 5.0, None, ("audio",))
    case("range_export", project([clip(A, 0, 6), clip(R, 0, 5, trans={"type": "crossfade", "dur": 1})]), {**hd, "range": [2.0, 7.5]}, 5.5)
    case("out_of_range_in_out", project([clip(A, 5.0, 9.0), clip(N, 0, 4)]), hd, 5.0)
    long_clips = [clip(A, i * 0.05, i * 0.05 + 0.2) for i in range(60)]
    case("many_clips_graph_file", project(long_clips, texts=[{"text": "x" * 20, "start": 0, "end": 12, "size": 5}] * 3), {**hd, "resolution": "360p"}, 12.0)

    for bad, proj, st in [("empty", project([]), hd), ("audio_only_timeline_as_video", project([clip(S, 0, 3)]), hd)]:
        try:
            ve.build_export(proj, st, OUT / "x.mp4", OUT)
            RESULTS.append((f"rejects {bad}", False, "no error raised"))
        except ValueError:
            RESULTS.append((f"rejects {bad}", True, "ValueError"))

    print("\n==== video editor export tests ====")
    for name, good, msg in RESULTS:
        print(f"{'PASS' if good else 'FAIL'}  {name:34s} {msg}")
    fails = sum(1 for r in RESULTS if not r[1])
    print(f"{len(RESULTS) - fails}/{len(RESULTS)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
