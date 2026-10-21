# Removes the Compliance Checker plug-in for AutoCAD 2026 (the pairing token, shared with Revit,
# stays in %AppData%\ComplianceChecker). Close AutoCAD first.
$ErrorActionPreference = "Stop"
$bundle = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins\ComplianceChecker.bundle"
if (Test-Path $bundle) {
    Remove-Item -Recurse -Force $bundle
    Write-Host "Removed $bundle"
} else {
    Write-Host "Not installed."
}
