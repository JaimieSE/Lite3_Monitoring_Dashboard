# WebSocket protocol v2

Endpoints (through the SSH tunnel in live mode):

- `ws://127.0.0.1:8765/ws` — main stream: `hello`, `telemetry`, `health`, `paths`.
- `ws://127.0.0.1:8765/ws/map` — optional map stream: `hello` (stream `map`) then `map`
  messages. The dashboard opens it only while the map layer is switched on; with
  no map clients the bridge does not encode or send the grid. Rejected with close
  code 1008 when `layers.map.enabled: false`.

v2 changes: map moved to `/ws/map`; `hello.stream`, `hello.layers`; `health.map`
gained `width/height/resolution/stats`; `health.bridge` gained `map_clients`,
`map_stream_enabled`; new `GET /api/clock`.

Direction: **bridge → dashboard only.** Anything a client sends is read and
discarded (only to detect disconnects). The dashboard never calls `send()`;
`tools/check_readonly.py` fails the build if it does.

Every message is a JSON object with a `type`. Types and TypeScript definitions:
`web/src/lib/types.ts` (keep in sync with `bridge/lite3_bridge/state.py` and
`server.py`). Bump `PROTOCOL_VERSION` in `server.py` on breaking changes.

| type | when | contents |
|---|---|---|
| `hello` | on connect (both streams) | stream (`main`/`map`), layers {map: {enabled}}, protocol, bridge_version, mode (`sim`/`ros`), `read_only: true`, identity (hostname, machine fingerprint, ROS_DOMAIN_ID, RMW, expected values, verified, warnings), frames, rates, staleness, arena_area_m2 |
| `telemetry` | 10 Hz | `pose` {x, y, yaw, frame, source tf/odometry, age_s, valid, map_frame} \| null; `velocity` {linear, lateral, angular, speed, age_s, valid, source}; `cmd_vel` (observed); `nav` {status, status_age_s, goal, distance_to_goal_m, global_path_length_m}; `exploration` {state, state_source, frontier_count, distance_travelled_m, runtime_s, stationary_s, stalled, stalled_for_s, stall_events, moving, pose_jumps, last_jump {distance_m, age_s, from, to}}; `tf` {base_frame, chain[{parent, child, static, age_s}], errors[], ok, required, notes[]} (`required: false` ⇒ missing TF is reported in `notes`, not `errors`) |
| `health` | 1 Hz | `topics[]` {role, name, type, decoded, expected_hz, min_hz, rate_hz, age_s, total, publishers, publisher_nodes, status ok/warn/error/missing/idle, note, value, label} (`value`/`label` are set for role `status_flag`: robot "is alive" std_msgs/Bool topics; `false` ⇒ status error; `bytes_per_s` = serialized bytes received per second, null when unknown; `temp_c`, `temp_warn_c`, `temp_crit_c` for role `temperature`: robot temperature topics from `temperature_topics`); `roles` {role → resolved topic \| null}; `missing_roles`; `nodes` {count, names, missing_expected}; `diagnostics` {ok, warn, error, stale, items[], age_s} \| null; `map` {version, age_s, stale, width, height, resolution, stats} \| null (stats are sent even when nobody streams the grid); `compute` {simulated, cores, cpu_total_pct (whole machine), load1, mem_used_mb, mem_total_mb, temps[{label, c}], temp_max_c, temp_warn_c, temp_crit_c, cpu_mhz, cpu_max_mhz, throttle_count, disk_free_gb, components[{name, cpu_pct (% of one core), rss_mb, processes}], top[{name, component, cpu_pct, rss_mb}]} \| null (NUC process stats from /proc; process names only, never command lines); `peers[]` {name, online, rtt_ms, banner, last_seen_age_s, stats_configured, stats {hostname, model, uptime_s, throttled_raw, throttle{under_voltage_now/occurred, throttled_now/occurred, freq_capped_now/occurred, soft_temp_limit_now/occurred}, cpu_total_pct, temps, temp_max_c, mem_*, disk_free_gb, disk_total_gb, cpu_mhz, cpu_max_mhz} \| null, stats_error, expected_hostname, identity_ok, temp_warn_c, temp_crit_c} (helper computers such as the Raspberry Pi); `source`; `bridge` {clients, map_clients, map_stream_enabled, dropped_frames, uptime_s, tf_dropped, mode, map_bytes} |
| `paths` | 1 Hz | `global`, `local` {frame, points [[x,y]…] ≤ 300, age_s, length_m} \| null; `frontiers` {count, points, frame, age_s} \| null; `trail` {frame, points} (a `null` entry = break at a pose jump; never draw across it) |
| `map` (on `/ws/map` only) | on change, ≥ 2 s apart | frame, resolution, width, height (cropped), full_width, full_height, origin {x, y, yaw} of the crop, `encoding: "zlib+base64"`, `data`, `stats` {total/free/occupied/unknown cells, known_area_m2, free_area_m2, known_fraction, coverage_pct}, version |

Map cells: `255` unknown, `0` free, `1..100` occupancy probability (≥ 65 drawn as occupied).
Row 0 is at `origin.y` (ROS convention); the browser inflates with
`DecompressionStream('deflate')`.

Ages (`age_s`) are seconds since the bridge *received* the data (monotonic clock).

## HTTP (GET only)

- `/healthz` → `{ok, mode, read_only, clients}`
- `/api/clock` → `{t}` bridge wall-clock seconds. Takes no input. The dashboard calls it
  at 1 Hz to measure round-trip link delay and the bridge↔Mac clock offset
  (NTP-style: offset from the lowest-RTT recent sample). CORS is allowed only for
  `server.dashboard_origins`. Telemetry one-way delay =
  browser receipt time − (`telemetry.server_time` − offset).
- `/api/status` → identity, mode, version, uptime, roles, source status
- `/api/discovery` → ROS graph (nodes, topics+types), TF frames and edges, roles

There are no POST/PUT/PATCH/DELETE routes on the bridge.
