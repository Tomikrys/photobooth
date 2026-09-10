# ==========================================
# PHOTOBOOTH BUILD SCRIPT
# ==========================================
# Compiles src\Photobooth.ps1 -> <root>\Photobooth.exe (the ONLY exe the
# operator needs). NikonMove.ps1 stays as a script that Photobooth.exe
# spawns via powershell.exe; there's no point compiling it separately.
#
# Auto-installs the PS2EXE PowerShell module the first time it runs.
#
# Usage:
#   - Double-click Build.bat at the project root, or
#   - Right-click src\Build.ps1 -> Run with PowerShell
# ==========================================

$ErrorActionPreference = "Stop"

$srcDir  = $PSScriptRoot
$rootDir = Split-Path -Parent $srcDir
Set-Location -LiteralPath $rootDir

function Write-Section { param([string]$Msg) Write-Host "`n=== $Msg ===" -ForegroundColor Cyan }

# ------------------------------------------
# 1. Ensure PS2EXE is available
# ------------------------------------------
Write-Section "Checking PS2EXE"
if (-not (Get-Command Invoke-PS2EXE -ErrorAction SilentlyContinue)) {
    Write-Host "PS2EXE not found — installing from PSGallery (current user only)..." -ForegroundColor Yellow

    try {
        if ((Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue).InstallationPolicy -ne "Trusted") {
            Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction Stop
        }
    } catch {
        Write-Host "Note: Could not mark PSGallery as trusted — you may be prompted to confirm." -ForegroundColor DarkYellow
    }

    try {
        if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
            Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Scope CurrentUser -Force | Out-Null
        }
    } catch {
        Write-Host "Warning: Could not install NuGet provider automatically: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }

    Install-Module -Name ps2exe -Scope CurrentUser -Force -AllowClobber
    Import-Module ps2exe -Force
    Write-Host "PS2EXE installed." -ForegroundColor Green
} else {
    Write-Host "PS2EXE already available." -ForegroundColor Green
}

# ------------------------------------------
# 2. Compile launcher -> root\Photobooth.exe
# ------------------------------------------
$inputScript = Join-Path $srcDir  "Photobooth.ps1"
$outputExe   = Join-Path $rootDir "Photobooth.exe"

Write-Section "Compiling $inputScript"
if (-not (Test-Path -LiteralPath $inputScript)) {
    Write-Host "Source not found: $inputScript" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Invoke-PS2EXE -inputFile $inputScript -outputFile $outputExe -title "Photobooth" -noConsole:$false

if (Test-Path -LiteralPath $outputExe) {
    Write-Host "Built $outputExe" -ForegroundColor Green
} else {
    Write-Host "Build produced no output." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Section "Done"
Write-Host "Run Photobooth.exe (at the project root) to start everything." -ForegroundColor Green
Read-Host "Press Enter to close"
