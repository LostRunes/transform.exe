# Dr. Doc → Microsoft Store: your to-do list

Details for every step are in `README.md`.

## Decide (blocking)
- [x] Licence decided: **open source, AGPL-3.0** (https://github.com/LostRunes/transform.exe); `LICENSE` added; shown in the app's About page and in the Store "Additional license terms"
- [ ] Make the repo public and push/tag the exact source of the version you submit (e.g. `v1.0.0`)
- [x] `libx264`/`libx265` fallback done (Windows' H.264 encoder), so an **LGPL FFmpeg** works too. Optional: build with `-FfmpegDir <BtbN win64-lgpl bin>`; otherwise keep the GPL Gyan build (fine under AGPL)
- [ ] Link the exact source of the bundled FFmpeg (and of x265/libheif/libde265 from pillow-heif) in the GitHub release notes
- [ ] Confirm you own the rights to the mascot artwork

## Account & name
- [ ] Create a Partner Center developer account (individual or company), verify your identity, and choose a publisher display name
- [ ] Reserve the product name **Dr. Doc** (or an alternative). If it's different, update `DisplayName` in `packaging/AppxManifest.template.xml`
- [ ] Copy **Package/Identity/Name**, **Package/Identity/Publisher** and **PublisherDisplayName** from *Product identity*

## Build & test
- [ ] Wait until the new features (Docs & sheets, video editor, …) are merged
- [ ] Rebuild: `packaging\build_msix.ps1 -Version 1.0.0.0 -IdentityName … -Publisher … -PublisherDisplayName … [-FfmpegDir …]`
- [ ] `store\build-info.txt` says **Store identity: yes** and **Smoke test: PASSED**
- [ ] Sideload-test a `-SignForTesting` build (`packaging\test_install.ps1 -Keep`, or trust the test `.cer` in *Local Machine → Trusted People*)
- [ ] Try by hand: convert, compress-to-size, PDF editor, Docs & sheets, video editor, clean-up, **right-click → Open with → Dr. Doc**, file/folder pickers, a big video
- [ ] Test on a PC **without** Microsoft Office and **without** ffmpeg on PATH (a Windows Sandbox or VM is ideal)
- [ ] (Optional) Run the Windows App Certification Kit **as admin** on the MSIX

## Listing assets
- [ ] Fill in the date and contact email in `listing/privacy-policy.md`, publish it (for example on GitHub Pages) and note the URL
- [ ] Retake the screenshots after the features are final: `.venv\Scripts\python packaging\screenshots.py`
- [ ] Check the screenshots show no personal paths or usernames (currently `C:\Users\KIIT\…`) and drop any "isn't installed in this build" screens
- [ ] Review `listing/description.md` against what actually ships (remove claims for unfinished features)
- [ ] Support contact (email or GitHub issues) and website URL

## Submission (Partner Center)
- [ ] Pricing & availability: markets, Free/paid, visibility, release date
- [ ] Properties: category **Productivity**, privacy-policy URL, support info, system requirements
- [ ] Age ratings: IARC questionnaire (answers in `listing/age-rating-notes.md`)
- [ ] Packages: upload `store\DrDoc_<version>_x64.msix` (the **unsigned** one, not `_TEST-SIGNED`)
- [ ] Restricted capability **runFullTrust**: paste `listing/runFullTrust-justification.txt`
- [ ] Store listing: description, what's new, features, keywords, screenshots (1366×768+ PNG), logos, copyright
- [ ] Notes for certification (test steps, text in README step 6f)
- [ ] Submit, then wait 1–3 business days and watch your email for the certification result

## Housekeeping
- [ ] Don't commit `store/*.msix` or `store/test-cert/` (`store/.gitignore` covers them)
- [ ] When finished testing: uninstall the test package and remove the *DrDocDev* test certificate (`certlm.msc` / `certmgr.msc`)
- [ ] For each update: bump `-Version` (last number stays 0), rebuild, and upload in a new submission
