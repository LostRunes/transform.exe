# Licences: read this before you publish

> **Decided (Oct 2026): Option A.** Dr. Doc is open source under AGPL-3.0 at https://github.com/LostRunes/transform.exe. The `LICENSE` file is in the repo root, and the app shows the licence, source link and notices in Help & manual → About. What's left for each release: push/tag the exact source, and link the FFmpeg/pillow-heif sources in the release notes.

> I'm not a lawyer and this isn't legal advice. It's an engineering summary of the licences of what the build bundles, so you can decide with your eyes open. If the app will make money, get a short consultation.

The full licence texts of every bundled component are in **`THIRD-PARTY-NOTICES.txt`**. The build regenerates that file from the actual Python environment, and it ships inside the MSIX under `LICENSES\`.

## TL;DR: three copyleft components ship in the package

| Component | Licence | What it means for Dr. Doc |
|---|---|---|
| **PyMuPDF / MuPDF** (`pymupdf`, also pulled in by `pdf2docx`) | **AGPL-3.0**, or a paid Artifex commercial licence | ⚠️ **Biggest issue.** If you distribute an app that contains PyMuPDF, the *whole app* must be under AGPL-compatible terms **and you must publish its complete source code**. Closed-source distribution, free or paid, needs a commercial licence from Artifex (https://artifex.com/licensing). |
| **FFmpeg** (`bin\ffmpeg.exe`, `bin\ffprobe.exe`). The current build bundles the **Gyan.dev "full" build 9.0.1** | **GPL-3.0** (built with `--enable-gpl --enable-version3`: x264, x265, xvid, and so on) | You must make the *exact* corresponding FFmpeg source available (written offer or download link) for as long as you distribute it, and the GPL licence text must ship with it. The build copies it to `bin\FFMPEG-LICENSE.txt`. Linking isn't involved (we run it as a separate program), so FFmpeg's GPL does **not** by itself force Dr. Doc's own code to be GPL. |
| **pillow-heif binary wheel** (HEIC support) | BSD source, but the **Windows wheel is GPL-2.0+** because it bundles **x265**. It also bundles libheif and libde265 (LGPL-3.0). | Same as FFmpeg: offer the source of those libraries, or build/use a pillow-heif without the x265 encoder. HEIC *decoding* only needs libde265 (LGPL). |

Everything else is permissive (MIT, BSD, Apache-2.0, PSF, ZPL, HPND/MIT-CMU) or font licences (SIL OFL 1.1 for Nunito and Silkscreen). Those only require keeping the copyright and licence notices, which `THIRD-PARTY-NOTICES.txt` does.

## Your realistic options

### Option A: open-source Dr. Doc under AGPL-3.0 (cheapest, fully compliant)
1. Put the Dr. Doc source code in a public repository (for example GitHub) with a `LICENSE` file containing AGPL-3.0.
2. In the app's Help/About screen and in the Store description, say: "Dr. Doc is free software under the GNU AGPL-3.0. Source code: <repo URL>."
3. In the repo or the release notes, link the exact FFmpeg and pillow-heif/x265 source versions you shipped (see below).
4. AGPL-3.0 is compatible with GPL-3.0 (FFmpeg) and with GPL-2.0-or-later (x265), so the whole bundle is consistent.
5. You can still charge money in the Store under the AGPL, but anyone may rebuild it from your source.

### Option B: keep Dr. Doc closed-source
1. **Buy a commercial PyMuPDF licence from Artifex**, or replace PyMuPDF and pdf2docx with permissively licensed alternatives (for example `pypdfium2`, Apache-2.0/BSD, for rendering, and `pypdf`, BSD, for page operations). The second route is a substantial code change in `core/conv_pdf.py`, `core/pdf_editor.py` and `core/conv_doc.py`.
2. **Swap FFmpeg for an LGPL build** (see below), *and*
3. replace or rebuild **pillow-heif** without x265, or accept GPL-2.0 obligations for that DLL. Because it's loaded into the same process, the safest reading is that it should not ship in a closed-source app.

## Swapping FFmpeg for an LGPL build (recommended in either option)

* Download a `win64-lgpl` build (static, or `-shared`) from **https://github.com/BtbN/FFmpeg-Builds/releases**, for example `ffmpeg-n7.1-latest-win64-lgpl-7.1.zip`.
* Unzip it outside OneDrive and rebuild:
  `powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1 -FfmpegDir "C:\ffmpeg-lgpl\bin" ...`
  The build script detects `--enable-gpl` and warns you if you're still bundling a GPL build. It records which build was used in `store\build-info.txt` and in `bin\FFMPEG-README.txt` inside the package.
* **⚠️ Code change needed first.** LGPL builds do **not** contain the GPL encoders `libx264` and `libx265`. Today the app hard-codes them:
  * `core/conv_media.py` lines ~123, 131, 139, 217 (`libx264` / `libx265`)
  * `core/video_editor.py` line ~135 (`libx264`)

  With an LGPL FFmpeg these MP4/H.264/H.265 encodes would fail. They need a fallback such as `h264_mf` / `hevc_mf` (Windows Media Foundation hardware/software encoders, present in BtbN builds), `libopenh264` if available, or hardware encoders (`h264_nvenc`, `h264_qsv`, `h264_amf`). For example: probe `ffmpeg -encoders` once and pick the first available encoder from `libx264, h264_mf, libopenh264, mpeg4`. `libmp3lame`, `libopus`, `libvorbis` and `libvpx` are LGPL/BSD and are present in the LGPL builds.
* Even for LGPL FFmpeg you must ship its licence text (the build does this) and offer the source of the exact version, which is a link to the BtbN release and its source tag.

## Providing the source for GPL/LGPL binaries
Easiest compliant way: in your public repo or on your website, add a "Third-party source code" page that links:
* FFmpeg: the exact version and tag on https://github.com/FFmpeg/FFmpeg plus the build scripts (Gyan: https://www.gyan.dev/ffmpeg/builds/ ; BtbN: https://github.com/BtbN/FFmpeg-Builds), or host the source tarball yourself. Strictly, GPL-3 "corresponding source" should be available from **you** for as long as you distribute, so host a copy of the tarball.
* x265 4.2, libheif 1.23.4, libde265 1.1.3 (versions from `pillow_heif` 1.8.0's `LICENSES_bundled.txt`).
* PyMuPDF 1.28.2 / MuPDF 1.28.2 (only under Option A): https://github.com/pymupdf/PyMuPDF

## Other notes
* **odfpy** is tri-licensed (Apache-2.0 / GPL-2.0 / LGPL-2.1). We use it under Apache-2.0, so no copyleft applies.
* **opencv-python-headless** (Apache-2.0, needed by pdf2docx) bundles its own LGPL FFmpeg DLL (`opencv_videoio_ffmpeg*.dll`). Its notices are included.
* **PyInstaller**'s bootloader is GPL-2.0 *with an exception* that explicitly allows distributing frozen apps under any licence.
* **pythonnet / .NET Framework / WebView2**: WebView2 and .NET are Windows components and are not redistributed.
* **Fonts**: Nunito and Silkscreen are under SIL OFL 1.1, which allows bundling. Keep `OFL-*.txt` (already in `web/fonts/` and in the notices).
* **Mascot artwork**: make sure you own the rights to the Dr. Doc character art (`web/assets/source/`) and that it isn't derived from someone else's IP. The Store can take down apps over trademark or copyright complaints.
* **Patents**: H.264/H.265/AAC encoders can involve patent licensing in some countries. Microsoft's own Media Foundation encoders (`h264_mf`) are covered by Windows' licence, which is another reason to prefer them.
