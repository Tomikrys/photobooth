# ==========================================
# PHOTOBOOTH LAUNCHER
# ==========================================
# 1. Copies .env.example -> .env if missing
# 2. Creates Python venv + installs requirements if missing
# 3. Creates photos/ subfolders
# 4. Starts NikonMove.ps1 + app.py
# 5. Opens browser (/ on subsequent runs, /config on first run)
# 6. Streams logs, cleans up on Ctrl+C
# ==========================================

$ErrorActionPreference = "Stop"

# ------------------------------------------
# LOCATE ROOT + SRC
# ------------------------------------------
$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}

if (Test-Path -LiteralPath (Join-Path $scriptDir "src\app.py")) {
    $rootDir = $scriptDir
    $srcDir  = Join-Path $rootDir "src"
} else {
    $srcDir  = $scriptDir
    $rootDir = Split-Path -Parent $srcDir
}

Set-Location -LiteralPath $rootDir

$AppPort = 5001

function Write-Log {
    param([string]$Message, [string]$Color = "Gray", [string]$Tag = "LAUNCHER")
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts][$Tag] $Message" -ForegroundColor $Color
}

function Test-CommandExists {
    param([string]$Name)
    try { Get-Command $Name -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}

Write-Log "Photobooth launcher starting" "Cyan"
Write-Log "Root: $rootDir" "Gray"
Write-Log "Src : $srcDir" "Gray"

# ------------------------------------------
# 1. .env BOOTSTRAP
# ------------------------------------------
$envAtRoot  = Join-Path $rootDir ".env"
$envExample = Join-Path $srcDir  ".env.example"
$firstRun   = $false

if (-not (Test-Path -LiteralPath $envAtRoot)) {
    if (Test-Path -LiteralPath $envExample) {
        Copy-Item -LiteralPath $envExample -Destination $envAtRoot
        Write-Log ".env created from src\.env.example. Open http://localhost:$AppPort/config to finish setup." "Yellow"
        $firstRun = $true
    } else {
        Write-Log ".env AND src\.env.example are both missing. Cannot continue." "Red"
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ------------------------------------------
# 2. PYTHON + VENV
# ------------------------------------------
if (-not (Test-CommandExists "python")) {
    Write-Log "Python is not on PATH. Install Python 3.12 from https://python.org and re-run." "Red"
    Read-Host "Press Enter to exit"
    exit 1
}

$venvDir      = Join-Path $srcDir "venv"
$pythonExe    = Join-Path $venvDir "Scripts\python.exe"
$pipExe       = Join-Path $venvDir "Scripts\pip.exe"
$requirements = Join-Path $srcDir "requirements.txt"

if (-not (Test-Path -LiteralPath $venvDir)) {
    Write-Log "Creating Python virtual environment (first-run setup)..." "Cyan"
    try {
        python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "python -m venv exited with code $LASTEXITCODE" }
    } catch {
        Write-Log "Failed to create venv: $($_.Exception.Message)" "Red"
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Log "Upgrading pip..." "Cyan"
    & $pythonExe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Log "pip upgrade failed." "Red"
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Log "Installing requirements..." "Cyan"
    & $pipExe install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Requirements install failed." "Red"
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Log "Setup complete." "Green"
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Log "venv exists but $pythonExe is missing. Delete src\venv and re-run." "Red"
    Read-Host "Press Enter to exit"
    exit 1
}

# ------------------------------------------
# 3. PHOTO FOLDERS
# ------------------------------------------
$photoDirs = @(
    "photos\camera",
    "photos\raw",
    "photos\processed",
    "photos\processed\thumbs",
    "photos\printed",
    "photos\hidden"
)
foreach ($d in $photoDirs) {
    $full = Join-Path $rootDir $d
    if (-not (Test-Path -LiteralPath $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
    }
}

# ------------------------------------------
# 4. START CHILD PROCESSES
# ------------------------------------------
$nikonScript = Join-Path $srcDir "NikonMove.ps1"
$appScript   = Join-Path $srcDir "app.py"

if (-not (Test-Path -LiteralPath $appScript)) {
    Write-Log "app.py not found at $appScript - cannot start Flask server." "Red"
    Read-Host "Press Enter to exit"
    exit 1
}

$children = @()

function Start-Child {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [hashtable]$ExtraEnv = @{}
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $FilePath
    $psi.WorkingDirectory       = $WorkingDirectory
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true

    foreach ($kv in $ExtraEnv.GetEnumerator()) {
        $psi.EnvironmentVariables[$kv.Key] = $kv.Value
    }

    if ($ArgumentList.Count -gt 0) {
        $quoted = foreach ($a in $ArgumentList) {
            if ($a -match '\s|"') { '"' + ($a -replace '"', '\"') + '"' } else { $a }
        }
        $psi.Arguments = ($quoted -join ' ')
    }

    $proc = [System.Diagnostics.Process]::Start($psi)

    $stdoutAction = {
        if ($EventArgs.Data) {
            $ts = Get-Date -Format "HH:mm:ss"
            Write-Host "[$ts][$($Event.MessageData)] $($EventArgs.Data)"
        }
    }
    $stderrAction = {
        if ($EventArgs.Data) {
            $ts = Get-Date -Format "HH:mm:ss"
            Write-Host "[$ts][$($Event.MessageData)] $($EventArgs.Data)" -ForegroundColor Red
        }
    }
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action $stdoutAction -MessageData $Name | Out-Null
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived  -Action $stderrAction -MessageData $Name | Out-Null
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    return $proc
}

if (Test-Path -LiteralPath $nikonScript) {
    Write-Log "Starting Nikon MTP importer..." "Cyan"
    try {
        $nikonProc = Start-Child -Name "NIKON" `
            -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $nikonScript) `
            -WorkingDirectory $rootDir
        $children += @{ Name = "NIKON"; Process = $nikonProc }
    } catch {
        Write-Log "Failed to start NikonMove.ps1: $($_.Exception.Message)" "Red"
    }
} else {
    Write-Log "src\NikonMove.ps1 not found - skipping camera importer." "Yellow"
}

Write-Log "Starting Flask app..." "Cyan"
try {
    $appProc = Start-Child -Name "APP" `
        -FilePath $pythonExe `
        -ArgumentList @($appScript) `
        -WorkingDirectory $rootDir `
        -ExtraEnv @{ "NIKON_MANAGED" = "1" }
    $children += @{ Name = "APP"; Process = $appProc }
} catch {
    Write-Log "Failed to start app.py: $($_.Exception.Message)" "Red"
    Read-Host "Press Enter to exit"
    exit 1
}

# ------------------------------------------
# 5. WAIT FOR SERVER, OPEN BROWSER, WATCH
# ------------------------------------------
$openedBrowser   = $false
$serverStartedAt = Get-Date
$openUrl         = if ($firstRun) { "http://localhost:$AppPort/config" } else { "http://localhost:$AppPort" }

Write-Log "All services launched. Press Ctrl+C to stop." "Green"
if ($firstRun) {
    Write-Log "First run — browser will open at /config so you can set up printer, camera, and email." "Yellow"
}

try {
    while ($true) {
        if (-not $openedBrowser) {
            $listening = $false
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $iar = $tcp.BeginConnect("127.0.0.1", $AppPort, $null, $null)
                if ($iar.AsyncWaitHandle.WaitOne(200)) {
                    try { $tcp.EndConnect($iar); $listening = $true } catch {}
                }
                $tcp.Close()
            } catch {}
            if ($listening) {
                Write-Log "Server is up - opening $openUrl" "Green"
                Start-Process $openUrl | Out-Null
                $openedBrowser = $true
            } elseif (((Get-Date) - $serverStartedAt).TotalSeconds -gt 30) {
                Write-Log "Server did not start within 30s. Check the [APP] logs above." "Yellow"
                $openedBrowser = $true
            }
        }

        $stillRunning = @()
        foreach ($c in $children) {
            if ($c.Process.HasExited) {
                Write-Log "$($c.Name) exited (code $($c.Process.ExitCode))." "Red"
                if ($c.Name -eq "APP") {
                    Write-Log "Flask app died - shutting everything down." "Red"
                    throw "Flask app exited unexpectedly."
                }
            } else {
                $stillRunning += $c
            }
        }
        $children = $stillRunning

        Start-Sleep -Milliseconds 500
    }
} catch {
    if ($_.Exception.Message -and $_.Exception.Message -notmatch "pipeline has been stopped") {
        Write-Log "Stopping: $($_.Exception.Message)" "Yellow"
    } else {
        Write-Log "Stopping (Ctrl+C)..." "Yellow"
    }
} finally {
    foreach ($c in $children) {
        try {
            if (-not $c.Process.HasExited) {
                Write-Log "Stopping $($c.Name) (PID $($c.Process.Id))..." "Yellow"
                try { $c.Process.CloseMainWindow() | Out-Null } catch {}
                if (-not $c.Process.WaitForExit(3000)) {
                    try { $c.Process.Kill($true) } catch { try { $c.Process.Kill() } catch {} }
                }
            }
        } catch {
            Write-Log "Error stopping $($c.Name): $($_.Exception.Message)" "Red"
        }
    }

    Get-EventSubscriber -ErrorAction SilentlyContinue | Unregister-Event -ErrorAction SilentlyContinue

    Write-Log "Photobooth stopped. Bye." "Cyan"
    Start-Sleep -Seconds 1
}
