# Dr. Doc for Android → Google Play

Everything needed to publish the Android app. The Windows version has its own guide in `../../store/README.md`.

| File | What it's for |
|---|---|
| `DrDoc_<version>_android.aab` | The app bundle you upload (not committed to git; rebuild it, see below) |
| `play-icon-512.png` | **App icon** (Store listing → Graphics) |
| `feature-graphic-1024x500.png` | **Feature graphic** (Store listing → Graphics) |

App facts you'll be asked for:

* **Package name:** `app.drdoc.android` (permanent; it can never change once uploaded)
* **Version:** 1.0.0 (version code 1). Bump `version:` in `pubspec.yaml` (e.g. `1.0.1+2`) for every new upload; the number after `+` must always go up.
* **Target / min SDK:** Android 16 (API 36) / Android 7.0 (API 24). Native libraries are 16 KB page-aligned (checked).
* **Privacy policy URL:** https://lostrunes.github.io/Dr.-Doc-privacy-policy/
* **Source code:** https://github.com/LostRunes/transform.exe (AGPL-3.0)

---

## ⚠️ The upload key: back it up now

The bundle is signed with an **upload key**: `android/upload-keystore.jks`, whose passwords are in `android/key.properties`. Both are git-ignored on purpose.

* **Lose them and you can't publish updates** until Google resets your upload key, which needs a support request and takes days.
* Copy **both files** to two safe places now (e.g. a password manager and a private USB/drive). Never commit them or post them anywhere.
* Certificate SHA-256 fingerprint (Play shows this too):
  `53:A5:31:3C:5A:34:3F:7D:DA:B5:1F:2D:EE:4B:16:48:72:0E:09:8C:64:0E:F9:45:30:DB:8E:21:A4:BC:C3:E2`

When you upload the first bundle, accept **Play App Signing**. Google then keeps the real app signing key and this file is only your *upload* key.

## Rebuilding the bundle

```
cd everything_flutter
flutter build appbundle --release
```

Output: `build/app/outputs/bundle/release/app-release.aab`. If OneDrive locks the `build` folder (it does on this machine), copy the project to a folder outside OneDrive and build there; `android/key.properties` points to the keystore with a relative path, so copy `android/upload-keystore.jks` along with it.
After changing `packaging/logo.png`, regenerate the icons with `python tool/make_android_assets.py`.

---

## Publishing, step by step

### 1. Developer account
1. https://play.google.com/console/signup → personal account (one-time **US$25** fee, identity verification).
2. **New personal accounts must run a closed test before production:** at least **12 testers** opted in for **14 days in a row**. Start this as early as possible. Ask friends to join; they need a Google account and an Android phone.

### 2. Create the app
Play Console → **Create app**: name **Dr. Doc**, default language English (United States), **App**, **Free**, then tick the declarations.

### 3. App content (Policy → App content)
Answer each section like this:

| Section | Answer |
|---|---|
| **Privacy policy** | `https://lostrunes.github.io/Dr.-Doc-privacy-policy/` |
| **Ads** | No, the app does not contain ads |
| **App access** | All functionality is available without special access (no login) |
| **Content rating** | Category **Utility, productivity, communication, or other**. Answer **No** to every question (no violence, sexual content, language, controlled substances, gambling, user-generated content sharing, no location sharing). The rating should come out as Everyone / PEGI 3 |
| **Target audience** | 13 and over (picking under-13 brings extra Families-policy requirements). Not designed for children |
| **News app** | No |
| **COVID-19 tracing** | No |
| **Data safety** | See below |
| **Government app** | No |
| **Financial features** | None |
| **Health** | None (the doctor mascot is a theme, not a health app) |
| **Photo and video permissions** | See below. **Important** |

#### Data safety
* Does your app collect or share any of the required user data types? **No.**
  (Everything is processed on the device and the app has no internet permission. On-device processing that never leaves the phone doesn't count as "collection" under Google's definitions.)
* Is all of the user data collected by your app encrypted in transit? Not applicable (no data collected).
* Do you provide a way for users to request that their data is deleted? Not applicable.
* Result shown on the listing: **"No data collected · No data shared"**.

#### Photo and video permissions declaration
The app declares `READ_MEDIA_IMAGES` and `READ_MEDIA_VIDEO`. Google asks why it needs broad access instead of the system photo picker. Suggested answer:

> Dr. Doc includes a storage clean-up tool ("Clean up") that finds duplicate and unusually large photos and videos so users can free space. Finding duplicates requires reading every photo and video in the user's media folders and comparing their contents, which the photo picker (one-off selection of a few items) cannot provide. Access is requested only when the user starts a scan on the Clean up screen; files are processed entirely on the device, nothing is uploaded (the app has no internet permission), and nothing is deleted without the user's explicit confirmation. Picking individual photos to convert uses the system photo picker.

If Google rejects this, the fallback is to remove both permissions in `android/app/src/main/AndroidManifest.xml` (add `tools:node="remove"` like the other removed permissions). Clean up would then only scan the app's own files and the folders the user picks, but everything else keeps working. Ask Claude to make that change if needed.

### 4. Store listing (Grow → Store presence → Main store listing)

**App name** (≤ 30): `Dr. Doc`

**Short description** (≤ 80):
```
Convert, compress & scan files to PDF, offline and private. No ads, no uploads.
```

**Full description** (≤ 4000):
```
Dr. Doc is a friendly all-in-one file toolkit that works entirely on your phone. No account, no ads, no uploads, and no internet permission at all, so your files never leave your device.

CONVERT ANYTHING
• Images: JPG, PNG, WebP, HEIC, GIF, BMP, TIFF, ICO, SVG → any other format or PDF
• Documents: PDF → Word, text, HTML or Markdown; Word, Markdown, HTML and TXT → PDF
• Spreadsheets: Excel, CSV, TSV, JSON and XML ↔ each other, plus PDF and Markdown tables
• Multi-step conversions are worked out for you

COMPRESS TO ANY SIZE
• Drag a slider ("make it 60% smaller") or type an exact size ("under 200 KB")
• Photos, PDFs, videos, music and Word/Excel/PowerPoint files
• Videos and audio use your phone's own hardware encoder
• See exactly how much you saved

SCAN TO PDF
• Snap pages with the camera, or pick photos from your gallery
• Crop, rotate, reorder, and clean up to black & white for sharp text
• Export one tidy PDF, fitted to the photos or on A4 pages

PDF TOOLS
• Merge, split, extract, delete and reorder pages
• Rotate, watermark, add page numbers
• Password-protect or remove a password
• Annotate: text, boxes, arrows, freehand, highlighter, whiteout

CLEAN UP YOUR PHONE
• Find duplicate photos and videos, very large files and empty folders
• Clear the app's cache
• Nothing is deleted without your confirmation

PRIVATE BY DESIGN
• 100% offline: the app has no internet permission
• No account, no ads, no tracking, no analytics
• Free and open source (AGPL-3.0): github.com/LostRunes/transform.exe

A pastel retro-desktop look with day and night themes, and a little doctor mascot who keeps you company.
```

**Graphics:**
* App icon: `play-icon-512.png`
* Feature graphic: `feature-graphic-1024x500.png`
* **Phone screenshots:** 2–8 needed (PNG/JPEG, 16:9 or 9:16, at least 320 px on the short side). Take them on a real phone with **Power + Volume down**: the Convert screen with a few files, Compress with the slider, Scan → PDF with pages, PDF tools, Clean up, night theme. Optional tablet screenshots use the same layout in landscape.

**Category:** Productivity · **Tags:** Productivity, Tools · **Contact email:** abinash.mohanty.contact@gmail.com · **Website:** https://github.com/LostRunes/transform.exe

### 5. Closed testing (required for new personal accounts)
1. Testing → **Closed testing** → Create track → **Create new release** → upload `DrDoc_1.0.0_android.aab`.
2. Release name `1.0.0`, release notes: `First release of Dr. Doc for Android.`
3. Add testers (an email list or a Google Group) and share the opt-in link. Get **12+ testers opted in, and keep them for 14 days**.
4. Countries: pick India (and any others), then **Send for review**. Reviews of the first release can take a few days.

### 6. Production
After the 14 days, Play Console unlocks **Apply for production access** (a short questionnaire about your testing). Once approved: Production → Create new release → reuse the same bundle (or a newer one) → roll out.

---

## Before you upload: test on a real phone
Some features could only be checked on a computer here, and **video/audio compression has never run on a real device**. Install the release build on one or two phones (the closed test is the easiest way) and try:

- [ ] Compress a video by 50% and to a target size (e.g. 5 MB); play the result
- [ ] Compress a voice note / song
- [ ] Scan → PDF with the camera (several pages, crop, rotate)
- [ ] Convert a few photos to one PDF, a PDF to images, a Word file to PDF
- [ ] Clean up → scan DCIM for duplicates (grant the photos/videos permission)
- [ ] Open / Save / Share a finished file
- [ ] Night theme, and rotate the phone

## Licences
* The app code is AGPL-3.0, like the desktop version (`../../LICENSE`).
* It uses **Syncfusion's PDF library** under the free **Syncfusion Community License**, which is only for individuals and organisations with less than US$1 million annual revenue (and ≤ 5 developers). Fine for now; revisit if Dr. Doc ever earns money at that scale.
* PDFium (via pdfrx) is BSD/Apache. Everything else is permissive (see `flutter pub deps`).
