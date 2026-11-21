# HANDOVER — shared status board

Read this first. Update it (status, open questions, log) at the end of every
work session so the next human or agent (e.g. Codex) can continue.

## Current status (2026-11-21)

| Area | State |
|---|---|
| Repository inspection | Done. Repo was empty (README only). `lite3_ws` is **not** in this repo and the NUC was not contacted. |
| `lite3-monitor/bridge` (FastAPI + rclpy, read-only) | Implemented. Sim mode fully tested; ROS mode tested only against a **fake rclpy** (`tests/test_ros_source_fake.py`). Not yet run on real ROS 2. |
| Simulator | Implemented (frontier exploration on a random floor plan, injected faults, optional link dropouts). |
| Dashboard (Next.js 15, TS, Tailwind) | Implemented: Live page (map, cards, trends, health, TF/diagnostics, events), History page (list, detail, compare ≤4, CSV/JSON export). Builds; screenshots in `lite3-monitor/docs/img/`. |
| Scripts | macOS: install, start-sim, start-robot (auto-reconnect tunnel), discover-remote (zero-footprint), deploy-bridge. NUC: install (venv), start-bridge. NUC/robot scripts **never run yet**. |
| Safety | Static audit (`tools/check_readonly.py`), runtime audit in `RosSource._audit`, loopback bind, identity checks. |
| NUC integration | **Blocked – awaiting approval + details** (see below). |

## Approvals

| Action | Approved? | By / date |
|---|---|---|
| SSH to NUC for read-only discovery (`discover-remote.sh`) | NO | |
| Copy bridge to NUC (`deploy-bridge.sh`) | NO | |
| pip install into `~/lite3-monitor/.venv` on NUC | NO | |
| Run bridge on NUC | NO | |

Agents: do not perform an action until its row says YES.

## Open questions for the team

1. NUC IP/hostname on the school Wi-Fi, SSH user, and the NUC's `hostname` output.
2. Our `ROS_DOMAIN_ID` (if it is the default 0, other robots on the Wi-Fi may share
   it — consider asking the team to set a unique one; this project will not change it).
3. `RMW_IMPLEMENTATION` and whether `ROS_LOCALHOST_ONLY` is used.
4. Which SLAM (slam_toolbox / cartographer / other), navigation (Nav2?) and
   exploration (explore_lite / custom) packages run, and their topic names.
5. Odometry topic and type: `/odom`, `/leg_odom`, `/leg_odom2`? Body frame name
   (`base_link`, `base`, `body`, `trunk`)?
6. Does the NUC have internet access for `pip install`? Python version?
7. Arena area in m² (to report coverage % instead of explored area).
8. Any custom message types in `lite3_ws` that carry useful state (battery, gait, mode)?

## Next tasks (in order)

- [x] ~~BUG: simulator robot stalls~~ — fixed 2026-11-21 (see Agent log).
- [ ] **Codex: independent safety review** of the bridge (read-only guarantees, load on
      the NUC, stale-data handling, bypasses of `tools/check_readonly.py`). Write findings
      under "Review findings" below; do not change code in the review pass.
- [ ] (Human) Answer the questions above and grant discovery approval.
- [ ] Run `scripts/mac/discover-remote.sh`, commit report to `lite3-monitor/docs/discovery/`.
- [ ] Tune `bridge/config/default.yaml` candidates/rates/frames to the discovered graph; add `expected_nodes`.
- [ ] (After approval) deploy, install, run; complete the checklist in `docs/NUC_INTEGRATION.md`
      — especially confirm `ros2 node info /lite3_monitor_readonly` shows no publishers
      and whether rclpy emitted a `/parameter_events` message at startup.
- [ ] If custom Lite3 state messages exist (battery, motor temps, gait), add a read-only role + card.
- [ ] Optional: store a final map snapshot (PNG) with each history session.
- [ ] Optional: Playwright smoke test in CI against the simulator.

## Review findings

_(empty — to be filled by the reviewer)_

## Decisions log

- Single bridge codebase serves both sim and ROS mode (identical protocol), so
  the dashboard is tested end-to-end without a robot.
- Latest-value store + per-client single slots instead of queues ⇒ bounded memory,
  never a backlog of stale data.
- Role/candidate topic resolution: nothing is hard-wired; missing topics are reported.
- Ages measured at receipt with monotonic clocks (bridge) and browser clock (link),
  never from ROS header stamps.
- History stored as JSON files on the Mac via Next.js API routes (no database).
- Charts are a small in-house canvas component (no chart library dependency).

## Agent log (append newest at the bottom)

- 2026-11-21 · Claude Code · Initial implementation of bridge, simulator,
  dashboard, scripts, docs, tests, CI. Verified: 15 bridge tests, 2 web tests,
  typecheck, production build, read-only audit; visual check of live / telemetry
  lost / reconnect / history in Chromium against the simulator. Not verified: real
  ROS 2 / NUC behaviour, macOS shell scripts on an actual Mac (bash 3.2 compatible
  by design), Safari rendering.
  Known open bug: simulator robot stalls (see Next tasks). Dashboard/bridge correctly
  report it as STALLED, so this only affects the demo, not monitoring logic.
- 2026-11-21 · Claude Code · Fixed the simulator stall. Root causes: (1) the scan
  ray-cast stepped in half-cells and could slip past obstacle corners, so the map
  missed obstacles; (2) when the robot drifted into the inflation margin, A* freed
  cells touching walls and allowed diagonal corner cutting, so paths ran into corners;
  (3) a collision just zeroed speed forever and nothing replanned. Fixes in `sim.py`:
  exact DDA ray traversal, bumper-style recovery (mark obstacle, reverse 1.5 s, replan),
  no-progress watchdog (6 s → blacklist goal, replan; disabled during the injected
  "stuck" fault so that stall stays visible), no corner cutting, frontier count excludes
  blacklisted frontiers. Loop body moved to `SimSource.tick(now)` so tests use a
  simulated clock. New `tests/test_sim.py` (seeds 7–11): > 15 m in 120 s; exploration
  completes with > 95 % of body-reachable floor explored; injected stall never aborted.
  Verified: 23 bridge tests, read-only audit, real-time run with dashboard (93 m in
  3 min, exploration complete, bridge ~2 % CPU). Simulator only; no protocol change.
