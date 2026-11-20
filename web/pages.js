/* "Organize pages": open a PDF, see every page as a thumbnail, then remove, rotate, reorder,
   or add pages anywhere: from other PDFs, from pictures, or blank. Saves a new PDF; the
   original is never touched. Used by the PDF tools card with id "pdf_organize". */
(function () {
  const { $, h, api, toast, fail, ask, S, pickFiles, titlebar } = window.App;
  const IMAGES = ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "tif", "heic", "heif", "avif", "tga", "ico"];
  const st = { base: null, pages: [], sel: new Set(), anchor: null, undo: [], redo: [], name: "", dirty: false, root: null, focus: null };
  let nextId = 1;
  const page = (o) => ({ id: nextId++, rotate: 0, ...o });
  const thumb = (p, size = 260) => `/api/organize/thumb?size=${size}&page=${p.page || 0}&path=${encodeURIComponent(p.path)}`;
  const stem = (name) => name.replace(/\.[^.]+$/, "");

  // ------------------------------------------------------------ history
  const snap = () => JSON.stringify(st.pages);
  function change(fn) {
    st.undo.push(snap()); if (st.undo.length > 200) st.undo.shift();
    st.redo = [];
    fn();
    st.dirty = true;
    draw();
  }
  function undo() { if (!st.undo.length) return; st.redo.push(snap()); st.pages = JSON.parse(st.undo.pop()); st.sel.clear(); st.dirty = true; draw(); }
  function redo() { if (!st.redo.length) return; st.undo.push(snap()); st.pages = JSON.parse(st.redo.pop()); st.sel.clear(); st.dirty = true; draw(); }

  // ------------------------------------------------------------ loading
  async function pdfPages(f) {
    const info = await api("/api/pdf/info?path=" + encodeURIComponent(f.path));  // explains locked / damaged files
    return info.pages.map((sz, i) => page({ kind: "pdf", path: f.path, page: i, w: sz.w, h: sz.h, src: f.name, of: info.count }));
  }

  async function open(f) {
    if (st.dirty && !(await ask("Open another PDF? Your changes to this one haven't been saved.", { yes: "Open", no: "Keep editing" }))) return;
    try {
      const pages = await pdfPages(f);
      Object.assign(st, { base: f, pages, sel: new Set(), anchor: null, undo: [], redo: [], name: stem(f.name) + " (edited)", dirty: false, focus: null });
      draw();
    } catch (e) { fail(e); }
  }

  /** Where new pages go: after the last selected page, else at the end. */
  const insertIndex = () => {
    if (!st.sel.size) return st.pages.length;
    return Math.max(...st.pages.map((p, i) => (st.sel.has(p.id) ? i : -1))) + 1;
  };
  const sizeNear = (at) => { const p = st.pages[Math.max(0, Math.min(at - 1, st.pages.length - 1))]; return p ? { w: p.w, h: p.h } : { w: 595, h: 842 }; };

  async function addFiles(files, at = insertIndex()) {
    const added = [], skipped = [];
    for (const f of files) {
      try {
        if (f.ext === "pdf") added.push(...(await pdfPages(f)));
        else if (IMAGES.includes(f.ext)) added.push(page({ kind: "image", path: f.path, ...sizeNear(at), src: f.name }));
        else skipped.push(f.name);
      } catch (e) { fail(e); }
    }
    if (skipped.length) toast(`Skipped ${skipped.length} file(s): only PDFs and pictures can be added. Convert other files to PDF first.`, true, 6000);
    if (!added.length) return;
    change(() => { st.pages.splice(at, 0, ...added); st.sel = new Set(added.map((p) => p.id)); });
    toast(`Added ${added.length} page${added.length > 1 ? "s" : ""} at position ${at + 1}`);
  }
  async function pickAndAdd(at) { try { const fs = await pickFiles(); if (fs.length) await addFiles(fs, at); } catch (e) { fail(e); } }
  function addBlank(at = insertIndex()) {
    const p = page({ kind: "blank", ...sizeNear(at) });
    change(() => { st.pages.splice(at, 0, p); st.sel = new Set([p.id]); });
  }

  // ------------------------------------------------------------ editing
  const targets = (id) => (id != null && !st.sel.has(id) ? [id] : [...st.sel]);
  function remove(id) {
    const ids = new Set(targets(id));
    if (!ids.size) return toast("Select the pages to remove first (click them).");
    change(() => { st.pages = st.pages.filter((p) => !ids.has(p.id)); ids.forEach((x) => st.sel.delete(x)); });
  }
  function rotate(id, by = 90) {
    const ids = new Set(targets(id));
    if (!ids.size) return toast("Select the pages to rotate first (click them).");
    change(() => st.pages.forEach((p) => { if (ids.has(p.id)) p.rotate = (p.rotate + by + 360) % 360; }));
  }
  /** Move a page (or the whole selection it belongs to) to before index `to`. */
  function move(id, to) {
    const ids = st.sel.has(id) ? st.sel : new Set([id]);
    const moving = st.pages.filter((p) => ids.has(p.id));
    const before = st.pages.slice(0, to).filter((p) => !ids.has(p.id)).length;
    change(() => { const rest = st.pages.filter((p) => !ids.has(p.id)); rest.splice(before, 0, ...moving); st.pages = rest; });
  }
  function select(id, e) {
    if (e?.shiftKey && st.anchor != null) {
      const a = st.pages.findIndex((p) => p.id === st.anchor), b = st.pages.findIndex((p) => p.id === id);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) st.sel.add(st.pages[i].id);
    } else if (st.sel.has(id)) st.sel.delete(id);
    else st.sel.add(id);
    st.anchor = id;
    draw();
  }

  async function save() {
    if (!st.pages.length) return toast("There are no pages left to save.", true);
    try {
      await api("/api/organize/assemble", {
        pages: st.pages.map(({ kind, path, page: n, rotate: r, w, h: hh }) => ({ kind, path, page: n, rotate: r, w, h: hh })),
        name: st.name || "organized", out_dir: S.outDir,
      });
      st.dirty = false;
      toast(`Saving ${st.pages.length} pages as “${st.name || "organized"}.pdf”…`);
      window.App.openJobs?.(); window.App.watchJobs();
      draw();
    } catch (e) { fail(e); }
  }

  // ------------------------------------------------------------ preview
  function preview(start) {
    let i = start;
    const m = $("#modal"), img = h("img", { class: "org-big", alt: "" }), cap = h("div", { class: "org-cap" });
    const show = () => {
      const p = st.pages[i];
      img.style.transform = `rotate(${p.rotate}deg)`;
      if (p.kind === "blank") { img.removeAttribute("src"); img.style.cssText += `;width:${Math.min(500, p.w)}px;height:${Math.min(700, p.h)}px;background:#fff`; }
      else { img.style.width = img.style.height = ""; img.src = thumb(p, 1400); }
      cap.replaceChildren(h("b", {}, `Page ${i + 1} of ${st.pages.length}`), " · ", label(p));
    };
    const go = (d) => { i = (i + d + st.pages.length) % st.pages.length; show(); };
    const close = () => { m.hidden = true; m.replaceChildren(); removeEventListener("keydown", key); st.root?.querySelector(`[data-id="${st.pages[i]?.id}"]`)?.focus(); };
    const key = (e) => { if (e.key === "Escape") close(); else if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1); };
    const closeBtn = h("button", { class: "tb-x", "aria-label": "Close preview", onclick: close }, "✕");
    m.replaceChildren(h("div", { class: "dialog win org-preview", role: "dialog", "aria-modal": "true", "aria-label": "Page preview" },
      h("div", { class: "titlebar" }, h("span", {}, "page_preview.exe"), closeBtn),
      h("div", { class: "org-stage" }, h("button", { class: "btn ghost org-nav", "aria-label": "Previous page", onclick: () => go(-1) }, "‹"), img,
        h("button", { class: "btn ghost org-nav", "aria-label": "Next page", onclick: () => go(1) }, "›")), cap));
    m.onclick = (e) => { if (e.target === m) close(); };
    m.hidden = false;
    addEventListener("keydown", key);
    show();
    closeBtn.focus();
  }

  const label = (p) => p.kind === "blank" ? "blank page" : p.kind === "image" ? p.src : `${p.src} · p.${p.page + 1}`;

  // ------------------------------------------------------------ drawing
  let dragId = null;
  function card(p, i) {
    const sel = st.sel.has(p.id), fromBase = p.kind === "pdf" && p.path === st.base.path;
    const img = p.kind === "blank" ? h("div", { class: "pg-blank" }, "blank") : h("img", { src: thumb(p), alt: "", loading: "lazy", draggable: "false" });
    // Size the page so that it fits the thumbnail box *after* turning, then turn it.
    const turned = p.rotate % 180 !== 0, BOX_W = 134, BOX_H = 176;
    const k = Math.min(BOX_W / (turned ? p.h : p.w), BOX_H / (turned ? p.w : p.h));
    img.style.width = `${Math.round(p.w * k)}px`;
    img.style.height = `${Math.round(p.h * k)}px`;
    img.style.transform = `rotate(${p.rotate}deg)`;
    const plusAfter = h("button", { class: "pg-plus", title: "Add pages here", "aria-label": `Add pages after page ${i + 1}`, onclick: (e) => { e.stopPropagation(); addMenu(e.currentTarget, i + 1); } }, "+");
    const el = h("div", {
      class: "pg-card" + (sel ? " sel" : "") + (fromBase ? "" : " added"), tabindex: 0, draggable: "true", role: "option",
      "aria-selected": String(sel), "data-id": p.id, "aria-label": `Page ${i + 1}: ${label(p)}${p.rotate ? `, rotated ${p.rotate}°` : ""}`,
      onclick: (e) => select(p.id, e), ondblclick: () => preview(i),
    },
      h("span", { class: "pg-check", "aria-hidden": "true" }, sel ? "✓" : ""),
      h("div", { class: "pg-thumb" }, img),
      h("div", { class: "pg-num" }, String(i + 1)),
      fromBase ? null : h("div", { class: "pg-src", title: label(p) }, p.kind === "blank" ? "new" : "added"),
      h("div", { class: "pg-tools" },
        h("button", { class: "tb", title: "Preview (Enter)", "aria-label": `Preview page ${i + 1}`, onclick: (e) => { e.stopPropagation(); preview(i); } }, "🔍"),
        h("button", { class: "tb", title: "Rotate (R)", "aria-label": `Rotate page ${i + 1}`, onclick: (e) => { e.stopPropagation(); rotate(p.id); } }, "↻"),
        h("button", { class: "tb x", title: "Remove (Delete)", "aria-label": `Remove page ${i + 1}`, onclick: (e) => { e.stopPropagation(); remove(p.id); } }, "✕")),
      plusAfter);
    el.onkeydown = (e) => {
      if (e.target !== el) return;
      const cards = [...st.root.querySelectorAll(".pg-card")], k = cards.indexOf(el);
      if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); st.focus = p.id; move(p.id, e.key === "ArrowLeft" ? Math.max(0, i - 1) : i + 2); }
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); cards[k + 1]?.focus(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); cards[k - 1]?.focus(); }
      else if (e.key === " ") { e.preventDefault(); st.focus = p.id; select(p.id, e); }
      else if (e.key === "Enter") preview(i);
      else if (e.key === "Delete" || e.key === "Backspace") { st.focus = st.pages[i + 1]?.id ?? st.pages[i - 1]?.id; remove(p.id); }
      else if (e.key.toLowerCase() === "r") { st.focus = p.id; rotate(p.id, e.shiftKey ? -90 : 90); }
    };
    el.ondragstart = (e) => { dragId = p.id; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/x-page", String(p.id)); };
    el.ondragend = () => { dragId = null; el.classList.remove("dragging"); st.root.querySelectorAll(".drop-before,.drop-after").forEach((c) => c.classList.remove("drop-before", "drop-after")); };
    el.ondragover = (e) => {
      if (dragId == null) return;
      e.preventDefault();
      const r = el.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
      st.root.querySelectorAll(".drop-before,.drop-after").forEach((c) => c.classList.remove("drop-before", "drop-after"));
      el.classList.add(after ? "drop-after" : "drop-before");
    };
    el.ondrop = (e) => {
      if (dragId == null) return;
      e.preventDefault(); e.stopPropagation();
      const r = el.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
      const id = dragId; dragId = null; st.focus = id;
      move(id, i + (after ? 1 : 0));
    };
    return el;
  }

  function addMenu(anchor, at) {
    st.root.querySelector(".pg-menu")?.remove();
    const close = () => { menu.remove(); removeEventListener("click", outside, true); };
    const outside = (e) => { if (!menu.contains(e.target)) close(); };
    const menu = h("div", { class: "pg-menu win", role: "menu" },
      h("button", { role: "menuitem", onclick: () => { close(); pickAndAdd(at); } }, "📄 Pages from a PDF or pictures…"),
      h("button", { role: "menuitem", onclick: () => { close(); addBlank(at); } }, "▭ A blank page"));
    const r = anchor.getBoundingClientRect(), base = st.root.getBoundingClientRect();
    menu.style.left = `${r.left - base.left - 80}px`; menu.style.top = `${r.bottom - base.top + 6}px`;
    st.root.append(menu);
    menu.querySelector("button").focus();
    menu.onkeydown = (e) => { if (e.key === "Escape") close(); };
    setTimeout(() => addEventListener("click", outside, true));
  }

  function draw() {
    const root = st.root;
    if (!root || !st.base) return;
    // keep keyboard focus on the same page across the rebuild (undo, redo, select…)
    if (st.focus == null && root.contains(document.activeElement)) st.focus = document.activeElement.closest(".pg-card")?.dataset.id ?? null;
    const n = st.pages.length, s = st.sel.size;
    const nameIn = h("input", { type: "text", value: st.name, "aria-label": "Name of the new PDF", class: "pg-name" });
    nameIn.oninput = () => (st.name = nameIn.value);
    root.replaceChildren(
      h("div", { class: "win pg-bar" }, titlebar(`${st.base.name}${st.dirty ? " (unsaved)" : ""}`),
        h("div", { class: "pg-row" },
          h("button", { class: "btn", onclick: () => pickAndAdd(insertIndex()) }, "＋ Add pages"),
          h("button", { class: "btn ghost", onclick: () => addBlank() }, "▭ Blank page"),
          h("span", { class: "pg-sep" }),
          h("button", { class: "btn ghost", disabled: !s, onclick: () => rotate(null, -90), title: "Rotate selected left" }, "↺"),
          h("button", { class: "btn ghost", disabled: !s, onclick: () => rotate(null, 90), title: "Rotate selected right" }, "↻ Rotate"),
          h("button", { class: "btn ghost", disabled: !s, onclick: () => remove(null) }, `✕ Remove${s ? ` (${s})` : ""}`),
          h("span", { class: "pg-sep" }),
          h("button", { class: "btn ghost sm", onclick: () => { st.sel = new Set(st.pages.map((p) => p.id)); draw(); } }, "Select all"),
          h("button", { class: "btn ghost sm", disabled: !s, onclick: () => { st.sel.clear(); draw(); } }, "Clear"),
          h("button", { class: "btn ghost sm", disabled: !st.undo.length, onclick: undo, title: "Undo (Ctrl+Z)" }, "↶ Undo"),
          h("button", { class: "btn ghost sm", disabled: !st.redo.length, onclick: redo, title: "Redo (Ctrl+Y)" }, "↷ Redo"),
          h("span", { class: "spacer" }),
          h("button", { class: "btn ghost sm", onclick: async () => { const f = (await pickFiles().catch(fail) || []).find((x) => x.ext === "pdf"); if (f) open(f); } }, "📂 Open another PDF")),
        h("div", { class: "pg-hint muted sm", "aria-live": "polite" },
          s ? `${s} page${s > 1 ? "s" : ""} selected · new pages go after the last selected one` :
            "Click pages to select them · drag to reorder · hover a page and click ＋ to add pages right there · double-click to preview")),
      h("div", { class: "pg-grid", role: "listbox", "aria-multiselectable": "true", "aria-label": `${n} pages` },
        ...st.pages.map(card),
        h("button", { class: "pg-card pg-add", onclick: (e) => addMenu(e.currentTarget, st.pages.length), "aria-label": "Add pages at the end" }, h("span", {}, "＋"), "Add pages")),
      h("div", { class: "runbar" },
        h("label", { class: "pg-save-name" }, "Save as ", nameIn, ".pdf"),
        h("button", { class: "btn big", disabled: !n, onclick: save }, `Save ${n} page${n === 1 ? "" : "s"} as a new PDF`),
        h("span", { class: "muted sm" }, "Your original is never changed · saved to " + S.outDir)));
    if (st.focus != null) { root.querySelector(`[data-id="${st.focus}"]`)?.focus(); st.focus = null; }
  }

  // Ctrl+Z / Ctrl+Y / Ctrl+A while working in the page grid
  addEventListener("keydown", (e) => {
    if (!st.root?.isConnected || !st.root.contains(document.activeElement) || /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
    else if ((e.ctrlKey || e.metaKey) && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); redo(); }
    else if ((e.ctrlKey || e.metaKey) && k === "a") { e.preventDefault(); st.sel = new Set(st.pages.map((p) => p.id)); draw(); }
  });
  addEventListener("beforeunload", (e) => { if (st.dirty && st.root?.isConnected) { e.preventDefault(); e.returnValue = ""; } });

  /** Called by app.js's tool page. `files` are files the user just added (browse / drop). */
  function render(t, v, files) {
    st.root ||= h("div", { class: "pg-root" });
    const incoming = files.splice(0);
    v.append(st.root);
    if (st.base) v.querySelector(".dropzone")?.remove();  // a document is open: "Add pages" replaces the drop zone
    if (incoming.length) {
      if (!st.base) {
        const first = incoming.find((f) => f.ext === "pdf");
        if (!first) return toast("Start with a PDF; you can add pictures to it afterwards.", true);
        open(first).then(() => { v.querySelector(".dropzone")?.remove(); const rest = incoming.filter((f) => f !== first); if (rest.length) addFiles(rest); });
      } else addFiles(incoming);
    } else draw();
  }

  window.PageOrganizer = { render, open, get state() { return st; } };
})();
