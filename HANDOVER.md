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
| NUC integration | **Live on group8 (2026-11-23)**: bridge runs on the NUC in tmux, dashboard works from the team's Mac through the SSH tunnel, map-less profile. Daily procedure: `lite3-monitor/docs/STARTUP_MANUAL.md`. |

## Approvals

| Action | Approved? | By / date |
|---|---|---|
| SSH to NUC for read-only discovery (`discover-remote.sh`) | YES (done) | team ran it 2026-11-23 |
| Copy bridge to NUC (`deploy-bridge.sh` or `git clone` on the NUC) | YES | team, in chat, 2026-11-23 |
| pip install into the lite3-monitor `.venv` on NUC | YES | team, in chat, 2026-11-23 |
| Run bridge on NUC | YES | team, in chat, 2026-11-23 |
| Run read-only `pi_reporter` on the Raspberry Pi (group8pi), incl. serving stored scene-check pictures (`--scene-log`) | YES | team, in chat (Claude Code session on group8pi), 2026-11-26 |
| Node 22 for building/testing the dashboard, unpacked in `~/.local/node` on the Pi only | YES | team, in chat, 2026-11-26 |

Agents: do not perform an action until its row says YES.

## Known robot facts (confirmed by the team, 2026-11-23)

- NUC hostname: `group8` · `ROS_DOMAIN_ID=8` (set in the team's shell environment,
  not visible to non-interactive SSH shells) · RMW: default · Python 3.10.12 ·
  workspace `~/lite3_ws` · NUC has internet (pip install possible).
- Raspberry Pi added: hostname `group8pi`, on the same Wi-Fi (RI_Network), powered by
  USB-C from the NUC (under-voltage risk). Its address lives only in the NUC's
  git-ignored `bridge/config/local.yaml` (`peers`). The team shared the Pi password in
  chat; it was NOT stored anywhere - recommend they change it and use SSH keys.
- SSH from the team's Mac works. IP address and username are kept only in each
  laptop's git-ignored `scripts/*/robot.env`, never in this repo.

## Discovery findings — group8, 2026-11-23 (`lite3-monitor/docs/discovery/discovery-20261123-151619.md`)

- Domain 8 contains ONE node: `/lite3_domain_bridge_8` (a ROS domain bridge). It
  republishes 31 topics from the robot's internal domain into domain 8. The robot's
  real nodes run on another domain and are not visible here.
- Available on domain 8: `/leg_odom2` (Odometry, 200 Hz), `/leg_odom`
  (PoseWithCovarianceStamped, 200 Hz), `/imu/data` 200 Hz, `/joint_states` 200 Hz,
  `/handle_state` (Twist, 200 Hz, meaning unknown), `/us_publisher/ultrasound_distance`
  (Float64, 200 Hz), `/livox/points` + `/livox/lidar` + `/livox/imu` (14.7 Hz), Orbbec
  camera topics (~30 Hz), five `/sensor_status/*_isalive` Bool topics (2 Hz), static TF
  only (base_link → camera_link, livox_frame).
- NOT present on domain 8 at discovery time: `/map`, `/scan`, dynamic `/tf`
  (no odom → base_link, no map → odom), any navigation / exploration topics or
  actions, any terrain-hazard cloud. Either SLAM/nav were not running, or they run
  on another domain and are not bridged into domain 8 (open question 9).
- Consequence today: dashboard pose = `/leg_odom2` in its odom frame (no map
  alignment), health + sensor flags work; map / paths / goal / frontiers stay empty.
- Read-only evidence from the discovery run: `/parameter_events` had 0 publishers
  and `/rosout` only the domain bridge, i.e. the monitor's node created neither.
- Config updated accordingly (200 Hz expectations, `/tf` not required, cheap
  camera/Livox liveness topics, `status_flags`, expected node = domain bridge).

## Robot TF finding (2026-11-23, while navigation/LIO was running)

`ros2 run tf2_ros tf2_echo map base_link` on group8 printed a CONSTANT
`map -> base_link = (0.030, -0.020, 0)` "At time 0.0", i.e. a **static** transform
(`/tf_static`, re-sent by the domain bridge every ~2.5 s), while a **moving**
`map -> base_link` also arrives on `/tf` (pose ~5.7, -2.2). Two parents for the same
child is a TF setup problem on the robot side: tf2 users (tf2_echo, possibly RViz or
navigation on domain 8) may see the robot pinned near the origin. The monitor now
keeps them apart, prefers the moving one while fresh, and reports the conflict in the
TF panel. Team: find which launch file publishes the static `map -> base_link`
(likely a placeholder static_transform_publisher) - their decision whether to remove it.

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
9. **Where do SLAM / navigation / exploration run, and on which ROS domain?** On the
   computer where RViz2 shows the map, what is `echo $ROS_DOMAIN_ID`, and which topic
   names does RViz2's Displays panel use for the map, robot pose/TF, paths and the
   terrain hazard cloud? Were they running during discovery? (Bridging more topics
   into domain 8 would be a change to the robot setup — the team's decision, not this
   project's.)
11. **Robot temperatures** (motors / body / battery): which topic publishes them, on which
    domain, and in what unit? The team reports the robot overheats often. Once known, add
    it to `temperature_topics` (and bridge it into domain 8 if needed - team decision).
10. What do `/handle_state` (Twist, 200 Hz) and `/us_publisher/ultrasound_distance`
    represent (e.g. joystick command, nearest-obstacle distance in metres)?

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
- 2026-11-23 · Claude Code · Analysed the first real discovery report (see
  "Discovery findings"). Tuned `bridge/config/default.yaml` to group8 (200 Hz
  odom/IMU/joints, `/tf` optional, camera_info + livox/imu liveness, expected node).
  New `status_flags` config + `status_flag` role: robot "is alive" Bool topics shown
  as chips in the TF & diagnostics panel; false ⇒ error; exempt from decode
  throttling (a quick true→false must not be skipped — caught by the new test).
  Simulator now emits rates from config and the flags (IMU flag false during the
  IMU fault). 28 bridge tests, typecheck, build, read-only audit pass; browser check
  of the chips against the simulator. Blocked on open question 9 for map/nav data.
- 2026-11-23 · Claude Code · Team decision: run WITHOUT the map. New robot profile
  `bridge/config/group8.yaml` (identity group8/8, `layers.map.enabled: false`,
  `frames.tf_required: false`, absent roles' candidates emptied so nothing is
  reported missing). `--config` can be repeated (default → profile → local.yaml);
  `scripts/nuc/start-bridge.sh` loads `config/$LITE3_PROFILE.yaml` (default group8).
  TF optional: odometry pose without TF is a note, not a fault (`tf.required`,
  `tf.notes` in telemetry). Dashboard draws trail/robot in the pose frame when there
  is no map, fits to the trail, panel reads "Live position (no map)". Simulator
  `odom_only` (via the profile) mimics group8. `start-sim --profile group8` /
  `-Profile group8`. 30 bridge tests, typecheck, build, audit; browser check: clean
  event log, trail fitted, TF "not used", sensor chips green.
- 2026-11-23 · Claude Code · First live run on the real robot: bridge installed on the
  NUC via `git clone` + `scripts/nuc/install.sh` (no-sudo venv fallback added), runtime
  read-only audit passed on real rclpy ("0 publishers, 0 services, 0 clients"),
  subscriptions created (odometry, IMU, joints, TF, sensor flags, camera/Livox info),
  team confirmed the website works. Starting a second bridge crashed on the busy port →
  now exits early with a clear message. Wrote `docs/STARTUP_MANUAL.md` (daily start,
  checks, shutdown, troubleshooting, update, reinstall). Still to verify on the robot:
  `ros2 node info /lite3_monitor_readonly` output and bridge CPU (`top`) — see
  NUC_INTEGRATION.md checklist.
- 2026-11-23 · Claude Code · Compute & data monitoring (team request). New
  `bridge/lite3_bridge/system_stats.py`: NUC CPU (total + per process, % of one core
  like top), memory, temperatures (hwmon/thermal), load, disk, grouped into
  components by `compute.components` patterns in default.yaml; reads /proc and /sys
  only, sends process names only (no command lines); simulated on macOS / in sim.
  Sampled every 2 s off the event loop, sent as `health.compute`. Per-topic
  `bytes_per_s` from raw message sizes (only for topics already subscribed - heavy
  camera / point-cloud topics stay unsubscribed). Ultrasound topic added to health.
  `discover.py` reports kB/s; `discover-remote.sh 8 --heavy` / `-Heavy` measures heavy
  topics once. Dashboard: "Data" column in System health, new "NUC compute" and
  "Data per topic" panels. 33 bridge tests, typecheck, build, audit; browser check
  with the group8 simulator. Component patterns are guesses until checked on the NUC
  (`top` names of the camera / Livox / navigation processes).
- 2026-11-23 · Claude Code · Temperatures (team: "robot overheats quite a fair bit").
  NUC: thresholds `compute.temperature.warn_c/crit_c` (80/90), CPU clock + kernel
  thermal-throttle counters in `health.compute`. Robot: new `temperature_topics` config
  + `temperature` role (sensor_msgs/Temperature or std_msgs/Float32/64, optional
  `scale`, per-topic warn/crit) - EMPTY for group8, nothing found on domain 8 (open
  question 11); simulator adds two labelled simulated robot temps when empty.
  Dashboard: "Temperatures" graph panel (NUC + robot series, 1-30 min window, warn
  line, value tiles), `NUC °C` and `Robot °C` pills in the top bar, thermal events with
  3 °C hysteresis (`web/src/lib/thermal.ts`; first browser run showed flapping without
  it), throttling start/stop as two events (was one per second), temps + NUC CPU in
  recorded samples, history detail chart and summary/compare rows. 34 bridge tests,
  5 web tests, typecheck, build, audit; browser check through a simulated heat episode.
- 2026-11-23 · Claude Code · One-command start (team request): `scripts/mac/start-all.sh`
  and `scripts/windows/start-all.ps1` stream `scripts/nuc/ensure-bridge.sh` to the NUC
  (`bash -s`): if `/healthz` answers, nothing is started; else the bridge is started in
  tmux session `monitor` (new window if the session exists; nohup + ~/lite3-bridge.log
  without tmux) with ROS_DOMAIN_ID from robot.env, waiting up to 25 s and printing the
  bridge output on failure. It only manages lite3_bridge, never robot nodes. Then
  start-robot runs. start-robot now rebuilds the dashboard when `git rev-parse HEAD`
  differs from `.next/lite3-build-rev`, and refuses (with a fix) when the local tunnel
  port is busy (team hit the endless password loop). Mac: `nuc_path` keeps `~` for
  NUC paths sourced from robot.env (bash expanded them to the Mac home; also fixed in
  discover-remote). ensure-bridge tested locally with tmux (start, healthy re-run);
  PowerShell only via Windows CI.
- 2026-11-23 · Claude Code · Fixed "robot moves without control" seen live: the store
  kept one TF edge per child, so the fixed /tf_static map->base_link (0.03,-0.02)
  re-sent every ~2.5 s overwrote the moving /tf one and the pose teleported to the
  origin and back (diagonal lines, zigzags, inflated distance). Now separate dynamic
  and static edges (dynamic preferred while fresh), `tf_conflicts()` warning, and the
  MotionTracker detects pose jumps (`exploration.jump_threshold_m`, 1.0 m within 1 s):
  no distance, trail break (`null` in trail points), `pose_jumps` / `last_jump`,
  dashboard event + "N position jumps ignored". Also: first rate/bytes reading is no
  longer halved; the group8 simulator test no longer depends on machine speed (it
  failed on Windows CI). 36 bridge tests, 5 web tests, typecheck, audit.
- 2026-11-23 · Claude Code · Raspberry Pi monitoring. `peers.py` (NUC bridge): TCP
  connect to the peer's SSH port (no login, no credentials) for online/RTT; optional
  GET /stats from `pi_reporter.py`, which runs on the Pi with the standard library only
  (reads /proc, /sys incl. firmware `get_throttled` and rpi_volt alarm; no commands; GET
  /stats only; refuses to start without `--allow-from`, answers only those IPs).
  `health.peers` -> dashboard "Raspberry Pi" panel (online/RTT, hostname verification,
  power & throttling now / since boot with advice, temperature, CPU, memory, SD), `Pi …`
  pill, events (offline/online, under-voltage, throttling, overheating with hysteresis,
  wrong device), Pi temperature on the Temperatures graph. Simulator has a simulated Pi
  with periodic under-voltage and a short outage. 40 bridge tests (reporter end-to-end
  incl. allow-list refusal), web tests, typecheck, build, audit, browser check.
  Also noted from a new `ros2 node list`: Nav2 + slam_toolbox + laser_mapping +
  pointcloud_to_laserscan + lite3_terrain_monitor now run on domain 8; two nodes named
  `/rviz` (duplicate names). Next: re-run discovery with navigation running and re-enable
  map / nav / scan / terrain layers in the group8 profile.
- 2026-11-25 · Claude Code · Monitoring that needs no navigation: IMU posture (roll /
  pitch / tilt from orientation, or from gravity when orientation is absent; warn 20°,
  crit 35°, hysteresis), leg effort from /joint_states, ultrasound as a `range_topics`
  entry (/us_publisher/ultrasound_distance, metres, 4.5 m = clear; warn 0.5, crit 0.25),
  command vs actual using /handle_state (Twist, robot velocity command - confirmed by
  team echo), robot log panel from /rosout (rate-capped 40/s, last 15 s in health,
  de-dup by id+t, ERROR+ also as events). Navigation roles are `optional_roles`: idle /
  "inactive" when absent, auto-subscribed when present; group8 map layer re-enabled.
  Simulator: stumbles, efforts, ultrasound ray-cast, logs. 44 bridge tests, web tests,
  typecheck, audit, browser check.
- 2026-11-25 · Claude Code · "Pi link" panel (team request: is the Pi live, what does it
  send / receive). pi_reporter now adds `net`: bytes & packets per second per interface
  from /proc/net/dev, open TCP/UDP connections and listening ports from /proc/net/{tcp,
  udp}{,6} with the owning process name via /proc/<pid>/fd (like `ss -tunap`), sorted
  NUC-first (allow-listed IPs = NUC). No message contents. Dashboard: big LIVE/OFFLINE,
  RTT, rx/tx kB/s + packets/s, 2-min graph, "talking to" list. The Pi has no ROS node on
  domain 8, so its ROS messages cannot be shown. 45 bridge tests (address decoding,
  reporter sees its own NUC connection), typecheck, audit, browser check.
- 2026-11-25 · Claude Code · Fix: a pose built only from STATIC transforms is no longer
  used as the robot position. After navigation stopped, the moving map->base_link aged
  out and the fixed /tf_static map->base_link (0.03,-0.02; age 0) would have been shown
  as a LIVE pose near the origin. Now ignored with a TF note; pose falls back to
  odometry. Test updated. Explained "POSE STALE" to the team (pose source older than
  staleness.pose_stale_s = 1 s; nav TF updates only ~2 Hz).
- 2026-11-25 · Claude Code · `scripts/nuc/start-bridge.sh`: checks the port before
  touching ROS. Our bridge running -> "ALREADY RUNNING (PID)" + hint, exit 0;
  `--restart` stops only `python -m lite3_bridge` processes (TERM, then KILL after 10 s)
  and starts the new code; a foreign program on the port -> shown via `ss`, never
  stopped, with steps to move to port 8775 (`LITE3_PORT`). Team kept hitting "port in
  use" after `git pull`. Tested all three paths locally.
- 2026-11-26 · Claude Code (on group8pi) · Pi perception panels (team request: see the Pi's
  detections, Claude scene checks and mission reports in this dashboard). Bridge: new optional
  roles `pi_detections` / `pi_scene_events` (std_msgs/String JSON, decoded, < 1 Hz; group8.yaml
  names `/group8pi/perception/detections` and `/scene_events`), `perception.py` (joins Claude
  requests by request_id + capture stamp; reads the robot's mission_reports.jsonl of the newest
  run folder, only when it changes) -> `health.perception`, `health.missions`. Pictures: GET
  `/api/pi/scene_image` relays a stored JPEG from `pi_reporter --scene-log` (validated inputs,
  cache of 40). Simulator produces both. Web: "Pi sees now", "Claude scene checks", "Mission
  reports" panels. Verified on the Pi: 51 bridge tests (6 new), read-only audit, typecheck,
  7 web tests (2 new), production build. Not yet verified: the live bridge on the NUC with these
  topics, and a browser check on the team's Mac.
