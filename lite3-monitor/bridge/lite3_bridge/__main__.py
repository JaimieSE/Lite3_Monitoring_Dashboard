"""Entry point: python -m lite3_bridge [--sim] [--config FILE]

Identity safeguards (ROS mode):
  * refuses to start if identity.expected_hostname is set and differs from
    this machine's hostname;
  * refuses to start if identity.expected_ros_domain_id is set and differs
    from ROS_DOMAIN_ID in the environment;
  * refuses to bind to a non-loopback address unless --allow-remote-bind.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import socket
import sys

from . import __version__
from .config import env_ros_domain_id, is_loopback, load_config
from .state import TelemetryStore

log = logging.getLogger("lite3_bridge")


def machine_fingerprint() -> str:
    """Short, non-reversible id of this machine (from /etc/machine-id when present)."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="ascii") as fh:
                return hashlib.sha256(fh.read().strip().encode()).hexdigest()[:12]
        except OSError:
            continue
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12]


def build_identity(cfg: dict, mode: str) -> dict:
    ident = cfg["identity"]
    hostname = socket.gethostname()
    domain = env_ros_domain_id()
    warnings = []
    if mode == "ros":
        if not ident.get("expected_hostname"):
            warnings.append("identity.expected_hostname not configured - robot identity is unverified")
        if ident.get("expected_ros_domain_id") is None:
            warnings.append("identity.expected_ros_domain_id not configured - ROS domain is unverified")
        if os.environ.get("ROS_DOMAIN_ID") is None:
            warnings.append("ROS_DOMAIN_ID not set (ROS 2 default 0, shared by every unconfigured robot)")
    return {
        "robot_name": ident.get("robot_name") or "Lite3",
        "hostname": "SIMULATOR" if mode == "sim" else hostname,
        "machine_fingerprint": "sim" if mode == "sim" else machine_fingerprint(),
        "ros_domain_id": None if mode == "sim" else (domain if domain is not None else 0),
        "ros_domain_id_explicit": domain is not None,
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION") or "default",
        "ros_localhost_only": os.environ.get("ROS_LOCALHOST_ONLY", "0") == "1",
        "expected_hostname": ident.get("expected_hostname") or None,
        "expected_ros_domain_id": ident.get("expected_ros_domain_id"),
        "verified": mode == "ros" and bool(ident.get("expected_hostname"))
        and ident.get("expected_ros_domain_id") is not None,
        "warnings": warnings,
    }


def check_identity(cfg: dict) -> None:
    ident = cfg["identity"]
    exp_host = ident.get("expected_hostname")
    if exp_host and socket.gethostname() != exp_host:
        sys.exit(f"REFUSING TO START: hostname '{socket.gethostname()}' != expected '{exp_host}'. "
                 "This may be another team's robot.")
    exp_dom = ident.get("expected_ros_domain_id")
    if exp_dom is not None:
        dom = env_ros_domain_id()
        dom = 0 if dom is None else dom
        if dom != int(exp_dom):
            sys.exit(f"REFUSING TO START: ROS_DOMAIN_ID={dom} != expected {exp_dom}.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="lite3_bridge", description="Read-only Lite3 telemetry bridge")
    ap.add_argument("--sim", action="store_true", help="run the built-in simulator instead of ROS 2")
    ap.add_argument("--config", action="append",
                    help="YAML file merged over config/default.yaml; repeat to stack files "
                         "(e.g. --config config/group8.yaml --config config/local.yaml)")
    ap.add_argument("--host", help="override server.host")
    ap.add_argument("--port", type=int, help="override server.port")
    ap.add_argument("--allow-remote-bind", action="store_true",
                    help="permit binding to a non-loopback address (NOT recommended)")
    ap.add_argument("--sim-link-dropouts", action="store_true", help="sim: periodically drop the link")
    ap.add_argument("--sim-no-faults", action="store_true", help="sim: disable injected topic faults")
    ap.add_argument("--sim-latency-ms", type=float, default=0, help="sim: add one-way link delay (ms)")
    ap.add_argument("--no-map-stream", action="store_true",
                    help="never stream the occupancy grid (same as layers.map.enabled: false)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port
    if args.sim_link_dropouts:
        cfg["sim"]["link_dropouts"] = True
    if args.sim_no_faults:
        cfg["sim"]["topic_faults"] = False
    if args.sim_latency_ms:
        cfg["sim"]["latency_ms"] = args.sim_latency_ms
    if args.no_map_stream:
        cfg["layers"]["map"]["enabled"] = False

    host = cfg["server"]["host"]
    if not is_loopback(host) and not args.allow_remote_bind:
        sys.exit(f"REFUSING TO BIND to non-loopback address {host}. Use an SSH tunnel, "
                 "or pass --allow-remote-bind if you really mean it.")

    mode = "sim" if args.sim else "ros"
    if mode == "ros":
        check_identity(cfg)
    identity = build_identity(cfg, mode)
    for w in identity["warnings"]:
        log.warning(w)

    # Fail fast (before touching ROS) if the port is taken - usually another bridge.
    import socket as _socket
    probe = _socket.socket(_socket.AF_INET6 if ":" in host else _socket.AF_INET, _socket.SOCK_STREAM)
    try:
        probe.bind((host, int(cfg["server"]["port"])))
    except OSError:
        sys.exit(f"Port {cfg['server']['port']} on {host} is already in use - another lite3_bridge is "
                 "probably running (check: pgrep -af lite3_bridge). Nothing was started.")
    finally:
        probe.close()

    store = TelemetryStore(cfg, mode)
    if mode == "sim":
        from .sim import SimSource
        source = SimSource(store, cfg)
    else:
        try:
            from .ros_source import RosSource
        except ImportError as exc:
            sys.exit(f"rclpy not importable ({exc}). Source /opt/ros/humble/setup.bash first, "
                     "or run with --sim.")
        source = RosSource(store, cfg)
    source.start()

    import uvicorn
    from .server import create_app

    app = create_app(store, cfg, source, identity)
    log.info("lite3-monitor bridge %s (%s mode, READ-ONLY) on ws://%s:%s/ws", __version__, mode, host,
             cfg["server"]["port"])
    try:
        uvicorn.run(app, host=host, port=int(cfg["server"]["port"]), log_level="warning",
                    ws_max_size=64 * 1024, ws_ping_interval=10, ws_ping_timeout=10)
    finally:
        source.stop()


if __name__ == "__main__":
    main()
