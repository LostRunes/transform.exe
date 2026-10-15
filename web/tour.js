/* First-run guided tour: a spotlight that walks through the screen, one step at a time.
   Shown once on first launch; "Skip tour" or finishing it remembers that. Restart it any time
   from Start → "Take the tour", from Help, or with Tour.start(). */
(function () {
  const { $, h, store } = window.App;

  // [element to highlight (null = centred), title, text, view to open first]
  const STEPS = [
    [null, "Hi, I'm Dr. Doc! ✦", "I convert, compress, combine and edit your files, all on this computer. Nothing is ever uploaded. Let me show you around. It takes about a minute."],
    ["#nav", "Everything lives here", "Each item is a workspace. Click one, or press Tab to move through them and Enter to open."],
    ["#nav [data-view='convert']", "Convert", "Turn any file into another format: photos → PDF, Word → PDF, video → MP3 and lots more. Several photos going to PDF can be arranged and combined into one PDF, one each, or your own groups.", "convert"],
    [".dropzone", "Add files", "Drop files anywhere on the window, click Browse files, or paste a file or folder path. Big files are read where they are, never copied or uploaded.", "convert"],
    ["#nav [data-view='tools:Compress']", "Compress", "Make any file smaller: drag a slider (\"60% smaller\") or type an exact size (\"under 200 KB\"). Works for photos, PDFs, videos, music and Office files."],
    ["#nav [data-view='editor']", "PDF editor", "Rewrite text that's already in a PDF, add text, shapes, arrows, highlights, signatures and images."],
    ["#nav [data-view='office']", "Docs & sheets", "Open Word documents and Excel spreadsheets to read or edit them, then save a copy or export to PDF."],
    ["#nav [data-view='video']", "Video editor", "A real timeline: trim, split, join clips, add music and text, crossfades, then export in the size you need."],
    [".addr", "Where results go", "Finished files are saved here. Click to choose another folder, or ↗ to open it. Nothing is ever overwritten."],
    ["#jobs-toggle", "Jobs", "Every task runs in the background with live progress. Open this to see results and Open or Show them in Explorer."],
    ["#search-btn", "Search everything", "Not sure where something is? Press Ctrl+K and type what you want to do, like \"combine pdf\" or \"make video smaller\"."],
    ["#start", "Start menu", "Help & manual, this tour, text size, day/night, and your output folder are all in here."],
    [null, "You're all set ✧", "Tip: press F1 any time for the manual. You can replay this tour from Start → Take the tour. Have fun!"],
  ];

  let i = 0, root = null, lastFocus = null;

  function start(from = 0) {
    stop(false);
    i = from;
    lastFocus = document.activeElement;
    root = h("div", { class: "tour", role: "dialog", "aria-modal": "true", "aria-labelledby": "tour-title" });
    document.body.append(root);
    addEventListener("keydown", onKey, true);
    addEventListener("resize", place);
    show();
  }

  /** finished/skipped = true remembers it so the tour doesn't auto-start again. */
  function stop(remember = true) {
    if (!root) return;
    root.remove(); root = null;
    removeEventListener("keydown", onKey, true);
    removeEventListener("resize", place);
    if (remember) store.set("tour.done", true);
    lastFocus?.focus?.();
  }

  function show() {
    const [sel, title, text, view] = STEPS[i];
    if (view && window.App.S.view !== view) window.App.route?.(view);
    const last = i === STEPS.length - 1;
    const next = h("button", { class: "btn", onclick: () => go(1) }, last ? "Finish ✓" : "Next →");
    root.replaceChildren(
      h("div", { class: "tour-spot" }),
      h("div", { class: "tour-card win" },
        h("div", { class: "titlebar" }, h("span", {}, `tour ${i + 1}/${STEPS.length}`),
          h("button", { class: "tb-x", title: "Close the tour", "aria-label": "Close the tour", onclick: () => stop(true) }, "✕")),
        h("div", { class: "tour-body" },
          h("h3", { id: "tour-title" }, title),
          h("p", {}, text),
          h("div", { class: "tour-dots", "aria-hidden": "true" }, ...STEPS.map((_, k) => h("i", { class: k === i ? "on" : "" })))),
        h("div", { class: "tour-actions" },
          !last ? h("button", { class: "btn ghost sm", onclick: () => stop(true) }, "Skip tour") : h("span"),
          h("span", { class: "spacer" }),
          i > 0 ? h("button", { class: "btn ghost", onclick: () => go(-1) }, "← Back") : null,
          next)));
    requestAnimationFrame(() => { place(); next.focus(); });
  }

  function place() {
    if (!root) return;
    const spot = root.querySelector(".tour-spot"), card = root.querySelector(".tour-card");
    const el = STEPS[i][0] && $(STEPS[i][0]);
    const r = el && el.getClientRects().length ? el.getBoundingClientRect() : null;
    if (!r) {  // centred step
      spot.style.cssText = `left:50%;top:45%;width:0;height:0`;
      card.style.cssText = `left:50%;top:50%;transform:translate(-50%,-50%)`;
      return;
    }
    el.scrollIntoView?.({ block: "nearest" });
    const pad = 6;
    spot.style.cssText = `left:${r.left - pad}px;top:${r.top - pad}px;width:${r.width + pad * 2}px;height:${r.height + pad * 2}px`;
    const cw = Math.min(360, innerWidth - 24), ch = card.offsetHeight || 220;
    // prefer the right of the target, then below, then above, then left
    let x = r.right + 18, y = r.top;
    if (x + cw > innerWidth - 12) { x = Math.max(12, Math.min(r.left, innerWidth - cw - 12)); y = r.bottom + 16; }
    if (y + ch > innerHeight - 12) y = Math.max(12, r.top - ch - 16);
    if (y < 12) y = 12;
    card.style.cssText = `left:${x}px;top:${y}px;width:${cw}px`;
  }

  function go(d) {
    const n = i + d;
    if (n >= STEPS.length) return stop(true);
    if (n < 0) return;
    i = n; show();
  }

  function onKey(e) {
    if (!root) return;
    if (e.key === "Escape") { e.preventDefault(); stop(true); }
    else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    else if (e.key === "Tab") {  // keep focus inside the tour card
      const f = [...root.querySelectorAll("button")];
      const k = f.indexOf(document.activeElement);
      if (e.shiftKey && k <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && k === f.length - 1) { e.preventDefault(); f[0].focus(); }
    }
  }

  /** Called once the UI has booted: start automatically the very first time. */
  function maybeAutoStart() {
    if (store.get("tour.done", false)) return;
    setTimeout(() => { if (!document.querySelector(".tour, .modal:not([hidden])")) start(0); }, 700);
  }

  window.Tour = { start, stop, maybeAutoStart, steps: STEPS.length };
})();
