"""Read-only ROS 2 telemetry source (runs on the NUC).

SAFETY CONTRACT - enforced by tools/check_readonly.py and by a runtime audit:
  * Only `create_subscription` and `create_timer` are used on the node.
  * No publishers, service clients/servers, action clients/servers.
  * No parameters are declared, set or queried on other nodes.
  * rosout and parameter services are disabled for this node; the rclpy
    built-in /parameter_events publisher is destroyed right after creation.
  * Graph introspection (topic/node names, publisher info) is passive.

All subscriptions use raw (undecoded) mode where available. Messages are
deserialised only for roles we actually display, and those are throttled.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from .geom import compose, yaw_from_quat
from .mapcodec import int8_to_bytes
from .sim import set_diagnostics
from .state import NAV_STATUS_NAMES, TelemetryStore

log = logging.getLogger("lite3_bridge.ros")

NODE_NAME = "lite3_monitor_readonly"

# Roles whose content we decode. Everything else is counted only.
DECODED_ROLES = {"map", "odometry", "tf", "tf_static", "global_plan", "local_plan", "goal", "nav_status",
                 "frontiers", "exploration_state", "diagnostics", "cmd_vel", "status_flag"}
# Rare / latched roles: always decode (never throttled).
UNTHROTTLED_ROLES = {"map", "tf_static", "goal", "nav_status", "exploration_state", "status_flag"}
FLAG_TYPE = "std_msgs/msg/Bool"
# Roles where we prefer RELIABLE (if every publisher offers it) so large or
# rare messages are not silently lost.
RELIABLE_ROLES = {"map", "tf_static", "goal", "nav_status", "frontiers", "exploration_state", "global_plan"}
TF_MAX_MSGS_PER_S = 400.0
MAX_PATH_POINTS = 300


def _q(o: Any) -> Tuple[float, float, float, float]:
    return (o.x, o.y, o.z, o.w)


def _downsample(points: List[List[float]], n: int) -> List[List[float]]:
    if len(points) <= n:
        return points
    step = len(points) / float(n)
    out = [points[int(i * step)] for i in range(n)]
    out[-1] = points[-1]
    return out


def _path_length(points: List[List[float]]) -> float:
    return sum(math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))


class RosSource:
    def __init__(self, store: TelemetryStore, cfg: Dict[str, Any]):
        self.store = store
        self.cfg = cfg
        self.node: Optional[Node] = None
        self.executor: Optional[SingleThreadedExecutor] = None
        self.thread: Optional[threading.Thread] = None
        self.subs: Dict[str, Any] = {}               # topic name -> subscription
        self.decode_interval = 1.0 / float(cfg["rates"]["decode_hz"])
        self.last_decode: Dict[str, float] = {}
        self.tf_budget = TF_MAX_MSGS_PER_S
        self.tf_budget_t = time.monotonic()
        self.diag_items: Dict[str, Dict[str, Any]] = {}
        self.audit_ok = False

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        rclpy.init(args=None)
        self.node = Node(NODE_NAME, enable_rosout=False, start_parameter_services=False)
        self._drop_parameter_event_publisher()
        self._audit("startup")
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.node.create_timer(float(self.cfg["rates"]["graph_scan_interval_s"]), self._scan_graph)
        self._register_static_roles()
        self._scan_graph()
        self.thread = threading.Thread(target=self._spin, name="ros-spin", daemon=True)
        self.thread.start()

    def _drop_parameter_event_publisher(self) -> None:
        pub = getattr(self.node, "_parameter_event_publisher", None)
        if pub is not None:
            try:
                self.node.destroy_publisher(pub)
                self.node._parameter_event_publisher = None  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover - depends on rclpy version
                log.warning("could not destroy built-in /parameter_events publisher: %s", exc)

    def _audit(self, when: str) -> None:
        """Abort if this node owns any interface that could affect the robot."""
        node = self.node
        pubs = [p.topic_name for p in node.publishers]
        services = [s.srv_name for s in node.services]
        clients = [c.srv_name for c in node.clients]
        problems = []
        if pubs:
            problems.append(f"publishers={pubs}")
        if services:
            problems.append(f"services={services}")
        if clients:
            problems.append(f"clients={clients}")
        if problems:
            msg = f"READ-ONLY AUDIT FAILED ({when}): " + ", ".join(problems)
            log.critical(msg)
            raise RuntimeError(msg)
        self.audit_ok = True
        log.info("read-only audit passed (%s): 0 publishers, 0 services, 0 clients", when)

    def _spin(self) -> None:
        try:
            self.executor.spin()
        except Exception:  # pragma: no cover
            log.exception("ROS executor stopped")
            with self.store.lock:
                self.store.source_status = {"ok": False, "message": "ROS executor stopped"}

    def stop(self) -> None:
        try:
            if self.executor is not None:
                self.executor.shutdown(timeout_sec=1.0)
            if self.node is not None:
                self.node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # pragma: no cover
            log.exception("error during ROS shutdown")

    def link_is_down(self) -> bool:
        return False

    def _register_static_roles(self) -> None:
        for extra in self.cfg.get("extra_health_topics") or []:
            self.store.register_topic("extra", extra["name"], expected_hz=extra.get("expected_hz"),
                                      min_hz=extra.get("min_hz"))
        for flag in self.cfg.get("status_flags") or []:
            self.store.register_topic("status_flag", flag["name"], label=flag.get("label") or flag["name"],
                                      expected_hz=flag.get("expected_hz"), min_hz=flag.get("min_hz"),
                                      type=FLAG_TYPE)

    # -------------------------------------------------------------- discovery
    def _scan_graph(self) -> None:
        node = self.node
        try:
            names_types = dict(node.get_topic_names_and_types())
            nodes = sorted(
                (ns.rstrip("/") + "/" + n) if ns != "/" else "/" + n
                for n, ns in node.get_node_names_and_namespaces()
                if n != NODE_NAME
            )
        except Exception as exc:
            log.warning("graph scan failed: %s", exc)
            return
        s = self.store
        with s.lock:
            s.graph = {"nodes": nodes, "topics": [[k, list(v)] for k, v in sorted(names_types.items())],
                       "rx": time.monotonic()}
            s.source_status = {"ok": True, "message": f"ROS graph: {len(nodes)} nodes, {len(names_types)} topics"}

        for role, spec in self.cfg["topics"].items():
            current = s.roles.get(role)
            if current is not None and current in self.subs:
                continue
            for cand in spec.get("candidates") or []:
                if cand not in names_types:
                    continue
                types = [t for t in names_types[cand] if t in spec["types"]]
                if not types:
                    st = s.register_topic(role, cand, type=",".join(names_types[cand]), available=True,
                                          expected_hz=spec.get("expected_hz"), min_hz=spec.get("min_hz"),
                                          single_publisher=bool(spec.get("single_publisher")))
                    st.error = f"unexpected type {names_types[cand]} (accepted: {spec['types']})"
                    continue
                s.roles[role] = cand
                s.register_topic(role, cand, type=types[0], available=True, decoded=role in DECODED_ROLES,
                                 expected_hz=spec.get("expected_hz"), min_hz=spec.get("min_hz"),
                                 single_publisher=bool(spec.get("single_publisher")))
                self._subscribe(role, cand, types[0])
                break

        for extra in self.cfg.get("extra_health_topics") or []:
            name = extra["name"]
            if name in names_types and name not in self.subs:
                s.register_topic("extra", name, type=names_types[name][0], available=True)
                self._subscribe("extra", name, names_types[name][0])

        for flag in self.cfg.get("status_flags") or []:
            name = flag["name"]
            if name in names_types and name not in self.subs:
                st = s.topics[name]
                if FLAG_TYPE not in names_types[name]:
                    st.error = f"unexpected type {names_types[name]} (expected {FLAG_TYPE})"
                    continue
                st.available = True
                st.decoded = True
                self._subscribe("status_flag", name, FLAG_TYPE)

        # publisher counts and availability for everything we track
        for name, st in list(s.topics.items()):
            st.available = name in names_types
            if not st.available:
                continue
            try:
                infos = node.get_publishers_info_by_topic(name)
            except Exception:
                continue
            st.publishers = len(infos)
            st.publisher_nodes = sorted({(i.node_namespace.rstrip("/") + "/" + i.node_name) for i in infos})
        self._audit("graph-scan")

    def _qos_for(self, role: str, name: str) -> QoSProfile:
        try:
            infos = self.node.get_publishers_info_by_topic(name)
        except Exception:
            infos = []
        all_transient = bool(infos) and all(i.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL for i in infos)
        all_reliable = bool(infos) and all(i.qos_profile.reliability == ReliabilityPolicy.RELIABLE for i in infos)
        if role == "tf_static":
            return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=100,
                              reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        reliable = role in RELIABLE_ROLES and all_reliable
        durability = DurabilityPolicy.TRANSIENT_LOCAL if (all_transient and reliable) else DurabilityPolicy.VOLATILE
        return QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1 if role == "map" else 5,
            reliability=ReliabilityPolicy.RELIABLE if reliable else ReliabilityPolicy.BEST_EFFORT,
            durability=durability,
        )

    def _subscribe(self, role: str, name: str, type_str: str) -> None:
        st = self.store.topics[name]
        try:
            msg_cls = get_message(type_str)
        except Exception as exc:
            st.error = f"cannot import {type_str} ({exc}); source the workspace that defines it"
            log.warning("%s: %s", name, st.error)
            return
        qos = self._qos_for(role, name)
        cb = self._make_callback(role, name, msg_cls, type_str)
        try:
            sub = self.node.create_subscription(msg_cls, name, cb, qos, raw=True)
        except TypeError:  # rclpy without raw support: receive decoded messages
            sub = self.node.create_subscription(msg_cls, name, cb, qos)
        self.subs[name] = sub
        st.subscribed = True
        st.error = None
        log.info("subscribed (read-only) %s [%s] role=%s reliability=%s durability=%s", name, type_str, role,
                 qos.reliability.name, qos.durability.name)

    # -------------------------------------------------------------- callbacks
    def _make_callback(self, role: str, name: str, msg_cls: Any, type_str: str) -> Callable[[Any], None]:
        store = self.store
        decode = role in DECODED_ROLES
        throttled = role not in UNTHROTTLED_ROLES and role != "tf"
        handler = self._handler_for(role, type_str)
        if role == "status_flag":
            handler = lambda m, now, _name=name: self._on_flag(_name, m, now)  # noqa: E731

        def cb(raw: Any) -> None:
            now = time.monotonic()
            store.topic_rx(name, 1, now)
            if not decode or handler is None:
                return
            if role == "tf" and not self._tf_take(now):
                return
            if throttled:
                if now - self.last_decode.get(name, 0.0) < self.decode_interval:
                    return
                self.last_decode[name] = now
            try:
                msg = deserialize_message(raw, msg_cls) if isinstance(raw, (bytes, bytearray)) else raw
                handler(msg, now)
            except Exception as exc:
                st = store.topics.get(name)
                if st is not None:
                    st.error = f"decode error: {exc}"
                log.debug("decode error on %s", name, exc_info=True)

        return cb

    def _tf_take(self, now: float) -> bool:
        self.tf_budget = min(TF_MAX_MSGS_PER_S, self.tf_budget + (now - self.tf_budget_t) * TF_MAX_MSGS_PER_S)
        self.tf_budget_t = now
        if self.tf_budget >= 1.0:
            self.tf_budget -= 1.0
            return True
        self.store.tf_dropped += 1
        return False

    def _handler_for(self, role: str, type_str: str) -> Optional[Callable[[Any, float], None]]:
        short = type_str.split("/")[-1]
        if role == "odometry":
            return self._on_odometry
        if role in ("tf", "tf_static"):
            static = role == "tf_static"
            return lambda m, now: self._on_tf(m, now, static)
        if role == "map":
            return self._on_map
        if role in ("global_plan", "local_plan"):
            kind = "global" if role == "global_plan" else "local"
            return lambda m, now: self._on_path(m, now, kind)
        if role == "goal":
            return self._on_goal
        if role == "nav_status":
            return self._on_nav_status
        if role == "frontiers":
            return self._on_frontiers_markers if short == "MarkerArray" else self._on_frontiers_poses
        if role == "exploration_state":
            return self._on_exploration_state
        if role == "diagnostics":
            return self._on_diagnostics
        if role == "cmd_vel":
            return self._on_cmd_vel
        if role == "status_flag":
            return lambda m, now, _short=short: None  # replaced per topic in _make_callback
        return None

    # helpers --------------------------------------------------------------
    def _to_map(self, frame: str, pts: List[List[float]]) -> Tuple[str, List[List[float]]]:
        """Transform 2D points into the map frame when the TF chain is known."""
        frame = frame.lstrip("/")
        map_frame = self.cfg["frames"]["map"]
        if frame == map_frame or not frame:
            return map_frame if not frame else frame, pts
        with self.store.lock:
            ch = self.store._chain(frame, map_frame, time.monotonic())
        if ch is None:
            return frame, pts
        out = []
        for x, y in pts:
            t, _ = compose(ch["t"], ch["q"], (x, y, 0.0), (0.0, 0.0, 0.0, 1.0))
            out.append([round(t[0], 3), round(t[1], 3)])
        return map_frame, out

    # handlers -------------------------------------------------------------
    def _on_odometry(self, msg: Any, now: float) -> None:
        frame = msg.header.frame_id.lstrip("/")
        twist = None
        if hasattr(msg, "twist") and hasattr(msg.twist, "twist"):
            twist = msg.twist.twist
            pose = msg.pose.pose
        elif hasattr(msg.pose, "pose"):  # PoseWithCovarianceStamped
            pose = msg.pose.pose
        else:  # PoseStamped
            pose = msg.pose
        rec = {"x": pose.position.x, "y": pose.position.y, "yaw": yaw_from_quat(_q(pose.orientation)),
               "frame": frame or self.cfg["frames"]["odom"], "rx": now,
               "vx": None, "vy": None, "wz": None}
        if twist is not None:
            rec.update(vx=twist.linear.x, vy=twist.linear.y, wz=twist.angular.z)
        with self.store.lock:
            self.store.odom = rec

    def _on_tf(self, msg: Any, now: float, static: bool) -> None:
        for t in msg.transforms:
            tr = t.transform.translation
            self.store.set_tf(t.header.frame_id, t.child_frame_id, (tr.x, tr.y, tr.z), _q(t.transform.rotation),
                              static=static, now=now)

    def _on_map(self, msg: Any, now: float) -> None:
        info = msg.info
        o = info.origin
        data = int8_to_bytes(msg.data)
        with self.store.lock:
            self.store.map_raw = {"data": data, "width": info.width, "height": info.height,
                                  "resolution": info.resolution,
                                  "origin": (o.position.x, o.position.y, yaw_from_quat(_q(o.orientation))),
                                  "frame": msg.header.frame_id.lstrip("/") or self.cfg["frames"]["map"], "rx": now}
            self.store.map_version += 1

    def _on_path(self, msg: Any, now: float, kind: str) -> None:
        pts = [[p.pose.position.x, p.pose.position.y] for p in msg.poses]
        length = _path_length(pts)
        frame, pts = self._to_map(msg.header.frame_id, _downsample(pts, MAX_PATH_POINTS))
        with self.store.lock:
            self.store.paths[kind] = {"frame": frame, "points": [[round(x, 3), round(y, 3)] for x, y in pts],
                                      "rx": now, "length": length}

    def _on_goal(self, msg: Any, now: float) -> None:
        p = msg.pose
        frame, pts = self._to_map(msg.header.frame_id, [[p.position.x, p.position.y]])
        with self.store.lock:
            self.store.goal = {"x": pts[0][0], "y": pts[0][1], "yaw": yaw_from_quat(_q(p.orientation)),
                               "frame": frame, "rx": now}

    def _on_nav_status(self, msg: Any, now: float) -> None:
        status = "NONE"
        if msg.status_list:
            latest = max(msg.status_list,
                         key=lambda s: (s.goal_info.stamp.sec, s.goal_info.stamp.nanosec))
            status = NAV_STATUS_NAMES.get(int(latest.status), str(latest.status))
        with self.store.lock:
            self.store.nav_status = {"status": status, "rx": now}

    def _on_frontiers_markers(self, msg: Any, now: float) -> None:
        spheres, others, frame = [], [], ""
        for m in msg.markers:
            if m.action != 0:  # ADD/MODIFY only
                continue
            frame = frame or m.header.frame_id
            if m.type == 2:  # SPHERE
                spheres.append([m.pose.position.x, m.pose.position.y])
            elif m.points:
                xs = [p.x for p in m.points]
                ys = [p.y for p in m.points]
                others.append([sum(xs) / len(xs), sum(ys) / len(ys)])
            else:
                others.append([m.pose.position.x, m.pose.position.y])
        pts = spheres if spheres else others
        frame, pts = self._to_map(frame, pts[:200])
        with self.store.lock:
            self.store.frontiers = {"count": len(spheres) if spheres else len(others),
                                    "points": [[round(x, 2), round(y, 2)] for x, y in pts],
                                    "frame": frame, "rx": now}

    def _on_frontiers_poses(self, msg: Any, now: float) -> None:
        pts = [[p.position.x, p.position.y] for p in msg.poses]
        frame, pts = self._to_map(msg.header.frame_id, pts[:200])
        with self.store.lock:
            self.store.frontiers = {"count": len(msg.poses), "points": [[round(x, 2), round(y, 2)] for x, y in pts],
                                    "frame": frame, "rx": now}

    def _on_exploration_state(self, msg: Any, now: float) -> None:
        with self.store.lock:
            self.store.exploration_state = {"value": str(msg.data)[:64], "rx": now}

    def _on_diagnostics(self, msg: Any, now: float) -> None:
        for s in msg.status:
            lvl = s.level
            if isinstance(lvl, (bytes, bytearray)):
                lvl = lvl[0]
            self.diag_items[s.name] = {"name": s.name[:96], "level": int(lvl), "message": s.message[:160], "rx": now}
        # forget statuses not refreshed for 30 s; cap memory
        for k in [k for k, v in self.diag_items.items() if now - v["rx"] > 30.0]:
            del self.diag_items[k]
        if len(self.diag_items) > 500:
            for k in sorted(self.diag_items, key=lambda k: self.diag_items[k]["rx"])[:100]:
                del self.diag_items[k]
        items = [{k: v for k, v in it.items() if k != "rx"} for it in self.diag_items.values()]
        set_diagnostics(self.store, items)

    def _on_flag(self, name: str, msg: Any, now: float) -> None:
        st = self.store.topics.get(name)
        if st is not None:
            st.flag_value = bool(msg.data)

    def _on_cmd_vel(self, msg: Any, now: float) -> None:
        tw = msg.twist if hasattr(msg, "twist") else msg
        with self.store.lock:
            self.store.cmd_vel = {"linear": math.hypot(tw.linear.x, tw.linear.y), "angular": tw.angular.z, "rx": now}
