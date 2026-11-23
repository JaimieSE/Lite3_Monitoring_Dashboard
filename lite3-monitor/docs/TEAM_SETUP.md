# Team setup: Mac and Windows, several viewers at once

Every team-mate can run the dashboard on their own laptop (macOS or Windows).
Each laptop opens its **own** SSH tunnel to the NUC and keeps its **own** test
history. Nobody needs to touch the robot to watch it.

```
 Laptop A (Mac)      ──SSH tunnel──┐
 Laptop B (Windows)  ──SSH tunnel──┼──▶ NUC: lite3_bridge (one copy, read-only) ──▶ listens to ROS topics
 Laptop C (Windows)  ──SSH tunnel──┘
```

## 1. Get the code (everyone)

```bash
git clone https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git
cd Lite3_Monitoring_Dashboard
git checkout claude/gallant-hamilton-q50da3    # until this is merged into main
cd lite3-monitor
```

## 2a. macOS

```bash
brew install node@20 python@3.12     # skip what you already have (Node >= 20, Python >= 3.10)
./scripts/mac/install.sh              # one-time; stays inside the repo folder
./scripts/mac/start-sim.sh            # simulator → http://127.0.0.1:3000
```
Live robot: fill `scripts/mac/robot.env`, then `./scripts/mac/start-robot.sh`.

## 2b. Windows 10/11 (PowerShell)

```powershell
winget install OpenJS.NodeJS.LTS Python.Python.3.12 Git.Git   # then reopen PowerShell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\start-sim.ps1
```
`start-sim.ps1` options: `-Dev`, `-Dropouts`, `-NoFaults`, `-LatencyMs 150`, `-NoMap`, `-Profile group8`.

**Our robot runs without a map** (profile `group8`): position comes from leg odometry,
there are no paths/goals/frontiers, and TF is not required. Preview exactly that with
`start-sim.sh --profile group8` / `start-sim.ps1 -Profile group8`.

Live robot: fill `scripts\windows\robot.env` (created by install), then
```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start-robot.ps1
```

Notes
- `-ExecutionPolicy Bypass` applies to that one command only; nothing system-wide changes.
- `ssh` is built into Windows 10/11. If missing: Settings → Apps → Optional features → *OpenSSH Client*.
- If Windows Firewall asks about Python or Node, you can click **Cancel**: everything listens on 127.0.0.1 only.
- Use Chrome or Edge.
- WSL (Ubuntu on Windows) also works and can use the Mac scripts unchanged.

## 3. SSH access for each team-mate

Each laptop needs to SSH into the NUC. Agree with the team **before** adding anything to the NUC
(it changes the NUC user's `~/.ssh/authorized_keys`, which is outside this project):

- Simplest: everyone uses the shared NUC account and password; the tunnel prompts for the password
  and again after every Wi-Fi drop.
- Better: each person adds their own SSH key once, so reconnects are automatic.
  - Mac: `ssh-keygen -t ed25519` then `ssh-copy-id USER@NUC`
  - Windows: `ssh-keygen -t ed25519` then
    `type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh USER@NUC "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"`

Only **one** person starts the bridge on the NUC (`scripts/nuc/start-bridge.sh` in tmux).
Everyone else only runs the tunnel + dashboard.

## 4. Several viewers: what it costs

| | Per extra viewer |
|---|---|
| Robot navigation / SLAM / locomotion | **No effect.** Viewers only receive copies of data the bridge already has; the bridge subscribes to ROS once, no matter how many people watch. |
| NUC CPU | Very small: one encrypted SSH session + sending the same pre-built messages again. |
| NUC Wi-Fi upload | ≈ 5–15 kB/s per viewer for telemetry, plus map bursts if the viewer has the map on. |
| Each viewer's delay | Independent; shown in each person's top bar. On congested Wi-Fi, more viewers = more traffic on the same access point. |

Limits and tips
- Up to **6** dashboards at once (`server.max_clients` in the bridge config). A 7th is refused and
  keeps retrying until someone closes their tab.
- If the Wi-Fi is struggling, ask viewers who only need numbers to switch **Map stream: off**.
- The top bar's delay pill (hover it) shows how many dashboards are connected.
- Test history is saved on each laptop separately (`web/data/history`). Use **Export JSON/CSV** to share runs.
