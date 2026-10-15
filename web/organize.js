/* File organiser: big previews you drag into order, rotate, inspect and remove, plus the
   "how many PDFs?" choice — one combined PDF, one per file, or custom groups like 1-3, 4, 5-8. */
(function () {
  const { $, h, api, toast, fail, S, store } = window.App;
  const PREVIEWABLE = ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "tif", "heic", "heif", "avif", "ico", "tga", "pdf", "svg"];
  const GROUP_COLORS = ["var(--pink)", "var(--mint)", "var(--sky)", "var(--butter)", "var(--lilac)", "var(--peach)"];
  const thumbUrl = (f, size = 320, page = 0) => `/api/organize/thumb?size=${size}&page=${page}&path=${encodeURIComponent(f.path)}`;

  /** Fetch page counts / pixel sizes once per file. */
  async function describe(files) {
    const missing = files.filter((f) => !f.info);
    if (!missing.length) return;
    try {
      const r = await api("/api/organize/info", { paths: missing.map((f) => f.path) });
      for (const f of missing) f.info = r.files[f.path] || {};
    } catch { for (const f of missing) f.info = {}; }
  }

  // ------------------------------------------------------------ grouping (mirrors core/organize.py)
  function parseRanges(spec, n) {
    const out = [];
    for (const part of spec.replace(/\s/g, "").split(",")) {
      if (!part) continue;
      const m = part.match(/^(\d*)-(\d*)$/);
      if (m) {
        const a = m[1] ? +m[1] : 1, b = m[2] ? +m[2] : n, step = b >= a ? 1 : -1;
        for (let i = a; step > 0 ? i <= b : i >= b; i += step) if (i >= 1 && i <= n) out.push(i - 1);
      } else if (/^\d+$/.test(part) && +part >= 1 && +part <= n) out.push(+part - 1);
    }
    return out;
  }
  /** -> {groups: [[idx…]…], error} for the current settings. */
  function plan(n, st) {
    if (st.mode === "single") return { groups: n ? [[...Array(n).keys()]] : [] };
    if (st.mode === "each") return { groups: [...Array(n).keys()].map((i) => [i]) };
    const groups = [], used = new Set();
    for (const part of (st.groups || "").replace(/;/g, ",").split(",")) {
      if (!part.trim()) continue;
      const idx = parseRanges(part, n);
      if (!idx.length) return { groups: [], error: `“${part.trim()}” doesn't match any file (there are ${n})` };
      groups.push(idx); idx.forEach((i) => used.add(i));
    }
    if (st.leftovers !== "skip") for (let i = 0; i < n; i++) if (!used.has(i)) groups.push([i]);
    groups.sort((a, b) => Math.min(...a) - Math.min(...b));
    if (!groups.length) return { groups, error: "Type which files go together, e.g. 1-3, 4, 5-8" };
    return { groups };
  }

  // ------------------------------------------------------------ the grid
  /**
   * files: array (reordered in place). opts: {onChange(), groupOf(i) -> group number or null}
   */
  function grid(files, { onChange, groupOf, extra } = {}) {
    describe(files).then(() => files.forEach((f, i) => cards[i]?.refreshMeta()));
    const wrap = h("div", { class: "org-grid", role: "list", "aria-label": "Files in order. Drag, or use Alt+arrow keys, to reorder." });
    const cards = [];
    let dragFrom = -1;
    const move = (from, to) => {
      if (to < 0 || to >= files.length || from === to) return;
      const [m] = files.splice(from, 1); files.splice(to, 0, m);
      onChange?.({ focus: to });
    };
    files.forEach((f, i) => {
      const img = h("img", { alt: "", draggable: "false" });
      const thumb = h("div", { class: "org-thumb" }, h("span", { class: "org-ext" }, f.ext.toUpperCase()));
      if (PREVIEWABLE.includes(f.ext)) {
        img.onload = () => { thumb.replaceChildren(img); img.style.transform = `rotate(${f.rotate || 0}deg)`; };
        img.src = thumbUrl(f, 320);
      }
      const meta = h("div", { class: "org-sub" });
      const g = groupOf?.(i);
      const card = h("div", {
        class: "org-card", role: "listitem", tabindex: 0, draggable: "true",
        "aria-label": `${i + 1}. ${f.name}${g != null ? `, goes in PDF ${g + 1}` : ""}`,
      },
        h("div", { class: "org-num", style: g != null ? `background:${GROUP_COLORS[g % GROUP_COLORS.length]}` : "" }, String(i + 1)),
        g != null ? h("div", { class: "org-group", style: `background:${GROUP_COLORS[g % GROUP_COLORS.length]}` }, `PDF ${g + 1}`) : null,
        thumb,
        h("div", { class: "org-name", title: f.path }, f.name), meta, extra?.(f) || null,
        h("div", { class: "org-actions" },
          h("button", { class: "tb", title: "Preview", "aria-label": `Preview ${f.name}`, onclick: () => preview(files, i) }, "🔍"),
          h("button", { class: "tb", title: "Rotate 90° (R)", "aria-label": `Rotate ${f.name}`, onclick: () => rotate(i) }, "↻"),
          h("button", { class: "tb", title: "Move left (Alt+←)", "aria-label": "Move earlier", disabled: i === 0, onclick: () => move(i, i - 1) }, "◀"),
          h("button", { class: "tb", title: "Move right (Alt+→)", "aria-label": "Move later", disabled: i === files.length - 1, onclick: () => move(i, i + 1) }, "▶"),
          h("button", { class: "tb x", title: "Remove (Delete)", "aria-label": `Remove ${f.name}`, onclick: () => { files.splice(i, 1); onChange?.({ focus: Math.min(i, files.length - 1) }); } }, "✕")));
      card.refreshMeta = () => {
        const inf = f.info || {};
        const bits = [f.size_h];
        if (inf.w) bits.push(`${inf.w}×${inf.h}`);
        if (inf.pages > 1 || f.ext === "pdf") bits.push(`${inf.pages ?? "?"} page${inf.pages === 1 ? "" : "s"}`);
        if (inf.locked) bits.push("🔒 locked");
        meta.replaceChildren(bits.join(" · "));
        if (f.ext === "pdf" && inf.pages > 1 && !card.querySelector(".org-pages")) {
          const pin = h("input", { type: "text", class: "org-pages", value: f.pages || "", placeholder: "all pages", "aria-label": `Pages of ${f.name} to include, e.g. 1-3, 5` });
          pin.oninput = () => (f.pages = pin.value);
          meta.after(h("label", { class: "org-pages-row" }, "Pages ", pin));
        }
      };
      card.refreshMeta();
      const rotate = (k) => { const t = files[k]; t.rotate = ((t.rotate || 0) + 90) % 360; img.style.transform = `rotate(${t.rotate}deg)`; };
      card.ondblclick = () => preview(files, i);
      card.onkeydown = (e) => {
        if (e.target !== card) return;
        if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowUp")) { e.preventDefault(); move(i, i - 1); }
        else if (e.altKey && (e.key === "ArrowRight" || e.key === "ArrowDown")) { e.preventDefault(); move(i, i + 1); }
        else if (e.key === "ArrowRight") cards[i + 1]?.focus();
        else if (e.key === "ArrowLeft") cards[i - 1]?.focus();
        else if (e.key === "Delete" || e.key === "Backspace") { files.splice(i, 1); onChange?.({ focus: Math.min(i, files.length - 1) }); }
        else if (e.key.toLowerCase() === "r") rotate(i);
        else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); preview(files, i); }
      };
      card.ondragstart = (e) => { dragFrom = i; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/x-org", String(i)); };
      card.ondragend = () => { card.classList.remove("dragging"); cards.forEach((c) => c.classList.remove("drop-before", "drop-after")); };
      card.ondragover = (e) => {
        if (dragFrom < 0) return;
        e.preventDefault();
        const r = card.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
        cards.forEach((c) => c.classList.remove("drop-before", "drop-after"));
        card.classList.add(after ? "drop-after" : "drop-before");
      };
      card.ondrop = (e) => {
        if (dragFrom < 0) return;
        e.preventDefault(); e.stopPropagation();
        const r = card.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
        let to = i + (after ? 1 : 0);
        if (dragFrom < to) to--;
        const from = dragFrom; dragFrom = -1;
        move(from, to);
      };
      cards.push(card);
      wrap.append(card);
    });
    wrap.focusCard = (k) => cards[k]?.focus();
    return wrap;
  }

  function toolbar(files, onChange) {
    const sortBy = (fn) => { files.sort(fn); onChange?.({}); };
    const byName = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    return h("div", { class: "org-bar", role: "toolbar", "aria-label": "Arrange files" },
      h("span", { class: "muted sm" }, "Drag to reorder · double-click to preview"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn ghost sm", onclick: () => sortBy(byName) }, "Sort A → Z"),
      h("button", { class: "btn ghost sm", onclick: () => sortBy((a, b) => byName(b, a)) }, "Z → A"),
      h("button", { class: "btn ghost sm", onclick: () => { files.reverse(); onChange?.({}); } }, "Reverse"),
      h("button", { class: "btn ghost sm", onclick: () => { files.forEach((f) => (f.rotate = 0)); onChange?.({}); } }, "Reset rotation"));
  }

  // ------------------------------------------------------------ full-size preview
  function preview(files, start) {
    let i = start, page = 0;
    const m = $("#modal");
    const img = h("img", { class: "org-big", alt: "" });
    const cap = h("div", { class: "org-cap" });
    const show = () => {
      const f = files[i];
      const pages = f.info?.pages || 1;
      cap.replaceChildren(h("b", {}, `${i + 1} / ${files.length} · ${f.name}`),
        f.ext === "pdf" && pages > 1 ? h("span", {}, ` · page ${page + 1} of ${pages} `,
          h("button", { class: "btn ghost sm", disabled: page === 0, onclick: () => { page--; show(); } }, "‹ page"),
          h("button", { class: "btn ghost sm", disabled: page >= pages - 1, onclick: () => { page++; show(); } }, "page ›")) : null);
      if (PREVIEWABLE.includes(f.ext)) { img.hidden = false; img.src = thumbUrl(f, 1400, page); img.style.transform = `rotate(${f.rotate || 0}deg)`; }
      else { img.hidden = true; cap.append(h("p", { class: "muted" }, "No preview for this kind of file — it will be converted to PDF pages when you run.")); }
    };
    const go = (d) => { i = (i + d + files.length) % files.length; page = 0; show(); };
    const close = () => { m.hidden = true; m.replaceChildren(); removeEventListener("keydown", key); };
    const key = (e) => { if (e.key === "Escape") close(); else if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1); };
    const closeBtn = h("button", { class: "tb-x", "aria-label": "Close preview", onclick: close }, "✕");
    m.replaceChildren(h("div", { class: "dialog win org-preview", role: "dialog", "aria-modal": "true", "aria-label": "Preview" },
      h("div", { class: "titlebar" }, h("span", {}, "preview.exe"), closeBtn),
      h("div", { class: "org-stage" },
        h("button", { class: "btn ghost org-nav", "aria-label": "Previous file", onclick: () => go(-1) }, "‹"), img,
        h("button", { class: "btn ghost org-nav", "aria-label": "Next file", onclick: () => go(1) }, "›")),
      cap));
    m.onclick = (e) => { if (e.target === m) close(); };
    m.hidden = false;
    addEventListener("keydown", key);
    show();
    closeBtn.focus();
  }

  // ------------------------------------------------------------ "how many PDFs?" panel
  const defaults = () => ({ mode: store.get("pdfOut.mode", "single"), groups: "", leftovers: "each", name: "",
    page_size: store.get("pdfOut.page", "fit"), margin: 0, quality: 92 });

  function outputPanel(files, st, onChange) {
    const p = plan(files.length, st);
    const radio = (val, label, hint) => {
      const r = h("input", { type: "radio", name: "pdf-mode", value: val });
      r.checked = st.mode === val;
      r.onchange = () => { st.mode = val; store.set("pdfOut.mode", val); onChange(); };
      return h("label", { class: "org-mode" + (st.mode === val ? " on" : "") }, r, h("div", {}, h("b", {}, label), h("span", { class: "muted sm" }, hint)));
    };
    const groupsIn = h("input", { type: "text", value: st.groups, placeholder: "e.g. 1-3, 4, 5-8", "aria-label": "Which files go together" });
    groupsIn.oninput = () => { st.groups = groupsIn.value; clearTimeout(groupsIn._t); groupsIn._t = setTimeout(onChange, 450); };
    const leftovers = h("select", { "aria-label": "Files you didn't list" },
      h("option", { value: "each", selected: st.leftovers !== "skip" }, "each become their own PDF"),
      h("option", { value: "skip", selected: st.leftovers === "skip" }, "are left out"));
    leftovers.onchange = () => { st.leftovers = leftovers.value; onChange(); };
    const nameIn = h("input", { type: "text", value: st.name, placeholder: "automatic", "aria-label": "File name" });
    nameIn.oninput = () => (st.name = nameIn.value);
    const pageSel = h("select", { "aria-label": "Page size for pictures" },
      ...[["fit", "Fit each picture"], ["a4", "A4"], ["letter", "US Letter"]].map(([v, l]) => h("option", { value: v, selected: st.page_size === v }, l)));
    pageSel.onchange = () => { st.page_size = pageSel.value; store.set("pdfOut.page", pageSel.value); };
    const marginIn = h("input", { type: "number", min: 0, value: st.margin, style: "width:80px", "aria-label": "Margin in points" });
    marginIn.oninput = () => (st.margin = +marginIn.value || 0);

    const summary = p.error ? h("div", { class: "org-summary err", role: "alert" }, p.error)
      : h("div", { class: "org-summary", "aria-live": "polite" }, `→ ${p.groups.length} PDF${p.groups.length === 1 ? "" : "s"}: `,
        ...p.groups.slice(0, 12).map((g, k) => h("span", { class: "org-chip", style: `background:${GROUP_COLORS[k % GROUP_COLORS.length]}` },
          g.length === 1 ? `file ${g[0] + 1}` : `files ${fmtGroup(g)}`)), p.groups.length > 12 ? ` …and ${p.groups.length - 12} more` : "");
    return h("div", { class: "card org-out" }, h("h3", {}, "How many PDFs do you want?"),
      h("div", { class: "org-modes", role: "radiogroup", "aria-label": "PDF output" },
        radio("single", "One combined PDF", "everything, in the order shown"),
        radio("each", "A separate PDF for each file", "same names as the originals"),
        radio("groups", "Custom groups", "some files together, some on their own")),
      st.mode === "groups" ? h("div", { class: "row org-groups" }, h("label", {}, "Put together: ", groupsIn), h("label", {}, "Files I don't list ", leftovers)) : null,
      summary,
      h("div", { class: "row org-opts" },
        st.mode !== "each" ? h("label", {}, "File name ", nameIn) : null,
        h("label", {}, "Pictures on ", pageSel), h("label", {}, "Margin ", marginIn)));
  }
  const fmtGroup = (g) => {  // [0,1,2,4] -> "1-3, 5"
    const out = []; let s = g[0], prev = g[0];
    for (const x of [...g.slice(1), null]) { if (x === prev + 1) { prev = x; continue; } out.push(s === prev ? `${s + 1}` : `${s + 1}-${prev + 1}`); s = prev = x; }
    return out.join(", ");
  };

  async function run(files, st) {
    const p = plan(files.length, st);
    if (p.error) throw new Error(p.error);
    return api("/api/organize/build", {
      items: files.map((f) => ({ path: f.path, rotate: f.rotate || 0, pages: f.pages || "" })),
      mode: st.mode, groups: st.groups, leftovers: st.leftovers, name: st.name, out_dir: S.outDir,
      params: { page_size: st.page_size, margin: st.margin, quality: st.quality },
    });
  }

  window.Organizer = { grid, toolbar, outputPanel, run, plan, preview, defaults, describe };
})();
