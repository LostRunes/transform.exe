/* Working window buttons. Every retro window used to show a decorative minimise / maximise /
   close picture; this turns them into real controls:
     ▁  minimise: fold the window down to its title bar (click again to unfold)
     ▢  maximise: show the whole workspace (document, PDF, video, manual…) full screen
   Windows that have their own ✕ keep it. Double-clicking a title bar also toggles full screen,
   and F11 / Esc toggle / leave it. */
(function () {
  const { $, h, S } = window.App;
  let full = null;  // the element currently shown full screen

  /** What full screen shows: the whole workspace for windows inside a view, else the dialog itself. */
  const targetOf = (win) => win.closest(".view") || win.closest(".dialog") || win;
  const winOf = (bar) => bar.parentElement;  // .win (title bar) or .card (h3 header)

  function enter(target) {
    if (full === target) return;
    if (full) leave(false);
    full = target;
    target.classList.add("is-full");
    document.body.classList.add("has-full");
    // Real full screen (hides Windows' taskbar too). The page itself goes full screen, not the
    // workspace, so dialogs, previews and notifications can still appear on top.
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
    }
    sync();
    relayout();
  }

  function leave(exitScreen = true) {
    if (!full) return;
    full.classList.remove("is-full");
    full = null;
    document.body.classList.remove("has-full");
    if (exitScreen && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    sync();
    relayout();
  }

  const toggle = (win) => (full && full === targetOf(win) ? leave() : enter(targetOf(win)));

  /** Editors size themselves to the space they have; tell them it changed. */
  function relayout() {
    requestAnimationFrame(() => {
      dispatchEvent(new Event("resize"));
      if (S.view === "editor" && window.Editor) window.Editor.mount($("#view-editor"));
    });
  }

  /** Keep every maximise button's icon and label in step with the current state. */
  function sync() {
    document.querySelectorAll(".wc-max").forEach((b) => {
      const on = !!full && full === targetOf(winOf(b.closest(".titlebar, h3")));
      b.setAttribute("aria-pressed", String(on));
      b.title = on ? "Exit full screen (Esc)" : "Full screen (F11)";
      b.setAttribute("aria-label", b.title);
      b.classList.toggle("on", on);
    });
  }

  function addControls(bar) {
    bar.dataset.wc = "1";
    bar.classList.add("has-wc");
    const win = winOf(bar);
    const min = h("button", { class: "wc wc-min", type: "button", title: "Minimise", "aria-label": "Minimise",
      "aria-expanded": "true", onclick: (e) => {
        e.stopPropagation();
        const folded = win.classList.toggle("win-min");
        min.setAttribute("aria-expanded", String(!folded));
        min.title = folded ? "Restore" : "Minimise";
        min.setAttribute("aria-label", min.title);
      } });
    const max = h("button", { class: "wc wc-max", type: "button", onclick: (e) => { e.stopPropagation(); win.classList.remove("win-min"); toggle(win); } });
    const group = h("span", { class: "wc-group" }, min, max);
    const close = bar.querySelector(":scope > .tb-x");
    close ? bar.insertBefore(group, close) : bar.append(group);
    bar.addEventListener("dblclick", (e) => { if (!e.target.closest("button, input, select")) toggle(win); });
  }

  // Windows that get controls: everything inside a workspace, plus the big viewers that open as dialogs.
  const SELECTOR = [".view .win > .titlebar", ".view .card > h3:first-child",
    ".dialog.org-preview > .titlebar", ".dialog.text-dialog > .titlebar"].join(",");
  function scan() {
    document.querySelectorAll(SELECTOR).forEach((bar) => { if (!bar.dataset.wc) addControls(bar); });
    if (full && (!full.isConnected || full.hidden)) leave();  // switched workspace, or the dialog closed
    sync();
  }
  // Mutation callbacks already arrive batched, once per task; no animation frame needed (those
  // pause while the window isn't painting, which left new windows without buttons).
  new MutationObserver(scan).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
  scan();

  // Esc (handled by the browser in real full screen) or switching workspace leaves full screen.
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && full) leave(false); });
  addEventListener("keydown", (e) => {
    if (e.key === "F11") {
      e.preventDefault();
      if (full) return leave();
      const view = document.querySelector(".view:not([hidden])");
      if (view) enter(view);
    } else if (e.key === "Escape" && full && !e.defaultPrevented && document.querySelector("#modal")?.hidden !== false && !document.querySelector(".tour")) {
      leave();
    }
  });
  window.WinCtl = { enter, leave, toggle, get active() { return full; } };
})();
