# Live mode: keep an SSH tunnel to OUR NUC open (auto-reconnect) and run the dashboard.
# Assumes the bridge is already running on the NUC (scripts/nuc/start-bridge.sh).
# Never starts, stops or changes anything on the robot.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-robot.ps1
. (Join-Path $PSScriptRoot "_common.ps1")
$cfg = Read-RobotEnv
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { Fail "'ssh' not found. Enable 'OpenSSH Client' in Settings > Apps > Optional features." }

$env:LITE3_BRIDGE_WS_URL = "ws://127.0.0.1:$($cfg['LOCAL_PORT'])/ws"
$env:LITE3_EXPECTED_HOSTNAME = "$($cfg['EXPECTED_HOSTNAME'])"
$env:LITE3_EXPECTED_DOMAIN_ID = "$($cfg['EXPECTED_DOMAIN_ID'])"
if (-not $env:LITE3_EXPECTED_HOSTNAME) { Write-Host "WARNING: EXPECTED_HOSTNAME not set - robot identity will be shown as unverified." -ForegroundColor Yellow }

# The tunnel needs LOCAL_PORT free on this PC. If something already listens there
# (an old tunnel from a closed window, or the simulator), stop instead of looping.
$busy = @(Get-NetTCPConnection -LocalPort ([int]$cfg["LOCAL_PORT"]) -State Listen -ErrorAction SilentlyContinue)
if ($busy.Count -gt 0) {
    Write-Host "Port $($cfg['LOCAL_PORT']) on this PC is already in use by:" -ForegroundColor Yellow
    foreach ($b in $busy) {
        $p = Get-Process -Id $b.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "   PID $($b.OwningProcess)  $($p.ProcessName)"
    }
    Write-Host ""
    Write-Host "Usually an old tunnel (ssh) or the simulator (python). Stop it with:"
    Write-Host "   Get-NetTCPConnection -LocalPort $($cfg['LOCAL_PORT']) -State Listen | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }"
    Write-Host "then run this script again."
    exit 1
}

$web = $null
try {
    Push-Location (Join-Path $Root "web")
    try {
        # Rebuild when the code changed since the last build (e.g. after `git pull`).
        $rev = "unknown"
        try { $rev = (& git -C $Root rev-parse HEAD 2>$null) } catch { }
        $built = ""
        if (Test-Path ".next\lite3-build-rev") { $built = (Get-Content ".next\lite3-build-rev" -Raw).Trim() }
        if (-not (Test-Path ".next") -or $built -ne "$rev") {
            Write-Host "==> Building the dashboard for this version (1-2 min, only after updates)"
            & npm.cmd ci --no-audit --no-fund --silent; if ($LASTEXITCODE -ne 0) { Fail "npm ci failed" }
            & npm.cmd run build; if ($LASTEXITCODE -ne 0) { Fail "build failed" }
            Set-Content -Path ".next\lite3-build-rev" -Value "$rev" -NoNewline
        }
        $web = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "start") -NoNewWindow -PassThru
    } finally { Pop-Location }
    Start-Sleep -Seconds 3
    Write-Host "==> Dashboard: http://127.0.0.1:3000   (Ctrl+C stops the tunnel and the dashboard only)"
    Start-Process "http://127.0.0.1:3000"

    # Tunnel in the foreground so a password / host-key prompt is visible.
    # Use an SSH key (see docs/TEAM_SETUP.md) so reconnects need no typing.
    $delay = 1
    while ($true) {
        Write-Host "[tunnel] $($cfg['SSH_DEST']) : 127.0.0.1:$($cfg['LOCAL_PORT']) -> NUC 127.0.0.1:$($cfg['REMOTE_PORT'])"
        $started = Get-Date
        & ssh -N -p $cfg["NUC_SSH_PORT"] -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o ConnectTimeout=8 `
            -o ExitOnForwardFailure=yes -L "127.0.0.1:$($cfg['LOCAL_PORT']):127.0.0.1:$($cfg['REMOTE_PORT'])" $cfg["SSH_DEST"]
        if (((Get-Date) - $started).TotalSeconds -gt 30) { $delay = 1 }
        Write-Host "[tunnel] disconnected; retrying in ${delay}s"
        Start-Sleep -Seconds $delay
        $delay = [Math]::Min(10, $delay * 2)
    }
} finally {
    Stop-Tree $web
}
