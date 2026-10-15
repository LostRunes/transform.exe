"""Smoke-test a built Dr. Doc: start it, find its localhost port, call /api/caps, run real conversions, stop it.

  python packaging\\smoke_test.py --exe <dist>\\DrDoc\\DrDoc.exe        # frozen onedir build
  python packaging\\smoke_test.py --aumid <PackageFamilyName>!DrDoc     # installed MSIX (launched via shell:AppsFolder)
Exit code 0 = all checks passed. Uses only the standard library.
"""
import argparse
import csv
import io
import json
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
import zlib
from pathlib import Path


def drdoc_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DrDoc.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return {int(r[1]) for r in csv.reader(io.StringIO(out)) if len(r) > 1 and r[0].lower() == "drdoc.exe"}


def listening_ports(pids):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    ports = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].startswith("127.0.0.1:") and int(parts[4]) in pids:
            ports.append(int(parts[1].rsplit(":", 1)[1]))
    return ports


def call(base, path, body=None, timeout=30):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Local-App": "1"},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def make_png(path: Path, w=64, h=48):
    raw = b"".join(b"\x00" + bytes(v for x in range(w) for v in (x * 4 % 256, y * 5 % 256, 160)) for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_wav(path: Path, seconds=1):
    import math
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
        wf.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(22050 * seconds)))


def run_job(base, items, out_dir, timeout=120):
    job = call(base, "/api/convert", {"items": items, "out_dir": str(out_dir), "params": {}})["job"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = next((j for j in call(base, "/api/jobs")["jobs"] if j["id"] == job["id"]), None)
        if j and j["status"] not in ("running", "queued"):
            return j
        time.sleep(0.5)
    raise TimeoutError("job did not finish")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--exe")
    g.add_argument("--aumid")
    ap.add_argument("--keep", action="store_true", help="leave the app running")
    a = ap.parse_args()

    before = drdoc_pids()
    if before:
        print(f"note: DrDoc.exe already running (pids {sorted(before)}) — those are ignored")
    if a.exe:
        # minimal PATH, so the test proves the *bundled* binfmpeg.exe is used (not one installed on this PC)
        import os
        env = dict(os.environ, PATH=os.pathsep.join([os.path.join(os.environ["SystemRoot"], "System32"), os.environ["SystemRoot"]]))
        subprocess.Popen([a.exe, "--hidden"], env=env)
    else:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{a.aumid}"])

    base, t0 = None, time.time()
    while time.time() - t0 < 90 and not base:
        time.sleep(1)
        new = drdoc_pids() - before
        for port in listening_ports(new):
            try:
                if call(f"http://127.0.0.1:{port}", "/api/caps", timeout=5).get("ok"):
                    base = f"http://127.0.0.1:{port}"
            except Exception:
                pass
    results, ok_all = [], True
    try:
        if not base:
            print("FAIL: app did not start / no port answered within 90 s")
            return 1
        print(f"started in {time.time() - t0:.1f}s at {base}")
        caps = call(base, "/api/caps")
        print("caps:", {k: v for k, v in caps["caps"].items()})
        idx = urllib.request.urlopen(base + "/", timeout=10).read()
        print(f"GET / -> {len(idx)} bytes of HTML")

        tmp = Path(tempfile.mkdtemp(prefix="drdoc-smoke-"))
        out = tmp / "out"
        make_png(tmp / "sample.png")
        make_wav(tmp / "tone.wav")
        tests = [("png->jpg", tmp / "sample.png", "jpg"), ("png->pdf", tmp / "sample.png", "pdf")]
        if caps["caps"].get("ffmpeg"):
            tests.append(("wav->mp3 (ffmpeg)", tmp / "tone.wav", "mp3"))
        for label, src, target in tests:
            j = run_job(base, [{"path": str(src), "target": target}], out)
            good = j["status"] == "done" and j["outputs"] and all(Path(p).exists() and Path(p).stat().st_size > 0 for p in j["outputs"])
            ok_all &= bool(good)
            results.append(f"{'PASS' if good else 'FAIL'}: {label}: {j['status']} {j['outputs'] or j['errors']}")
        if not caps["caps"].get("ffmpeg"):
            results.append("WARN: ffmpeg not detected — video/audio disabled in this build")
        print("\n".join(results))
        return 0 if ok_all else 1
    finally:
        if not a.keep:
            for pid in drdoc_pids() - before:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
