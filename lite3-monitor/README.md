# lite3-monitor

Read-only, real-time mission-control dashboard for the DEEP Robotics **Lite3**
autonomous exploration competition.

- **Web dashboard** (macOS): Next.js 15 + TypeScript + Tailwind, live SLAM map,
  telemetry cards, health, trends, recorded test history with CSV/JSON export.
- **Telemetry bridge** (NUC): Python + FastAPI + rclpy. Subscribes only, throttles,
  and pushes JSON over a WebSocket bound to `127.0.0.1`.
- **SSH tunnel** connects the two. Nothing on the robot is reachable from the network.
- **Simulator**: the same bridge with `--sim` runs a fake exploring robot so the
  whole stack works on a Mac with no robot.

> **Safety first:** the system is strictly monitoring-only. It never publishes,
> never calls services/actions, never touches parameters, never starts/stops nodes
> and never executes anything the dashboard sends. See [docs/SAFETY.md](docs/SAFETY.md).

```
 MacBook (macOS)                                   NUC (Ubuntu 22.04, ROS 2 Humble)
 ┌──────────────────────────────┐   SSH tunnel    ┌───────────────────────────────────┐
 │ Browser → Next.js :3000      │  127.0.0.1:8765 │ lite3_bridge (FastAPI :8765, lo)  │
 │   Live page  (WebSocket in)  │◀───────────────▶│   ├─ RosSource: subscriptions only│
 │   History page               │   -L 8765:      │   ├─ TelemetryStore (latest-value)│
 │ /api/history → data/*.json   │   127.0.0.1:8765│   └─ Broadcaster 10/1/1/0.5 Hz    │
 └──────────────────────────────┘                 │ existing lite3_ws nodes (untouched)│
                                                  └───────────────────────────────────┘
```

## Quick start

**Running it on the robot every day: [docs/STARTUP_MANUAL.md](docs/STARTUP_MANUAL.md).**
**Team-mates (Mac or Windows, several viewers at once): see [docs/TEAM_SETUP.md](docs/TEAM_SETUP.md).**

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\start-sim.ps1
```

### Simulation, macOS

Requirements: Node.js ≥ 20, Python ≥ 3.10.

```bash
cd lite3-monitor
./scripts/mac/install.sh          # npm ci + local Python venv (repo-local only)
./scripts/mac/start-sim.sh        # simulator bridge + dashboard → http://127.0.0.1:3000
./scripts/mac/start-sim.sh --dropouts   # also simulate Wi-Fi loss to see TELEMETRY LOST
./scripts/mac/start-sim.sh --latency 150   # emulate a slow link (150 ms each way)
./scripts/mac/start-sim.sh --profile group8   # behave like our robot: no map, pose from odometry
```

Manual equivalent:

```bash
cd bridge && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m lite3_bridge --sim            # ws://127.0.0.1:8765/ws
cd ../web && npm ci && npm run build && npm run start   # http://127.0.0.1:3000
```

## Live robot (only after the team approves NUC integration)

1. Fill in `scripts/mac/robot.env` (copied from `robot.env.example`): NUC host,
   user, expected hostname, expected `ROS_DOMAIN_ID`. Nothing is guessed.
2. **Discover** the real ROS graph, read-only and zero-footprint (streams a script
   over SSH; installs nothing): `./scripts/mac/discover-remote.sh`. Commit the
   report in `docs/discovery/` and adjust `bridge/config/default.yaml` candidates.
3. **Deploy** (approval required): `./scripts/mac/deploy-bridge.sh` copies the bridge
   to `~/lite3-monitor` on the NUC. On the NUC: `~/lite3-monitor/scripts/nuc/install.sh`
   (venv with `--system-site-packages`; pip installs fastapi, uvicorn, websockets,
   PyYAML; no sudo/apt), edit `bridge/config/local.yaml` identity, then run
   `~/lite3-monitor/scripts/nuc/start-bridge.sh` inside `tmux`.
4. On the Mac: `./scripts/mac/start-robot.sh` (auto-reconnecting tunnel + dashboard).

Full procedure and checklist: [docs/NUC_INTEGRATION.md](docs/NUC_INTEGRATION.md).

## Dashboard

**Live** page
- Top bar: SIM / verified / unverified / mismatch identity badge, robot@host and
  domain, link state (LIVE / STALE / TELEMETRY LOST) with age of last message,
  **link delay** (round trip through Wi-Fi + tunnel; hover for one-way delay,
  clock offset and kB/s), recording controls.
- **Map stream** switch (top-left of the map): turn the occupancy grid off to save
  bandwidth; everything else, including coverage numbers, stays live.
- Live SLAM map (main element): occupancy grid (free / occupied / unknown), robot
  pose from TF (`map→odom→base`), trail, global/local path, frontiers, nav goal,
  1 m grid, pan/zoom/follow/auto-fit, map age. When telemetry stops the robot is
  drawn as a dashed **LAST KNOWN · Ns ago** outline and a red banner is shown.
- Robot overview: x, y, yaw, frame/source, linear/lateral/angular velocity vs
  commanded, navigation status, distance to goal, mission time, session time.
- Exploration: state (from topic, or inferred: NAVIGATING / MOVING / STATIONARY /
  STALLED / COMPLETE?), frontier count, distance travelled, runtime, known area /
  coverage, stationary time, stall events.
- TF chain with per-edge ages; diagnostics summary.
- Live trends: linear and angular velocity (measured vs commanded), sensor rates
  as % of expected, explored area.
- System health: every monitored topic with rate vs expected, age, publisher
  count (more than one on single-publisher topics ⇒ possible cross-robot traffic),
  missing roles and expected nodes, bridge statistics.
- Event log of state changes and faults.

**History** page: sessions recorded at 1 Hz to `web/data/history/*.json` on the
Mac; details (summary, trajectory, events, speed/area/rate charts), compare up to
4 runs, export JSON / CSV samples / CSV events, notes, delete.

## Configuration

| What | Where |
|---|---|
| Topic candidates, rates, staleness thresholds, frames, identity, arena area | `bridge/config/default.yaml`, then a robot profile (`config/group8.yaml`), then optional `config/local.yaml` — stack them with repeated `--config` |
| Bridge URL, expected hostname / domain for the dashboard | `web/.env.local` (`LITE3_*`, read at runtime by `/api/config`) |
| Tunnel + NUC details | `scripts/mac/robot.env` |

The bridge resolves each *role* (map, odometry, scan, imu, …) to the **first
candidate topic that exists** with an accepted type. Roles with no match show as
missing; nothing is assumed.

## Tests and checks

```bash
cd bridge && .venv/bin/python -m pytest -q          # bridge + simulator + fake-rclpy tests
cd web && npm run typecheck && npm test              # TS types + summary/CSV tests
python3 tools/check_readonly.py                      # static read-only audit (bridge + web)
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – components, data flow, performance budget
- [docs/PROTOCOL.md](docs/PROTOCOL.md) – WebSocket message schema
- [docs/SAFETY.md](docs/SAFETY.md) – read-only guarantees and how they are enforced
- [docs/NUC_INTEGRATION.md](docs/NUC_INTEGRATION.md) – approval-gated robot rollout
- [docs/TEAM_SETUP.md](docs/TEAM_SETUP.md) – Mac / Windows setup, SSH access, multiple viewers
