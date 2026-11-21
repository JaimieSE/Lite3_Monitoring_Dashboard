# NUC integration (approval-gated)

**Status: NOT STARTED. Waiting for the team's approval and the details below.**
Until approval, only simulation mode is used. Each step below that touches the
NUC is marked 🔒 and needs explicit approval at that time.

## Information needed (do not guess)

| Item | Why | Value |
|---|---|---|
| NUC IP / hostname on school Wi-Fi | SSH tunnel target | _unknown_ |
| SSH username (and key / `~/.ssh/config` alias) | SSH | _unknown_ |
| NUC `hostname` output | identity check | _unknown_ |
| `ROS_DOMAIN_ID` used by our robot | identity + isolation | _unknown_ |
| `RMW_IMPLEMENTATION` | discovery behaviour | _unknown_ |
| Path to `lite3_ws` on the NUC | source custom msg types read-only | assumed `~/lite3_ws`, confirm |
| Odometry topic (`/odom`, `/leg_odom2`, …) and type | pose fallback / velocity | discover |
| SLAM package and map topic, map QoS | map display | discover |
| Navigation stack (Nav2? custom?), action / status topics | nav status | discover |
| Exploration node, frontier topic, state topic | exploration panel | discover |
| TF frame names (`map`, `odom`, base frame) | pose | discover |
| Arena area in m² (optional) | coverage % | team |
| Is Python ≥ 3.10 + pip/venv available on the NUC? | bridge install | discover |

## Steps

1. Fill `scripts/mac/robot.env`. Confirm with `ssh <user>@<host> hostname` that it
   is **our** NUC (multiple robots share the Wi-Fi).
2. 🔒 **Read-only discovery** — `./scripts/mac/discover-remote.sh 8`.
   Streams `bridge/lite3_bridge/discover.py` to `python3 -` over SSH: lists nodes,
   topics + types + rates + publisher counts + QoS, actions, services (names only),
   TF edges. Installs and writes nothing on the NUC. Commit the report in
   `docs/discovery/`.
3. Update `bridge/config/default.yaml` (or a committed `config/lite3.yaml`) with the
   discovered topic names, frames, expected rates and `expected_nodes`. Run tests.
4. 🔒 **Deploy** — `./scripts/mac/deploy-bridge.sh` (rsync of the bridge source into
   `~/lite3-monitor`, separate from `lite3_ws`).
5. 🔒 **Install** on the NUC — `~/lite3-monitor/scripts/nuc/install.sh`: creates
   `~/lite3-monitor/.venv` with `--system-site-packages` and pip-installs
   `fastapi uvicorn websockets PyYAML`. No sudo, no apt, nothing system-wide.
   If the NUC has no internet, wheels can be copied from the Mac (`pip download`).
6. Edit `~/lite3-monitor/bridge/config/local.yaml`: `expected_hostname`,
   `expected_ros_domain_id` (the bridge then refuses to run anywhere else).
7. 🔒 **Run** — in `tmux`: `~/lite3-monitor/scripts/nuc/start-bridge.sh`. Check the log
   line `read-only audit passed … 0 publishers, 0 services, 0 clients`.
8. On the Mac: set `EXPECTED_HOSTNAME`/`EXPECTED_DOMAIN_ID` in `robot.env`, run
   `./scripts/mac/start-robot.sh`, open http://127.0.0.1:3000. The top bar must show
   **Robot verified** and the right hostname/domain.

## Verification checklist on the real robot

- [ ] `ros2 node info /lite3_monitor_readonly` shows **Publishers: none** (or only what
      rclpy cannot avoid – record it), **Service Servers: none**, **Clients: none**.
- [ ] `ros2 topic info -v /cmd_vel` lists no publisher from `lite3_monitor_readonly`.
- [ ] `top` on the NUC: bridge CPU < 5 % of one core during exploration.
- [ ] Unplug Wi-Fi on the Mac for 10 s: dashboard shows TELEMETRY LOST, robot keeps
      running, dashboard recovers automatically.
- [ ] Kill the bridge (Ctrl-C): robot behaviour unchanged.
- [ ] Map, pose, paths and goal line up with RViz.
- [ ] Publisher counts are 1 on `/scan`, odometry and `/map` (no other robot on our domain).

## Rollback

Ctrl-C the bridge; optionally `rm -rf ~/lite3-monitor`. Nothing else was changed.
