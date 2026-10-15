"""Dr. Doc desktop shell — the entry point of the packaged (Microsoft Store / MSIX) build.

Starts the Flask app (app.py) with waitress on a free localhost port in a background thread and shows it in a
native WebView2 window (pywebview, EdgeChromium backend). File pickers become real Windows dialogs.
Files passed on the command line ("Open with Dr. Doc", double-click) are handed to the UI as ?open=[paths].
A second launch forwards its files to the running window instead of opening another copy.
If WebView2 is not installed, falls back to an Edge/Chrome --app window (like app.py) and quits when it closes.

Run from source:  .venv\\Scripts\\python desktop.py [files...]     (app.py / Start.bat still work as before)
"""
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

# A windowed (no-console) build has no stdout/stderr; anything that prints would crash.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from core.util import NATIVE_DIALOGS, WORKSPACE  # noqa: E402  (creates the workspace folders)

LOG_FILE = WORKSPACE / "desktop.log"
STATE_FILE = WORKSPACE / "desktop.json"   # {"port": ..., "pid": ...} of the running instance
TITLE = "Dr. Doc"
SIZE = (1320, 880)
MIN_SIZE = (900, 620)
BG = "#efe9ff"

logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("drdoc.desktop")

WINDOW = None   # the pywebview window once created
BASE_URL = ""


def resource(*parts) -> Path:
    """Path to a bundled resource (PyInstaller _MEIPASS) or the source tree."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def icon_path():
    for p in (resource("assets", "drdoc.ico"), Path(__file__).resolve().parent / "packaging" / "assets" / "drdoc.ico"):
        if p.exists():
            return str(p)
    return None


def files_from_args(argv) -> list[str]:
    out = []
    for a in argv:
        if a.startswith("-"):
            continue
        p = os.path.abspath(a.strip().strip('"'))
        if os.path.exists(p):
            out.append(p)
    return out


# ---------------------------------------------------------------- single instance
_mutex = None


def is_primary_instance() -> bool:
    global _mutex
    if os.name != "nt":
        return True
    try:
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DrDoc.Desktop.SingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def forward_to_running(paths) -> bool:
    """Hand our files to the running instance (and bring it to front). True if it answered."""
    try:
        port = json.loads(STATE_FILE.read_text(encoding="utf-8"))["port"]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/desktop/open", data=json.dumps({"paths": paths}).encode(),
                                     headers={"Content-Type": "application/json", "X-Local-App": "1"}, method="POST")
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        log.info("forward to running instance failed: %s", e)
        return False


# ---------------------------------------------------------------- native dialogs (callable from any thread)
def _on_ui_thread(fn):
    """Run fn on the WinForms UI thread (WinForms dialogs need the STA UI thread) and return its result."""
    result = {}

    def call():
        try:
            result["value"] = fn()
        except Exception as e:  # noqa
            result["error"] = e
    try:
        from System import Action  # pythonnet, loaded by pywebview's WinForms backend
        from webview.platforms.winforms import BrowserView
        form = BrowserView.instances.get(WINDOW.uid)
        if form is not None and form.InvokeRequired:
            form.Invoke(Action(call))
        else:
            call()
    except ImportError:
        call()
    if "error" in result:
        raise result["error"]
    return result.get("value")


_dialog_lock = threading.Lock()


def _dialog(kind, **kw):
    import webview
    kw.setdefault("directory", str(Path.home()))
    with _dialog_lock:
        return _on_ui_thread(lambda: WINDOW.create_file_dialog(kind, **kw))


def native_pick_files():
    import webview
    return list(_dialog(webview.FileDialog.OPEN, allow_multiple=True) or [])


def native_pick_folder(title="Choose folder"):
    import webview
    res = _dialog(webview.FileDialog.FOLDER)
    if not res:
        return None
    return res[0] if isinstance(res, (list, tuple)) else res


# ---------------------------------------------------------------- server
def start_server(app, port):
    from waitress import create_server
    server = create_server(app, host="127.0.0.1", port=port, threads=12, max_request_body_size=1 << 50,
                           channel_timeout=3600, inbuf_overflow=1 << 22)
    threading.Thread(target=server.run, name="waitress", daemon=True).start()
    return server


def add_desktop_routes(app):
    from flask import jsonify, request

    @app.post("/api/desktop/open")
    def desktop_open():
        paths = [p for p in (request.json or {}).get("paths", []) if isinstance(p, str)]
        if WINDOW is not None:
            try:
                WINDOW.restore()
                WINDOW.show()
                WINDOW.on_top = True   # nudge to the foreground
                WINDOW.on_top = False
            except Exception:
                pass
            if paths:
                js_paths = json.dumps(paths)
                WINDOW.evaluate_js(
                    "(function(p){if(typeof addConvertFiles==='function'&&typeof route==='function'){route('convert');"
                    "api('/api/fileinfo',{paths:p}).then(function(r){addConvertFiles(r.files)});}"
                    "else{location.href='/?open='+encodeURIComponent(JSON.stringify(p));}})(" + js_paths + ")")
        return jsonify({"ok": True})


# ---------------------------------------------------------------- WebView2 detection + browser fallback
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_installed() -> bool:
    if os.name != "nt":
        return False
    import winreg
    keys = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
            (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}")]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as k:
                v = winreg.QueryValueEx(k, "pv")[0]
                if v and v != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def run_browser_fallback(url):
    """Chromeless Edge/Chrome window with its own profile, so we can wait for it to close."""
    candidates = [os.path.expandvars(p) for p in (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]
    for exe in candidates:
        if os.path.exists(exe):
            profile = WORKSPACE / "browser-profile"
            proc = subprocess.Popen([exe, f"--app={url}", f"--window-size={SIZE[0]},{SIZE[1]}",
                                     f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"])
            proc.wait()
            return
    import webbrowser
    webbrowser.open(url)
    ctypes.windll.user32.MessageBoxW(None, "Dr. Doc is running in your browser.\nClick OK to quit Dr. Doc.", TITLE, 0x40)


# ---------------------------------------------------------------- main
def main():
    global WINDOW, BASE_URL
    paths = files_from_args(sys.argv[1:])
    if not is_primary_instance():
        # another Dr. Doc is running (or still starting, e.g. several files opened at once): hand over our files
        import time
        deadline = time.time() + 20
        while time.time() < deadline:
            if forward_to_running(paths):
                return 0
            time.sleep(0.5)

    import app as drdoc   # the Flask app (registers all routes/blueprints)
    add_desktop_routes(drdoc.app)
    port = drdoc.free_port()
    server = start_server(drdoc.app, port)
    BASE_URL = f"http://127.0.0.1:{port}/"
    url = BASE_URL + (("?open=" + urllib.parse.quote(json.dumps(paths))) if paths else "")
    try:
        STATE_FILE.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass
    log.info("server on %s (frozen=%s, args=%s)", BASE_URL, getattr(sys, "frozen", False), paths)

    try:
        use_webview = "--browser" not in sys.argv and webview2_installed()
        if use_webview:
            try:
                import webview
                webview.settings["ALLOW_DOWNLOADS"] = True
                WINDOW = webview.create_window(TITLE, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE,
                                               background_color=BG, text_select=True, zoomable=True,
                                               hidden="--hidden" in sys.argv)  # --hidden: smoke tests
                NATIVE_DIALOGS["files"] = native_pick_files
                NATIVE_DIALOGS["folder"] = native_pick_folder
                webview.start(gui="edgechromium", private_mode=False, storage_path=str(WORKSPACE / "webview"),
                              icon=icon_path(), debug="--debug" in sys.argv)
            except Exception:
                log.exception("WebView2 window failed — falling back to browser window")
                NATIVE_DIALOGS.clear()
                WINDOW, use_webview = None, False
        if not use_webview:
            run_browser_fallback(url)
    finally:
        log.info("window closed, shutting down")
        try:
            server.close()
        except Exception:
            pass
        try:
            STATE_FILE.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    code = main()
    os._exit(code or 0)   # don't wait for job/worker threads — the window is gone
