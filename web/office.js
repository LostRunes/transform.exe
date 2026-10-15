/* Docs & sheets: a Word-style document editor, a spreadsheet grid, and read-only slide / PDF viewers.
   Plain JS, offline. Server side: core/api_office.py + core/office_editor.py. */
(function () {
  const { $, $$, h, api, toast, fail, ask, S, store, pickFiles, mascotImg, titlebar } = window.App;
  if (!document.querySelector('link[href="/web/office.css"]')) document.head.append(h("link", { rel: "stylesheet", href: "/web/office.css" }));

  const KIND = (ext) => (["docx", "docm", "dotx", "doc", "rtf", "odt", "txt", "md", "markdown", "html", "htm"].includes(ext) ? "doc"
    : ["xlsx", "xlsm", "xltx", "xls", "ods", "csv", "tsv"].includes(ext) ? "sheet"
    : ["pptx", "ppt", "pptm", "pps", "ppsx", "odp"].includes(ext) ? "slides" : ext === "pdf" ? "pdf" : "other");
  const O = { root: null, file: null, view: null, caps: {}, opening: false };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const isDirty = () => !!O.view?.dirty?.();

  // ------------------------------------------------------------------ small UI helpers
  /** Toolbar button. keep=true keeps the text selection in the document while clicking. */
  function tb(label, title, onclick, { cls = "", keep = true, id = null } = {}) {
    return h("button", { type: "button", class: "tb " + cls, title, "aria-label": title, id, onclick,
      onmousedown: keep ? (e) => e.preventDefault() : null }, label);
  }
  const sep = () => h("span", { class: "sep", "aria-hidden": "true" });
  const DOTS = (ys) => ys.map((y) => `<path d="M4 ${y}h.01" stroke-width="3"/>`).join("");
  const NUM = (n, y) => `<text x="1.2" y="${y}" font-size="6.5" stroke="none" fill="currentColor" font-weight="700">${n}</text>`;
  const ICONS = {
    left: '<path d="M3 5h14M3 9h9M3 13h14M3 17h9"/>', center: '<path d="M3 5h14M6 9h8M3 13h14M6 17h8"/>',
    right: '<path d="M3 5h14M8 9h9M3 13h14M8 17h9"/>', justify: '<path d="M3 5h14M3 9h14M3 13h14M3 17h14"/>',
    ul: '<path d="M8 5h9M8 10h9M8 15h9"/>' + DOTS([5, 10, 15]),
    ol: '<path d="M9 5h8M9 10h8M9 15h8"/>' + NUM(1, 7.5) + NUM(2, 12.5) + NUM(3, 17.5),
    indent: '<path d="M3 4h14M9 8h8M9 12h8M3 16h14M3 7l3 3-3 3"/>', outdent: '<path d="M3 4h14M9 8h8M9 12h8M3 16h14M6 7l-3 3 3 3"/>',
    table: '<rect x="3" y="4" width="14" height="12" rx="1.5"/><path d="M3 8h14M3 12h14M8 4v12M12.5 4v12"/>',
    image: '<rect x="3" y="4" width="14" height="12" rx="1.5"/><path d="M4 15l4-5 3 3 2-2 3 4"/><circle cx="13" cy="7.5" r="1.3"/>',
    link: '<path d="M8.5 11.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-1 1M11.5 8.5a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l1-1"/>',
    hr: '<path d="M3 10h14"/><path d="M3 5h6M3 15h9" opacity=".35"/>',
    pagebreak: '<path d="M5 3v4h10V3M5 17v-4h10v4"/><path d="M2 10h3M7.5 10h2M12 10h2M16.5 10h1.5"/>',
    clear: '<path d="M5 4h10M10 4l-3 12M4 16h6"/><path d="M13 11l4 4M17 11l-4 4"/>',
    undo: '<path d="M7 4L3 8l4 4"/><path d="M3 8h9a4.5 4.5 0 0 1 0 9H9"/>', redo: '<path d="M13 4l4 4-4 4"/><path d="M17 8H8a4.5 4.5 0 0 0 0 9h3"/>',
    find: '<circle cx="8.5" cy="8.5" r="5"/><path d="M12.5 12.5l4.5 4.5"/>',
    print: '<path d="M6 7V3h8v4M6 14H4V8h12v6h-2"/><rect x="6" y="11" width="8" height="6"/>',
    open: '<path d="M2.5 15.5V5h5l1.5 2h7.5v8.5z"/>',
  };
  const ico = (name) => h("span", { class: "ico-svg", "aria-hidden": "true", html: `<svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>` });

  /** Dropdown: a toolbar button that opens a small menu. items: [label, fn, {hint, danger, disabled}] | "-" */
  function dropdown(label, title, items, { right = false, keep = true } = {}) {
    const wrap = h("span", { class: "of-pop" });
    const btn = tb(label, title, () => (menu.hidden ? open() : close()), { keep });
    btn.setAttribute("aria-haspopup", "menu");
    btn.setAttribute("aria-expanded", "false");
    const menu = h("div", { class: "of-menu win" + (right ? " right" : ""), role: "menu", hidden: true });
    const build = () => menu.replaceChildren(...(typeof items === "function" ? items() : items).map((it) => it === "-" ? h("hr") :
      it.nodeType ? it : h("button", { type: "button", role: "menuitem", class: it[2]?.danger ? "danger" : "", disabled: it[2]?.disabled,
        onmousedown: keep ? (e) => e.preventDefault() : null, onclick: () => { close(); it[1](); } }, it[0], it[2]?.hint ? h("small", {}, it[2].hint) : null)));
    const outside = (e) => { if (!wrap.contains(e.target)) close(); };
    const key = (e) => {
      if (e.key === "Escape") { close(); btn.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const bs = $$("button:not(:disabled)", menu); const i = bs.indexOf(document.activeElement);
        bs[(i + (e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length]?.focus(); e.preventDefault();
      }
    };
    function open() { build(); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); setTimeout(() => addEventListener("pointerdown", outside), 0); menu.addEventListener("keydown", key); }
    function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); removeEventListener("pointerdown", outside); }
    wrap.append(btn, menu);
    wrap.close = close; wrap.menu = menu; wrap.btn = btn;
    return wrap;
  }

  function colorBtn(label, title, value, onpick, cls = "") {
    const input = h("input", { type: "color", value, "aria-label": title, title });
    const b = h("b", { class: cls, style: `--c:${value}` }, label);
    input.addEventListener("change", () => { b.style.setProperty("--c", input.value); onpick(input.value); });
    const lab = h("label", { class: "of-color", title, onmousedown: (e) => { if (e.target !== input) e.preventDefault(); } }, b, input);
    lab.apply = () => onpick(input.value);
    b.onclick = (e) => { e.preventDefault(); onpick(input.value); };
    return lab;
  }

  function savedToast(path, verb = "Saved") {
    const t = toast(`${verb}: ${path.split(/[\\/]/).pop()}`, false, 7000);
    t.querySelector(".toast-body span")?.append(" ",
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); api("/api/open", { path, reveal: false }).catch(fail); } }, "Open"), " · ",
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); api("/api/open", { path }).catch(fail); } }, "Show in folder"));
  }

  /** A prompt built on App.ask (msg can be a node). Resolves the text, or null. */
  async function prompt(label, value = "", { title = "edit", yes = "OK", placeholder = "" } = {}) {
    const input = h("input", { type: "text", value, placeholder, "aria-label": label, style: "width:100%;margin-top:8px;padding:6px 8px;border:2px solid var(--ink-soft);border-radius:8px;background:var(--win-2)" });
    const p = ask(h("div", {}, h("div", {}, label), input), { title, yes, no: "Cancel" });
    setTimeout(() => { input.focus(); input.select(); }, 30);
    return (await p) ? input.value : null;
  }

  function addRecent(f) {
    const list = store.get("office.recent", []).filter((x) => x.path.toLowerCase() !== f.path.toLowerCase());
    list.unshift({ path: f.path, name: f.name, ext: f.ext, size_h: f.size_h || "" });
    store.set("office.recent", list.slice(0, 10));
  }

  // ------------------------------------------------------------------ mount / open / close
  function mount(el) {
    O.root = el;
    if (O.view) { if (!el.contains(O.view.el)) el.replaceChildren(O.view.el); O.view.onShow?.(); return; }
    if (!O.opening) renderEmpty();
  }

  function renderEmpty() {
    const recent = store.get("office.recent", []);
    const openBtn = h("button", { class: "btn big", onclick: pickAndOpen }, "📂 Open a document");
    O.root.replaceChildren(h("div", { class: "of-empty" }, h("div", { class: "win" }, titlebar("docs_and_sheets.exe — no file open"),
      h("div", { class: "of-empty-body" },
        mascotImg("float"),
        h("h2", {}, "open a doc or a sheet ✎"),
        h("p", { class: "muted" }, "View and edit Word documents and spreadsheets right here: DOCX, DOC, RTF, ODT, TXT, Markdown, HTML, XLSX, XLS, ODS, CSV and TSV. PowerPoint and PDF files open read-only. Your original is never changed unless you choose “Save over original”."),
        h("div", { class: "row" }, openBtn, h("button", { class: "btn ghost", onclick: newBlank }, "✚ New blank document")),
        h("p", { class: "muted sm" }, "or drop a file anywhere on this page"),
        recent.length ? h("div", { class: "of-recent" }, h("h4", {}, "recent files"),
          ...recent.map((f) => h("button", { type: "button", onclick: () => openFile(f), title: f.path },
            h("span", { class: "ext " + KIND(f.ext) }, f.ext), h("span", { class: "nm" }, f.name), h("span", { class: "pth" }, f.path)))) : null))));
    setTimeout(() => openBtn.focus({ preventScroll: true }), 0);
  }

  async function pickAndOpen() {
    try { const fs = await pickFiles(); if (fs?.length) openFile(fs[0]); } catch (e) { fail(e); }
  }

  async function newBlank() {
    if (isDirty() && !(await confirmDiscard())) return;
    try {
      // a blank document is just an empty .docx in the output folder's temp space: we open it from the server's temp dir
      const d = await api("/api/office/new", { kind: "doc" });
      openFile(d.file, true);
    } catch (e) { fail(e); }
  }

  const confirmDiscard = () => ask(`“${O.file?.name}” has unsaved changes. Discard them?`, { title: "unsaved changes", danger: true, yes: "Discard", no: "Keep editing" });

  async function openFile(f, skipDirtyCheck = false) {
    if (!f) return;
    if (!O.root) O.root = $("#view-office");
    if (!skipDirtyCheck && isDirty() && !(await confirmDiscard())) return;
    await closeView();
    O.opening = true;
    O.root.replaceChildren(h("div", { class: "of-loading" }, mascotImg("float"), h("div", {}, h("span", { class: "spinner" }), " opening ", f.name, "…"),
      ["ppt", "pptx", "doc", "rtf", "odt"].includes(f.ext) ? h("div", { class: "sm" }, "Office files go through Microsoft Office first, this can take a few seconds.") : null));
    try {
      const d = await api("/api/office/open", { path: f.path });
      O.caps = d.caps || {};
      O.file = { ...f, path: d.path, name: d.name, ext: d.ext };
      if (!f.temp) addRecent(O.file);
      O.view = d.kind === "doc" ? DocView(d) : d.kind === "sheet" ? SheetView(d) : d.kind === "slides" ? SlidesView(d) : PdfView(d);
      O.root.replaceChildren(O.view.el);
      O.view.onShow?.();
    } catch (e) {
      fail(e);
      O.view = null; O.file = null;
      renderEmpty();
    } finally { O.opening = false; }
  }

  async function closeView() {
    const v = O.view;
    O.view = null;
    if (v) { try { await v.destroy?.(); } catch {} }
  }

  async function closeFile() {
    if (isDirty() && !(await confirmDiscard())) return;
    await closeView();
    O.file = null;
    renderEmpty();
  }

  addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
  addEventListener("keydown", (e) => {
    if (S.view !== "office" || !O.view || !$("#modal").hidden) return;
    O.view.onKey?.(e);
  });

  /** Shared window chrome: titlebar with dirty mark and close button, toolbars, body and status line. */
  function chrome(V, toolRows, main, status) {
    const title = titlebar("");
    const tspan = title.firstChild;
    title.append(h("button", { class: "tb-x", title: "Close file", "aria-label": "Close file", onclick: closeFile }, "✕"));
    V.setTitle = () => {
      tspan.replaceChildren(V.dirty() ? h("span", { class: "of-dirty", title: "Unsaved changes" }, "●") : "", `${O.file.name}${V.dirty() ? " (unsaved)" : ""} — docs_and_sheets.exe`);
    };
    V.el = h("div", { class: "of of-" + V.kind }, h("div", { class: "of-bar win" }, title, ...toolRows), main, status);
    V.setTitle();
    return V.el;
  }

  async function doPrint(prepare) {
    document.body.classList.add("of-printing");
    let pageStyle = null;
    try { pageStyle = await prepare?.(); } catch (e) { fail(e); }
    const done = () => { document.body.classList.remove("of-printing"); pageStyle?.remove(); removeEventListener("afterprint", done); };
    addEventListener("afterprint", done);
    setTimeout(() => window.print(), 50);
  }

  // =================================================================== DOCUMENT EDITOR
  const STYLES = [["p", "", "Normal"], ["h1", "title", "Title"], ["h1", "", "Heading 1"], ["h2", "", "Heading 2"], ["h3", "", "Heading 3"], ["blockquote", "", "Quote"], ["pre", "", "Code"]];
  const FONTS = ["Calibri", "Cambria", "Arial", "Times New Roman", "Georgia", "Verdana", "Segoe UI", "Tahoma", "Trebuchet MS", "Garamond", "Courier New", "Consolas", "Comic Sans MS"];
  const SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72];
  const BLOCK_SEL = "p,h1,h2,h3,h4,h5,h6,blockquote,pre,li,div:not(.page-break),td,th";
  const ALLOWED = new Set(["P", "BR", "B", "STRONG", "I", "EM", "U", "S", "STRIKE", "DEL", "SUB", "SUP", "A", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI",
    "TABLE", "THEAD", "TBODY", "TFOOT", "TR", "TD", "TH", "BLOCKQUOTE", "PRE", "CODE", "SPAN", "IMG", "HR", "DIV", "FONT", "MARK"]);
  const DROP = new Set(["SCRIPT", "STYLE", "META", "LINK", "TITLE", "HEAD", "IFRAME", "OBJECT", "EMBED", "SVG", "MATH", "NOSCRIPT", "TEMPLATE", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "FORM"]);
  const STYLE_OK = ["font-weight", "font-style", "text-decoration", "text-decoration-line", "color", "background-color", "font-size", "font-family", "text-align", "margin-left", "vertical-align", "width", "height"];

  function cleanHTML(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const walk = (node) => {
      for (const ch of [...node.childNodes]) {
        if (ch.nodeType === 8) { ch.remove(); continue; }
        if (ch.nodeType !== 1) continue;
        const tag = ch.tagName.toUpperCase();
        if (DROP.has(tag) || tag.includes(":") && !/^O:P$/.test(tag)) { ch.remove(); continue; }
        walk(ch);
        if (!ALLOWED.has(tag)) { ch.replaceWith(...ch.childNodes); continue; }
        const keep = {};
        if (tag === "A" && ch.getAttribute("href") && !/^\s*(javascript|vbscript|data):/i.test(ch.getAttribute("href"))) keep.href = ch.getAttribute("href");
        if (tag === "IMG" && /^(data:image\/|https?:)/i.test(ch.getAttribute("src") || "")) keep.src = ch.getAttribute("src");
        if (/^T[DH]$/.test(tag)) for (const a of ["colspan", "rowspan"]) if (ch.getAttribute(a)) keep[a] = ch.getAttribute(a);
        if (tag === "FONT") for (const a of ["face", "size", "color"]) if (ch.getAttribute(a)) keep[a] = ch.getAttribute(a);
        const cls = (ch.getAttribute("class") || "").split(/\s+/).filter((c) => ["page-break", "title", "subtitle", "tab"].includes(c)).join(" ");
        if (cls) keep.class = cls;
        const st = STYLE_OK.map((p) => [p, ch.style.getPropertyValue(p)]).filter(([, v]) => v && !/mso-|var\(/.test(v)).map(([p, v]) => `${p}:${v}`).join(";");
        for (const a of [...ch.attributes]) ch.removeAttribute(a.name);
        for (const [k, v] of Object.entries(keep)) ch.setAttribute(k, v);
        if (st) ch.setAttribute("style", st);
        if (tag === "IMG" && !keep.src) ch.remove();
      }
    };
    walk(doc.body);
    return doc.body.innerHTML;
  }

  function DocView(d) {
    const V = { kind: "doc", alive: true };
    let dirty = false;
    V.dirty = () => dirty;
    const pt2px = (v) => v * 96 / 72;
    const pg = d.page || { w: 612, h: 792, mt: 72, mb: 72, ml: 72, mr: 72 };
    const font = d.font || { family: "Calibri", size: 11 };
    const page = h("div", { class: "of-page", contenteditable: "true", spellcheck: "true", role: "textbox", "aria-multiline": "true", "aria-label": "Document: " + O.file.name,
      style: `width:${pt2px(pg.w)}px;min-height:${pt2px(pg.h)}px;padding:${pt2px(pg.mt)}px ${pt2px(pg.mr)}px ${pt2px(pg.mb)}px ${pt2px(pg.ml)}px;font-family:'${font.family}',Calibri,Arial,sans-serif;font-size:${font.size}pt` });
    page.innerHTML = d.html;
    const paper = h("div", { class: "of-paper" }, page);
    const stage = h("div", { class: "of-stage" }, paper);
    let zoom = store.get("office.zoom", 1);

    // ---------- selection memory (toolbar clicks / dropdowns don't lose the caret)
    let savedRange = null;
    const onSel = () => {
      if (!V.alive) return;
      const s = getSelection();
      if (s.rangeCount && page.contains(s.anchorNode)) { savedRange = s.getRangeAt(0).cloneRange(); queueState(); }
    };
    document.addEventListener("selectionchange", onSel);
    function restoreSel() {
      const s = getSelection();
      if (s.rangeCount && page.contains(s.anchorNode)) {  // the live selection is already in the page: keep it
        savedRange = s.getRangeAt(0).cloneRange();
        if (document.activeElement !== page) { const r = savedRange; page.focus({ preventScroll: true }); s.removeAllRanges(); s.addRange(r); }
        return;
      }
      page.focus({ preventScroll: true });
      if (savedRange && page.contains(savedRange.startContainer)) { s.removeAllRanges(); s.addRange(savedRange); }
    }
    // text offsets (survive innerHTML swaps for undo/redo and block rewrites)
    function offsetOf(node, off) { const r = document.createRange(); r.setStart(page, 0); try { r.setEnd(node, off); } catch { return 0; } return r.toString().length; }
    function getOffsets() {
      const s = getSelection();
      if (!s.rangeCount || !page.contains(s.anchorNode)) return savedRange ? [offsetOf(savedRange.startContainer, savedRange.startOffset), offsetOf(savedRange.endContainer, savedRange.endOffset)] : [0, 0];
      const r = s.getRangeAt(0);
      return [offsetOf(r.startContainer, r.startOffset), offsetOf(r.endContainer, r.endOffset)];
    }
    function pointAt(n) {
      const w = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
      let t, acc = 0, last = null;
      while ((t = w.nextNode())) { if (acc + t.length >= n) return [t, n - acc]; acc += t.length; last = t; }
      return last ? [last, last.length] : [page, 0];
    }
    function setOffsets([a, b]) {
      const r = document.createRange();
      try { r.setStart(...pointAt(a)); r.setEnd(...pointAt(b)); } catch { return; }
      const s = getSelection(); s.removeAllRanges(); s.addRange(r); savedRange = r.cloneRange();
    }

    // ---------- undo / redo (HTML snapshots; covers execCommand and our own DOM edits alike)
    const undo = [], redo = [];
    let burst = false, burstTimer = null;
    const snap = () => ({ html: page.innerHTML, sel: getOffsets() });
    function checkpoint() { undo.push(snap()); if (undo.length > 80) undo.shift(); redo.length = 0; burst = false; syncUndo(); }
    function restore(s) { page.innerHTML = s.html; page.focus({ preventScroll: true }); setOffsets(s.sel); changed(); }
    function doUndo() { if (!undo.length) return; redo.push(snap()); restore(undo.pop()); syncUndo(); }
    function doRedo() { if (!redo.length) return; undo.push(snap()); restore(redo.pop()); syncUndo(); }
    page.addEventListener("beforeinput", (e) => {
      if (e.inputType === "historyUndo") { e.preventDefault(); doUndo(); return; }
      if (e.inputType === "historyRedo") { e.preventDefault(); doRedo(); return; }
      if (!burst || e.inputType === "insertParagraph" || e.inputType.startsWith("delete") && e.inputType !== "deleteContentBackward" && e.inputType !== "deleteContentForward") checkpoint();
      burst = true;
      clearTimeout(burstTimer); burstTimer = setTimeout(() => (burst = false), 900);
    });
    page.addEventListener("input", () => changed());
    let countTimer = null;
    function changed() {
      if (!dirty) { dirty = true; V.setTitle(); }
      clearTimeout(countTimer); countTimer = setTimeout(updateCount, 250);
      if (find.open) find.refresh(false);
    }

    // ---------- commands
    function exec(name, val = null, css = false) {
      restoreSel(); checkpoint();
      document.execCommand("styleWithCSS", false, css);
      document.execCommand(name, false, val);
      changed(); queueState();
    }
    function textNodesIn(r) {
      const root = r.commonAncestorContainer.nodeType === 3 ? r.commonAncestorContainer.parentNode : r.commonAncestorContainer;
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const out = []; let t;
      while ((t = w.nextNode())) if (t.length && r.intersectsNode(t) && page.contains(t)) out.push(t);
      return out;
    }
    /** Apply one inline CSS property to the selection (font, size, colours). */
    function inlineStyle(prop, value) {
      restoreSel();
      const s = getSelection();
      if (!s.rangeCount) return;
      checkpoint();
      let r = s.getRangeAt(0);
      if (r.collapsed) {  // typing style at the caret: a styled span with a zero-width space to type into
        const sp = h("span", { style: `${prop}:${value}` }, "​");
        r.insertNode(sp);
        const nr = document.createRange(); nr.setStart(sp.firstChild, 1); nr.collapse(true);
        s.removeAllRanges(); s.addRange(nr); savedRange = nr.cloneRange();
        changed(); return;
      }
      let { startContainer: sc, startOffset: so, endContainer: ec, endOffset: eo } = r;
      if (ec.nodeType === 3 && eo < ec.length) ec.splitText(eo);
      if (sc.nodeType === 3 && so > 0) { const nsc = sc.splitText(so); if (ec === sc) ec = nsc; sc = nsc; so = 0; }
      r = document.createRange();
      if (sc.nodeType === 3) r.setStart(sc, 0); else r.setStart(sc, so);
      if (ec.nodeType === 3) r.setEnd(ec, ec.length); else r.setEnd(ec, eo);
      const texts = textNodesIn(r).filter((t) => !t.parentElement.closest(".page-break"));
      for (const t of texts) {
        const p = t.parentElement;
        if (p.tagName === "SPAN" && p.childNodes.length === 1 && p !== page) p.style.setProperty(prop, value);
        else { const sp = document.createElement("span"); sp.style.setProperty(prop, value); t.replaceWith(sp); sp.append(t); }
      }
      if (texts.length) { const nr = document.createRange(); nr.setStart(texts[0], 0); const last = texts[texts.length - 1]; nr.setEnd(last, last.length); s.removeAllRanges(); s.addRange(nr); savedRange = nr.cloneRange(); }
      changed(); queueState();
    }
    function caretBlock() {
      const s = getSelection();
      const n = s.rangeCount && page.contains(s.anchorNode) ? s.anchorNode : savedRange?.startContainer;
      const el = n?.nodeType === 3 ? n.parentElement : n;
      return el?.closest?.(BLOCK_SEL) && page.contains(el.closest(BLOCK_SEL)) ? el.closest(BLOCK_SEL) : null;
    }
    function selectedBlocks() {
      const s = getSelection();
      const r = s.rangeCount && page.contains(s.anchorNode) ? s.getRangeAt(0) : savedRange;
      if (!r) return [];
      const leaf = $$(BLOCK_SEL, page).filter((b) => r.intersectsNode(b) && !b.querySelector("p,h1,h2,h3,h4,h5,h6,blockquote,pre,li,div:not(.page-break),table"));
      if (leaf.length) return leaf;
      const b = caretBlock(); return b ? [b] : [];
    }
    function setBlock(tag, cls) {
      restoreSel(); checkpoint();
      const offs = getOffsets();
      let blocks = selectedBlocks().filter((b) => !/^(LI|TD|TH)$/.test(b.tagName));
      const inCell = selectedBlocks().filter((b) => /^(TD|TH)$/.test(b.tagName));
      if (!blocks.length || inCell.length) {  // bare text (top level or in a table cell): wrap it in a block first
        document.execCommand("formatBlock", false, "p");
        blocks = selectedBlocks().filter((b) => !/^(LI|TD|TH)$/.test(b.tagName));
      }
      for (const b of blocks) {
        const n = document.createElement(tag);
        if (cls) n.className = cls;
        if (b.getAttribute("style")) n.setAttribute("style", b.getAttribute("style"));
        if (tag === "pre") b.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
        n.append(...b.childNodes);
        if (!n.firstChild) n.append(h("br"));
        b.replaceWith(n);
      }
      setOffsets(offs); changed(); queueState();
    }
    function align(a) {
      restoreSel(); checkpoint();
      for (const b of selectedBlocks()) b.style.textAlign = a === "left" ? "" : a;
      changed(); queueState();
    }
    function indent(dir) {
      const b = caretBlock();
      if (b?.closest("li")) { exec(dir > 0 ? "indent" : "outdent"); return; }
      restoreSel(); checkpoint();
      for (const blk of selectedBlocks()) {
        const cur = parseFloat(blk.style.marginLeft) || 0; // pt
        const next = Math.max(0, Math.min(360, cur + dir * 36));
        blk.style.marginLeft = next ? next + "pt" : "";
      }
      changed();
    }
    function topBlock(node) {
      let el = node?.nodeType === 3 ? node.parentElement : node;
      while (el && el.parentElement && el.parentElement !== page && !/^(TD|TH)$/.test(el.parentElement.tagName)) el = el.parentElement;
      return el && page.contains(el) && el !== page ? el : null;
    }
    function insertBlock(el, caretInto = null) {
      restoreSel(); checkpoint();
      const s = getSelection();
      const blk = topBlock(s.anchorNode);
      if (blk) blk.after(el); else page.append(el);
      if (!el.nextElementSibling) el.after(h("p", {}, h("br")));
      const target = caretInto || el.nextElementSibling;
      const r = document.createRange(); r.selectNodeContents(target); r.collapse(true);
      s.removeAllRanges(); s.addRange(r); savedRange = r.cloneRange();
      changed();
    }
    function insertInline(node) {
      restoreSel(); checkpoint();
      const s = getSelection();
      if (!s.rangeCount) { page.append(node); changed(); return; }
      const r = s.getRangeAt(0);
      r.deleteContents(); r.insertNode(node);
      const nr = document.createRange(); nr.setStartAfter(node); nr.collapse(true);
      s.removeAllRanges(); s.addRange(nr); savedRange = nr.cloneRange();
      changed();
    }

    // tables
    function insertTable(rows, cols) {
      const t = h("table", {}, h("tbody", {}, ...Array.from({ length: rows }, () => h("tr", {}, ...Array.from({ length: cols }, () => h("td", {}, h("br")))))));
      insertBlock(t, t.querySelector("td"));
    }
    function curCell() {
      const n = (getSelection().rangeCount && page.contains(getSelection().anchorNode)) ? getSelection().anchorNode : savedRange?.startContainer;
      const el = n?.nodeType === 3 ? n.parentElement : n;
      const c = el?.closest?.("td,th");
      return c && page.contains(c) ? c : null;
    }
    function tableOp(kind) {
      const cell = curCell();
      if (!cell) return toast("Put the cursor inside a table first");
      restoreSel(); checkpoint();
      const tr = cell.parentElement, table = cell.closest("table"), idx = cell.cellIndex;
      const blankRow = () => { const n = document.createElement("tr"); for (const c of tr.cells) { const td = h("td", { colspan: c.colSpan > 1 ? c.colSpan : null }, h("br")); n.append(td); } return n; };
      if (kind === "rowAbove") tr.before(blankRow());
      else if (kind === "rowBelow") tr.after(blankRow());
      else if (kind === "colLeft" || kind === "colRight") {
        for (const row of table.rows) { const ref = row.cells[Math.min(idx, row.cells.length - 1)]; const td = h(ref?.tagName === "TH" ? "th" : "td", {}, h("br")); if (!ref) row.append(td); else kind === "colLeft" ? ref.before(td) : ref.after(td); }
      } else if (kind === "delRow") { tr.remove(); if (!table.rows.length) table.remove(); }
      else if (kind === "delCol") { for (const row of [...table.rows]) row.cells[idx]?.remove(); if (![...table.rows].some((r) => r.cells.length)) table.remove(); }
      else if (kind === "delTable") table.remove();
      changed();
    }
    // images
    const fileIn = h("input", { type: "file", accept: "image/*", hidden: true });
    fileIn.onchange = () => {
      const f = fileIn.files[0]; fileIn.value = "";
      if (f) readImage(f).then((img) => insertInline(img)).catch(fail);
    };
    function readImage(f) {
      return new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => {
          const img = new Image();
          img.onload = () => {
            const maxW = pt2px(pg.w - pg.ml - pg.mr);
            const w = Math.min(img.naturalWidth, maxW);
            res(h("img", { src: fr.result, alt: f.name || "", style: `width:${Math.round(w)}px;height:${Math.round(w * img.naturalHeight / img.naturalWidth)}px` }));
          };
          img.onerror = () => rej(new Error("That file isn't an image the browser can read"));
          img.src = fr.result;
        };
        fr.onerror = () => rej(fr.error);
        fr.readAsDataURL(f);
      });
    }
    let selImg = null;
    const imgBar = h("div", { class: "of-imgbar win", hidden: true },
      tb("−", "Make picture smaller", () => sizeImg(0.8)), tb("+", "Make picture bigger", () => sizeImg(1.25)),
      tb("↔", "Fit picture to page width", () => sizeImg(0)), tb("🗑", "Remove picture", () => { checkpoint(); selImg.remove(); pickImg(null); changed(); }));
    function pickImg(img) {
      page.querySelectorAll("img.of-img-sel").forEach((i) => i.classList.remove("of-img-sel"));
      selImg = img;
      imgBar.hidden = !img;
      if (!img) return;
      img.classList.add("of-img-sel");
      const sr = stage.getBoundingClientRect(), ir = img.getBoundingClientRect();
      imgBar.style.left = (ir.left - sr.left + stage.scrollLeft) + "px";
      imgBar.style.top = Math.max(0, ir.top - sr.top + stage.scrollTop - 40) + "px";
    }
    function sizeImg(f) {
      if (!selImg) return;
      checkpoint();
      const maxW = pt2px(pg.w - pg.ml - pg.mr);
      const ratio = (selImg.naturalHeight || selImg.height) / (selImg.naturalWidth || selImg.width || 1);
      const w = Math.max(16, Math.min(maxW, f ? selImg.getBoundingClientRect().width / zoom * f : maxW));
      selImg.style.width = Math.round(w) + "px"; selImg.style.height = Math.round(w * ratio) + "px";
      changed(); pickImg(selImg);
    }
    page.addEventListener("click", (e) => pickImg(e.target.tagName === "IMG" ? e.target : null));
    stage.addEventListener("scroll", () => { if (selImg) pickImg(selImg); });

    async function linkDialog() {
      restoreSel();
      const s = getSelection();
      const r = s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
      const node = r?.startContainer; const a = (node?.nodeType === 3 ? node.parentElement : node)?.closest?.("a");
      let url = await prompt("Link address (leave empty to remove the link):", a?.getAttribute("href") || "https://", { title: "insert link", yes: "Apply" });
      if (url === null) return;
      url = url.trim();
      page.focus({ preventScroll: true });
      if (r) { s.removeAllRanges(); s.addRange(r); savedRange = r; }
      if (!url || url === "https://") { if (a) { checkpoint(); a.replaceWith(...a.childNodes); changed(); } return; }
      if (!/^([a-z][a-z0-9+.-]*:|#|\/)/i.test(url)) url = (/^[^@\s]+@[^@\s]+\.\w+$/.test(url) ? "mailto:" : "https://") + url;
      if (a) { checkpoint(); a.setAttribute("href", url); changed(); return; }
      if (!r || r.collapsed) insertInline(h("a", { href: url }, url));
      else exec("createLink", url);
    }

    // ---------- find & replace
    const find = (() => {
      const q = h("input", { type: "text", placeholder: "Find", "aria-label": "Find" });
      const rep = h("input", { type: "text", placeholder: "Replace with", "aria-label": "Replace with" });
      const mc = h("input", { type: "checkbox", "aria-label": "Match case" });
      const count = h("span", { class: "of-find-count", "aria-live": "polite" });
      let matches = [], cur = -1;
      const hl = typeof Highlight !== "undefined" && CSS.highlights;
      const panel = h("div", { class: "of-find win", hidden: true, role: "dialog", "aria-label": "Find and replace" },
        (() => { const t = titlebar("find_and_replace"); t.append(h("button", { class: "tb-x", title: "Close (Esc)", "aria-label": "Close find", onclick: () => F.close() }, "✕")); return t; })(),
        h("div", { class: "of-find-body" }, q,
          h("div", { class: "row" }, h("button", { class: "btn ghost sm", onclick: () => go(-1), title: "Previous (Shift+Enter)" }, "↑ Prev"),
            h("button", { class: "btn ghost sm", onclick: () => go(1), title: "Next (Enter)" }, "↓ Next"),
            h("label", { class: "sm" }, mc, " Match case"), h("span", { class: "spacer" }), count),
          rep,
          h("div", { class: "row" }, h("button", { class: "btn sm", onclick: () => replaceOne() }, "Replace"), h("button", { class: "btn ghost sm", onclick: () => replaceAll() }, "Replace all"))));
      function compute() {
        matches = [];
        const needle = q.value;
        if (!needle) return;
        const w = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
        const nodes = []; let full = "", t;
        while ((t = w.nextNode())) { nodes.push([t, full.length]); full += t.data; }
        const hay = mc.checked ? full : full.toLowerCase(), nd = mc.checked ? needle : needle.toLowerCase();
        const locate = (i) => { let lo = 0, hi = nodes.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (nodes[m][1] <= i) lo = m; else hi = m - 1; } return lo; };
        let i = hay.indexOf(nd);
        while (i >= 0 && matches.length < 5000) {
          const a = locate(i), b = locate(i + nd.length - 1);
          const r = document.createRange();
          r.setStart(nodes[a][0], i - nodes[a][1]); r.setEnd(nodes[b][0], i + nd.length - nodes[b][1]);
          matches.push(r);
          i = hay.indexOf(nd, i + nd.length);
        }
      }
      function paint() {
        if (hl) {
          CSS.highlights.set("of-find", new Highlight(...matches));
          if (matches[cur]) CSS.highlights.set("of-find-cur", new Highlight(matches[cur])); else CSS.highlights.delete("of-find-cur");
        }
        count.textContent = q.value ? (matches.length ? `${cur + 1} of ${matches.length}` : "no matches") : "";
      }
      function show(i) {
        if (!matches.length) { cur = -1; paint(); return; }
        cur = (i + matches.length) % matches.length;
        paint();
        const rect = matches[cur].getBoundingClientRect(), sr = stage.getBoundingClientRect();
        if (rect.top < sr.top + 40 || rect.bottom > sr.bottom - 20) stage.scrollTop += rect.top - sr.top - sr.height / 3;
        if (!hl) { const s = getSelection(); s.removeAllRanges(); s.addRange(matches[cur]); }
      }
      function go(dir) { compute(); if (cur < 0) cur = dir > 0 ? -1 : 0; show(cur + dir); }
      function replaceOne() {
        compute();
        if (!matches.length) return;
        if (cur < 0 || cur >= matches.length) cur = 0;
        checkpoint();
        const r = matches[cur]; r.deleteContents(); r.insertNode(document.createTextNode(rep.value));
        page.normalize(); changed(); compute(); show(cur);
      }
      function replaceAll() {
        compute();
        if (!matches.length) return toast("Nothing to replace");
        checkpoint();
        const n = matches.length;
        for (const r of [...matches].reverse()) { r.deleteContents(); r.insertNode(document.createTextNode(rep.value)); }
        page.normalize(); changed(); compute(); cur = -1; paint();
        toast(`Replaced ${n} match${n > 1 ? "es" : ""}`);
      }
      q.addEventListener("input", () => { compute(); show(0); });
      mc.addEventListener("change", () => { compute(); show(0); });
      panel.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.preventDefault(); F.close(); }
        if (e.key === "Enter" && e.target === q) { e.preventDefault(); go(e.shiftKey ? -1 : 1); }
        if (e.key === "Enter" && e.target === rep) { e.preventDefault(); replaceOne(); }
      });
      const F = {
        panel, open: false,
        show(replace) {
          F.open = true; panel.hidden = false;
          const s = getSelection().toString();
          if (s && s.length < 80 && !s.includes("\n")) q.value = s;
          (replace ? rep : q).focus(); q.select();
          compute(); show(0);
        },
        close() { F.open = false; panel.hidden = true; matches = []; if (hl) { CSS.highlights.delete("of-find"); CSS.highlights.delete("of-find-cur"); } restoreSel(); },
        refresh() { compute(); if (cur >= matches.length) cur = matches.length - 1; paint(); },
      };
      return F;
    })();

    // ---------- toolbar
    const styleSel = h("select", { title: "Paragraph style", "aria-label": "Paragraph style" }, ...STYLES.map(([t, c, l], i) => h("option", { value: i }, l)));
    styleSel.onchange = () => { const [t, c] = STYLES[+styleSel.value]; setBlock(t, c); };
    const fontSel = h("select", { title: "Font", "aria-label": "Font", style: "width:128px" }, h("option", { value: "" }, "Font"), ...FONTS.map((f) => h("option", { value: f, style: `font-family:'${f}'` }, f)));
    fontSel.onchange = () => { if (fontSel.value) inlineStyle("font-family", `'${fontSel.value}'`); };
    const sizeSel = h("select", { title: "Font size (pt)", "aria-label": "Font size", style: "width:64px" }, h("option", { value: "" }, "Size"), ...SIZES.map((s) => h("option", { value: s }, s)));
    sizeSel.onchange = () => { if (sizeSel.value) inlineStyle("font-size", sizeSel.value + "pt"); };
    const btnB = tb(h("span", { class: "of-b" }, "B"), "Bold (Ctrl+B)", () => exec("bold"));
    const btnI = tb(h("span", { class: "of-i" }, "I"), "Italic (Ctrl+I)", () => exec("italic"));
    const btnU = tb(h("span", { class: "of-u" }, "U"), "Underline (Ctrl+U)", () => exec("underline"));
    const btnS = tb(h("span", { class: "of-s" }, "S"), "Strikethrough", () => exec("strikeThrough"));
    const alignBtns = [["left", "Align left (Ctrl+L)"], ["center", "Centre (Ctrl+E)"], ["right", "Align right (Ctrl+R)"], ["justify", "Justify (Ctrl+J)"]]
      .map(([a, t]) => { const b = tb(ico(a), t, () => align(a)); b.dataset.align = a; return b; });
    const btnUL = tb(ico("ul"), "Bulleted list", () => exec("insertUnorderedList"));
    const btnOL = tb(ico("ol"), "Numbered list", () => exec("insertOrderedList"));
    const undoBtn = tb(ico("undo"), "Undo (Ctrl+Z)", doUndo), redoBtn = tb(ico("redo"), "Redo (Ctrl+Y)", doRedo);
    function syncUndo() { undoBtn.disabled = !undo.length; redoBtn.disabled = !redo.length; }

    const tablePick = (() => {
      const label = h("div", { class: "of-tpick-label" }, "Insert table");
      const grid = h("div", { class: "of-tpick", role: "grid", "aria-label": "Choose table size" });
      const cells = [];
      for (let r = 0; r < 8; r++) for (let c = 0; c < 10; c++) {
        const i = h("i", { "data-r": r, "data-c": c });
        cells.push(i); grid.append(i);
      }
      grid.addEventListener("mouseover", (e) => {
        if (e.target.tagName !== "I") return;
        const R = +e.target.dataset.r, C = +e.target.dataset.c;
        cells.forEach((x) => x.classList.toggle("on", +x.dataset.r <= R && +x.dataset.c <= C));
        label.textContent = `${R + 1} × ${C + 1} table`;
      });
      const dd = dropdown(ico("table"), "Insert table", () => [label, grid]);
      grid.addEventListener("click", (e) => { if (e.target.tagName !== "I") return; dd.close(); insertTable(+e.target.dataset.r + 1, +e.target.dataset.c + 1); });
      grid.addEventListener("mousedown", (e) => e.preventDefault());
      return dd;
    })();
    const tableMenu = dropdown("▾", "Table: add or delete rows & columns", [
      ["Insert table 3 × 3", () => insertTable(3, 3)], "-",
      ["Row above", () => tableOp("rowAbove")], ["Row below", () => tableOp("rowBelow")],
      ["Column left", () => tableOp("colLeft")], ["Column right", () => tableOp("colRight")], "-",
      ["Delete row", () => tableOp("delRow"), { danger: true }], ["Delete column", () => tableOp("delCol"), { danger: true }], ["Delete table", () => tableOp("delTable"), { danger: true }]]);
    const zoomSel = h("select", { title: "Zoom", "aria-label": "Zoom" }, ...[0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2].map((z) => h("option", { value: z, selected: z === zoom }, Math.round(z * 100) + "%")));
    zoomSel.onchange = () => setZoom(+zoomSel.value);
    function setZoom(z) { zoom = z; page.style.zoom = z; store.set("office.zoom", z); zoomSel.value = String(z); pickImg(selImg); }

    const ext = O.file.ext;
    const primary = ["docx", "html", "md", "txt"].includes(ext) ? ext : ext === "htm" ? "html" : ext === "markdown" ? "md" : "docx";
    const canOverwrite = !O.file.temp && ["docx", "html", "htm", "md", "markdown", "txt"].includes(ext) || (["doc", "rtf", "odt"].includes(ext) && O.caps.word);
    const fileRow = h("div", { class: "of-tools", role: "toolbar", "aria-label": "File and insert" },
      tb(ico("open"), "Open another file", pickAndOpen, { keep: false }),
      h("button", { class: "btn sm", title: `Save a copy as “${O.file.name.replace(/\.[^.]+$/, "")} (edited).${primary}” in the output folder (Ctrl+S)`, onclick: () => save(primary, "copy") }, "💾 Save"),
      dropdown("Save as ▾", "Save in another format", () => [
        ["Word document (.docx)", () => save("docx", "copy"), { hint: "DOCX" }],
        ["PDF", () => save("pdf", "copy"), { hint: O.caps.word ? "via Word" : "PDF" }],
        ["Web page (.html)", () => save("html", "copy"), { hint: "HTML" }],
        ["Markdown (.md)", () => save("md", "copy"), { hint: "MD" }],
        ["Plain text (.txt)", () => save("txt", "copy"), { hint: "TXT" }],
        ...(O.caps.word ? [["Rich text (.rtf)", () => save("rtf", "copy"), { hint: "RTF" }], ["OpenDocument (.odt)", () => save("odt", "copy"), { hint: "ODT" }]] : []),
        "-",
        ["Save over original…", () => save(ext === "htm" ? "html" : ext === "markdown" ? "md" : ext, "overwrite"), { danger: true, disabled: !canOverwrite }],
      ]),
      tb("⇩ PDF", "Export to PDF", () => save("pdf", "copy")),
      tb(ico("print"), "Print", () => doPrint(() => { const st = h("style", {}, `@page { size: ${pg.w}pt ${pg.h}pt; margin: ${pg.mt}pt ${pg.mr}pt ${pg.mb}pt ${pg.ml}pt; }`); document.head.append(st); return st; })),
      sep(), undoBtn, redoBtn, sep(),
      tablePick, tableMenu,
      tb(ico("image"), "Insert picture from a file", () => { restoreSel(); fileIn.click(); }),
      tb(ico("link"), "Insert link (Ctrl+K)", linkDialog),
      tb(ico("hr"), "Horizontal line", () => exec("insertHorizontalRule")),
      tb(ico("pagebreak"), "Page break", () => insertBlock(h("div", { class: "page-break", contenteditable: "false" }))),
      sep(),
      tb(ico("find"), "Find & replace (Ctrl+F / Ctrl+H)", () => find.show(false)),
      h("span", { class: "of-hint" }, d.note || ""),
      zoomSel, fileIn);
    const fmtRow = h("div", { class: "of-tools", role: "toolbar", "aria-label": "Formatting" },
      styleSel, fontSel, sizeSel, sep(), btnB, btnI, btnU, btnS,
      colorBtn("A", "Text colour", "#c00000", (c) => inlineStyle("color", c)),
      colorBtn("ab", "Highlight colour", "#ffff00", (c) => inlineStyle("background-color", c), "hl"),
      sep(), ...alignBtns, sep(), btnUL, btnOL,
      tb(ico("outdent"), "Decrease indent (Shift+Tab in lists)", () => indent(-1)), tb(ico("indent"), "Increase indent (Tab in lists)", () => indent(1)), sep(),
      tb(ico("clear"), "Clear formatting", () => exec("removeFormat")));

    const countEl = h("span", {});
    const status = h("div", { class: "of-status", "aria-live": "off" }, countEl,
      h("span", {}, `Page ${Math.round(pg.w / 72 * 25.4)} × ${Math.round(pg.h / 72 * 25.4)} mm`),
      h("span", { class: "spacer" }), h("span", {}, "Saves go to: ", h("b", {}, S.outDir)));
    function updateCount() {
      const text = page.innerText.replace(/​/g, "");
      const words = (text.match(/[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*/gu) || []).length;
      countEl.replaceChildren(h("b", {}, words.toLocaleString()), " words · ", h("b", {}, text.replace(/\s/g, "").length.toLocaleString()), " characters");
    }

    // toolbar state follows the caret
    let stateQueued = false;
    function queueState() { if (!stateQueued) { stateQueued = true; requestAnimationFrame(updateState); } }
    function updateState() {
      stateQueued = false;
      if (!V.alive) return;
      const q = (c) => { try { return document.queryCommandState(c); } catch { return false; } };
      btnB.classList.toggle("on", q("bold")); btnI.classList.toggle("on", q("italic")); btnU.classList.toggle("on", q("underline")); btnS.classList.toggle("on", q("strikeThrough"));
      btnUL.classList.toggle("on", q("insertUnorderedList")); btnOL.classList.toggle("on", q("insertOrderedList"));
      const b = caretBlock();
      if (b) {
        const blk = b.closest("h1,h2,h3,blockquote,pre") || b;
        const idx = STYLES.findIndex(([t, c]) => t === blk.tagName.toLowerCase() && (c ? blk.classList.contains(c) : !blk.classList.contains("title")));
        styleSel.value = String(Math.max(0, idx));
        const al = getComputedStyle(b).textAlign;
        alignBtns.forEach((x) => x.classList.toggle("on", x.dataset.align === (al === "start" ? "left" : al)));
      }
      const n = getSelection().anchorNode; const el = n?.nodeType === 3 ? n.parentElement : n;
      if (el && page.contains(el)) {
        const cs = getComputedStyle(el);
        const fam = cs.fontFamily.split(",")[0].replace(/['"]/g, "").trim();
        fontSel.value = FONTS.includes(fam) ? fam : "";
        const pt = Math.round(parseFloat(cs.fontSize) * 0.75 * 2) / 2;
        if (![...sizeSel.options].some((o) => o.value === String(pt))) sizeSel.append(h("option", { value: pt }, pt));
        sizeSel.value = String(pt);
      }
    }

    // ---------- keyboard & paste
    V.onKey = (e) => {
      const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
      if (!ctrl) return;
      const inPage = page.contains(document.activeElement) || document.activeElement === page;
      if (k === "s") { e.preventDefault(); save(primary, "copy"); }
      else if (k === "f" || k === "h") { e.preventDefault(); find.show(k === "h"); }
      else if (!inPage) return;
      else if (k === "z" && !e.shiftKey) { e.preventDefault(); doUndo(); }
      else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); doRedo(); }
      else if (k === "b") { e.preventDefault(); exec("bold"); }
      else if (k === "i") { e.preventDefault(); exec("italic"); }
      else if (k === "u") { e.preventDefault(); exec("underline"); }
      else if (k === "k") { e.preventDefault(); linkDialog(); }
      else if (k === "e" || k === "l" || k === "r" || k === "j") { e.preventDefault(); align({ e: "center", l: "left", r: "right", j: "justify" }[k]); }
    };
    page.addEventListener("keydown", (e) => {
      if (e.key === "Tab" && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        const cell = curCell();
        if (cell) {  // move between table cells
          const cells = $$("td,th", cell.closest("table")); const i = cells.indexOf(cell) + (e.shiftKey ? -1 : 1);
          if (cells[i]) { const r = document.createRange(); r.selectNodeContents(cells[i]); getSelection().removeAllRanges(); getSelection().addRange(r); }
          else if (!e.shiftKey) { tableOp("rowBelow"); }
        } else if (caretBlock()?.closest("li")) exec(e.shiftKey ? "outdent" : "indent");
        else if (!e.shiftKey) insertInline(h("span", { class: "tab" }, "\t"));
      }
    });
    page.addEventListener("paste", (e) => {
      const dt = e.clipboardData;
      if (!dt) return;
      const img = [...dt.files].find((f) => f.type.startsWith("image/"));
      if (img) { e.preventDefault(); readImage(img).then(insertInline).catch(fail); return; }
      const html = dt.getData("text/html");
      if (html) { e.preventDefault(); checkpoint(); document.execCommand("insertHTML", false, cleanHTML(html)); changed(); }
    });
    page.addEventListener("drop", (e) => {
      const img = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
      if (img) {
        e.preventDefault(); e.stopPropagation();
        dispatchEvent(new Event("drop"));  // lets app.js clear its drag overlay (no files -> it ignores the drop)
        const r = document.caretRangeFromPoint?.(e.clientX, e.clientY);
        if (r && page.contains(r.startContainer)) { const s = getSelection(); s.removeAllRanges(); s.addRange(r); savedRange = r.cloneRange(); }
        readImage(img).then(insertInline).catch(fail);
      }
    });
    page.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.items || [])].some((i) => i.type.startsWith("image/"))) e.stopPropagation(); });

    // ---------- save
    let saving = false;
    async function save(fmt, mode) {
      if (saving) return;
      if (mode === "overwrite") {
        const warn = ["docx", "doc", "rtf", "odt"].includes(fmt)
          ? " Text, formatting, tables, lists and pictures are kept, but things this editor doesn't show (comments, tracked changes, footnotes, text boxes, fields) will be lost. Headers, footers and page setup are kept."
          : "";
        if (!(await ask(`Overwrite the original “${O.file.name}”? This can't be undone.${warn}`, { title: "save over original", danger: true, yes: "Overwrite", no: "Cancel" }))) return;
      }
      saving = true;
      const t = toast(fmt === "pdf" ? "Making the PDF…" : "Saving…", false, 60000);
      try {
        const html = page.innerHTML.replace(/​/g, "");
        const r = await api("/api/office/doc/save", { path: O.file.path, html, format: fmt, mode, out_dir: S.outDir, page: pg, font });
        if (fmt === primary || mode === "overwrite") { dirty = false; V.setTitle(); }
        t.remove();
        savedToast(r.path, mode === "overwrite" ? "Saved over original" : fmt === "pdf" ? "PDF ready" : "Saved");
      } catch (e) { t.remove(); fail(e); }
      saving = false;
    }

    stage.append(imgBar);
    chrome(V, [fileRow, fmtRow], h("div", { class: "of-main" }, stage, find.panel), status);
    V.onShow = () => { requestAnimationFrame(() => { if (!savedRange) { page.focus({ preventScroll: true }); setOffsets([0, 0]); } }); };
    V.destroy = () => { V.alive = false; document.removeEventListener("selectionchange", onSel); if (CSS.highlights) { CSS.highlights.delete("of-find"); CSS.highlights.delete("of-find-cur"); } };
    V.page = page;
    setZoom(zoom);
    syncUndo(); updateCount();
    return V;
  }

  // =================================================================== SPREADSHEET
  const RH = 22, HH = 24, RW = 52, DEFW = 84, PAGE = 200;
  const colName = (c) => { let s = ""; c++; while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = (c - m - 1) / 26; } return s; };
  const colIndex = (s) => { let n = 0; for (const ch of s.toUpperCase()) n = n * 26 + ch.charCodeAt(0) - 64; return n - 1; };
  const NFS = [["", "General"], ["0", "Number (0)"], ["0.00", "Number (0.00)"], ["#,##0", "Thousands (1,234)"], ["#,##0.00", "Thousands (1,234.00)"],
    ["$#,##0.00", "Currency ($)"], ["€#,##0.00", "Currency (€)"], ["₹#,##0.00", "Currency (₹)"], ["0%", "Percent (0%)"], ["0.00%", "Percent (0.00%)"],
    ["yyyy-mm-dd", "Date (2024-12-31)"], ["dd/mm/yyyy", "Date (31/12/2024)"], ["yyyy-mm-dd hh:mm", "Date & time"], ["@", "Text"]];

  function parseTSV(text) {
    const rows = []; let row = [], f = "", q = false;
    text = text.replace(/\r\n?/g, "\n");
    if (text.endsWith("\n")) text = text.slice(0, -1);
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += ch; }
      else if (ch === '"' && f === "") q = true;
      else if (ch === "\t") { row.push(f); f = ""; }
      else if (ch === "\n") { row.push(f); rows.push(row); row = []; f = ""; }
      else f += ch;
    }
    row.push(f); rows.push(row);
    return rows;
  }
  const toTSV = (rows) => rows.map((r) => r.map((v) => /[\t\n"]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v).join("\t")).join("\r\n");

  function cssOf(st) {
    if (!st) return "";
    let s = "";
    if (st.b) s += "font-weight:700;";
    if (st.i) s += "font-style:italic;";
    if (st.u || st.s) s += `text-decoration:${st.u ? "underline " : ""}${st.s ? "line-through" : ""};`;
    if (st.color) s += `color:${st.color};`;
    if (st.fill) s += `background:${st.fill};`;
    if (st.al) s += `text-align:${st.al};`;
    if (st.sz) s += `font-size:${st.sz}pt;`;
    return s;
  }

  function SheetView(d) {
    const V = { kind: "sheet", alive: true };
    let M = d.sheet;
    const sid = M.sid;
    let si = M.active || 0;
    let readonly = M.status !== "ready";
    let gen = 0;
    const cache = new Map();          // model row -> {g: gen, cells}
    const inflight = new Set();
    let sel = { r1: 0, c1: 0, r2: 0, c2: 0 }, act = { r: 0, c: 0 }, anchor = { r: 0, c: 0 };
    let filter = null;                 // {q, rows: [model rows], pos: Map}
    let edit = null;                   // {r, c, el, mode, orig}
    let clip = null;                   // internal clipboard {tsv, raw}
    let colX = [0], widths = [], nCols = 26;
    V.dirty = () => !!M.dirty;

    const sheet = () => readonly ? previewSheet() : M.sheets[si];
    function previewSheet() {
      const p = M.preview || { name: "Loading…", rows: [], total: 0 };
      return { name: p.name, rows: p.rows.length, cols: Math.max(0, ...p.rows.map((r) => r.length)), widths: {}, merged: [], frozen: 0 };
    }
    const F = () => (sheet().frozen || 0);
    const totalRows = () => Math.max(sheet().rows + 60, 100);
    const nView = () => filter ? filter.rows.length : Math.max(0, totalRows() - F());
    const modelRow = (v) => filter ? filter.rows[v] : v + F();
    const viewRow = (r) => filter ? (filter.pos.get(r) ?? -1) : r - F();

    // ---------- DOM
    const vp = h("div", { class: "og-vp", tabindex: "0", role: "grid", "aria-label": "Spreadsheet " + O.file.name, "aria-multiselectable": "true" });
    const head = h("div", { class: "og-head" });
    const corner = h("div", { class: "og-corner", title: "Select all (Ctrl+A)" });
    const colsEl = h("div", { class: "og-cols", role: "row" });
    const frozenEl = h("div", { class: "og-frozen" });
    head.append(corner, colsEl, frozenEl);
    const body = h("div", { class: "og-body" });
    const rowsEl = h("div", { class: "og-rows", "aria-hidden": "true" });
    const cellsEl = h("div", { class: "og-cells", role: "rowgroup" });
    const selEl = h("div", { class: "og-sel", hidden: true }), actEl = h("div", { class: "og-act" });
    const selElF = h("div", { class: "og-sel", hidden: true }), actElF = h("div", { class: "og-act", hidden: true });
    body.append(rowsEl, cellsEl);
    cellsEl.append();
    vp.append(head, body);
    const wrap = h("div", { class: "og-wrap" }, vp);

    const nameBox = h("input", { class: "of-name", type: "text", "aria-label": "Cell reference (type e.g. B12 and press Enter to jump)", title: "Cell reference: type e.g. B12 and press Enter" });
    const fx = h("input", { class: "of-formula", type: "text", "aria-label": "Cell contents / formula", placeholder: "Cell contents or =formula", spellcheck: "false" });
    const fbar = h("div", { class: "of-fbar" }, nameBox, h("span", { class: "of-fx", "aria-hidden": "true" }, "fx"), fx);
    const tabs = h("div", { class: "of-tabs", role: "tablist", "aria-label": "Sheets" });
    const banner = h("div", { class: "of-banner", hidden: true });
    const statusL = h("span", {}), statusR = h("span", {});
    const status = h("div", { class: "of-status" }, statusL, h("span", { class: "spacer" }), statusR);

    // ---------- geometry
    function layout() {
      const s = sheet();
      nCols = Math.max(s.cols + 6, 26);
      widths = Array.from({ length: nCols }, (_, c) => s.widths?.[c] ?? DEFW);
      colX = [0];
      for (let c = 0; c < nCols; c++) colX.push(colX[c] + widths[c]);
      const W = RW + colX[nCols];
      head.style.width = W + "px";
      head.style.height = (HH + F() * RH) + "px";
      corner.style.cssText = `width:${RW}px;height:${HH + F() * RH}px`;
      frozenEl.style.cssText = `top:${HH}px;left:0;width:${W}px;height:${F() * RH}px`;
      body.style.width = W + "px";
      body.style.height = nView() * RH + "px";
      rowsEl.style.cssText = `width:${RW}px;height:${nView() * RH}px`;
      cellsEl.style.left = RW + "px";
      vp.setAttribute("aria-rowcount", totalRows());
      vp.setAttribute("aria-colcount", nCols);
    }
    function colAt(x) { let lo = 0, hi = nCols - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (colX[m] <= x) lo = m; else hi = m - 1; } return Math.max(0, lo); }

    // ---------- data
    function rowCells(r) {
      if (readonly) return M.preview?.rows[r]?.map((v) => v === "" || v == null ? null : { v: String(v), n: /^-?[\d.,]+%?$/.test(v) ? 1 : 0 }) || [];
      if (r >= sheet().rows) return [];
      const e = cache.get(r);
      return e ? e.cells : undefined;
    }
    const stale = (r) => !readonly && r < sheet().rows && (!cache.has(r) || cache.get(r).g !== gen);
    let fetchTimer = null;
    function needRows(list) {
      if (readonly) return;
      const missing = list.filter((r) => r < sheet().rows && (!cache.has(r) || cache.get(r).g !== gen));
      if (!missing.length) return;
      clearTimeout(fetchTimer);
      fetchTimer = setTimeout(() => fetchRows(missing), 16);
    }
    async function fetchRows(missing) {
      const g = gen, sIdx = si;
      if (filter) {
        const key = g + ":f:" + missing[0];
        if (inflight.has(key)) return;
        inflight.add(key);
        try {
          const d = await api("/api/office/sheet/rows", { sid, sheet: sIdx, indices: missing });
          if (sIdx === si) missing.forEach((r, i) => store1(r, d.rows[i], d.styles, g));
        } catch (e) { fail(e); } finally { inflight.delete(key); }
      } else {
        const pages = [...new Set(missing.map((r) => Math.floor(r / PAGE)))];
        await Promise.all(pages.map(async (p) => {
          const key = g + ":" + sIdx + ":" + p;
          if (inflight.has(key)) return;
          inflight.add(key);
          try {
            const d = await api(`/api/office/sheet/rows?sid=${sid}&sheet=${sIdx}&start=${p * PAGE}&count=${PAGE}`);
            if (sIdx === si) d.rows.forEach((row, i) => store1(p * PAGE + i, row, d.styles, g));
          } catch (e) { if (V.alive) fail(e); } finally { inflight.delete(key); }
        }));
      }
      if (V.alive) { render(); syncFormulaBar(); }
    }
    function store1(r, row, styles, g) {
      for (const c of row) if (c && c.s != null) { c.st = styles[c.s]; c.css = cssOf(c.st); }
      cache.set(r, { g, cells: row });
    }
    function trimCache() {
      if (cache.size < 30000) return;
      const mid = modelRow(Math.floor(vp.scrollTop / RH));
      for (const r of cache.keys()) if (Math.abs(r - mid) > 5000) cache.delete(r);
    }

    // ---------- rendering
    let rq = false;
    const render = () => { if (!rq) { rq = true; requestAnimationFrame(() => { rq = false; draw(); }); } };
    function cellHTML(r, c, cell, top, left, w, hgt, extra = "") {
      const st = cell?.st;
      let cls = "og-c";
      if (cell?.n && !st?.al) cls += " n";
      if (cell?.x) cls += " x";
      if (st?.wrap) cls += " w";
      if (cell === undefined) cls += " load";
      const css = cell?.css || "";
      const text = cell === undefined ? "" : cell ? esc(cell.v) : "";
      return `<div class="${cls}${extra}" role="gridcell" id="og-${r}-${c}" aria-rowindex="${r + 1}" aria-colindex="${c + 1}"${cell?.x ? ' title="Calculated by Excel when the file is opened there"' : ""} style="top:${top}px;left:${left}px;width:${w}px;height:${hgt}px;${css}">${text}</div>`;
    }
    function draw() {
      if (!V.alive) return;
      const st = vp.scrollTop, sl = vp.scrollLeft;
      const vh = vp.clientHeight - HH - F() * RH, vw = vp.clientWidth - RW;
      const v0 = Math.max(0, Math.floor(st / RH) - 1), v1 = Math.min(nView() - 1, Math.ceil((st + vh) / RH) + 1);
      const c0 = colAt(sl), c1 = Math.min(nCols - 1, colAt(sl + vw) + 1);
      const s = sheet();
      const merges = filter ? [] : s.merged || [];
      const covered = new Set(), need = [];
      // body rows
      let html = "", rh = "";
      const mergeHTML = [];
      for (const [mr1, mc1, mr2, mc2] of merges) {
        const vr1 = viewRow(mr1), vr2 = viewRow(mr2);
        if (mr2 < F() || vr2 < v0 || vr1 > v1 || mc2 < c0 || mc1 > c1) continue;
        for (let r = mr1; r <= mr2; r++) for (let c = mc1; c <= mc2; c++) covered.add(r + ":" + c);
        if (mr1 < F()) continue;
        const cells = rowCells(mr1); if (stale(mr1)) need.push(mr1);
        mergeHTML.push(cellHTML(mr1, mc1, cells?.[mc1] ?? (cells ? null : undefined), vr1 * RH, colX[mc1], colX[mc2 + 1] - colX[mc1], (mr2 - mr1 + 1) * RH, " m"));
      }
      for (let v = v0; v <= v1; v++) {
        const r = modelRow(v);
        if (r === undefined) continue;
        const cells = rowCells(r);
        if (stale(r)) need.push(r);
        let rowHtml = "";
        for (let c = c0; c <= c1; c++) {
          if (covered.has(r + ":" + c)) continue;
          rowHtml += cellHTML(r, c, cells === undefined ? undefined : cells[c] || null, v * RH, colX[c], widths[c], RH);
        }
        html += `<div role="row" aria-rowindex="${r + 1}" style="display:contents">${rowHtml}</div>`;
        const on = r >= Math.min(sel.r1, sel.r2) && r <= Math.max(sel.r1, sel.r2);
        rh += `<div class="og-r${on ? " on" : ""}" data-r="${r}" style="top:${v * RH}px;width:${RW}px">${r + 1}</div>`;
      }
      cellsEl.innerHTML = html + mergeHTML.join("");
      cellsEl.append(selEl, actEl);
      rowsEl.innerHTML = rh;
      // column headers
      let ch = "";
      const cs1 = Math.min(sel.c1, sel.c2), cs2 = Math.max(sel.c1, sel.c2);
      for (let c = c0; c <= c1; c++) ch += `<div class="og-h${c >= cs1 && c <= cs2 ? " on" : ""}" role="columnheader" aria-colindex="${c + 1}" data-c="${c}" style="left:${RW + colX[c]}px;width:${widths[c]}px">${colName(c)}<i class="rz" data-c="${c}" title="Drag to resize"></i></div>`;
      colsEl.innerHTML = ch;
      // frozen rows (header strip)
      let fh = "", frh = "";
      for (let r = 0; r < F(); r++) {
        const cells = rowCells(r);
        if (stale(r)) need.push(r);
        for (let c = c0; c <= c1; c++) fh += cellHTML(r, c, cells === undefined ? undefined : cells[c] || null, r * RH, RW + colX[c], widths[c], RH);
        const on = r >= Math.min(sel.r1, sel.r2) && r <= Math.max(sel.r1, sel.r2);
        frh += `<div class="og-r${on ? " on" : ""}" data-r="${r}" style="top:${HH + r * RH}px;width:${RW}px;position:absolute">${r + 1}</div>`;
      }
      frozenEl.innerHTML = fh;
      frozenEl.append(selElF, actElF);
      corner.innerHTML = frh;
      drawSel();
      if (need.length) needRows(need);
      trimCache();
      const id = `og-${act.r}-${act.c}`;
      if (document.getElementById(id)) vp.setAttribute("aria-activedescendant", id); else vp.removeAttribute("aria-activedescendant");
    }
    function rectOf(r1, c1, r2, c2) {
      // rectangle in body coordinates for rows >= F, or in frozen coordinates for rows < F
      const top = viewRow(r1), bot = viewRow(r2);
      return { top: top * RH, height: (bot - top + 1) * RH, left: colX[c1], width: colX[c2 + 1] - colX[c1] };
    }
    function drawSel() {
      const r1 = Math.min(sel.r1, sel.r2), r2 = Math.max(sel.r1, sel.r2), c1 = Math.min(sel.c1, sel.c2), c2 = Math.max(sel.c1, sel.c2);
      const fz = F();
      const box = (el, top, height, left, width, dx = 0) => { el.hidden = height <= 0; el.style.cssText = `top:${top}px;height:${height}px;left:${left + dx}px;width:${width}px`; };
      const multi = r1 !== r2 || c1 !== c2;
      // part in the body
      const br1 = Math.max(r1, fz);
      if (multi && r2 >= fz && (!filter || true)) {
        const a = filter ? viewRow(br1) : br1 - fz, b = filter ? viewRow(r2) : r2 - fz;
        if (a >= 0 && b >= 0) box(selEl, a * RH, (b - a + 1) * RH, colX[c1], colX[c2 + 1] - colX[c1]); else selEl.hidden = true;
      } else selEl.hidden = true;
      if (multi && r1 < fz) box(selElF, r1 * RH, (Math.min(r2, fz - 1) - r1 + 1) * RH, colX[c1], colX[c2 + 1] - colX[c1], RW); else selElF.hidden = true;
      // active cell (merged cells get the full merge rectangle)
      const m = (sheet().merged || []).find(([a, b, c, d2]) => act.r >= a && act.r <= c && act.c >= b && act.c <= d2);
      const [ar1, ac1, ar2, ac2] = m && !filter ? m : [act.r, act.c, act.r, act.c];
      if (ar1 < fz) { actEl.hidden = true; actElF.hidden = false; box(actElF, ar1 * RH, (ar2 - ar1 + 1) * RH, colX[ac1], colX[ac2 + 1] - colX[ac1], RW); }
      else {
        actElF.hidden = true;
        const v = viewRow(ar1);
        if (v < 0) actEl.hidden = true; else { actEl.hidden = false; box(actEl, v * RH, (ar2 - ar1 + 1) * RH, colX[ac1], colX[ac2 + 1] - colX[ac1]); }
      }
    }
    vp.addEventListener("scroll", () => { render(); if (edit) placeEditor(); });
    new ResizeObserver(() => render()).observe(vp);

    // ---------- selection
    const cellAt = (r) => rowCells(r);
    const lastRow = () => totalRows() - 1;
    function select(r, c, extend = false, keepAnchor = false) {
      r = Math.max(0, Math.min(r, lastRow())); c = Math.max(0, Math.min(c, nCols - 1));
      if (filter && r >= F() && !filter.pos.has(r)) return;
      act = { r, c };
      if (!extend) { anchor = { r, c }; sel = { r1: r, c1: c, r2: r, c2: c }; }
      else sel = { r1: anchor.r, c1: anchor.c, r2: r, c2: c };
      if (keepAnchor) sel = { ...sel };
      scrollIntoView(r, c);
      syncFormulaBar();
      render();
    }
    function scrollIntoView(r, c) {
      const vh = vp.clientHeight - HH - F() * RH, vw = vp.clientWidth - RW;
      if (r >= F()) {
        const v = viewRow(r);
        if (v >= 0) {
          if (v * RH < vp.scrollTop) vp.scrollTop = v * RH;
          else if ((v + 1) * RH > vp.scrollTop + vh) vp.scrollTop = (v + 1) * RH - vh;
        }
      }
      if (colX[c] < vp.scrollLeft) vp.scrollLeft = colX[c];
      else if (colX[c + 1] > vp.scrollLeft + vw) vp.scrollLeft = colX[c + 1] - vw;
    }
    function rawOf(cell) { return cell ? (cell.f ?? cell.e ?? cell.v ?? "") : ""; }
    function syncFormulaBar() {
      const r1 = Math.min(sel.r1, sel.r2), r2 = Math.max(sel.r1, sel.r2), c1 = Math.min(sel.c1, sel.c2), c2 = Math.max(sel.c1, sel.c2);
      if (document.activeElement !== nameBox) nameBox.value = r1 === r2 && c1 === c2 ? colName(act.c) + (act.r + 1) : `${colName(c1)}${r1 + 1}:${colName(c2)}${r2 + 1}`;
      if (document.activeElement !== fx && !edit) { const cells = cellAt(act.r); fx.value = cells ? rawOf(cells[act.c]) : ""; }
      const n = (r2 - r1 + 1) * (c2 - c1 + 1);
      statusR.textContent = n > 1 ? `${(r2 - r1 + 1).toLocaleString()} × ${c2 - c1 + 1} selected` + selStats(r1, r2, c1, c2) : "";
    }
    function selStats(r1, r2, c1, c2) {
      if ((r2 - r1 + 1) * (c2 - c1 + 1) > 20000) return "";
      let sum = 0, count = 0;
      for (let r = r1; r <= r2; r++) { const cells = cellAt(r); if (!cells) continue; for (let c = c1; c <= c2; c++) { const x = cells[c]; if (x?.n) { const v = parseFloat(String(x.e ?? x.v).replace(/[^0-9.eE+-]/g, "")); if (!isNaN(v)) { sum += v; count++; } } } }
      return count ? ` · Sum ${+sum.toFixed(10)} · Average ${+(sum / count).toFixed(10)} · Count ${count}` : "";
    }
    function hit(e) {
      const br = body.getBoundingClientRect();
      const x = e.clientX - br.left - RW, y = e.clientY - br.top;
      const v = Math.max(0, Math.min(nView() - 1, Math.floor(y / RH)));
      return { r: modelRow(v), c: colAt(Math.max(0, x)), x };
    }
    let dragging = null;
    body.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      commitEdit();
      const p = hit(e);
      if (p.r === undefined) return;
      vp.focus({ preventScroll: true });
      if (p.x < 0 || e.target.closest(".og-r")) {  // row header
        anchor = e.shiftKey ? anchor : { r: p.r, c: 0 };
        sel = { r1: anchor.r, c1: 0, r2: p.r, c2: nCols - 1 }; act = { r: p.r, c: act.c };
        dragging = "row";
      } else {
        select(p.r, p.c, e.shiftKey);
        dragging = "cell";
      }
      body.setPointerCapture(e.pointerId);
      syncFormulaBar(); render();
    });
    body.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const p = hit(e);
      if (p.r === undefined) return;
      if (dragging === "row") sel = { ...sel, r2: p.r };
      else sel = { r1: anchor.r, c1: anchor.c, r2: p.r, c2: p.c };
      autoscroll(e);
      syncFormulaBar(); render();
    });
    body.addEventListener("pointerup", () => (dragging = null));
    body.addEventListener("dblclick", (e) => { const p = hit(e); if (p.x >= 0 && p.r !== undefined) { select(p.r, p.c); startEdit("edit"); } });
    function autoscroll(e) {
      const r = vp.getBoundingClientRect();
      if (e.clientY > r.bottom - 20) vp.scrollTop += RH;
      else if (e.clientY < r.top + HH + F() * RH + 10) vp.scrollTop -= RH;
      if (e.clientX > r.right - 20) vp.scrollLeft += 40;
      else if (e.clientX < r.left + RW + 10) vp.scrollLeft -= 40;
    }
    // header strip: column headers, resize handles, frozen rows, corner
    head.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      commitEdit();
      vp.focus({ preventScroll: true });
      const hr = head.getBoundingClientRect();
      const x = e.clientX - hr.left - RW, y = e.clientY - hr.top;
      if (e.target.classList.contains("rz")) { startResize(e, +e.target.dataset.c); return; }
      if (x < 0 && y < HH) { anchor = { r: 0, c: 0 }; sel = { r1: 0, c1: 0, r2: lastRow(), c2: nCols - 1 }; syncFormulaBar(); render(); return; }
      if (y < HH) {  // column header
        const c = colAt(x);
        if (!e.shiftKey) anchor = { r: 0, c };
        sel = { r1: 0, c1: anchor.c, r2: lastRow(), c2: c }; act = { r: act.r, c };
        dragging = "col";
        head.setPointerCapture(e.pointerId);
      } else {  // frozen rows
        const r = Math.min(F() - 1, Math.floor((y - HH) / RH));
        if (x < 0) { anchor = e.shiftKey ? anchor : { r, c: 0 }; sel = { r1: anchor.r, c1: 0, r2: r, c2: nCols - 1 }; act = { r, c: act.c }; }
        else { select(r, colAt(x), e.shiftKey); dragging = "cell"; head.setPointerCapture(e.pointerId); }
      }
      syncFormulaBar(); render();
    });
    head.addEventListener("pointermove", (e) => {
      if (dragging !== "col") return;
      const hr = head.getBoundingClientRect();
      sel = { ...sel, c2: colAt(Math.max(0, e.clientX - hr.left - RW)) };
      syncFormulaBar(); render();
    });
    head.addEventListener("pointerup", () => (dragging = null));
    head.addEventListener("dblclick", (e) => {
      const hr = head.getBoundingClientRect(), y = e.clientY - hr.top, x = e.clientX - hr.left - RW;
      if (y >= HH && x >= 0) { select(Math.floor((y - HH) / RH), colAt(x)); startEdit("edit"); }
    });
    function startResize(e, c) {
      e.stopPropagation(); e.preventDefault();
      const x0 = e.clientX, w0 = widths[c];
      const move = (ev) => { const w = Math.max(16, w0 + ev.clientX - x0); sheet().widths[c] = w; layout(); render(); };
      const up = async (ev) => {
        removeEventListener("pointermove", move); removeEventListener("pointerup", up);
        const w = Math.max(16, w0 + ev.clientX - x0);
        if (w !== w0) op({ type: "col_width", col: c, px: w }, false);
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    }

    // ---------- editing
    const editor = h("textarea", { class: "og-edit", rows: 1, spellcheck: "false", "aria-label": "Edit cell" });
    function startEdit(mode, initial) {
      if (readonly) return toast("Still loading the workbook… you can edit in a moment");
      const cells = cellAt(act.r);
      if (cells === undefined) return;
      const cell = cells?.[act.c];
      edit = { r: act.r, c: act.c, mode, orig: rawOf(cell) };
      editor.value = initial ?? edit.orig;
      (act.r < F() ? head : body).append(editor);
      placeEditor();
      editor.focus();
      const n = editor.value.length; editor.setSelectionRange(n, n);
      fx.value = editor.value;
    }
    function placeEditor() {
      if (!edit) return;
      const m = (sheet().merged || []).find(([a, b, c, d2]) => edit.r >= a && edit.r <= c && edit.c >= b && edit.c <= d2);
      const [r1, c1, r2, c2] = m && !filter ? m : [edit.r, edit.c, edit.r, edit.c];
      const top = edit.r < F() ? HH + r1 * RH : viewRow(r1) * RH, left = RW + colX[c1];
      const w = colX[c2 + 1] - colX[c1], hgt = (r2 - r1 + 1) * RH;
      editor.style.cssText = `top:${top}px;left:${left}px;min-width:${w}px;height:${Math.max(hgt, RH * Math.min(8, editor.value.split("\n").length))}px;width:${Math.max(w, Math.min(600, editor.scrollWidth + 4))}px`;
    }
    editor.addEventListener("input", () => { fx.value = editor.value; placeEditor(); });
    editor.addEventListener("keydown", (e) => {
      const k = e.key;
      if (k === "Enter" && e.altKey) { e.preventDefault(); const p = editor.selectionStart; editor.setRangeText("\n", p, editor.selectionEnd, "end"); placeEditor(); return; }
      if (k === "Enter") { e.preventDefault(); commitEdit(); move(e.shiftKey ? -1 : 1, 0); }
      else if (k === "Tab") { e.preventDefault(); commitEdit(); move(0, e.shiftKey ? -1 : 1); }
      else if (k === "Escape") { e.preventDefault(); cancelEdit(); }
      else if (edit?.mode === "enter" && k.startsWith("Arrow")) { e.preventDefault(); commitEdit(); move(...({ ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] })[k]); }
      e.stopPropagation();
    });
    editor.addEventListener("blur", () => { if (edit && document.activeElement !== fx) commitEdit(); });
    function commitEdit() {
      if (!edit) return;
      const { r, c, orig } = edit;
      const val = editor.value;
      edit = null; editor.remove();
      vp.focus({ preventScroll: true });
      if (val !== orig) setCells([[r, c, val]]);
      syncFormulaBar();
    }
    function cancelEdit() { if (!edit) return; edit = null; editor.remove(); vp.focus({ preventScroll: true }); syncFormulaBar(); }
    async function setCells(cells) {
      // optimistic: show the typed text immediately, then the server's formatted/calculated result
      for (const [r, c, v] of cells.slice(0, 5000)) {
        const e = cache.get(r);
        if (e) { const row = e.cells; while (row.length <= c) row.push(null); row[c] = v === "" ? null : { ...(row[c] || {}), v: String(v).startsWith("=") ? "…" : v, f: undefined, e: undefined, x: 0 }; }
      }
      render();
      await op({ type: "set", cells });
    }
    fx.addEventListener("focus", () => { if (readonly) return; fx.dataset.orig = fx.value; fx.dataset.r = act.r; fx.dataset.c = act.c; });
    fx.addEventListener("input", () => { if (edit) { editor.value = fx.value; placeEditor(); } });
    fx.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (edit) { editor.value = fx.value; commitEdit(); }
        else if (fx.value !== fx.dataset.orig && !readonly) setCells([[+fx.dataset.r, +fx.dataset.c, fx.value]]);
        fx.dataset.orig = fx.value;
        vp.focus({ preventScroll: true });
        if (e.key === "Enter") move(1, 0); else move(0, e.shiftKey ? -1 : 1);
      } else if (e.key === "Escape") { e.preventDefault(); if (edit) cancelEdit(); fx.value = fx.dataset.orig || ""; vp.focus({ preventScroll: true }); }
      e.stopPropagation();
    });
    nameBox.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Escape") { vp.focus(); syncFormulaBar(); return; }
      if (e.key !== "Enter") return;
      e.preventDefault();
      const m = nameBox.value.trim().toUpperCase().match(/^([A-Z]{1,3})(\d+)(?::([A-Z]{1,3})(\d+))?$/);
      if (!m) return toast("Type a cell like B12 or a range like A1:C20", true);
      vp.focus({ preventScroll: true });
      select(+m[2] - 1, colIndex(m[1]));
      if (m[3]) { sel = { r1: +m[2] - 1, c1: colIndex(m[1]), r2: +m[4] - 1, c2: colIndex(m[3]) }; render(); syncFormulaBar(); }
    });

    function move(dr, dc, extend = false, jump = false) {
      const s = sheet();
      let { r, c } = extend ? { r: sel.r2, c: sel.c2 } : act;
      if (filter && r >= F()) {
        let v = viewRow(r);
        if (jump) v = dr > 0 ? nView() - 1 : dr < 0 ? 0 : v;
        else v = Math.max(0, Math.min(nView() - 1, v + dr));
        r = dr ? modelRow(v) : r;
        if (dr < 0 && viewRow(act.r) === 0 && F()) r = F() - 1;
      } else if (jump) r = dr > 0 ? Math.max(s.rows - 1, 0) : dr < 0 ? 0 : r;
      else r += dr;
      if (jump) c = dc > 0 ? Math.max(s.cols - 1, 0) : dc < 0 ? 0 : c; else c += dc;
      // skip over merged areas
      const m = !extend && (s.merged || []).find(([a, b, cc, d2]) => act.r >= a && act.r <= cc && act.c >= b && act.c <= d2);
      if (m && !jump) { if (dc > 0) c = m[3] + 1; if (dr > 0) r = m[2] + 1; }
      if (extend) {
        r = Math.max(0, Math.min(r, lastRow())); c = Math.max(0, Math.min(c, nCols - 1));
        sel = { r1: anchor.r, c1: anchor.c, r2: r, c2: c };
        scrollIntoView(r, c); syncFormulaBar(); render();
      } else select(r, c);
    }

    // ---------- keyboard
    vp.addEventListener("keydown", (e) => {
      if (edit) return;
      const k = e.key, ctrl = e.ctrlKey || e.metaKey;
      const arrows = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
      if (arrows[k]) { e.preventDefault(); move(...arrows[k], e.shiftKey, ctrl); return; }
      if (k === "Tab") { e.preventDefault(); move(0, e.shiftKey ? -1 : 1); return; }
      if (k === "Enter" || k === "F2") { e.preventDefault(); if (k === "Enter" && e.shiftKey) move(-1, 0); else startEdit("edit"); return; }
      if (k === "Home") { e.preventDefault(); ctrl ? select(0, 0) : select(act.r, 0); return; }
      if (k === "End") { e.preventDefault(); const s = sheet(); ctrl ? select(Math.max(0, s.rows - 1), Math.max(0, s.cols - 1)) : select(act.r, Math.max(0, s.cols - 1)); return; }
      if (k === "PageDown" || k === "PageUp") { e.preventDefault(); const n = Math.max(1, Math.floor((vp.clientHeight - HH) / RH) - 1); move(k === "PageDown" ? n : -n, 0, e.shiftKey); return; }
      if (k === "Delete" || k === "Backspace") { e.preventDefault(); clearSel(); return; }
      if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); anchor = { r: 0, c: 0 }; sel = { r1: 0, c1: 0, r2: lastRow(), c2: nCols - 1 }; syncFormulaBar(); render(); return; }
      if (k.length === 1 && !ctrl && !e.altKey) { e.preventDefault(); startEdit("enter", k); }
    });
    V.onKey = (e) => {
      const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
      if (!ctrl || e.altKey) return;
      const ae = document.activeElement;
      const inGrid = !edit && (vp.contains(ae) || (V.el.contains(ae) && !/^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) || ae === document.body);
      if (k === "s") { e.preventDefault(); save(null, "copy"); }
      else if (k === "f") { e.preventDefault(); search.focus(); search.select(); }
      else if (!inGrid) return;
      else if (k === "z" && !e.shiftKey) { e.preventDefault(); undoRedo("undo"); }
      else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); undoRedo("redo"); }
      else if (k === "b") { e.preventDefault(); toggleFmt("b"); }
      else if (k === "i") { e.preventDefault(); toggleFmt("i"); }
      else if (k === "u") { e.preventDefault(); toggleFmt("u"); }
    };

    // ---------- clipboard (TSV, so it pastes into Excel and back)
    const normSel = () => ({ r1: Math.min(sel.r1, sel.r2), r2: Math.max(sel.r1, sel.r2), c1: Math.min(sel.c1, sel.c2), c2: Math.max(sel.c1, sel.c2) });
    function clampSel() { const s = normSel(), sh = sheet(); return { ...s, r2: Math.min(s.r2, Math.max(sh.rows - 1, s.r1)), c2: Math.min(s.c2, Math.max(sh.cols - 1, s.c1)) }; }
    function localRange(s, raw) {
      const out = [];
      for (let r = s.r1; r <= s.r2; r++) {
        const cells = cellAt(r);
        if (cells === undefined) return null;
        const row = [];
        for (let c = s.c1; c <= s.c2; c++) row.push(raw ? rawOf(cells[c]) : cells[c]?.v ?? "");
        out.push(row);
      }
      return out;
    }
    async function copySel(e, cut) {
      const s = clampSel();
      const rows = (s.r2 - s.r1 + 1) * (s.c2 - s.c1 + 1);
      const local = rows <= 200000 ? localRange(s, false) : null;
      if (local) {
        const tsv = toTSV(local);
        e.clipboardData.setData("text/plain", tsv); e.preventDefault();
        clip = { tsv, raw: localRange(s, true) };
      } else {
        e.preventDefault();
        try {
          const [vals, raw] = await Promise.all([api("/api/office/sheet/range", { sid, sheet: si, ...s }), api("/api/office/sheet/range", { sid, sheet: si, ...s, raw: true })]);
          const tsv = toTSV(vals.values);
          await navigator.clipboard.writeText(tsv);
          clip = { tsv, raw: raw.values };
          toast(`Copied ${vals.values.length.toLocaleString()} rows`);
        } catch (err) { fail(err); return; }
      }
      if (cut) clearSel();
    }
    function pasteText(text) {
      if (readonly) return;
      const rows = clip && clip.tsv.replace(/\r\n/g, "\n") === text.replace(/\r\n/g, "\n") ? clip.raw : parseTSV(text);
      const s = normSel();
      const cells = [];
      if (rows.length === 1 && rows[0].length === 1 && (s.r1 !== s.r2 || s.c1 !== s.c2)) {  // one value into a range: fill it
        const sh = clampSel();
        for (let r = s.r1; r <= Math.min(s.r2, Math.max(sh.r2, s.r1 + 999)); r++) for (let c = s.c1; c <= s.c2; c++) cells.push([r, c, rows[0][0]]);
      } else rows.forEach((row, i) => row.forEach((v, j) => cells.push([act.r + i, act.c + j, v])));
      setCells(cells);
      sel = { r1: act.r, c1: act.c, r2: act.r + rows.length - 1, c2: act.c + Math.max(...rows.map((r) => r.length)) - 1 };
      render();
    }
    const onCopy = (e) => { if (V.alive && document.activeElement === vp && S.view === "office") copySel(e, false); };
    const onCut = (e) => { if (V.alive && document.activeElement === vp && S.view === "office" && !readonly) copySel(e, true); };
    const onPaste = (e) => { if (V.alive && document.activeElement === vp && S.view === "office") { e.preventDefault(); pasteText(e.clipboardData.getData("text/plain")); } };
    document.addEventListener("copy", onCopy); document.addEventListener("cut", onCut); document.addEventListener("paste", onPaste);
    function clearSel() {
      if (readonly) return;
      const s = clampSel();
      if (s.r1 > s.r2 || s.c1 > s.c2) return;
      if ((s.r2 - s.r1 + 1) * (s.c2 - s.c1 + 1) > 2e6) return toast("That's too many cells to clear at once", true);
      const cells = [];
      for (let r = s.r1; r <= s.r2; r++) for (let c = s.c1; c <= s.c2; c++) cells.push([r, c, ""]);
      setCells(cells);
    }

    // ---------- server edits
    async function op(o, refresh = true) {
      if (readonly) { toast("Still loading the workbook… you can edit in a moment"); return; }
      try {
        const r = await api("/api/office/sheet/op", { sid, op: { sheet: si, ...o } });
        applyMeta(r.sheet);
        if (refresh) invalidate();
        const ae = document.activeElement;
        if (V.el.contains(ae) && ae !== vp && !/^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName) && !edit) vp.focus({ preventScroll: true });
      } catch (e) { fail(e); invalidate(); }
    }
    async function undoRedo(which) {
      if (readonly) return;
      try { applyMeta((await api("/api/office/sheet/" + which, { sid })).sheet); invalidate(); if (!edit) vp.focus({ preventScroll: true }); } catch (e) { fail(e); }
    }
    function invalidate() {
      gen++;
      if (filter) runFilter(filter.q, true); else { layout(); render(); }
    }
    function applyMeta(m) {
      M = m;
      if (si >= M.sheets?.length) si = M.sheets.length - 1;
      undoBtn.disabled = !M.can_undo; redoBtn.disabled = !M.can_redo;
      V.setTitle?.();
      layout(); renderTabs(); updateStatus();
    }
    function updateStatus() {
      const s = sheet();
      statusL.replaceChildren(readonly ? "Loading…" : h("span", {}, h("b", {}, s.rows.toLocaleString()), " rows · ", h("b", {}, s.cols), " columns", filter ? h("span", {}, " · ", h("b", {}, filter.rows.length.toLocaleString()), " match “", filter.q, "”") : ""));
    }
    function selRows() { const s = normSel(); return { at: s.r1, n: Math.min(s.r2 - s.r1 + 1, Math.max(1, sheet().rows - s.r1)) }; }
    function selCols() { const s = normSel(); return { at: s.c1, n: Math.min(s.c2 - s.c1 + 1, Math.max(1, sheet().cols - s.c1)) }; }
    function structural(type, axis) {
      if (filter && type === "insert") return toast("Clear the filter before inserting rows", true);
      const { at, n } = axis === "row" ? selRows() : selCols();
      op({ type, axis, at, n });
    }
    function toggleFmt(k) {
      const cells = cellAt(act.r);
      const on = !!cells?.[act.c]?.st?.[k];
      fmt({ [k]: !on });
    }
    function fmt(patch) {
      const s = normSel();
      op({ type: "fmt", r1: s.r1, c1: s.c1, r2: s.r2, c2: s.c2, patch });
    }
    function sortBy(asc) {
      if (filter) return toast("Clear the filter before sorting", true);
      op({ type: "sort", col: act.c, asc, header: F() > 0 });
    }

    // ---------- filter / search
    let filterTimer = null;
    const search = h("input", { type: "search", class: "of-search", placeholder: "🔎 Filter rows…", "aria-label": "Filter rows containing text (Ctrl+F)", title: "Show only rows containing this text. The frozen header row always stays." });
    search.addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => runFilter(search.value.trim()), 300); });
    search.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") { search.value = ""; runFilter(""); vp.focus(); } if (e.key === "Enter") vp.focus(); });
    async function runFilter(q, keepScroll = false) {
      if (readonly) return;
      if (!q) { filter = null; layout(); render(); updateStatus(); return; }
      try {
        const d = await api("/api/office/sheet/search", { sid, sheet: si, q });
        const rows = d.rows.filter((r) => r >= F());
        filter = { q, rows, pos: new Map(rows.map((r, i) => [r, i])) };
        if (!keepScroll) vp.scrollTop = 0;
        layout(); render(); updateStatus();
        if (rows.length && !filter.pos.has(act.r) && act.r >= F()) select(rows[0], act.c);
      } catch (e) { fail(e); }
    }

    // ---------- sheet tabs
    function renderTabs() {
      const names = readonly ? (M.preview?.sheets || [sheet().name]) : M.sheets.map((s) => s.name);
      tabs.replaceChildren(...names.map((n, i) => h("button", { role: "tab", type: "button", "aria-selected": String(i === si), tabindex: i === si ? "0" : "-1",
        title: "Double-click to rename", onclick: () => switchSheet(i), ondblclick: () => renameSheet(i) }, n)),
      h("button", { class: "tb", type: "button", title: "Add sheet", "aria-label": "Add sheet", disabled: readonly, onclick: async () => { await op({ type: "add_sheet", name: "Sheet" }); switchSheet(M.sheets.length - 1); } }, "＋"),
      h("span", { class: "spacer" }),
      h("button", { class: "tb", type: "button", title: "Rename this sheet", "aria-label": "Rename sheet", disabled: readonly, onclick: () => renameSheet(si) }, "✎ Rename"),
      h("button", { class: "tb", type: "button", title: "Delete this sheet", "aria-label": "Delete sheet", disabled: readonly || names.length < 2, onclick: async () => {
        if (await ask(`Delete the sheet “${names[si]}”? (Undo brings it back.)`, { danger: true, yes: "Delete" })) { await op({ type: "delete_sheet" }); switchSheet(Math.min(si, M.sheets.length - 1)); }
      } }, "🗑 Delete"));
      tabs.onkeydown = (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const i = (si + (e.key === "ArrowRight" ? 1 : -1) + names.length) % names.length;
        switchSheet(i); tabs.querySelectorAll("[role=tab]")[i]?.focus();
      };
    }
    async function renameSheet(i) {
      if (readonly) return;
      const name = await prompt("New name for this sheet:", M.sheets[i].name, { title: "rename sheet", yes: "Rename" });
      if (name && name !== M.sheets[i].name) { const keep = si; si = i; await op({ type: "rename_sheet", name }); si = keep; renderTabs(); }
    }
    function switchSheet(i) {
      if (readonly || i === si && cache.size) { renderTabs(); return; }
      commitEdit();
      si = i; cache.clear(); gen++; filter = null; search.value = "";
      act = { r: 0, c: 0 }; anchor = { r: 0, c: 0 }; sel = { r1: 0, c1: 0, r2: 0, c2: 0 };
      vp.scrollTop = 0; vp.scrollLeft = 0;
      layout(); renderTabs(); updateStatus(); render(); syncFormulaBar();
    }

    // ---------- loading big files
    let pollTimer = null;
    async function poll() {
      try {
        const m = (await api("/api/office/sheet/meta?sid=" + sid)).sheet;
        if (!V.alive) return;
        if (m.status === "ready") { readonly = false; banner.hidden = true; applyMeta(m); gen++; render(); toast("Workbook loaded: you can edit now ✎"); syncFormulaBar(); return; }
        if (m.status === "error") { banner.textContent = "Couldn't load: " + m.error; return; }
        banner.replaceChildren(h("span", { class: "spinner" }), `Loading the whole workbook so you can edit it… ${Math.round(m.elapsed)}s. You can look around the first rows meanwhile.`);
        M.elapsed = m.elapsed;
      } catch (e) { banner.textContent = e.message; return; }
      pollTimer = setTimeout(poll, 1000);
    }

    // ---------- save / export / print
    const ext = O.file.ext;
    const primary = ["xlsx", "xlsm", "csv", "tsv"].includes(ext) ? ext : "xlsx";
    let warnedDrawings = false;
    async function save(fmtArg, mode) {
      if (readonly) return toast("Still loading the workbook…");
      commitEdit();
      const fmt = fmtArg || primary;
      if (mode === "overwrite") {
        if (!(await ask(`Overwrite the original “${O.file.name}”? This can't be undone.${M.has_drawings ? " Charts, pictures and pivot tables in this workbook will be lost." : ""}`, { title: "save over original", danger: true, yes: "Overwrite", no: "Cancel" }))) return;
      } else if (M.has_drawings && ["xlsx", "xlsm"].includes(fmt) && !warnedDrawings) {
        if (!(await ask("This workbook has charts or pictures. The saved copy keeps your data, formulas and formatting, but not the charts and pictures. Save anyway?", { title: "heads up", yes: "Save copy", no: "Cancel" }))) return;
        warnedDrawings = true;
      }
      if (["csv", "tsv"].includes(fmt) && M.sheets.length > 1) toast(`Only the sheet “${sheet().name}” goes into the .${fmt} file`, false, 5000);
      const t = toast(fmt === "pdf" ? "Making the PDF…" : "Saving…", false, 120000);
      try {
        const r = await api("/api/office/sheet/save", { sid, format: fmt, mode, out_dir: S.outDir, sheet: si });
        applyMeta(r.sheet);
        t.remove();
        savedToast(r.path, mode === "overwrite" ? "Saved over original" : fmt === "pdf" ? "PDF ready" : "Saved");
      } catch (e) { t.remove(); fail(e); }
    }
    const printBox = h("div", { class: "of-print" });
    async function print() {
      if (readonly) return toast("Still loading the workbook…");
      doPrint(async () => {
        const d = await api("/api/office/sheet/print", { sid, sheet: si });
        printBox.innerHTML = d.html;
        if (d.notes?.length) toast("Printing " + d.notes.join("; "));
        return null;
      });
    }

    // ---------- toolbar
    const undoBtn = tb(ico("undo"), "Undo (Ctrl+Z)", () => undoRedo("undo"), { keep: false }), redoBtn = tb(ico("redo"), "Redo (Ctrl+Y)", () => undoRedo("redo"), { keep: false });
    const nfSel = h("select", { title: "Number format", "aria-label": "Number format", style: "width:150px" }, h("option", { value: "__" }, "Number format…"), ...NFS.map(([v, l]) => h("option", { value: v }, l)));
    nfSel.onchange = () => { if (nfSel.value !== "__") fmt({ nf: nfSel.value }); nfSel.value = "__"; vp.focus(); };
    const fileRow = h("div", { class: "of-tools", role: "toolbar", "aria-label": "File" },
      tb(ico("open"), "Open another file", pickAndOpen, { keep: false }),
      h("button", { class: "btn sm", title: `Save a copy as “${O.file.name.replace(/\.[^.]+$/, "")} (edited).${primary}” in the output folder (Ctrl+S)`, onclick: () => save(null, "copy") }, "💾 Save"),
      dropdown("Save as ▾", "Save in another format", () => [
        ["Excel workbook (.xlsx)", () => save("xlsx", "copy"), { hint: "XLSX" }],
        ["CSV, this sheet (.csv)", () => save("csv", "copy"), { hint: "CSV" }],
        ["Tab-separated (.tsv)", () => save("tsv", "copy"), { hint: "TSV" }],
        ["OpenDocument (.ods)", () => save("ods", "copy"), { hint: "values" }],
        ["JSON (.json)", () => save("json", "copy"), { hint: "JSON" }],
        ["PDF", () => save("pdf", "copy"), { hint: O.caps.excel ? "via Excel" : "PDF" }], "-",
        ["Save over original…", () => save(ext, "overwrite"), { danger: true, disabled: !["xlsx", "xlsm", "csv", "tsv"].includes(ext) }],
      ], { keep: false }),
      tb("⇩ PDF", "Export to PDF", () => save("pdf", "copy"), { keep: false }),
      tb(ico("print"), "Print this sheet", print, { keep: false }),
      sep(), undoBtn, redoBtn, sep(), search,
      h("span", { class: "of-hint" }, (M.notes || []).join(" ")));
    const fmtRow = h("div", { class: "of-tools", role: "toolbar", "aria-label": "Cells" },
      tb(h("span", { class: "of-b" }, "B"), "Bold (Ctrl+B)", () => toggleFmt("b"), { keep: false }),
      tb(h("span", { class: "of-i" }, "I"), "Italic (Ctrl+I)", () => toggleFmt("i"), { keep: false }),
      tb(h("span", { class: "of-u" }, "U"), "Underline (Ctrl+U)", () => toggleFmt("u"), { keep: false }),
      colorBtn("A", "Text colour", "#c00000", (c) => fmt({ color: c })),
      colorBtn("▨", "Fill colour", "#ffe3a3", (c) => fmt({ fill: c })),
      tb("⌫▨", "Remove fill", () => fmt({ fill: "" }), { keep: false }),
      sep(),
      tb(ico("left"), "Align left", () => fmt({ al: "left" }), { keep: false }), tb(ico("center"), "Centre", () => fmt({ al: "center" }), { keep: false }), tb(ico("right"), "Align right", () => fmt({ al: "right" }), { keep: false }),
      nfSel, sep(),
      dropdown("Rows ▾", "Insert or delete rows", [["Insert row(s) above", () => structural("insert", "row")], ["Delete selected row(s)", () => structural("delete", "row"), { danger: true }]], { keep: false }),
      dropdown("Columns ▾", "Insert or delete columns", [["Insert column(s) left", () => structural("insert", "col")], ["Delete selected column(s)", () => structural("delete", "col"), { danger: true }]], { keep: false }),
      sep(),
      tb("A→Z", "Sort rows by this column, ascending (the frozen header row stays on top)", () => sortBy(true), { keep: false }),
      tb("Z→A", "Sort rows by this column, descending", () => sortBy(false), { keep: false }),
      tb("❄ Header", "Freeze / unfreeze the header row", () => op({ type: "freeze", rows: F() ? 0 : 1 }), { keep: false }));

    const main = h("div", { class: "of-main" }, banner, wrap, tabs, printBox);
    chrome(V, [fileRow, fmtRow, fbar], main, status);
    V.onShow = () => { layout(); render(); requestAnimationFrame(() => vp.focus({ preventScroll: true })); };
    V.destroy = async () => {
      V.alive = false; clearTimeout(pollTimer);
      document.removeEventListener("copy", onCopy); document.removeEventListener("cut", onCut); document.removeEventListener("paste", onPaste);
      api("/api/office/sheet/close", { sid }).catch(() => {});
    };
    if (readonly) { banner.hidden = false; poll(); }
    undoBtn.disabled = !M.can_undo; redoBtn.disabled = !M.can_redo;
    layout(); renderTabs(); updateStatus(); syncFormulaBar();
    V.select = select;
    return V;
  }

  // =================================================================== VIEWERS (slides, PDF)
  function pagesView(V, pdfPath, pages) {
    const stage = h("div", { class: "of-stage" });
    const list = h("div", { class: "of-pages" });
    stage.append(list);
    let zoom = 0;
    const draw = () => {
      const avail = Math.max(300, stage.clientWidth - 60);
      const z = zoom || Math.min(1.6, avail / Math.max(...pages.map((p) => p.w)));
      list.replaceChildren(...pages.map((p, i) => h("div", { class: "of-pg", style: `width:${p.w * z}px;height:${p.h * z}px` },
        h("img", { loading: "lazy", alt: `Page ${i + 1}`, src: `/api/pdf/page?path=${encodeURIComponent(pdfPath)}&page=${i}&zoom=${Math.min(3, z * (devicePixelRatio || 1)).toFixed(2)}` }),
        h("span", {}, `${i + 1} / ${pages.length}`))));
      V.zoomLabel.textContent = zoom ? Math.round(zoom * 100) + "%" : "fit";
    };
    V.zoomLabel = h("span", { class: "sm muted", style: "min-width:34px;text-align:center" });
    V.zoomBtns = [tb("−", "Zoom out", () => { zoom = Math.max(0.3, (zoom || 1) / 1.2); draw(); }, { keep: false }), V.zoomLabel,
      tb("+", "Zoom in", () => { zoom = Math.min(4, (zoom || 1) * 1.2); draw(); }, { keep: false }), tb("↔", "Fit width", () => { zoom = 0; draw(); }, { keep: false })];
    V.onShow = () => requestAnimationFrame(draw);
    V.printPages = () => doPrint(async () => {
      const imgs = $$("img", list); imgs.forEach((i) => (i.loading = "eager"));
      await Promise.race([Promise.all(imgs.map((i) => i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; }))), new Promise((r) => setTimeout(r, 15000))]);
      return null;
    });
    return stage;
  }

  function SlidesView(d) {
    const V = { kind: "slides", dirty: () => false };
    let stage, tools;
    if (d.mode === "pdf") {
      stage = pagesView(V, d.pdf, d.pages);
      tools = [tb(ico("open"), "Open another file", pickAndOpen, { keep: false }),
        tb("⇩ PDF", "Save these slides as a PDF in the output folder", async () => {
          try { const r = await api("/api/office/export_copy", { path: d.pdf, name: O.file.name.replace(/\.[^.]+$/, ""), out_dir: S.outDir }); savedToast(r.path, "PDF ready"); } catch (e) { fail(e); }
        }, { keep: false }),
        tb(ico("print"), "Print", () => V.printPages(), { keep: false }), sep(), ...V.zoomBtns,
        h("span", { class: "of-hint" }, `${d.pages.length} slides · read-only (rendered by PowerPoint)`)];
    } else {
      stage = h("div", { class: "of-stage" }, h("div", { class: "of-pages" }, ...d.slides.map((s) => h("div", { class: "of-slide" },
        h("span", { class: "n" }, `${s.n} / ${d.slides.length}`), h("h3", {}, s.title), ...s.paras.map((p) => h("p", {}, p)), ...s.images.map((src) => h("img", { src, alt: "" }))))));
      tools = [tb(ico("open"), "Open another file", pickAndOpen, { keep: false }), tb(ico("print"), "Print", () => doPrint(), { keep: false }), h("span", { class: "of-hint" }, d.note || "Read-only")];
    }
    chrome(V, [h("div", { class: "of-tools", role: "toolbar", "aria-label": "Slides" }, ...tools)], h("div", { class: "of-main" }, stage), h("div", { class: "of-status" }, "Slides are view-only here. To change them, open the file in PowerPoint."));
    return V;
  }

  function PdfView(d) {
    const V = { kind: "pdf", dirty: () => false };
    const file = { ...O.file };
    const stage = pagesView(V, d.path, d.pages);
    const tools = h("div", { class: "of-tools", role: "toolbar", "aria-label": "PDF" },
      tb(ico("open"), "Open another file", pickAndOpen, { keep: false }),
      h("button", { class: "btn sm", title: "Edit text, draw and annotate in the PDF editor", onclick: () => {
        if (window.App.route) window.App.route("editor"); else document.querySelector('#nav a[data-view="editor"]')?.click();
        window.Editor?.openFile(file);
      } }, "✎ Edit in PDF editor"),
      tb(ico("print"), "Print", () => V.printPages(), { keep: false }), sep(), ...V.zoomBtns,
      h("span", { class: "of-hint" }, `${d.pages.length} page${d.pages.length > 1 ? "s" : ""}`));
    chrome(V, [tools], h("div", { class: "of-main" }, stage), h("div", { class: "of-status" }, "PDFs open read-only here. Use “Edit in PDF editor” to change them."));
    return V;
  }

  window.Office = { mount, openFile, get dirty() { return isDirty(); } };

  // Debug / deep-link hook: #office=<path>[&cell=B12] opens that file on the Docs & sheets screen.
  const hm = decodeURIComponent(location.hash || "").match(/^#office=([^&]+)(?:&cell=([A-Z]+)(\d+))?/i);
  if (hm) {
    const th = location.hash.match(/[&#]theme=(light|dark)/);
    if (th) document.documentElement.dataset.theme = th[1];
    const go = async () => {
      if (!S.caps) return setTimeout(go, 100);
      if (window.App.route) window.App.route("office"); else document.querySelector('#nav a[data-view="office"]')?.click();
      try {
        const r = await api("/api/fileinfo", { paths: [hm[1]] });
        if (!r.files.length) throw new Error("No file at " + hm[1]);
        await openFile(r.files[0]);
        if (hm[2] && O.view?.select) setTimeout(() => O.view.select(+hm[3] - 1, colIndex(hm[2])), 400);
      } catch (e) { fail(e); }
    };
    go();
  }
})();
