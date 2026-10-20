# Builds the release zip: dist/ComplianceChecker-<version>.zip containing
#   ComplianceChecker\ (DLLs), ComplianceChecker.addin, install.ps1, uninstall.ps1, README.txt
param([string]$Version = "0.1.0")
$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$build = Join-Path $repo "revit-addin\src\ComplianceChecker\bin\Release\net8.0-windows"
$dist = Join-Path $repo "dist"
$stage = Join-Path $dist "ComplianceChecker-$Version"
$zip = "$stage.zip"

if (-not (Test-Path (Join-Path $build "ComplianceChecker.dll"))) { throw "Build first: just build-addin" }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stage, $zip
New-Item -ItemType Directory -Force -Path (Join-Path $stage "ComplianceChecker") | Out-Null

Copy-Item -Path (Join-Path $build "*") -Destination (Join-Path $stage "ComplianceChecker") -Recurse -Exclude "ComplianceChecker.addin", "*.pdb"
Copy-Item (Join-Path $build "ComplianceChecker.addin") $stage
Copy-Item (Join-Path $PSScriptRoot "install.ps1"), (Join-Path $PSScriptRoot "uninstall.ps1") $stage
@"
Compliance Checker for Revit 2026 (v$Version)

1. Close Revit.
2. Right-click install.ps1 > Run with PowerShell.
3. Start Revit 2026: use the 'Compliance' tab.
   Pair > Site Setup > Run Check. Export JSON saves the exported model.

Licensed under Apache-2.0.
"@ | Set-Content -Encoding utf8 (Join-Path $stage "README.txt")

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
Remove-Item -Recurse -Force $stage
Write-Host "Wrote $zip"

# The web app offers the zip on its "Pair Revit" page.
$web = Join-Path $PSScriptRoot "..\..\web\public\downloads"
New-Item -ItemType Directory -Force -Path $web | Out-Null
Copy-Item $zip (Join-Path $web "ComplianceChecker-revit2026.zip") -Force
