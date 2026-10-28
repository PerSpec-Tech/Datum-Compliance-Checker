# Builds the release zip: dist/ComplianceChecker-autocad-<version>.zip containing
#   Contents\ (DLLs), PackageContents.xml, install.ps1, uninstall.ps1, README.txt
# and copies it to web/public/downloads for the web app's pairing page.
param([string]$Version = "0.1.0")
$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$build = Join-Path $repo "autocad-addin\src\ComplianceChecker.AutoCAD\bin\Release\net8.0-windows"
$dist = Join-Path $repo "dist"
$stage = Join-Path $dist "ComplianceChecker-autocad-$Version"
$zip = "$stage.zip"

if (-not (Test-Path (Join-Path $build "ComplianceChecker.AutoCAD.dll"))) { throw "Build first: just build-autocad" }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stage, $zip
New-Item -ItemType Directory -Force -Path (Join-Path $stage "Contents") | Out-Null

Copy-Item -Path (Join-Path $build "*") -Destination (Join-Path $stage "Contents") -Recurse -Exclude "*.pdb"
Copy-Item (Join-Path $PSScriptRoot "PackageContents.xml"), (Join-Path $PSScriptRoot "install.ps1"), (Join-Path $PSScriptRoot "uninstall.ps1") $stage
@"
Compliance Checker for AutoCAD 2026 (v$Version)

1. Close AutoCAD.
2. Right-click install.ps1 > Run with PowerShell.
3. Start AutoCAD 2026: use the 'Datum' tab.
   1 Pair > 2 Layers > 3 Site > 4 Run Check. Results open in the Compliance palette.

Licensed under Apache-2.0.
"@ | Set-Content -Encoding utf8 (Join-Path $stage "README.txt")

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
Remove-Item -Recurse -Force $stage
Write-Host "Wrote $zip"

$web = Join-Path $PSScriptRoot "..\..\web\public\downloads"
New-Item -ItemType Directory -Force -Path $web | Out-Null
Copy-Item $zip (Join-Path $web "ComplianceChecker-autocad2026.zip") -Force
