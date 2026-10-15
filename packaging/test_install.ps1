<#
.SYNOPSIS
  Install the freshly built Dr. Doc package, launch it through its Start-menu identity (AUMID), smoke-test it, uninstall.

.DESCRIPTION
  Mode "auto" (default): tries the test-signed .msix from store\ first. That only works once the test certificate is
  trusted machine-wide (admin, one time - see store\README.md). Otherwise it falls back to registering the unpacked
  layout (%LOCALAPPDATA%\DrDocBuild\layout\AppxManifest.xml), which needs Windows "Developer Mode" but no admin.
  Run packaging\build_msix.ps1 -SignForTesting first.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\test_install.ps1            # install, test, uninstall
  powershell -ExecutionPolicy Bypass -File packaging\test_install.ps1 -Keep      # leave it installed to try by hand
#>
param(
    [ValidateSet("auto", "msix", "register")] [string]$Mode = "auto",
    [switch]$Keep,
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA "DrDocBuild")
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$manifestPath = Join-Path $BuildRoot "layout\AppxManifest.xml"
if (-not (Test-Path $manifestPath)) { throw "No build found - run packaging\build_msix.ps1 first" }
$name = ([xml](Get-Content -Raw $manifestPath)).Package.Identity.Name

Get-AppxPackage -Name $name | ForEach-Object { Write-Host "Removing previous install $($_.PackageFullName)"; Remove-AppxPackage $_.PackageFullName }

$installed = $false
if ($Mode -in @("auto", "msix")) {
    $msix = Get-ChildItem (Join-Path $Root "store") -Filter "DrDoc_*_x64_TEST-SIGNED.msix" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($msix) {
        try { Add-AppxPackage -Path $msix.FullName; $installed = $true; Write-Host "Installed $($msix.Name)" -ForegroundColor Green }
        catch { Write-Host "MSIX install failed: $(($_.Exception.Message -split "`n")[0])" -ForegroundColor Yellow
                if ($Mode -eq "msix") { throw } }
    } elseif ($Mode -eq "msix") { throw "No *_TEST-SIGNED.msix in store\ - build with -SignForTesting" }
}
if (-not $installed) {
    Write-Host "Registering the unpacked layout instead (Developer Mode)..."
    Add-AppxPackage -Register $manifestPath
    Write-Host "Registered (development mode)" -ForegroundColor Green
}
$pkg = Get-AppxPackage -Name $name
$aumid = "$($pkg.PackageFamilyName)!DrDoc"
Write-Host "AUMID: $aumid   (launch: explorer.exe shell:AppsFolder\$aumid)"

$ErrorActionPreference = "Continue"
& $Python (Join-Path $PSScriptRoot "smoke_test.py") --aumid $aumid
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if (-not $Keep) {
    Get-Process DrDoc -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$($pkg.InstallLocation)*" } | Stop-Process -Force
    Start-Sleep 1
    Remove-AppxPackage $pkg.PackageFullName
    Write-Host "Uninstalled."
}
Write-Host $(if ($code -eq 0) { "INSTALL TEST PASSED" } else { "INSTALL TEST FAILED" })
exit $code
