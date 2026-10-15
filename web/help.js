/* Help: the in-app user manual (searchable, F1) and the "What do you want to do?" search (Ctrl+K). */
(function () {
  const { $, h, S, store } = window.App;
  const k = (s) => h("kbd", {}, s);
  const REPO = "https://github.com/LostRunes/transform.exe";  // public source code (AGPL-3.0)

  // ------------------------------------------------------------------ the manual
  // [id, title, keywords, html]
  const MANUAL = [
    ["start", "Getting started", "welcome basics add files drop browse output folder jobs", `
<p><b>Dr. Doc</b> converts, compresses, combines and edits files on your own computer. It works completely offline: nothing is uploaded, and there are no size limits. If your disk can hold it, Dr. Doc can work on it.</p>
<h4>The basics, in three steps</h4>
<ol>
<li><b>Pick a workspace</b> in the left sidebar (Convert, Compress, PDF tools, Docs &amp; sheets, Video editor…).</li>
<li><b>Add files.</b> Drop them anywhere on the window, click <b>Browse files</b>, or paste a file or folder path and press Enter. Browsing reads big files where they are, so nothing is copied.</li>
<li><b>Press the big button.</b> The work runs in the background. Watch it under <b>Jobs</b> on the taskbar, then use <b>Open</b> or <b>Show</b> on the result.</li>
</ol>
<h4>Where do my files go?</h4>
<p>Results are saved to the folder shown next to <b>save to</b> at the top (normally <i>Downloads\\Dr. Doc</i>). Click it to choose another folder, or <b>↗</b> to open it. Dr. Doc never overwrites anything: if a name is taken, it adds <i>(1)</i>, <i>(2)</i>… Your original files are never changed.</p>
<h4>Not sure where something is?</h4>
<p>Press ${"<kbd>Ctrl</kbd>+<kbd>K</kbd>"} (or the 🔍 button) and type what you want to do, like "combine photos into pdf" or "make video smaller".</p>`],

    ["convert", "Convert any file", "format change jpg png pdf word docx excel csv mp4 mp3 heic webp svg", `
<p>Open <b>Convert</b>, add files, and choose the format you want next to each file (the arrow →). When you have several files of the same type, use <b>All JPG →</b> to set them all at once. Dr. Doc remembers your last choice for each type.</p>
<p>Conversions that need several steps (for example DOCX → PDF → PNG) are worked out automatically.</p>
<table>
<tr><th>From</th><th>To</th></tr>
<tr><td>Images (JPG, PNG, WebP, HEIC, AVIF, GIF, TIFF, BMP, ICO, SVG)</td><td>Any other image, PDF, SVG (vectorised)</td></tr>
<tr><td>Documents (PDF, Word, RTF, ODT, Markdown, HTML, TXT, PowerPoint)</td><td>PDF, Word, HTML, text, Markdown, images of each page</td></tr>
<tr><td>Spreadsheets (XLSX, XLS, ODS, CSV, TSV, JSON, XML)</td><td>Each other, SQL inserts, Markdown tables, PDF</td></tr>
<tr><td>Video (MP4, MKV, MOV, WebM, AVI, …)</td><td>Other video formats, GIF, audio (MP3, WAV…)</td></tr>
<tr><td>Audio (MP3, WAV, FLAC, M4A, OGG, Opus, …)</td><td>Any other audio format</td></tr>
</table>
<p>Options for the chosen formats (quality, resolution, bitrate…) appear in <b>options.ini</b> below the list.</p>
<p class="note">Word, Excel and PowerPoint conversions are best when Microsoft Office is installed. Dr. Doc uses it automatically, and falls back to its own converters if Office isn't there. Video and audio need FFmpeg (the chips at the bottom-left show what's available).</p>`],

    ["combine", "Combine files into PDFs (one PDF, one each, or groups)", "merge combine join images photos to pdf order reorder arrange organise organize rotate group ranges separate single multiple preview", `
<p>Whenever two or more files are going to PDF, on <b>Convert</b>, <b>PDF tools → Merge PDFs</b>, or <b>Image tools → Images → one PDF</b>, they appear as big preview cards you can arrange.</p>
<h4>Arrange</h4>
<ul>
<li><b>Drag</b> a card to move it. A coloured bar shows where it will land.</li>
<li>Use <b>◀ ▶</b> on a card, or focus it and press ${"<kbd>Alt</kbd>+<kbd>←</kbd>/<kbd>→</kbd>"}.</li>
<li><b>↻</b> (or ${"<kbd>R</kbd>"}) rotates a page; <b>✕</b> (or ${"<kbd>Delete</kbd>"}) removes it from the list (not from your disk).</li>
<li><b>🔍</b>, a double-click or ${"<kbd>Enter</kbd>"} opens a large preview; use ${"<kbd>←</kbd> <kbd>→</kbd>"} to flip through, ${"<kbd>Esc</kbd>"} to close.</li>
<li><b>Sort A → Z / Z → A / Reverse</b> reorder everything at once.</li>
<li>For a PDF with several pages, type which <b>Pages</b> to include (e.g. <i>1-3, 7</i>). Leave it empty for all pages.</li>
</ul>
<h4>How many PDFs?</h4>
<ul>
<li><b>One combined PDF</b>: everything in the order shown. Give it a name if you like.</li>
<li><b>A separate PDF for each file</b>: one PDF per file, named like the originals.</li>
<li><b>Custom groups</b>: type which files go together, by their card numbers. Each comma makes a new PDF:
<br><code>1-3, 4, 5-8</code> → PDF 1 has files 1, 2, 3 · PDF 2 has file 4 · PDF 3 has files 5 to 8.
<br>Files you don't list either become their own PDFs or are left out (you choose). Each card shows which PDF it lands in.</li>
</ul>
<p><b>Pictures on</b> sets the page size for photos: fit each picture exactly, or place them on A4 / US Letter pages with an optional margin.</p>`],

    ["compress", "Compress (make files smaller)", "compress shrink reduce size smaller kb mb target percent slider quality photo video audio pdf word office zip", `
<p>Open <b>Compress</b> → <b>Compress anything</b> and drop in any mix of files, or use the compress tool inside PDF tools, Image tools or Video &amp; audio.</p>
<h4>How small?</h4>
<ul>
<li><b>Shrink by a percentage</b>: drag the slider ("make it 60% smaller").</li>
<li><b>Hit a target size</b>: type a number and pick KB / MB / GB ("at most 200 KB"). Great for upload limits.</li>
<li><b>Set the quality myself</b>: the classic quality / level / bitrate controls.</li>
</ul>
<p>A line under the settings estimates the result before you start, and each finished job says exactly what it achieved (e.g. <i>photo.jpg: 4.3 MB → 298 KB (−93%)</i>).</p>
<h4>What happens to each kind of file</h4>
<ul>
<li><b>Photos</b>: the best quality that fits; only if that's not enough is the picture made smaller in pixels.</li>
<li><b>PDFs</b>: repacked, then images inside are downsampled. Tick <i>flatten pages</i> only if you accept text no longer being selectable.</li>
<li><b>Video</b>: two-pass encoding so it lands on the size; resolution is lowered only when the size is tight (you can turn that off).</li>
<li><b>Audio</b>: the right bitrate, with optional mono and lower sample rate (great for voice).</li>
<li><b>Word / Excel / PowerPoint</b>: the pictures inside are recompressed.</li>
<li><b>Anything else</b> is zipped.</li>
</ul>
<p class="note">A file that's already under your target is copied unchanged. If a target is impossible, Dr. Doc saves the smallest it could make and tells you.</p>`],

    ["pdf", "PDF tools", "merge split extract delete reorder pages rotate watermark page numbers password protect unlock images", `
<ul>
<li><b>Merge PDFs</b>: combine PDFs and pictures, arranged visually (see <a data-help="combine">Combine files</a>).</li>
<li><b>Split PDF</b>: every page, every N pages, or custom ranges like <code>1-3; 4-10; 11-</code>.</li>
<li><b>Extract / delete / reorder pages</b>: keep or remove pages; list them in a new order like <code>3,1,2,4-</code>.</li>
<li><b>Rotate pages</b>, <b>Watermark</b>, <b>Add page numbers</b> (format such as <code>{n} / {total}</code>).</li>
<li><b>Password-protect</b> (AES-256) and <b>Remove password</b> (you need the current password).</li>
<li><b>Extract embedded images</b> pulls the original pictures out of a PDF.</li>
</ul>
<p>Page ranges everywhere: <code>1-3, 5, 8-</code> means pages 1 to 3, page 5, and 8 to the end. Blank means all pages.</p>`],

    ["pdfeditor", "PDF editor", "edit pdf text annotate draw sign signature highlight whiteout arrow shape image", `
<p>Open <b>PDF editor</b> and pick or drop a PDF. Choose a tool from the toolbar:</p>
<ul>
<li><b>Edit text</b>: click existing text to rewrite it.</li>
<li><b>Add text</b>, <b>Rectangle</b>, <b>Ellipse</b>, <b>Line</b>, <b>Arrow</b>, <b>Freehand</b>, <b>Highlight</b>, <b>Whiteout</b> (cover something up).</li>
<li><b>Image</b>: click where a picture or signature should go.</li>
<li><b>Select / move</b>: drag items around, ${"<kbd>Delete</kbd>"} removes them. ${"<kbd>Ctrl</kbd>+<kbd>Z</kbd>"} undoes.</li>
</ul>
<p>Saving always writes a new copy; your original is untouched.</p>`],

    ["office", "Docs & sheets (view and edit Word & Excel files)", "word docx doc edit document excel xlsx spreadsheet cells formula open view print export", `
<p>Open <b>Docs &amp; sheets</b> and pick or drop a file.</p>
<h4>Documents (DOCX, ODT, RTF, TXT, Markdown, HTML)</h4>
<p>Edit right on the page with the toolbar: styles and headings, fonts and sizes, bold / italic / underline, colours and highlight, alignment, lists, tables, images, links, page breaks, find &amp; replace. Common shortcuts work (${"<kbd>Ctrl</kbd>+<kbd>B</kbd>/<kbd>I</kbd>/<kbd>U</kbd>/<kbd>Z</kbd>/<kbd>Y</kbd>/<kbd>F</kbd>"}).</p>
<h4>Spreadsheets (XLSX, XLS, ODS, CSV, TSV)</h4>
<p>Click a cell and type; ${"<kbd>Enter</kbd>"} / ${"<kbd>Tab</kbd>"} / arrows move around; the formula bar shows formulas. Copy and paste works with Excel. Insert or delete rows and columns, sort, search, and switch sheets with the tabs at the bottom.</p>
<h4>Saving</h4>
<p><b>Save</b> writes a new copy (e.g. <i>report (edited).docx</i>) into your output folder. Saving over the original asks first. <b>Save as</b> and <b>Export to PDF</b> offer other formats, and <b>Print</b> prints just the page.</p>
<p class="note">PowerPoint files open read-only. With Microsoft Office installed they look exactly like the original.</p>`],

    ["video", "Video editor", "video edit trim cut split join combine merge clips music audio text title crossfade transition speed export timeline", `
<p>Open <b>Video editor</b> and add videos, pictures and music (Browse or drop). Then build your video on the timeline:</p>
<ul>
<li><b>Add to timeline</b> from the media bin. Clips play one after another.</li>
<li><b>Trim</b>: drag a clip's left or right edge. <b>Split</b> at the playhead with ${"<kbd>S</kbd>"}. <b>Delete</b> with ${"<kbd>Del</kbd>"}. Drag clips to reorder.</li>
<li><b>Inspector</b> (right): exact in/out times, speed (0.25×–4×), volume / mute, fades, rotate, crop, colour (brightness, contrast, saturation), how long a picture stays on screen.</li>
<li><b>Text</b>: add titles and captions with a start/end time, position, size and colour.</li>
<li><b>Music</b>: add a song on its own track, trim it, set its volume, and choose to mix it with or replace the clips' sound.</li>
<li><b>Transitions</b>: a crossfade between clips.</li>
<li>${"<kbd>Space</kbd>"} plays / pauses; ${"<kbd>Ctrl</kbd>+<kbd>Z</kbd>"} / ${"<kbd>Ctrl</kbd>+<kbd>Y</kbd>"} undo / redo; press <b>?</b> in the editor for all shortcuts.</li>
</ul>
<p><b>Export</b> picks the resolution, shape (16:9, vertical 9:16 for phones, square 1:1), quality and format (MP4, WebM, MOV, GIF, or just the audio). It runs as a job with progress you can cancel. Save the project to keep editing later.</p>
<p class="note">Needs FFmpeg. If the Video/Audio chip at the bottom-left shows ✕, install it (<code>winget install Gyan.FFmpeg</code>).</p>`],

    ["media", "Video & audio tools", "compress video audio trim cut resize rotate speed join clips remove audio frames volume normalise", `
<p>Quick one-step tools for when you don't need the full editor: <b>Compress video</b>, <b>Compress audio</b>, <b>Trim / cut</b>, <b>Resize / rotate / speed</b>, <b>Join clips</b>, <b>Remove audio</b>, <b>Video → image frames</b> and <b>Volume / normalise audio</b>. For anything more, use the <a data-help="video">Video editor</a>.</p>`],

    ["images", "Image tools", "image compress resize rotate flip grayscale exif gps metadata", `
<ul>
<li><b>Compress images</b>: by percentage, target size, or quality; optionally convert to WebP/AVIF.</li>
<li><b>Resize images</b>: by percentage or exact pixels (keeping the aspect ratio if you like).</li>
<li><b>Rotate / flip / grayscale</b>, and <b>strip EXIF/GPS</b> so photos don't reveal where they were taken.</li>
<li><b>Images → one PDF</b>: see <a data-help="combine">Combine files</a>.</li>
</ul>`],

    ["data", "Spreadsheet tools", "merge spreadsheets csv excel json combine rows", `
<p><b>Merge spreadsheets</b> stacks the rows of several CSV / Excel / JSON files into one sheet, optionally adding a column with the source file name. To change a spreadsheet's format, use <a data-help="convert">Convert</a>; to edit it, use <a data-help="office">Docs &amp; sheets</a>.</p>`],

    ["cleanup", "Clean up", "disk space temp files recycle bin duplicates large files empty folders free space", `
<p>See how full your drives are and free up space: clear Dr. Doc's own cache, Windows temp files, and the Recycle Bin. The finders look for <b>duplicate files</b> (compared by content, not just name), <b>large files</b> and <b>empty folders</b> in any folder you choose.</p>
<p class="note">Everything the finders remove goes to the Recycle Bin, so you can restore it. Only temp files are deleted directly.</p>`],

    ["keys", "Keyboard shortcuts", "keyboard shortcuts keys hotkeys", `
<table>
<tr><td>${k("Ctrl")} + ${k("K")}</td><td>Search: jump to any tool or help topic</td></tr>
<tr><td>${k("F1")}</td><td>Open this manual</td></tr>
<tr><td>${k("Alt")} + ${k("1")}…${k("9")}</td><td>Switch workspace (in sidebar order)</td></tr>
<tr><td>${k("Tab")} / ${k("Shift")}+${k("Tab")}</td><td>Move between buttons and fields</td></tr>
<tr><td>${k("Esc")}</td><td>Close a dialog, preview, menu or the tour</td></tr>
<tr><td colspan="2"><b>Arranging files</b></td></tr>
<tr><td>${k("←")} ${k("→")}</td><td>Move between cards</td></tr>
<tr><td>${k("Alt")} + ${k("←")} / ${k("→")}</td><td>Move the card earlier / later</td></tr>
<tr><td>${k("R")} · ${k("Delete")} · ${k("Enter")}</td><td>Rotate · remove · preview</td></tr>
<tr><td colspan="2"><b>Video editor</b></td></tr>
<tr><td>${k("Space")} · ${k("S")} · ${k("Del")}</td><td>Play/pause · split · delete clip</td></tr>
<tr><td>${k("Ctrl")}+${k("Z")} / ${k("Ctrl")}+${k("Y")}</td><td>Undo / redo (also in the PDF and document editors)</td></tr>
</table>`],

    ["access", "Accessibility & comfort", "accessibility text size bigger larger font zoom keyboard screen reader contrast motion animation", `
<ul>
<li><b>Text size</b>: Start → Text size cycles Normal / Large / Larger. ${"<kbd>Ctrl</kbd>+<kbd>+</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd>"} also zoom.</li>
<li><b>Keyboard</b>: everything works without a mouse. A clear outline shows where you are.</li>
<li><b>Calm mode</b>: Start → Reduce motion stops the floating mascot, clouds and sparkles (Windows' own "show animations" setting is respected too).</li>
<li><b>Day / night</b> themes from the taskbar.</li>
<li>Buttons and controls carry labels for screen readers, and progress and errors are announced.</li>
</ul>`],

    ["faq", "Troubleshooting & FAQ", "help problem error not working ffmpeg password office slow large file missing", `
<dl>
<dt>Video/Audio shows ✕</dt><dd>FFmpeg isn't installed. Run <code>winget install Gyan.FFmpeg</code> in a terminal, or place <i>ffmpeg.exe</i> and <i>ffprobe.exe</i> in Dr. Doc's <i>bin</i> folder, then restart.</dd>
<dt>"This PDF is password-protected"</dt><dd>Use PDF tools → Remove password with the current password first.</dd>
<dt>Word / Excel layout looks different</dt><dd>Install Microsoft Office for exact conversions; without it Dr. Doc uses its own converters, which keep text, tables and pictures but may simplify complex layouts.</dd>
<dt>A job failed</dt><dd>Open Jobs. The red text explains why. Other files in the same batch still finish.</dd>
<dt>It's slow with huge files</dt><dd>Use Browse instead of drag &amp; drop (dropping copies the file first). Big videos take as long as they take; cancel any time from Jobs.</dd>
<dt>Where are my files?</dt><dd>In the "save to" folder at the top. Click ↗ to open it.</dd>
</dl>`],

    ["privacy", "Privacy", "privacy offline internet upload data tracking", `
<p>Dr. Doc works entirely on your PC. It doesn't upload files, has no accounts, no ads, no analytics and no tracking. Your files are read where they are, and temporary copies are deleted after each job.</p>`],

    ["about", "About Dr. Doc & open source", "about version credits licence license open source source code github agpl gpl ffmpeg third party notices", `
<p><b>Dr. Doc</b>: convert, compress, combine and edit anything, offline.</p>
<h4>Free and open source</h4>
<p>Dr. Doc is free software, licensed under the <b>GNU Affero General Public License v3.0</b> (AGPL-3.0). You may use, study, share and change it; if you share a changed version, you must share its source code under the same licence.</p>
<p>Source code: <a data-url="${REPO}">${REPO.replace("https://", "")}</a></p>
<p><a data-text="/web/licenses/LICENSE.txt" data-title="LICENSE.txt">Read the full licence</a> · <a data-text="/web/licenses/THIRD-PARTY-NOTICES.txt" data-title="THIRD-PARTY-NOTICES.txt">Third-party notices</a></p>
<h4>Built with</h4>
<p>Python, PyMuPDF (AGPL-3.0), Pillow, pandas, openpyxl, python-docx, pdf2docx, Flask, pywebview and other open-source projects. Fonts: Silkscreen and Nunito (SIL Open Font License).</p>
<p><b>FFmpeg</b> (GPL) handles video and audio. Its source code is available at <a data-url="https://ffmpeg.org/download.html#get-sources">ffmpeg.org</a>; the bundled Windows build comes from <a data-url="https://www.gyan.dev/ffmpeg/builds/">gyan.dev</a>, and the exact version is listed in the third-party notices.</p>
<p>This program comes with ABSOLUTELY NO WARRANTY. See the licence for details.</p>`],
  ];

  let mounted = null, current = "start";

  /** External links open in the browser (inside the app window they'd replace the app). */
  const openUrl = (url) => window.App.api("/api/open-url", { url }).catch(window.App.fail);

  /** Show a bundled text file (licence, notices) in a scrollable dialog. */
  async function showText(url, title) {
    const m = $("#modal");
    const pre = h("pre", { class: "text-view", tabindex: "0" }, "Loading…");
    const close = () => { m.hidden = true; m.replaceChildren(); removeEventListener("keydown", key); };
    const key = (e) => { if (e.key === "Escape") close(); };
    m.replaceChildren(h("div", { class: "dialog win text-dialog", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "titlebar" }, h("span", {}, title), h("button", { class: "tb-x", "aria-label": "Close", onclick: close }, "✕")), pre));
    m.onclick = (e) => { if (e.target === m) close(); };
    m.hidden = false;
    addEventListener("keydown", key);
    pre.focus();
    try { const r = await fetch(url); pre.textContent = r.ok ? await r.text() : "Couldn't load this file."; } catch { pre.textContent = "Couldn't load this file."; }
  }

  function mount(el, id) {
    current = id || (location.hash.match(/topic=(\w+)/) || [])[1] || current;  // e.g. #view=help&topic=about
    const search = h("input", { type: "search", placeholder: "Search the manual…", "aria-label": "Search the manual", class: "help-search" });
    const toc = h("nav", { class: "help-toc", "aria-label": "Manual topics" });
    const body = h("article", { class: "help-body", tabindex: "-1" });
    const renderToc = () => {
      const q = search.value.trim().toLowerCase();
      const hits = MANUAL.filter(([, t, kw, html]) => !q || (t + " " + kw + " " + html.replace(/<[^>]+>/g, " ")).toLowerCase().includes(q));
      toc.replaceChildren(...hits.map(([id, t]) => h("a", { href: "#", class: id === current ? "on" : "", "aria-current": id === current ? "page" : null,
        onclick: (e) => { e.preventDefault(); open(id); } }, t)), hits.length ? null : h("p", { class: "muted sm" }, "No topic matches."));
    };
    const open = (id) => {
      current = id;
      const sec = MANUAL.find((m) => m[0] === id) || MANUAL[0];
      body.innerHTML = `<h2>${sec[1]}</h2>${sec[3]}`;
      body.querySelectorAll("a[data-help]").forEach((a) => { a.href = "#"; a.onclick = (e) => { e.preventDefault(); open(a.dataset.help); }; });
      body.querySelectorAll("a[data-url]").forEach((a) => { a.href = a.dataset.url; a.title = a.dataset.url + " (opens in your browser)"; a.onclick = (e) => { e.preventDefault(); openUrl(a.dataset.url); }; });
      body.querySelectorAll("a[data-text]").forEach((a) => { a.href = "#"; a.onclick = (e) => { e.preventDefault(); showText(a.dataset.text, a.dataset.title); }; });
      renderToc();
      body.scrollTop = 0;
    };
    search.oninput = renderToc;
    el.replaceChildren(h("div", { class: "help win" }, h("div", { class: "titlebar" }, h("span", {}, "manual.hlp")),
      h("div", { class: "help-top" }, search,
        h("button", { class: "btn ghost sm", onclick: () => window.Tour?.start(0) }, "▶ Take the tour"),
        h("button", { class: "btn ghost sm", onclick: openPalette }, "🔍 Find a tool (Ctrl+K)")),
      h("div", { class: "help-cols" }, toc, body)));
    mounted = { open };
    open(current);
  }

  /** Open the manual at a topic from anywhere. */
  function show(id) {
    window.App.route("help");
    mounted?.open(id || "start");
  }

  // ------------------------------------------------------------------ Ctrl+K: "What do you want to do?"
  const VIEW_WORDS = {
    convert: "convert change format jpg png pdf word to",
    "tools:Compress": "compress shrink smaller reduce size",
    "tools:PDF": "pdf merge split pages rotate watermark password",
    editor: "edit pdf sign annotate draw text",
    office: "word docx excel xlsx document spreadsheet edit open view",
    video: "video edit trim cut join clips music timeline",
    "tools:Image": "image photo picture resize compress",
    "tools:Video & Audio": "video audio mp4 mp3 compress trim",
    "tools:Data": "spreadsheet csv excel merge",
    cleanup: "clean disk space duplicates temp recycle",
    help: "help manual guide",
  };

  function entries() {
    const out = [];
    for (const [v, ico, label] of window.App.VIEWS) out.push({ ico, label, hint: "Workspace", words: VIEW_WORDS[v] || "", run: () => window.App.route(v) });
    for (const t of S.tools) out.push({ ico: t.icon, label: t.name, hint: t.cat, words: (t.desc || "") + " " + t.cat, run: () => window.App.openTool(t) });
    for (const [id, title, kw] of MANUAL) out.push({ ico: "?", label: title, hint: "Help", words: kw, run: () => show(id) });
    out.push({ ico: "▶", label: "Take the tour", hint: "Help", words: "tour guide introduction walkthrough", run: () => window.Tour?.start(0) });
    out.push({ ico: "📁", label: "Open output folder", hint: "Action", words: "output folder saved results explorer", run: () => window.App.api("/api/open", { path: S.outDir }).catch(window.App.fail) });
    out.push({ ico: "◐", label: "Day / night theme", hint: "Action", words: "dark light theme night day", run: () => $("#theme").click() });
    out.push({ ico: "♥", label: "Source code on GitHub", hint: "Action", words: "github source code open source repository contribute", run: () => openUrl(REPO) });
    out.push({ ico: "A", label: "Text size", hint: "Action", words: "text size bigger larger font zoom accessibility", run: () => window.App.cycleTextSize() });
    return out;
  }

  function score(e, q) {
    const label = e.label.toLowerCase(), hay = (e.label + " " + e.hint + " " + e.words).toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    if (!words.every((w) => hay.includes(w))) return -1;
    return (label.startsWith(q) ? 100 : 0) + (label.includes(q) ? 50 : 0) + words.filter((w) => label.includes(w)).length * 10 - (e.hint === "Help" ? 5 : 0);
  }

  function openPalette() {
    const m = $("#modal");
    const all = entries();
    let sel = 0, shown = [];
    const input = h("input", { type: "search", class: "pal-input", placeholder: "What do you want to do? e.g. combine photos into pdf", "aria-label": "Search tools and help", role: "combobox", "aria-expanded": "true", "aria-controls": "pal-list" });
    const list = h("div", { class: "pal-list", id: "pal-list", role: "listbox" });
    const close = () => { m.hidden = true; m.replaceChildren(); removeEventListener("keydown", key, true); };
    const pick = (e) => { close(); e.run(); };
    const render = () => {
      const q = input.value.trim().toLowerCase();
      shown = q ? all.map((e) => [score(e, q), e]).filter(([s]) => s >= 0).sort((a, b) => b[0] - a[0]).map(([, e]) => e) : all.filter((e) => e.hint !== "Help").slice(0, 14);
      sel = Math.min(sel, Math.max(0, shown.length - 1));
      list.replaceChildren(...shown.slice(0, 40).map((e, i) => h("div", { class: "pal-item" + (i === sel ? " on" : ""), role: "option", "aria-selected": i === sel ? "true" : "false", id: "pal-" + i,
        onclick: () => pick(e), onmousemove: () => { if (sel !== i) { sel = i; render(); } } },
        h("span", { class: "pal-ico" }, e.ico), h("span", { class: "pal-label" }, e.label), h("span", { class: "pal-hint" }, e.hint))),
        shown.length ? null : h("div", { class: "muted sm", style: "padding:12px" }, "Nothing matches. Try other words, or press F1 for the manual."));
      input.setAttribute("aria-activedescendant", shown.length ? "pal-" + sel : "");
      list.querySelector(".on")?.scrollIntoView({ block: "nearest" });
    };
    const key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
      else if (e.key === "Enter" && shown[sel]) { e.preventDefault(); pick(shown[sel]); }
    };
    input.oninput = () => { sel = 0; render(); };
    m.replaceChildren(h("div", { class: "dialog win cmd-palette", role: "dialog", "aria-modal": "true", "aria-label": "Find a tool" },
      h("div", { class: "titlebar" }, h("span", {}, "find.exe")), h("div", { class: "pal-body" }, input, list)));
    m.onclick = (e) => { if (e.target === m) close(); };
    m.hidden = false;
    addEventListener("keydown", key, true);
    render();
    input.focus();
  }

  window.Help = { mount, show, openPalette, topics: MANUAL.map(([id, t]) => [id, t]) };
})();
