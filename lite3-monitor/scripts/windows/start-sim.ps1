# Run the full dashboard on Windows against the built-in simulator (no robot).
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-sim.ps1 [-Dev] [-Dropouts] [-NoFaults] [-LatencyMs 150] [-NoMap] [-Profile group8]
param([switch]$Dev, [switch]$Dropouts, [switch]$NoFaults, [int]$LatencyMs = 0, [switch]$NoMap, [string]$Profile = "")
. (Join-Path $PSScriptRoot "_common.ps1")

$vpy = Venv-Python
if (-not (Test-Path $vpy)) { Fail "Run scripts\windows\install.ps1 first." }

$bridgeArgs = @("-m", "lite3_bridge", "--sim")
if ($Dropouts) { $bridgeArgs += "--sim-link-dropouts" }
if ($NoFaults) { $bridgeArgs += "--sim-no-faults" }
if ($LatencyMs -gt 0) { $bridgeArgs += @("--sim-latency-ms", "$LatencyMs") }
if ($NoMap) { $bridgeArgs += "--no-map-stream" }
if ($Profile) {
    if (-not (Test-Path (Join-Path $Root "bridge\config\$Profile.yaml"))) { Fail "No profile bridge\config\$Profile.yaml" }
    $bridgeArgs += @("--config", "config/$Profile.yaml")
}

$env:LITE3_BRIDGE_WS_URL = "ws://127.0.0.1:8765/ws"
$bridge = $null
$web = $null
try {
    Write-Host "==> Simulated bridge on ws://127.0.0.1:8765/ws"
    $bridge = Start-Process -FilePath $vpy -ArgumentList $bridgeArgs -WorkingDirectory (Join-Path $Root "bridge") -NoNewWindow -PassThru

    Push-Location (Join-Path $Root "web")
    try {
        if ($Dev) {
            $web = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") -NoNewWindow -PassThru
        } else {
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { Fail "build failed" }
            $web = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "start") -NoNewWindow -PassThru
        }
    } finally { Pop-Location }

    Start-Sleep -Seconds 4
    Write-Host "==> Dashboard: http://127.0.0.1:3000   (Ctrl+C to stop everything)"
    Start-Process "http://127.0.0.1:3000"
    while (-not $bridge.HasExited -and -not $web.HasExited) { Start-Sleep -Seconds 1 }
    if ($bridge.HasExited) { Write-Host "Bridge stopped (exit $($bridge.ExitCode))." -ForegroundColor Yellow }
} finally {
    Stop-Tree $web
    Stop-Tree $bridge
}
