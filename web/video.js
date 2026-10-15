/* Video editor (video_editor.exe): media bin, timeline preview, inspector, multi-track timeline, export.
   The project is plain JSON (see core/video_editor.py). Timeline maths in clipDur()/layout() mirrors the Python side. */
(function () {
  const { $, h, api, toast, fail, ask, S, store, pickFiles, mascotImg, titlebar } = window.App;

  if (!document.querySelector('link[href="/web/video.css"]')) document.head.append(h("link", { rel: "stylesheet", href: "/web/video.css" }));

  const VIDEO_EXT = ["mp4", "mkv", "mov", "avi", "webm", "flv", "wmv", "m4v", "mpeg", "mpg", "3gp", "ts", "mts", "m2ts", "ogv", "vob", "gif"];
  const AUDIO_EXT = ["mp3", "wav", "aac", "flac", "ogg", "m4a", "opus", "wma", "aiff", "aif", "amr", "ac3", "mka"];
  const IMAGE_EXT = ["png", "jpg", "jpeg", "jfif", "webp", "bmp", "tif", "tiff"];
  const MEDIA_EXT = new Set([...VIDEO_EXT, ...AUDIO_EXT, ...IMAGE_EXT]);
  const PROJECT_EXT = "drdocvideo";
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4];
  const SNAP_PX = 8;

  const uid = () => Math.random().toString(36).slice(2, 10);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const num = (v, d = 0) => (Number.isFinite(+v) ? +v : d);
  const r3 = (v) => Math.round(v * 1000) / 1000;
  const enc = encodeURIComponent;
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // ------------------------------------------------------------ state
  const newProject = () => ({ media: [], clips: [], texts: [], music: [], music_mode: "mix",
    export: { format: "mp4", resolution: "1080p", aspect: "keep", fit: "pad", fps: "source", crf: 20 } });
  const V = {
    P: newProject(), name: "my video", path: null, sel: null, t: 0, playing: false, zoom: 60, snap: true,
    marks: { in: null, out: null }, undo: [], redo: [], root: null, dom: null, els: {}, aels: {}, waves: {},
    ready: new Set(), proxyPoll: {}, loaded: false, last: 0, textKey: "", helpOpen: false,
  };

  // ------------------------------------------------------------ timeline maths (mirrors core/video_editor.py)
  const mediaOf = (id) => V.P.media.find((m) => m.id === id);
  const speedOf = (c) => clamp(num(c.speed, 1), 0.25, 4);
  const clipDur = (c) => (c.kind === "image" ? Math.max(0.1, num(c.dur, 4)) : Math.max(0.04, (num(c.out) - num(c.in)) / speedOf(c)));
  function layout(clips = V.P.clips) {
    const out = []; let t = 0, prev = 0;
    clips.forEach((c, i) => {
      const d = clipDur(c);
      let xd = 0;
      if (i && c.trans?.type === "crossfade") xd = r3(Math.max(0, Math.min(num(c.trans.dur, 1), prev / 2, d / 2)));
      const start = Math.max(0, t - xd);
      out.push({ c, i, start, dur: d, xd, end: start + d, m: mediaOf(c.media) });
      t = start + d; prev = d;
    });
    return out;
  }
  const mainTotal = () => { const L = layout(); return L.length ? L[L.length - 1].end : 0; };
  const musicEnd = () => Math.max(0, ...V.P.music.map((m) => m.start + (m.out - m.in)));
  const projectEnd = () => Math.max(mainTotal(), V.P.clips.length ? 0 : musicEnd());
  const fpsOf = () => {
    const f = V.P.export.fps;
    if (f && f !== "source") return +f;
    const v = V.P.clips.map((c) => mediaOf(c.media)).find((m) => m?.kind === "video");
    return Math.min(60, v?.fps || 30);
  };

  // ------------------------------------------------------------ formatting
  function tc(t, fps = fpsOf()) {
    t = Math.max(0, t || 0);
    const f = Math.floor((t % 1) * fps + 1e-6), s = Math.floor(t) % 60, m = Math.floor(t / 60) % 60, hr = Math.floor(t / 3600);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(hr)}:${p(m)}:${p(s)}:${p(f)}`;
  }
  function dur(t) {
    t = Math.max(0, t || 0);
    const m = Math.floor(t / 60), s = t - m * 60;
    return m ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${s.toFixed(1)}s`;
  }

  // ------------------------------------------------------------ history + autosave
  function snapshot() { V.undo.push(JSON.stringify(V.P)); if (V.undo.length > 200) V.undo.shift(); V.redo = []; }
  function undo() { if (!V.undo.length) return toast("Nothing to undo"); V.redo.push(JSON.stringify(V.P)); V.P = JSON.parse(V.undo.pop()); fixSel(); commit(); }
  function redo() { if (!V.redo.length) return toast("Nothing to redo"); V.undo.push(JSON.stringify(V.P)); V.P = JSON.parse(V.redo.pop()); fixSel(); commit(); }
  function fixSel() { if (V.sel && !findSel()) V.sel = null; }
  let saveTimer;
  function autosave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => store.set("video.autosave", { P: V.P, name: V.name, path: V.path, zoom: V.zoom }), 300);
  }
  /** Re-render everything that depends on the project after a change. */
  function commit({ inspector = true } = {}) {
    autosave();
    if (!V.dom) return mount(V.root);
    renderTitle(); renderBin(); renderTimeline(); if (inspector) renderInspector(); layoutStage(); syncPreview(true);
  }
  /** Cheap update while dragging a slider/handle (no inspector rebuild, no autosave spam). */
  function light() { renderTimeline(); syncPreview(true); }

  // ------------------------------------------------------------ selection
  const TRACK = { v: "clips", t: "texts", a: "music" };
  function findSel(sel = V.sel) { return sel ? V.P[TRACK[sel.track]].find((x) => x.id === sel.id) : null; }
  function select(track, id) {
    V.sel = track ? { track, id } : null;
    renderTimeline(); renderInspector(); syncPreview(true);
  }

  // ------------------------------------------------------------ mount / empty state
  function mount(container) {
    V.root = container;
    if (!V.loaded) {
      V.loaded = true;
      const saved = store.get("video.autosave", null);
      if (saved?.P) { V.P = Object.assign(newProject(), saved.P); V.P.export = Object.assign(newProject().export, saved.P.export); V.name = saved.name || V.name; V.path = saved.path || null; V.zoom = saved.zoom || V.zoom; }
      V.P.media.forEach((m) => { if (!m.playable && !m.missing) ensureProxy(m); });
    }
    if (!V.P.media.length && !V.P.clips.length && !V.P.music.length) return renderEmpty();
    if (V.dom && container.contains(V.dom.root)) { renderAll(); return; }
    build();
  }

  function renderEmpty() {
    V.dom = null;
    V.root.replaceChildren(h("div", { class: "ve-empty" }, h("div", { class: "win" }, titlebar("video_editor.exe — no project"),
      h("div", { class: "ve-empty-body" },
        mascotImg("float"),
        h("h2", {}, "make a movie ✦"),
        h("p", { class: "muted" }, "Trim and split clips, join videos and photos, change speed, add text, music and crossfades, crop, rotate and colour-correct, then export to MP4, WebM, GIF or audio. Everything stays on this PC and your originals are never touched."),
        h("div", { class: "row", style: "justify-content:center" },
          h("button", { class: "btn big", onclick: browse }, "🎬 Add videos"),
          h("button", { class: "btn ghost", onclick: openProject }, "📂 Open project")),
        h("p", { class: "muted sm" }, "or drop videos, photos and music anywhere on this page")))));
  }

  // ------------------------------------------------------------ layout
  const ib = (icon, label, onclick, extra = {}) => h("button", { class: "tb", type: "button", title: label, "aria-label": label, onclick, ...extra }, icon);

  function build() {
    const d = V.dom = {};
    d.title = h("span", {});
    d.undoBtn = ib("↶", "Undo (Ctrl+Z)", undo); d.redoBtn = ib("↷", "Redo (Ctrl+Y)", redo);
    d.help = h("div", { class: "ve-help win", hidden: true, role: "dialog", "aria-label": "Keyboard shortcuts" });
    const bar = h("div", { class: "ve-bar win" }, h("div", { class: "titlebar" }, d.title),
      h("div", { class: "ve-tools" },
        h("button", { class: "tb", type: "button", title: "Add videos, photos or music", "aria-label": "Add media", onclick: browse }, "📂", h("span", { class: "sm" }, "Add media")),
        ib("🗁", "Open project (.drdocvideo)", openProject),
        ib("💾", "Save project (Ctrl+S)", saveProject),
        ib("✚", "New project", newProjectAsk),
        h("span", { class: "sep" }),
        d.undoBtn, d.redoBtn,
        h("span", { class: "sep" }),
        h("button", { class: "tb", type: "button", title: "Split at playhead (S)", "aria-label": "Split at playhead", onclick: split }, "✂", h("span", { class: "sm" }, "Split")),
        ib("⧉", "Duplicate selected (Ctrl+D)", duplicate),
        ib("🗑", "Delete selected (Del)", del),
        h("span", { class: "sep" }),
        h("button", { class: "tb", type: "button", title: "Add text at playhead (T)", "aria-label": "Add text", onclick: addText }, "T", h("span", { class: "sm" }, "Text")),
        h("button", { class: "tb", type: "button", title: "Add music", "aria-label": "Add music", onclick: () => browse("audio") }, "♪", h("span", { class: "sm" }, "Music")),
        h("span", { class: "spacer" }),
        ib("?", "Keyboard shortcuts (?)", toggleHelp, { "aria-haspopup": "dialog" }),
        h("button", { class: "btn", type: "button", onclick: openExport, title: "Export video (Ctrl+E)" }, "⬇ Export")), d.help);

    // media bin
    d.bin = h("div", { class: "ve-bin-list", role: "list", "aria-label": "Media bin" });
    const bin = h("div", { class: "ve-bin win" }, titlebar("media bin"), d.bin,
      h("div", { class: "ve-bin-foot" }, h("button", { class: "btn sm", type: "button", onclick: browse }, "＋ Browse…")));

    // preview
    d.stage = h("div", { class: "ve-stage", "aria-label": "Preview" });
    d.textLayer = h("div", { class: "ve-text-layer" });
    d.msg = h("div", { class: "ve-msg", hidden: true });
    d.stage.append(d.textLayer, d.msg);
    d.stageWrap = h("div", { class: "ve-stage-wrap" }, d.stage);
    d.playBtn = ib("▶", "Play (Space)", togglePlay, { class: "tb play" });
    d.tc = h("span", { class: "ve-tc", "aria-live": "off" });
    d.size = h("span", { class: "sm muted ve-size" });
    const view = h("div", { class: "ve-view win" }, titlebar("preview"), d.stageWrap,
      h("div", { class: "ve-transport" },
        ib("⏮", "Go to start (Home)", () => seek(0)),
        ib("◀|", "Previous frame (←)", () => seek(V.t - 1 / fpsOf())),
        d.playBtn,
        ib("|▶", "Next frame (→)", () => seek(V.t + 1 / fpsOf())),
        ib("⏭", "Go to end (End)", () => seek(projectEnd())),
        d.tc, h("span", { class: "spacer" }), d.size));

    // inspector
    d.insp = h("div", { class: "ve-insp-body" });
    const insp = h("div", { class: "ve-insp win" }, titlebar("inspector"), d.insp);

    // timeline
    d.zoom = h("input", { type: "range", min: 5, max: 400, step: 1, value: V.zoom, title: "Timeline zoom", "aria-label": "Timeline zoom" });
    d.zoom.oninput = () => setZoom(+d.zoom.value, true);
    d.snapBtn = ib("🧲", "Snap to edges and playhead (hold Alt to bypass)", () => { V.snap = !V.snap; d.snapBtn.classList.toggle("on", V.snap); d.snapBtn.setAttribute("aria-pressed", V.snap); });
    d.snapBtn.classList.toggle("on", V.snap); d.snapBtn.setAttribute("aria-pressed", V.snap);
    d.marksLabel = h("span", { class: "sm muted" });
    const tlbar = h("div", { class: "ve-tl-bar" },
      ib("−", "Zoom out (−)", () => setZoom(V.zoom / 1.4)), d.zoom, ib("+", "Zoom in (+)", () => setZoom(V.zoom * 1.4)),
      ib("↔", "Fit timeline to window", fitZoom), d.snapBtn,
      h("span", { class: "sep" }),
      ib("[", "Mark range start at playhead (I)", () => setMark("in")), ib("]", "Mark range end at playhead (O)", () => setMark("out")),
      ib("⌫", "Clear range marks", () => { V.marks = { in: null, out: null }; renderTimeline(); }), d.marksLabel,
      h("span", { class: "spacer" }),
      h("span", { class: "sm muted" }, "drag clips to reorder · drag edges to trim"));
    d.lane = h("div", { class: "ve-lane" });
    d.scroll = h("div", { class: "ve-scroll" }, d.lane);
    const heads = h("div", { class: "ve-heads", "aria-hidden": "true" }, h("div", { class: "ve-head ruler" }),
      h("div", { class: "ve-head v" }, "▶ video"), h("div", { class: "ve-head t" }, "T text"), h("div", { class: "ve-head a" }, "♪ music"));
    const tl = h("div", { class: "ve-tl win" }, titlebar("timeline"), tlbar, h("div", { class: "ve-tl-body" }, heads, d.scroll));

    d.root = h("div", { class: "ve" }, bar, h("div", { class: "ve-mid" }, bin, view, insp), tl);
    V.root.replaceChildren(d.root);

    // mouse clicks shouldn't leave focus on toolbar buttons (Space must keep meaning play/pause)
    d.root.addEventListener("mousedown", (e) => { if (e.target.closest("button.tb, button.btn") && !e.target.closest(".ve-insp")) e.preventDefault(); });
    d.lane.addEventListener("pointerdown", onLaneDown);
    d.lane.addEventListener("dragover", onLaneDragOver);
    d.lane.addEventListener("drop", onLaneDrop);
    d.lane.addEventListener("dblclick", (e) => { const el = e.target.closest(".ve-clip"); if (el?.dataset.track === "t") setTimeout(() => $(".ve-insp textarea")?.focus(), 0); });
    d.textLayer.addEventListener("pointerdown", onTextDown);
    d.scroll.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); setZoom(V.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)); } }, { passive: false });
    new ResizeObserver(() => { layoutStage(); syncPreview(true); }).observe(d.stageWrap);
    V.els = {};  // the old stage is gone, so are its media elements
    renderAll();
  }

  function renderAll() { renderTitle(); renderBin(); renderTimeline(); renderInspector(); layoutStage(); syncPreview(true); }
  function renderTitle() {
    if (!V.dom) return;
    V.dom.title.textContent = `video_editor.exe — ${V.name}${V.path ? "" : " (unsaved)"}`;
    V.dom.undoBtn.disabled = !V.undo.length; V.dom.redoBtn.disabled = !V.redo.length;
  }

  // ------------------------------------------------------------ media bin
  function renderBin() {
    const d = V.dom; if (!d) return;
    const used = new Set([...V.P.clips, ...V.P.music].map((c) => c.media));
    if (!V.P.media.length) { d.bin.replaceChildren(h("div", { class: "sm muted ve-bin-empty" }, "Drop videos, photos or music here, or use Browse.")); return; }
    d.bin.replaceChildren(...V.P.media.map((m) => {
      const meta = [m.kind === "image" ? "photo" : dur(m.duration), m.width ? `${m.width}×${m.height}` : null, m.kind === "video" && !m.has_audio ? "no audio" : null].filter(Boolean).join(" · ");
      const badge = m.missing ? h("span", { class: "ve-badge err" }, "missing") : (!m.playable && !isReady(m)) ? h("span", { class: "ve-badge" }, "preparing preview…") : null;
      const thumbEl = m.kind === "audio" || m.missing ? h("div", { class: "ve-bin-ico" }, m.kind === "audio" ? "♪" : "?")
        : h("img", { src: `/api/video/thumb?path=${enc(m.path)}&t=${m.kind === "video" ? Math.min(1, m.duration / 3).toFixed(2) : 0}&h=90`, alt: "", loading: "lazy", draggable: "false" });
      const item = h("div", { class: "ve-bin-item" + (used.has(m.id) ? " used" : ""), role: "listitem", draggable: "true", title: m.path,
        ondblclick: () => addToTimeline(m) },
        thumbEl,
        h("div", { class: "ve-bin-txt" }, h("div", { class: "ve-bin-name" }, m.name), h("div", { class: "sm muted" }, meta), badge),
        h("div", { class: "ve-bin-btns" },
          h("button", { class: "tb", type: "button", title: `Add ${m.name} to the ${m.kind === "audio" ? "music track" : "timeline"}`, "aria-label": `Add ${m.name} to timeline`, onclick: () => addToTimeline(m) }, "＋"),
          h("button", { class: "tb", type: "button", title: `Remove ${m.name} from the project`, "aria-label": `Remove ${m.name}`, onclick: () => removeMedia(m) }, "✕")));
      item.addEventListener("dragstart", (e) => { e.dataTransfer.setData("application/x-drdoc-media", m.id); e.dataTransfer.effectAllowed = "copy"; });
      return item;
    }));
  }

  async function browse(kind) {
    try {
      const files = await pickFiles();
      if (files.length) await addFiles(files, { musicOnly: kind === "audio" });
    } catch (e) { fail(e); }
  }

  const extKind = (e) => (VIDEO_EXT.includes(e) ? "video" : AUDIO_EXT.includes(e) ? "audio" : IMAGE_EXT.includes(e) ? "image" : null);

  /** Files from the picker or a drop: [{path, name, ext}] */
  async function addFiles(files, { musicOnly = false } = {}) {
    try {
      const proj = files.find((f) => f.ext === PROJECT_EXT || f.path.toLowerCase().endsWith("." + PROJECT_EXT));
      if (proj) return loadProject(proj.path);
      const ok = files.filter((f) => MEDIA_EXT.has(f.ext) || extKind(f.path.split(".").pop().toLowerCase()));
      if (ok.length < files.length) toast(`${files.length - ok.length} file(s) skipped: not a video, photo or audio file`, true);
      if (!ok.length) return;
      const d = await api("/api/video/info", { paths: ok.map((f) => f.path) });
      d.errors.forEach((e) => toast(e, true, 6000));
      if (!d.media.length) return;
      snapshot();
      const wasEmpty = !V.P.clips.length && !V.P.music.length;
      const added = [];
      for (const info of d.media) {
        let m = V.P.media.find((x) => x.path === info.path);
        if (!m) { m = { ...info, id: uid() }; V.P.media.push(m); } else Object.assign(m, info, { missing: false });
        if (m.proxy_ready) V.ready.add(m.path);
        added.push(m);
        ensureProxy(m);
      }
      if (wasEmpty || musicOnly) {
        for (const m of added) if (!musicOnly || m.kind === "audio") placeMedia(m);
        if (wasEmpty && added.length && !V.sel) {
          const c = V.P.clips[0]; if (c) V.sel = { track: "v", id: c.id };
          if (V.P.clips.length) V.P.export.aspect = "keep";
        }
      } else toast(`Added ${added.length} file(s) to the media bin: drag them onto the timeline or press ＋`);
      commit();
    } catch (e) { fail(e); }
  }

  /** New clip objects with every field the exporter understands. */
  function newClip(m) {
    const c = { id: uid(), media: m.id, kind: m.kind, in: 0, out: m.kind === "image" ? 0 : r3(m.duration), speed: 1, volume: 1, muted: false,
      fade_in: 0, fade_out: 0, rotate: 0, crop: { t: 0, b: 0, l: 0, r: 0 }, eq: { brightness: 0, contrast: 1, saturation: 1 }, trans: { type: "none", dur: 1 } };
    if (m.kind === "image") c.dur = 4;
    return c;
  }
  function placeMedia(m, { index = null, at = null } = {}) {
    if (m.missing) return toast("That file is missing", true);
    if (m.kind === "audio") {
      const mu = { id: uid(), media: m.id, start: r3(at ?? musicEnd()), in: 0, out: r3(m.duration), volume: 1, fade_in: 0, fade_out: 0 };
      V.P.music.push(mu); return mu;
    }
    const c = newClip(m);
    V.P.clips.splice(index ?? V.P.clips.length, 0, c);
    return c;
  }
  function addToTimeline(m) {
    snapshot();
    const item = placeMedia(m);
    if (item) V.sel = { track: m.kind === "audio" ? "a" : "v", id: item.id };
    commit();
  }
  async function removeMedia(m) {
    const uses = V.P.clips.filter((c) => c.media === m.id).length + V.P.music.filter((c) => c.media === m.id).length;
    if (uses && !(await ask(`“${m.name}” is used ${uses} time(s) on the timeline. Remove it and those clips?`, { danger: true, yes: "Remove" }))) return;
    snapshot();
    V.P.clips = V.P.clips.filter((c) => c.media !== m.id);
    V.P.music = V.P.music.filter((c) => c.media !== m.id);
    V.P.media = V.P.media.filter((x) => x.id !== m.id);
    fixSel();
    if (!V.P.media.length) { renderEmpty(); autosave(); return; }
    commit();
  }

  // ------------------------------------------------------------ preview proxies
  const isReady = (m) => m.playable || V.ready.has(m.path);
  function mediaSrc(m) {
    if (m.missing) return null;
    if (m.playable) return `/api/video/media?path=${enc(m.path)}`;
    return V.ready.has(m.path) ? `/api/video/media?path=${enc(m.path)}&proxy=1` : null;
  }
  async function ensureProxy(m) {
    if (m.playable || m.missing || V.ready.has(m.path) || V.proxyPoll[m.path]) return;
    try {
      const d = await api("/api/video/proxy", { path: m.path });
      if (d.ready) return proxyReady(m.path);
      window.App.watchJobs();
      V.proxyPoll[m.path] = setInterval(async () => {
        try {
          const s = await api(`/api/video/proxy?path=${enc(m.path)}`);
          if (s.ready) proxyReady(m.path);
          else if (["error", "cancelled", "none"].includes(s.status)) {
            clearInterval(V.proxyPoll[m.path]); delete V.proxyPoll[m.path];
            if (s.status === "error") toast(`Couldn't prepare a preview for ${m.name}: ${s.error || "error"}. It will still export.`, true, 7000);
          }
        } catch { /* server busy: try again next tick */ }
      }, 1500);
    } catch (e) { fail(e); }
  }
  function proxyReady(path) {
    clearInterval(V.proxyPoll[path]); delete V.proxyPoll[path];
    V.ready.add(path);
    for (const m of V.P.media.filter((x) => x.path === path)) {
      m.proxy_ready = true;
      const el = V.els[m.id];
      if (el) { el.remove(); delete V.els[m.id]; }
    }
    if (V.dom) { renderBin(); syncPreview(true); }
  }

  // ------------------------------------------------------------ preview
  function frameSize() {
    const ex = V.P.export;
    const A = { "16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1, "4:3": 4 / 3, "4:5": 4 / 5 }[ex.aspect];
    const first = layout().find((x) => x.m && x.m.kind !== "audio");
    let w = 1920, hh = 1080;
    if (first) [w, hh] = visualSize(first.c, first.m);
    return A ? [A * 1000, 1000] : [w, hh];
  }
  function visualSize(c, m) {
    let w = Math.max(2, m.width || 1280), hh = Math.max(2, m.height || 720);
    const cr = c.crop || {};
    w *= Math.max(0.05, 1 - num(cr.l) - num(cr.r)); hh *= Math.max(0.05, 1 - num(cr.t) - num(cr.b));
    return (num(c.rotate) % 180 === 90) ? [hh, w] : [w, hh];
  }
  function layoutStage() {
    const d = V.dom; if (!d) return;
    const [fw, fh] = frameSize();
    const W = d.stageWrap.clientWidth - 16, H = d.stageWrap.clientHeight - 16;
    if (W <= 0 || H <= 0) return;
    const k = Math.min(W / fw, H / fh);
    d.stage.style.width = Math.round(fw * k) + "px"; d.stage.style.height = Math.round(fh * k) + "px";
    V.stageW = Math.round(fw * k); V.stageH = Math.round(fh * k);
    const [ow, oh] = outSize();
    d.size.textContent = V.P.export.format === "mp3" || V.P.export.format === "wav" ? "audio export" : `${ow}×${oh} · ${fpsOf()} fps`;
    V.textKey = "";
  }
  /** Rough mirror of export_size() in Python, for labels only. */
  function outSize(ex = V.P.export) {
    const [fw, fh] = frameSize();
    const even = (x) => Math.max(2, Math.round(x / 2) * 2);
    if (ex.resolution === "custom") return [even(num(ex.width, 1920)), even(num(ex.height, 1080))];
    const first = layout().find((x) => x.m && x.m.kind !== "audio");
    const [sw, sh] = first ? visualSize(first.c, first.m) : [1920, 1080];
    const a = fw / fh;
    let short = { "2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360 }[ex.resolution];
    if (!short) short = (!ex.aspect || ex.aspect === "keep") ? Math.min(sw, sh) : Math.min(sw, sh, Math.max(sw, sh) / Math.max(a, 1 / a));
    let w = a >= 1 ? even(short * a) : even(short), hh = a >= 1 ? even(short) : even(short / a);
    if (ex.format === "gif" && Math.max(w, hh) > 640) { const k = 640 / Math.max(w, hh); w = even(w * k); hh = even(hh * k); }
    return [w, hh];
  }

  function poolEl(m) {
    let el = V.els[m.id];
    if (el) return el;
    const src = mediaSrc(m);
    if (!src || m.kind === "audio") return null;
    if (m.kind === "image") el = h("img", { class: "ve-media", src, alt: "", draggable: "false" });
    else {
      el = h("video", { class: "ve-media", src, preload: "auto", playsinline: true, disablepictureinpicture: true });
      el.addEventListener("waiting", () => V.dom?.stage.classList.add("buffering"));
      el.addEventListener("playing", () => V.dom?.stage.classList.remove("buffering"));
    }
    V.els[m.id] = el;
    V.dom.stage.insertBefore(el, V.dom.textLayer);
    return el;
  }

  /** Which main-track clip is visible at time t (crossfades switch halfway through the overlap). */
  function activeAt(t, L = layout()) {
    let cur = null;
    for (const it of L) { if (t >= it.start + it.xd / 2 - 1e-6) cur = it; else break; }
    if (cur && t >= cur.end) cur = (L.length && t >= L[L.length - 1].end - 1e-6 && t - L[L.length - 1].end < 1e-3) ? cur : null;
    return cur;
  }
  const srcTime = (it, t) => clamp(num(it.c.in) + (t - it.start) * speedOf(it.c), num(it.c.in), Math.max(num(it.c.in), num(it.c.out) - 0.02));

  function place(el, c, m) {
    const W = V.stageW, H = V.stageH;
    const sw = Math.max(2, m.width || W), sh = Math.max(2, m.height || H);
    const cr = c.crop || {}, l = num(cr.l), r = num(cr.r), t = num(cr.t), b = num(cr.b);
    const cw = sw * (1 - l - r), ch = sh * (1 - t - b);
    const rot = num(c.rotate) % 360, q = rot % 180 === 90;
    const dw = q ? ch : cw, dh = q ? cw : ch;
    const s = (V.P.export.fit === "crop" ? Math.max : Math.min)(W / dw, H / dh);
    const cx = (l * sw + cw / 2) * s, cy = (t * sh + ch / 2) * s;
    Object.assign(el.style, { width: sw * s + "px", height: sh * s + "px", left: W / 2 - cx + "px", top: H / 2 - cy + "px",
      transformOrigin: `${cx}px ${cy}px`, transform: rot ? `rotate(${rot}deg)` : "",
      clipPath: l || r || t || b ? `inset(${t * 100}% ${r * 100}% ${b * 100}% ${l * 100}%)` : "" });
    const eq = c.eq || {};
    const br = num(eq.brightness), co = num(eq.contrast, 1), sa = num(eq.saturation, 1);
    el.style.filter = br || co !== 1 || sa !== 1 ? `brightness(${1 + br}) contrast(${co}) saturate(${sa})` : "";
  }

  function fadeAt(it, t, L) {
    const local = t - it.start, c = it.c;
    let op = 1;
    if (num(c.fade_in) > 0 && local < c.fade_in) op = Math.min(op, local / c.fade_in);
    if (num(c.fade_out) > 0 && local > it.dur - c.fade_out) op = Math.min(op, (it.dur - local) / c.fade_out);
    if (it.xd) op = Math.min(op, 0.5 + (local - it.xd / 2) / it.xd);  // dip during a crossfade
    const next = L[it.i + 1];
    if (next?.xd && t > next.start) op = Math.min(op, 0.5 + (next.start + next.xd / 2 - t) / next.xd);
    return clamp(op, 0, 1);
  }

  /** Bring the <video>/<img>/<audio> elements and text overlays in line with the playhead. */
  function syncPreview(force) {
    const d = V.dom; if (!d) return;
    const L = layout(), t = V.t;
    const it = activeAt(t, L);
    const el = it?.m ? poolEl(it.m) : null;
    for (const [id, e] of Object.entries(V.els)) {
      const on = e === el;
      e.classList.toggle("on", on);
      if (!on && e.tagName === "VIDEO" && !e.paused) e.pause();
      if (!V.P.media.some((m) => m.id === id)) { e.remove(); delete V.els[id]; }
    }
    let msg = "";
    if (!L.length) msg = V.P.music.length ? "♪ music only: add a video or photo for pictures" : "Add a clip to the timeline to start";
    else if (!it) msg = t >= mainTotal() ? "— end —" : "";
    else if (it.m?.missing) msg = `File missing: ${it.m.name}`;
    else if (!el) msg = "Preparing a preview copy of this clip… (it exports at full quality either way)";
    d.msg.hidden = !msg; d.msg.textContent = msg;
    if (el && it) {
      place(el, it.c, it.m);
      el.style.opacity = fadeAt(it, t, L);
      if (el.tagName === "VIDEO") {
        const c = it.c;
        el.playbackRate = speedOf(c);
        const vol = num(c.volume, 1);
        el.muted = !!c.muted || vol <= 0 || V.P.music_mode === "replace" || !it.m.has_audio;
        el.volume = clamp(vol, 0, 1) * (V.previewVol ?? 1);
        el.preload = "auto";
        const want = srcTime(it, t);
        if (V.playing) {
          if (force === "seek" || (!el.seeking && Math.abs(el.currentTime - want) > 0.5)) el.currentTime = want;
          if (el.paused) el.play().catch(() => {});
        } else {
          if (!el.paused) el.pause();
          if (Math.abs(el.currentTime - want) > 0.015) el.currentTime = want;
        }
      }
    }
    syncMusic(it);
    renderTexts();
    drawPlayhead();
  }

  function syncMusic(active) {
    const ids = new Set(V.P.music.map((m) => m.id));
    for (const [id, a] of Object.entries(V.aels)) if (!ids.has(id)) { a.pause(); delete V.aels[id]; }
    const voice = active && active.c.kind === "video" && active.m?.has_audio && !active.c.muted && V.P.music_mode !== "replace";
    for (const mu of V.P.music) {
      const m = mediaOf(mu.media); if (!m) continue;
      const src = mediaSrc(m);
      let a = V.aels[mu.id];
      if (!a && src) { a = V.aels[mu.id] = new Audio(src); a.preload = "auto"; }
      if (!a) continue;
      const len = mu.out - mu.in, local = V.t - mu.start;
      if (V.playing && local >= 0 && local < len) {
        let v = clamp(num(mu.volume, 1), 0, 1);
        if (mu.fade_in > 0 && local < mu.fade_in) v *= local / mu.fade_in;
        if (mu.fade_out > 0 && local > len - mu.fade_out) v *= (len - local) / mu.fade_out;
        if (V.P.music_mode === "duck" && voice) v *= 0.3;
        a.volume = clamp(v * (V.previewVol ?? 1), 0, 1);
        const want = mu.in + local;
        if (Math.abs(a.currentTime - want) > 0.3) a.currentTime = want;
        if (a.paused) a.play().catch(() => {});
      } else if (!a.paused) a.pause();
    }
  }

  function renderTexts() {
    const d = V.dom, t = V.t;
    const vis = V.P.texts.filter((x) => t >= x.start && t < x.end);
    const key = JSON.stringify([vis, V.stageW, V.stageH, V.sel?.id]);
    if (key === V.textKey) return;
    V.textKey = key;
    d.textLayer.replaceChildren(...vis.map((x) => {
      const size = Math.max(6, V.stageH * num(x.size, 6) / 100);
      const el = h("div", { class: "ve-txt" + (V.sel?.id === x.id ? " sel" : "") + (x.box ? " box" : ""), "data-id": x.id, title: "Drag to move",
        style: `font-size:${size}px;color:${x.color || "#fff"};--boxc:${x.box_color || "#000000"};padding:${x.box ? size / 3 : 0}px` }, x.text);
      return el;
    }));
    // position after layout so text width is known: left = (W - w) * x
    for (const el of d.textLayer.children) {
      const x = V.P.texts.find((tt) => tt.id === el.dataset.id);
      el.style.left = (V.stageW - el.offsetWidth) * num(x.x, 0.5) + "px";
      el.style.top = (V.stageH - el.offsetHeight) * num(x.y, 0.9) + "px";
    }
  }

  function onTextDown(ev) {
    const el = ev.target.closest(".ve-txt"); if (!el || ev.button !== 0) return;
    ev.preventDefault();
    const x = V.P.texts.find((tt) => tt.id === el.dataset.id); if (!x) return;
    if (V.sel?.id !== x.id) select("t", x.id);
    const sx = ev.clientX, sy = ev.clientY, ox = num(x.x, 0.5), oy = num(x.y, 0.9);
    const fw = Math.max(1, V.stageW - el.offsetWidth), fh = Math.max(1, V.stageH - el.offsetHeight);
    let moved = false;
    const move = (e) => {
      if (!moved) { if (Math.hypot(e.clientX - sx, e.clientY - sy) < 3) return; moved = true; snapshot(); }
      x.x = r3(clamp(ox + (e.clientX - sx) / fw, 0, 1)); x.y = r3(clamp(oy + (e.clientY - sy) / fh, 0, 1));
      if (Math.abs(x.x - 0.5) < 0.015) x.x = 0.5;  // gentle centre snap
      V.textKey = ""; renderTexts();
    };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); if (moved) commit(); };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  }

  // ------------------------------------------------------------ transport
  function seek(t, keepPlaying = true) {
    V.t = clamp(t, 0, Math.max(projectEnd(), 0));
    if (!keepPlaying && V.playing) pause();
    syncPreview("seek");
    followPlayhead();
  }
  function togglePlay() { V.playing ? pause() : play(); }
  function play() {
    if (!V.dom) return;
    const end = projectEnd();
    if (end <= 0) return toast("Add a clip first");
    if (V.t >= end - 0.02) V.t = 0;
    V.playing = true; V.last = performance.now(); V.stall = 0;
    V.dom.playBtn.textContent = "❚❚"; V.dom.playBtn.title = "Pause (Space)"; V.dom.playBtn.setAttribute("aria-label", "Pause");
    syncPreview("seek");
    requestAnimationFrame(tick);
  }
  function pause() {
    V.playing = false;
    for (const e of Object.values(V.els)) if (e.tagName === "VIDEO") e.pause();
    for (const a of Object.values(V.aels)) a.pause();
    if (V.dom) { V.dom.playBtn.textContent = "▶"; V.dom.playBtn.title = "Play (Space)"; V.dom.playBtn.setAttribute("aria-label", "Play"); V.dom.stage.classList.remove("buffering"); }
    syncPreview(true);
  }
  function tick(now) {
    if (!V.playing) return;
    if (S.view !== "video" || !V.dom || !document.body.contains(V.dom.root)) return pause();
    const dt = Math.min(0.25, (now - V.last) / 1000); V.last = now;
    const L = layout(), it = activeAt(V.t, L);
    let t = V.t + dt;
    if (it?.c.id !== V.stallId) { V.stallId = it?.c.id; V.stall = 0; }
    if (it && it.c.kind === "video") {  // follow the video clock when it's running smoothly
      const el = V.els[it.m?.id];
      if (el && el.classList.contains("on") && !el.paused && !el.seeking && el.readyState >= 3 && !el.ended) {
        V.stall = 0;
        const tv = it.start + (el.currentTime - it.c.in) / speedOf(it.c);
        if (Math.abs(tv - t) < 0.4) t = Math.max(V.t, tv);
      } else if (el && !el.error && !el.ended && V.stall < 0.6) { V.stall += dt; t = V.t; }  // just switched/seeking: wait a moment
    }
    const end = projectEnd();
    if (t >= end) { V.t = end; pause(); return; }
    V.t = t;
    syncPreview(false);
    followPlayhead();
    requestAnimationFrame(tick);
  }
  function drawPlayhead() {
    const d = V.dom; if (!d) return;
    d.tc.textContent = `${tc(V.t)} / ${tc(projectEnd())}`;
    if (d.playhead) d.playhead.style.left = V.t * V.zoom + "px";
  }
  function followPlayhead() {
    const sc = V.dom?.scroll; if (!sc) return;
    const x = V.t * V.zoom;
    if (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = Math.max(0, x - (V.playing ? 40 : sc.clientWidth / 2));
  }
  function setZoom(z, fromSlider) {
    V.zoom = clamp(z, 5, 400);
    if (!fromSlider && V.dom) V.dom.zoom.value = V.zoom;
    renderTimeline(); followPlayhead(); autosave();
  }
  function fitZoom() {
    const end = Math.max(projectEnd(), musicEnd(), ...V.P.texts.map((x) => x.end), 5);
    setZoom((V.dom.scroll.clientWidth - 30) / end);
  }
  function setMark(which) {
    V.marks[which] = r3(V.t);
    if (V.marks.in != null && V.marks.out != null && V.marks.out < V.marks.in) [V.marks.in, V.marks.out] = [V.marks.out, V.marks.in];
    renderTimeline();
  }

  // ------------------------------------------------------------ timeline
  function rulerStep() {
    const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    return steps.find((s) => s * V.zoom >= 70) || 600;
  }
  function renderTimeline() {
    const d = V.dom; if (!d) return;
    renderTitle();
    const hadFocus = d.lane.contains(document.activeElement);
    const z = V.zoom, L = layout();
    const end = Math.max(mainTotal(), musicEnd(), ...V.P.texts.map((x) => x.end), 0);
    const width = Math.max(d.scroll.clientWidth - 4, (end + 8) * z);
    d.lane.style.width = width + "px";
    const step = rulerStep();
    const ruler = h("div", { class: "ve-ruler", style: `background-size:${step * z / 5}px 100%`, title: "Click or drag to move the playhead" });
    for (let s = 0; s * z < width; s += step) ruler.append(h("span", { style: `left:${s * z}px` }, step < 1 ? `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`));
    if (V.marks.in != null || V.marks.out != null) {
      const a = V.marks.in ?? 0, b = V.marks.out ?? mainTotal();
      ruler.append(h("div", { class: "ve-range", style: `left:${a * z}px;width:${Math.max(2, (b - a) * z)}px`, title: `Range ${tc(a)} → ${tc(b)}` }));
    }
    d.marksLabel.textContent = V.marks.in != null || V.marks.out != null ? `range ${dur(V.marks.in ?? 0)}–${dur(V.marks.out ?? mainTotal())}` : "";

    const vt = h("div", { class: "ve-track v", "data-track": "v" });
    for (const it of L) {
      const c = it.c, m = it.m || { name: "missing", kind: "video" };
      const sel = V.sel?.track === "v" && V.sel.id === c.id;
      const thumb = m.kind !== "audio" && !m.missing && m.path ? `background-image:url("/api/video/thumb?path=${enc(m.path)}&t=${m.kind === "video" ? num(c.in).toFixed(2) : 0}&h=56")` : "";
      const tags = [speedOf(c) !== 1 ? `${speedOf(c)}×` : null, c.muted ? "🔇" : null, num(c.rotate) ? `⟳${c.rotate}°` : null].filter(Boolean).join(" ");
      vt.append(h("div", { class: `ve-clip k-${m.kind}${sel ? " sel" : ""}`, tabindex: 0, role: "button", "data-track": "v", "data-id": c.id,
        "aria-label": `Clip ${it.i + 1}: ${m.name}, ${dur(it.dur)}${sel ? ", selected" : ""}`, title: `${m.name}\n${dur(it.dur)} (source ${num(c.in).toFixed(2)}–${num(c.out).toFixed(2)}s)`,
        style: `left:${it.start * z}px;width:${Math.max(6, it.dur * z)}px` },
        h("div", { class: "ve-thumbs", style: thumb }),
        it.xd ? h("div", { class: "ve-xf", style: `width:${it.xd * z}px`, title: `Crossfade ${it.xd}s` }) : null,
        h("div", { class: "ve-clip-lbl" }, h("span", {}, m.name), tags ? h("b", {}, tags) : null),
        h("div", { class: "ve-h l", title: "Drag to trim the start" }), h("div", { class: "ve-h r", title: "Drag to trim the end" })));
    }
    if (!L.length) vt.append(h("div", { class: "ve-track-hint" }, "drag videos or photos here"));

    const tt = h("div", { class: "ve-track t", "data-track": "t" });
    for (const x of V.P.texts) {
      const sel = V.sel?.track === "t" && V.sel.id === x.id;
      tt.append(h("div", { class: "ve-clip k-text" + (sel ? " sel" : ""), tabindex: 0, role: "button", "data-track": "t", "data-id": x.id,
        "aria-label": `Text “${x.text}”, ${dur(x.start)} to ${dur(x.end)}${sel ? ", selected" : ""}`, title: x.text,
        style: `left:${x.start * z}px;width:${Math.max(6, (x.end - x.start) * z)}px` },
        h("div", { class: "ve-clip-lbl" }, h("span", {}, "T " + x.text.replace(/\n/g, " "))),
        h("div", { class: "ve-h l", title: "Drag to change when it appears" }), h("div", { class: "ve-h r", title: "Drag to change when it disappears" })));
    }
    if (!V.P.texts.length) tt.append(h("div", { class: "ve-track-hint" }, "press T to add a title"));

    const at = h("div", { class: "ve-track a", "data-track": "a" });
    for (const mu of V.P.music) {
      const m = mediaOf(mu.media) || { name: "missing" };
      const sel = V.sel?.track === "a" && V.sel.id === mu.id;
      const w = Math.max(6, (mu.out - mu.in) * z);
      const cv = h("canvas", { class: "ve-wave", width: Math.min(4000, Math.ceil(w)), height: 40 });
      at.append(h("div", { class: "ve-clip k-audio" + (sel ? " sel" : ""), tabindex: 0, role: "button", "data-track": "a", "data-id": mu.id,
        "aria-label": `Music ${m.name}, starts ${dur(mu.start)}, ${dur(mu.out - mu.in)} long${sel ? ", selected" : ""}`, title: m.name,
        style: `left:${mu.start * z}px;width:${w}px` }, cv,
        h("div", { class: "ve-clip-lbl" }, h("span", {}, "♪ " + m.name), num(mu.volume, 1) !== 1 ? h("b", {}, Math.round(mu.volume * 100) + "%") : null),
        h("div", { class: "ve-h l", title: "Drag to trim the start" }), h("div", { class: "ve-h r", title: "Drag to trim the end" })));
      drawWave(cv, m, mu);
    }
    if (!V.P.music.length) at.append(h("div", { class: "ve-track-hint" }, "drop a song here"));

    d.playhead = h("div", { class: "ve-playhead", style: `left:${V.t * z}px` }, h("i", {}));
    d.lane.replaceChildren(ruler, vt, tt, at, d.playhead);
    drawPlayhead();
    if (hadFocus && V.sel) d.lane.querySelector(`.ve-clip[data-id="${V.sel.id}"]`)?.focus({ preventScroll: true });
  }

  async function drawWave(cv, m, mu) {
    if (!m.path || m.missing) return;
    let w = V.waves[m.path];
    if (!w) {
      if (V.waves[m.path + ":loading"]) return;
      V.waves[m.path + ":loading"] = true;
      try { w = V.waves[m.path] = await api(`/api/video/wave?path=${enc(m.path)}`); } catch { return; }
      renderTimeline(); return;
    }
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    g.fillStyle = getComputedStyle(V.dom.root).getPropertyValue("--ink").trim() || "#8086d4";
    g.globalAlpha = 0.55;
    const a = mu.in * w.per_sec, b = mu.out * w.per_sec;
    for (let x = 0; x < W; x++) {
      const i = Math.floor(a + (b - a) * x / W), p = w.peaks[i] || 0;
      const hh = Math.max(1, p * (H - 4));
      g.fillRect(x, (H - hh) / 2, 1, hh);
    }
  }

  // ---- snapping
  function snapPoints(exceptId) {
    const pts = [0, V.t];
    for (const it of layout()) if (it.c.id !== exceptId) pts.push(it.start, it.end);
    for (const x of V.P.texts) if (x.id !== exceptId) pts.push(x.start, x.end);
    for (const mu of V.P.music) if (mu.id !== exceptId) pts.push(mu.start, mu.start + mu.out - mu.in);
    if (V.marks.in != null) pts.push(V.marks.in);
    if (V.marks.out != null) pts.push(V.marks.out);
    return pts;
  }
  function snapT(t, exceptId, ev) {
    if (!V.snap || ev?.altKey) return t;
    let best = t, bd = SNAP_PX / V.zoom;
    for (const p of snapPoints(exceptId)) { const dd = Math.abs(p - t); if (dd < bd) { bd = dd; best = p; } }
    return best;
  }
  function snapSpan(start, len, exceptId, ev) {  // snap whichever edge is closer
    const s1 = snapT(start, exceptId, ev);
    if (s1 !== start) return s1;
    const e1 = snapT(start + len, exceptId, ev);
    return e1 - len;
  }

  // ---- pointer: seek, select, move, trim
  function onLaneDown(ev) {
    if (ev.button !== 0) return;
    const lane = V.dom.lane, rect = () => lane.getBoundingClientRect();
    const tAt = (e) => Math.max(0, (e.clientX - rect().left) / V.zoom);
    const clipEl = ev.target.closest(".ve-clip");
    if (!clipEl) {  // ruler / empty track: seek and scrub
      ev.preventDefault();
      if (V.sel && ev.target.closest(".ve-track")) select(null);
      seek(tAt(ev));
      const move = (e) => seek(tAt(e));
      const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
      return;
    }
    const track = clipEl.dataset.track, id = clipEl.dataset.id;
    const handle = ev.target.closest(".ve-h");
    const mode = handle ? (handle.classList.contains("l") ? "trimL" : "trimR") : "move";
    ev.preventDefault();
    if (V.sel?.id !== id) select(track, id);
    V.dom.lane.querySelector(`.ve-clip[data-id="${id}"]`)?.focus({ preventScroll: true });
    const item = V.P[TRACK[track]].find((x) => x.id === id);
    const orig = clone(item), t0 = tAt(ev), x0 = ev.clientX;
    const startOf = () => layout().find((x) => x.c.id === id)?.start ?? 0;
    let moved = false;
    const move = (e) => {
      if (!moved) { if (Math.abs(e.clientX - x0) < 3) return; moved = true; snapshot(); document.body.classList.add("ve-dragging"); }
      const dt = tAt(e) - t0;
      if (track === "v") dragMain(item, orig, mode, dt, tAt(e), startOf, e);
      else if (track === "t") dragText(item, orig, mode, dt, e);
      else dragMusic(item, orig, mode, dt, e);
      light();
    };
    const up = () => {
      removeEventListener("pointermove", move); removeEventListener("pointerup", up);
      document.body.classList.remove("ve-dragging");
      if (moved) commit();
    };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  }

  function dragMain(c, o, mode, dt, tPointer, startOf, e) {
    const m = mediaOf(c.media), sp = speedOf(c);
    if (mode === "move") {  // live reorder: drop position = number of other clips whose middle is left of the pointer
      const others = V.P.clips.filter((x) => x !== c);
      const idx = layout(others).filter((it) => it.start + it.dur / 2 < tPointer).length;
      if (V.P.clips.indexOf(c) !== idx) { V.P.clips = [...others.slice(0, idx), c, ...others.slice(idx)]; }
      return;
    }
    if (c.kind === "image") {
      if (mode === "trimR") c.dur = r3(Math.max(0.2, snapT(startOf() + o.dur + dt, c.id, e) - startOf()));
      else c.dur = r3(Math.max(0.2, o.dur - dt));
      return;
    }
    if (mode === "trimR") {
      const edge = snapT(startOf() + (o.out - o.in) / sp + dt, c.id, e);
      c.out = r3(clamp(o.in + (edge - startOf()) * sp, o.in + 0.1, m?.duration || o.out));
    } else c.in = r3(clamp(o.in + dt * sp, 0, o.out - 0.1));
  }
  function dragText(x, o, mode, dt, e) {
    if (mode === "move") { const len = o.end - o.start; x.start = r3(Math.max(0, snapSpan(o.start + dt, len, x.id, e))); x.end = r3(x.start + len); }
    else if (mode === "trimL") x.start = r3(clamp(snapT(o.start + dt, x.id, e), 0, o.end - 0.2));
    else x.end = r3(Math.max(o.start + 0.2, snapT(o.end + dt, x.id, e)));
  }
  function dragMusic(mu, o, mode, dt, e) {
    const m = mediaOf(mu.media), len = o.out - o.in;
    if (mode === "move") mu.start = r3(Math.max(0, snapSpan(o.start + dt, len, mu.id, e)));
    else if (mode === "trimL") {
      const ns = snapT(o.start + dt, mu.id, e);
      const dd = clamp(ns - o.start, Math.max(-o.in, -o.start), len - 0.2);
      mu.in = r3(o.in + dd); mu.start = r3(o.start + dd);
    } else {
      const edge = snapT(o.start + len + dt, mu.id, e);
      mu.out = r3(clamp(o.in + edge - o.start, o.in + 0.2, m?.duration || o.out));
    }
  }

  // ---- drag from the media bin onto the timeline
  function onLaneDragOver(e) {
    if (!e.dataTransfer.types.includes("application/x-drdoc-media")) return;
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  }
  function onLaneDrop(e) {
    const id = e.dataTransfer.getData("application/x-drdoc-media");
    if (!id) return;
    e.preventDefault(); e.stopPropagation();
    const m = mediaOf(id); if (!m) return;
    const t = Math.max(0, (e.clientX - V.dom.lane.getBoundingClientRect().left) / V.zoom);
    snapshot();
    let item;
    if (m.kind === "audio") item = placeMedia(m, { at: snapT(t) });
    else item = placeMedia(m, { index: layout().filter((it) => it.start + it.dur / 2 < t).length });
    if (item) V.sel = { track: m.kind === "audio" ? "a" : "v", id: item.id };
    commit();
  }

  // ------------------------------------------------------------ edit commands
  function itemAtPlayhead() {
    const s = findSel();
    if (V.sel?.track === "t" && s && V.t > s.start && V.t < s.end) return { track: "t", item: s };
    if (V.sel?.track === "a" && s && V.t > s.start && V.t < s.start + s.out - s.in) return { track: "a", item: s };
    const L = layout();
    const it = (V.sel?.track === "v" && L.find((x) => x.c.id === V.sel.id && V.t > x.start && V.t < x.end)) || L.find((x) => V.t >= x.start && V.t < x.end);
    return it ? { track: "v", item: it.c, it } : null;
  }
  function split() {
    const f = itemAtPlayhead();
    if (!f) return toast("Put the playhead over a clip to split it");
    const MIN = 0.05;
    if (f.track === "v") {
      const { it, item: c } = f, local = V.t - it.start;
      if (local < MIN || local > it.dur - MIN) return toast("Too close to the edge of the clip");
      snapshot();
      const b = clone(c); b.id = uid(); b.trans = { type: "none", dur: 1 }; b.fade_in = 0; c.fade_out = 0;
      if (c.kind === "image") { b.dur = r3(it.dur - local); c.dur = r3(local); }
      else { const cut = r3(num(c.in) + local * speedOf(c)); b.in = cut; c.out = cut; }
      V.P.clips.splice(V.P.clips.indexOf(c) + 1, 0, b);
      V.sel = { track: "v", id: b.id };
    } else if (f.track === "t") {
      snapshot();
      const x = f.item, b = { ...clone(x), id: uid(), start: r3(V.t) };
      x.end = r3(V.t); V.P.texts.push(b); V.sel = { track: "t", id: b.id };
    } else {
      snapshot();
      const mu = f.item, cut = r3(mu.in + (V.t - mu.start));
      const b = { ...clone(mu), id: uid(), in: cut, start: r3(V.t), fade_in: 0 };
      mu.out = cut; mu.fade_out = 0; V.P.music.push(b); V.sel = { track: "a", id: b.id };
    }
    commit();
  }
  function del() {
    const s = findSel(); if (!s) return toast("Select a clip first");
    snapshot();
    const list = V.P[TRACK[V.sel.track]];
    const i = list.indexOf(s);
    list.splice(i, 1);
    const next = list[Math.min(i, list.length - 1)];
    V.sel = next ? { track: V.sel.track, id: next.id } : null;
    commit();
  }
  function duplicate() {
    const s = findSel(); if (!s) return toast("Select a clip first");
    snapshot();
    const b = clone(s); b.id = uid();
    if (V.sel.track === "v") { V.P.clips.splice(V.P.clips.indexOf(s) + 1, 0, b); }
    else if (V.sel.track === "t") { const len = s.end - s.start; b.start = s.end; b.end = r3(s.end + len); V.P.texts.push(b); }
    else { b.start = r3(s.start + s.out - s.in); V.P.music.push(b); }
    V.sel = { track: V.sel.track, id: b.id };
    commit();
  }
  function addText() {
    if (!V.dom) return;
    snapshot();
    const st = Math.floor(V.t * 1000) / 1000;  // never round past the playhead, or the new title is invisible
    const x = { id: uid(), text: "Your text", start: st, end: r3(st + 3), x: 0.5, y: 0.9, size: 7, color: "#ffffff", box: true, box_color: "#000000" };
    V.P.texts.push(x); V.sel = { track: "t", id: x.id };
    commit();
    setTimeout(() => { const ta = $(".ve-insp textarea"); if (ta) { ta.focus(); ta.select(); } }, 0);
  }
  /** Arrow keys on a focused clip: move it, or trim with Alt (start) / Ctrl (end). */
  function nudge(track, id, dir, ev) {
    const list = V.P[TRACK[track]], x = list.find((y) => y.id === id); if (!x) return;
    const step = (ev.shiftKey ? 1 : 0.1) * dir;
    snapshot();
    if (track === "v") {
      const i = list.indexOf(x), sp = speedOf(x), m = mediaOf(x.media);
      if (ev.altKey) { if (x.kind === "image") x.dur = r3(Math.max(0.2, x.dur - step)); else x.in = r3(clamp(x.in + step * sp, 0, x.out - 0.1)); }
      else if (ev.ctrlKey) { if (x.kind === "image") x.dur = r3(Math.max(0.2, x.dur + step)); else x.out = r3(clamp(x.out + step * sp, x.in + 0.1, m?.duration || x.out)); }
      else { const j = clamp(i + dir, 0, list.length - 1); list.splice(i, 1); list.splice(j, 0, x); }
    } else if (track === "t") {
      if (ev.altKey) x.start = r3(clamp(x.start + step, 0, x.end - 0.2));
      else if (ev.ctrlKey) x.end = r3(Math.max(x.start + 0.2, x.end + step));
      else { const len = x.end - x.start; x.start = r3(Math.max(0, x.start + step)); x.end = r3(x.start + len); }
    } else {
      const m = mediaOf(x.media);
      if (ev.altKey) { const dd = clamp(step, Math.max(-x.in, -x.start), x.out - x.in - 0.2); x.in = r3(x.in + dd); x.start = r3(x.start + dd); }
      else if (ev.ctrlKey) x.out = r3(clamp(x.out + step, x.in + 0.2, m?.duration || x.out));
      else x.start = r3(Math.max(0, x.start + step));
    }
    V.sel = { track, id };
    commit();
  }

  // ------------------------------------------------------------ inspector
  const fld = (label, ...kids) => h("label", { class: "ve-f" }, h("span", {}, label), ...kids);
  function numIn(key, value, { min, max, step = 0.1, title }, set) {
    const i = h("input", { type: "number", value: r3(value), min, max, step, "data-k": key, "aria-label": title || key, title: title || "" });
    i.onchange = () => { snapshot(); set(clamp(num(i.value, value), min ?? -1e9, max ?? 1e9)); commit(); };
    return i;
  }
  function rangeIn(key, value, { min, max, step, fmt }, set) {
    const out = h("output", { class: "sm muted" }, fmt(value));
    const i = h("input", { type: "range", min, max, step, value, "data-k": key, "aria-label": key });
    let snapped = false;
    i.oninput = () => { if (!snapped) { snapshot(); snapped = true; } set(+i.value); out.textContent = fmt(+i.value); light(); };
    i.onchange = () => { snapped = false; commit({ inspector: false }); renderTitle(); };
    return [i, out];
  }
  function seg(key, options, cur, set) {
    return h("div", { class: "ve-seg", role: "group", "aria-label": key }, ...options.map(([v, label, title]) =>
      h("button", { type: "button", class: "tb" + (String(v) === String(cur) ? " on" : ""), "aria-pressed": String(v) === String(cur), title: title || label, "aria-label": title || label,
        onclick: () => { snapshot(); set(v); commit(); } }, label)));
  }
  function check(key, label, value, set) {
    const i = h("input", { type: "checkbox", "data-k": key }); i.checked = !!value;
    i.onchange = () => { snapshot(); set(i.checked); commit(); };
    return h("label", { class: "ve-check" }, i, label);
  }
  const sect = (title, ...kids) => h("section", { class: "ve-sect" }, h("h4", {}, title), ...kids);

  function renderInspector() {
    const d = V.dom; if (!d) return;
    const focusKey = document.activeElement?.dataset?.k;
    const s = findSel();
    const body = !s ? inspectProject() : V.sel.track === "v" ? inspectClip(s) : V.sel.track === "t" ? inspectText(s) : inspectMusic(s);
    const top = d.insp.scrollTop;
    d.insp.replaceChildren(body);
    d.insp.scrollTop = top;
    if (focusKey) d.insp.querySelector(`[data-k="${focusKey}"]`)?.focus();
  }

  function inspectProject() {
    const name = h("input", { type: "text", value: V.name, "data-k": "name", "aria-label": "Project name" });
    name.onchange = () => { V.name = name.value.trim() || "my video"; renderTitle(); autosave(); };
    const L = layout();
    return h("div", {},
      sect("project", fld("Name", name),
        h("div", { class: "sm muted" }, `${L.length} clip(s) · ${V.P.texts.length} text(s) · ${V.P.music.length} music · ${dur(mainTotal())}`)),
      musicModeSect(),
      sect("tips", h("ul", { class: "ve-tips sm muted" },
        h("li", {}, "Click a clip to edit its trim, speed, volume, crop, colour and transition."),
        h("li", {}, "Drag clips to reorder, drag their edges to trim."),
        h("li", {}, "S splits at the playhead, T adds a title, ? lists every shortcut."),
        h("li", {}, "Mark a range with I / O to export just that part."))),
      h("button", { class: "btn", type: "button", onclick: openExport, style: "width:100%;justify-content:center" }, "⬇ Export…"));
  }
  function musicModeSect() {
    return sect("music & original audio",
      seg("Music mode", [["mix", "Mix", "Mix music with the clips' sound"], ["duck", "Duck", "Lower the music while clips have sound"], ["replace", "Replace", "Use only the music, drop the clips' sound"]],
        V.P.music_mode, (v) => (V.P.music_mode = v)),
      h("div", { class: "sm muted" }, { mix: "Music plays under the original sound.", duck: "Music dips automatically when the clips have sound.", replace: "Original audio is removed; only music is heard." }[V.P.music_mode]));
  }

  function inspectClip(c) {
    const m = mediaOf(c.media) || { name: "missing", kind: c.kind };
    const L = layout(), it = L.find((x) => x.c.id === c.id);
    const idx = V.P.clips.indexOf(c);
    const parts = [];
    parts.push(h("div", { class: "ve-insp-head" }, h("b", {}, m.name),
      h("div", { class: "sm muted" }, [m.kind, m.width ? `${m.width}×${m.height}` : null, m.fps ? `${m.fps} fps` : null, m.kind === "video" ? `source ${dur(m.duration)}` : null].filter(Boolean).join(" · ")),
      h("div", { class: "sm muted" }, `on timeline ${tc(it.start)} → ${tc(it.end)} (${dur(it.dur)})`)));
    if (c.kind === "image") {
      parts.push(sect("timing", fld("Duration (s)", numIn("dur", c.dur, { min: 0.2, max: 3600, step: 0.5 }, (v) => (c.dur = r3(v))))));
    } else {
      const sp = speedOf(c);
      const [spIn, spOut] = rangeIn("speed", sp, { min: 0.25, max: 4, step: 0.05, fmt: (v) => v.toFixed(2) + "×" }, (v) => (c.speed = v));
      parts.push(sect("trim",
        h("div", { class: "ve-2" },
          fld("In (s)", numIn("in", c.in, { min: 0, max: c.out - 0.1, step: 0.05, title: "Start inside the source file" }, (v) => (c.in = r3(v)))),
          fld("Out (s)", numIn("out", c.out, { min: c.in + 0.1, max: m.duration || 1e9, step: 0.05, title: "End inside the source file" }, (v) => (c.out = r3(v))))),
        h("div", { class: "row" },
          h("button", { class: "btn ghost sm", type: "button", title: "Set the start to the playhead", onclick: () => trimToPlayhead(c, "in") }, "⇤ start here"),
          h("button", { class: "btn ghost sm", type: "button", title: "Set the end to the playhead", onclick: () => trimToPlayhead(c, "out") }, "end here ⇥"))),
        sect("speed", h("div", { class: "ve-rng" }, spIn, spOut),
          h("div", { class: "ve-chips" }, ...SPEEDS.map((v) => h("button", { type: "button", class: "tb" + (Math.abs(sp - v) < 1e-3 ? " on" : ""), title: `${v}× speed`, "aria-label": `${v} times speed`, onclick: () => { snapshot(); c.speed = v; commit(); } }, v + "×"))),
          h("div", { class: "sm muted" }, "Audio keeps its pitch.")));
      if (m.has_audio) {
        const [vIn, vOut] = rangeIn("volume", Math.round(num(c.volume, 1) * 100), { min: 0, max: 200, step: 5, fmt: (v) => v + "%" }, (v) => (c.volume = v / 100));
        parts.push(sect("audio", h("div", { class: "ve-rng" }, vIn, vOut), check("muted", "Mute / remove this clip's audio", c.muted, (v) => (c.muted = v))));
      }
    }
    parts.push(sect("fades",
      h("div", { class: "ve-2" },
        fld("Fade in (s)", numIn("fade_in", c.fade_in || 0, { min: 0, max: 10, step: 0.25, title: "Fade in from black (and silence)" }, (v) => (c.fade_in = r3(v)))),
        fld("Fade out (s)", numIn("fade_out", c.fade_out || 0, { min: 0, max: 10, step: 0.25, title: "Fade out to black (and silence)" }, (v) => (c.fade_out = r3(v)))))));
    if (idx > 0) {
      const tr = c.trans || (c.trans = { type: "none", dur: 1 });
      parts.push(sect("transition from previous clip",
        seg("Transition", [["none", "Cut"], ["crossfade", "Crossfade"]], tr.type, (v) => (c.trans = { ...tr, type: v })),
        tr.type === "crossfade" ? fld("Duration (s)", numIn("trans_dur", tr.dur, { min: 0.1, max: 5, step: 0.1 }, (v) => (c.trans = { ...tr, dur: r3(v) }))) : null,
        it.xd && tr.type === "crossfade" && it.xd < tr.dur ? h("div", { class: "sm muted" }, `Shortened to ${it.xd}s (half the shorter clip).`) : null));
    }
    const cr = c.crop || (c.crop = { t: 0, b: 0, l: 0, r: 0 });
    const pc = (k) => numIn("crop_" + k, Math.round(num(cr[k]) * 1000) / 10, { min: 0, max: 45, step: 1, title: `Crop ${k} %` }, (v) => (c.crop = { ...cr, [k]: r3(v / 100) }));
    parts.push(sect("frame",
      h("div", { class: "ve-sub sm muted" }, "Rotate"),
      seg("Rotate", [[0, "0°"], [90, "90°"], [180, "180°"], [270, "270°"]], num(c.rotate), (v) => (c.rotate = v)),
      h("div", { class: "ve-sub sm muted" }, "Crop (%)"),
      h("div", { class: "ve-4" }, fld("Top", pc("t")), fld("Bottom", pc("b")), fld("Left", pc("l")), fld("Right", pc("r"))),
      h("div", { class: "ve-chips" }, ...[["free", "None"], ["16:9", "16:9"], ["9:16", "9:16"], ["1:1", "1:1"], ["4:3", "4:3"], ["4:5", "4:5"]].map(([a, label]) =>
        h("button", { type: "button", class: "tb", title: a === "free" ? "Remove crop" : `Crop to ${a} (centred)`, "aria-label": a === "free" ? "Remove crop" : `Crop to ${a}`, onclick: () => cropAspect(c, a) }, label)))));
    const eq = c.eq || (c.eq = { brightness: 0, contrast: 1, saturation: 1 });
    const [bIn, bOut] = rangeIn("brightness", eq.brightness, { min: -0.5, max: 0.5, step: 0.02, fmt: (v) => (v > 0 ? "+" : "") + Math.round(v * 100) }, (v) => (c.eq = { ...c.eq, brightness: v }));
    const [cIn, cOut] = rangeIn("contrast", eq.contrast, { min: 0.5, max: 2, step: 0.05, fmt: (v) => Math.round(v * 100) + "%" }, (v) => (c.eq = { ...c.eq, contrast: v }));
    const [sIn, sOut] = rangeIn("saturation", eq.saturation, { min: 0, max: 2, step: 0.05, fmt: (v) => Math.round(v * 100) + "%" }, (v) => (c.eq = { ...c.eq, saturation: v }));
    parts.push(sect("colour",
      fld("Brightness", h("div", { class: "ve-rng" }, bIn, bOut)), fld("Contrast", h("div", { class: "ve-rng" }, cIn, cOut)), fld("Saturation", h("div", { class: "ve-rng" }, sIn, sOut)),
      h("button", { class: "btn ghost sm", type: "button", onclick: () => { snapshot(); c.eq = { brightness: 0, contrast: 1, saturation: 1 }; commit(); } }, "Reset colour")));
    parts.push(clipActions());
    return h("div", {}, ...parts);
  }
  const clipActions = () => h("div", { class: "row ve-actions" },
    h("button", { class: "btn ghost sm", type: "button", onclick: split, title: "Split at playhead (S)" }, "✂ Split"),
    h("button", { class: "btn ghost sm", type: "button", onclick: duplicate, title: "Duplicate (Ctrl+D)" }, "⧉ Duplicate"),
    h("button", { class: "btn danger sm", type: "button", onclick: del, title: "Delete (Del)" }, "🗑 Delete"));

  function trimToPlayhead(c, which) {
    const it = layout().find((x) => x.c.id === c.id);
    const local = V.t - it.start;
    if (local <= 0 || local >= it.dur) return toast("Move the playhead inside this clip first");
    snapshot();
    const at = r3(num(c.in) + local * speedOf(c));
    if (which === "in") { c.in = at; V.t = it.start; } else c.out = at;
    commit();
  }
  function cropAspect(c, a) {
    snapshot();
    if (a === "free") { c.crop = { t: 0, b: 0, l: 0, r: 0 }; return commit(); }
    const m = mediaOf(c.media); const [x, y] = a.split(":").map(Number);
    let target = x / y;
    if (num(c.rotate) % 180 === 90) target = 1 / target;  // crop happens before rotation
    const w = m.width || 16, hh = m.height || 9;
    if (w / hh > target) { const k = (1 - hh * target / w) / 2; c.crop = { t: 0, b: 0, l: r3(k), r: r3(k) }; }
    else { const k = (1 - w / target / hh) / 2; c.crop = { t: r3(k), b: r3(k), l: 0, r: 0 }; }
    commit();
  }

  function inspectText(x) {
    const ta = h("textarea", { rows: 3, "data-k": "text", "aria-label": "Text" }); ta.value = x.text;
    let snapped = false;
    ta.oninput = () => { if (!snapped) { snapshot(); snapped = true; } x.text = ta.value; V.textKey = ""; renderTexts(); };
    ta.onchange = () => { snapped = false; commit({ inspector: false }); };
    const [sIn, sOut] = rangeIn("size", num(x.size, 7), { min: 2, max: 25, step: 0.5, fmt: (v) => v + "%" }, (v) => (x.size = v));
    const color = h("input", { type: "color", value: x.color || "#ffffff", "data-k": "color", title: "Text colour", "aria-label": "Text colour" });
    color.onchange = () => { snapshot(); x.color = color.value; commit(); };
    const boxc = h("input", { type: "color", value: x.box_color || "#000000", "data-k": "box_color", title: "Box colour", "aria-label": "Box colour" });
    boxc.onchange = () => { snapshot(); x.box_color = boxc.value; x.box = true; commit(); };
    return h("div", {},
      sect("text", ta, h("div", { class: "sm muted" }, "Drag the text on the preview to place it anywhere.")),
      sect("timing", h("div", { class: "ve-2" },
        fld("Start (s)", numIn("start", x.start, { min: 0, step: 0.1 }, (v) => { x.start = r3(Math.min(v, x.end - 0.1)); })),
        fld("End (s)", numIn("end", x.end, { min: 0.1, step: 0.1 }, (v) => { x.end = r3(Math.max(v, x.start + 0.1)); })))),
      sect("position",
        seg("Vertical position", [[0.06, "Top"], [0.5, "Centre"], [0.94, "Bottom"]], [0.06, 0.5, 0.94].find((v) => Math.abs(v - x.y) < 0.01) ?? "", (v) => (x.y = v)),
        seg("Horizontal position", [[0.04, "Left"], [0.5, "Middle"], [0.96, "Right"]], [0.04, 0.5, 0.96].find((v) => Math.abs(v - x.x) < 0.01) ?? "", (v) => (x.x = v))),
      sect("style", fld("Size (% of height)", h("div", { class: "ve-rng" }, sIn, sOut)),
        h("div", { class: "row" }, h("span", { class: "sm" }, "Colour"), color, check("box", "Background box", x.box, (v) => (x.box = v)), boxc)),
      clipActions());
  }

  function inspectMusic(mu) {
    const m = mediaOf(mu.media) || { name: "missing" };
    const [vIn, vOut] = rangeIn("volume", Math.round(num(mu.volume, 1) * 100), { min: 0, max: 200, step: 5, fmt: (v) => v + "%" }, (v) => (mu.volume = v / 100));
    return h("div", {},
      h("div", { class: "ve-insp-head" }, h("b", {}, "♪ " + m.name), h("div", { class: "sm muted" }, `song ${dur(m.duration)} · plays ${dur(mu.out - mu.in)} from ${tc(mu.start)}`)),
      sect("position & trim",
        fld("Starts at (s on timeline)", numIn("start", mu.start, { min: 0, step: 0.1 }, (v) => (mu.start = r3(v)))),
        h("div", { class: "ve-2" },
          fld("Song in (s)", numIn("in", mu.in, { min: 0, max: mu.out - 0.2, step: 0.1 }, (v) => (mu.in = r3(v)))),
          fld("Song out (s)", numIn("out", mu.out, { min: mu.in + 0.2, max: m.duration || 1e9, step: 0.1 }, (v) => (mu.out = r3(v))))),
        h("button", { class: "btn ghost sm", type: "button", title: "Trim the song so it ends with the video", onclick: () => { snapshot(); mu.out = r3(clamp(mu.in + mainTotal() - mu.start, mu.in + 0.2, m.duration || mu.out)); commit(); } }, "Fit to video length")),
      sect("volume", h("div", { class: "ve-rng" }, vIn, vOut),
        h("div", { class: "ve-2" },
          fld("Fade in (s)", numIn("fade_in", mu.fade_in || 0, { min: 0, max: 20, step: 0.5 }, (v) => (mu.fade_in = r3(v)))),
          fld("Fade out (s)", numIn("fade_out", mu.fade_out || 0, { min: 0, max: 20, step: 0.5 }, (v) => (mu.fade_out = r3(v)))))),
      musicModeSect(),
      clipActions());
  }

  // ------------------------------------------------------------ export dialog
  function openExport() {
    if (!V.P.clips.length && !V.P.music.length) return toast("Add something to the timeline first", true);
    const ex = V.P.export, modal = $("#modal");
    const sel = (key, opts, title) => {
      const s = h("select", { "aria-label": title, "data-k": key }, ...opts.map(([v, l]) => h("option", { value: v, selected: String(ex[key]) === String(v) }, l)));
      s.onchange = () => { ex[key] = s.value; update(); };
      return s;
    };
    const fmt = sel("format", [["mp4", "MP4 (H.264): plays everywhere"], ["webm", "WebM (VP9)"], ["mov", "MOV (H.264)"], ["gif", "GIF animation"], ["mp3", "MP3 audio only"], ["wav", "WAV audio only"]], "Format");
    const res = sel("resolution", [["source", "Same as first clip"], ["2160p", "4K (2160p)"], ["1080p", "1080p"], ["720p", "720p"], ["480p", "480p"], ["360p", "360p"], ["custom", "Custom…"]], "Resolution");
    const asp = sel("aspect", [["keep", "Keep (first clip)"], ["16:9", "16:9 landscape"], ["9:16", "9:16 vertical (Shorts, Reels, TikTok)"], ["1:1", "1:1 square"], ["4:5", "4:5 portrait"], ["4:3", "4:3"]], "Aspect ratio");
    const fit = sel("fit", [["pad", "Fit (black bars)"], ["crop", "Fill (crop edges)"]], "Fit mode");
    const fps = sel("fps", [["source", "Same as source"], ["24", "24"], ["25", "25"], ["30", "30"], ["50", "50"], ["60", "60"]], "Frame rate");
    const cw = h("input", { type: "number", min: 16, max: 7680, step: 2, value: ex.width || 1920, "aria-label": "Width" });
    const chh = h("input", { type: "number", min: 16, max: 7680, step: 2, value: ex.height || 1080, "aria-label": "Height" });
    cw.onchange = () => { ex.width = +cw.value; update(); }; chh.onchange = () => { ex.height = +chh.value; update(); };
    const custom = h("div", { class: "row" }, cw, "×", chh);
    const crfLabel = h("output", { class: "sm muted" });
    const crf = h("input", { type: "range", min: 14, max: 34, step: 1, value: ex.crf || 20, "aria-label": "Quality" });
    crf.oninput = () => { ex.crf = +crf.value; update(); };
    // range: marks, else the selected clip, else everything
    const L = layout(), s = findSel();
    let r0 = 0, r1 = projectEnd();
    if (V.marks.in != null || V.marks.out != null) { r0 = V.marks.in ?? 0; r1 = V.marks.out ?? r1; }
    else if (V.sel?.track === "v" && s) { const it = L.find((x) => x.c.id === s.id); r0 = it.start; r1 = it.end; }
    const rOn = h("input", { type: "checkbox" }); rOn.checked = V.marks.in != null || V.marks.out != null;
    const ra = h("input", { type: "number", min: 0, step: 0.1, value: r3(r0), "aria-label": "Range start (s)" });
    const rb = h("input", { type: "number", min: 0, step: 0.1, value: r3(r1), "aria-label": "Range end (s)" });
    const summary = h("div", { class: "ve-ex-sum" });
    const nameIn = h("input", { type: "text", value: V.name, "aria-label": "File name" });
    const rows = {};
    function update() {
      const audio = ["mp3", "wav"].includes(ex.format);
      for (const k of ["res", "asp", "fit", "fps", "crf"]) rows[k].hidden = audio || (k === "crf" && ex.format === "gif");
      custom.hidden = ex.resolution !== "custom" || audio;
      crfLabel.textContent = ex.crf <= 17 ? "best (big file)" : ex.crf <= 21 ? "high" : ex.crf <= 26 ? "good" : ex.crf <= 30 ? "small file" : "tiny file";
      const len = rOn.checked ? Math.max(0, +rb.value - +ra.value) : projectEnd();
      const [w, hh] = outSize(ex);
      summary.textContent = audio ? `${ex.format.toUpperCase()} audio · ${dur(len)}` : `${ex.format.toUpperCase()} · ${w}×${hh} · ${ex.format === "gif" ? Math.min(15, fpsOf()) : fpsOf()} fps · ${dur(len)}`;
      autosave();
    }
    rOn.onchange = ra.oninput = rb.oninput = update;
    const row = (k, label, ...kids) => (rows[k] = h("div", { class: "ve-ex-row" }, h("span", {}, label), h("div", {}, ...kids)));
    const close = () => { modal.hidden = true; modal.replaceChildren(); removeEventListener("keydown", key, true); layoutStage(); syncPreview(true); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    async function go() {
      const settings = { ...ex };
      if (rOn.checked) settings.range = [+ra.value, +rb.value];
      try {
        const d = await api("/api/video/export", { project: V.P, settings, out_dir: S.outDir, name: nameIn.value.trim() || V.name });
        close();
        toast(`Exporting ${d.job.title.replace(/^Export /, "")}… watch the jobs panel`);
        if ($("#jobs")?.hidden) $("#jobs-toggle")?.click();
        window.App.watchJobs();
      } catch (e) { fail(e); }
    }
    const goBtn = h("button", { class: "btn", type: "button", onclick: go }, "⬇ Export");
    modal.replaceChildren(h("div", { class: "dialog win ve-export", role: "dialog", "aria-label": "Export video" },
      h("div", { class: "titlebar" }, h("span", {}, "export.exe"), h("button", { class: "tb-x", type: "button", title: "Close", "aria-label": "Close", onclick: close }, "✕")),
      h("div", { class: "ve-ex-body" },
        h("div", { class: "ve-ex-row" }, h("span", {}, "File name"), h("div", {}, nameIn)),
        row("fmt", "Format", fmt),
        row("res", "Resolution", res, custom),
        row("asp", "Aspect", asp),
        row("fit", "Fit", fit),
        row("fps", "Frame rate", fps),
        row("crf", "Quality", h("div", { class: "row" }, crf, crfLabel)),
        row("rng", "Range", h("label", { class: "ve-check" }, rOn, "Export only part"), h("div", { class: "row" }, ra, "→", rb, h("span", { class: "sm muted" }, "seconds"))),
        summary,
        h("div", { class: "sm muted" }, "Saves to ", h("b", {}, S.outDir || "your output folder"), ". Your original files are never changed.")),
      h("div", { class: "dialog-actions" }, goBtn, h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"))));
    modal.onclick = (e) => { if (e.target === modal) close(); };
    modal.hidden = false;
    addEventListener("keydown", key, true);
    update();
    goBtn.focus();
  }

  // ------------------------------------------------------------ projects
  async function saveProject() {
    if (!V.P.media.length) return toast("Nothing to save yet");
    try {
      const d = await api("/api/video/project/save", { project: V.P, name: V.name, out_dir: S.outDir, path: V.path });
      V.path = d.path; renderTitle(); autosave();
      toast("Project saved: " + d.path.split(/[\\/]/).pop());
    } catch (e) { fail(e); }
  }
  async function openProject() {
    try {
      const f = (await pickFiles()).find((x) => x.path.toLowerCase().endsWith("." + PROJECT_EXT));
      if (f) loadProject(f.path); else toast("Pick a .drdocvideo project file", true);
    } catch (e) { fail(e); }
  }
  async function loadProject(path) {
    try {
      if (V.P.clips.length && !(await ask("Open this project? Unsaved changes to the current one will be lost (you can still undo).", { yes: "Open" }))) return;
      const d = await api("/api/video/project/load", { path });
      snapshot();
      const p = d.project;
      V.P = Object.assign(newProject(), { media: p.media || [], clips: p.clips || [], texts: p.texts || [], music: p.music || [], music_mode: p.music_mode || "mix" });
      V.P.export = Object.assign(newProject().export, p.export || {});
      V.path = d.path; V.name = d.path.split(/[\\/]/).pop().replace(/\.drdocvideo$/i, ""); V.sel = null; V.t = 0;
      V.P.media.forEach((m) => { if (m.proxy_ready) V.ready.add(m.path); ensureProxy(m); });
      if (d.missing.length) toast(`${d.missing.length} file(s) are missing: ${d.missing.slice(0, 3).join(", ")}`, true, 8000);
      if (V.dom && V.root.contains(V.dom.root)) commit(); else { autosave(); mount(V.root); }
    } catch (e) { fail(e); }
  }
  async function newProjectAsk() {
    if (V.P.media.length && !(await ask("Start a new, empty project? (Undo can bring this one back.)", { yes: "New project" }))) return;
    snapshot();
    pause();
    V.P = newProject(); V.path = null; V.name = "my video"; V.sel = null; V.t = 0; V.marks = { in: null, out: null };
    autosave();
    renderEmpty();
  }

  // ------------------------------------------------------------ keyboard
  const KEYS = [["Space / K", "Play / pause"], ["J / L", "Back / forward 1 second"], ["← / →", "Previous / next frame (Shift: 1 s)"], ["Home / End", "Go to start / end"],
    ["S", "Split at the playhead"], ["Del", "Delete selected"], ["Ctrl+D", "Duplicate selected"], ["Ctrl+Z / Ctrl+Y", "Undo / redo"],
    ["T", "Add text at the playhead"], ["I / O", "Mark export range start / end"], ["+ / −  (Ctrl+wheel)", "Zoom the timeline"],
    ["Ctrl+S", "Save project"], ["Ctrl+E", "Export"], ["Tab", "Focus a clip on the timeline"], ["focused clip: ← / →", "Move it (Shift: 1 s steps)"],
    ["focused clip: Alt+← / →", "Trim its start"], ["focused clip: Ctrl+← / →", "Trim its end"], ["Alt while dragging", "Don't snap"], ["Esc", "Deselect / close"], ["?", "Show this list"]];
  function toggleHelp(force) {
    const p = V.dom?.help; if (!p) return;
    V.helpOpen = typeof force === "boolean" ? force : p.hidden;
    p.hidden = !V.helpOpen;
    if (V.helpOpen) {
      p.replaceChildren(h("div", { class: "titlebar" }, h("span", {}, "shortcuts.txt"), h("button", { class: "tb-x", type: "button", title: "Close", "aria-label": "Close shortcuts", onclick: () => toggleHelp(false) }, "✕")),
        h("dl", {}, ...KEYS.flatMap(([k, v]) => [h("dt", {}, h("kbd", {}, k)), h("dd", {}, v)])));
      p.querySelector(".tb-x").focus();
    }
  }

  addEventListener("keydown", (ev) => {
    if (S.view !== "video" || !V.dom || !document.body.contains(V.dom.root)) return;
    if (!$("#modal").hidden) return;
    const k = ev.key, ctrl = ev.ctrlKey || ev.metaKey;
    if (k === "Escape") { if (V.helpOpen) toggleHelp(false); else if (V.sel) select(null); return; }
    if (ev.target.matches("input, textarea, select, [contenteditable]")) return;
    const focusedClip = document.activeElement?.closest?.(".ve-clip");
    const onButton = ev.target.matches("button");
    const done = () => ev.preventDefault();
    if (ctrl && k.toLowerCase() === "z" && !ev.shiftKey) { undo(); return done(); }
    if (ctrl && (k.toLowerCase() === "y" || (k.toLowerCase() === "z" && ev.shiftKey))) { redo(); return done(); }
    if (ctrl && k.toLowerCase() === "d") { duplicate(); return done(); }
    if (ctrl && k.toLowerCase() === "s") { saveProject(); return done(); }
    if (ctrl && k.toLowerCase() === "e") { openExport(); return done(); }
    if (ctrl && !["ArrowLeft", "ArrowRight"].includes(k)) return;
    if ((k === "ArrowLeft" || k === "ArrowRight") && focusedClip) { nudge(focusedClip.dataset.track, focusedClip.dataset.id, k === "ArrowLeft" ? -1 : 1, ev); return done(); }
    if (focusedClip && (k === "Enter")) { select(focusedClip.dataset.track, focusedClip.dataset.id); return done(); }
    if (focusedClip && V.sel?.id !== focusedClip.dataset.id) V.sel = { track: focusedClip.dataset.track, id: focusedClip.dataset.id };
    switch (k) {
      case " ": if (onButton) return; togglePlay(); return done();
      case "k": case "K": togglePlay(); return done();
      case "j": case "J": seek(V.t - (ev.shiftKey ? 5 : 1)); return done();
      case "l": case "L": seek(V.t + (ev.shiftKey ? 5 : 1)); return done();
      case "ArrowLeft": case ",": seek(V.t - (ev.shiftKey ? 1 : 1 / fpsOf())); return done();
      case "ArrowRight": case ".": seek(V.t + (ev.shiftKey ? 1 : 1 / fpsOf())); return done();
      case "Home": seek(0); return done();
      case "End": seek(projectEnd()); return done();
      case "s": case "S": split(); return done();
      case "Delete": case "Backspace": del(); return done();
      case "t": case "T": addText(); return done();
      case "i": case "I": setMark("in"); return done();
      case "o": case "O": setMark("out"); return done();
      case "+": case "=": setZoom(V.zoom * 1.4); return done();
      case "-": case "_": setZoom(V.zoom / 1.4); return done();
      case "?": toggleHelp(); return done();
    }
  });

  // Debug/test hook: index.html#video opens this screen, #video=path1|path2 also loads files.
  if (location.hash.startsWith("#video")) {
    const paths = decodeURIComponent(location.hash.split("=")[1] || "").split("|").filter(Boolean);
    const wait = setInterval(() => {
      if (!S.caps) return;
      clearInterval(wait);
      document.querySelector('#nav a[data-view="video"]')?.click();
      if (paths.length) api("/api/fileinfo", { paths }).then((r) => addFiles(r.files)).catch(fail);
    }, 100);
  }

  window.VideoEditor = { mount, addFiles };
})();
