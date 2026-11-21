# Architecture

## Components

| Component | Runs on | Code |
|---|---|---|
| Telemetry bridge | NUC (ROS mode) or Mac (sim mode) | `bridge/lite3_bridge/` |
| ROS source (subscriptions only) | NUC | `ros_source.py` |
| Simulator source | Mac | `sim.py` |
| Latest-value store + motion analytics | bridge | `state.py` |
| WebSocket / HTTP server | bridge | `server.py` |
| Map encoder (crop + zlib + base64) | bridge | `mapcodec.py` |
| Read-only discovery report | NUC (streamed over SSH) | `discover.py` |
| Dashboard | Mac | `web/src/app`, `web/src/components` |
| Telemetry client (receive-only WS, reconnect, freshness) | browser | `web/src/lib/client.ts` |
| Session recorder | browser → `/api/history` → `web/data/history/*.json` | `web/src/lib/recorder.ts`, `historyStore.ts` |

## Data flow

```
ROS topics ──(raw subscriptions, best-effort unless latched/reliable needed)──▶ callback
   callback: count message (rate) ─▶ for decoded roles, deserialize at ≤ decode_hz ─▶ TelemetryStore (latest value)

Broadcaster (asyncio, one task):
   every 1/telemetry_hz (10 Hz): build telemetry snapshot (pose from TF, velocity, nav, exploration, tf)
   every 1/health_hz    (1 Hz):  topic rates/status, nodes, diagnostics, map age, bridge stats
   every 1/paths_hz     (1 Hz):  global/local path, frontiers, trail
   when map version changes (≥ map_min_interval_s apart): encode in a worker thread, send once

Per client: one slot per message type ("latest wins"), sent in priority order
hello > telemetry > health > paths > map; 5 s send timeout. No unbounded queue exists.
```

The ROS executor thread never waits on the network, and the network never
waits on ROS: they only share the lock-protected store. If the dashboard,
browser, tunnel or Wi-Fi disappear, the robot side is unaffected; the bridge
simply has zero clients. If the bridge itself crashes, the robot's nodes do not
notice (a subscriber leaving is a normal DDS event).

## Optional map stream and link delay

- The occupancy grid is the largest message (tens of KB). It travels on its own
  socket (`/ws/map`). The **Map stream** button on the map toggles that socket; the
  choice is remembered per browser. Off ⇒ no grid is encoded or sent (bridge
  CPU and Wi-Fi saved), the map panel keeps drawing robot, trail, paths, goal and
  frontiers on a plain grid, and explored-area / coverage numbers keep updating
  from cheap cell counts in the `health` message. `layers.map.enabled: false` (or
  `--no-map-stream`) disables it at the bridge for everyone.
- The ROS subscription to `/map` is kept either way: it is ~1 small message every
  few seconds and keeps the latched map available instantly when switched back on.
- Link delay: 1 Hz `GET /api/clock` → round trip (median of last 5) shown in the
  top bar (green < 150 ms, amber < 500 ms, orange above; red when probes fail),
  the clock offset, and the estimated one-way telemetry delay. Charted in Live
  trends and recorded per sample in history (`link_rtt_ms`, `transit_ms`,
  `map_stream`). The simulator can add delay: `--sim-latency-ms 150`.

## Pose, freshness and "never show stale as live"

- Pose comes from TF: the chain `map → … → base` is composed from the latest
  edges (`frames.base` candidates). Fallback: `odom → base` (shown as *not on the
  map*), then the odometry message.
- All ages use the **bridge's monotonic clock at receipt**, never ROS header
  stamps (immune to clock skew between NUC and other computers).
- `pose.valid` is false if the newest dynamic TF edge is older than
  `staleness.pose_stale_s`.
- The browser measures link freshness with its own clock: > 1.5 s without
  telemetry ⇒ STALE (amber), > 3.5 s or socket closed ⇒ TELEMETRY LOST (red).
  A socket with no bytes for 6 s is force-closed (half-open TCP after Wi-Fi loss)
  and reconnection resumes with jittered backoff 0.5 → 5 s.
- The robot is drawn live only when *link live* ∧ *pose.valid* ∧ *identity OK*;
  otherwise it is a dashed grey "LAST KNOWN · Ns ago" outline. Cards grey out with
  a **NOT LIVE** tag. Charts insert gaps during outages. Recorded samples store
  `x/y = null` whenever the pose was not live.

## Exploration analytics (bridge-side, `MotionTracker`)

Updated at the telemetry rate from **valid** poses only:
- distance: sum of displacements ≥ `jitter_threshold_m`, jumps > 2 m ignored;
- trail: points ≥ `min_trail_step_m` apart, max `max_trail_points`;
- stationary: time since speed > `stationary_speed_mps` (or turning);
- stalled: a nav goal is active or `/cmd_vel` is non-zero, but displacement over
  `stall_after_s` < 0.10 m;
- state: from `exploration_state` topic if configured, else inferred;
- frontier count: from a MarkerArray (spheres, else per-marker centroids) or
  PoseArray topic, if one exists.

Coverage: if `exploration.arena_area_m2` is set, coverage % = free area / arena
area. Otherwise the dashboard shows explored (known) area in m², because the
SLAM grid's extent is not the arena.

## Performance budget (NUC)

- Raw (undecoded) subscriptions for rate-only topics (`/scan`, `/imu/data`,
  `/joint_states`); point clouds are not subscribed unless added explicitly.
- Decoded topics are throttled to `rates.decode_hz` (20 Hz) except rare/latched
  ones (map, tf_static, goal, nav status). `/tf` decode is capped at 400 msg/s.
- Map: cropped to the known bounding box, zlib level 3, sent only on change and
  at most every 2 s; encoding runs off the event loop.
- Bridge runs under `nice -n 10`. Expected load: a few % of one core.
- Network to the Mac: ~10 KB/s telemetry + map bursts (tens of KB compressed).

## History storage

Browser samples 1 Hz while recording, events are appended as they occur, the
session JSON is POSTed every 10 s (and via `sendBeacon` on tab close) to the
local Next.js API, which validates it, recomputes the summary and writes
`data/history/<id>.json` atomically. Max 4 h of samples / 2000 events per session.
