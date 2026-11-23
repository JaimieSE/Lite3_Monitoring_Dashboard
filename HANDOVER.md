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

## Known robot facts (confirmed by the team, 2026-11-23)

- NUC hostname: `group8` · `ROS_DOMAIN_ID=8` (set in the team's shell environment,
  not visible to non-interactive SSH shells) · RMW: default · Python 3.10.12 ·
  workspace `~/lite3_ws` · NUC has internet (pip install possible).
- SSH from the team's Mac works. IP address and username are kept only in each
  laptop's git-ignored `scripts/*/robot.env`, never in this repo.

## Open questions for the team

1. ~~NUC address, user, hostname~~ — answered (see Known robot facts).
2. ~~`ROS_DOMAIN_ID`~~ — answered: 8.
3. ~~`RMW_IMPLEMENTATION`~~ — default. Whether `ROS_LOCALHOST_ONLY` is used: still unknown.
4. Which SLAM (slam_toolbox / cartographer / other), navigation (Nav2?) and
   exploration (explore_lite / custom) packages run, and their topic names.
5. Odometry topic and type: `/odom`, `/leg_odom`, `/leg_odom2`? Body frame name
   (`base_link`, `base`, `body`, `trunk`)?
6. ~~Internet / Python~~ — answered: yes, 3.10.12.
7. Arena area in m² (to report coverage % instead of explored area).
8. Any custom message types in `lite3_ws` that carry useful state (battery, gait, mode)?

## Next tasks (in order)

- [x] ~~BUG: simulator robot stalls~~ — fixed 2026-11-21 (see Agent log).
- [ ] **Codex: independent safety review** of the bridge (read-only guarantees, load on
      the NUC, stale-data handling, bypasses of `tools/check_readonly.py`). Write findings
      under "Review findings" below; do not change code in the review pass.
      Include the v2 additions: `GET /api/clock` (+ CORS allow-list) and the optional
      `/ws/map` stream.
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
- 2026-11-21 · Claude Code · Protocol v2 (user request): link-delay measurement and an
  on/off map stream. `GET /api/clock` (no input, CORS only for the dashboard origin)
  probed at 1 Hz → RTT, clock offset, one-way telemetry delay; shown in top bar,
  Live trends chart, health footer, recorded in history (+ summary median/p95, CSV).
  Occupancy grid moved to its own socket `/ws/map`; the Map stream button
  opens/closes it (remembered per browser), bridge encodes/sends nothing without map
  clients but still reports coverage stats in `health.map.stats`. Bridge-wide off
  switch `layers.map.enabled` / `--no-map-stream`. Simulator `--sim-latency-ms`.
  Verified: 26 bridge tests (new: map stream split, stats without stream, config
  disable, clock CORS), 3 web tests, typecheck, build, read-only audit, browser run
  with 120 ms simulated delay (RTT read 243 ms; map off → 0 map clients on bridge,
  known area still updating; preference persisted across reload; back on → map
  restored).
- 2026-11-21 · Claude Code · Windows support for team-mates: `scripts/windows/`
  (install, start-sim, start-robot with auto-reconnecting tunnel, discover-remote),
  `.gitattributes` (LF for sh/py), Windows CI job (PowerShell 5.1: parse check,
  install.ps1, robot.env parsing, bridge tests, web build, live smoke test of
  bridge + dashboard). `docs/TEAM_SETUP.md` covers Mac/Windows, SSH keys and
  multiple viewers. `server.max_clients` raised 4 → 6; new test for concurrent
  viewers and the limit. PowerShell scripts were NOT run locally (no PowerShell
  in this container) — verified via the Windows CI job: run 44934186211 passed
  (parse, install.ps1, robot.env parsing, bridge tests, web build, smoke test).
  Not yet tried on a team-mate's actual laptop.
- 2026-11-23 · Claude Code · Team confirmed hostname `group8`, domain 8. Fixed a
  discovery bug found before first use: the remote discovery shell is
  non-interactive, so `~/.bashrc` (where the team sets ROS_DOMAIN_ID) is not loaded
  and discovery would have inspected domain 0. Both `discover-remote.sh` and
  `.ps1` now export `ROS_DOMAIN_ID` from `EXPECTED_DOMAIN_ID` in robot.env (required)
  and abort unless the remote `hostname` equals `EXPECTED_HOSTNAME`.
  Note for start-bridge: the bridge already refuses to start if ROS_DOMAIN_ID does
  not match `identity.expected_ros_domain_id`, so it must be run from a shell where
  the team's environment is loaded (or with `ROS_DOMAIN_ID=8` exported).
