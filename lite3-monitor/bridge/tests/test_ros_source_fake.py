"""Exercise ros_source.py against a FAKE rclpy (no ROS install needed).

This checks role resolution, QoS selection, message handlers and the
read-only audit. It does NOT prove behaviour against real rclpy/DDS; that
must be verified on the NUC (see HANDOVER.md).
"""
import enum
import math
import sys
import time
import types
from types import SimpleNamespace as NS

import pytest


# ----------------------------------------------------------------- fake rclpy
class Reliability(enum.Enum):
    RELIABLE = 1
    BEST_EFFORT = 2


class Durability(enum.Enum):
    TRANSIENT_LOCAL = 1
    VOLATILE = 2


class History(enum.Enum):
    KEEP_LAST = 1


class QoSProfile:
    def __init__(self, history=None, depth=10, reliability=None, durability=None):
        self.history, self.depth, self.reliability, self.durability = history, depth, reliability, durability


class FakeNode:
    graph = {}
    pub_info = {}

    def __init__(self, name, enable_rosout=True, start_parameter_services=True):
        self.name = name
        self.subs = []
        self._publishers = [NS(topic_name="/parameter_events")]
        self._parameter_event_publisher = self._publishers[0]

    @property
    def publishers(self):
        return iter(self._publishers)

    services = property(lambda self: iter([]))
    clients = property(lambda self: iter([]))

    def destroy_publisher(self, pub):
        self._publishers.remove(pub)

    def create_timer(self, *a, **k):
        return None

    def create_subscription(self, cls, name, cb, qos, raw=False):
        self.subs.append(NS(cls=cls, name=name, cb=cb, qos=qos, raw=raw))
        return self.subs[-1]

    def get_topic_names_and_types(self):
        return [(k, v) for k, v in self.graph.items()]

    def get_node_names_and_namespaces(self):
        return [("slam_toolbox", "/"), ("lite3_monitor_readonly", "/")]

    def get_publishers_info_by_topic(self, name):
        return self.pub_info.get(name, [NS(node_name="pub", node_namespace="/",
                                           qos_profile=NS(durability=Durability.VOLATILE,
                                                          reliability=Reliability.RELIABLE))])


@pytest.fixture()
def ros_source(monkeypatch):
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda args=None: None
    rclpy.ok = lambda: False
    rclpy.shutdown = lambda: None
    node_mod = types.ModuleType("rclpy.node")
    node_mod.Node = FakeNode
    qos_mod = types.ModuleType("rclpy.qos")
    qos_mod.QoSProfile, qos_mod.ReliabilityPolicy, qos_mod.DurabilityPolicy, qos_mod.HistoryPolicy = (
        QoSProfile, Reliability, Durability, History)
    exe_mod = types.ModuleType("rclpy.executors")
    exe_mod.SingleThreadedExecutor = lambda: NS(add_node=lambda n: None, spin=lambda: None,
                                                shutdown=lambda timeout_sec=None: None)
    ser_mod = types.ModuleType("rclpy.serialization")
    ser_mod.deserialize_message = lambda raw, cls: raw
    rosidl = types.ModuleType("rosidl_runtime_py")
    util = types.ModuleType("rosidl_runtime_py.utilities")
    util.get_message = lambda t: type(t.replace("/", "_"), (), {})
    for name, mod in {"rclpy": rclpy, "rclpy.node": node_mod, "rclpy.qos": qos_mod, "rclpy.executors": exe_mod,
                      "rclpy.serialization": ser_mod, "rosidl_runtime_py": rosidl,
                      "rosidl_runtime_py.utilities": util}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "lite3_bridge.ros_source", raising=False)
    from lite3_bridge import ros_source
    return ros_source


def make(ros_source, graph, pub_info=None):
    from lite3_bridge.config import load_config
    from lite3_bridge.state import TelemetryStore
    FakeNode.graph = graph
    FakeNode.pub_info = pub_info or {}
    cfg = load_config()
    store = TelemetryStore(cfg, "ros")
    src = ros_source.RosSource(store, cfg)
    src.start()
    return src, store


def sub_for(src, name):
    return [s for s in src.node.subs if s.name == name][0]


def pose_msg(x, y, yaw):
    return NS(position=NS(x=x, y=y, z=0.0), orientation=NS(x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2)))


def test_audit_removes_parameter_event_publisher_and_resolves_roles(ros_source):
    src, store = make(ros_source, {
        "/leg_odom2": ["nav_msgs/msg/Odometry"],
        "/odom": ["nav_msgs/msg/Odometry"],
        "/scan": ["sensor_msgs/msg/LaserScan"],
        "/map": ["nav_msgs/msg/OccupancyGrid"],
        "/tf": ["tf2_msgs/msg/TFMessage"],
        "/imu/data": ["sensor_msgs/msg/Imu"],
        "/weird": ["custom/msg/Thing"],
    })
    assert list(src.node.publishers) == []
    assert src.audit_ok
    assert store.roles["odometry"] == "/leg_odom2"  # first candidate that exists wins
    assert store.roles["scan"] == "/scan"
    assert store.roles["goal"] is None
    assert all(s.raw for s in src.node.subs)
    # rate-only roles are never decoded
    assert not store.topics["/scan"].decoded and store.topics["/leg_odom2"].decoded
    # map publisher is volatile+reliable -> reliable volatile subscription (compatible)
    q = sub_for(src, "/map").qos
    assert q.reliability == Reliability.RELIABLE and q.durability == Durability.VOLATILE
    # sensor topics -> best effort
    assert sub_for(src, "/scan").qos.reliability == Reliability.BEST_EFFORT


def test_audit_fails_if_a_publisher_exists(ros_source):
    src, _ = make(ros_source, {})
    src.node._publishers.append(NS(topic_name="/cmd_vel"))
    with pytest.raises(RuntimeError, match="READ-ONLY AUDIT FAILED"):
        src._audit("test")


def test_transient_local_map_gets_latched_qos(ros_source):
    info = [NS(node_name="map_server", node_namespace="/",
               qos_profile=NS(durability=Durability.TRANSIENT_LOCAL, reliability=Reliability.RELIABLE))]
    src, _ = make(ros_source, {"/map": ["nav_msgs/msg/OccupancyGrid"]}, {"/map": info})
    q = sub_for(src, "/map").qos
    assert q.durability == Durability.TRANSIENT_LOCAL and q.depth == 1


def test_wrong_type_is_reported_not_subscribed(ros_source):
    src, store = make(ros_source, {"/scan": ["sensor_msgs/msg/PointCloud2"]})
    assert store.roles["scan"] is None
    assert "unexpected type" in store.topics["/scan"].error
    assert not any(s.name == "/scan" for s in src.node.subs)


def test_handlers_tf_odom_map_path_status_frontiers_diag(ros_source):
    src, store = make(ros_source, {
        "/tf": ["tf2_msgs/msg/TFMessage"],
        "/odom": ["nav_msgs/msg/Odometry"],
        "/map": ["nav_msgs/msg/OccupancyGrid"],
        "/plan": ["nav_msgs/msg/Path"],
        "/navigate_to_pose/_action/status": ["action_msgs/msg/GoalStatusArray"],
        "/explore/frontiers": ["visualization_msgs/msg/MarkerArray"],
        "/diagnostics": ["diagnostic_msgs/msg/DiagnosticArray"],
    })
    hdr = lambda f: NS(frame_id=f)  # noqa: E731
    tr = lambda p, c, x: NS(header=hdr(p), child_frame_id=c,  # noqa: E731
                            transform=NS(translation=NS(x=x, y=0.0, z=0.0), rotation=NS(x=0.0, y=0.0, z=0.0, w=1.0)))
    sub_for(src, "/tf").cb(NS(transforms=[tr("map", "odom", 1.0), tr("odom", "base_link", 2.0)]))
    pose = store.pose_snapshot(time.monotonic())["pose"]
    assert pose["frame"] == "map" and math.isclose(pose["x"], 3.0) and pose["valid"]

    sub_for(src, "/odom").cb(NS(header=hdr("odom"), pose=NS(pose=pose_msg(1, 2, 0.5)),
                                twist=NS(twist=NS(linear=NS(x=0.3, y=0.0), angular=NS(z=0.1)))))
    assert store.odom["vx"] == 0.3 and math.isclose(store.odom["yaw"], 0.5)

    import array
    grid = array.array("b", [-1] * 50 + [0] * 40 + [100] * 10)
    sub_for(src, "/map").cb(NS(header=hdr("map"), info=NS(width=10, height=10, resolution=0.05,
                                                         origin=pose_msg(-1, -1, 0)), data=grid))
    assert store.map_raw["data"].count(0xFF) == 50 and store.map_version == 1

    # path in odom frame is transformed into map frame (+1 m in x)
    sub_for(src, "/plan").cb(NS(header=hdr("odom"), poses=[NS(pose=pose_msg(0, 0, 0)), NS(pose=pose_msg(1, 0, 0))]))
    assert store.paths["global"]["frame"] == "map"
    assert store.paths["global"]["points"][0] == [1.0, 0.0] and math.isclose(store.paths["global"]["length"], 1.0)

    st = lambda code, sec: NS(status=code, goal_info=NS(stamp=NS(sec=sec, nanosec=0)))  # noqa: E731
    sub_for(src, "/navigate_to_pose/_action/status").cb(NS(status_list=[st(4, 1), st(2, 5)]))
    assert store.nav_status["status"] == "EXECUTING"

    mk = lambda t, a, x: NS(type=t, action=a, header=hdr("map"), pose=NS(position=NS(x=x, y=0.0)), points=[])  # noqa: E731
    sub_for(src, "/explore/frontiers").cb(NS(markers=[mk(2, 0, 1.0), mk(2, 0, 2.0), mk(8, 0, 0.0), mk(2, 2, 9.0)]))
    assert store.frontiers["count"] == 2

    sub_for(src, "/diagnostics").cb(NS(status=[NS(name="lidar", level=b"\x02", message="timeout"),
                                               NS(name="imu", level=b"\x00", message="OK")]))
    assert store.diagnostics["summary"]["error"] == 1 and store.diagnostics["summary"]["ok"] == 1


def test_decoding_is_throttled_but_counting_is_not(ros_source):
    src, store = make(ros_source, {"/odom": ["nav_msgs/msg/Odometry"]})
    calls = []
    src._on_odometry = lambda m, now: calls.append(now)  # noqa: E731 - handler bound at subscribe time
    cb = src._make_callback("odometry", "/odom", object, "nav_msgs/msg/Odometry")
    for _ in range(100):
        cb(b"raw")
    assert store.topics["/odom"].total == 100
    assert len(calls) <= 2


def test_status_flags_subscribed_and_false_is_error(ros_source):
    src, store = make(ros_source, {"/sensor_status/imu_isalive": ["std_msgs/msg/Bool"],
                                   "/sensor_status/joint_isalive": ["std_msgs/msg/Float64"]})
    sub = sub_for(src, "/sensor_status/imu_isalive")
    sub.cb(NS(data=True))
    assert store.topics["/sensor_status/imu_isalive"].flag_value is True
    sub.cb(NS(data=False))
    h = {t["name"]: t for t in store.health_message({})["topics"]}
    imu = h["/sensor_status/imu_isalive"]
    assert imu["value"] is False and imu["status"] == "error" and "NOT alive" in imu["note"]
    assert imu["label"] == "IMU"
    # wrong type is reported, not subscribed
    assert "unexpected type" in h["/sensor_status/joint_isalive"]["note"]
    assert not any(s.name == "/sensor_status/joint_isalive" for s in src.node.subs)
    # configured but absent from the graph -> missing
    assert h["/sensor_status/ultrasound_isalive"]["status"] == "missing"
