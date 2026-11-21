"""Read-only ROS 2 discovery report (run on the NUC, only after approval).

    python3 -m lite3_bridge.discover --seconds 8 --json report.json

What it does (all passive):
  * lists nodes, topics + types, services + types (names only, never called)
  * lists action names inferred from /_action/status topics
  * samples message rates for N seconds using raw best-effort subscriptions
    (no deserialisation, except /tf and /tf_static to list TF frames)
  * prints publisher counts per topic (more than one publisher on /odom or
    /scan may mean another robot is on the same ROS_DOMAIN_ID)

It never publishes, calls services/actions, or reads/writes parameters.
Point-cloud and image topics are skipped by default (--include-heavy to
sample them).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from typing import Any, Dict

HEAVY_TYPES = ("sensor_msgs/msg/PointCloud2", "sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage",
               "livox_ros_driver2/msg/CustomMsg", "livox_ros_driver/msg/CustomMsg")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only ROS 2 discovery")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--json", help="also write the report as JSON to this path")
    ap.add_argument("--include-heavy", action="store_true", help="also sample point clouds / images")
    args = ap.parse_args(argv)

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    rclpy.init(args=None)
    node = Node("lite3_monitor_discovery", enable_rosout=False, start_parameter_services=False)
    pub = getattr(node, "_parameter_event_publisher", None)
    if pub is not None:
        node.destroy_publisher(pub)
        node._parameter_event_publisher = None

    # let discovery settle
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)

    topics = dict(node.get_topic_names_and_types())
    services = dict(node.get_service_names_and_types())
    nodes = sorted((ns.rstrip("/") + "/" + n) for n, ns in node.get_node_names_and_namespaces())
    counts: Dict[str, int] = {t: 0 for t in topics}
    tf_edges: Dict[str, Dict[str, Any]] = {}
    subs = []
    skipped = []

    best_effort = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10,
                             reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
    latched = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=100,
                         reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)

    for name, types in topics.items():
        t = types[0]
        if t in HEAVY_TYPES and not args.include_heavy:
            skipped.append(name)
            continue
        try:
            cls = get_message(t)
        except Exception:
            skipped.append(name)
            continue
        is_tf = name in ("/tf", "/tf_static")

        def cb(raw, name=name, cls=cls, is_tf=is_tf):
            counts[name] += 1
            if is_tf:
                msg = deserialize_message(raw, cls)
                for tr in msg.transforms:
                    tf_edges[tr.child_frame_id] = {"parent": tr.header.frame_id, "static": name == "/tf_static"}

        qos = latched if name == "/tf_static" else best_effort
        try:
            subs.append(node.create_subscription(cls, name, cb, qos, raw=True))
        except TypeError:
            skipped.append(name)

    assert not list(node.publishers), "discovery node must not own publishers"
    assert not list(node.clients) and not list(node.services), "discovery node must not own services/clients"

    t0 = time.monotonic()
    while time.monotonic() - t0 < args.seconds:
        rclpy.spin_once(node, timeout_sec=0.05)
    elapsed = time.monotonic() - t0

    report: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "ros_domain_id": os.environ.get("ROS_DOMAIN_ID", "(unset => 0)"),
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION", "(default)"),
        "ros_localhost_only": os.environ.get("ROS_LOCALHOST_ONLY", "0"),
        "sample_seconds": round(elapsed, 1),
        "nodes": nodes,
        "topics": [],
        "actions": sorted(n[: -len("/_action/status")] for n in topics if n.endswith("/_action/status")),
        "services": sorted(f"{n} [{', '.join(t)}]" for n, t in services.items()),
        "tf_edges": tf_edges,
        "skipped_topics": sorted(skipped),
    }
    for name in sorted(topics):
        try:
            infos = node.get_publishers_info_by_topic(name)
        except Exception:
            infos = []
        report["topics"].append({
            "name": name,
            "types": topics[name],
            "rate_hz": None if name in skipped else round(counts.get(name, 0) / elapsed, 2),
            "publishers": len(infos),
            "publisher_nodes": sorted({(i.node_namespace.rstrip("/") + "/" + i.node_name) for i in infos}),
            "durability": sorted({i.qos_profile.durability.name for i in infos}),
            "reliability": sorted({i.qos_profile.reliability.name for i in infos}),
        })

    node.destroy_node()
    rclpy.shutdown()

    print(f"# ROS 2 discovery report - {report['hostname']}")
    print(f"ROS_DOMAIN_ID={report['ros_domain_id']}  RMW={report['rmw_implementation']}  "
          f"LOCALHOST_ONLY={report['ros_localhost_only']}  sampled {report['sample_seconds']} s\n")
    print(f"## Nodes ({len(nodes)})")
    for n in nodes:
        print(f"- {n}")
    print(f"\n## Topics ({len(report['topics'])})")
    print("| topic | type | Hz | pubs | publisher nodes | QoS |")
    print("|---|---|---|---|---|---|")
    for t in report["topics"]:
        hz = "skipped" if t["rate_hz"] is None else f"{t['rate_hz']:.1f}"
        print(f"| {t['name']} | {', '.join(t['types'])} | {hz} | {t['publishers']} | "
              f"{', '.join(t['publisher_nodes'])} | {'/'.join(t['reliability'])} {'/'.join(t['durability'])} |")
    print(f"\n## Actions ({len(report['actions'])})")
    for a in report["actions"]:
        print(f"- {a}")
    print(f"\n## TF edges ({len(tf_edges)})")
    for child, e in sorted(tf_edges.items()):
        print(f"- {e['parent']} -> {child}{' (static)' if e['static'] else ''}")
    print(f"\n## Services ({len(report['services'])}) - names only, none were called")
    for s in report["services"]:
        print(f"- {s}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nJSON written to {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
