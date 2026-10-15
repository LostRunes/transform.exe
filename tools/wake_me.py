"""Wake the developer up: max volume, an alarm, then a spoken status update.

usage:
    python tools/wake_me.py                      # speaks the default message
    python tools/wake_me.py --message-file m.txt # speaks the text in m.txt
    python tools/wake_me.py --rounds 3 --dry-run # build everything, play nothing

Press Ctrl+Space anywhere (any window) to stop the alarm and the voice immediately.

Windows only. Volume is raised through the Core Audio API (via PowerShell), the alarm is a
generated WAV played with winsound, and the voice is Windows' built-in speech (SAPI).
"""
import argparse
import math
import struct
import subprocess
import ctypes
import ctypes.wintypes
import tempfile
import threading
import time
import wave
from pathlib import Path

DEFAULT_MESSAGE = (
    "Wake up! This is Claude, your coding assistant, working on your Dr. Doc project, "
    "the convert-anything app in the folder called everything on your desktop. "
    "I've finished the work you asked for. Please come back to the computer and read my summary in VS Code."
)

# Core Audio from PowerShell: unmute and set the default speakers to a volume (0..1).
VOLUME_PS = r"""
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float level, System.Guid ctx);
  int j(); int GetMasterVolumeLevelScalar(out float level);
  int k(); int l(); int m(); int n();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, System.Guid ctx);
  int GetMute(out bool mute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid id, int ctx, int p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice ep); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorCom { }
public class Vol {
  static IAudioEndpointVolume Ep() {
    var en = new MMDeviceEnumeratorCom() as IMMDeviceEnumerator;
    IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
    var iid = typeof(IAudioEndpointVolume).GUID; object o;
    dev.Activate(ref iid, 23, 0, out o);
    return (IAudioEndpointVolume)o;
  }
  public static float Get() { float v; Ep().GetMasterVolumeLevelScalar(out v); return v; }
  public static void Set(float v) { var e = Ep(); e.SetMute(false, System.Guid.Empty); e.SetMasterVolumeLevelScalar(v, System.Guid.Empty); }
}
'@
"""


def volume(level=None):
    """Set (or just read, when level is None) the speaker volume. Returns the volume before."""
    cmd = VOLUME_PS + ("[Vol]::Get()" if level is None else f"$b=[Vol]::Get(); [Vol]::Set({level}); $b")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("volume control failed:", r.stderr.strip()[:300])
        return None


def make_alarm(path: Path, seconds=6.0, rate=44100):
    """A siren sweep plus beeps: hard to sleep through."""
    frames = bytearray()
    n = int(seconds * rate)
    for i in range(n):
        t = i / rate
        sweep = 650 + 450 * math.sin(2 * math.pi * 0.9 * t)            # wailing siren
        beep = 1800 if (t * 4) % 1 < 0.5 else 0                          # fast beeps on top
        s = 0.55 * math.sin(2 * math.pi * sweep * t) + (0.35 * math.sin(2 * math.pi * beep * t) if beep else 0)
        frames += struct.pack("<h", int(max(-1, min(1, s)) * 32000))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


STOP = threading.Event()


def listen_for_stop():
    """System-wide Ctrl+Space hotkey (works whichever window has focus) that sets STOP."""
    user32 = ctypes.windll.user32
    MOD_CONTROL, MOD_NOREPEAT, VK_SPACE, WM_HOTKEY = 0x0002, 0x4000, 0x20, 0x0312
    if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_NOREPEAT, VK_SPACE):
        print("Couldn't register Ctrl+Space (another app owns it). Close this window to stop.")
        return
    msg = ctypes.wintypes.MSG()
    try:
        while not STOP.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                print("Ctrl+Space: stopping")
                STOP.set()
    finally:
        user32.UnregisterHotKey(None, 1)


def wait(seconds: float) -> bool:
    """Sleep, but wake early when stopped. True = keep going."""
    return not STOP.wait(seconds)


def say_until_done_or_stopped(text: str):
    """Speak asynchronously so Ctrl+Space can cut the voice off mid-sentence."""
    try:
        import win32com.client
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Volume = 100
        voice.Rate = -1
        voice.Speak(text, 1)  # SVSFlagsAsync
        while not voice.WaitUntilDone(100):
            if STOP.is_set():
                voice.Speak("", 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak: silence now
                return
    except Exception:
        speak(text)


def speak(text: str, dry=False):
    """Windows' built-in voice, slightly slower and at full volume."""
    try:
        import win32com.client
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Volume = 100
        voice.Rate = -1
        if not dry:
            voice.Speak(text)
        return True
    except Exception:
        safe = text.replace("'", "''")
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.Volume = 100; $s.Rate = -1; " + ("" if dry else f"$s.Speak('{safe}')"))
        return subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=300).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message-file")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    msg = Path(a.message_file).read_text(encoding="utf-8").strip() if a.message_file else DEFAULT_MESSAGE

    alarm = Path(tempfile.gettempdir()) / "drdoc_wake_alarm.wav"
    make_alarm(alarm)
    if a.dry_run:
        print("alarm:", alarm, alarm.stat().st_size, "bytes")
        print("current volume:", volume(None))
        print("voice ok:", speak(msg, dry=True))
        print("message:", msg)
        return

    import winsound
    threading.Thread(target=listen_for_stop, daemon=True).start()
    before = volume(1.0)
    print("volume raised to 100% (was", before, "). Press Ctrl+Space to stop.")
    try:
        for r in range(a.rounds):
            if STOP.is_set():
                break
            winsound.PlaySound(str(alarm), winsound.SND_FILENAME | winsound.SND_ASYNC)
            if not wait(6.2):  # the alarm's length
                break
            say_until_done_or_stopped(msg)
            if not wait(1.5):
                break
    finally:
        winsound.PlaySound(None, winsound.SND_PURGE)  # cut the alarm off if it's still playing
        if before is not None:
            volume(max(before, 0.4))  # put it back, but loud enough to hear the next message


if __name__ == "__main__":
    main()
