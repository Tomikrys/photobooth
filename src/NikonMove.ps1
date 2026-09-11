# ==========================================
# NIKON D3100 -> LOCAL FOLDER PHOTO IMPORTER
# ==========================================
# Continuously monitors the camera over MTP, moves new photos off the SD card
# to a local folder, and renames every file to a processing-time timestamp
# (yyyyMMdd_HHmmss_fff) so nothing can ever overwrite an existing photo.
# ==========================================

$ErrorActionPreference = "Stop"

# ------------------------------------------
# ENV FILE PARSING
# ------------------------------------------
$envPath = ".\.env"
$DestinationFolder = "C:\Photos\NikonD3100" # Fallback if .env is missing/invalid

function Write-Log {
    param(
        [string]$Message,
        [string]$Color = "Gray"
    )
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

if (Test-Path -LiteralPath $envPath) {
    try {
        Get-Content -LiteralPath $envPath | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith("#")) { return }
            if ($line -notmatch '=') { return }

            $parts = $line -split '=', 2
            $key = $parts[0].Trim()
            $value = if ($parts.Count -ge 2) { $parts[1].Trim() } else { "" }

            if ($key -eq "CAMERA_DIR" -and $value) {
                $rawPath = $value.Trim('"').Trim("'")
                try {
                    $DestinationFolder = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($rawPath)
                } catch {
                    Write-Log "Warning: Could not resolve CAMERA_DIR '$rawPath'. Using fallback." "Yellow"
                }
            }
            if ($key -eq "CAMERA_NAME" -and $value) {
                $CameraName = $value.Trim('"').Trim("'")
            }
            if ($key -eq "CAMERA_FOLDER_PATTERN" -and $value) {
                $FolderPattern = $value.Trim('"').Trim("'")
            }
        }
    } catch {
        Write-Log "Warning: Failed to read .env ($($_.Exception.Message)). Using fallback path." "Yellow"
    }
} else {
    Write-Log "Warning: .env file not found. Using default path: $DestinationFolder" "Yellow"
}

$CameraName    = "D3100"
$FolderPattern = "100D3100"

# ------------------------------------------
# DIRECTORY SETUP
# ------------------------------------------
Write-Log "Initializing connection to camera ($CameraName)..." "Cyan"
Write-Log "Destination: $DestinationFolder" "Cyan"

if (-not (Test-Path -LiteralPath $DestinationFolder)) {
    New-Item -ItemType Directory -Path $DestinationFolder -Force | Out-Null
    Write-Log "Created directory: $DestinationFolder" "Green"
}

$tempRoot = Join-Path -Path $DestinationFolder -ChildPath ".mtp_temp"
if (-not (Test-Path -LiteralPath $tempRoot)) {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
}

# ------------------------------------------
# HELPERS
# ------------------------------------------

# Generates a unique target filename inside $DestinationFolder based on the
# current time, guaranteed not to collide with any existing file.
function Get-UniqueTargetPath {
    param(
        [Parameter(Mandatory)][string]$Extension,
        [Parameter(Mandatory)][string]$DestFolder
    )
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
    $name = "${timestamp}${Extension}"
    $path = Join-Path -Path $DestFolder -ChildPath $name
    $counter = 1
    while (Test-Path -LiteralPath $path) {
        $name = "${timestamp}_${counter}${Extension}"
        $path = Join-Path -Path $DestFolder -ChildPath $name
        $counter++
    }
    return [pscustomobject]@{ Name = $name; Path = $path }
}

# Waits until a file's size is stable across two checks (i.e. the OS finished
# writing it). Returns $true on success, $false on timeout.
function Wait-ForStableFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [int]$TimeoutMs = 15000,
        [int]$PollMs = 100
    )
    $elapsed = 0
    $lastSize = -1
    while ($elapsed -lt $TimeoutMs) {
        if (Test-Path -LiteralPath $Path) {
            try {
                $size = (Get-Item -LiteralPath $Path -ErrorAction Stop).Length
                if ($size -gt 0 -and $size -eq $lastSize) { return $true }
                $lastSize = $size
            } catch {
                # File may be locked mid-write; keep polling
            }
        }
        Start-Sleep -Milliseconds $PollMs
        $elapsed += $PollMs
    }
    return $false
}

# Sweeps any leftover files from previous crashed runs out of .mtp_temp
# (including per-transfer subfolders) into the destination with fresh names.
function Invoke-OrphanSweep {
    param(
        [Parameter(Mandatory)][string]$TempRoot,
        [Parameter(Mandatory)][string]$DestFolder
    )
    if (-not (Test-Path -LiteralPath $TempRoot)) { return }

    $orphans = Get-ChildItem -LiteralPath $TempRoot -File -Recurse -ErrorAction SilentlyContinue
    if (-not $orphans -or $orphans.Count -eq 0) {
        # Still clean up any empty subfolders left behind
        Get-ChildItem -LiteralPath $TempRoot -Directory -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        return
    }

    Write-Log "Recovering $($orphans.Count) orphaned file(s) from previous run..." "Yellow"
    foreach ($orphan in $orphans) {
        try {
            $target = Get-UniqueTargetPath -Extension $orphan.Extension -DestFolder $DestFolder
            Move-Item -LiteralPath $orphan.FullName -Destination $target.Path -Force -ErrorAction Stop
            Write-Log "  Recovered: $($orphan.Name) -> $($target.Name)" "Green"
        } catch {
            Write-Log "  Failed to recover $($orphan.Name): $($_.Exception.Message)" "Red"
        }
    }

    # Remove any now-empty per-transfer subfolders
    Get-ChildItem -LiteralPath $TempRoot -Directory -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# ------------------------------------------
# STARTUP RECOVERY
# ------------------------------------------
Invoke-OrphanSweep -TempRoot $tempRoot -DestFolder $DestinationFolder

$shell = New-Object -ComObject Shell.Application

Write-Log "[Listening] Monitoring camera folder for new photos... Press Ctrl+C to stop." "Green"

# ------------------------------------------
# CONTINUOUS MONITORING LOOP
# ------------------------------------------
$cameraWasConnected = $null   # tri-state: $null (unknown), $true, $false
$lastErrorMessage   = $null
$lastErrorAt        = [datetime]::MinValue
$sourceFolder       = $null   # cached MTP folder reference — re-resolved on connect/error
$dcimFolder         = $null   # cached DCIM reference — sourceFolder re-fetched each loop from this

try {
    while ($true) {
        try {
            # Re-resolve the full MTP tree only when we don't have a cached DCIM reference.
            # $sourceFolder is re-fetched every loop from $dcimFolder so the D3100's MTP
            # layer returns a fresh listing rather than a stale cached snapshot.
            if (-not $dcimFolder) {
                $myComputer = $shell.Namespace(0x11)
                if (-not $myComputer) {
                    throw "Could not access 'This PC' shell namespace (0x11)."
                }

                $camera = $myComputer.Items() | Where-Object { $_.Name -like "*$CameraName*" } | Select-Object -First 1

                if (-not $camera) {
                    if ($cameraWasConnected -ne $false) {
                        Write-Log "Camera '$CameraName' not detected. Waiting..." "DarkYellow"
                        $cameraWasConnected = $false
                    }
                    Start-Sleep -Seconds 2
                    continue
                }

                $storage = $camera.GetFolder.Items() | Where-Object { $_.Name -like "*Removable storage*" } | Select-Object -First 1
                if (-not $storage) { Start-Sleep -Milliseconds 500; continue }

                $dcimFolder = $storage.GetFolder.Items() | Where-Object { $_.Name -eq "DCIM" } | Select-Object -First 1
                if (-not $dcimFolder) { Start-Sleep -Milliseconds 500; continue }

                if ($cameraWasConnected -ne $true) {
                    Write-Log "Camera '$CameraName' connected." "Green"
                    $cameraWasConnected = $true
                }
            }

            # Re-resolve sourceFolder every loop — the D3100 MTP layer returns stale
            # results from a cached COM object, so we must re-enumerate from DCIM each time.
            $sourceFolder = $dcimFolder.GetFolder.Items() | Where-Object { $_.Name -eq $FolderPattern } | Select-Object -First 1
            if (-not $sourceFolder) { Start-Sleep -Milliseconds 500; continue }

            $cameraFiles = @($sourceFolder.GetFolder.Items())
            if ($cameraFiles.Count -eq 0) { Start-Sleep -Milliseconds 300; continue }

            foreach ($file in $cameraFiles) {
                $originalName = $file.Name
                Write-Log "New photo detected: $originalName" "Yellow"

                $ext = [System.IO.Path]::GetExtension($originalName)

                # Create a private, per-transfer temp subfolder so the MTP move
                # cannot collide with anything from a previous or concurrent transfer.
                $transferId  = [guid]::NewGuid().ToString("N")
                $transferDir = Join-Path -Path $tempRoot -ChildPath $transferId
                New-Item -ItemType Directory -Path $transferDir -Force | Out-Null
                $transferShellFolder = $shell.Namespace($transferDir)

                if (-not $transferShellFolder) {
                    Write-Log "  -> Error: Could not open transfer folder $transferDir" "Red"
                    Remove-Item -LiteralPath $transferDir -Recurse -Force -ErrorAction SilentlyContinue
                    continue
                }

                # MTP move to per-transfer folder. Flag 20 = 16 (Yes to All) + 4 (no progress dialog).
                # "Resource in use" is transient (camera still flushing to SD); retry with backoff.
                $moveOk = $false
                for ($mtpAttempt = 0; $mtpAttempt -lt 10 -and -not $moveOk; $mtpAttempt++) {
                    try {
                        $transferShellFolder.MoveHere($file, 20)
                        $moveOk = $true
                    } catch {
                        $errMsg = $_.Exception.Message
                        # "Element not found" means the file vanished from the camera between
                        # listing and moving (already transferred, or camera ejected mid-loop).
                        # Treat it as a clean skip rather than a retry-worthy error.
                        if ($errMsg -like "*Element not found*") {
                            Write-Log "  -> $originalName no longer on camera (already moved?), skipping." "DarkYellow"
                            $moveOk = $true  # don't retry, don't log as failure
                            break
                        }
                        if ($mtpAttempt -lt 9) {
                            Write-Log "  -> MTP MoveHere attempt $($mtpAttempt+1) failed ('$errMsg'), retrying in 2s..." "DarkYellow"
                            Start-Sleep -Seconds 2
                        } else {
                            Write-Log "  -> MTP MoveHere failed after 10 attempts: $errMsg" "Red"
                        }
                    }
                }
                if (-not $moveOk) {
                    Remove-Item -LiteralPath $transferDir -Recurse -Force -ErrorAction SilentlyContinue
                    continue
                }

                $tempFilePath = Join-Path -Path $transferDir -ChildPath $originalName

                # If the file never landed (e.g. "Element not found" skip above), clean up and move on.
                if (-not (Test-Path -LiteralPath $tempFilePath)) {
                    Remove-Item -LiteralPath $transferDir -Recurse -Force -ErrorAction SilentlyContinue
                    continue
                }

                # Wait for the file to actually land AND finish being written.
                if (-not (Wait-ForStableFile -Path $tempFilePath -TimeoutMs 20000 -PollMs 200)) {
                    Write-Log "  -> Timeout waiting for MTP transfer to complete for $originalName" "Red"
                    # Leave the folder around; the orphan sweep on next startup will recover
                    # anything that eventually shows up. Attempt cleanup only if empty.
                    if (-not (Get-ChildItem -LiteralPath $transferDir -ErrorAction SilentlyContinue)) {
                        Remove-Item -LiteralPath $transferDir -Recurse -Force -ErrorAction SilentlyContinue
                    }
                    continue
                }

                # Pick a fresh timestamp name at the moment of rename to guarantee uniqueness.
                $target = Get-UniqueTargetPath -Extension $ext -DestFolder $DestinationFolder

                $moved = $false
                for ($attempt = 0; $attempt -lt 25 -and -not $moved; $attempt++) {
                    try {
                        Move-Item -LiteralPath $tempFilePath -Destination $target.Path -ErrorAction Stop
                        $moved = $true
                    } catch {
                        Start-Sleep -Milliseconds 200
                    }
                }

                if ($moved) {
                    Write-Log "  -> Saved as $($target.Name)" "Green"
                } else {
                    Write-Log "  -> Error: Could not move $originalName out of temp." "Red"
                }

                # Clean up the per-transfer folder if empty
                if (-not (Get-ChildItem -LiteralPath $transferDir -ErrorAction SilentlyContinue)) {
                    Remove-Item -LiteralPath $transferDir -Recurse -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {
            # Suppress *repeated* identical transient COM errors (camera busy writing to card),
            # but always surface the first occurrence and any new error message.
            $msg = $_.Exception.Message
            $now = Get-Date
            if ($msg -ne $lastErrorMessage -or ($now - $lastErrorAt).TotalSeconds -gt 30) {
                Write-Log "Loop error: $msg" "Red"
                $lastErrorMessage = $msg
                $lastErrorAt = $now
            }
            # Invalidate cached folders — force full re-walk on next iteration
            $dcimFolder   = $null
            $sourceFolder = $null
        }

        Start-Sleep -Milliseconds 300
    }
} finally {
    # Best-effort COM cleanup on Ctrl+C / exit
    if ($shell) {
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null } catch {}
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    Write-Log "Shutting down." "Cyan"
}
