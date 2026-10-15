<#
.SYNOPSIS
  Build the Dr. Doc MSIX package (Microsoft Store / sideload) from this repo.

.DESCRIPTION
  1. generates icons/logos from web\assets\mascot-light.png      (packaging\make_assets.py)
  2. freezes desktop.py with PyInstaller (onedir, windowed)        (packaging\drdoc.spec)
  3. bundles ffmpeg.exe + ffprobe.exe into bin\                     (-FfmpegDir, or the one on PATH)
  4. stages the package layout, fills AppxManifest.xml, builds resources.pri
  5. makeappx pack  ->  store\DrDoc_<Version>_x64.msix   (UNSIGNED: this is the file you upload to Partner Center)
  6. optional -SignForTesting: self-signed cert (same Publisher CN) -> store\DrDoc_<Version>_x64_TEST-SIGNED.msix
  7. smoke test: starts the frozen exe, checks /api/caps and runs real conversions
  8. optional -Screenshots: retakes store\screenshots with headless Edge

  Build output (PyInstaller work/dist, layout) lives in %LOCALAPPDATA%\DrDocBuild (outside OneDrive, which locks
  build folders). Only the final .msix files and notices are copied into store\. Safe to re-run any time.

.EXAMPLE
  # local test build (fake identity) + signed sideload copy
  powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1 -SignForTesting

.EXAMPLE
  # Store build: values from Partner Center > Product management > Product identity
  powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1 -Version 1.0.0.0 `
      -IdentityName "12345YourName.DrDoc" -Publisher "CN=1A2B3C4D-...." -PublisherDisplayName "Your Name" `
      -FfmpegDir "C:\ffmpeg-lgpl\bin"
#>
[CmdletBinding()]
param(
    [string]$Version = "1.0.0.0",
    [string]$IdentityName = "DrDocDev.DrDoc",            # FAKE - replace with Partner Center "Package/Identity/Name"
    [string]$Publisher = "CN=DrDocDev",                  # FAKE - replace with Partner Center "Package/Identity/Publisher"
    [string]$PublisherDisplayName = "Dr. Doc (dev build)",  # replace with Partner Center "PublisherDisplayName"
    [string]$FfmpegDir = "",                             # folder containing ffmpeg.exe + ffprobe.exe (default: the one on PATH)
    [switch]$NoFfmpeg,                                   # build without bundled ffmpeg (video/audio disabled unless on PATH)
    [switch]$SignForTesting,                             # also produce a self-signed copy for sideload testing
    [string]$TestCertPassword = "drdoc-test",
    [switch]$SkipPyInstaller,                            # reuse the previous PyInstaller output
    [switch]$SkipTests,
    [switch]$Screenshots,                                # also retake store\screenshots (headless Edge)
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA "DrDocBuild"),
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = Split-Path -Parent $PSScriptRoot
$Pack = $PSScriptRoot
$Store = Join-Path $Root "store"
if (-not $Python) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "WARNING: $msg" -ForegroundColor Yellow }
function Run($exe, [string[]]$argv, [string]$log = "") {
    $eap = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # tools log to stderr; judge by exit code
    try {
        if ($log) { & $exe @argv *> $log } else { & $exe @argv }
    } finally { $ErrorActionPreference = $eap }
    if ($LASTEXITCODE -ne 0) {
        if ($log) { Get-Content $log -Tail 25 | ForEach-Object { Write-Host "  $_" } }
        throw "$([IO.Path]::GetFileName($exe)) failed with exit code $LASTEXITCODE$(if ($log) { " (full log: $log)" })"
    }
}
function Reset-Dir($p) {
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    New-Item -ItemType Directory -Force $p | Out-Null
}
function Xml-Escape($s) { return [Security.SecurityElement]::Escape($s) }

# ---------------------------------------------------------------- checks
if ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw "Version must look like 1.0.0.0 (four numbers)" }
if (-not $Version.EndsWith(".0")) { Warn "Microsoft Store requires the last version number to be 0 (e.g. 1.0.1.0)." }
if (-not (Test-Path $Python)) { throw "Python not found at $Python (create the .venv first - see Start.bat)" }
if ($Publisher -notmatch '^CN=') { throw "Publisher must start with CN= (copy it exactly from Partner Center)" }
$isStoreIdentity = ($Publisher -ne "CN=DrDocDev") -and ($IdentityName -ne "DrDocDev.DrDoc")
if (-not $isStoreIdentity) { Warn "Using the FAKE dev identity ($IdentityName / $Publisher). Fine for testing, NOT for the Store." }

# Windows SDK: newest version that has makeappx + makepri + signtool
$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$Sdk = Get-ChildItem $kits -Directory -Filter "10.*" -ErrorAction SilentlyContinue |
    Sort-Object { [version]$_.Name } -Descending |
    ForEach-Object { Join-Path $_.FullName "x64" } |
    Where-Object { (Test-Path (Join-Path $_ "makeappx.exe")) -and (Test-Path (Join-Path $_ "makepri.exe")) -and (Test-Path (Join-Path $_ "signtool.exe")) } |
    Select-Object -First 1
if (-not $Sdk) { throw "Windows 10/11 SDK not found (need makeappx/makepri/signtool). Install it: winget install Microsoft.WindowsSDK.10.0.26100" }
$MakeAppx = Join-Path $Sdk "makeappx.exe"; $MakePri = Join-Path $Sdk "makepri.exe"; $SignTool = Join-Path $Sdk "signtool.exe"
Write-Host "Windows SDK tools: $Sdk"

# ffmpeg
$ffmpegExe = $null; $ffprobeExe = $null; $ffmpegGpl = $false; $ffmpegLicense = $null; $ffmpegVersion = "not bundled"
if (-not $NoFfmpeg) {
    if (-not $FfmpegDir) {
        $cmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
        if (-not $cmd) { throw "ffmpeg not found on PATH. Pass -FfmpegDir <folder with ffmpeg.exe and ffprobe.exe> or -NoFfmpeg." }
        $item = Get-Item $cmd.Source
        $real = $item.FullName
        if ($item.LinkType) { $real = @($item.Target)[0] }       # winget installs symlinks in WinGet\Links
        $FfmpegDir = Split-Path -Parent $real
    }
    $ffmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"; $ffprobeExe = Join-Path $FfmpegDir "ffprobe.exe"
    foreach ($f in @($ffmpegExe, $ffprobeExe)) { if (-not (Test-Path $f)) { throw "Missing $f" } }
    $verText = (& $ffmpegExe -hide_banner -version | Out-String)
    $ffmpegVersion = ($verText -split "`n")[0].Trim()
    $ffmpegGpl = $verText -match "--enable-gpl"
    $ffmpegLicense = @(Get-ChildItem -Path @($FfmpegDir, (Split-Path -Parent $FfmpegDir)) -Filter "LICENSE*" -File -ErrorAction SilentlyContinue | Select-Object -First 1)
    Write-Host "ffmpeg: $ffmpegExe"
    Write-Host "        $ffmpegVersion"
    if ($ffmpegGpl) {
        Warn "This ffmpeg build is GPL (--enable-gpl). Distributing it obliges you to offer its complete source code."
        Warn "Before publishing, prefer an LGPL build (https://github.com/BtbN/FFmpeg-Builds/releases, *-lgpl-shared or *-lgpl) - see store\LICENSES\README.md."
    }
}

New-Item -ItemType Directory -Force $BuildRoot, $Store, (Join-Path $BuildRoot "logs") | Out-Null
$Logs = Join-Path $BuildRoot "logs"
$Dist = Join-Path $BuildRoot "dist"; $Work = Join-Path $BuildRoot "work"; $Layout = Join-Path $BuildRoot "layout"
$PriDir = Join-Path $BuildRoot "pri"; $OutDir = Join-Path $BuildRoot "out"

# a previous run may still be running / registered from the build folder - release it so folders can be rebuilt
Get-Process DrDoc -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($BuildRoot, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object { $_.InstallLocation -and $_.InstallLocation.StartsWith($BuildRoot, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Write-Host "Unregistering test package $($_.PackageFullName)"; Remove-AppxPackage $_.PackageFullName }

# ---------------------------------------------------------------- 1. assets + notices
Step "Generating icons and Store logos"
Run $Python @((Join-Path $Pack "make_assets.py"))
New-Item -ItemType Directory -Force (Join-Path $Store "listing") | Out-Null
Copy-Item (Join-Path $Pack "assets\store-logo-*.png") (Join-Path $Store "listing")
Step "Collecting third-party licence notices"
Run $Python @((Join-Path $Pack "collect_licenses.py"), (Join-Path $Store "LICENSES\THIRD-PARTY-NOTICES.txt"))
# Ship the licences inside the app too (Help -> About shows them): Dr. Doc is AGPL-3.0, open source.
$WebLic = Join-Path $Root "web\licenses"
New-Item -ItemType Directory -Force $WebLic | Out-Null
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $WebLic "LICENSE.txt") -Force
Copy-Item (Join-Path $Store "LICENSES\THIRD-PARTY-NOTICES.txt") (Join-Path $WebLic "THIRD-PARTY-NOTICES.txt") -Force

# ---------------------------------------------------------------- 2. PyInstaller
if (-not $SkipPyInstaller -or -not (Test-Path (Join-Path $Dist "DrDoc\DrDoc.exe"))) {
    Step "Freezing the app with PyInstaller (takes a few minutes)"
    # exe version resource
    $vparts = $Version.Split(".")
    $vfile = Join-Path $BuildRoot "version_info.txt"
    @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($($vparts -join ', ')), prodvers=($($vparts -join ', ')), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', '$($PublisherDisplayName -replace "'", "")'),
    StringStruct('FileDescription', 'Dr. Doc'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('InternalName', 'DrDoc'),
    StringStruct('OriginalFilename', 'DrDoc.exe'),
    StringStruct('ProductName', 'Dr. Doc'),
    StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding ASCII $vfile
    $env:DRDOC_VERSION_FILE = $vfile
    if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
    Run $Python @((Join-Path $Pack "run_pyinstaller.py"), (Join-Path $Pack "drdoc.spec"), "--noconfirm", "--log-level", "WARN",
                  "--distpath", $Dist, "--workpath", $Work) (Join-Path $Logs "pyinstaller.log")
    Remove-Item Env:\DRDOC_VERSION_FILE
} else { Step "Reusing previous PyInstaller output ($Dist)" }

# ---------------------------------------------------------------- 3. layout
Step "Staging package layout"
Reset-Dir $Layout
robocopy (Join-Path $Dist "DrDoc") $Layout /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0
# MSIX is an OPC zip: "[Content_Types].xml" and "_rels\*.rels" are reserved names anywhere in the package and make
# makeappx fail with 0x8007007b. python-docx ships an unused, unpacked copy of its template that contains them.
$tpl = Join-Path $Layout "_internal\docx\templates\default-docx-template"
if (Test-Path $tpl) { Remove-Item -Recurse -Force -LiteralPath $tpl }
Get-ChildItem $Layout -Recurse -File -Force | Where-Object {
    $_.Name -eq "[Content_Types].xml" -or ($_.Extension -eq ".rels" -and $_.Directory.Name -eq "_rels")
} | ForEach-Object {
    Write-Host "  removing OPC-reserved file: $($_.FullName.Substring($Layout.Length + 1))"
    Remove-Item -LiteralPath $_.FullName -Force
}
$bin = Join-Path $Layout "bin"
New-Item -ItemType Directory -Force $bin | Out-Null
if ($ffmpegExe) {
    Copy-Item $ffmpegExe, $ffprobeExe $bin
    if ($ffmpegLicense) { Copy-Item $ffmpegLicense[0].FullName (Join-Path $bin "FFMPEG-LICENSE.txt") }
    "Bundled: $ffmpegVersion`r`nFrom: $FfmpegDir`r`nGPL build: $ffmpegGpl`r`nSource code: https://ffmpeg.org/download.html (and the build's own source/README)" |
        Set-Content -Encoding ASCII (Join-Path $bin "FFMPEG-README.txt")
}
$licDst = Join-Path $Layout "LICENSES"
New-Item -ItemType Directory -Force $licDst | Out-Null
Copy-Item (Join-Path $Store "LICENSES\*") $licDst -Recurse -Force
$assets = Join-Path $Layout "Assets"
New-Item -ItemType Directory -Force $assets | Out-Null
Copy-Item (Join-Path $Pack "assets\msix\*.png") $assets

# manifest
$manifest = (Get-Content -Raw -Encoding UTF8 (Join-Path $Pack "AppxManifest.template.xml"))
$manifest = $manifest.Replace("{{IDENTITY_NAME}}", (Xml-Escape $IdentityName)).Replace("{{PUBLISHER}}", (Xml-Escape $Publisher)).
    Replace("{{PUBLISHER_DISPLAY_NAME}}", (Xml-Escape $PublisherDisplayName)).Replace("{{VERSION}}", $Version)
$manifestPath = Join-Path $Layout "AppxManifest.xml"
[IO.File]::WriteAllText($manifestPath, $manifest, (New-Object Text.UTF8Encoding $false))
$null = [xml][IO.File]::ReadAllText($manifestPath)   # throws if not well-formed XML

# resources.pri - index only the Assets folder (not the 400 MB of binaries)
Step "Building resources.pri"
Reset-Dir $PriDir
Copy-Item $assets (Join-Path $PriDir "Assets") -Recurse
Copy-Item $manifestPath $PriDir
Push-Location $PriDir
try {
    Run $MakePri @("createconfig", "/cf", "priconfig.xml", "/dq", "en-US", "/pv", "10.0.0", "/o") (Join-Path $Logs "makepri-config.log")
    # one resources.pri for the single package (no per-scale resource packs)
    $cfgPath = Join-Path $PriDir "priconfig.xml"
    $cfg = [xml][IO.File]::ReadAllText($cfgPath)
    foreach ($n in @($cfg.SelectNodes("//packaging"))) { [void]$n.ParentNode.RemoveChild($n) }
    $cfg.Save($cfgPath)
    Run $MakePri @("new", "/pr", $PriDir, "/cf", "priconfig.xml", "/mn", (Join-Path $PriDir "AppxManifest.xml"), "/of", (Join-Path $Layout "resources.pri"), "/o") (Join-Path $Logs "makepri.log")
} finally { Pop-Location }

# ---------------------------------------------------------------- 4. pack
Step "Packing MSIX"
Reset-Dir $OutDir
$name = "DrDoc_$($Version)_x64"
$msix = Join-Path $OutDir "$name.msix"
Run $MakeAppx @("pack", "/d", $Layout, "/p", $msix, "/o") (Join-Path $Logs "makeappx-pack.log")
Step "Validating: unpacking the MSIX again"
$unpack = Join-Path $BuildRoot "unpack-check"
if (Test-Path $unpack) { Remove-Item -Recurse -Force $unpack }
Run $MakeAppx @("unpack", "/p", $msix, "/d", $unpack, "/o") (Join-Path $Logs "makeappx-unpack.log")
if (-not (Test-Path (Join-Path $unpack "DrDoc.exe"))) { throw "Unpacked MSIX has no DrDoc.exe" }
Remove-Item -Recurse -Force $unpack

Get-ChildItem $Store -Filter "DrDoc_*_x64*.msix" -ErrorAction SilentlyContinue | Remove-Item -Force
Copy-Item $msix $Store
$results = @("Unsigned (upload to Partner Center): store\$name.msix")

# ---------------------------------------------------------------- 5. test signing
if ($SignForTesting) {
    Step "Signing a copy for sideload testing (self-signed, Publisher $Publisher)"
    $certDir = Join-Path $Store "test-cert"
    New-Item -ItemType Directory -Force $certDir | Out-Null
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $Publisher -and $_.FriendlyName -eq "Dr. Doc test signing" -and $_.NotAfter -gt (Get-Date).AddDays(7) } |
        Sort-Object NotAfter -Descending | Select-Object -First 1
    if (-not $cert) {
        $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature -FriendlyName "Dr. Doc test signing" `
            -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(2) `
            -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
        Write-Host "Created test certificate $($cert.Thumbprint)"
    } else { Write-Host "Reusing test certificate $($cert.Thumbprint)" }
    $safe = ($Publisher -replace '^CN=', '' -replace '[^A-Za-z0-9_-]', '_')
    $pfx = Join-Path $certDir "DrDocTest_$safe.pfx"; $cer = Join-Path $certDir "DrDocTest_$safe.cer"
    $pw = ConvertTo-SecureString -String $TestCertPassword -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pw | Out-Null
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
    $signed = Join-Path $OutDir "$($name)_TEST-SIGNED.msix"
    Copy-Item $msix $signed
    Run $SignTool @("sign", "/fd", "SHA256", "/f", $pfx, "/p", $TestCertPassword, $signed) (Join-Path $Logs "signtool.log")
    Copy-Item $signed $Store
    $results += "Test-signed (sideload only):       store\$($name)_TEST-SIGNED.msix"
    $results += "Test certificate:                  store\test-cert\$(Split-Path -Leaf $cer)  (pfx password: $TestCertPassword)"
}

# ---------------------------------------------------------------- 6. smoke test
$smoke = "skipped"
if (-not $SkipTests) {
    Step "Smoke test: frozen app starts, answers /api/caps, converts files"
    $ErrorActionPreference = "Continue"
    & $Python (Join-Path $Pack "smoke_test.py") --exe (Join-Path $Layout "DrDoc.exe")
    $ErrorActionPreference = "Stop"
    $smoke = if ($LASTEXITCODE -eq 0) { "PASSED" } else { "FAILED (exit $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

if ($Screenshots) {
    Step "Retaking Store screenshots"
    Run $Python @("-W", "ignore", (Join-Path $Pack "screenshots.py"), (Join-Path $Store "screenshots")) (Join-Path $Logs "screenshots.log")
}

# ---------------------------------------------------------------- summary
$hash = (Get-FileHash $msix -Algorithm SHA256).Hash
$sizeMb = [math]::Round((Get-Item $msix).Length / 1MB, 1)
$info = @"
Dr. Doc MSIX build
Built:                 $(Get-Date -Format "yyyy-MM-dd HH:mm")
Version:               $Version
Identity Name:         $IdentityName
Publisher:             $Publisher
PublisherDisplayName:  $PublisherDisplayName
Store identity:        $(if ($isStoreIdentity) { "yes" } else { "NO - fake dev identity, rebuild with your Partner Center values" })
MSIX:                  store\$name.msix  ($sizeMb MB, SHA256 $hash)
ffmpeg:                $ffmpegVersion
ffmpeg is GPL build:   $ffmpegGpl
Smoke test:            $smoke
Rebuild:               powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1 -Version $Version -IdentityName "$IdentityName" -Publisher "$Publisher" -PublisherDisplayName "$PublisherDisplayName"$(if ($FfmpegDir) { " -FfmpegDir `"$FfmpegDir`"" })$(if ($SignForTesting) { " -SignForTesting" })
"@
$info | Set-Content -Encoding UTF8 (Join-Path $Store "build-info.txt")
Step "Done"
$results | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
Write-Host "  Smoke test: $smoke"
Write-Host "  Details: store\build-info.txt"
if ($smoke -like "FAILED*") { exit 1 }
