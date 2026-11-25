# Safe operation: read-only guarantees

This project must never influence the robot. These rules are non-negotiable for
humans and coding agents alike:

- NEVER publish ROS 2 messages (including `/cmd_vel`, goals, initial poses).
- NEVER call services or actions, create action clients, or cancel goals.
- NEVER get/set/declare parameters on other nodes.
- NEVER start, stop, restart or modify existing nodes, launch files or `lite3_ws`.
- NEVER execute commands received from the dashboard. The bridge ignores all inbound data.
- Do not deploy or install anything on the NUC without the team's explicit approval.

## How it is enforced

| Layer | Mechanism |
|---|---|
| Static audit | `tools/check_readonly.py` (AST): forbids `create_publisher`, `create_client`, `create_service`, `ActionClient/Server`, `call/call_async`, `send_goal*`, `*parameter*` mutation, `publish`, `subprocess`, `os.system/popen`, `exec/eval`, non-GET HTTP routes; only an allow-list of `node.*` methods may be called. Web: forbids `.send(` on sockets and process execution. Runs in tests and CI. |
| Runtime audit | `RosSource._audit()` runs at startup and after every graph scan: if the node owns **any** publisher, service or client, the bridge raises and exits. |
| Node options | `enable_rosout=False`, `start_parameter_services=False`. rclpy's built-in `/parameter_events` publisher is destroyed right after node creation (before any subscription exists). The node declares no parameters. |
| Network | Bridge binds `127.0.0.1` only and refuses other addresses without `--allow-remote-bind`. Access only via SSH port forwarding. |
| Protocol | WebSockets are output-only; inbound frames are discarded unread. HTTP is GET-only. The dashboard's only requests are the GETs above: `/api/clock` (1 Hz link-delay probe, no parameters) is the only one it makes routinely. Pictures in the "Claude scene checks" panel are plain image GETs (`/api/pi/scene_image`) of files the Pi already stored; the bridge relays them from `pi_reporter` and never asks the Pi to capture anything. Switching the map layer on/off is done by opening/closing the separate `/ws/map` socket — no message is ever sent to the bridge, and nothing on the ROS side changes. |
| Identity | Bridge refuses to start if `identity.expected_hostname` / `expected_ros_domain_id` are set and do not match. The dashboard hides all robot data and shows **IDENTITY MISMATCH** if the bridge's hostname/domain differs from `LITE3_EXPECTED_*`. Topics that should have one publisher are flagged when more appear (another robot on the same domain). |
| Resource use | Raw subscriptions, throttled decoding, best-effort QoS for sensors, capped TF decoding, map only on change, `nice -n 10`, bounded per-client slots. Point clouds are not subscribed by default. |

### QoS notes (why subscribing cannot disturb publishers)

Sensor topics use **best-effort** subscriptions: a slow or vanished subscriber
cannot apply back-pressure to a publisher. Latched/rare topics (map, tf_static,
goal, nav status, frontiers, plans) use **reliable** only when every publisher
offers reliable, with `KEEP_LAST` depth 1–5, so a reliable writer keeps
overwriting its history instead of blocking. `TRANSIENT_LOCAL` is requested only
when all publishers offer it (otherwise it would be incompatible).

### Known residual effects (honest list)

- A subscriber is visible in the ROS graph (`ros2 node list` shows
  `/lite3_monitor_readonly`) and DDS discovery traffic increases slightly.
- Each subscribed topic is delivered to one more reader (CPU/network cost on the
  NUC; measured budget in ARCHITECTURE.md). Heavy topics are excluded by default.
- `rclpy.init()` creates a ROS context; on some rclpy versions creating the node
  may announce its own `use_sim_time` parameter on `/parameter_events` before the
  built-in publisher is destroyed. This only describes the monitor node itself and
  cannot change any other node. **To verify on the NUC** (see HANDOVER.md).

## What to do if in doubt

Stop the bridge (Ctrl-C in its tmux pane). The robot is unaffected by the
bridge stopping. Never "fix" a robot-side problem from this project.
