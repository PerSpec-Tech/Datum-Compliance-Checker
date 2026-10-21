# Installs the Compliance Checker plug-in for AutoCAD 2026 for the current user.
#
#   From the release zip:   right-click install.ps1 > Run with PowerShell
#                           (or: powershell -ExecutionPolicy Bypass -File install.ps1)
#   From the repo:          just install-autocad
#
# Copies the plug-in as %AppData%\Autodesk\ApplicationPlugins\ComplianceChecker.bundle, which AutoCAD
# loads at start-up. Close AutoCAD first.
param([string]$Source = "")
$ErrorActionPreference = "Stop"

if (-not $Source) {
    $zipLayout = Join-Path $PSScriptRoot "Contents"
    $repoLayout = Join-Path $PSScriptRoot "..\src\ComplianceChecker.AutoCAD\bin\Release\net8.0-windows"
    $Source = if (Test-Path (Join-Path $zipLayout "ComplianceChecker.AutoCAD.dll")) { $zipLayout } else { $repoLayout }
}
if (-not (Test-Path (Join-Path $Source "ComplianceChecker.AutoCAD.dll"))) {
    throw "ComplianceChecker.AutoCAD.dll not found in '$Source'. Build first: just build-autocad"
}
if (Get-Process -Name acad -ErrorAction SilentlyContinue) {
    Write-Warning "AutoCAD is running. Close it first, or the DLLs may be locked and the new version won't load."
}

$bundle = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins\ComplianceChecker.bundle"
$contents = Join-Path $bundle "Contents"
New-Item -ItemType Directory -Force -Path $contents | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $contents -Recurse -Force -Exclude "*.pdb"
Copy-Item -Path (Join-Path $PSScriptRoot "PackageContents.xml") -Destination $bundle -Force

Write-Host "Installed to $bundle"
Write-Host "Start AutoCAD 2026: a 'Compliance' tab should appear on the ribbon."
