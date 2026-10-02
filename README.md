# Everything Converter

A local, offline "convert anything to anything" toolbox. Your files never leave your PC, and there are no size limits: if your disk can hold it, it converts.

## Start

Double-click **Start.bat**. It opens as an app window (Edge app mode). Close the black console window to quit.

The first run on a new PC installs the Python packages, and that one step needs internet. After that everything works offline.

## What it does

| Area | Highlights |
|---|---|
| **Convert** | Any supported format to any other. Multi-step routes are automatic (e.g. DOCX → PDF → PNG, XLSX → PDF → JPG, PDF → PNG → SVG). |
| Images | JPG, PNG, WebP, AVIF, HEIC, GIF, BMP, TIFF, ICO, TGA, plus **raster → SVG vectorising** and SVG → PNG/PDF |
| Documents | PDF ⇄ Word, Word/RTF/ODT/HTML/TXT/Markdown ⇄ each other, PowerPoint & Excel → PDF (uses your installed MS Office for perfect fidelity; pure-Python fallbacks otherwise) |
| Spreadsheets | XLSX, XLS, ODS, CSV, TSV, JSON, XML → each other, plus SQL inserts, Markdown tables, PDF. Multi-sheet workbooks split into one file per sheet. |
| Video | MP4, MKV, MOV, WebM, AVI, FLV, WMV, MPEG, 3GP, TS, **GIF ⇄ MP4** |
| Audio | MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WMA, AIFF, AC3, **extract audio from any video** |
| **PDF tools** | Merge, split, extract/delete/reorder pages, rotate, compress, watermark, page numbers, password protect/remove, extract images |
| **PDF editor** | Rewrite existing text, add text, rectangles, ellipses, lines, arrows, freehand, highlight, whiteout, images/signatures. Undo, move, resize. Always saves a copy. |
| **Image tools** | Compress (quality / max size / WebP / AVIF), resize, rotate/flip/grayscale, strip EXIF/GPS, images → one PDF |
| **Video & audio tools** | Compress (by quality *or* target MB, H.264/H.265), trim, resize/rotate/speed, join clips, remove audio, video → frames, volume/normalise |
| **Clean up** | Drive space, app cache, Windows temp files, Recycle Bin, **duplicate finder** (content-hashed), large-file finder, empty folders. Everything you remove goes to the Recycle Bin, except temp files. |

## Notes

- **Browse files** reads files where they are, with zero copying, so it's best for huge files. Drag & drop also works, but it copies the file into the app cache first.
- Output goes to `Downloads\Everything Converter` by default. Change it with the "Save to" chip. Existing files are never overwritten.
- Scratch files live in `%LOCALAPPDATA%\EverythingConverter` (not on OneDrive), and are wiped after every job.
- Video/audio needs **ffmpeg**: `winget install Gyan.FFmpeg`, or drop `ffmpeg.exe` + `ffprobe.exe` into a `bin` folder here.
- The server listens on `127.0.0.1` only and rejects cross-site requests.

## Layout

```
app.py              web server + API
core/registry.py    conversion graph & tool catalogue (add new formats here)
core/conv_*.py      engines: image, pdf, doc (Office), data, media (ffmpeg)
core/pdf_editor.py  editor backend
core/cleanup.py     clean-up features
core/jobs.py        background jobs, progress, cancel
web/                UI (plain HTML/CSS/JS, no internet needed)
```

To add a conversion, write `fn(src: Path, out: Path, params) -> [paths]` and register it with `edge([...inputs], [...outputs], fn)` in `core/registry.py`. Chained routes to and from it then work automatically.

## Theme & mascots

Pastel retro-desktop look with a **day** (light) and **night** (dark) theme. Toggle it from the taskbar or the Start menu.
The mascots live in `web/assets/`. To use your own (or add the night-mode one), save the original sticker image as
`web/assets/source/mascot-light.png` or `web/assets/source/mascot-dark.png`, then run:

```
.venv\Scripts\python tools\make_mascot.py
```

It cuts the character out of its paper background and crops off the "SVG / PNG / JPG / PDF" bubbles automatically.
Fonts (Silkscreen, Nunito) are bundled in `web/fonts/` under the SIL Open Font License, so nothing loads from the internet.
