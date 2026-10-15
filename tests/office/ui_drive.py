"""End-to-end UI check for the Docs & sheets screen, driving headless Edge over the DevTools protocol.
Needs: the app running (python app.py --no-browser), `pip install websocket-client` (test-only), Microsoft Edge.
Usage:  python tests/office/ui_drive.py <port> <samples_dir> <out_dir> [--big]
Saves screenshots into <out_dir> and prints PASS/FAIL lines."""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import websocket  # websocket-client

PORT, SAMPLES, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DBG = 9339
os.makedirs(OUT, exist_ok=True)
SAVE_DIR = os.path.join(OUT, "saved")
shutil.rmtree(SAVE_DIR, ignore_errors=True)
os.makedirs(SAVE_DIR, exist_ok=True)
results = []


class CDP:
    def __init__(self):
        prof = os.path.join(OUT, "edge-profile")
        shutil.rmtree(prof, ignore_errors=True)
        self.proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={DBG}",
                                      f"--user-data-dir={prof}", "--window-size=1400,900", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DBG}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
        self.i = 0
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Browser.grantPermissions", {"permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
                                               "origin": f"http://127.0.0.1:{PORT}"})
        self.send("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.errors = []

    def send(self, method, params=None):
        self.i += 1
        my = self.i
        self.ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                self.errors.append(msg["params"]["exceptionDetails"].get("exception", {}).get("description", "?"))
            if msg.get("method") == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
                self.errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"]))
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def jsel(self, expr):
        """Run JS that changes the selection, then let 'selectionchange' fire like it would for a person."""
        v = self.js(expr)
        time.sleep(0.15)
        return v

    def js(self, expr, await_promise=True):
        r = self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": await_promise, "returnByValue": True})
        if "exceptionDetails" in r:
            raise RuntimeError("JS error: " + r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"])))
        return r["result"].get("value")

    def wait(self, expr, timeout=30, step=0.15):
        t = time.time()
        while time.time() - t < timeout:
            try:
                if self.js(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(step)
        return False

    def key(self, key, code=None, vk=None, mods=0, text=None):
        base = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk or 0, "modifiers": mods}
        self.send("Input.dispatchKeyEvent", {"type": "keyDown" if text else "rawKeyDown", **base, **({"text": text} if text else {})})
        self.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def ctrl(self, letter, shift=False):
        self.key(letter, "Key" + letter.upper(), ord(letter.upper()), mods=2 | (8 if shift else 0))

    def type(self, text):
        for ch in text:
            if ch == "\n":
                self.key("Enter", "Enter", 13, text="\r")
            elif ch == "\t":
                self.key("Tab", "Tab", 9)
            else:
                self.key(ch, text=ch)

    def click(self, x, y, mods=0, count=1):
        for t in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "clickCount": count, "modifiers": mods})

    def click_el(self, selector, mods=0, count=1):
        r = self.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        self.click(r[0], r[1], mods, count)

    def shot(self, name):
        data = self.send("Page.captureScreenshot", {"format": "png"})["data"]
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(base64.b64decode(data))

    def open(self, path, theme="light"):
        url = f"http://127.0.0.1:{PORT}/?t={time.time()}#office={urllib.parse.quote(path)}&notour&theme={theme}"
        self.send("Page.navigate", {"url": url})
        time.sleep(0.5)
        ok = self.wait("!!(document.querySelector('.of-page') || document.querySelector('.og-c') || document.querySelector('.of-pg') || document.querySelector('.of-slide'))", 60)
        self.js(f"App.S.outDir = {json.dumps(SAVE_DIR)}")
        return ok


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def saved_files():
    return sorted(os.listdir(SAVE_DIR))


def doc_tests(b):
    check("doc opens", b.open(os.path.join(SAMPLES, "rich.docx")))
    time.sleep(0.5)
    # put the caret at the end of the "Introduction" heading and type
    b.jsel("""(() => { const h = [...document.querySelectorAll('.of-page h1')].find(x => x.textContent === 'Introduction');
      const r = document.createRange(); r.selectNodeContents(h); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      document.querySelector('.of-page').focus(); })()""")
    b.type(" v2")
    check("typing goes into the document", b.js("document.querySelector('.of-page').innerHTML.includes('Introduction v2')"))
    check("dirty indicator shows", b.js("document.querySelector('.of-bar .titlebar').textContent.includes('unsaved')"))
    # select "Plain" and press Ctrl+B
    sel_plain = """(() => { const p = [...document.querySelectorAll('.of-page p')].find(x => x.textContent.startsWith('Plain'));
      const t = p.firstChild; const r = document.createRange(); r.setStart(t, 0); r.setEnd(t, 5); const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()"""
    b.jsel(sel_plain)
    b.ctrl("b")
    check("Ctrl+B bolds the selection", b.js("/<b>Plain<\\/b>/.test(document.querySelector('.of-page').innerHTML)"))
    b.ctrl("z")
    check("Ctrl+Z undoes it", b.js("!/<b>Plain<\\/b>/.test(document.querySelector('.of-page').innerHTML) && document.querySelector('.of-page').innerHTML.includes('Introduction v2')"))
    b.ctrl("y")
    check("Ctrl+Y redoes it", b.js("/<b>Plain<\\/b>/.test(document.querySelector('.of-page').innerHTML)"))
    # font size via the dropdown
    b.jsel(sel_plain.replace("p.firstChild", "p.querySelector('b').firstChild"))
    b.js("(() => { const s = document.querySelector('select[aria-label=\"Font size\"]'); s.value = '24'; s.dispatchEvent(new Event('change')); })()")
    check("font size applies a span", b.js("document.querySelector('.of-page').innerHTML.includes('font-size: 24pt')"))
    # paragraph style: make "Centered paragraph" a Heading 2
    b.jsel("""(() => { const p = [...document.querySelectorAll('.of-page p')].find(x => x.textContent === 'Centered paragraph');
      const r = document.createRange(); r.setStart(p.firstChild, 2); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
    b.js("""(() => { const sel = document.querySelector('select[aria-label=\"Paragraph style\"]'); sel.value = '3'; sel.dispatchEvent(new Event('change')); })()""")
    check("paragraph style -> Heading 2 (keeps alignment)", b.js("[...document.querySelectorAll('.of-page h2')].some(x => x.textContent === 'Centered paragraph' && x.style.textAlign === 'center')"))
    # bulleted list from a paragraph
    b.jsel("""(() => { const p = [...document.querySelectorAll('.of-page p')].find(x => x.textContent === 'Right aligned');
      const r = document.createRange(); r.setStart(p.firstChild, 1); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
    b.click_el('button[aria-label="Bulleted list"]')
    check("bulleted list button", b.js("[...document.querySelectorAll('.of-page ul li')].some(x => x.textContent === 'Right aligned')"))
    # insert a 2x3 table via the picker after the last paragraph
    b.jsel("""(() => { const ps = document.querySelectorAll('.of-page p'); const p = ps[ps.length - 1];
      const r = document.createRange(); r.selectNodeContents(p); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
    b.click_el('button[aria-label="Insert table"]')
    b.wait("!!document.querySelector('.of-tpick i[data-r=\"1\"][data-c=\"2\"]')", 5)
    b.click_el('.of-tpick i[data-r="1"][data-c="2"]')
    n_tables = b.js("document.querySelectorAll('.of-page table').length")
    check("table picker inserts a 2x3 table", n_tables == 2 and b.js("(() => { const t = [...document.querySelectorAll('.of-page table')].pop(); return t.rows.length === 2 && t.rows[0].cells.length === 3; })()"), n_tables)
    b.type("cell A")
    b.key("Tab", "Tab", 9)
    b.type("cell B")
    check("typing in table cells + Tab moves to next cell", b.js("(() => { const t = [...document.querySelectorAll('.of-page table')].pop(); return t.rows[0].cells[0].textContent === 'cell A' && t.rows[0].cells[1].textContent === 'cell B'; })()"))
    b.js("[...document.querySelectorAll('.of-menu')].forEach(m => m.hidden = true)")
    # find & replace
    b.ctrl("h")
    check("Ctrl+H opens find & replace", b.wait("!document.querySelector('.of-find').hidden", 3))
    b.js("""(() => { const f = document.querySelector('.of-find'); const [q, r] = f.querySelectorAll('input[type=text]');
      q.value = 'Justified'; q.dispatchEvent(new Event('input')); r.value = 'Even'; })()""")
    cnt = b.js("document.querySelector('.of-find-count').textContent")
    check("find counts matches", cnt == "1 of 12", cnt)
    b.shot("ui_doc_find.png")
    b.js("[...document.querySelectorAll('.of-find button')].find(x => x.textContent === 'Replace all').click()")
    check("replace all", b.js("!document.querySelector('.of-page').innerText.includes('Justified') && document.querySelector('.of-page').innerText.split('Even').length === 13"))
    b.key("Escape", "Escape", 27)
    time.sleep(0.4)
    words = b.js("document.querySelector('.of-status').textContent")
    expect = b.js("(document.querySelector('.of-page').innerText.match(/[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*/gu) || []).length")
    check("word count shown and current", f"{expect} words" in words, f"{words} vs {expect}")
    # print layout: only the page is shown
    b.js("document.body.classList.add('of-printing')")
    b.send("Emulation.setEmulatedMedia", {"media": "print"})
    vis = b.js("[...document.querySelectorAll('.sidebar,.of-bar,.topbar,.taskbar')].every(e => getComputedStyle(e).display === 'none') && getComputedStyle(document.querySelector('.of-page')).boxShadow === 'none'")
    check("print stylesheet shows only the page", vis)
    b.shot("ui_doc_print.png")
    b.send("Emulation.setEmulatedMedia", {"media": ""})
    b.js("document.body.classList.remove('of-printing')")
    # save (Ctrl+S) -> "rich (edited).docx"
    b.js("document.querySelector('.of-page').focus()")
    b.ctrl("s")
    check("Ctrl+S saves a copy", b.wait(f"!document.querySelector('.of-bar .titlebar').textContent.includes('unsaved')", 30))
    time.sleep(0.3)
    files = saved_files()
    check("saved file is 'rich (edited).docx'", "rich (edited).docx" in files, files)
    b.shot("ui_doc_saved.png")
    # export to pdf + md
    b.click_el('button[aria-label="Export to PDF"]')
    check("Export to PDF", b.wait("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('PDF ready'))", 90))
    return files


def sheet_cell(b, r, c):
    return b.js(f"(() => {{ const e = document.getElementById('og-{r}-{c}'); return e ? e.textContent : null; }})()")


def sheet_tests(b):
    ok = b.open(os.path.join(SAMPLES, "multi.xlsx"))
    if not ok:
        b.shot("ui_fail_sheet_open.png")
        print("   page text:", b.js("document.body.innerText.slice(0, 400)"))
    check("sheet opens", ok)
    b.wait("document.getElementById('og-1-3')?.textContent === '3.75'", 15)
    check("cached formula value shows", sheet_cell(b, 1, 3) == "3.75", sheet_cell(b, 1, 3))
    check("currency number format", sheet_cell(b, 1, 2) == "$1.25", sheet_cell(b, 1, 2))
    check("grid has role=grid & aria indexes", b.js("document.querySelector('.og-vp').getAttribute('role') === 'grid' && document.getElementById('og-1-3').getAttribute('aria-colindex') === '4'"))
    # click B2, type 10, Enter
    b.click_el("#og-1-1")
    check("formula bar shows raw value", b.js("document.querySelector('.of-formula').value") == "3")
    b.type("10\n")
    check("typing edits the cell and Enter commits", b.wait("document.getElementById('og-1-3')?.textContent === '12.5'", 10), sheet_cell(b, 1, 3))
    check("SUM recalculates", b.wait("document.getElementById('og-6-3')?.textContent === '25.7'", 10), sheet_cell(b, 6, 3))
    check("Enter moved down to B3", b.js("document.querySelector('.of-name').value") == "B3")
    # formula entry
    b.click_el("#og-10-0") if b.js("!!document.getElementById('og-10-0')") else None
    b.type("=SUM(B2:B5)*2\n")
    check("new formula evaluates", b.wait("document.getElementById('og-10-0')?.textContent === '58'", 10), sheet_cell(b, 10, 0))
    # undo / redo
    b.js("document.querySelector('.og-vp').focus()")
    b.ctrl("z")
    check("Ctrl+Z undoes the formula", b.wait("document.getElementById('og-10-0')?.textContent === ''", 10), sheet_cell(b, 10, 0))
    b.ctrl("y")
    check("Ctrl+Y redoes it", b.wait("document.getElementById('og-10-0')?.textContent === '58'", 10))
    # range select A2:B3 with shift-click and copy
    b.click_el("#og-1-0")
    b.click_el("#og-2-1", mods=8)
    check("shift-click selects a range", b.js("document.querySelector('.of-name').value") == "A2:B3")
    b.ctrl("c")
    time.sleep(0.3)
    clip = b.js("navigator.clipboard.readText()")
    check("copy puts TSV on the clipboard", clip == "Apples\t10\r\nPears\t5", repr(clip))
    # paste into H1
    b.js("navigator.clipboard.writeText('x\\ty\\n1\\t2')")
    b.click_el("#og-0-7")
    b.ctrl("v")
    check("paste TSV fills cells", b.wait("document.getElementById('og-1-8')?.textContent === '2'", 10), sheet_cell(b, 1, 8))
    # delete clears
    b.click_el("#og-1-8")
    b.key("Delete", "Delete", 46)
    check("Delete clears the cell", b.wait("document.getElementById('og-1-8')?.textContent === ''", 10))
    # bold via toolbar on A3
    b.click_el("#og-2-0")
    b.ctrl("b")
    check("Ctrl+B bolds a cell", b.wait("getComputedStyle(document.getElementById('og-2-0')).fontWeight === '700'", 10))
    # filter
    b.js("(() => { const s = document.querySelector('.of-search'); s.value = 'pear'; s.dispatchEvent(new Event('input')); })()")
    check("filter shows matching rows only", b.wait("document.querySelectorAll('.og-rows .og-r').length === 1 && document.querySelector('.og-rows .og-r').textContent === '3'", 10),
          b.js("[...document.querySelectorAll('.og-rows .og-r')].map(x => x.textContent).join(',')"))
    b.shot("ui_sheet_filter.png")
    b.js("(() => { const s = document.querySelector('.of-search'); s.value = ''; s.dispatchEvent(new Event('input')); })()")
    b.wait("document.querySelectorAll('.og-rows .og-r').length > 5", 10)
    # insert a row above row 3 via menu
    b.click_el("#og-2-0")
    b.click_el('button[aria-label="Insert or delete rows"]')
    b.js("[...document.querySelectorAll('.of-menu button')].find(x => x.textContent.startsWith('Insert row')).click()")
    check("insert row shifts data down", b.wait("document.getElementById('og-3-0')?.textContent === 'Pears' && document.getElementById('og-2-0')?.textContent === ''", 10))
    check("formula refs shift (SUM moved to row 8)", b.wait("document.getElementById('og-7-3')?.textContent === '25.7'", 10), sheet_cell(b, 7, 3))
    b.ctrl("z")
    check("Ctrl+Z right after a toolbar menu undoes the insert", b.wait("document.getElementById('og-2-0')?.textContent === 'Pears'", 10))
    # column resize via drag
    w0 = b.js("document.getElementById('og-1-0').offsetWidth")
    r = b.js("(() => { const r = document.querySelector('.og-h[data-c=\"0\"] .rz').getBoundingClientRect(); return [r.left + 3, r.top + 10]; })()")
    b.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": r[0], "y": r[1], "button": "left", "clickCount": 1})
    b.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": r[0] + 60, "y": r[1], "button": "left"})
    b.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": r[0] + 60, "y": r[1], "button": "left", "clickCount": 1})
    check("column resize by dragging", b.wait(f"document.getElementById('og-1-0').offsetWidth > {w0 + 40}", 5))
    # sheet tabs: switch to Notes
    b.js("[...document.querySelectorAll('.of-tabs [role=tab]')].find(t => t.textContent === 'Notes').click()")
    check("sheet tab switch", b.wait("document.getElementById('og-0-0')?.textContent === 'Keep me'", 10))
    check("cross-sheet formula shows value", b.wait("document.getElementById('og-1-1')?.textContent === '51.4'", 10), sheet_cell(b, 1, 1))
    b.js("[...document.querySelectorAll('.of-tabs [role=tab]')].find(t => t.textContent === 'Sales').click()")
    b.wait("document.getElementById('og-1-0')?.textContent === 'Apples'", 10)
    b.shot("ui_sheet.png")
    b.js("document.querySelector('.og-vp').focus()")
    b.ctrl("s")
    check("Ctrl+S saves the workbook", b.wait("!document.querySelector('.of-bar .titlebar').textContent.includes('unsaved')", 60))
    time.sleep(0.5)
    files = saved_files()
    check("saved 'multi (edited).xlsx'", "multi (edited).xlsx" in files, files)
    return files


def csv_tests(b):
    check("csv opens", b.open(os.path.join(SAMPLES, "tricky.csv")))
    b.wait("document.getElementById('og-1-0')?.textContent === 'Zoë'", 10)
    check("csv quoting & unicode", sheet_cell(b, 1, 1) == 'She said "hi", then left' and sheet_cell(b, 2, 0) == "日本")
    check("csv keeps 007 as text", sheet_cell(b, 1, 3) == "007")
    b.shot("ui_csv.png")


def big_tests(b):
    t0 = time.time()
    check("big xlsx shows a preview while loading", b.open(os.path.join(SAMPLES, "big.xlsx")))
    check("loading banner visible", b.js("!document.querySelector('.of-banner').hidden"))
    b.shot("ui_big_loading.png")
    check("big workbook becomes editable", b.wait("document.querySelector('.of-banner').hidden", 240, 1))
    print(f"   (loaded in {time.time() - t0:.0f}s)")
    t = time.time()
    b.js("document.querySelector('.og-vp').focus()")
    b.key("End", "End", 35, mods=2)  # Ctrl+End: last data cell
    ok = b.wait("[...document.querySelectorAll('.og-rows .og-r')].some(x => x.textContent === '100001') && document.getElementById('og-100000-1')?.textContent === 'name 100000'", 20, 0.05)
    check("Ctrl+End jumps to row 100,001 and renders it (virtualised)", ok)
    check("name box shows E100001", b.js("document.querySelector('.of-name').value") == "E100001")
    ncells = b.js("document.querySelectorAll('.og-c').length")
    print(f"   (jump to bottom rendered in {(time.time() - t) * 1000:.0f} ms, DOM cells: {ncells})")
    b.shot("ui_big_bottom.png")
    b.js("(() => { const s = document.querySelector('.of-search'); s.value = 'name 99999'; s.dispatchEvent(new Event('input')); })()")
    check("filter on 100k rows", b.wait("document.querySelectorAll('.og-rows .og-r').length === 1", 20))


def viewer_tests(b):
    pdfs = [f for f in saved_files() if f.endswith(".pdf")]
    if pdfs:
        check("pdf viewer opens", b.open(os.path.join(SAVE_DIR, pdfs[0])))
        check("pdf pages render", b.wait("document.querySelector('.of-pg img')?.complete && document.querySelector('.of-pg img').naturalWidth > 0", 20))
        b.shot("ui_pdf.png")
        b.js("[...document.querySelectorAll('.of-tools .btn')].find(x => x.textContent.includes('PDF editor')).click()")
        check("Edit in PDF editor switches view", b.wait("!document.getElementById('view-editor').hidden && !!document.querySelector('#view-editor .ed-stage')", 20))
    pp = os.path.join(SAMPLES, "deck.pptx")
    if os.path.exists(pp):
        check("pptx viewer opens", b.open(pp))
        check("slides render", b.wait("document.querySelector('.of-pg img')?.naturalWidth > 0 || !!document.querySelector('.of-slide')", 60))
        b.shot("ui_pptx.png")


def empty_state(b):
    b.send("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/?e={time.time()}#notour&theme=dark"})
    time.sleep(1)
    b.js("document.querySelector('#nav a[data-view=\"office\"]').click()")
    check("empty state with recent files", b.wait("!!document.querySelector('.of-empty') && document.querySelectorAll('.of-recent button').length >= 2", 10))
    b.shot("ui_empty_dark.png")


if __name__ == "__main__":
    b = CDP()
    try:
        doc_tests(b)
        sheet_tests(b)
        csv_tests(b)
        viewer_tests(b)
        empty_state(b)
        if "--big" in sys.argv:
            big_tests(b)
    finally:
        errs = [e for e in b.errors if "favicon" not in e]
        check("no JavaScript errors", not errs, "; ".join(errs[:5]))
        b.ws.close()
        b.proc.kill()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} UI checks passed")
    sys.exit(1 if failed else 0)
