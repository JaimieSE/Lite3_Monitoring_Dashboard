# ONE command for live monitoring:
#   1. on the NUC: start the read-only bridge in tmux (skipped if it is already running)
#   2. on this PC: SSH tunnel + dashboard (start-robot.ps1), browser opens
# Safe for every team-mate to run: it never starts a second bridge.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-all.ps1
. (Join-Path $PSScriptRoot "_common.ps1")
$cfg = Read-RobotEnv
$dom = "$($cfg['EXPECTED_DOMAIN_ID'])"
if ($dom -notmatch '^\d+$') { Fail "Set EXPECTED_DOMAIN_ID (a number) in robot.env first." }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { Fail "'ssh' not found. Enable 'OpenSSH Client' in Settings > Apps > Optional features." }
$dir = "$($cfg['NUC_MONITOR_DIR'])"
if (-not $dir) { $dir = "~/Lite3_Monitoring_Dashboard/lite3-monitor" }

Write-Host "==> Checking the bridge on the NUC ($($cfg['SSH_DEST'])) - enter the NUC password if asked"
# Stream ensure-bridge.sh to `bash -s` byte-exactly with LF endings (CRLF would break bash).
$script = ((Get-Content -Raw (Join-Path $Root "scripts\nuc\ensure-bridge.sh")) -replace "`r`n", "`n")
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "ssh"
$psi.Arguments = "-p $($cfg['NUC_SSH_PORT']) -o ConnectTimeout=8 $($cfg['SSH_DEST']) bash -s -- $dom $($cfg['REMOTE_PORT']) $dir"
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($script)
$proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
$proc.StandardInput.Close()
$proc.WaitForExit()
if ($proc.ExitCode -ne 0) {
    Fail "The bridge is not running on the NUC (see above). Fix that first; the robot is unaffected."
}

Write-Host "==> Starting tunnel + dashboard (enter the NUC password again if asked)"
& (Join-Path $PSScriptRoot "start-robot.ps1")
