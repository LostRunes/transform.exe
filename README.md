# Dr. Doc

*(formerly Everything Converter)*

A local, offline toolbox to convert, compress, combine and edit anything. Your files never leave your PC, and there are no size limits: if your disk can hold it, it converts.

## Android version

There is a Flutter port for Android in [`everything_flutter/`](everything_flutter/).
It keeps this UI, runs everything on-device, and adds a **Scan → PDF** page that
builds a PDF from camera shots or gallery photos. Compression (including video and
audio, via the phone's own encoders) works there too; the other FFmpeg tools and the
Office-backed conversions are Windows-only — see its README.

## Start

- **Development:** double-click **Start.bat**. It opens as an app window (Edge app mode). Close the black console window to quit. The first run on a new PC installs the Python packages, and that one step needs internet. After that everything works offline.
- **Desktop app:** `.venv\Scripts\python desktop.py` opens Dr. Doc in its own window (WebView2) with native file dialogs and "Open with" support. This is what the Microsoft Store build runs.
- **Microsoft Store / MSIX:** see [`store/README.md`](store/README.md). Build with `powershell -ExecutionPolicy Bypass -File packaginguild_msix.ps1 -SignForTesting`.

First launch shows a short guided tour (skip it, or replay it from Start → Take the tour). The full manual is built in: press **F1**, or **Ctrl+K** to search for any tool.

## What it does

| Area | Highlights |
|---|---|
| **Compress** | Shrink **any** file with a slider (*make it 60% smaller*) or a typed-in target (*under 200 KB*, *under 8 MB*). Photos search quality then resolution; PDFs downsample images; video uses two-pass encoding and drops resolution only when needed; audio picks the bitrate, channels and sample rate; Word/Excel/PowerPoint files recompress their pictures; anything else is zipped. Each job reports *before → after*. |
| **Combine into PDFs** | Big drag-to-reorder previews (rotate, remove, full-size preview, pick PDF pages), then make **one combined PDF**, **one PDF per file**, or **custom groups** like `1-3, 4, 5-8`. Works on Convert, Merge PDFs and Images → one PDF, and mixes in Word/Excel/Markdown files too. |
| **Docs & sheets** | Open Word documents and Excel/CSV spreadsheets to view and edit them; save a copy, save as another format, export to PDF, print. |
| **Video editor** | Timeline editor: trim, split, reorder and join clips, photos, text titles, music track (mix / duck / replace), crossfades, speed, volume, fades, rotate, crop, colour. Exports MP4/WebM/MOV/GIF/MP3/WAV at any size or shape (16:9, 9:16, 1:1…). Projects save as `.drdocvideo`. |
| **Convert** | Any supported format to any other. Multi-step routes are automatic (e.g. DOCX → PDF → PNG, XLSX → PDF → JPG, PDF → PNG → SVG). |
| Images | JPG, PNG, WebP, AVIF, HEIC, GIF, BMP, TIFF, ICO, TGA, plus **raster → SVG vectorising** and SVG → PNG/PDF |
| Documents | PDF ⇄ Word, Word/RTF/ODT/HTML/TXT/Markdown ⇄ each other, PowerPoint & Excel → PDF (uses your installed MS Office for perfect fidelity; pure-Python fallbacks otherwise) |
| Spreadsheets | XLSX, XLS, ODS, CSV, TSV, JSON, XML → each other, plus SQL inserts, Markdown tables, PDF. Multi-sheet workbooks split into one file per sheet. |
| Video | MP4, MKV, MOV, WebM, AVI, FLV, WMV, MPEG, 3GP, TS, **GIF ⇄ MP4** |
| Audio | MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WMA, AIFF, AC3, **extract audio from any video** |
| **PDF tools** | Merge, split, extract/delete/reorder pages, rotate, compress, watermark, page numbers, password protect/remove, extract images |
| **PDF editor** | Rewrite existing text, add text, rectangles, ellipses, lines, arrows, freehand, highlight, whiteout, images/signatures. Undo, move, resize. Always saves a copy. |
| **Image tools** | Compress (by % / target size / quality, WebP / AVIF), resize, rotate/flip/grayscale, strip EXIF/GPS, images → one PDF |
| **Video & audio tools** | Compress video and audio (by % / target size / quality, H.264/H.265, mono / sample rate), trim, resize/rotate/speed, join clips, remove audio, video → frames, volume/normalise |
| **Clean up** | Drive space, app cache, Windows temp files, Recycle Bin, **duplicate finder** (content-hashed), large-file finder, empty folders. Everything you remove goes to the Recycle Bin, except temp files. |

## Notes

- **Browse files** reads files where they are, with zero copying, so it's best for huge files. Drag & drop also works, but it copies the file into the app cache first.
- Output goes to `Downloads\Dr. Doc` by default. Change it with the "Save to" chip. Existing files are never overwritten.
- Scratch files live in `%LOCALAPPDATA%\DrDoc` (not on OneDrive), and are wiped after every job.
- Video/audio needs **ffmpeg**: `winget install Gyan.FFmpeg`, or drop `ffmpeg.exe` + `ffprobe.exe` into a `bin` folder here. LGPL ffmpeg builds (no x264/x265) work too: H.264 then goes through Windows' own Media Foundation encoder.
- The server listens on `127.0.0.1` only and rejects cross-site requests.

## Layout

```
app.py              web server + API (feature modules plug in as blueprints: core/api_*.py)
desktop.py          desktop shell: WebView2 window, native dialogs, Open-with, single instance
core/registry.py    conversion graph & tool catalogue (add new formats here)
core/conv_*.py      engines: image, pdf, doc (Office), data, media (ffmpeg)
core/pdf_editor.py  editor backend
core/shrink.py      size-targeted compression (% / target size), Office & zip, "Compress anything"
core/organize.py    combine files into one PDF / one each / groups (api_organize.py)
core/video_editor.py  video editor rendering (api_video.py)
core/office_editor.py document & spreadsheet editing (api_office.py)
core/cleanup.py     clean-up features
core/jobs.py        background jobs, progress, cancel
web/                UI (plain HTML/CSS/JS, no internet needed):
                    app.js shell · organize.js · editor.js (PDF) · office.js · video.js · help.js (manual, Ctrl+K) · tour.js
packaging/          PyInstaller spec + MSIX build/test scripts
store/              everything needed to publish on the Microsoft Store
tests/              video & office test suites
```

To add a conversion, write `fn(src: Path, out: Path, params) -> [paths]` and register it with `edge([...inputs], [...outputs], fn)` in `core/registry.py`. Chained routes to and from it then work automatically.

## License

Dr. Doc is free and open-source software under the **GNU Affero General Public License v3.0**; see [`LICENSE`](LICENSE). Source: https://github.com/LostRunes/transform.exe.
Third-party components keep their own licences (PyMuPDF is AGPL-3.0; the bundled FFmpeg is GPL); the full list ships with the app
(Help & manual → About) and in [`store/LICENSES/`](store/LICENSES/).

## Theme & mascots

Pastel retro-desktop look with a **day** (light) and **night** (dark) theme. Toggle it from the taskbar or the Start menu.
The mascots live in `web/assets/`. To use your own (or add the night-mode one), save the original sticker image as
`web/assets/source/mascot-light.png` or `web/assets/source/mascot-dark.png`, then run:

```
.venv\Scripts\python tools\make_mascot.py
```

It cuts the character out of its paper background and crops off the "SVG / PNG / JPG / PDF" bubbles automatically.
Fonts (Silkscreen, Nunito) are bundled in `web/fonts/` under the SIL Open Font License, so nothing loads from the internet.
