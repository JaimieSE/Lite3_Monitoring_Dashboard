# AGENTS.md — instructions for coding agents (Codex, Claude Code, …)

This repository is shared between humans and multiple coding agents.
**The repository is the communication channel**: read `HANDOVER.md` first,
and append to its *Agent log* before you finish a work session.

## Project

`lite3-monitor/` — read-only monitoring dashboard for a DEEP Robotics Lite3
(ROS 2 Humble on an Ubuntu NUC; dashboard on macOS). See `lite3-monitor/README.md`.

## Hard safety rules (never violate, never "temporarily" relax)

1. The bridge must NEVER publish, call services/actions, create action clients,
   touch parameters, or start/stop/modify robot nodes. Subscriptions + passive
   graph queries only.
2. Never modify the robot's `lite3_ws` or anything outside `lite3-monitor/` on the NUC.
3. The dashboard never sends data to the bridge; the bridge ignores inbound data.
4. Do not SSH into, deploy to, or install anything on the NUC unless the human
   has approved it in `HANDOVER.md` (see "Approvals"). Never guess IPs,
   usernames, ROS domain IDs or custom message types.
5. Never present stale data as live (see docs/ARCHITECTURE.md "freshness").
6. `python3 lite3-monitor/tools/check_readonly.py` must pass. If you need a new
   rclpy call, add it to the allow-list only if it is passive, and explain why in
   `HANDOVER.md`.

## Commands

```bash
# bridge (Python ≥ 3.10; NUC is Python 3.10 – no 3.11+ only syntax)
cd lite3-monitor/bridge
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m lite3_bridge --sim           # simulator on ws://127.0.0.1:8765/ws

# web (Node ≥ 20)
cd lite3-monitor/web
npm ci && npm run typecheck && npm test && npm run build
npm run dev                                       # http://127.0.0.1:3000

# safety audit
python3 lite3-monitor/tools/check_readonly.py
```

CI (`.github/workflows/ci.yml`) runs all of the above.

## Conventions

- Protocol changes: update `bridge/lite3_bridge/state.py|server.py`,
  `web/src/lib/types.ts` **and** `docs/PROTOCOL.md` together.
- Config: new topics/thresholds go in `bridge/config/default.yaml` as *candidates*,
  never hard-coded names.
- Status colours (good/warn/serious/crit) are reserved for health; data series use
  the categorical slots `s1…s7` (see `web/src/app/globals.css`). Every status uses
  icon/shape + text, never colour alone.
- Keep the bridge dependency-light (fastapi, uvicorn, websockets, PyYAML; numpy not required).
- Commit messages: imperative mood, explain *why*.
