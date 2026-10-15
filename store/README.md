# How to publish Dr. Doc on the Microsoft Store

Everything you need is in this folder:

| Path | What it is |
|---|---|
| `DrDoc_<version>_x64.msix` | **The package you upload to Partner Center.** It's unsigned on purpose, because the Store signs it for you. ⚠️ The one here now was built with a *fake test identity*. Rebuild it with your real identity (step 4). |
| `DrDoc_<version>_x64_TEST-SIGNED.msix` | The same app signed with a self-signed test certificate, for installing on your own PC before you submit. **Don't upload this one.** |
| `test-cert/` | The test certificate (`.cer`) and its key (`.pfx`, password `drdoc-test`). Private. Don't share or commit it. |
| `build-info.txt` | What the last build contains (identity, version, size, SHA-256, FFmpeg build, smoke-test result) and the exact command to rebuild it |
| `listing/` | Copy-paste text for the Store listing, the privacy policy, the runFullTrust justification, age-rating answers and Store logos |
| `screenshots/` | 1920×1080 screenshots of the real app |
| `LICENSES/` | Third-party licences plus **an important licence review (read `LICENSES/README.md` first!)** |
| `CHECKLIST.md` | Tick-box list of everything you still need to do yourself |

The build tooling lives in `..\packaging\`. The build output goes to `%LOCALAPPDATA%\DrDocBuild` (outside OneDrive).

---

## 0. Licences (decided: open source)
Dr. Doc is **open source under AGPL-3.0** (https://github.com/LostRunes/transform.exe), which satisfies PyMuPDF's AGPL licence. The `LICENSE` file is at the repo root, and the app shows the licence, the source link and the third-party notices in **Help & manual → About Dr. Doc & open source**.

Keep doing these with every release:
* **Push the exact source of each release to the public repo** (tag it, e.g. `v1.0.0`) before or when it goes live. The AGPL requires that users can get the source of the version they have.
* **FFmpeg:** the bundled Gyan build is GPL, which is fine alongside AGPL as long as its source is available (the About page links ffmpeg.org and gyan.dev; the notices list the exact version). An LGPL build also works now: the app falls back to Windows' own H.264 encoder when x264 is missing (`-FfmpegDir <lgpl bin>`).
* Details: `LICENSES/README.md`.

## 1. Create a Microsoft Partner Center developer account
1. Go to **https://storedeveloper.microsoft.com** (or https://partner.microsoft.com/dashboard/registration) and sign in with a personal Microsoft account (Outlook/Hotmail). Use one you'll keep forever, because the app is tied to it.
2. Choose the account type:
   * **Individual**: for a solo developer. Since late 2024 Microsoft has offered **free** registration for individual developers, but check the price shown on the sign-up page. You'll need to verify your identity with an ID document and a selfie.
   * **Company**: needed if you publish as a business. There's a one-time fee (historically about US $99, depending on country), plus business verification such as a D-U-N-S number or a company email/domain. This can take a few days.
3. Your **publisher display name** (the "by …" shown in the Store) is chosen here. Pick it carefully, because changing it later is a hassle.
4. Fill in the payout and tax profile only if you'll charge money.

## 2. Reserve the name "Dr. Doc"
1. Partner Center → **Apps and games** → **+ New product** → **MSIX or PWA app**.
2. Enter **Dr. Doc** and click **Check availability** → **Reserve product name**.
3. If it's taken (it's a short, common name), try these, in order of preference:
   *Dr. Doc – File Converter*, *Dr. Doc: Convert & Compress*, *Dr Doc File Toolkit*, *Doctor Doc Converter*, *Dr. Doc Offline Converter*.
   The window title and Start-menu name in the package stay "Dr. Doc" (`DisplayName` in `packaging\AppxManifest.template.xml`). For the Store it's cleanest if the package `DisplayName` exactly matches a reserved name. If you reserve a different name, change `<DisplayName>` and `uap:VisualElements DisplayName` in the template to match.
4. A reservation lasts 3 months, so submit within that window.

## 3. Copy your package identity
Partner Center → your app → **Product management** → **Product identity**. Copy these three values:

| Partner Center shows | Build-script parameter | Example |
|---|---|---|
| `Package/Identity/Name` | `-IdentityName` | `12345JaneDoe.DrDoc` |
| `Package/Identity/Publisher` | `-Publisher` | `CN=1A2B3C4D-5E6F-7A8B-9C0D-1E2F3A4B5C6D` |
| `Package/Properties/PublisherDisplayName` | `-PublisherDisplayName` | `Jane Doe` |

## 4. Rebuild the package with your identity
From the repo folder, in PowerShell (no admin needed):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1 `
    -Version 1.0.0.0 `
    -IdentityName "12345JaneDoe.DrDoc" `
    -Publisher "CN=1A2B3C4D-5E6F-7A8B-9C0D-1E2F3A4B5C6D" `
    -PublisherDisplayName "Jane Doe" `
    -FfmpegDir "C:\ffmpeg-lgpl\bin"          # optional: the LGPL FFmpeg you downloaded (default: ffmpeg on PATH)
```

* It takes about 5 minutes. It regenerates icons, freezes the app with PyInstaller, bundles FFmpeg, writes the manifest, builds `resources.pri`, packs and re-validates the MSIX, and runs a smoke test that starts the app and does real PNG→JPG, PNG→PDF and WAV→MP3 conversions.
* Result: `store\DrDoc_1.0.0.0_x64.msix`. `store\build-info.txt` should say `Store identity: yes` and `Smoke test: PASSED`.
* **Versions:** the Store requires the last number to be `0`. Every new upload must be higher: 1.0.0.0 → 1.0.1.0 → 1.1.0.0.
* Useful switches: `-SignForTesting` (also make a self-signed copy for sideloading), `-SkipPyInstaller` (repack only), `-SkipTests`, `-NoFfmpeg`.
* Requirements: the `.venv` from `Start.bat` (with `pyinstaller` and `pywebview` installed), and the Windows 10/11 SDK. The script finds `makeappx`, `makepri` and `signtool` automatically.

## 5. (Recommended) Test the package on your PC first
Either of these works:

* **Developer Mode, no admin.** Settings → System → For developers → Developer Mode **On**. Then run
  `powershell -ExecutionPolicy Bypass -File packaging\test_install.ps1`
  It registers the built package, launches it from its Start-menu identity, runs real conversions and uninstalls it again. Add `-Keep` to keep it installed and try it yourself: right-click a PDF → Open with → Dr. Doc.
* **Real MSIX install, needs admin once.** Build with `-SignForTesting`, then double-click `test-cert\DrDocTest_DrDocDev.cer` → *Install Certificate* → **Local Machine** → *Place all certificates in the following store* → **Trusted People** → Finish. Then double-click `DrDoc_<version>_x64_TEST-SIGNED.msix` → Install.
  When you're done: Settings → Apps → Dr. Doc → Uninstall, and remove the certificate with `certlm.msc` → Trusted People → delete *DrDocDev*.
  (The test identity `CN=DrDocDev` differs from your Store identity, so test with a `-SignForTesting` build made with the default fake identity. The real Store build gets Microsoft's signature.)
* Optional: the **Windows App Certification Kit** (the Store runs the same checks) is installed with the SDK. Run it **as administrator**:
  `"C:\Program Files (x86)\Windows Kits\10\App Certification Kit\appcertui.exe"` → Validate Store App → pick the MSIX.

## 6. Create the submission
Partner Center → your app → **Start submission**. Work through each section:

### 6a. Pricing and availability
* **Markets:** all, or choose some.
* **Visibility:** Public audience. Use "Private audience" first if you want a hidden beta.
* **Pricing:** Free (or a price; a free trial is possible).
* **Release:** "as soon as possible after certification", or manual.

### 6b. Properties
* **Category:** **Productivity**. Subcategory, if shown: none. Alternative: *Utilities & tools*.
* **Privacy policy URL:** required. Host `listing/privacy-policy.md` (see the note at the bottom of that file: GitHub Pages is free) and paste the URL.
* **Website / support contact:** your GitHub page or email.
* **Product declarations:** tick "This app has been tested to meet accessibility guidelines" only if you really checked it. Leave the others as they are.
* **System requirements:** *Minimum*: 64-bit (x64), 4 GB memory. Note *"Microsoft Office (optional) improves Word/Excel/PowerPoint to PDF fidelity"* in the description.

### 6c. Age ratings
Fill in the IARC questionnaire using `listing/age-rating-notes.md` (expected result: 3+ / Everyone).

### 6d. Packages
* Drag in `store\DrDoc_<version>_x64.msix`. Partner Center validates it. If you see an identity mismatch, you built with the wrong `-IdentityName`/`-Publisher`.
* Device families: **Windows 10/11 Desktop** only.
* Because the package declares **`runFullTrust`** (a restricted capability), a **"Submission options" → "Restricted capabilities"** box appears. Paste the text from `listing/runFullTrust-justification.txt`.

### 6e. Store listing (English, United States)
Copy from `listing/description.md`: description, what's new, product features, keywords (search terms), copyright, additional licence terms and so on.
* **Screenshots:** at least 1, up to 10, PNG, **1366×768 or larger** (1920×1080 recommended, 16:9). Upload from `screenshots/` in this order: 01 convert, 02 home, 03 compress, 04 PDF tools, 06 video editor, 07 clean-up. Leave out 05 until the Docs & sheets screen is finished. Add captions; for example see the feature bullets.
  ⚠️ **Retake them when the new features are finished**, and before you submit: `.venv\Scripts\python packaging\screenshots.py`. Then check that no personal paths or usernames are visible. The current shots show `C:\Users\KIIT\...` and real temp-folder sizes. Change your output folder to something neutral or crop it out.
* **Store logos (optional):** `listing/store-logo-300.png` (1:1) and `listing/store-logo-1080.png`. Partner Center may also ask for a 1:1 box-art image of 1080×1080 or 2160×2160, and `store-logo-1080.png` works for that.
* Optional trailers: none needed.

### 6f. Submission options
* Restricted capabilities justification (see 6d).
* **Notes for certification** (helpful): *"Dr. Doc is an offline file converter. To test: open the app, click Browse files, pick any PDF or image, choose a target format and click Convert. The output appears in Downloads\Dr. Doc. No account or network connection is needed. Word/Excel/PowerPoint to PDF uses Microsoft Office when installed and a built-in converter otherwise."*

### 6g. Submit
Click **Submit to the Store**. Certification usually takes **1–3 business days**. You'll get an email. Common reasons for rejection, and how to avoid them:
* Missing or unreachable privacy-policy URL.
* Name or `DisplayName` mismatch with your reserved name.
* Screenshots that show other brands or personal data.
* App crashes on a clean PC without Office. Dr. Doc handles this: it falls back to built-in converters.
* The listing claims features that aren't in the build. Keep the description in sync with what ships.

## 7. Updating later
1. Bump the version (`-Version 1.0.1.0`), rebuild with the same identity parameters, and check that `Smoke test: PASSED`.
2. Partner Center → your app → **Update** (creates a new submission) → Packages → remove the old MSIX, upload the new one → update "What's new" → Submit.

## Troubleshooting the build
* **PyInstaller "IndexError: tuple index out of range"**: that's the Python 3.10.0 `dis` bug. `packaging\run_pyinstaller.py` patches it automatically. Upgrading the venv to Python ≥ 3.10.1 also fixes it.
* **makeappx 0x8007007b**: a bundled file uses an MSIX-reserved name (`[Content_Types].xml`, `_rels\*.rels`). The script removes these automatically. If a new library adds more, extend that step in `build_msix.ps1`.
* **A feature works from source but not in the packaged app**: a new Python dependency probably isn't collected. Add it to the `collect_all` list in `packaging\drdoc.spec`. Logs: `%LOCALAPPDATA%\DrDocBuild\logs\` and the app's own `%LOCALAPPDATA%\DrDoc\desktop.log`.
* **OneDrive locks**: all build folders are under `%LOCALAPPDATA%\DrDocBuild`, and only the final `.msix` is copied here. If OneDrive syncing the roughly 300 MB `.msix` files bothers you, right-click `store` → *Free up space* or move the repo out of OneDrive.
