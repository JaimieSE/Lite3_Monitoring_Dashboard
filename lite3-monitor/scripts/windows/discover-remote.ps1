# READ-ONLY discovery of the NUC's ROS 2 graph, zero footprint (nothing installed or
# written on the NUC). Same as scripts/mac/discover-remote.sh. Requires approval.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\discover-remote.ps1 [-Seconds 8]
param([int]$Seconds = 8, [switch]$Heavy)   # -Heavy: also measure camera / point-cloud data rates once
. (Join-Path $PSScriptRoot "_common.ps1")
$cfg = Read-RobotEnv
$ws = $cfg["NUC_LITE3_WS"]
if (-not $ws) { $ws = "~/lite3_ws" }

# A non-interactive SSH shell does not load ~/.bashrc, so ROS_DOMAIN_ID must come
# from robot.env - otherwise discovery would look at domain 0 (other robots).
$dom = "$($cfg['EXPECTED_DOMAIN_ID'])"
$expHost = "$($cfg['EXPECTED_HOSTNAME'])"
if ($dom -notmatch '^\d+$') { Fail "Set EXPECTED_DOMAIN_ID (a number) in robot.env first." }
if (-not $expHost) { Fail "Set EXPECTED_HOSTNAME in robot.env first." }

Write-Host "This will SSH to $($cfg['SSH_DEST']) and run a read-only ROS 2 discovery for ${Seconds}s:"
Write-Host "  - lists nodes/topics/services/actions/TF frames, samples topic rates (subscriptions only)"
Write-Host "  - never publishes, never calls services/actions, never touches parameters"
Write-Host "  - installs nothing and writes no files on the NUC"
Confirm-Or-Exit "Proceed?"

# Build the remote bash script with LF line endings (CRLF would break bash heredocs).
$py = (Get-Content -Raw (Join-Path $Root "bridge\lite3_bridge\discover.py")) -replace "`r`n", "`n"
$lines = @(
    ('if [ "$(hostname)" != "' + $expHost + '" ]; then echo "WRONG MACHINE: $(hostname) is not ' + $expHost + ' - aborting" >&2; exit 3; fi'),
    'source /opt/ros/humble/setup.bash >/dev/null 2>&1',
    "export ROS_DOMAIN_ID=$dom",
    "WS=$ws",
    'if [ -f "$WS/install/setup.bash" ]; then source "$WS/install/setup.bash" >/dev/null 2>&1; fi',
    'echo "# hostname: $(hostname)  ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}" >&2',
    ("python3 - --seconds $Seconds" + $(if ($Heavy) { " --include-heavy" } else { "" }) + " <<'__LITE3_DISCOVER_PY__'"),
    $py.TrimEnd("`n"),
    '__LITE3_DISCOVER_PY__'
)
$script = ($lines -join "`n") + "`n"
$utf8 = New-Object System.Text.UTF8Encoding($false)   # no BOM

$outDir = Join-Path $Root "docs\discovery"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$out = Join-Path $outDir ("discovery-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".md")

# Feed the script to `ssh ... bash -s` byte-exactly (PowerShell pipes would re-encode it).
# stderr stays on the console so password / host-key prompts remain visible.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "ssh"
$psi.Arguments = "-p $($cfg['NUC_SSH_PORT']) -o ConnectTimeout=8 $($cfg['SSH_DEST']) bash -s"
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$bytes = $utf8.GetBytes($script)
$proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
$proc.StandardInput.Close()
$report = $proc.StandardOutput.ReadToEnd()
$proc.WaitForExit()
if ($proc.ExitCode -ne 0) { Write-Host "ssh exited with code $($proc.ExitCode)" -ForegroundColor Yellow }
[System.IO.File]::WriteAllText($out, $report, $utf8)
Write-Host $report
Write-Host ""
Write-Host "Saved to $out - commit it so the next agent can use it."
