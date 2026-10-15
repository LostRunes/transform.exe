# Dr. Doc — Flutter (Android)

A port of the desktop Dr. Doc (formerly Everything Converter) to Flutter for Android, with the same
pastel retro-desktop UI, plus a new **Scan → PDF** feature that builds a PDF from
photos you take with the camera or pick from the gallery.

Everything runs **on the device**. There is no server, no upload, and no network
code — the `INTERNET` permission is explicitly stripped from the manifest so a
dependency cannot quietly add it back.

## Build and run

```
flutter pub get
flutter run                      # debug, on a connected device
flutter build apk --release      # release APK (for sideloading)
flutter build appbundle --release # Google Play bundle, signed with the upload key
```

Package name: `com.abinashmohanty.drdoc`. Release builds are signed with the Play
**upload key** in `android/upload-keystore.jks` + `android/key.properties` (both git-ignored;
without them the release build falls back to the debug key and prints a warning).
Publishing on Google Play, including the upload key, every Play Console form and the
listing text, is covered in [`store/README.md`](store/README.md).
Icons and Play graphics come from `../packaging/logo.png`: `python tool/make_android_assets.py`.

Requires the Flutter SDK (Dart 3.10+) and the Android SDK. `minSdk` is 24.

A universal release APK is ~79MB, most of it PDFium and the native codecs built
for every ABI. `flutter build apk --split-per-abi` produces per-architecture APKs
that are roughly a third of that, and an app bundle (`flutter build appbundle`)
does the same automatically.

### Permissions

The release build ships with camera and photo/video-read permissions and nothing else
(plus two harmless ones from Google's media library: network-state and wake-lock).
`MANAGE_EXTERNAL_STORAGE` ("All files access") is removed with `tools:node="remove"`
because Google Play only allows it for file managers, backup and antivirus apps.
`INTERNET` is stripped in `android/app/src/main/AndroidManifest.xml` with
`tools:node="remove"`, so no dependency can pull it in behind your back; debug and
profile builds re-add it from their own manifests so hot reload still works. The
camera plugin's `RECORD_AUDIO` and `READ_MEDIA_AUDIO` are removed the same way,
since the scanner only ever takes stills.

## What's new here: Scan → PDF

The sidebar's **Scan → PDF** page is Android-only and has no desktop counterpart.

- **Take photos** opens a full-screen camera that stays open between shots, so a
  ten-page document is ten taps. There's a torch toggle, a running page count and
  a thumbnail of the last shot.
- **From gallery** / **From files** pull in pictures you already have.
- Pages can be reordered by dragging, **cropped**, rotated individually, or removed.
- **Crop** (tap a page's preview, or its ⬚ button) opens a full-screen editor:
  drag the corners, rotate, thirds guides, reset. Edits always write a new file
  in the app's own cache, so a photo imported from the gallery is never altered.
- **Clean-up** converts pages to greyscale or high-contrast black-and-white before
  export, which makes text documents far smaller and more readable.
- Export writes one PDF, fitted to the photos or laid out on A4.

## UI

The look is ported from `web/style.css` rather than reimagined: the day/night
colour tokens, the Silkscreen + Nunito fonts, hard offset shadows, gradient title
bars with their little window buttons, the drifting clouds and twinkling
sparkles, the taskbar with its Start menu and clock, and the floating mascot that
wiggles when you poke it.

The one deliberate change is layout. The desktop app's CSS already collapses to a
single column below 960px, and this build follows the same rule: on a phone the
sidebar folds into the Start menu and the jobs window floats over the content.
On a tablet in landscape you get the full three-column desktop layout.

## What works

| Area | Notes |
|---|---|
| **Convert** | Any supported format to any other, with the same multi-step routing (e.g. DOCX → PDF → PNG) carried over from `core/registry.py` |
| Images | JPG, PNG, WebP, GIF, BMP, TIFF, ICO, TGA, HEIC, plus SVG → raster/PDF |
| Documents | PDF → text/HTML/Markdown/Word · Markdown/HTML/TXT/DOCX → PDF, and between each other |
| Spreadsheets | XLSX, XLS, CSV, TSV, JSON, XML → each other, plus SQL inserts, Markdown tables and PDF. Multi-sheet workbooks split into one file per sheet |
| **PDF tools** | Merge, split, extract/delete/reorder pages, rotate, compress, watermark, page numbers, password protect/remove, save pages as images |
| **PDF editor** | Text, boxes, ellipses, lines, arrows, freehand, highlighter, whiteout, undo. Always saves to a new copy |
| **Compress** | Any file, by a % slider or a typed-in target size (KB/MB/GB). Photos, PDFs, video, audio, Word/Excel/PowerPoint (pictures inside are recompressed), everything else zipped. Live "≈ before → after" estimate, and each job reports what it achieved |
| **Image tools** | Compress (by % / target size / quality), resize, rotate/flip/greyscale, strip EXIF/GPS, images → one PDF |
| **Video & audio** | Compress video (MP4, H.264/H.265, auto-lowers resolution when the size is tight) and audio (M4A/AAC, mono, sample rate) with the phone's hardware encoders |
| **Scan → PDF** | Camera and gallery capture, reorder, rotate, clean up, export |
| **Clean up** | Storage meter, app cache, and a duplicate / large-file / empty-folder finder |

Jobs run one at a time in a queue with live progress, cancel, and **Open / Save /
Share** on every finished file — the same model as `core/jobs.py`. **Save** opens
Android's own "Save to" dialog so a copy can go anywhere, which matters because
the app's own output folder is not always somewhere convenient. The PDF editor
saves through the same queue, so its output gets the same three actions.

## What did not carry over, and why

These are real gaps, not oversights. The desktop build leans on Windows-only or
native dependencies that have no equivalent here.

- **Video and audio, apart from compression.** Trimming, joining and format changes are
  FFmpeg underneath. The official `ffmpeg_kit_flutter` was retired in 2025 and the
  maintained fork adds 40–70MB to the APK along with LGPL/GPL obligations, so those
  stay greyed out. **Compression** does work: it runs on Android's own hardware
  encoders through Media3 Transformer (`MediaCompressor.kt`), which costs a few MB.
  Phone encoders treat a bitrate as a hint, so a target-size encode is checked and
  re-run lower if it overshoots. Audio is always saved as M4A (AAC), the format every
  Android device can encode.
- **Office-fidelity conversion.** The desktop app drives installed Word, Excel and
  PowerPoint over COM for exact rendering. Android has no such thing. DOCX is read
  and written directly as OOXML, which handles text well but not complex layout;
  PPTX and XLS→PDF via Office are gone.
- **Rewriting existing PDF text.** The desktop editor edits text spans in place via
  PyMuPDF. There is no pure-Dart equivalent, so the editor annotates on top instead.
- **Raster → SVG vectorising.** Needs a tracing algorithm (potrace) with no Dart port.
  SVG *input* works fine.
- **Recycle Bin.** Android has none, so Clean up deletes permanently and the confirm
  dialog says exactly that instead of promising an undo.

## Mobile layout

The desktop three-column layout only appears at 960px and up (a tablet in
landscape). On a phone:

- the sidebar is replaced by a **scrollable tab strip** under the title bar, so
  every screen is one tap away instead of being buried in the Start menu;
- the "save to" bar shows just the folder name rather than the full path;
- the jobs window is a sheet that stops above the taskbar, so the button that
  opened it stays reachable;
- Android **back** unwinds the UI — Start menu, then jobs panel, then tool page,
  then back to Convert — and only exits from Convert;
- the Convert overview collapses from six cards into one compact list.

## Known characteristics

- Conversions run on the main isolate, one job at a time. The queue yields between
  files, so the UI stays responsive across a batch, but a single very large image
  or PDF page can stutter the animations while it is being decoded. Moving the
  pure-Dart image work into `Isolate.run` would fix it; the PDFium and platform-codec
  paths have to stay on the root isolate either way.
- `Clean up`'s storage meter shells out to `df`. If a device restricts that, the
  card reads "unavailable" rather than showing a wrong number.
- **Clean up and the folder picker.** Since Android 11 the system folder picker
  refuses to grant access to `Download` or the root of internal storage — it
  answers "To protect your privacy, choose another folder". That is an OS rule,
  not something the app can work around. So the Clean up page offers quick picks
  for the folders Android *does* share (DCIM, Pictures, Documents…). Other apps'
  private files are never scanned; the Play build doesn't ask for "All files access".

## Layout

```
lib/main.dart            app entry, theme wiring
lib/shell.dart           sidebar, top bar, taskbar, Start menu, routing
lib/core/theme.dart      design tokens ported 1:1 from web/style.css
lib/core/registry.dart   conversion graph + tool catalogue (add formats here)
lib/core/jobs.dart       background job queue with progress and cancel
lib/core/models.dart     FileItem, ToolDef, ParamDef, Job
lib/core/fs.dart         output folder, safe naming, scratch space, permissions
lib/core/shrink.dart     size-targeted compression (% / target size), Office & zip, "Compress anything"
lib/engines/img.dart     images: decode, transform, compress, images → PDF
lib/engines/pdfeng.dart  PDF: merge, split, pages, security, rasterising
lib/engines/data.dart    tables: CSV/TSV/JSON/XML/XLSX/MD/SQL/HTML/PDF
lib/engines/doc.dart     text/Markdown/HTML/DOCX, and all of them to PDF
lib/engines/svg.dart     SVG rasterising
lib/engines/media.dart   video/audio compression (bitrate maths; encoding in android/…/MediaCompressor.kt)
lib/views/               one file per screen
lib/widgets/retro.dart   the window/button/control kit
lib/widgets/sky.dart     animated background
```

To add a conversion, write a function matching `ConvertFn` and register it with
`edge([...inputs], [...outputs], fn)` in `lib/core/registry.dart`. Chained routes
through it then work automatically, exactly as in the Python version.

## Dependencies worth knowing about

- **`syncfusion_flutter_pdf`** does the PDF structure work. It is free under
  Syncfusion's Community License for individuals and small companies, but it is
  **not** OSS-licensed — check their terms before shipping commercially.
- **`pdfrx`** bundles PDFium to render pages. Everything else is plain Dart or a
  standard Flutter plugin.

## Tests

```
flutter test
```

Covers the conversion graph (routing, aliases, multi-hop chains, and that every
target the UI offers is actually reachable), page-range parsing, and the
Markdown/HTML/DOCX conversions.
