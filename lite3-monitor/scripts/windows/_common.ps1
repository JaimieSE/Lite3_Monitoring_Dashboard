# Shared helpers for the Windows scripts. Compatible with Windows PowerShell 5.1 and PowerShell 7.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path   # ...\lite3-monitor

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Find-Python {
    # Returns @(exe, args...) for Python >= 3.10, or $null. Prefers the py launcher and
    # skips the Microsoft Store "python" stub (which prints no version).
    foreach ($candidate in @("py -3", "python", "python3")) {
        $parts = $candidate -split ' '
        $exe = $parts[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $cmdArgs = @()
        if ($parts.Length -gt 1) { $cmdArgs = @($parts[1..($parts.Length - 1)]) }
        $ver = $null
        try { $ver = & $exe @cmdArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" } catch { continue }
        if ("$ver" -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 10) {
            $result = @($exe) + $cmdArgs
            return ,$result
        }
    }
    return $null
}

function Venv-Python { Join-Path $Root "bridge\.venv\Scripts\python.exe" }

function Read-RobotEnv {
    $file = Join-Path $PSScriptRoot "robot.env"
    if (-not (Test-Path $file)) { Fail "Missing $file (copy robot.env.example and fill it in)." }
    $cfg = @{}
    foreach ($line in Get-Content $file) {
        $l = ($line -replace '#.*$', '').Trim()
        if ($l -match '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
    }
    if ($cfg["NUC_SSH_TARGET"]) { $cfg["SSH_DEST"] = $cfg["NUC_SSH_TARGET"] }
    elseif ($cfg["NUC_HOST"] -and $cfg["NUC_USER"]) { $cfg["SSH_DEST"] = "$($cfg['NUC_USER'])@$($cfg['NUC_HOST'])" }
    else { Fail "Set NUC_HOST and NUC_USER (or NUC_SSH_TARGET) in $file" }
    foreach ($k in @("NUC_SSH_PORT", "LOCAL_PORT", "REMOTE_PORT")) { if (-not $cfg[$k]) { $cfg[$k] = "" } }
    if (-not $cfg["NUC_SSH_PORT"]) { $cfg["NUC_SSH_PORT"] = "22" }
    if (-not $cfg["LOCAL_PORT"]) { $cfg["LOCAL_PORT"] = "8765" }
    if (-not $cfg["REMOTE_PORT"]) { $cfg["REMOTE_PORT"] = "8765" }
    return $cfg
}

function Stop-Tree($proc) {
    # Stop a process and all of its children (npm -> node, etc.).
    if ($proc -and -not $proc.HasExited) {
        try { & taskkill.exe /T /F /PID $proc.Id | Out-Null } catch { }
    }
}

function Confirm-Or-Exit($question) {
    $a = Read-Host "$question [y/N]"
    if ($a -notmatch '^[Yy]$') { Write-Host "Aborted."; exit 1 }
}
