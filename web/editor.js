/* Visual PDF editor: edit existing text, add text, shapes, arrows, freehand, highlight, whiteout, images.
   All edit coordinates are PDF points in the page's displayed orientation. */
(function () {
  const { $, h, api, toast, fail, S, pickFiles, mascotImg, titlebar } = window.App;
  const PALETTE = ["#111111", "#ffffff", "#e5484d", "#f6a9c9", "#ff9f6e", "#ffe3a3", "#7bd3a6", "#a9e7cf", "#5b8def", "#a8c8ff", "#8d8ff2", "#cdb8ff", "#3f3e6e"];
  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs) => { const el = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v); return el; };
  const FAMILY_CSS = { sans: "Arial, Helvetica, sans-serif", serif: "'Times New Roman', Times, serif", mono: "'Courier New', monospace" };

  const E = {
    file: null, pages: [], page: 0, zoom: 1, edits: [], undo: [], mode: "edittext", sel: -1, lines: {},
    style: { color: "#111111", fill: "none", width: 2, size: 14, family: "sans", bold: false },
    saving: null, root: null,
  };
  const TOOLS = [
    ["select", "⬚", "Select / move", "Click an item to select, drag to move, Delete to remove"],
    ["edittext", "✎", "Edit text", "Click any existing text to rewrite it"],
    ["text", "T", "Add text", "Click where the text should go"],
    ["whiteout", "▭", "Whiteout", "Drag to cover something with a solid box"],
    ["highlight", "▬", "Highlight", "Drag over text to highlight"],
    ["rect", "□", "Rectangle", "Drag to draw"],
    ["ellipse", "○", "Ellipse", "Drag to draw"],
    ["line", "╱", "Line", "Drag to draw"],
    ["arrow", "➚", "Arrow", "Drag from tail to head"],
    ["pen", "✐", "Freehand", "Draw freely"],
    ["image", "▣", "Image", "Click where to place an image or signature"],
  ];

  function snapshot() { E.undo.push(JSON.stringify(E.edits)); if (E.undo.length > 100) E.undo.shift(); }
  function pageEdits() { return E.edits.map((e, i) => [e, i]).filter(([e]) => e.page === E.page); }

  // ------------------------------------------------------------ mount / open
  function mount(container) {
    E.root = container;
    if (!E.file) {
      container.replaceChildren(h("div", { class: "ed-empty" }, h("div", { class: "win" }, titlebar("paint.exe — no file open"),
        h("div", { class: "ed-empty-body" },
          mascotImg("float"),
          h("h2", {}, "edit any pdf ✎"),
          h("p", { class: "muted" }, "Rewrite existing text, add text boxes, draw diagrams (boxes, circles, arrows, lines, freehand), highlight, white-out, and drop in images or signatures. Your original is never modified."),
          h("button", { class: "btn big", onclick: async () => { try { const f = (await pickFiles()).find((x) => x.ext === "pdf"); if (f) openFile(f); else toast("Pick a PDF file", true); } catch (e) { fail(e); } } }, "📂 Open PDF"),
          h("p", { class: "muted sm" }, "or drop a PDF anywhere on this page")))));
      return;
    }
    render();
  }

  async function openFile(f) {
    if (!f) return toast("That's not a PDF", true);
    try {
      const d = await api("/api/pdf/info?path=" + encodeURIComponent(f.path));
      Object.assign(E, { file: f, pages: d.pages, page: 0, edits: [], undo: [], sel: -1, lines: {}, zoom: 0 });
      render();
    } catch (e) { fail(e); }
  }

  // ------------------------------------------------------------ layout
  function render() {
    const c = E.root;
    if (!E.zoom) {  // fit page width: view width − thumbnails column − gaps/padding/scrollbar
      const avail = c.clientWidth - 150 - 16 - 76;
      E.zoom = Math.max(0.5, Math.min(2.2, avail / E.pages[E.page].w));
    }
    const tb = toolbar();
    const thumbs = h("div", { class: "ed-thumbs" }, ...E.pages.map((p, i) => {
      const img = h("img", { loading: "lazy", src: `/api/pdf/page?path=${encodeURIComponent(E.file.path)}&page=${i}&zoom=${(130 / p.w).toFixed(3)}` });
      return h("div", { class: "ed-thumb" + (i === E.page ? " on" : ""), onclick: () => goto(i) }, img,
        h("div", {}, `Page ${i + 1}`, E.edits.some((e) => e.page === i) ? h("span", { class: "dotmark", title: "Has edits" }) : null));
    }));
    const wrap = h("div", { class: "ed-stage-wrap" });
    c.replaceChildren(h("div", { class: "ed" }, thumbs, h("div", { class: "ed-main" }, tb, wrap)));
    wrap.append(stage());
  }

  function goto(i) { E.page = i; E.sel = -1; render(); }

  function toolbar() {
    const s = E.style;
    const color = h("input", { type: "color", value: s.color, title: "Colour (text & lines)" });
    color.oninput = () => { s.color = color.value; applyToSel({ color: s.color, stroke: s.color }); };
    const fillOn = h("input", { type: "checkbox", title: "Fill shapes" }); fillOn.checked = s.fill !== "none";
    const fill = h("input", { type: "color", value: s.fill === "none" ? "#ffeb3b" : s.fill, title: "Fill colour" });
    const syncFill = () => { s.fill = fillOn.checked ? fill.value : "none"; applyToSel({ fill: s.fill }); };
    fillOn.onchange = syncFill; fill.oninput = () => { fillOn.checked = true; syncFill(); };
    const width = h("input", { type: "number", min: 0.5, max: 30, step: 0.5, value: s.width, title: "Line width" });
    width.onchange = () => { s.width = +width.value; applyToSel({ width: s.width }); };
    const size = h("input", { type: "number", min: 4, max: 200, value: s.size, title: "Font size" });
    size.onchange = () => { s.size = +size.value; applyToSel({ size: s.size }); };
    const fam = h("select", { title: "Font" }, ...[["sans", "Sans"], ["serif", "Serif"], ["mono", "Mono"]].map(([v, l]) => h("option", { value: v, selected: v === s.family }, l)));
    fam.onchange = () => { s.family = fam.value; applyToSel({ family: s.family }); };
    const bold = h("button", { class: "tb" + (s.bold ? " on" : ""), title: "Bold", style: "font-weight:800" }, "B");
    bold.onclick = () => { s.bold = !s.bold; bold.classList.toggle("on", s.bold); applyToSel({ bold: s.bold }); };
    const hint = TOOLS.find((t) => t[0] === E.mode)?.[3] || "";
    const palette = h("div", { class: "palette" }, h("span", { class: "sm muted" }, "colours"),
      ...PALETTE.map((c) => h("button", { class: "swatch" + (c === s.color ? " on" : ""), style: `background:${c}`, title: c,
        onclick: () => { s.color = c; color.value = c; applyToSel({ color: c, stroke: c }); render(); } })),
      h("span", { class: "hint" }, hint));
    return h("div", { class: "ed-paint win" }, titlebar("paint.exe — " + E.file.name), bar(), palette);
    function bar() { return h("div", { class: "ed-toolbar" },
      h("button", { class: "tb", title: "Open another PDF", onclick: async () => { const f = (await pickFiles().catch(fail) || []).find((x) => x.ext === "pdf"); if (f) openFile(f); } }, "📂"),
      h("span", { class: "sep" }),
      ...TOOLS.map(([id, ico, label], n) => h("button", { class: "tb" + (E.mode === id ? " on" : ""), title: label, onclick: () => { E.mode = id; E.sel = -1; render(); } },
        ico, n < 3 ? h("span", { class: "sm" }, label) : null)),
      h("span", { class: "sep" }),
      color, h("label", { class: "tb", title: "Fill shapes" }, fillOn, fill), h("span", { class: "sm muted" }, "W"), width,
      h("span", { class: "sm muted" }, "Size"), size, fam, bold,
      h("span", { class: "sep" }),
      h("button", { class: "tb", title: "Undo (Ctrl+Z)", onclick: doUndo }, "↶"),
      h("button", { class: "tb", title: "Zoom out", onclick: () => { E.zoom = Math.max(0.3, E.zoom / 1.2); render(); } }, "−"),
      h("span", { class: "sm muted" }, Math.round(E.zoom * 100) + "%"),
      h("button", { class: "tb", title: "Zoom in", onclick: () => { E.zoom = Math.min(5, E.zoom * 1.2); render(); } }, "+"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn", disabled: !E.edits.length || !!E.saving, onclick: save }, E.saving ? "Saving…" : `💾 Save copy (${E.edits.length} edit${E.edits.length === 1 ? "" : "s"})`)); }
  }

  function applyToSel(patch) {
    if (E.sel < 0) return;
    const e = E.edits[E.sel];
    snapshot();
    for (const [k, v] of Object.entries(patch)) {
      if (k in e || (k === "fill" && ["rect", "ellipse"].includes(e.type)) || (k === "color" && e.type === "text")) {
        if (k === "color" && e.type !== "text") continue;
        if (k === "stroke" && !("stroke" in e)) continue;
        e[k] = v;
      }
    }
    drawOverlay();
  }

  // ------------------------------------------------------------ stage
  let stageEl, svgEl, layerEl;
  function stage() {
    const p = E.pages[E.page], z = E.zoom;
    const dpr = Math.min(3, (window.devicePixelRatio || 1) * z);
    stageEl = h("div", { class: "ed-stage mode-" + E.mode, style: `width:${p.w * z}px;height:${p.h * z}px` },
      h("img", { class: "pg", src: `/api/pdf/page?path=${encodeURIComponent(E.file.path)}&page=${E.page}&zoom=${dpr.toFixed(3)}`, draggable: "false" }));
    svgEl = sv("svg", { viewBox: `0 0 ${p.w} ${p.h}`, preserveAspectRatio: "none" });
    layerEl = h("div", { class: "ed-layer" });
    stageEl.append(svgEl, layerEl);
    stageEl.addEventListener("pointerdown", onDown);
    loadLines().then(drawOverlay);
    drawOverlay();
    return stageEl;
  }

  async function loadLines() {
    if (E.lines[E.page]) return;
    try { E.lines[E.page] = (await api(`/api/pdf/text?path=${encodeURIComponent(E.file.path)}&page=${E.page}`)).lines; } catch (e) { E.lines[E.page] = []; }
  }

  const pt = (ev) => { const r = stageEl.getBoundingClientRect(); return [(ev.clientX - r.left) / E.zoom, (ev.clientY - r.top) / E.zoom]; };
  const px = (v) => v * E.zoom + "px";

  function drawOverlay() {
    if (!svgEl) return;
    svgEl.replaceChildren();
    layerEl.replaceChildren();
    const z = E.zoom;
    // existing text lines (click targets for "Edit text")
    const replaced = new Map(E.edits.filter((e) => e.type === "replace" && e.page === E.page).map((e) => [e.ubbox.join(","), e]));
    for (const ln of E.lines[E.page] || []) {
      const key = ln.ubbox.join(",");
      if (replaced.has(key)) continue;
      const [x0, y0, x1, y1] = ln.bbox;
      const box = h("div", { class: "ed-line", style: `left:${px(x0)};top:${px(y0)};width:${px(x1 - x0)};height:${px(y1 - y0)}`, title: "Click to edit" });
      box.addEventListener("pointerdown", (ev) => { if (E.mode === "edittext") { ev.stopPropagation(); editLine(ln); } });
      layerEl.append(box);
    }
    for (const [e, i] of pageEdits()) {
      const sel = i === E.sel;
      const common = { "data-idx": i, class: sel ? "ed-shape-sel" : null, style: "cursor:move" };
      if (e.type === "replace") {
        const [x0, y0, x1, y1] = e.bbox;
        const div = h("div", { class: "ed-replaced", "data-idx": i, style: `left:${px(x0 - 0.5)};top:${px(y0 - 0.5)};min-width:${px(x1 - x0 + 1)};height:${px(y1 - y0 + 1)};font-size:${px(e.size)};line-height:${px(y1 - y0 + 1)};color:${e.color};font-family:${FAMILY_CSS[e.family]};font-weight:${e.bold ? 700 : 400};pointer-events:${E.mode === "edittext" ? "auto" : "none"};cursor:text` }, e.text);
        div.addEventListener("pointerdown", (ev) => { if (E.mode === "edittext") { ev.stopPropagation(); editLine(e._line || { ...e, text: e.text }, e); } });
        layerEl.append(div);
      } else if (e.type === "text") {
        layerEl.append(h("div", { class: "ed-text" + (sel ? " sel" : ""), "data-idx": i, style: `left:${px(e.x)};top:${px(e.y)};font-size:${px(e.size)};color:${e.color};font-family:${FAMILY_CSS[e.family]};font-weight:${e.bold ? 700 : 400}` }, e.text));
      } else if (e.type === "image") {
        const [x0, y0, x1, y1] = e.rect;
        const div = h("div", { class: "ed-img" + (sel ? " ed-shape-sel" : ""), "data-idx": i, style: `left:${px(x0)};top:${px(y0)};width:${px(x1 - x0)};height:${px(y1 - y0)}` }, h("img", { src: e.data }));
        if (sel) div.append(h("div", { class: "handle", "data-handle": i }));
        layerEl.append(div);
      } else if (["rect", "whiteout", "highlight", "ellipse"].includes(e.type)) {
        const [x0, y0, x1, y1] = e.rect;
        const attrs = { ...common, "pointer-events": "all" };
        let fill = e.fill || "none", stroke = e.stroke || "none", sw = e.width || 0, op = 1;
        if (e.type === "whiteout") { stroke = "none"; fill = e.fill || "#ffffff"; }
        if (e.type === "highlight") { stroke = "none"; fill = e.fill || "#ffeb3b"; op = 0.4; }
        const el = e.type === "ellipse"
          ? sv("ellipse", { ...attrs, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, rx: Math.abs(x1 - x0) / 2, ry: Math.abs(y1 - y0) / 2 })
          : sv("rect", { ...attrs, x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0) });
        el.setAttribute("fill", fill); el.setAttribute("stroke", stroke); el.setAttribute("stroke-width", sw); el.setAttribute("fill-opacity", op);
        if (e.type === "highlight") el.style.mixBlendMode = "multiply";
        if (sel) { el.setAttribute("stroke-dasharray", "4 3"); if (stroke === "none") { el.setAttribute("stroke", "#5b5bf7"); el.setAttribute("stroke-width", 1); } }
        svgEl.append(el);
      } else if (e.type === "line" || e.type === "arrow") {
        const g = sv("g", common);
        g.append(sv("line", { x1: e.p1[0], y1: e.p1[1], x2: e.p2[0], y2: e.p2[1], stroke: e.stroke, "stroke-width": e.width, "stroke-linecap": "round" }));
        if (e.type === "arrow") {
          const ang = Math.atan2(e.p2[1] - e.p1[1], e.p2[0] - e.p1[0]), head = Math.max(8, e.width * 4);
          for (const da of [Math.PI * 0.85, -Math.PI * 0.85]) {
            g.append(sv("line", { x1: e.p2[0], y1: e.p2[1], x2: e.p2[0] + head * Math.cos(ang + da), y2: e.p2[1] + head * Math.sin(ang + da), stroke: e.stroke, "stroke-width": e.width, "stroke-linecap": "round" }));
          }
        }
        g.append(sv("line", { x1: e.p1[0], y1: e.p1[1], x2: e.p2[0], y2: e.p2[1], stroke: "transparent", "stroke-width": 12, "pointer-events": "stroke" }));
        if (sel) g.setAttribute("opacity", 0.6);
        svgEl.append(g);
      } else if (e.type === "pen") {
        const pts = e.points.map((p) => p.join(",")).join(" ");
        const g = sv("g", common);
        g.append(sv("polyline", { points: pts, fill: "none", stroke: e.stroke, "stroke-width": e.width, "stroke-linecap": "round", "stroke-linejoin": "round" }));
        g.append(sv("polyline", { points: pts, fill: "none", stroke: "transparent", "stroke-width": 12, "pointer-events": "stroke" }));
        if (sel) g.setAttribute("opacity", 0.6);
        svgEl.append(g);
      }
    }
    // only the select tool interacts with drawn items
    for (const el of [...svgEl.querySelectorAll("[data-idx]"), ...layerEl.querySelectorAll(".ed-text,.ed-img")]) {
      el.style.pointerEvents = E.mode === "select" ? "" : "none";
    }
    svgEl.style.pointerEvents = E.mode === "select" ? "" : "none";
  }

  // ------------------------------------------------------------ text inputs
  function openInput({ x, y, w, hgt, size, family, bold, color, value, multiline }, onCommit) {
    const z = E.zoom;
    const inp = h(multiline ? "textarea" : "input", { class: "ed-input", style:
      `left:${px(x)};top:${px(y)};min-width:${px(Math.max(w || 0, 60))};height:${hgt ? px(hgt) : "auto"};font-size:${size * z}px;font-family:${FAMILY_CSS[family]};font-weight:${bold ? 700 : 400};color:${color}` });
    inp.value = value || "";
    if (multiline) {
      inp.rows = Math.max(1, inp.value.split("\n").length);
      inp.oninput = () => { inp.rows = Math.max(1, inp.value.split("\n").length); inp.style.width = "auto"; inp.style.width = inp.scrollWidth + 4 + "px"; };
    } else {
      inp.oninput = () => { inp.style.width = "auto"; inp.style.width = Math.max(inp.scrollWidth + 6, (w || 0) * z) + "px"; };
    }
    let done = false;
    const finish = (commit) => { if (done) return; done = true; inp.remove(); if (commit) onCommit(inp.value); };
    inp.onkeydown = (ev) => {
      ev.stopPropagation();
      if (ev.key === "Escape") finish(false);
      if (ev.key === "Enter" && (!multiline || ev.ctrlKey)) { ev.preventDefault(); finish(true); }
    };
    inp.onblur = () => finish(true);
    inp.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    stageEl.append(inp);
    setTimeout(() => { inp.focus(); inp.oninput(); if (!multiline) inp.select(); }, 0);
  }

  function editLine(ln, existing) {
    const [x0, y0, x1, y1] = ln.bbox;
    openInput({ x: x0 - 1, y: y0 - 1, w: x1 - x0 + 2, hgt: y1 - y0 + 2, size: ln.size, family: ln.family, bold: ln.bold, color: ln.color, value: existing ? existing.text : ln.text }, (val) => {
      if (!existing && val === ln.text) return;
      snapshot();
      if (existing) { existing.text = val; }
      else E.edits.push({ type: "replace", page: E.page, ubbox: ln.ubbox, uorigin: ln.uorigin, bbox: ln.bbox, text: val, size: ln.size, color: ln.color, family: ln.family, bold: ln.bold, _line: ln });
      refresh();
    });
  }

  function addTextAt(x, y, existing) {
    const s = existing || E.style;
    openInput({ x, y, size: s.size, family: s.family, bold: s.bold, color: existing ? existing.color : s.color, value: existing?.text || "", multiline: true }, (val) => {
      if (existing) {
        snapshot();
        if (!val.trim()) E.edits.splice(E.edits.indexOf(existing), 1); else existing.text = val;
      } else if (val.trim()) {
        snapshot();
        E.edits.push({ type: "text", page: E.page, x, y, text: val, size: s.size, color: s.color, family: s.family, bold: s.bold });
      }
      refresh();
    });
  }

  function refresh() { E.sel = Math.min(E.sel, E.edits.length - 1); const scroll = $(".ed-stage-wrap", E.root)?.scrollTop; render(); const w = $(".ed-stage-wrap", E.root); if (w) w.scrollTop = scroll; }

  // ------------------------------------------------------------ pointer handling
  function onDown(ev) {
    if (ev.button !== 0) return;
    const [x, y] = pt(ev);
    const s = E.style;
    if (E.mode === "select") return selectDown(ev, x, y);
    if (E.mode === "text") { ev.preventDefault(); return addTextAt(x, y); }
    if (E.mode === "image") return placeImage(x, y);
    if (E.mode === "edittext") return;
    ev.preventDefault();
    stageEl.setPointerCapture(ev.pointerId);
    let e;
    if (["rect", "ellipse", "whiteout", "highlight"].includes(E.mode)) {
      e = { type: E.mode, page: E.page, rect: [x, y, x, y], stroke: s.color, fill: E.mode === "whiteout" ? "#ffffff" : E.mode === "highlight" ? (s.fill !== "none" ? s.fill : "#ffeb3b") : s.fill, width: s.width };
    } else if (E.mode === "line" || E.mode === "arrow") {
      e = { type: E.mode, page: E.page, p1: [x, y], p2: [x, y], stroke: s.color, width: s.width };
    } else if (E.mode === "pen") {
      e = { type: "pen", page: E.page, points: [[x, y]], stroke: s.color, width: s.width };
    }
    if (!e) return;
    snapshot();
    E.edits.push(e);
    const move = (mv) => {
      const [mx, my] = pt(mv);
      if (e.rect) e.rect = [x, y, mx, my];
      else if (e.p2) e.p2 = [mx, my];
      else { const last = e.points[e.points.length - 1]; if (Math.hypot(mx - last[0], my - last[1]) > 1.2 / E.zoom) e.points.push([mx, my]); }
      drawOverlay();
    };
    const up = () => {
      stageEl.removeEventListener("pointermove", move); stageEl.removeEventListener("pointerup", up);
      if (e.rect) { const [a, b, c, d] = e.rect; e.rect = [Math.min(a, c), Math.min(b, d), Math.max(a, c), Math.max(b, d)]; if (e.rect[2] - e.rect[0] < 2 && e.rect[3] - e.rect[1] < 2) E.edits.pop(); }
      if (e.p2 && Math.hypot(e.p2[0] - e.p1[0], e.p2[1] - e.p1[1]) < 2) E.edits.pop();
      if (e.points && e.points.length < 2) E.edits.pop();
      refresh();
    };
    stageEl.addEventListener("pointermove", move); stageEl.addEventListener("pointerup", up);
  }

  function selectDown(ev, x, y) {
    const handle = ev.target.closest("[data-handle]");
    const target = ev.target.closest("[data-idx]");
    if (!target) { E.sel = -1; drawOverlay(); return; }
    const i = +target.dataset.idx, e = E.edits[i];
    if (e.type === "replace") return;
    if (ev.detail === 2 && e.type === "text") { E.sel = -1; return addTextAt(e.x, e.y, e); }
    E.sel = i;
    ev.preventDefault();
    stageEl.setPointerCapture(ev.pointerId);
    let lx = x, ly = y, moved = false;
    const move = (mv) => {
      const [mx, my] = pt(mv), dx = mx - lx, dy = my - ly;
      if (!moved) { snapshot(); moved = true; }
      lx = mx; ly = my;
      if (handle && e.rect) { e.rect[2] += dx; e.rect[3] += dy; }
      else if (e.rect) e.rect = [e.rect[0] + dx, e.rect[1] + dy, e.rect[2] + dx, e.rect[3] + dy];
      else if (e.p1) { e.p1 = [e.p1[0] + dx, e.p1[1] + dy]; e.p2 = [e.p2[0] + dx, e.p2[1] + dy]; }
      else if (e.points) e.points = e.points.map(([a, b]) => [a + dx, b + dy]);
      else if ("x" in e) { e.x += dx; e.y += dy; }
      drawOverlay();
    };
    const up = () => { stageEl.removeEventListener("pointermove", move); stageEl.removeEventListener("pointerup", up); refresh(); };
    stageEl.addEventListener("pointermove", move); stageEl.addEventListener("pointerup", up);
    drawOverlay();
  }

  function placeImage(x, y) {
    const inp = h("input", { type: "file", accept: "image/*" });
    inp.onchange = () => {
      const f = inp.files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        const img = new Image();
        img.onload = () => {
          const maxW = 220, k = Math.min(1, maxW / img.width);
          const w = img.width * k, hh = img.height * k;
          snapshot();
          E.edits.push({ type: "image", page: E.page, rect: [x, y, x + w, y + hh], data: rd.result });
          E.mode = "select"; E.sel = E.edits.length - 1;
          refresh();
          toast("Drag to move, drag the corner square to resize");
        };
        img.src = rd.result;
      };
      rd.readAsDataURL(f);
    };
    inp.click();
  }

  function doUndo() { if (!E.undo.length) return; E.edits = JSON.parse(E.undo.pop()); E.sel = -1; refresh(); }

  addEventListener("keydown", (ev) => {
    if (S.view !== "editor" || !E.file || ev.target.matches("input,textarea,select")) return;
    if ((ev.key === "Delete" || ev.key === "Backspace") && E.sel >= 0) { snapshot(); E.edits.splice(E.sel, 1); E.sel = -1; refresh(); ev.preventDefault(); }
    else if (ev.key === "z" && (ev.ctrlKey || ev.metaKey)) { doUndo(); ev.preventDefault(); }
    else if (ev.key === "PageDown" || (ev.key === "ArrowRight" && ev.altKey)) { if (E.page < E.pages.length - 1) goto(E.page + 1); }
    else if (ev.key === "PageUp" || (ev.key === "ArrowLeft" && ev.altKey)) { if (E.page > 0) goto(E.page - 1); }
  });

  // ------------------------------------------------------------ save
  async function save() {
    const edits = E.edits.map(({ _line, ...e }) => e);
    try {
      const d = await api("/api/pdf/save", { path: E.file.path, edits, out_dir: S.outDir });
      E.saving = d.job.id; render(); window.App.watchJobs();
    } catch (e) { fail(e); }
  }

  function onJobDone(j) {
    if (j.id !== E.saving) return;
    E.saving = null;
    if (j.status === "done" && j.outputs[0]) {
      toast("Saved: " + j.outputs[0].split(/[\\/]/).pop());
      api("/api/open", { path: j.outputs[0] }).catch(() => {});
    }
    if (S.view === "editor") render();
  }

  window.Editor = { mount, openFile, onJobDone };
})();
