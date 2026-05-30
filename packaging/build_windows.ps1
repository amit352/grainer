# Grain Scanner - Windows build script
# Run from the repo root on your Windows VM (Parallels Desktop):
#   .\packaging\build_windows.ps1
#   .\packaging\build_windows.ps1 -Version 1.2.0

param(
    [string]$Version = "1.0.0",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Grain Scanner Windows Build  v$Version"           -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# If running from a UNC path (\\Mac\...), copy source to a local temp dir first.
# pip and PyInstaller fail silently when run from network shares.
$OriginalRoot = Split-Path -Parent $PSScriptRoot
$LocalRoot    = $OriginalRoot

if ($OriginalRoot -like "\\*") {
    $LocalRoot = "C:\grainer_build"
    Write-Host "`nNetwork share detected - copying source to $LocalRoot ..." -ForegroundColor Yellow
    if (Test-Path $LocalRoot) { Remove-Item $LocalRoot -Recurse -Force }
    Copy-Item $OriginalRoot $LocalRoot -Recurse
    Write-Host "  Done. Building from local copy."
}

$PackageDir = Join-Path $LocalRoot "packaging"

# 0. Require x64 Python 3.12.
#    opencv has no ARM64 Windows wheels, so we need x64 Python even on ARM Windows.
#    x64 Python runs fine under Windows' built-in x64 emulation on ARM.
Write-Host "`n[0/3] Checking x64 Python 3.12..." -ForegroundColor Yellow
$pyexe = $null
# "py -3.12-64" asks the py launcher specifically for the 64-bit x64 build
foreach ($candidate in @("py -3.12-64", "py -3.12", "python")) {
    try {
        $parts = $candidate.Split()
        $ver  = & $parts[0] ($parts[1..99] + @("--version")) 2>&1
        $arch = & $parts[0] ($parts[1..99] + @("-c", "import platform; print(platform.machine())")) 2>&1
        if ($ver -match "3\.12" -and $arch -match "AMD64") { $pyexe = $candidate; break }
    } catch {}
}
if (-not $pyexe) {
    Write-Error @"
x64 Python 3.12 not found.

You are on Windows ARM (Parallels on Apple Silicon). Install the x64 build:
    winget install Python.Python.3.12 --architecture x64

Then close and reopen PowerShell and re-run this script.
"@
}
Write-Host "      Using: $pyexe"

function Invoke-Py {
    $parts = $pyexe.Split()
    & $parts[0] ($parts[1..99] + $args)
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $pyexe $args" }
}

# 1. Install dependencies
Write-Host "`n[1/3] Installing dependencies..." -ForegroundColor Yellow
Invoke-Py -m pip install --quiet --upgrade pip
Invoke-Py -m pip install --quiet pyinstaller
Invoke-Py -m pip install --quiet --prefer-binary -r "$PackageDir\requirements-windows.txt"
Write-Host "      Done."

# 2. PyInstaller bundle
Write-Host "`n[2/3] Building bundle with PyInstaller..." -ForegroundColor Yellow
Set-Location $PackageDir
Invoke-Py -m PyInstaller grain_scanner.spec --noconfirm
Set-Location $LocalRoot
Write-Host "      Bundle: $PackageDir\dist\GrainScanner\"

# 3. Inno Setup installer
if (-not $SkipInstaller) {
    Write-Host "`n[3/3] Building installer with Inno Setup..." -ForegroundColor Yellow
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($iscc) {
        Set-Location $PackageDir
        & $iscc /DMyAppVersion="$Version" installer.iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
        Set-Location $LocalRoot

        # Copy installer back to original location if we built locally
        if ($LocalRoot -ne $OriginalRoot) {
            $outDir = Join-Path $OriginalRoot "packaging\Output"
            New-Item -ItemType Directory -Force $outDir | Out-Null
            Copy-Item "$PackageDir\Output\*.exe" $outDir -Force
            Write-Host "  Installer copied to: $outDir" -ForegroundColor Green
        } else {
            Write-Host "  Installer: $PackageDir\Output\GrainScanner-Setup-$Version.exe" -ForegroundColor Green
        }
    } else {
        Write-Host "  Inno Setup 6 not found - skipping." -ForegroundColor Yellow
        Write-Host "  Download: https://jrsoftware.org/isdl.php"
        Write-Host "  Bundle: $PackageDir\dist\GrainScanner\" -ForegroundColor Green
    }
} else {
    Write-Host "`n[3/3] Skipped (-SkipInstaller)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Cyan
