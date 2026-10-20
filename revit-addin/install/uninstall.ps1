# Removes the Compliance Checker add-in for Revit 2026 for the current user.
$ErrorActionPreference = "Stop"
$addins = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2026"
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $addins "ComplianceChecker.addin")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $addins "ComplianceChecker")
Write-Host "Compliance Checker removed. Saved pairing token (if any) is in $env:APPDATA\ComplianceChecker."
