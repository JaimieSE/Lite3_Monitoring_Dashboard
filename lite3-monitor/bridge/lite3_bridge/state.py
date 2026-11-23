"""Thread-safe latest-value telemetry store.

Data sources (the ROS subscriber thread or the simulator thread) write into
this store. The websocket server reads snapshots from it at fixed rates.
There is deliberately NO queue between sources and clients: every field is
"latest value wins", so memory is bounded and nothing stale piles up.

All ages are measured with time.monotonic() on the bridge host at *receipt*
time, never from ROS header stamps, so clock skew between machines cannot
make old data look fresh.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

from .geom import Quat, Vec3, compose, yaw_from_quat

NAV_STATUS_NAMES = {
    0: "UNKNOWN",
    1: "ACCEPTED",
    2: "EXECUTING",
    3: "CANCELING",
    4: "SUCCEEDED",
    5: "CANCELED",
    6: "ABORTED",
}
NAV_ACTIVE = {"ACCEPTED", "EXECUTING", "CANCELING"}


def _r(v: Optional[float], nd: int = 3) -> Optional[float]:
    if v is None or not math.isfinite(v):
        return None
    return round(v, nd)


@dataclass
class TopicStat:
    role: str
    name: str
    expected_hz: Optional[float] = None
    min_hz: Optional[float] = None
    single_publisher: bool = False
    decoded: bool = False
    type: Optional[str] = None
    available: bool = False          # present in the ROS graph
    subscribed: bool = False
    error: Optional[str] = None
    publishers: int = 0
    publisher_nodes: List[str] = field(default_factory=list)
    window_count: int = 0
    total: int = 0
    last_rx: Optional[float] = None
    rate_hz: float = 0.0
    last_rate_calc: float = field(default_factory=time.monotonic)
    # data volume: serialized bytes received (only known for raw subscriptions)
    window_bytes: int = 0
    bytes_per_s: Optional[float] = None
    bytes_known: bool = False
    # status flags (std_msgs/Bool "is alive" topics): last value and display label
    flag_value: Optional[bool] = None
    # robot temperature topics (role "temperature"): last value in degrees C + thresholds
    temp_value: Optional[float] = None
    temp_warn: Optional[float] = None
    temp_crit: Optional[float] = None
    label: Optional[str] = None


@dataclass
class TfEdge:
    parent: str
    child: str
    t: Vec3
    q: Quat
    rx: float
    static: bool


class TelemetryStore:
    def __init__(self, cfg: Dict[str, Any], mode: str):
        self.cfg = cfg
        self.mode = mode
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.started_wall = time.time()

        self.topics: Dict[str, TopicStat] = {}
        self.roles: Dict[str, Optional[str]] = {r: None for r in cfg["topics"]}
        self.tf_edges: Dict[str, TfEdge] = {}  # keyed by child frame
        self.tf_dropped = 0

        self.odom: Optional[Dict[str, Any]] = None
        self.map_raw: Optional[Dict[str, Any]] = None
        self.map_version = 0
        self.map_stats: Optional[Dict[str, Any]] = None  # filled by the broadcaster
        self.paths: Dict[str, Optional[Dict[str, Any]]] = {"global": None, "local": None}
        self.goal: Optional[Dict[str, Any]] = None
        self.nav_status: Optional[Dict[str, Any]] = None
        self.frontiers: Optional[Dict[str, Any]] = None
        self.exploration_state: Optional[Dict[str, Any]] = None
        self.diagnostics: Optional[Dict[str, Any]] = None
        self.cmd_vel: Optional[Dict[str, Any]] = None
        self.graph: Dict[str, Any] = {"nodes": [], "topics": [], "rx": None}
        self.source_status: Dict[str, Any] = {"ok": True, "message": ""}

        self.tracker = MotionTracker(cfg)

    # ------------------------------------------------------------------ topics
    def register_topic(self, role: str, name: str, **kw: Any) -> TopicStat:
        with self.lock:
            st = self.topics.get(name)
            if st is None:
                st = TopicStat(role=role, name=name, **kw)
                self.topics[name] = st
            else:
                for k, v in kw.items():
                    setattr(st, k, v)
            return st

    def topic_rx(self, name: str, n: int = 1, now: Optional[float] = None, nbytes: Optional[int] = None) -> None:
        st = self.topics.get(name)
        if st is None:
            return
        with self.lock:
            st.window_count += n
            st.total += n
            st.last_rx = now if now is not None else time.monotonic()
            if nbytes is not None:
                st.window_bytes += nbytes
                st.bytes_known = True

    def update_rates(self) -> None:
        now = time.monotonic()
        with self.lock:
            for st in self.topics.values():
                dt = now - st.last_rate_calc
                if dt <= 0.2:
                    continue
                inst = st.window_count / dt
                # light smoothing; reset quickly to zero when silent
                st.rate_hz = inst if st.window_count == 0 else 0.5 * st.rate_hz + 0.5 * inst
                st.window_count = 0
                if st.bytes_known:
                    binst = st.window_bytes / dt
                    prev = st.bytes_per_s or 0.0
                    st.bytes_per_s = binst if st.window_bytes == 0 else 0.5 * prev + 0.5 * binst
                    st.window_bytes = 0
                st.last_rate_calc = now

    # --------------------------------------------------------------------- TF
    def set_tf(self, parent: str, child: str, t: Vec3, q: Quat, static: bool, now: Optional[float] = None) -> None:
        parent = parent.lstrip("/")
        child = child.lstrip("/")
        with self.lock:
            self.tf_edges[child] = TfEdge(parent, child, t, q, now if now is not None else time.monotonic(), static)

    def _resolve_base_frame(self) -> Optional[str]:
        for f in self.cfg["frames"]["base"]:
            if f in self.tf_edges:
                return f
        return None

    def _chain(self, child: str, root: str, now: float) -> Optional[Dict[str, Any]]:
        """Walk child -> ... -> root. Returns composed transform root_T_child."""
        t: Vec3 = (0.0, 0.0, 0.0)
        q: Quat = (0.0, 0.0, 0.0, 1.0)
        edges = []
        frame = child
        seen = set()
        while frame != root:
            if frame in seen or len(edges) > 32:
                return None
            seen.add(frame)
            e = self.tf_edges.get(frame)
            if e is None:
                return None
            t, q = compose(e.t, e.q, t, q)
            edges.append(e)
            frame = e.parent
        dyn_ages = [now - e.rx for e in edges if not e.static]
        return {
            "t": t,
            "q": q,
            "age": max(dyn_ages) if dyn_ages else 0.0,
            "edges": [
                {
                    "parent": e.parent,
                    "child": e.child,
                    "static": e.static,
                    "age_s": _r(now - e.rx, 2),
                }
                for e in reversed(edges)
            ],
        }

    # ------------------------------------------------------------- snapshots
    def pose_snapshot(self, now: float) -> Dict[str, Any]:
        frames = self.cfg["frames"]
        stale_s = float(self.cfg["staleness"]["pose_stale_s"])
        tf_stale_s = float(self.cfg["staleness"]["tf_stale_s"])
        base = self._resolve_base_frame()
        tf_info: Dict[str, Any] = {"base_frame": base, "chain": [], "errors": [], "ok": False}
        pose = None
        if base:
            ch = self._chain(base, frames["map"], now)
            frame = frames["map"]
            if ch is None:
                tf_info["errors"].append(f"no TF chain {frames['map']} -> {base}")
                ch = self._chain(base, frames["odom"], now)
                frame = frames["odom"]
                if ch is None:
                    tf_info["errors"].append(f"no TF chain {frames['odom']} -> {base}")
            if ch is not None:
                tf_info["chain"] = ch["edges"]
                for e in ch["edges"]:
                    if not e["static"] and e["age_s"] is not None and e["age_s"] > tf_stale_s:
                        tf_info["errors"].append(f"stale TF {e['parent']} -> {e['child']} ({e['age_s']:.1f}s)")
                pose = {
                    "x": ch["t"][0],
                    "y": ch["t"][1],
                    "yaw": yaw_from_quat(ch["q"]),
                    "frame": frame,
                    "source": "tf",
                    "age_s": ch["age"],
                }
        else:
            tf_info["errors"].append("robot base frame not found in TF (tried " + ", ".join(frames["base"]) + ")")

        if pose is None and self.odom is not None:
            o = self.odom
            pose = {
                "x": o["x"],
                "y": o["y"],
                "yaw": o["yaw"],
                "frame": o["frame"],
                "source": "odometry",
                "age_s": now - o["rx"],
            }
        tf_required = bool(frames.get("tf_required", True))
        tf_info["required"] = tf_required
        tf_info["notes"] = []
        if not tf_required and pose is not None and pose["source"] == "odometry":
            # Robot without dynamic TF (e.g. group8 domain 8): odometry pose is the
            # intended source, so missing TF chains are information, not a fault.
            tf_info["notes"] = tf_info["errors"] + ["pose from odometry (TF not required)"]
            tf_info["errors"] = []
        tf_info["ok"] = not tf_info["errors"]
        if pose is not None:
            pose["valid"] = pose["age_s"] <= stale_s
            pose["map_frame"] = pose["frame"] == frames["map"]
        return {"pose": pose, "tf": tf_info}

    def velocity_snapshot(self, now: float) -> Optional[Dict[str, Any]]:
        stale_s = float(self.cfg["staleness"]["pose_stale_s"])
        o = self.odom
        if o is not None and o.get("vx") is not None:
            age = now - o["rx"]
            return {
                "linear": o["vx"],
                "lateral": o["vy"],
                "angular": o["wz"],
                "speed": math.hypot(o["vx"], o["vy"]),
                "age_s": age,
                "valid": age <= stale_s,
                "source": "odometry",
            }
        est = self.tracker.estimated_velocity()
        if est is not None:
            est["valid"] = est["age_s"] <= stale_s
        return est

    def nav_snapshot(self, now: float, pose: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": None, "status_age_s": None, "goal": None, "distance_to_goal_m": None,
                               "global_path_length_m": None}
        if self.nav_status is not None:
            out["status"] = self.nav_status["status"]
            out["status_age_s"] = _r(now - self.nav_status["rx"], 2)
        if self.goal is not None:
            g = self.goal
            out["goal"] = {"x": _r(g["x"]), "y": _r(g["y"]), "yaw": _r(g["yaw"]), "frame": g["frame"],
                           "age_s": _r(now - g["rx"], 1)}
            if pose is not None and pose["frame"] == g["frame"]:
                out["distance_to_goal_m"] = _r(math.hypot(g["x"] - pose["x"], g["y"] - pose["y"]), 2)
        gp = self.paths.get("global")
        if gp is not None:
            out["global_path_length_m"] = _r(gp["length"], 2)
        return out

    def nav_active(self, now: float) -> bool:
        ns = self.nav_status
        return bool(ns and ns["status"] in NAV_ACTIVE and now - ns["rx"] < 30.0)

    def cmd_active(self, now: float) -> bool:
        c = self.cmd_vel
        return bool(c and now - c["rx"] < 1.0 and (abs(c["linear"]) > 0.05 or abs(c["angular"]) > 0.1))

    def telemetry_message(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self.lock:
            ps = self.pose_snapshot(now)
            pose = ps["pose"]
            vel = self.velocity_snapshot(now)
            nav = self.nav_snapshot(now, pose)
            expl = self.tracker.update(now, pose, vel, self.nav_active(now), self.cmd_active(now),
                                       self.frontiers, self.exploration_state)
            cmd = None
            if self.cmd_vel is not None:
                cmd = {"linear": _r(self.cmd_vel["linear"]), "angular": _r(self.cmd_vel["angular"]),
                       "age_s": _r(now - self.cmd_vel["rx"], 2)}
        if pose is not None:
            pose = {k: (_r(v) if isinstance(v, float) else v) for k, v in pose.items()}
        if vel is not None:
            vel = {k: (_r(v) if isinstance(v, float) else v) for k, v in vel.items()}
        return {
            "type": "telemetry",
            "server_time": time.time(),
            "uptime_s": _r(now - self.started, 1),
            "pose": pose,
            "velocity": vel,
            "cmd_vel": cmd,
            "nav": nav,
            "exploration": expl,
            "tf": ps["tf"],
        }

    def health_message(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        self.update_rates()
        now = time.monotonic()
        topics = []
        with self.lock:
            for st in sorted(self.topics.values(), key=lambda s: (s.role, s.name)):
                topics.append(self._topic_health(st, now))
            missing_roles = [r for r, n in self.roles.items() if n is None and self.cfg["topics"][r]["candidates"]]
            diag = None
            if self.diagnostics is not None:
                d = self.diagnostics
                diag = dict(d["summary"])
                diag["items"] = d["items"]
                diag["age_s"] = _r(now - d["rx"], 1)
            expected_nodes = list(self.cfg.get("expected_nodes") or [])
            present = set(self.graph["nodes"])
            nodes = {
                "count": len(self.graph["nodes"]),
                "names": self.graph["nodes"][:200],
                "missing_expected": [n for n in expected_nodes if n not in present],
                "scan_age_s": _r(now - self.graph["rx"], 1) if self.graph["rx"] else None,
            }
            roles = dict(self.roles)
            map_info = None
            if self.map_raw is not None:
                map_info = {"version": self.map_version, "age_s": _r(now - self.map_raw["rx"], 1),
                            "stale": now - self.map_raw["rx"] > float(self.cfg["staleness"]["map_stale_s"]),
                            "width": self.map_raw["width"], "height": self.map_raw["height"],
                            "resolution": self.map_raw["resolution"], "stats": self.map_stats}
            source = dict(self.source_status)
            tf_dropped = self.tf_dropped
        return {
            "type": "health",
            "server_time": time.time(),
            "topics": topics,
            "roles": roles,
            "missing_roles": missing_roles,
            "nodes": nodes,
            "diagnostics": diag,
            "map": map_info,
            "source": source,
            "bridge": dict(extra, uptime_s=_r(now - self.started, 1), tf_dropped=tf_dropped, mode=self.mode),
        }

    def _topic_health(self, st: TopicStat, now: float) -> Dict[str, Any]:
        age = None if st.last_rx is None else now - st.last_rx
        status = "ok"
        notes: List[str] = []
        if not st.available:
            status = "missing"
            notes.append("not in ROS graph")
        elif st.error:
            status = "error"
            notes.append(st.error)
        elif st.last_rx is None:
            # Event-driven topics (goal, paths, map) may legitimately be quiet.
            if st.min_hz:
                status = "error"
                notes.append("no messages received")
            else:
                status = "idle"
                notes.append("no messages yet")
        else:
            if st.min_hz:
                if st.rate_hz < st.min_hz:
                    status = "warn" if st.rate_hz > 0 else "error"
                    notes.append(f"rate {st.rate_hz:.1f} Hz < {st.min_hz} Hz")
                if age is not None and age > max(2.0, 3.0 / st.min_hz):
                    status = "error"
                    notes.append(f"stale {age:.1f}s")
        if st.role == "temperature" and st.temp_value is not None and status in ("ok", "warn", "idle"):
            if st.temp_crit is not None and st.temp_value >= st.temp_crit:
                status = "error"
                notes.insert(0, f"too hot: {st.temp_value:.1f} °C ≥ {st.temp_crit:g} °C")
            elif st.temp_warn is not None and st.temp_value >= st.temp_warn:
                status = "warn"
                notes.insert(0, f"hot: {st.temp_value:.1f} °C ≥ {st.temp_warn:g} °C")
        if st.role == "status_flag" and st.flag_value is False and status != "missing":
            status = "error"
            notes.insert(0, "reports NOT alive")
        if st.single_publisher and st.publishers > 1:
            if status == "ok":
                status = "warn"
            notes.append(f"{st.publishers} publishers - possible cross-robot traffic")
        return {
            "role": st.role,
            "name": st.name,
            "type": st.type,
            "decoded": st.decoded,
            "expected_hz": st.expected_hz,
            "min_hz": st.min_hz,
            "rate_hz": _r(st.rate_hz, 2),
            "age_s": _r(age, 2),
            "total": st.total,
            "publishers": st.publishers,
            "publisher_nodes": st.publisher_nodes[:8],
            "status": status,
            "note": "; ".join(notes),
            "value": st.flag_value,
            "label": st.label,
            "bytes_per_s": _r(st.bytes_per_s, 0) if st.bytes_known else None,
            "temp_c": _r(st.temp_value, 1),
            "temp_warn_c": st.temp_warn,
            "temp_crit_c": st.temp_crit,
        }

    def paths_message(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self.lock:
            def p(kind: str) -> Optional[Dict[str, Any]]:
                v = self.paths.get(kind)
                if v is None:
                    return None
                return {"frame": v["frame"], "points": v["points"], "age_s": _r(now - v["rx"], 1),
                        "length_m": _r(v["length"], 2)}
            frontiers = None
            if self.frontiers is not None:
                frontiers = {"count": self.frontiers["count"], "points": self.frontiers["points"],
                             "frame": self.frontiers["frame"], "age_s": _r(now - self.frontiers["rx"], 1)}
            return {
                "type": "paths",
                "server_time": time.time(),
                "global": p("global"),
                "local": p("local"),
                "frontiers": frontiers,
                "trail": self.tracker.trail_payload(now),
            }

    def map_snapshot(self) -> Tuple[int, Optional[Dict[str, Any]]]:
        with self.lock:
            return self.map_version, self.map_raw


class MotionTracker:
    """Distance, trail, stationary and stall detection.

    Updated from the telemetry tick (not the ROS thread) so its cost is bounded
    by rates.telemetry_hz regardless of how fast odometry is published.
    Only VALID (fresh) poses are integrated, so stale data never adds distance.
    """

    def __init__(self, cfg: Dict[str, Any]):
        ex = cfg["exploration"]
        self.stationary_speed = float(ex["stationary_speed_mps"])
        self.stationary_after = float(ex["stationary_after_s"])
        self.stall_after = float(ex["stall_after_s"])
        self.trail_step = float(ex["min_trail_step_m"])
        self.max_trail = int(ex["max_trail_points"])
        self.jitter = float(ex["jitter_threshold_m"])
        self.distance = 0.0
        self.last_xy: Optional[Tuple[float, float, str]] = None
        self.trail: Deque[Tuple[float, float, float]] = deque(maxlen=self.max_trail)
        self.trail_frame: Optional[str] = None
        self.history: Deque[Tuple[float, float, float]] = deque(maxlen=600)  # (t, x, y) ~60 s at 10 Hz
        self.motion_started: Optional[float] = None
        self.last_moving: Optional[float] = None
        self.stalled = False
        self.stall_events = 0
        self.stalled_since: Optional[float] = None
        self.max_frontiers = 0
        self.est_vel: Optional[Dict[str, Any]] = None

    def estimated_velocity(self) -> Optional[Dict[str, Any]]:
        return None if self.est_vel is None else dict(self.est_vel, age_s=time.monotonic() - self.est_vel["rx"])

    def update(self, now: float, pose: Optional[Dict[str, Any]], vel: Optional[Dict[str, Any]],
               nav_active: bool, cmd_active: bool, frontiers: Optional[Dict[str, Any]],
               state_topic: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        valid = bool(pose and pose.get("valid"))
        if valid:
            x, y, frame = pose["x"], pose["y"], pose["frame"]
            if self.last_xy is not None and self.last_xy[2] == frame:
                d = math.hypot(x - self.last_xy[0], y - self.last_xy[1])
                if d >= self.jitter:
                    if d < 2.0:  # ignore teleports (SLAM jumps, frame switches)
                        self.distance += d
                    self.last_xy = (x, y, frame)
            else:
                self.last_xy = (x, y, frame)
            if self.history and len(self.history) >= 2:
                t0, x0, y0 = self.history[-1]
                dt = now - t0
                if dt > 0:
                    self.est_vel = {"linear": None, "lateral": None, "angular": None,
                                    "speed": math.hypot(x - x0, y - y0) / dt, "rx": now, "source": "estimated"}
            self.history.append((now, x, y))
            if self.trail_frame != frame:
                self.trail.clear()
                self.trail_frame = frame
            if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= self.trail_step:
                self.trail.append((x, y, time.time()))

        speed = None
        if vel is not None and vel.get("valid") and vel.get("speed") is not None:
            speed = vel["speed"]
            if vel.get("angular") is not None and abs(vel["angular"]) > 0.15:
                speed = max(speed, self.stationary_speed + 1e-3)  # turning on the spot counts as moving
        moving = valid and speed is not None and speed > self.stationary_speed
        if moving:
            self.last_moving = now
            if self.motion_started is None:
                self.motion_started = now
        stationary_s = None
        if valid:
            ref = self.last_moving if self.last_moving is not None else (self.history[0][0] if self.history else now)
            stationary_s = max(0.0, now - ref)

        # stall: trying to move (goal active or non-zero cmd_vel) but < 0.10 m displacement over window
        trying = nav_active or cmd_active
        displacement = None
        if valid and self.history:
            old = [h for h in self.history if now - h[0] >= self.stall_after]
            if old:
                h = old[-1]
                displacement = math.hypot(pose["x"] - h[1], pose["y"] - h[2])
        stalled = bool(trying and displacement is not None and displacement < 0.10)
        if stalled and not self.stalled:
            self.stall_events += 1
            self.stalled_since = now
        if not stalled:
            self.stalled_since = None
        self.stalled = stalled

        fcount = None
        if frontiers is not None:
            fcount = frontiers["count"]
            self.max_frontiers = max(self.max_frontiers, fcount)

        if state_topic is not None and now - state_topic["rx"] < 10.0:
            state, source = state_topic["value"], "topic"
        else:
            source = "inferred"
            if not valid:
                state = "NO POSE"
            elif stalled:
                state = "STALLED"
            elif fcount == 0 and self.max_frontiers > 0 and not nav_active and not moving:
                state = "COMPLETE?"
            elif nav_active and moving:
                state = "NAVIGATING"
            elif nav_active:
                state = "GOAL ACTIVE"
            elif moving:
                state = "MOVING"
            elif stationary_s is not None and stationary_s >= self.stationary_after:
                state = "STATIONARY"
            else:
                state = "IDLE"

        return {
            "state": state,
            "state_source": source,
            "frontier_count": fcount,
            "distance_travelled_m": _r(self.distance, 2),
            "runtime_s": _r(now - self.motion_started, 1) if self.motion_started is not None else None,
            "stationary_s": _r(stationary_s, 1),
            "stalled": stalled,
            "stalled_for_s": _r(now - self.stalled_since, 1) if self.stalled_since else None,
            "stall_events": self.stall_events,
            "moving": moving,
        }

    def trail_payload(self, now: float) -> Dict[str, Any]:
        return {"frame": self.trail_frame, "points": [[round(x, 2), round(y, 2)] for x, y, _ in self.trail]}
