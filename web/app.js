/* Dr. Doc — UI. Plain JS, no external libraries (works offline). */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};
const store = {
  get(k, d) { try { const v = localStorage.getItem("ec." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ec." + k, JSON.stringify(v)); } catch {} },
};

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Local-App": "1" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ ok: false, error: r.statusText }));
  if (!data.ok) throw new Error(data.error || "Request failed");
  // every started job is tracked from the start, so even an instant one gets its "done" toast
  if (data.job?.id && typeof known === "object" && !known[data.job.id]) known[data.job.id] = "queued";
  return data;
}

// ---------------------------------------------------------------- mascot & theme
const MASCOT = { light: "/web/assets/mascot-light.png", dark: "/web/assets/mascot-light.png" };
const effectiveTheme = () => document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
const mascotSrc = () => MASCOT[effectiveTheme()];
const mascotImg = (cls = "") => h("img", { class: "mascot " + cls, src: mascotSrc(), alt: "" });
function updateMascots() {
  $$("img.mascot").forEach((i) => (i.src = mascotSrc()));
  const dark = effectiveTheme() === "dark";
  $("#theme-ico").textContent = dark ? "☾" : "☀";
  $("#theme-label").textContent = dark ? "night" : "day";
  const fav = $("link[rel=icon]"); if (fav) fav.href = mascotSrc().replace(".png", "-sm.png");
}
fetch("/web/assets/mascot-dark.png", { method: "HEAD" }).then((r) => { if (r.ok) { MASCOT.dark = "/web/assets/mascot-dark.png"; updateMascots(); } }).catch(() => {});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", updateMascots);

const titlebar = (title, cls = "") => h("div", { class: "titlebar " + cls }, h("span", {}, title));

function toast(msg, err = false, ms = 3800) {
  const t = h("div", { class: "toast win", role: err ? "alert" : null }, titlebar(err ? "error" : "notice.txt", err ? "err" : ""),
    h("div", { class: "toast-body" }, h("img", { src: mascotSrc().replace(".png", "-sm.png"), alt: "" }), h("span", {}, msg)));
  $("#toasts").append(t);
  setTimeout(() => t.remove(), ms);
  return t;
}
const fail = (e) => toast(e.message || String(e), true, 6500);

/** Retro "are you sure?" dialog. Resolves true for Yes. */
function ask(msg, { title = "are you sure?", yes = "Yes", no = "No", danger = false } = {}) {
  return new Promise((resolve) => {
    const m = $("#modal");
    const done = (v) => { m.hidden = true; m.replaceChildren(); removeEventListener("keydown", key); resolve(v); };
    const key = (e) => {
      if (e.key === "Escape") done(false);
      else if (e.key === "Enter" && !document.activeElement?.closest?.(".dialog-actions")) done(true);  // a focused button handles Enter itself
    };
    const yesBtn = h("button", { class: "btn" + (danger ? " danger" : ""), onclick: () => done(true) }, yes);
    m.replaceChildren(h("div", { class: "dialog win", role: "alertdialog", "aria-modal": "true", "aria-label": title }, titlebar(title, danger ? "err" : ""),
      h("div", { class: "dialog-body" }, mascotImg("float"), h("div", {}, msg)),
      h("div", { class: "dialog-actions" }, yesBtn, h("button", { class: "btn ghost", onclick: () => done(false) }, no))));
    m.onclick = (e) => { if (e.target === m) done(false); };
    m.hidden = false;
    addEventListener("keydown", key);
    yesBtn.focus();
  });
}

const S = {
  caps: null, tools: [], categories: {}, convertParams: {},
  outDir: store.get("outDir", null),
  convertFiles: [],    // {path,name,ext,size_h,target}
  toolFiles: {},       // toolId -> files
  targets: {},         // ext -> [targets]
  view: "convert",
  currentTool: null,
};
window.App = { $, $$, h, api, toast, fail, ask, S, store, pickFiles, uploadFiles, renderParams, readParams, mascotImg, titlebar, watchJobs: () => pollJobs(true) };

const norm = (e) => (S.aliases?.[e] || e);
const catOf = (e) => S.categories[norm(e)] || "other";

// ---------------------------------------------------------------- boot
(async function boot() {
  applyTheme(store.get("theme", null));
  applyComfort();
  updateMascots();
  try {
    const d = await api("/api/caps");
    Object.assign(S, { caps: d.caps, tools: d.tools, categories: d.categories, convertParams: d.convert_params, aliases: d.aliases });
    if (!S.outDir) S.outDir = d.default_output;
    setupTaskbar();
    renderCaps();
    renderOut();
    // files handed over by "Open with…" / double-click (desktop build passes ?open=[paths])
    const opened = (() => { try { return JSON.parse(new URLSearchParams(location.search).get("open") || "[]"); } catch { return []; } })();
    const linked = decodeURIComponent((location.hash.match(/view=([^&]+)/) || [])[1] || "");  // e.g. #view=help
    route(opened.length ? "convert" : VIEWS.some((v) => v[0] === linked) ? linked : store.get("view", "convert"));
    if (location.hash.includes("palette")) window.Help?.openPalette();
    if (location.hash.includes("notour")) store.set("tour.done", true);
    const openTo = new URLSearchParams(location.search).get("to");  // e.g. ?to=pdf: "combine these into a PDF"
    if (opened.length) api("/api/fileinfo", { paths: opened }).then((r) => addConvertFiles(r.files, openTo)).catch(fail);
    pollJobs();
    window.Tour?.maybeAutoStart();
  } catch (e) {
    document.body.innerHTML = `<p style="padding:40px">Couldn't reach the local server: ${e.message}</p>`;
  }
})();

function renderCaps() {
  const c = S.caps;
  const items = [["ffmpeg", "Video/Audio"], ["word", "Word"], ["excel", "Excel"], ["powerpoint", "PowerPoint"], ["heic", "HEIC"], ["avif", "AVIF"]];
  $("#caps").replaceChildren(...items.map(([k, label]) => h("span", { class: c[k] ? "on" : "", title: c[k] ? "Available" : "Not installed" }, (c[k] ? "✓ " : "✕ ") + label)));
}

function renderOut() { $("#out-dir").textContent = S.outDir; $("#out-dir").title = S.outDir; }
$("#out-pick").onclick = async () => {
  try { const d = await api("/api/pick/folder", { title: "Choose where converted files go" }); if (d.path) { S.outDir = d.path; store.set("outDir", d.path); renderOut(); } } catch (e) { fail(e); }
};
$("#out-open").onclick = () => api("/api/open", { path: S.outDir }).catch(fail);

function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; updateMascots?.(); }
function toggleTheme() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  applyTheme(next); store.set("theme", next);
  say(next === "dark" ? "good night~ ☾ the stars are out" : "good morning! ☀");
}
$("#theme").onclick = toggleTheme;

// ---------------------------------------------------------------- buddy & taskbar
const VIEWS = [
  ["convert", "⇄", "Convert", "convert.exe", "drop anything on me ✦ I'll turn it into anything"],
  ["tools:Compress", "⇲", "Compress", "compress.exe", "too big? tell me how small and I'll squish it ✧"],
  ["tools:PDF", "▤", "PDF tools", "pdf_tools.exe", "merge, split, squish… pick a tool!"],
  ["editor", "✎", "PDF editor", "paint_a_pdf.exe", "let's scribble on a PDF ✎"],
  ["office", "▤", "Docs & sheets", "docs_and_sheets.exe", "open a Word doc or a spreadsheet and edit away ✎"],
  ["video", "🎬", "Video editor", "video_editor.exe", "trim, join, add music… lights, camera, action! 🎬"],
  ["tools:Image", "▧", "Image tools", "image_tools.exe", "photos too big? I'll make them tiny~"],
  ["tools:Video & Audio", "▶", "Video & audio", "video_audio.exe", "gif → mp4, mp4 → mp3… easy ♪"],
  ["tools:Data", "▦", "Spreadsheets", "spreadsheets.exe", "rows and columns, my favourite"],
  ["cleanup", "✦", "Clean up", "clean_up.exe", "let's tidy your computer ✧"],
  ["help", "?", "Help & manual", "manual.hlp", "stuck? I wrote everything down for you ✎"],
];
Object.assign(window.App, { VIEWS, route, openTool, cycleTextSize, applyComfort, openJobs: () => openJobs() });

// ---------------------------------------------------------------- comfort: text size & motion
function textSizes() { return [["normal", 1], ["large", 1.15], ["larger", 1.3]]; }  // a function: boot() runs before consts below exist
function applyComfort() {
  const size = textSizes().find(([k]) => k === store.get("textSize", "normal")) || textSizes()[0];
  document.documentElement.style.setProperty("--ui-zoom", size[1]);
  document.documentElement.classList.toggle("calm", !!store.get("calm", false));
}
function cycleTextSize() {
  const sizes = textSizes(), i = sizes.findIndex(([k]) => k === store.get("textSize", "normal"));
  const next = sizes[(i + 1) % sizes.length][0];
  store.set("textSize", next); applyComfort();
  toast(`Text size: ${next}`);
}
function toggleCalm() {
  store.set("calm", !store.get("calm", false)); applyComfort();
  toast(store.get("calm") ? "Reduce motion: on (no floating or sparkles)" : "Reduce motion: off");
}

// ---------------------------------------------------------------- keyboard: Ctrl+K, F1, Alt+1…9
addEventListener("keydown", (e) => {
  if (document.querySelector(".tour")) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if ($("#modal").hidden) window.Help?.openPalette(); }
  else if (e.key === "F1") { e.preventDefault(); window.Help?.show(); }
  else if (e.altKey && !e.ctrlKey && /^[1-9]$/.test(e.key) && !typing) {
    const a = $$("#nav a")[+e.key - 1];
    if (a) { e.preventDefault(); a.click(); }
  }
});
$("#search-btn").onclick = () => window.Help?.openPalette();
$("#help-btn").onclick = () => window.Help?.show();
const QUIPS = ["hehe that tickles", "boop!", "✦ sparkle mode ✦", "I don't need the internet, only you", "no file too big!", "*floats happily*", "converting is my cardio"];
let sayTimer;
function say(text, ms = 0) {
  const b = $("#buddy-say"); if (!b) return;
  b.textContent = text;
  clearTimeout(sayTimer);
  if (ms) sayTimer = setTimeout(() => (b.textContent = VIEWS.find((v) => v[0] === S.view)?.[4] || ""), ms);
}
$("#buddy").onclick = (e) => {
  const img = e.currentTarget;
  img.classList.remove("float", "wiggle"); void img.offsetWidth; img.classList.add("wiggle");
  setTimeout(() => { img.classList.remove("wiggle"); img.classList.add("float"); }, 650);
  say(QUIPS[Math.floor(Math.random() * QUIPS.length)], 2600);
};

function setupTaskbar() {
  const clock = () => ($("#clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  clock(); setInterval(clock, 10000);
  const menu = $("#start-menu"), start = $("#start");
  $("#start-items").replaceChildren(
    ...VIEWS.map(([v, ico, label]) => h("button", { onclick: () => { route(v); closeMenu(); } }, h("span", {}, ico), label)),
    h("hr"),
    h("button", { onclick: () => { api("/api/open", { path: S.outDir }).catch(fail); closeMenu(); } }, h("span", {}, "📁"), "Open output folder"),
    h("button", { onclick: () => { toggleTheme(); closeMenu(); } }, h("span", {}, "◐"), "Day / night"),
    h("hr"),
    h("button", { onclick: () => { closeMenu(); window.Help?.show(); } }, h("span", {}, "?"), "Help & manual"),
    h("button", { onclick: () => { closeMenu(); window.Tour?.start(0); } }, h("span", {}, "▶"), "Take the tour"),
    h("button", { onclick: () => { closeMenu(); window.Help?.openPalette(); } }, h("span", {}, "🔍"), "Find a tool… (Ctrl+K)"),
    h("button", { onclick: () => { cycleTextSize(); } }, h("span", {}, "A"), "Text size"),
    h("button", { onclick: () => { toggleCalm(); closeMenu(); } }, h("span", {}, "≈"), "Reduce motion"));
  $$("#start-items button").forEach((b) => b.setAttribute("role", "menuitem"));
  const closeMenu = (focusStart) => { menu.hidden = true; start.classList.remove("on"); start.setAttribute("aria-expanded", "false"); if (focusStart) start.focus(); };
  start.onclick = (e) => {
    e.stopPropagation(); menu.hidden = !menu.hidden; start.classList.toggle("on", !menu.hidden); start.setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) $("#start-items button")?.focus();
  };
  menu.onkeydown = (e) => {
    const items = $$("#start-items button"), i = items.indexOf(document.activeElement);
    if (e.key === "Escape") closeMenu(true);
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  };
  addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
}

// ---------------------------------------------------------------- routing
$$("#nav a").forEach((a) => (a.onclick = (e) => { e.preventDefault(); route(a.dataset.view); }));
$("#buddy").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } };
function route(view) {
  S.view = view; store.set("view", view);
  $$("#nav a").forEach((a) => { a.classList.toggle("active", a.dataset.view === view); a.toggleAttribute("aria-current", a.dataset.view === view); });
  document.title = view === "convert" ? "Dr. Doc" : `${VIEWS.find((v) => v[0] === view)?.[2] || "Dr. Doc"} · Dr. Doc`;
  $$(".view").forEach((v) => (v.hidden = true));
  const [kind, cat] = view.split(":");
  const meta = VIEWS.find((v) => v[0] === view);
  $("#view-title").textContent = meta?.[3] || view;
  say(meta?.[4] || "");
  if (kind === "convert") { $("#view-convert").hidden = false; renderConvert(); }
  else if (kind === "tools") { $("#view-tools").hidden = false; S.currentTool = null; renderToolGrid(cat); }
  else if (kind === "editor") { $("#view-editor").hidden = false; window.Editor?.mount($("#view-editor")); }
  else if (kind === "cleanup") { $("#view-cleanup").hidden = false; renderCleanup(); }
  else if (kind === "office") { $("#view-office").hidden = false; mountModule("Office", "#view-office", "Docs & sheets"); }
  else if (kind === "video") { $("#view-video").hidden = false; mountModule("VideoEditor", "#view-video", "The video editor"); }
  else if (kind === "help") { $("#view-help").hidden = false; window.Help?.mount($("#view-help")); }
}

/** Feature screens live in their own script (office.js, video.js) and expose window.X.mount(el). */
function mountModule(name, sel, label) {
  const el = $(sel);
  if (window[name]?.mount) window[name].mount(el);
  else el.replaceChildren(h("div", { class: "card" }, h("h3", {}, label + " isn't installed in this build.")));
}

// ---------------------------------------------------------------- adding files
async function pickFiles() { return (await api("/api/pick/files", {})).files; }

function uploadFiles(fileList) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    let total = 0;
    for (const f of fileList) { fd.append("files", f, f.name); total += f.size; }
    const xhr = new XMLHttpRequest();
    const t = h("div", { class: "toast" }, "Copying dropped files… 0%");
    $("#toasts").append(t);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) t.textContent = `Copying dropped files… ${Math.round(e.loaded / e.total * 100)}%`; };
    xhr.onload = () => { t.remove(); try { const d = JSON.parse(xhr.responseText); d.ok ? resolve(d.files) : reject(new Error(d.error)); } catch (e) { reject(e); } };
    xhr.onerror = () => { t.remove(); reject(new Error("Upload failed")); };
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-Local-App", "1");
    xhr.send(fd);
    if (total > 2e9) toast("Tip: for huge files use “Browse”: it reads them in place with no copying.", false, 7000);
  });
}

// global drag & drop → whichever file list is on screen
let dragDepth = 0;
addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; document.body.classList.add("dragging"); } });
addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", async (e) => {
  e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
  if (!e.dataTransfer?.files.length) return;
  try {
    const files = await uploadFiles(e.dataTransfer.files);
    if (S.view === "editor") window.Editor?.openFile(files.find((f) => f.ext === "pdf"));
    else if (S.view === "office") window.Office?.openFile(files[0]);
    else if (S.view === "video") window.VideoEditor?.addFiles(files);
    else addFiles(files);
  } catch (err) { fail(err); }
});

function addFiles(files) {
  if (S.view === "convert") { addConvertFiles(files); return; }
  if (S.currentTool) {
    const t = S.currentTool;
    const ok = files.filter((f) => t.inputs.includes("*") || t.inputs.includes(f.ext));
    if (ok.length < files.length) toast(`${files.length - ok.length} file(s) skipped: not supported by “${t.name}”`, true);
    S.toolFiles[t.id] = [...(S.toolFiles[t.id] || []), ...ok];
    renderToolPage(t);
  } else {
    toast("Pick a tool first, or use Convert");
  }
}

function dropzone(onAdd, accept) {
  const pathIn = h("input", { type: "text", placeholder: "…or paste a file / folder path and press Enter" });
  pathIn.onkeydown = async (e) => {
    if (e.key !== "Enter" || !pathIn.value.trim()) return;
    try { const d = await api("/api/fileinfo", { paths: pathIn.value.split(/\r?\n/) }); if (!d.files.length) throw new Error("No files found at that path"); onAdd(d.files); pathIn.value = ""; } catch (err) { fail(err); }
  };
  return h("div", { class: "dropzone win" }, titlebar("drop_files_here.exe"),
    h("div", { class: "dz-body" },
      h("h2", {}, "drop files on me ✦"),
      h("p", {}, "Drop files anywhere, or browse. Big files are read in place; nothing is uploaded anywhere.",
        accept ? h("br") : null, accept ? h("span", { class: "sm" }, "Accepts: " + accept) : null),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: async () => { try { onAdd(await pickFiles()); } catch (e) { fail(e); } } }, "📂 Browse files")),
      h("div", { class: "path-input" }, pathIn),
      mascotImg("float dz-mascot")));
}

function fileRow(f, { right, onRemove, draggable, list, rerender }) {
  const thumb = h("div", { class: "thumb" }, f.ext);
  if (["jpg", "png", "webp", "gif", "bmp", "tiff", "heic", "avif", "ico", "pdf"].includes(f.ext)) {
    const img = h("img", { src: "/api/thumb?path=" + encodeURIComponent(f.path), alt: "" });  // detached until loaded, so no lazy-loading
    img.onerror = () => img.remove();
    img.onload = () => thumb.replaceChildren(img);
  }
  const row = h("div", { class: "file" + (f.bad ? " bad" : ""), draggable: draggable ? "true" : null },
    h("div", { class: "grip", title: draggable ? "Drag to reorder" : "" }, draggable ? "⋮⋮" : ""),
    thumb,
    h("div", { class: "meta" }, h("div", { class: "name", title: f.path }, f.name), h("div", { class: "sub" }, `${f.ext.toUpperCase()} · ${f.size_h}`)),
    right?.[0] || h("span"), right?.[1] || h("span"),
    h("button", { class: "x", title: "Remove", "aria-label": `Remove ${f.name}`, onclick: onRemove }, "✕"));
  if (draggable) {
    row.ondragstart = (e) => { row.classList.add("dragging"); e.dataTransfer.setData("text/x-index", list.indexOf(f)); e.stopPropagation(); };
    row.ondragend = () => row.classList.remove("dragging");
    row.ondragover = (e) => e.preventDefault();
    row.ondrop = (e) => {
      const raw = e.dataTransfer.getData("text/x-index");
      if (raw === "" || e.dataTransfer.files.length) return;
      const from = +raw;
      e.preventDefault(); e.stopPropagation();
      const to = list.indexOf(f);
      const [m] = list.splice(from, 1); list.splice(to, 0, m); rerender();
    };
  }
  return row;
}

// ---------------------------------------------------------------- params form
function renderParams(params, values = {}) {
  const wrap = h("div", { class: "opts" });
  const inputs = {};
  for (const p of params) {
    const v = values[p.name] ?? p.default;
    let input, box;
    if (p.type === "select") {
      input = h("select", {}, ...p.options.map(([val, label]) => h("option", { value: val, selected: String(val) === String(v) }, label)));
    } else if (p.type === "checkbox") {
      input = h("input", { type: "checkbox" }); input.checked = !!v;
      box = h("div", { class: "opt check" }, h("label", {}, input, p.label));
    } else if (p.type === "range") {
      input = h("input", { type: "range", min: p.min, max: p.max, step: p.step || 1, value: v });
      const out = h("b", {}, String(v));
      input.oninput = () => (out.textContent = input.value);
      box = h("div", { class: "opt" }, h("label", {}, p.label), h("div", { class: "inline" }, input, out));
    } else if (p.type === "color") {
      input = h("input", { type: "color", value: v });
    } else {
      input = h("input", { type: p.type === "number" ? "number" : p.type === "password" ? "password" : "text", value: v ?? "", step: p.step ?? null, min: p.type === "number" ? p.min ?? null : null });
    }
    input.id ||= "opt-" + p.name + "-" + Math.random().toString(36).slice(2, 7);
    box = box || h("div", { class: "opt" }, h("label", { for: input.id }, p.label), input);
    if (p.type === "range") { box.querySelector("label").setAttribute("for", input.id); input.setAttribute("aria-valuetext", String(v)); input.addEventListener("input", () => input.setAttribute("aria-valuetext", input.value)); }
    box.dataset.name = p.name;
    inputs[p.name] = { input, p, box };
    wrap.append(box);
  }
  const sync = () => {
    for (const { p, box } of Object.values(inputs)) {
      if (!p.show_if) continue;
      box.hidden = !Object.entries(p.show_if).every(([k, val]) => inputs[k] && !inputs[k].box.hidden &&
        [val].flat().map(String).includes(String(readOne(inputs[k]))));
    }
    wrap.onsync?.();
  };
  wrap.addEventListener("input", sync); wrap.addEventListener("change", sync); sync();
  wrap._inputs = inputs;
  wrap._sync = sync;
  return wrap;
}
function readOne({ input, p }) {
  if (p.type === "checkbox") return input.checked;
  if (p.type === "number") return input.value === "" ? "" : Number(input.value);
  if (p.type === "range") return Number(input.value);
  return input.value;
}
function readParams(wrap) {
  const out = {};
  if (!wrap?._inputs) return out;
  for (const [k, it] of Object.entries(wrap._inputs)) out[k] = readOne(it);
  return out;
}

// ---------------------------------------------------------------- Convert view
const DEFAULT_TARGET = {
  jpg: "png", png: "jpg", heic: "jpg", webp: "png", avif: "jpg", bmp: "png", tiff: "jpg", gif: "mp4", svg: "png", ico: "png",
  pdf: "docx", docx: "pdf", doc: "docx", rtf: "pdf", odt: "pdf", pptx: "pdf", ppt: "pdf", xlsx: "csv", xls: "xlsx", csv: "xlsx",
  tsv: "csv", json: "csv", xml: "csv", md: "pdf", html: "pdf", txt: "pdf",
  mp4: "mp3", mkv: "mp4", mov: "mp4", avi: "mp4", webm: "mp4", flv: "mp4", wmv: "mp4", m4v: "mp4", mpeg: "mp4", "3gp": "mp4", ts: "mp4",
  mp3: "wav", wav: "mp3", flac: "mp3", m4a: "mp3", aac: "mp3", ogg: "mp3", opus: "mp3", wma: "mp3", aiff: "mp3",
};
let convertOpts = null;

async function ensureTargets(exts) {
  const missing = [...new Set(exts)].filter((e) => !(e in S.targets));
  if (missing.length) Object.assign(S.targets, (await api("/api/targets", { exts: missing })).targets);
  // A PDF can "go to PDF" too: it joins the other files when they're combined.
  if (S.targets.pdf && !S.targets.pdf.includes("pdf")) S.targets.pdf.unshift("pdf");
}

async function addConvertFiles(files, want = null) {
  await ensureTargets(files.map((f) => f.ext));
  for (const f of files) {
    const t = S.targets[f.ext] || [];
    const last = store.get("lastTarget." + f.ext, null);
    f.target = t.includes(want) ? want : t.includes(last) ? last : t.includes(DEFAULT_TARGET[f.ext]) ? DEFAULT_TARGET[f.ext] : t[0] || "";
    f.bad = !t.length;
    S.convertFiles.push(f);
  }
  renderConvert();
}

function targetSelect(list, value, onChange) {
  const groups = {};
  for (const t of list) (groups[catOf(t)] ||= []).push(t);
  const names = { image: "Images", gif: "Animated", video: "Video", audio: "Audio", doc: "Documents", data: "Spreadsheets & data", other: "Other" };
  const sel = h("select", {}, ...Object.entries(groups).map(([c, ts]) =>
    h("optgroup", { label: names[c] || c }, ...ts.map((t) => h("option", { value: t, selected: t === value }, t.toUpperCase())))));
  sel.onchange = () => onChange(sel.value);
  return sel;
}

function renderConvert() {
  const v = $("#view-convert");
  const files = S.convertFiles;
  const prev = readParams(convertOpts);
  v.replaceChildren();
  v.append(dropzone(addConvertFiles));
  if (!files.length) {
    const tool = (id) => () => openTool(S.tools.find((t) => t.id === id));
    v.append(h("div", { class: "section-label" }, "What do you want to do?"),
      h("div", { class: "tool-grid" }, ...[
        ["⊕", "Combine photos into a PDF", "Arrange pictures, then make one PDF, one each, or groups", tool("img_to_pdf")],
        ["⇲", "Make a file smaller", "Any file, by a % or to an exact size like 200 KB", tool("compress_any")],
        ["✎", "Edit a PDF", "Change text, add notes, shapes, signatures", () => route("editor")],
        ["▤", "Open a Word or Excel file", "Read, edit and save documents and spreadsheets", () => route("office")],
        ["🎬", "Edit a video", "Trim, join clips, add music and titles", () => route("video")],
        ["⊞", "Merge or split PDFs", "Combine PDFs, pull out or reorder pages", () => route("tools:PDF")],
        ["♪", "Convert video or audio", "MP4 → MP3, MOV → MP4, GIF ⇄ MP4 …", () => route("tools:Video & Audio")],
        ["?", "Show me around", "A one-minute tour of Dr. Doc", () => window.Tour?.start(0)],
      ].map(([i, t, d, go]) => h("button", { class: "tool-card", onclick: go }, h("div", { class: "ti" }, i), h("b", {}, t), h("p", {}, d)))),
      h("p", { class: "muted sm", style: "margin-top:16px" }, "Or just drop files above to convert them to any format: images, documents, spreadsheets, video and audio."));
    return;
  }

  // bulk "set all X to Y" chips for each input type present
  const byExt = {};
  for (const f of files) (byExt[f.ext] ||= []).push(f);
  const actions = h("div", { class: "file-actions" }, h("b", {}, `${files.length} file(s)`), h("span", { class: "spacer" }));
  for (const [ext, fs] of Object.entries(byExt)) {
    if (fs.length < 2 || !S.targets[ext]?.length) continue;
    actions.append(h("div", { class: "group-set" }, `All ${ext.toUpperCase()} →`,
      targetSelect(S.targets[ext], fs[0].target, (t) => { fs.forEach((f) => (f.target = t)); store.set("lastTarget." + ext, t); renderConvert(); })));
  }
  actions.append(h("button", { class: "btn ghost sm", onclick: () => { S.convertFiles = []; renderConvert(); } }, "Clear all"));
  v.append(actions);

  // Two or more files going to PDF: arrange them visually and choose one PDF / one each / groups.
  const toPdf = files.filter((f) => f.target === "pdf" && !f.bad);
  const organise = toPdf.length >= 2 && window.Organizer;
  if (organise) v.append(pdfOrganiser(toPdf, files));

  const list = h("div", { class: "files" });
  for (const f of files) {
    if (organise && toPdf.includes(f)) continue;
    const tg = S.targets[f.ext] || [];
    const sel = tg.length ? targetSelect(tg, f.target, (t) => { f.target = t; store.set("lastTarget." + f.ext, t); renderConvert(); })
      : h("span", { class: "muted sm" }, "No converter for this type");
    list.append(fileRow(f, { right: [h("span", { class: "arrow" }, "→"), sel], onRemove: () => { files.splice(files.indexOf(f), 1); renderConvert(); } }));
  }
  if (list.children.length) v.append(...[organise && h("div", { class: "section-label" }, "Other files"), list].filter(Boolean));

  // options relevant to the chosen targets
  const groups = new Set();
  for (const f of files) {
    if (organise && toPdf.includes(f)) continue;
    const tc = catOf(f.target), sc = catOf(f.ext);
    if (f.target === "svg") groups.add("svg");
    else if ((tc === "image" || f.target === "gif") && ["doc", "data"].includes(sc)) groups.add("from_pdf_image");
    else if (f.target === "gif" && sc === "video") groups.add("gif");
    else if (tc === "image" || tc === "gif") groups.add("image");
    if (tc === "video" || (f.ext === "gif" && tc === "video")) groups.add("video");
    if (tc === "audio") groups.add("audio");
  }
  const params = [];
  const seen = new Set();
  for (const g of groups) for (const p of S.convertParams[g] || []) if (!seen.has(p.name)) { seen.add(p.name); params.push(p); }
  convertOpts = renderParams(params, prev);
  if (params.length) v.append(h("div", { class: "card", style: "margin-top:14px" }, h("h3", { style: "margin-bottom:12px" }, "options.ini"), convertOpts));

  const ready = files.filter((f) => f.target && !f.bad);
  const plan = organise ? Organizer.plan(toPdf.length, S.pdfOut) : null;
  const label = organise ? `Convert ${ready.length} file(s)` + (plan.error ? "" : ` → ${plan.groups.length + ready.length - toPdf.length} result(s)`) : `Convert ${ready.length} file(s)`;
  v.append(h("div", { class: "runbar" },
    h("button", { class: "btn big", disabled: !ready.length || !!plan?.error, onclick: runConvert }, label),
    h("span", { class: "muted sm" }, "Saved to: " + S.outDir)));
}

/** The organiser block on the Convert page for files whose target is PDF. */
function pdfOrganiser(toPdf, all) {
  S.pdfOut ||= Organizer.defaults();
  const rerender = () => renderConvert();
  const plan = Organizer.plan(toPdf.length, S.pdfOut);
  const groupOf = S.pdfOut.mode === "groups" && !plan.error ? (i) => { const g = plan.groups.findIndex((x) => x.includes(i)); return g < 0 ? null : g; } : null;
  const onChange = ({ focus } = {}) => {
    // the grid reorders/removes in toPdf; mirror that into the main list
    S.convertFiles = [...all.filter((f) => !(f.target === "pdf" && !f.bad)), ...toPdf];
    rerender();
    if (focus != null) requestAnimationFrame(() => $("#view-convert .org-grid")?.focusCard(focus));
  };
  const targetPick = (f) => {
    const tg = S.targets[f.ext] || [];
    return tg.length > 1 ? h("label", { class: "org-target" }, "→ ", targetSelect(tg, f.target, (t) => { f.target = t; store.set("lastTarget." + f.ext, t); rerender(); })) : null;
  };
  return h("div", { class: "org-wrap" },
    h("div", { class: "section-label" }, `${toPdf.length} files → PDF`),
    Organizer.outputPanel(toPdf, S.pdfOut, rerender),
    Organizer.toolbar(toPdf, onChange),
    Organizer.grid(toPdf, { onChange, groupOf, extra: targetPick }));
}

async function runConvert() {
  const ready = S.convertFiles.filter((f) => f.target && !f.bad);
  const toPdf = ready.filter((f) => f.target === "pdf");
  const organise = toPdf.length >= 2 && window.Organizer;
  const same = ready.filter((f) => f.ext === f.target && !(organise && toPdf.includes(f)));  // e.g. one PDF "→ PDF": nothing to do
  if (same.length) toast(`${same.length} file(s) skipped: already ${same[0].target.toUpperCase()}. Add more files to combine them.`);
  const items = ready.filter((f) => !(organise && toPdf.includes(f)) && !same.includes(f)).map((f) => ({ path: f.path, target: f.target }));
  try {
    if (organise) await Organizer.run(toPdf, S.pdfOut);
    if (items.length) await api("/api/convert", { items, out_dir: S.outDir, params: readParams(convertOpts) });
    if (!organise && !items.length) return;
    toast(`Started converting ${ready.length} file(s)`);
    S.convertFiles = []; renderConvert();
    openJobs(); pollJobs(true);
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- Tools
function renderToolGrid(cat) {
  const v = $("#view-tools");
  const tools = S.tools.filter((t) => t.cat === cat);
  v.replaceChildren(h("div", { class: "tool-grid" }, ...tools.map((t) =>
    h("button", { class: "tool-card", onclick: () => { S.currentTool = t; renderToolPage(t); } },
      h("div", { class: "ti" }, t.icon), h("b", {}, t.name), h("p", {}, t.desc || shortAccepts(t))))));
  if (cat === "PDF") v.append(h("div", { class: "section-label" }, "Edit text, draw diagrams & annotate"),
    h("div", { class: "tool-grid" }, h("button", { class: "tool-card", onclick: () => route("editor") },
      h("div", { class: "ti" }, "✎"), h("b", {}, "Open the PDF editor"), h("p", {}, "Change existing text, add text, shapes, arrows, freehand, highlights, images, whiteout."))));
  if (cat === "PDF" || cat === "Data" || cat === "Image") v.append(h("p", { class: "muted sm", style: "margin-top:18px" },
    "Format changes (e.g. PDF → Word, Excel → CSV, PNG → SVG) are on the ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); route("convert"); } }, "Convert"), " page."));
}
const shortAccepts = (t) => t.inputs.includes("*") ? "Any file" : t.inputs.slice(0, 8).map((e) => e.toUpperCase()).join(", ") + (t.inputs.length > 8 ? "…" : "");

function openTool(t) {
  if (!t) return;
  route("tools:" + t.cat);
  S.currentTool = t; renderToolPage(t);
}

let toolOpts = null;
function renderToolPage(t) {
  const v = $("#view-tools");
  const files = (S.toolFiles[t.id] ||= []);
  const prev = toolOpts?._tool === t.id ? readParams(toolOpts) : {};
  v.replaceChildren(
    h("button", { class: "back", onclick: () => { S.currentTool = null; renderToolGrid(t.cat); } }, "← All " + t.cat + " tools"),
    h("div", { class: "tool-head" }, h("div", { class: "ti" }, t.icon), h("div", {}, h("h2", {}, t.name), h("p", {}, t.desc || ""))),
    dropzone((fs) => addFiles(fs), shortAccepts(t)));
  if (ORGANISED_TOOLS.includes(t.id) && window.Organizer) return renderOrganisedTool(t, v, files);
  if (files.length) {
    const list = h("div", { class: "files" });
    const rerender = () => renderToolPage(t);
    for (const f of files) list.append(fileRow(f, { draggable: t.multi, list: files, rerender, onRemove: () => { files.splice(files.indexOf(f), 1); rerender(); } }));
    v.append(h("div", { class: "file-actions" }, h("b", {}, `${files.length} file(s)`), t.multi ? h("span", { class: "muted sm" }, "Drag ⋮⋮ to set the order") : null,
      h("span", { class: "spacer" }), h("button", { class: "btn ghost sm", onclick: () => { S.toolFiles[t.id] = []; rerender(); } }, "Clear")), list);
  }
  toolOpts = renderParams(t.params, prev);
  toolOpts._tool = t.id;
  if (t.params.length) v.append(h("div", { class: "card", style: "margin-top:14px" }, h("h3", { style: "margin-bottom:12px" }, "settings.ini"), toolOpts));
  if (toolOpts._inputs.size_mode) {
    const est = h("div", { class: "size-est" });
    toolOpts.append(est);
    toolOpts.onsync = () => { est.textContent = sizeEstimate(files, readParams(toolOpts)); est.hidden = !est.textContent; };
    toolOpts._sync();
  }
  const need = t.multi ? 2 : 1;
  v.append(h("div", { class: "runbar" },
    h("button", { class: "btn big", disabled: files.length < (t.id === "pdf_merge" || t.id === "vid_concat" ? need : 1), onclick: () => runTool(t) }, t.name),
    h("span", { class: "muted sm" }, "Saved to: " + S.outDir)));
}

// Tools whose files are arranged in the visual organiser and can produce one PDF, one each, or groups.
const ORGANISED_TOOLS = ["pdf_merge", "img_to_pdf"];
function renderOrganisedTool(t, v, files) {
  S.pdfOut ||= Organizer.defaults();
  const st = S.pdfOut;
  const rerender = () => renderToolPage(t);
  if (files.length) {
    const plan = Organizer.plan(files.length, st);
    const groupOf = st.mode === "groups" && !plan.error ? (i) => { const g = plan.groups.findIndex((x) => x.includes(i)); return g < 0 ? null : g; } : null;
    const onChange = ({ focus } = {}) => { rerender(); if (focus != null) requestAnimationFrame(() => $("#view-tools .org-grid")?.focusCard(focus)); };
    v.append(h("div", { class: "file-actions" }, h("b", {}, `${files.length} file(s)`), h("span", { class: "spacer" }),
      h("button", { class: "btn ghost sm", onclick: () => { S.toolFiles[t.id] = []; rerender(); } }, "Clear")),
      Organizer.outputPanel(files, st, rerender), Organizer.toolbar(files, onChange), Organizer.grid(files, { onChange, groupOf }));
    v.append(h("div", { class: "runbar" },
      h("button", { class: "btn big", disabled: !!plan.error, onclick: async () => {
        try {
          await Organizer.run(files, st);
          toast(`Started: ${t.name}`);
          S.toolFiles[t.id] = []; rerender(); openJobs(); pollJobs(true);
        } catch (e) { fail(e); }
      } }, plan.error ? t.name : `Make ${plan.groups.length} PDF${plan.groups.length === 1 ? "" : "s"}`),
      h("span", { class: "muted sm" }, "Saved to: " + S.outDir)));
  }
}

const UNIT = { KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3 };
const humanSize = (n) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return (i ? n.toFixed(1) : n.toFixed(0)) + " " + u[i]; };
/** One line saying what the size controls will aim for, given the files picked so far. */
function sizeEstimate(files, p) {
  if (p.size_mode === "target") {
    const limit = Number(p.target_size) * (UNIT[p.target_unit] || UNIT.MB);
    if (!(limit > 0)) return "Type a size to aim for.";
    const under = files.filter((f) => f.size <= limit).length;
    return `Each file will be made ${humanSize(limit)} or smaller.` + (under ? ` ${under} already fit${under > 1 ? "" : "s"} and will be copied as-is.` : "");
  }
  if (p.size_mode === "percent" && files.length) {
    const total = files.reduce((a, f) => a + (f.size || 0), 0);
    return `≈ ${humanSize(total)} → ${humanSize(total * (100 - p.reduce_pct) / 100)} in total`;
  }
  return "";
}

async function runTool(t) {
  const files = S.toolFiles[t.id];
  try {
    await api("/api/tool", { tool: t.id, paths: files.map((f) => f.path), out_dir: S.outDir, params: readParams(toolOpts) });
    toast(`Started: ${t.name}`);
    S.toolFiles[t.id] = []; renderToolPage(t);
    openJobs(); pollJobs(true);
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- Jobs
var known = {};  // var: api() may look at it before this line has run
let pollTimer = null;
let lastJobsKey = "";
const syncJobsBtn = () => $("#jobs-toggle").classList.toggle("on", !$("#jobs").hidden);
function openJobs() { $("#jobs").hidden = false; syncJobsBtn(); }
$("#jobs-toggle").onclick = () => { $("#jobs").hidden = !$("#jobs").hidden; syncJobsBtn(); };
$("#jobs-close").onclick = () => { $("#jobs").hidden = true; syncJobsBtn(); };
$("#jobs-clear").onclick = () => api("/api/jobs/clear", {}).then(() => pollJobs(true)).catch(fail);

async function pollJobs(force) {
  clearTimeout(pollTimer);
  let active = false;
  try {
    const { jobs } = await api("/api/jobs");
    active = jobs.some((j) => j.status === "running" || j.status === "queued");
    renderJobs(jobs);
    for (const j of jobs) {
      const was = known[j.id];
      if (was && was !== j.status && ["done", "error", "cancelled"].includes(j.status)) {
        j.status === "done" ? toast("✓ " + j.title + ": " + j.message) : toast(j.title + ": " + j.message, true, 6000);
        window.Editor?.onJobDone?.(j);
        window.VideoEditor?.onJobDone?.(j); window.Office?.onJobDone?.(j);
      }
      known[j.id] = j.status;
    }
  } catch {}
  pollTimer = setTimeout(pollJobs, active || force ? 700 : 3000);
}

const base = (p) => p.split(/[\\/]/).pop();
// Finished files can go straight into the matching editor.
const EDITORS = { pdf: "editor", docx: "office", doc: "office", odt: "office", rtf: "office", txt: "office", md: "office", html: "office",
  xlsx: "office", xls: "office", ods: "office", csv: "office", tsv: "office", pptx: "office",
  mp4: "video", mov: "video", mkv: "video", webm: "video", avi: "video", m4v: "video", mp3: "video", wav: "video", m4a: "video" };
const editorFor = (p) => {
  const v = EDITORS[(p.split(".").pop() || "").toLowerCase()];
  return v && (v === "editor" || window[v === "office" ? "Office" : "VideoEditor"]) ? v : null;
};
async function editInApp(p) {
  try {
    const [f] = (await api("/api/fileinfo", { paths: [p] })).files;
    const v = editorFor(p);
    route(v);
    if (v === "editor") window.Editor?.openFile(f);
    else if (v === "office") window.Office?.openFile(f);
    else window.VideoEditor?.addFiles([f]);
  } catch (e) { fail(e); }
}
function renderJobs(jobs) {
  const running = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const b = $("#jobs-count"); b.textContent = running; b.classList.toggle("zero", !running);
  const list = $("#jobs-list");
  const key = JSON.stringify(jobs.map((j) => [j.id, j.status, j.message, j.progress, j.outputs.length, j.notes?.length]));
  if (key === lastJobsKey) return;  // unchanged: don't re-render (keeps animations smooth)
  lastJobsKey = key;
  if (running) say(`working on it… ${running} job${running > 1 ? "s" : ""} running ⏳`);
  if (!jobs.length) { list.replaceChildren(h("div", { class: "jobs-empty" }, mascotImg("float"), "nothing yet~ zzz", h("div", { class: "sm muted" }, "Conversions show up here with live progress."))); return; }
  list.replaceChildren(...jobs.map((j) => h("div", { class: "job " + j.status },
    h("div", { class: "job-top" }, h("div", { class: "job-title" }, j.title), h("span", { class: "status " + j.status }, j.status)),
    h("div", { class: "job-msg" }, j.message),
    h("div", { class: "bar" }, h("i", { style: `width:${Math.round(j.progress * 100)}%` })),
    j.status === "running" || j.status === "queued" ? h("div", { class: "row", style: "margin-top:8px" },
      h("button", { class: "btn ghost sm", onclick: () => api(`/api/jobs/${j.id}/cancel`, {}).catch(fail) }, "Cancel")) : null,
    j.outputs.length ? h("div", { class: "outs" }, ...j.outputs.slice(0, 30).map((p) => h("div", { class: "out-item" },
      h("span", { title: p }, base(p)),
      h("a", { onclick: () => api("/api/open", { path: p, reveal: false }).catch(fail) }, "Open"),
      h("a", { onclick: () => api("/api/open", { path: p }).catch(fail) }, "Show"),
      editorFor(p) ? h("a", { title: "Open it in Dr. Doc's editor", onclick: () => editInApp(p) }, "Edit") : null)),
      j.outputs.length > 30 ? h("div", { class: "muted sm" }, `…and ${j.outputs.length - 30} more`) : null) : null,
    j.notes?.length ? h("div", { class: "notes" }, j.notes.join("\n")) : null,
    j.errors.length ? h("div", { class: "errs" }, j.errors.join("\n")) : null)));
}

// ---------------------------------------------------------------- Clean up
let cleanTab = "duplicates";
async function renderCleanup() {
  const v = $("#view-cleanup");
  v.replaceChildren(h("div", { class: "loading" }, mascotImg("float"), h("span", { class: "spinner" }), "measuring drives and temp folders…"));
  let d;
  try { d = await api("/api/clean/overview"); } catch (e) { fail(e); return; }
  const low = d.disks.find((k) => k.free / k.total < 0.1);
  if (low && S.view === "cleanup") say(`eek! ${low.drive} only has ${low.free_h} left… let's tidy up ✧`);
  const disks = h("div", { class: "card" }, h("h3", {}, "drives.sys"), ...d.disks.map((k) => h("div", { class: "disk" },
    h("div", { class: "row" }, h("b", {}, k.drive), h("span", { class: "muted" }, `${k.free_h} free of ${k.total_h}`)),
    h("div", { class: "bar" }, h("i", { style: `width:${(k.used / k.total * 100).toFixed(1)}%` + (k.free / k.total < 0.1 ? ";background:var(--err)" : "") })),
    k.free / k.total < 0.1 ? h("div", { class: "sm", style: "color:var(--err);margin-top:4px" }, "Almost full: big video conversions may run out of space.") : null)));

  const appCard = h("div", { class: "card" }, h("h3", {}, "app_cache.tmp"), h("p", { class: "muted sm" }, "Copies of dropped files and leftover temp files from conversions."),
    h("div", { class: "stat" }, d.app_cache_h),
    h("button", { class: "btn ghost", onclick: async () => { try { const r = await api("/api/clean/app", {}); toast(`Freed ${r.freed_h}`); renderCleanup(); } catch (e) { fail(e); } } }, "Clear app cache"));

  const tempTotal = d.temp.reduce((a, t) => a + t.size, 0);
  const age = h("select", {}, h("option", { value: "24" }, "older than 1 day"), h("option", { value: "168" }, "older than 1 week"), h("option", { value: "1" }, "older than 1 hour"));
  const tempChecks = d.temp.map((t) => { const c = h("input", { type: "checkbox" }); c.checked = true; c.value = t.path; return [c, t]; });
  const tempCard = h("div", { class: "card" }, h("h3", {}, "temp_files"), h("p", { class: "muted sm" }, "Windows & app temp folders. Files in use are skipped automatically."),
    h("div", { class: "stat" }, fmt(tempTotal)),
    ...tempChecks.map(([c, t]) => h("div", { class: "loc" }, c, h("span", { title: t.path }, t.path), h("b", {}, t.size_h))),
    h("div", { class: "row", style: "margin-top:10px" }, age, h("button", { class: "btn", onclick: async () => {
      const paths = tempChecks.filter(([c]) => c.checked).map(([c]) => c.value);
      if (!paths.length || !(await ask(`Permanently delete temp files ${age.selectedOptions[0].text} in ${paths.length} folder(s)?`, { danger: true, yes: "Delete" }))) return;
      try { const r = await api("/api/clean/temp", { paths, min_age_hours: +age.value }); toast(`Freed ${r.freed_h} · ${r.deleted} files deleted, ${r.skipped} skipped`); renderCleanup(); } catch (e) { fail(e); }
    } }, "Clean temp files")));

  const rb = d.recycle_bin;
  const rbCard = h("div", { class: "card" }, h("h3", {}, "recycle_bin"), h("p", { class: "muted sm" }, "Everything this app removes goes here first, so you can undo."),
    h("div", { class: "stat" }, rb ? rb.size_h : "—"), h("p", { class: "muted sm", style: "margin-top:-8px" }, rb ? `${rb.items} item(s)` : ""),
    h("button", { class: "btn danger", disabled: !rb || !rb.items, onclick: async () => {
      if (!(await ask("Empty the Recycle Bin? This can't be undone.", { danger: true, yes: "Empty it" }))) return;
      try { const r = await api("/api/clean/recycle-bin", {}); toast(`Freed ${r.freed_h}`); renderCleanup(); } catch (e) { fail(e); }
    } }, "Empty Recycle Bin"));

  // finders
  const folderIn = h("input", { type: "text", value: store.get("cleanFolder", ""), placeholder: "Folder to scan, e.g. C:\\Users\\you\\Downloads", style: "flex:1;min-width:260px" });
  const minIn = h("input", { type: "number", value: cleanTab === "large" ? 100 : 1, style: "width:90px" });
  const results = h("div", { class: "results" });
  const scanBtn = h("button", { class: "btn" }, "Scan");
  const tabs = h("div", { class: "tabs" }, ...[["duplicates", "Duplicate files"], ["large", "Large files"], ["empty", "Empty folders"]].map(([k, l]) =>
    h("button", { class: cleanTab === k ? "on" : "", onclick: () => { cleanTab = k; renderCleanup(); } }, l)));
  const minLabel = { duplicates: "Min KB", large: "Min MB", empty: null }[cleanTab];
  scanBtn.onclick = async () => {
    const folder = folderIn.value.trim();
    if (!folder) return toast("Choose a folder to scan", true);
    store.set("cleanFolder", folder);
    results.replaceChildren(h("div", { class: "row muted" }, h("span", { class: "spinner" }), "Scanning… big folders can take a while"));
    scanBtn.disabled = true;
    try {
      const r = await api("/api/clean/scan", { kind: cleanTab, folder, min_kb: minIn.value === "" ? 1 : +minIn.value, min_mb: minIn.value === "" ? 100 : +minIn.value });
      renderFindings(results, r);
    } catch (e) { fail(e); results.replaceChildren(); }
    scanBtn.disabled = false;
  };
  const finder = h("div", { class: "card", style: "margin-top:14px" }, h("h3", {}, "find_clutter.exe"),
    h("p", { class: "muted sm" }, "Selected items go to the Recycle Bin. Nothing is deleted without your say-so."), tabs,
    h("div", { class: "row" }, folderIn,
      h("button", { class: "btn ghost", onclick: async () => { const r = await api("/api/pick/folder", { title: "Folder to scan" }).catch(fail); if (r?.path) folderIn.value = r.path; } }, "Browse…"),
      minLabel ? h("span", { class: "muted sm" }, minLabel) : null, minLabel ? minIn : null, scanBtn),
    results);
  v.replaceChildren(h("div", { class: "clean-grid" }, disks, appCard, tempCard, rbCard), finder);
}
const fmt = (n) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return (i ? n.toFixed(1) : n) + " " + u[i]; };

function renderFindings(box, r) {
  const checks = [];
  const item = (path, size, checked, extra) => {
    const c = h("input", { type: "checkbox" }); c.checked = checked; c.value = path; checks.push(c);
    return h("div", { class: "res-item" }, c, h("label", { title: path, onclick: () => (c.checked = !c.checked) }, path), extra, size ? h("span", { class: "sz" }, size) : null,
      h("a", { class: "sm", style: "color:var(--accent);cursor:pointer", onclick: () => api("/api/open", { path }).catch(fail) }, "Show"));
  };
  const body = h("div");
  let summary = "";
  if (r.groups) {
    summary = r.groups.length ? `${r.groups.length} duplicate groups · ${r.wasted_h} reclaimable. The oldest copy in each group is kept unless you tick it.` : "No duplicates found 🎉";
    for (const g of r.groups.slice(0, 500)) body.append(h("div", { class: "dup-group" }, h("div", { class: "gh" }, `${g.files.length} copies · ${g.size_h} each`),
      ...g.files.map((p, i) => item(p, null, i > 0, i === 0 ? h("span", { class: "orig" }, "KEEP") : null))));
  } else if (r.files) {
    summary = r.files.length ? `${r.files.length} large files (biggest first). Tick the ones you want gone.` : "No files above that size.";
    for (const f of r.files) body.append(item(f.path, f.size_h, false));
  } else if (r.folders) {
    summary = r.folders.length ? `${r.folders.length} empty folders.` : "No empty folders.";
    for (const p of r.folders) body.append(item(p, null, true));
  }
  const go = h("button", { class: "btn danger", onclick: async () => {
    const paths = checks.filter((c) => c.checked).map((c) => c.value);
    if (!paths.length) return toast("Nothing selected");
    if (!(await ask(`Move ${paths.length} item(s) to the Recycle Bin? You can restore them from there.`, { yes: "Recycle" }))) return;
    try {
      const res = await api("/api/clean/recycle", { paths });
      toast(`Recycled ${res.recycled.length} item(s)` + (res.freed ? ` · ${res.freed_h}` : "") + (res.failed.length ? ` · ${res.failed.length} failed` : ""));
      checks.filter((c) => res.recycled.includes(c.value)).forEach((c) => c.closest(".res-item").remove());
    } catch (e) { fail(e); }
  } }, "Move selected to Recycle Bin");
  box.replaceChildren(h("div", { class: "row", style: "margin-bottom:10px" }, h("span", { class: "muted" }, summary), h("span", { class: "spacer" }), checks.length || r.groups?.length || r.files?.length || r.folders?.length ? go : null), body);
}
