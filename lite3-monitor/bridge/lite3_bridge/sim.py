"""Simulated telemetry source.

Runs a small 2D world: a quadruped explores an unknown floor plan using
frontier exploration, reveals a SLAM-like occupancy grid with ray casting,
and feeds the SAME TelemetryStore that the ROS source uses. No ROS needed,
so the whole dashboard can be developed on macOS.

Pure Python, no numpy. Map is 0.1 m/cell to keep CPU low.
"""
from __future__ import annotations

import heapq
import logging
import math
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

from .geom import quat_from_yaw, wrap_angle
from .state import TelemetryStore

log = logging.getLogger("lite3_bridge.sim")

RES = 0.10
W, H = 240, 160          # 24 m x 16 m
ORIGIN = (-4.0, -4.0)    # world coords of cell (0, 0)
UNKNOWN, FREE, OCC = 0xFF, 0, 100
SCAN_RANGE = 6.0
INFLATE = 3              # cells (0.3 m)

Cell = Tuple[int, int]


def w2c(x: float, y: float) -> Cell:
    return int((x - ORIGIN[0]) / RES), int((y - ORIGIN[1]) / RES)


def c2w(cx: int, cy: int) -> Tuple[float, float]:
    return ORIGIN[0] + (cx + 0.5) * RES, ORIGIN[1] + (cy + 0.5) * RES


class World:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.truth = bytearray(W * H)
        self._build()

    def _rect(self, x0: float, y0: float, x1: float, y1: float) -> None:
        a, b = w2c(min(x0, x1), min(y0, y1))
        c, d = w2c(max(x0, x1), max(y0, y1))
        for cy in range(max(0, b), min(H, d + 1)):
            for cx in range(max(0, a), min(W, c + 1)):
                self.truth[cy * W + cx] = OCC

    def _build(self) -> None:
        x0, y0 = ORIGIN
        x1, y1 = x0 + W * RES - 0.01, y0 + H * RES - 0.01
        t = 0.15
        # outer walls
        self._rect(x0, y0, x1, y0 + t)
        self._rect(x0, y1 - t, x1, y1)
        self._rect(x0, y0, x0 + t, y1)
        self._rect(x1 - t, y0, x1, y1)
        r = self.rng
        # interior partition walls with doorways
        for wx in (4.0, 11.0):
            door = r.uniform(-2.5, 7.5)
            self._rect(wx, y0, wx + t, door - 0.6)
            self._rect(wx, door + 0.6, wx + t, y1)
        hy = r.uniform(2.5, 5.0)
        for seg in ((x0, 4.0), (4.0 + t, 11.0), (11.0 + t, x1)):
            door = r.uniform(seg[0] + 1.0, seg[1] - 1.0)
            self._rect(seg[0], hy, door - 0.6, hy + t)
            self._rect(door + 0.6, hy, seg[1], hy + t)
        # clutter boxes (competition obstacles)
        for _ in range(9):
            cx, cy = r.uniform(x0 + 1.5, x1 - 1.5), r.uniform(y0 + 1.5, y1 - 1.5)
            if math.hypot(cx, cy) < 2.0:
                continue  # keep start clear
            sx, sy = r.uniform(0.3, 1.0), r.uniform(0.3, 1.0)
            self._rect(cx - sx / 2, cy - sy / 2, cx + sx / 2, cy + sy / 2)
        # clear start area
        a, b = w2c(-1.0, -1.0)
        c, d = w2c(1.0, 1.0)
        for cy in range(b, d + 1):
            for cx in range(a, c + 1):
                self.truth[cy * W + cx] = FREE

    def occupied(self, x: float, y: float) -> bool:
        cx, cy = w2c(x, y)
        if not (0 <= cx < W and 0 <= cy < H):
            return True
        return self.truth[cy * W + cx] == OCC


class Explorer:
    """Frontier exploration + A* on the known grid."""

    def __init__(self, world: World):
        self.world = world
        self.known = bytearray([UNKNOWN]) * (W * H)
        self.blacklist: List[Tuple[float, float]] = []
        self.frontier_centroids: List[Tuple[float, float]] = []

    def scan(self, x: float, y: float) -> None:
        """Ray cast with exact grid traversal (Amanatides-Woo DDA): no ray can slip
        diagonally between two occupied cells, so walls are always closed."""
        known, truth = self.known, self.world.truth
        gx = (x - ORIGIN[0]) / RES
        gy = (y - ORIGIN[1]) / RES
        max_cells = SCAN_RANGE / RES
        for i in range(360):
            a = i * (2 * math.pi / 360)
            dx, dy = math.cos(a), math.sin(a)
            cx, cy = int(gx), int(gy)
            step_x = 1 if dx > 0 else -1
            step_y = 1 if dy > 0 else -1
            t_dx = abs(1.0 / dx) if dx != 0 else 1e18
            t_dy = abs(1.0 / dy) if dy != 0 else 1e18
            t_x = ((cx + 1 - gx) if dx > 0 else (gx - cx)) * t_dx
            t_y = ((cy + 1 - gy) if dy > 0 else (gy - cy)) * t_dy
            t = 0.0
            while t <= max_cells:
                if not (0 <= cx < W and 0 <= cy < H):
                    break
                idx = cy * W + cx
                if truth[idx] == OCC:
                    known[idx] = OCC
                    break
                known[idx] = FREE
                if t_x < t_y:
                    t = t_x
                    t_x += t_dx
                    cx += step_x
                else:
                    t = t_y
                    t_y += t_dy
                    cy += step_y

    def frontiers(self) -> List[Tuple[float, float, int, Cell]]:
        known = self.known
        is_f = bytearray(W * H)
        for cy in range(1, H - 1):
            row = cy * W
            for cx in range(1, W - 1):
                i = row + cx
                if known[i] != FREE:
                    continue
                if known[i - 1] == UNKNOWN or known[i + 1] == UNKNOWN or known[i - W] == UNKNOWN or known[i + W] == UNKNOWN:
                    is_f[i] = 1
        out = []
        seen = bytearray(W * H)
        for i in range(W * H):
            if not is_f[i] or seen[i]:
                continue
            stack, cells = [i], []
            seen[i] = 1
            while stack:
                j = stack.pop()
                cells.append(j)
                jx, jy = j % W, j // W
                for ddx in (-1, 0, 1):
                    for ddy in (-1, 0, 1):
                        k = (jy + ddy) * W + (jx + ddx)
                        if 0 <= k < W * H and is_f[k] and not seen[k]:
                            seen[k] = 1
                            stack.append(k)
            if len(cells) < 6:
                continue
            sx = sum(c % W for c in cells) / len(cells)
            sy = sum(c // W for c in cells) / len(cells)
            # pick the member cell closest to the centroid as the goal cell
            best = min(cells, key=lambda c: (c % W - sx) ** 2 + (c // W - sy) ** 2)
            wx, wy = c2w(int(sx), int(sy))
            out.append((wx, wy, len(cells), (best % W, best // W)))
        self.frontier_centroids = [(f[0], f[1]) for f in out]
        return out

    def blocked_mask(self) -> bytearray:
        known = self.known
        blocked = bytearray(W * H)
        for i in range(W * H):
            if known[i] == OCC:
                cx, cy = i % W, i // W
                for ddy in range(-INFLATE, INFLATE + 1):
                    yy = cy + ddy
                    if not 0 <= yy < H:
                        continue
                    for ddx in range(-INFLATE, INFLATE + 1):
                        xx = cx + ddx
                        if 0 <= xx < W and ddx * ddx + ddy * ddy <= INFLATE * INFLATE:
                            blocked[yy * W + xx] = 1
            elif known[i] == UNKNOWN:
                blocked[i] = 1
        return blocked

    def astar(self, start: Cell, goal: Cell, blocked: bytearray) -> Optional[List[Cell]]:
        sx, sy = start
        gx, gy = goal
        blocked = bytearray(blocked)
        # Let the robot leave an inflated zone it has drifted into: free known cells near
        # the start are usable, but never cells touching an obstacle.
        known = self.known
        r = INFLATE + 1
        for ddy in range(-r, r + 1):
            for ddx in range(-r, r + 1):
                xx, yy = sx + ddx, sy + ddy
                if not (1 <= xx < W - 1 and 1 <= yy < H - 1) or known[yy * W + xx] != FREE:
                    continue
                if any(known[(yy + j) * W + xx + i] == OCC for i in (-1, 0, 1) for j in (-1, 0, 1)):
                    continue
                blocked[yy * W + xx] = 0
        blocked[sy * W + sx] = 0
        blocked[gy * W + gx] = 0
        openh = [(0.0, sx, sy)]
        g = {(sx, sy): 0.0}
        parent: Dict[Cell, Cell] = {}
        moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
        expanded = 0
        while openh:
            _, x, y = heapq.heappop(openh)
            if (x, y) == (gx, gy):
                path = [(x, y)]
                while path[-1] in parent:
                    path.append(parent[path[-1]])
                return path[::-1]
            expanded += 1
            if expanded > 40000:
                return None
            gc = g[(x, y)]
            for dx, dy, cst in moves:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < W and 0 <= ny < H) or blocked[ny * W + nx]:
                    continue
                if dx and dy and (blocked[y * W + nx] or blocked[ny * W + x]):
                    continue  # no diagonal corner cutting
                ng = gc + cst
                if ng < g.get((nx, ny), 1e18):
                    g[(nx, ny)] = ng
                    parent[(nx, ny)] = (x, y)
                    heapq.heappush(openh, (ng + math.hypot(gx - nx, gy - ny), nx, ny))
        return None


class SimSource:
    def __init__(self, store: TelemetryStore, cfg: Dict):
        self.store = store
        self.cfg = cfg
        scfg = cfg.get("sim", {})
        self.seed = int(scfg.get("seed", 7))
        self.topic_faults = bool(scfg.get("topic_faults", True))
        self.link_dropouts = bool(scfg.get("link_dropouts", False))
        self.dropout_every = float(scfg.get("link_dropout_every_s", 90))
        self.dropout_dur = float(scfg.get("link_dropout_duration_s", 6))
        self.link_down_until = 0.0
        # odom_only: behave like a robot whose ROS domain carries odometry but no TF,
        # map or navigation topics (group8). The robot still explores internally.
        self.odom_only = bool(scfg.get("odom_only", False))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.rng = random.Random(self.seed)
        self._reset_world(self.seed)

    # ------------------------------------------------------------------ setup
    def _reset_world(self, seed: int) -> None:
        self.world = World(seed)
        self.explorer = Explorer(self.world)
        self.x, self.y, self.yaw = 0.0, 0.0, 0.0
        self.v, self.w = 0.0, 0.0
        self.cmd = (0.0, 0.0)
        self.path: List[Tuple[float, float]] = []
        self.goal: Optional[Tuple[float, float]] = None
        self.complete_at: Optional[float] = None
        self.home_sent = False
        self.drift = [0.0, 0.0, 0.0]  # map->odom
        self.fault: Optional[Tuple[str, float]] = None
        self.next_fault = time.monotonic() + 40.0
        self.battery = 92.0
        self.map_version_sent = 0
        self._rate_acc: Dict[str, float] = {}
        # collision / no-progress recovery
        self.backing_until = 0.0
        self.force_replan = False
        self.replan_after_backing = False
        self.progress_ref: Optional[Tuple[float, float, float]] = None  # (t, x, y)
        self.collisions = 0
        self.travelled = 0.0

    def _role_name(self, role: str) -> Optional[str]:
        c = self.cfg["topics"][role]["candidates"]
        return c[0] if c else None

    def _register(self) -> None:
        s = self.store
        for role, spec in self.cfg["topics"].items():
            name = self._role_name(role)
            if not name:
                continue
            s.register_topic(role, name, expected_hz=spec.get("expected_hz"), min_hz=spec.get("min_hz"),
                             single_publisher=bool(spec.get("single_publisher")), type=spec["types"][0],
                             available=True, subscribed=True, publishers=1,
                             decoded=role not in ("scan", "imu", "joint_states", "tf_static"),
                             publisher_nodes=[self._publisher_for(role)])
            s.roles[role] = name
        if self.odom_only:
            # /tf exists on such robots (static frames only), so it stays registered but idle.
            for role in ("map", "scan", "global_plan", "local_plan", "goal", "nav_status", "frontiers",
                         "diagnostics"):
                name = self._role_name(role)
                if name in s.topics:
                    del s.topics[name]
                s.roles[role] = None
        for extra in self.cfg.get("extra_health_topics") or []:
            s.register_topic("extra", extra["name"], expected_hz=extra.get("expected_hz"),
                             min_hz=extra.get("min_hz"), available=True, subscribed=True, publishers=1,
                             type="(simulated)")
        # Robot temperatures: the configured topics, or (if none are configured) two
        # clearly-labelled simulated ones so the Temperatures graph can be tried.
        for rt in self.cfg.get("range_topics") or []:
            s.register_topic("range", rt["name"], label=rt.get("label") or rt["name"], expected_hz=rt.get("expected_hz"),
                             min_hz=rt.get("min_hz"), range_warn=rt.get("warn_m"), range_crit=rt.get("crit_m"),
                             range_max=rt.get("max_m"), available=True, subscribed=True, publishers=1, decoded=True,
                             type="std_msgs/msg/Float64", publisher_nodes=["/us_publisher"])
        self._stumble_until = 0.0
        self._next_stumble = time.monotonic() + 100.0
        self._next_log = time.monotonic() + 3.0
        self._temp_topics = list(self.cfg.get("temperature_topics") or []) or [
            {"name": "/sim/robot_body_temperature", "label": "Robot body (sim)", "warn_c": 60, "crit_c": 70},
            {"name": "/sim/motor_temperature_max", "label": "Hottest leg motor (sim)", "warn_c": 70, "crit_c": 85},
        ]
        for tt in self._temp_topics:
            s.register_topic("temperature", tt["name"], label=tt.get("label") or tt["name"], min_hz=tt.get("min_hz", 0.5),
                             temp_warn=tt.get("warn_c"), temp_crit=tt.get("crit_c"), available=True, subscribed=True,
                             publishers=1, decoded=True, type="sensor_msgs/msg/Temperature",
                             publisher_nodes=["/lite3_driver"])
        for flag in self.cfg.get("status_flags") or []:
            st = s.register_topic("status_flag", flag["name"], label=flag.get("label") or flag["name"],
                                  expected_hz=flag.get("expected_hz"), min_hz=flag.get("min_hz"),
                                  available=True, subscribed=True, publishers=1, decoded=True,
                                  type="std_msgs/msg/Bool", publisher_nodes=["/lite3_driver"])
            st.flag_value = True
        nodes = ["/slam_toolbox", "/planner_server", "/controller_server", "/bt_navigator", "/explore_node",
                 "/robot_state_publisher", "/lite3_driver", "/lidar_driver", "/imu_driver", "/diagnostic_aggregator"]
        with s.lock:
            s.graph = {"nodes": nodes, "topics": [[t.name, [t.type]] for t in s.topics.values()],
                       "rx": time.monotonic()}
            s.source_status = {"ok": True, "message": "simulation running"}
        s.set_tf("base_link", "laser", (0.18, 0.0, 0.12), (0.0, 0.0, 0.0, 1.0), static=True)
        s.set_tf("base_link", "imu_link", (0.0, 0.0, 0.05), (0.0, 0.0, 0.0, 1.0), static=True)
        s.topic_rx(self._role_name("tf_static") or "/tf_static", 1)

    @staticmethod
    def _publisher_for(role: str) -> str:
        return {
            "map": "/slam_toolbox", "odometry": "/lite3_driver", "scan": "/lidar_driver", "imu": "/imu_driver",
            "joint_states": "/lite3_driver", "global_plan": "/planner_server", "local_plan": "/controller_server",
            "goal": "/explore_node", "nav_status": "/bt_navigator", "frontiers": "/explore_node",
            "diagnostics": "/diagnostic_aggregator", "cmd_vel": "/controller_server",
        }.get(role, "/robot_state_publisher")

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._register()
        self._thread = threading.Thread(target=self._run, name="sim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def link_is_down(self) -> bool:
        return time.monotonic() < self.link_down_until

    # ------------------------------------------------------------------- loop
    DT = 0.05

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self.tick(t0)
            except Exception:  # keep the simulator alive no matter what
                log.exception("sim step failed")
            self._stop.wait(max(0.0, self.DT - (time.monotonic() - t0)))

    def tick(self, now: float) -> None:
        """Advance the simulation by one DT step. `now` may be a simulated clock (tests)."""
        if not hasattr(self, "_t"):
            self._t = {"scan": -1e9, "plan": -1e9, "map": -1e9, "diag": -1e9, "frontier": -1e9,
                       "dropout": now}
            self._k = 0
            self._replan_needed = True
        t = self._t
        self._k += 1
        self._faults(now)
        if self.link_dropouts and now - t["dropout"] > self.dropout_every:
            t["dropout"] = now
            self.link_down_until = now + self.dropout_dur
            log.info("sim: simulated link dropout for %.0fs", self.dropout_dur)

        if now - t["scan"] >= 0.5:
            t["scan"] = now
            self.explorer.scan(self.x, self.y)
        due = now - t["plan"] >= 8.0 or (self.goal and self._dist_to(self.goal) < 0.4)
        if self.force_replan or (self._replan_needed and now - t["plan"] >= 1.0) or due:
            self.force_replan = False
            t["plan"] = now
            self._replan_needed = not self._replan(now)
            t["frontier"] = now
        if now - t["map"] >= 2.0:
            t["map"] = now
            self._publish_map()
        if now - t["diag"] >= 1.0:
            t["diag"] = now
            self._publish_diag()
            self._publish_paths()
            self._publish_flags()
            self._publish_temps()
            self._publish_logs()
            self._publish_perception(now)
        if now - t["frontier"] >= 3.0:
            t["frontier"] = now
            self._publish_frontiers(self.explorer.frontier_centroids)
        self._step(self.DT, now)
        self._publish_fast(self.DT, self._k)

    SIM_SCENES = (("object", "hand_tools", "workshop", ["pegboard with tools", "workbench"]),
                  ("person", "person", "unknown", []),
                  ("warning_sign", "high_voltage", "kitchen", ["toy stove", "sink unit"]),
                  ("qr", "My friend is in the market.", "kitchen", ["toy kitchen counter"]))

    def _publish_perception(self, now: float) -> None:
        """Simulated Pi perception: a detection record every second and a Claude scene check every 20 s
        (pending, then a result 3 s later; every fourth one fails)."""
        import json as _json
        p = self.store.perception
        k = int(now // 20)
        kind, label, room, evidence = self.SIM_SCENES[k % len(self.SIM_SCENES)]
        stamp = int(k * 20 * 1e9)
        rid = f"scene-{k}"
        p.on_detections(_json.dumps({"frame": int(now), "objects": [{"name": label, "confidence": 0.81}]
                                     if kind in ("object", "person") else [],
                                     "qr_codes": [{"text": label}] if kind == "qr" else [],
                                     "warning_sign_candidates": [{"label": label}] if kind == "warning_sign" else [],
                                     "stair_curtain": {"obstacle": "unknown", "reason": "no_confirmed_candidate"}}),
                        now)
        base = {"request_id": rid, "capture_stamp_ns": stamp, "frame": k, "frame_id": "camera_color_optical_frame",
                "trigger": {"kind": kind, "label": label}, "encounter_ids": [f"{kind}-{k}"]}
        phase = now - k * 20
        current = p.requests.get(rid)
        if current is None or current.get("capture_stamp_ns") != stamp:
            p.on_scene_event(_json.dumps(dict(base, event="scene_pending")), now)
        elif phase >= 3.0 and current["status"] == "pending":
            if k % 4 == 3:
                p.on_scene_event(_json.dumps(dict(base, event="scene_failed", error="TimeoutError (simulated)")), now)
            else:
                p.on_scene_event(_json.dumps(dict(base, event="scene_result",
                                                  scene={"type": room, "evidence": evidence})), now)

    def sim_missions(self) -> Dict:
        """Simulated mission log (what the robot's reporter wrote and what the scoring server answered)."""
        rows = [("M04", "qr", "", "", None, "My friend is in the market.", 5, 5, {"message": True}),
                ("M02", "hazard", "kitchen", "high_voltage", [1.02, 0.0], "", 10, 10,
                 {"scene_type": True, "pos": True, "label": True}),
                ("M01", "object", "workshop", "hand_tools", [2.04, 1.02], "", 5, 10,
                 {"scene_type": True, "pos": False, "label": True})]
        return {"run": "competition-sim", "file_mtime": None, "reports": [
            {"t": None, "task_id": t, "task_type": ty, "scene_type": sc, "label": la, "pos": pos, "message": msg,
             "http_status": 200, "dry_run": False, "accepted": True, "score": score, "max_score": mx,
             "evaluation": ev, "reason": None, "course": "A"}
            for t, ty, sc, la, pos, msg, score, mx, ev in rows]}

    def _dist_to(self, p: Tuple[float, float]) -> float:
        return math.hypot(p[0] - self.x, p[1] - self.y)

    def _faults(self, now: float) -> None:
        if self.fault and now > self.fault[1]:
            log.info("sim: fault %s cleared", self.fault[0])
            self.fault = None
        if self.topic_faults and self.fault is None and now > self.next_fault:
            kind = self.rng.choice(["scan_dropout", "imu_degraded", "stuck", "tf_stale"])
            dur = {"scan_dropout": 6, "imu_degraded": 12, "stuck": 14, "tf_stale": 4}[kind]
            self.fault = (kind, now + dur)
            self.next_fault = now + dur + self.rng.uniform(45, 90)
            log.info("sim: injecting fault %s for %ss", kind, dur)

    def _has_fault(self, kind: str) -> bool:
        return bool(self.fault and self.fault[0] == kind)

    # ----------------------------------------------------------- exploration
    def _replan(self, now: float) -> bool:
        ex = self.explorer
        fr = ex.frontiers()
        fr = [f for f in fr if all(math.hypot(f[0] - b[0], f[1] - b[1]) > 0.8 for b in ex.blacklist)]
        ex.frontier_centroids = [(f[0], f[1]) for f in fr]
        blocked = ex.blocked_mask()
        start = w2c(self.x, self.y)
        if not fr:
            if self.complete_at is None:
                self.complete_at = now
                log.info("sim: exploration complete")
            if not self.home_sent and self._dist_to((0.0, 0.0)) > 0.5:
                cells = ex.astar(start, w2c(0.0, 0.0), blocked)
                if cells:
                    self.home_sent = True
                    self._set_goal((0.0, 0.0), cells)
                    return True
            if self.goal and self._dist_to(self.goal) < 0.4:
                self._finish_goal("SUCCEEDED")
            if now - self.complete_at > 90.0:
                log.info("sim: restarting with a new world")
                self.seed += 1
                self._reset_world(self.seed)
                with self.store.lock:
                    self.store.paths = {"global": None, "local": None}
                    self.store.goal = None
            return True
        if self.goal and self._dist_to(self.goal) < 0.4:
            self._finish_goal("SUCCEEDED")
        fr.sort(key=lambda f: self._dist_to((f[0], f[1])) - 0.02 * f[2])
        for f in fr[:4]:
            cells = ex.astar(start, f[3], blocked)
            if cells:
                self._set_goal(c2w(*f[3]), cells)
                return True
            ex.blacklist.append((f[0], f[1]))
        self._finish_goal("ABORTED")
        return False

    def _set_goal(self, goal: Tuple[float, float], cells: List[Cell]) -> None:
        pts = [c2w(cx, cy) for cx, cy in cells]
        self.path = pts[::2] + [pts[-1]]
        self.goal = goal
        yaw = math.atan2(goal[1] - self.y, goal[0] - self.x)
        s = self.store
        now = time.monotonic()
        if self.odom_only:
            return
        with s.lock:
            s.goal = {"x": goal[0], "y": goal[1], "yaw": yaw, "frame": "map", "rx": now}
            s.nav_status = {"status": "EXECUTING", "rx": now}
        s.topic_rx(self._role_name("goal") or "/goal_pose")
        s.topic_rx(self._role_name("nav_status") or "/nav_status")

    def _finish_goal(self, status: str) -> None:
        if self.goal is None:
            return
        self.goal = None
        self.path = []
        if self.odom_only:
            return
        with self.store.lock:
            self.store.nav_status = {"status": status, "rx": time.monotonic()}
        self.store.topic_rx(self._role_name("nav_status") or "/nav_status")

    def _step(self, dt: float, now: float) -> None:
        tv, tw = 0.0, 0.0
        if self.path:
            # drop passed points, then aim at a lookahead point
            while len(self.path) > 1 and self._dist_to(self.path[0]) < 0.35:
                self.path.pop(0)
            target = self.path[0]
            for p in self.path:
                if self._dist_to(p) > 0.6:
                    target = p
                    break
            err = wrap_angle(math.atan2(target[1] - self.y, target[0] - self.x) - self.yaw)
            tw = max(-0.9, min(0.9, 1.8 * err))
            tv = 0.0 if abs(err) > 0.9 else 0.55 * math.cos(err)
            if len(self.path) == 1 and self._dist_to(self.path[0]) < 0.25:
                tv = tw = 0.0
        if now < self.backing_until:
            tv, tw = -0.25, 0.0  # bumper recovery: reverse away from the obstacle
        elif self.replan_after_backing:
            self.replan_after_backing = False
            self.force_replan = True
        self.cmd = (tv, tw)
        # first-order dynamics
        self.v += (tv - self.v) * min(1.0, dt * 3.0)
        self.w += (tw - self.w) * min(1.0, dt * 4.0)
        if self._has_fault("stuck"):
            self.v, self.w = 0.0, 0.02 * math.sin(now * 5)
        nx = self.x + self.v * math.cos(self.yaw) * dt
        ny = self.y + self.v * math.sin(self.yaw) * dt
        if not self.world.occupied(nx, ny):
            self.travelled += math.hypot(nx - self.x, ny - self.y)
            self.x, self.y = nx, ny
        else:
            self.v = 0.0
            if not self._has_fault("stuck"):
                self._on_collision(nx, ny, now)
        self.yaw = wrap_angle(self.yaw + self.w * dt)
        self._check_progress(now)
        # slow SLAM correction drift of map->odom
        self.drift[0] += self.rng.gauss(0, 0.0004)
        self.drift[1] += self.rng.gauss(0, 0.0004)
        self.drift[2] += self.rng.gauss(0, 0.0002)

    def _on_collision(self, x: float, y: float, now: float) -> None:
        """Like a bumper/costmap: record the obstacle that the scan missed, back off, replan."""
        cx, cy = w2c(x, y)
        known, truth = self.explorer.known, self.world.truth
        for ddy in (-1, 0, 1):
            for ddx in (-1, 0, 1):
                xx, yy = cx + ddx, cy + ddy
                if 0 <= xx < W and 0 <= yy < H and truth[yy * W + xx] == OCC:
                    known[yy * W + xx] = OCC
        if now >= self.backing_until:
            self.collisions += 1
            self.backing_until = now + 1.5
            self.replan_after_backing = True

    def _check_progress(self, now: float) -> None:
        """Give up on a goal if the robot has not moved 0.15 m in 6 s (not during injected stalls)."""
        if not self.goal or self._has_fault("stuck"):
            self.progress_ref = (now, self.x, self.y)
            return
        if self.progress_ref is None:
            self.progress_ref = (now, self.x, self.y)
            return
        t0, x0, y0 = self.progress_ref
        if math.hypot(self.x - x0, self.y - y0) >= 0.15:
            self.progress_ref = (now, self.x, self.y)
        elif now - t0 > 6.0:
            log.info("sim: no progress towards goal, blacklisting it and replanning")
            self.explorer.blacklist.append(self.goal)
            self._finish_goal("ABORTED")
            self.progress_ref = (now, self.x, self.y)
            self.force_replan = True

    # ------------------------------------------------------------- publishing
    def _publish_fast(self, dt: float, k: int) -> None:
        s = self.store
        now = time.monotonic()
        dx, dy, dth = self.drift
        # odom pose = inverse(map_T_odom) * map_pose
        c, sn = math.cos(-dth), math.sin(-dth)
        ox = c * (self.x - dx) - sn * (self.y - dy)
        oy = sn * (self.x - dx) + c * (self.y - dy)
        oyaw = wrap_angle(self.yaw - dth)
        noise = self.rng.gauss
        with s.lock:
            s.odom = {"x": ox, "y": oy, "yaw": oyaw, "frame": "odom",
                      "vx": self.v + noise(0, 0.01), "vy": noise(0, 0.005), "wz": self.w + noise(0, 0.01), "rx": now}
            s.cmd_vel = {"linear": self.cmd[0], "angular": self.cmd[1], "rx": now}
        if not self.odom_only:
            if not self._has_fault("tf_stale"):
                s.set_tf("map", "odom", (dx, dy, 0.0), quat_from_yaw(dth), static=False, now=now)
            s.set_tf("odom", "base_link", (ox, oy, 0.32), quat_from_yaw(oyaw), static=False, now=now)
        n = self._role_name
        # Rates follow the configured expected_hz (group8 publishes odom/IMU/joints at 200 Hz).
        self._count("odometry", None, now)
        if not self.odom_only:
            s.topic_rx(n("tf") or "/tf", 3, now)                                   # ~60 Hz
        s.topic_rx(n("cmd_vel") or "/cmd_vel", 1, now)                             # 20 Hz
        self._count("joint_states", None, now)
        self._publish_body(now)
        self._count("imu", 0.2 if self._has_fault("imu_degraded") else None, now)  # fault: 20 % rate
        if not self._has_fault("scan_dropout"):
            self._count("scan", None, now)
        for extra in self.cfg.get("extra_health_topics") or []:
            self._count_name(extra["name"], extra.get("expected_hz") or 10.0, now)

    def _count(self, role: str, factor, now: float) -> None:
        spec = self.cfg["topics"][role]
        name = self._role_name(role)
        if name:
            self._count_name(name, float(spec.get("expected_hz") or 10.0) * (factor or 1.0), now,
                             self.SIM_SIZES.get(role, 200))

    # Approximate serialized message sizes (bytes) so the data-rate column is realistic.
    SIM_SIZES = {"odometry": 720, "imu": 330, "joint_states": 640, "scan": 1460, "tf": 230, "cmd_vel": 56,
                 "/livox/imu": 330, "/camera/color/camera_info": 370, "/camera/depth/camera_info": 370,
                 "/us_publisher/ultrasound_distance": 12}

    def _count_name(self, name: str, hz: float, now: float, size: Optional[int] = None) -> None:
        """Add hz*DT messages per tick, carrying the fraction so the average rate is exact."""
        acc = self._rate_acc.get(name, 0.0) + hz * self.DT
        whole = int(acc)
        self._rate_acc[name] = acc - whole
        if whole:
            sz = size if size is not None else self.SIM_SIZES.get(name, 200)
            self.store.topic_rx(name, whole, now, whole * sz)

    def _publish_map(self) -> None:
        if self.odom_only:
            return
        s = self.store
        with s.lock:
            s.map_raw = {"data": bytes(self.explorer.known), "width": W, "height": H, "resolution": RES,
                         "origin": (ORIGIN[0], ORIGIN[1], 0.0), "frame": "map", "rx": time.monotonic()}
            s.map_version += 1
        s.topic_rx(self._role_name("map") or "/map")

    def _publish_paths(self) -> None:
        if self.odom_only:
            return
        s = self.store
        now = time.monotonic()
        if self.path:
            pts = [[round(self.x, 2), round(self.y, 2)]] + [[round(p[0], 2), round(p[1], 2)] for p in self.path]
            length = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
            local = pts[: min(len(pts), 8)]
            llen = sum(math.hypot(local[i + 1][0] - local[i][0], local[i + 1][1] - local[i][1]) for i in range(len(local) - 1))
            with s.lock:
                s.paths["global"] = {"frame": "map", "points": pts, "rx": now, "length": length}
                s.paths["local"] = {"frame": "map", "points": local, "rx": now, "length": llen}
            s.topic_rx(self._role_name("global_plan") or "/plan")
            s.topic_rx(self._role_name("local_plan") or "/local_plan")

    def _publish_frontiers(self, centroids: List[Tuple[float, float]]) -> None:
        if self.odom_only:
            return
        s = self.store
        with s.lock:
            s.frontiers = {"count": len(centroids), "points": [[round(x, 2), round(y, 2)] for x, y in centroids],
                           "frame": "map", "rx": time.monotonic()}
        s.topic_rx(self._role_name("frontiers") or "/frontiers")

    JOINTS = [f"{leg}_{j}" for leg in ("FL", "FR", "HL", "HR") for j in ("HipX", "HipY", "Knee")]

    def _publish_body(self, now: float) -> None:
        """IMU attitude (with an occasional simulated stumble), joint efforts, ultrasound, robot log."""
        s = self.store
        t = time.time()
        if now > self._next_stumble:
            self._stumble_until = now + 2.5
            self._next_stumble = now + self.rng.uniform(120, 200)
            s.add_log(30, "lite3_motion", "large body tilt detected - recovering balance (simulated)")
        stumble = now < self._stumble_until
        gait = abs(self.v) / 0.55
        roll = math.radians(1.5 * math.sin(t * 9.0) * gait + (27.0 if stumble else 0.0) + self.rng.gauss(0, 0.3))
        pitch = math.radians(2.0 * math.sin(t * 9.0 + 1.0) * gait + (-6.0 if stumble else 0.0) + self.rng.gauss(0, 0.3))
        acc = 9.81 * (1.0 + 0.08 * gait * math.sin(t * 18.0) + (0.6 if stumble else 0.0))
        with s.lock:
            s.imu = {"roll": roll, "pitch": pitch, "acc": acc, "gyro": abs(self.w) + 0.02, "source": "orientation", "rx": now}
            eff = []
            for i, _n in enumerate(self.JOINTS):
                base = (6.0 if i % 3 == 2 else 2.5) * (0.6 + gait)
                eff.append(base * (1.0 + 0.4 * math.sin(t * 9.0 + i)) + (8.0 if stumble and i % 3 == 2 else 0.0))
            s.joints = {"names": list(self.JOINTS), "effort": eff,
                        "velocity": [gait * 3.0 * math.sin(t * 9.0 + i) for i in range(12)], "rx": now}
        for rt in self.cfg.get("range_topics") or []:
            st = s.topics.get(rt["name"])
            if st is None:
                continue
            mx = float(rt.get("max_m") or 4.5)
            d = 0.05
            while d < mx and not self.world.occupied(self.x + d * math.cos(self.yaw), self.y + d * math.sin(self.yaw)):
                d += 0.05
            st.range_m = round(min(d, mx) + self.rng.gauss(0, 0.01), 3)
            self._count_name(rt["name"], float(rt.get("expected_hz") or 50), now, 12)

    def _publish_logs(self) -> None:
        now = time.monotonic()
        if now < self._next_log:
            return
        self._next_log = now + self.rng.uniform(4, 12)
        msgs = [
            (20, "lite3_sensor_relay", "relaying 5 sensor topics to domain 8"),
            (20, "odom_relay", "odometry stream healthy"),
            (30, "lite3_livox_cloud", "point cloud late by 120 ms"),
            (20, "lite3_terrain_monitor", "terrain map updated"),
            (40, "lite3_livox_cloud", "dropped 2 point clouds (buffer full)"),
        ]
        lvl, node, msg = self.rng.choice(msgs)
        self.store.add_log(lvl, node, msg + " (simulated)")

    def _publish_temps(self) -> None:
        """Robot temperatures: rise while walking, cool while standing, plus slow noise."""
        moving = abs(self.v) > 0.05 or abs(self.w) > 0.1
        self._heat = getattr(self, "_heat", 0.0)
        self._heat = min(1.0, self._heat + 0.004) if moving else max(0.0, self._heat - 0.006)
        t = time.time()
        for i, tt in enumerate(self._temp_topics):
            st = self.store.topics.get(tt["name"])
            if st is None:
                continue
            warn = float(tt.get("warn_c") or 60)
            base = warn - 22 + 4 * math.sin(t / 50.0 + i)
            st.temp_value = round(base + 30 * self._heat + self.rng.gauss(0, 0.3), 1)
            self.store.topic_rx(tt["name"], 1)

    def _publish_flags(self) -> None:
        """Robot-reported 'is alive' booleans; the IMU one goes false during the IMU fault."""
        for flag in self.cfg.get("status_flags") or []:
            st = self.store.topics.get(flag["name"])
            if st is None:
                continue
            st.flag_value = not ("imu" in flag["name"] and self._has_fault("imu_degraded"))
            self.store.topic_rx(flag["name"], 2)  # called at 1 Hz -> 2 msgs/s like the robot

    def _publish_diag(self) -> None:
        if self.odom_only:
            return
        s = self.store
        self.battery = max(5.0, self.battery - 0.01)
        items = [
            {"name": "lite3/battery", "level": 0 if self.battery > 25 else 1, "message": f"{self.battery:.1f}%"},
            {"name": "lite3/motors", "level": 0, "message": "OK"},
            {"name": "lidar/driver", "level": 1 if self._has_fault("scan_dropout") else 0,
             "message": "no scans received" if self._has_fault("scan_dropout") else "OK"},
            {"name": "imu/driver", "level": 1 if self._has_fault("imu_degraded") else 0,
             "message": "rate low" if self._has_fault("imu_degraded") else "OK"},
            {"name": "nav/controller", "level": 1 if self._has_fault("stuck") else 0,
             "message": "failed to make progress" if self._has_fault("stuck") else "OK"},
        ]
        set_diagnostics(s, items)
        s.topic_rx(self._role_name("diagnostics") or "/diagnostics")


def set_diagnostics(store: TelemetryStore, items: List[Dict]) -> None:
    summary = {"ok": 0, "warn": 0, "error": 0, "stale": 0}
    keys = {0: "ok", 1: "warn", 2: "error", 3: "stale"}
    for it in items:
        summary[keys.get(int(it["level"]), "error")] += 1
    worst = sorted(items, key=lambda i: -int(i["level"]))[:30]
    with store.lock:
        store.diagnostics = {"summary": summary, "items": worst, "rx": time.monotonic()}
