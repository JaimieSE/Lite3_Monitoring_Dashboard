# Windows one-time setup: web dependencies + a local Python venv for the simulator.
# Touches nothing outside this repository. Does not contact the robot.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
. (Join-Path $PSScriptRoot "_common.ps1")

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js not found. Install: winget install OpenJS.NodeJS.LTS (then reopen PowerShell)" }
$nodeMajor = [int](& node -p "process.versions.node.split('.')[0]")
if ($nodeMajor -lt 20) { Fail "Node >= 20 required (found $(& node -v))." }
$py = Find-Python
if (-not $py) { Fail "Python 3.10+ not found. Install: winget install Python.Python.3.12 (then reopen PowerShell)" }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: 'ssh' not found. Enable 'OpenSSH Client' in Settings > Apps > Optional features (needed for live mode only)." -ForegroundColor Yellow
}

Write-Host "==> Installing web dependencies (lite3-monitor\web)"
Push-Location (Join-Path $Root "web")
try { & npm.cmd ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { Fail "npm ci failed" } } finally { Pop-Location }

Write-Host "==> Creating simulator venv (lite3-monitor\bridge\.venv)"
$pyExe = $py[0]
$pyArgs = @()
if ($py.Length -gt 1) { $pyArgs = $py[1..($py.Length - 1)] }
& $pyExe @pyArgs -m venv (Join-Path $Root "bridge\.venv")
if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
$vpy = Venv-Python
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r (Join-Path $Root "bridge\requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

$envLocal = Join-Path $Root "web\.env.local"
if (-not (Test-Path $envLocal)) { Copy-Item (Join-Path $Root "web\.env.example") $envLocal; Write-Host "==> Created web\.env.local" }
$robotEnv = Join-Path $PSScriptRoot "robot.env"
if (-not (Test-Path $robotEnv)) {
    Copy-Item (Join-Path $PSScriptRoot "robot.env.example") $robotEnv
    Write-Host "==> Created scripts\windows\robot.env - fill in the NUC details before live use"
}
Write-Host ""
Write-Host "Done. Start the simulator dashboard with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\windows\start-sim.ps1"
