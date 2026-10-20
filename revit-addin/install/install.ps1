# Installs the Compliance Checker add-in for Revit 2026 for the current user.
#
#   From the release zip:   right-click install.ps1 > Run with PowerShell
#                           (or: powershell -ExecutionPolicy Bypass -File install.ps1)
#   From the repo:          just install-addin
#
# Copies the add-in to %AppData%\Autodesk\Revit\Addins\2026\ComplianceChecker\ and the manifest
# ComplianceChecker.addin next to that folder. Close Revit first.
param([string]$Source = "")
$ErrorActionPreference = "Stop"

if (-not $Source) {
    $zipLayout = Join-Path $PSScriptRoot "ComplianceChecker"
    $repoLayout = Join-Path $PSScriptRoot "..\src\ComplianceChecker\bin\Release\net8.0-windows"
    $Source = if (Test-Path (Join-Path $zipLayout "ComplianceChecker.dll")) { $zipLayout } else { $repoLayout }
}
if (-not (Test-Path (Join-Path $Source "ComplianceChecker.dll"))) {
    throw "ComplianceChecker.dll not found in '$Source'. Build first: just build-addin"
}
$manifest = @((Join-Path $Source "ComplianceChecker.addin"), (Join-Path $PSScriptRoot "ComplianceChecker.addin")) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $manifest) { throw "ComplianceChecker.addin not found." }

if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
    Write-Warning "Revit is running. Close it first, or the DLLs may be locked and the new version won't load."
}

$addins = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2026"
$target = Join-Path $addins "ComplianceChecker"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $target -Recurse -Force -Exclude "ComplianceChecker.addin", "*.pdb"
Copy-Item -Path $manifest -Destination $addins -Force

Write-Host "Installed to $target"
Write-Host "Start Revit 2026: a 'Compliance' tab should appear on the ribbon."
