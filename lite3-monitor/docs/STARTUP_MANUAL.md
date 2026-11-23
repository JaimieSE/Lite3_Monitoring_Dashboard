# Lite3 Monitor — Start-up Manual (group8)

Read-only monitoring dashboard for our Lite3. It **watches** the robot; it can
never move it, change its settings or stop its programs. If anything looks wrong,
stopping the monitor is always safe — the robot is not affected.

```
  NUC (on the robot)                          Your laptop (Mac or Windows)
  ┌────────────────────────────┐   SSH tunnel   ┌───────────────────────────┐
  │ robot software (unchanged) │                │ start-robot script        │
  │ lite3_bridge  ◀─ tmux ─────┼───────────────▶│  └─ dashboard → browser   │
  └────────────────────────────┘ 127.0.0.1:8765 │     http://127.0.0.1:3000 │
                                                └───────────────────────────┘
```

| Thing | Value |
|---|---|
| NUC address / user | `192.168.10.78` / `user` (also in your `robot.env`) |
| NUC hostname | `group8` |
| ROS domain | `8` |
| Code on the NUC | `~/Lite3_Monitoring_Dashboard/lite3-monitor` |
| Dashboard URL | http://127.0.0.1:3000 |

---

## 0. One-time setup (each laptop, only once)

Already done if the dashboard has worked on your laptop before.

1. Install the tools and the project → see [TEAM_SETUP.md](TEAM_SETUP.md)
   (`install.sh` on Mac, `install.ps1` on Windows).
2. Create your connection file and fill it in:
   - Mac: `scripts/mac/robot.env` · Windows: `scripts\windows\robot.env`
   ```
   NUC_HOST=192.168.10.78
   NUC_USER=user
   EXPECTED_HOSTNAME=group8
   EXPECTED_DOMAIN_ID=8
   ```
3. Check you can log in: `ssh user@192.168.10.78`.

The NUC side (bridge install) is already done. Re-install only if the folder
`~/Lite3_Monitoring_Dashboard` is deleted (see §6).

---

## 1. Start-up (every session)

Do the steps in this order. The robot's own software can already be running or be
started at any time — the monitor does not care about the order.

### Step 1 — Start the bridge on the NUC (one person only)

Only **one** team-mate does this. Everyone else skips to Step 2.

```bash
ssh user@192.168.10.78
tmux attach -t monitor || tmux new -s monitor
```
Inside tmux:
```bash
pgrep -af lite3_bridge            # prints a line? → bridge already running: skip to "Detach"
echo $ROS_DOMAIN_ID               # must print 8
~/Lite3_Monitoring_Dashboard/lite3-monitor/scripts/nuc/start-bridge.sh
```
Good start-up looks like:
```
hostname=group8 ROS_DOMAIN_ID=8 ...
profile=group8
... subscribed (read-only) /leg_odom2 ...
... read-only audit passed ...: 0 publishers, 0 services, 0 clients
... lite3-monitor bridge ... (ros mode, READ-ONLY) on ws://127.0.0.1:8765/ws
```
(After that it repeats `read-only audit passed (graph-scan)` every few seconds — normal.)

**Detach** (leave it running): press **Ctrl+B**, release, then **D**. You can now
close the SSH window.

### Step 2 — Start the dashboard on your laptop (everyone)

**Mac** (Terminal):
```bash
cd ~/Lite3_Monitoring_Dashboard/lite3-monitor
./scripts/mac/start-robot.sh
```
**Windows** (PowerShell):
```powershell
cd $HOME\Lite3_Monitoring_Dashboard\lite3-monitor
powershell -ExecutionPolicy Bypass -File scripts\windows\start-robot.ps1
```
Type the NUC password if asked. Keep this window open while monitoring.
The browser opens http://127.0.0.1:3000 (open it yourself if it doesn't).

### Step 3 — Check it is live (10 seconds)

| Where | Should show |
|---|---|
| Top bar, left | **Robot verified** · `Lite3 group8 @ group8 · domain 8` |
| Top bar, right | **LIVE** (green), `delay … ms` green or amber, **REC** running |
| Main panel | **Live position (no map)** — robot box moves when the robot walks |
| TF & diagnostics | sensor chips IMU · Joints · Odom · Odom2 · Ultrasound all **alive** (green); TF shows "not used" (normal for us) |
| System health | mostly green; `/leg_odom2`, `/imu/data`, `/joint_states` ≈ 200 Hz |

If any of these is wrong → §4 Troubleshooting.

---

## 2. During a run

- **Recording** starts automatically. Press **STOP** (top bar) at the end of a test
  run; press **Record session** to start the next one.
- **Map stream** button is shown as "Map: disabled" — expected, we run without a map.
- **Event log** (bottom right) lists every warning: stalls, sensor dropouts, link loss.
- **Temperatures** (graph under the map) shows the NUC's hottest sensor and any robot
  temperatures over the last 1–30 min. The top bar always shows `NUC xx °C` (amber ≥ 80 °C,
  red ≥ 90 °C, "· throttling" when the CPU slows itself down) and `Robot xx °C` once a
  robot temperature topic is configured. If the NUC runs hot: give it airflow / a break
  before performance drops. Robot temperature topics go in `temperature_topics` in
  `bridge/config/default.yaml` (none exist on domain 8 yet).
- **NUC compute** shows the NUC's CPU, memory, temperature and disk, and how much CPU
  each part uses (camera driver, LiDAR driver, domain bridge, navigation, this monitor).
  **Data per topic** shows how much data each monitored sensor stream produces.
  To measure the heavy camera / LiDAR streams once: `./scripts/mac/discover-remote.sh 8 --heavy`.
- **Red TELEMETRY LOST banner** = the laptop lost contact (usually Wi-Fi). The robot
  keeps running. The dashboard reconnects by itself; positions shown meanwhile are
  marked **LAST KNOWN** and are not live.
- Several team-mates can watch at once (up to 6). If the Wi-Fi is slow, the people
  who don't need the dashboard should close their tab.

---

## 3. Shutting down

1. **Laptop:** press **Ctrl+C** in the Terminal/PowerShell window running
   `start-robot`. This closes the tunnel and the dashboard.
2. **NUC bridge** (optional — it can stay running for the next session):
   ```bash
   ssh user@192.168.10.78
   tmux attach -t monitor        # then Ctrl+C to stop the bridge
   exit                          # closes the tmux window
   ```
Stopping either one never affects the robot.

Recorded sessions stay on your laptop: **History** tab → export **JSON / CSV**.

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **CONNECTING** forever, or TELEMETRY LOST right away | Bridge not running on the NUC → do Step 1. Or the tunnel failed: look at the `[tunnel]` lines in your laptop window (wrong password, NUC off, not on the school Wi-Fi). |
| `Port 8765 … already in use` when starting the bridge | A bridge is already running — fine, use it. To restart cleanly: `pkill -f lite3_bridge`, then Step 1 again. |
| `REFUSING TO START: ROS_DOMAIN_ID=0 != expected 8` | Your shell does not have the team environment. In tmux run `export ROS_DOMAIN_ID=8` (or open a fresh SSH login) and start again. |
| `REFUSING TO START: hostname … != expected 'group8'` | You are logged into the wrong computer. Check the IP. |
| **IDENTITY MISMATCH** (red) in the dashboard | Your `robot.env` says another hostname/domain than the bridge reports. Fix `EXPECTED_HOSTNAME=group8`, `EXPECTED_DOMAIN_ID=8`. |
| Laptop window: `bind ... 8765: Address already in use` | Another tunnel is already open on your laptop (old window). Close it, or stop it: Mac `pkill -f "8765:127.0.0.1:8765"`. |
| Robot box does not move | Check System health: `/leg_odom2` must be green ≈ 200 Hz. If missing, the robot's driver / domain bridge on the NUC is not running. |
| A sensor chip is red (**NOT alive**) | The robot itself reports that sensor as dead — check the robot, not the monitor. |
| **delay** amber/orange, spikes | Busy Wi-Fi. Fewer viewers, move closer to the access point. |
| **NUC 9x °C** red / "throttling" | The NUC is overheating and slowing its CPU. Pause, improve airflow, check the fan; navigation may lag until it cools. |
| No `NUC °C` pill at all | The NUC exposes no temperature sensors to normal users (rare). Check `ls /sys/class/hwmon`. |
| Asked for the password again and again | Normal after every Wi-Fi drop. Set up an SSH key to avoid it ([TEAM_SETUP.md](TEAM_SETUP.md) §3). |
| `tmux: command not found` | Run the bridge in a normal SSH window and leave that window open. |
| Dashboard page blank / old after an update | Stop `start-robot`, then in `web/` run `npm run build`, start again. |

When asking for help, copy the last ~20 lines of the bridge (tmux) and of your
laptop window.

---

## 5. Updating to a newer version

**Laptop:**
```bash
cd ~/Lite3_Monitoring_Dashboard && git pull
cd lite3-monitor/web && npm ci && npm run build
```
(Windows: same commands in PowerShell, `npm.cmd` works too.)

**NUC** (stop the bridge first, §3):
```bash
cd ~/Lite3_Monitoring_Dashboard && git pull
```
Then Step 1 again. Re-run `scripts/nuc/install.sh` only if `bridge/requirements.txt` changed.

---

## 6. Re-installing the bridge on the NUC (rarely needed)

```bash
cd ~
git clone https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git
~/Lite3_Monitoring_Dashboard/lite3-monitor/scripts/nuc/install.sh     # answer y
```
If the latest work is not merged into `main` yet, add `-b claude/gallant-hamilton-q50da3`
to the `git clone` line.
Installs 4 small Python packages into that folder only (no sudo, nothing in `lite3_ws`).
Remove completely: stop the bridge, then `rm -rf ~/Lite3_Monitoring_Dashboard`.

---

## 7. Safety rules (for everyone)

- The monitor is **read-only**. Never edit it to send commands to the robot.
- Do not change anything in `~/lite3_ws` for the monitor.
- The bridge only listens on the NUC itself (127.0.0.1); access is only through SSH.
- If in doubt: stop the monitor. The robot does not depend on it.

Details: [SAFETY.md](SAFETY.md) · Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
