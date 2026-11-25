import base64
import math
import subprocess
import sys
import time
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from lite3_bridge.config import is_loopback, load_config
from lite3_bridge.geom import quat_from_yaw
from lite3_bridge.mapcodec import encode_map, known_bbox
from lite3_bridge.server import create_app
from lite3_bridge.state import TelemetryStore

ROOT = Path(__file__).resolve().parents[2]


def make_store():
    return TelemetryStore(load_config(), "sim")


def test_loopback_detection():
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert not is_loopback("0.0.0.0") and not is_loopback("192.168.1.5")


def test_map_crop_roundtrip():
    w, h = 50, 40
    data = bytearray([0xFF]) * (w * h)
    for y in range(10, 20):
        for x in range(5, 15):
            data[y * w + x] = 0
    data[15 * w + 10] = 100
    assert known_bbox(bytes(data), w, h) == (5, 10, 14, 19)
    enc = encode_map(bytes(data), w, h, 0.05, -1.0, -2.0, 0.0, "map", arena_area_m2=1.0, pad=2)
    assert enc["width"] == 14 and enc["height"] == 14
    assert math.isclose(enc["origin"]["x"], -1.0 + 3 * 0.05)
    raw = zlib.decompress(base64.b64decode(enc["data"]))
    assert len(raw) == enc["width"] * enc["height"]
    assert enc["stats"]["free_cells"] == 99 and enc["stats"]["occupied_cells"] == 1
    assert enc["stats"]["coverage_pct"] == round(100 * 99 * 0.0025, 2)


def test_tf_chain_and_staleness():
    s = make_store()
    now = time.monotonic()
    s.set_tf("map", "odom", (1.0, 0.0, 0.0), quat_from_yaw(math.pi / 2), static=False, now=now)
    s.set_tf("odom", "base_link", (1.0, 0.0, 0.0), quat_from_yaw(0.0), static=False, now=now)
    snap = s.pose_snapshot(now + 0.1)
    p = snap["pose"]
    assert p["frame"] == "map" and p["valid"]
    assert math.isclose(p["x"], 1.0, abs_tol=1e-9) and math.isclose(p["y"], 1.0, abs_tol=1e-9)
    assert math.isclose(p["yaw"], math.pi / 2, abs_tol=1e-9)
    stale = s.pose_snapshot(now + 5.0)
    assert not stale["pose"]["valid"], "old pose must never be reported valid"
    assert any("stale TF" in e for e in stale["tf"]["errors"])


def test_pose_falls_back_to_odometry_when_no_tf():
    s = make_store()
    s.odom = {"x": 2.0, "y": 3.0, "yaw": 0.1, "frame": "odom", "vx": 0.2, "vy": 0.0, "wz": 0.0,
              "rx": time.monotonic()}
    snap = s.pose_snapshot(time.monotonic())
    assert snap["pose"]["source"] == "odometry" and snap["pose"]["frame"] == "odom"
    assert not snap["tf"]["ok"]


def test_distance_ignores_stale_poses():
    s = make_store()
    t = time.monotonic()
    tr = s.tracker
    for i in range(10):
        pose = {"x": i * 0.1, "y": 0.0, "frame": "map", "valid": True}
        tr.update(t + i * 0.1, pose, {"speed": 1.0, "valid": True, "angular": 0.0}, False, False, None, None)
    assert math.isclose(tr.distance, 0.9, abs_tol=1e-6)
    tr.update(t + 2, {"x": 5.0, "y": 0.0, "frame": "map", "valid": False}, None, False, False, None, None)
    assert math.isclose(tr.distance, 0.9, abs_tol=1e-6)


def test_stall_detection():
    s = make_store()
    tr = s.tracker
    t = time.monotonic()
    out = None
    for i in range(130):
        out = tr.update(t + i * 0.1, {"x": 1.0, "y": 1.0, "frame": "map", "valid": True},
                        {"speed": 0.0, "valid": True, "angular": 0.0}, True, False, None, None)
    assert out["stalled"] and out["state"] == "STALLED" and out["stall_events"] == 1


def test_topic_health_flags_multiple_publishers():
    s = make_store()
    st = s.register_topic("odometry", "/odom", min_hz=10, single_publisher=True, available=True, publishers=2)
    s.topic_rx("/odom", 50)
    time.sleep(0.3)
    h = s.health_message({})
    t = [x for x in h["topics"] if x["name"] == "/odom"][0]
    assert t["status"] in ("warn", "ok", "error")
    assert "cross-robot" in t["note"]


def _sim_app(map_enabled=True):
    cfg = load_config()
    cfg["layers"]["map"]["enabled"] = map_enabled
    store = TelemetryStore(cfg, "sim")
    from lite3_bridge.sim import SimSource
    src = SimSource(store, cfg)
    src.start()
    return src, create_app(store, cfg, src, {"hostname": "SIMULATOR"}), store


def _collect(ws, wanted, seconds=6):
    kinds = set()
    deadline = time.time() + seconds
    while time.time() < deadline and not wanted <= kinds:
        kinds.add(ws.receive_json()["type"])
    return kinds


def test_websocket_sim_end_to_end_and_ignores_input():
    src, app, _ = _sim_app()
    try:
        with TestClient(app) as client:
            assert client.get("/healthz").json()["read_only"] is True
            assert client.post("/api/status").status_code == 405  # no write routes
            with client.websocket_connect("/ws") as ws:
                first = ws.receive_json()
                assert first["type"] == "hello" and first["read_only"] is True
                assert first["layers"]["map"]["enabled"] is True
                ws.send_text('{"op":"publish","topic":"/cmd_vel"}')  # must be ignored
                kinds = _collect(ws, {"telemetry", "health", "paths"})
                assert {"telemetry", "health", "paths"} <= kinds
                assert "map" not in kinds, "the grid only travels on the optional /ws/map stream"
            with client.websocket_connect("/ws/map") as wm:
                assert wm.receive_json()["stream"] == "map"
                assert "map" in _collect(wm, {"map"})
    finally:
        src.stop()


def test_map_stats_reported_without_map_stream():
    """Map stream off must still give coverage numbers (cheap stats, no encoding)."""
    src, app, store = _sim_app()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                deadline = time.time() + 8
                stats = None
                while time.time() < deadline and stats is None:
                    m = ws.receive_json()
                    if m["type"] == "health" and m["map"] and m["map"]["stats"]:
                        stats = m["map"]["stats"]
                assert stats and stats["known_area_m2"] > 0
                assert app.state.broadcaster.map_cached is None, "no map client => no encoding"
    finally:
        src.stop()


def test_map_layer_disabled_in_config_rejects_map_stream():
    src, app, _ = _sim_app(map_enabled=False)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                assert ws.receive_json()["layers"]["map"]["enabled"] is False
            import pytest
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/ws/map") as wm:
                    wm.receive_json()
    finally:
        src.stop()


def test_clock_endpoint_cors_only_for_dashboard_origin():
    src, app, _ = _sim_app()
    try:
        with TestClient(app) as client:
            r = client.get("/api/clock", headers={"origin": "http://127.0.0.1:3000"})
            assert abs(r.json()["t"] - time.time()) < 5
            assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
            r2 = client.get("/api/clock", headers={"origin": "http://evil.example"})
            assert "access-control-allow-origin" not in r2.headers
    finally:
        src.stop()


def test_readonly_audit_passes_and_detects_violation(tmp_path):
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "check_readonly.py")], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    # the checker itself must flag a publisher
    import importlib.util
    spec = importlib.util.spec_from_file_location("chk", ROOT / "tools" / "check_readonly.py")
    chk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chk)
    bad = tmp_path / "bad.py"
    bad.write_text("def f(node):\n    node.create_publisher(1, '/cmd_vel', 10)\n")
    chk.ROOT = tmp_path
    chk.check_python(bad)
    assert any("create_publisher" in e for e in chk.errors)


def test_several_viewers_at_once_and_limit():
    """Team-mates each run a dashboard: all get the same live data; beyond max_clients is refused."""
    from starlette.websockets import WebSocketDisconnect
    import pytest
    cfg = load_config()
    cfg["server"]["max_clients"] = 3
    store = TelemetryStore(cfg, "sim")
    from lite3_bridge.sim import SimSource
    src = SimSource(store, cfg)
    src.start()
    try:
        app = create_app(store, cfg, src, {"hostname": "SIMULATOR"})
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b, \
                    client.websocket_connect("/ws") as c:
                for ws in (a, b, c):
                    assert ws.receive_json()["type"] == "hello"
                    assert "telemetry" in _collect(ws, {"telemetry"})
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect("/ws") as d:
                        d.receive_json()
                assert len(app.state.broadcaster.clients) == 3
    finally:
        src.stop()


def test_group8_profile_stacks_and_tf_optional():
    cfg = load_config([str(ROOT / "bridge" / "config" / "group8.yaml")])
    assert cfg["identity"]["expected_hostname"] == "group8" and cfg["identity"]["expected_ros_domain_id"] == 8
    # map layer on: it appears by itself when navigation publishes /map; TF stays optional
    assert cfg["layers"]["map"]["enabled"] is True and cfg["frames"]["tf_required"] is False
    assert cfg["topics"]["cmd_vel"]["candidates"][0] == "/handle_state"
    assert cfg["range_topics"][0]["name"] == "/us_publisher/ultrasound_distance"
    assert cfg["topics"]["odometry"]["candidates"][0] == "/leg_odom2"  # defaults still present
    store = TelemetryStore(cfg, "ros")
    store.odom = {"x": 1.0, "y": 2.0, "yaw": 0.0, "frame": "odom", "vx": 0.1, "vy": 0.0, "wz": 0.0,
                  "rx": time.monotonic()}
    snap = store.pose_snapshot(time.monotonic())
    assert snap["pose"]["source"] == "odometry" and snap["pose"]["valid"]
    assert snap["tf"]["ok"] and not snap["tf"]["errors"] and snap["tf"]["notes"]
    # with TF required (default), the same situation is a TF fault
    store2 = TelemetryStore(load_config(), "ros")
    store2.odom = dict(store.odom)
    assert not store2.pose_snapshot(time.monotonic())["tf"]["ok"]


def test_sim_odom_only_behaves_like_group8():
    from lite3_bridge.sim import SimSource
    cfg = load_config([str(ROOT / "bridge" / "config" / "group8.yaml")])
    cfg["sim"]["topic_faults"] = False
    store = TelemetryStore(cfg, "sim")
    src = SimSource(store, cfg)
    src._register()
    now = 1000.0
    for _ in range(int(30 / src.DT)):
        now += src.DT
        src.tick(now)
    tel = store.telemetry_message()
    assert tel["pose"]["source"] == "odometry" and tel["pose"]["frame"] == "odom"
    assert tel["tf"]["ok"] and store.map_raw is None and store.goal is None
    assert tel["exploration"]["distance_travelled_m"] >= 0
    assert store.paths_message()["trail"]["frame"] == "odom"
    # The 30 s above were simulated in well under a second of real time: make the rate
    # window match the simulated time (otherwise a fast machine measures nothing yet).
    for st in store.topics.values():
        st.last_rate_calc = time.monotonic() - 30.0
    h = store.health_message({})
    health = {t["name"]: t for t in h["topics"]}
    # roles the robot does not have are switched off in the profile: no MISSING noise
    assert "/map" not in health and "/scan" not in health and h["missing_roles"] == []
    assert not any(t["status"] in ("error", "missing") for t in h["topics"]), h["topics"]
    assert health["/sensor_status/imu_isalive"]["value"] is True


def test_topic_bytes_per_second():
    s = make_store()
    s.register_topic("odometry", "/leg_odom2", available=True, min_hz=10)
    st = s.topics["/leg_odom2"]
    st.last_rate_calc = time.monotonic() - 1.0
    for _ in range(100):
        s.topic_rx("/leg_odom2", 1, None, 720)
    h = {t["name"]: t for t in s.health_message({})["topics"]}
    # first window is taken as-is: 100 x 720 B in ~1 s
    assert 60000 < h["/leg_odom2"]["bytes_per_s"] < 80000
    s.register_topic("extra", "/unknown_size", available=True)
    s.topic_rx("/unknown_size", 5)
    assert {t["name"]: t for t in s.health_message({})["topics"]}["/unknown_size"]["bytes_per_s"] is None


def test_system_stats_real_and_simulated():
    import os
    from lite3_bridge.system_stats import SystemStats
    cfg = load_config()
    sim = SystemStats(cfg, simulated=True).sample()
    assert sim["simulated"] and {c["name"] for c in sim["components"]} >= {"Camera driver", "This monitor"}
    if os.path.isdir("/proc"):
        real = SystemStats(cfg, simulated=False)
        real.sample()
        time.sleep(0.3)
        r = real.sample()
        assert r["simulated"] is False and r["cores"] >= 1 and r["mem_total_mb"] > 0
        assert all(set(p) == {"name", "component", "cpu_pct", "rss_mb"} for p in r["top"])  # no cmdlines


def test_health_carries_compute_in_sim():
    src, app, _ = _sim_app()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                deadline = time.time() + 8
                compute = None
                while time.time() < deadline and compute is None:
                    m = ws.receive_json()
                    if m["type"] == "health" and m.get("compute"):
                        compute = m["compute"]
                assert compute and compute["simulated"] and compute["components"]
    finally:
        src.stop()


def test_static_and_dynamic_tf_for_same_child_do_not_alternate():
    """group8: /tf_static re-sends a fixed map->base_link (0.03,-0.02) every ~2.5 s while the
    real moving map->base_link comes on /tf. The pose must follow the moving one."""
    s = make_store()
    now = time.monotonic()
    s.set_tf("map", "base_link", (5.71, -2.19, 0.0), quat_from_yaw(0.0), static=False, now=now)
    s.set_tf("map", "base_link", (0.03, -0.02, 0.0), quat_from_yaw(0.0), static=True, now=now + 0.1)
    snap = s.pose_snapshot(now + 0.2)
    assert math.isclose(snap["pose"]["x"], 5.71) and snap["pose"]["source"] == "tf"
    assert any("fixed" in e and "moving" in e for e in snap["tf"]["errors"]), snap["tf"]
    # navigation stops: the fixed map->base_link must NOT become a "live" robot position.
    s.odom = {"x": 1.5, "y": 0.5, "yaw": 0.0, "frame": "odom", "vx": 0.0, "vy": 0.0, "wz": 0.0, "rx": now + 30}
    late = s.pose_snapshot(now + 30)
    assert late["pose"]["source"] == "odometry" and math.isclose(late["pose"]["x"], 1.5)
    assert any("fixed (static)" in e for e in late["tf"]["errors"])


def test_pose_jump_breaks_trail_and_adds_no_distance():
    s = make_store()
    tr = s.tracker
    t = time.monotonic()
    still = {"speed": 0.0, "valid": True, "angular": 0.0}
    seq = [(5.7, -2.2), (5.7, -2.2), (0.03, -0.02), (5.7, -2.2), (5.85, -2.2)]
    out = None
    for i, (x, y) in enumerate(seq):
        out = tr.update(t + i * 0.1, {"x": x, "y": y, "frame": "map", "valid": True}, still, False, False, None, None)
    assert out["pose_jumps"] == 2 and out["last_jump"]["distance_m"] > 5
    assert tr.distance < 0.2, tr.distance  # only the real 0.15 m step
    pts = tr.trail_payload(t)["points"]
    assert None in pts and pts[-1] == [5.85, -2.2]


def test_throttle_decoding():
    from lite3_bridge.pi_reporter import decode_throttled
    f = decode_throttled(0x50005)  # classic "under-voltage now + throttled now, both occurred"
    assert f["under_voltage_now"] and f["throttled_now"] and f["under_voltage_occurred"] and f["throttled_occurred"]
    assert not f["freq_capped_now"] and not f["soft_temp_limit_occurred"]
    assert not any(decode_throttled(0).values())


def test_pi_reporter_and_peer_monitor_end_to_end():
    import threading
    from http.server import ThreadingHTTPServer
    from lite3_bridge.peers import PeerMonitor, fetch_stats, tcp_probe
    from lite3_bridge.pi_reporter import make_handler
    from lite3_bridge.system_stats import SystemStats
    stats = SystemStats({"compute": {"components": []}}, simulated=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stats, ["127.0.0.1"]))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = fetch_stats("127.0.0.1", port)
        assert r["stats"]["hostname"] and "throttle" in r["stats"] and "temp_max_c" in r["stats"]
        net = r["stats"]["net"]
        assert isinstance(net["interfaces"], list) and isinstance(net["connections"], list)
        # our own HTTP request is an established connection from an allow-listed address
        assert any(c["to_nuc"] for c in net["connections"]), net["connections"][:5]
        assert tcp_probe("127.0.0.1", port)["online"]
        mon = PeerMonitor({"peers": [{"name": "Pi", "host": "127.0.0.1", "ssh_port": port, "stats_port": port,
                                      "expected_hostname": "definitely-not-this-host"}]}, simulated=False)
        out = mon.sample()[0]
        assert out["online"] and out["rtt_ms"] is not None and out["stats"] and out["identity_ok"] is False
    finally:
        srv.shutdown()
    # refused when the client is not allow-listed
    srv2 = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stats, ["10.9.9.9"]))
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        assert fetch_stats("127.0.0.1", srv2.server_address[1])["stats"] is None
    finally:
        srv2.shutdown()
    # nothing listening -> offline, no exception
    assert tcp_probe("127.0.0.1", 1, timeout=0.5)["online"] is False


def test_pi_reporter_requires_allow_list():
    from lite3_bridge.pi_reporter import main
    assert main([]) == 2


def test_simulated_peer_in_health():
    src, app, _ = _sim_app()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                deadline = time.time() + 8
                peers = None
                while time.time() < deadline and not peers:
                    m = ws.receive_json()
                    if m["type"] == "health" and m.get("peers"):
                        peers = m["peers"]
                assert peers and peers[0]["name"].endswith("(sim)") and peers[0]["stats"]["throttle"] is not None
    finally:
        src.stop()


def test_optional_roles_are_inactive_not_missing():
    s = make_store()
    s.register_topic("map", "/map", available=False)
    s.register_topic("odometry", "/leg_odom2", available=False, min_hz=10)
    s.roles["scan"] = None
    h = s.health_message({})
    t = {x["name"]: x for x in h["topics"]}
    assert t["/map"]["status"] == "idle" and "inactive" in t["/map"]["note"]
    assert t["/leg_odom2"]["status"] == "missing"          # required roles still alarm
    assert "scan" in h["inactive_roles"] and "scan" not in h["missing_roles"]


def test_attitude_joints_range_and_logs():
    s = make_store()
    now = time.monotonic()
    s.imu = {"roll": math.radians(30), "pitch": 0.0, "acc": 9.81, "gyro": 0.1, "source": "orientation", "rx": now}
    s.joints = {"names": ["FL_Knee"], "effort": [12.345], "velocity": [0.5], "rx": now}
    tel = s.telemetry_message()
    assert abs(tel["attitude"]["tilt_deg"] - 30.0) < 0.2 and tel["attitude"]["valid"]
    assert tel["attitude"]["tilt_warn_deg"] == 20 and tel["joints"]["effort"] == [12.35]
    s.register_topic("range", "/us", available=True, range_warn=0.5, range_crit=0.25, range_max=4.5)
    s.topic_rx("/us")
    s.topics["/us"].range_m = 0.2
    s.add_log(40, "planner_server", "failed to create plan")
    h = s.health_message({})
    us = {x["name"]: x for x in h["topics"]}["/us"]
    assert us["status"] == "error" and "very close" in us["note"] and us["range_m"] == 0.2
    assert h["logs"][-1]["msg"] == "failed to create plan" and h["logs"][-1]["level"] == 40


def test_sim_group8_has_body_data_and_command():
    from lite3_bridge.sim import SimSource
    cfg = load_config([str(ROOT / "bridge" / "config" / "group8.yaml")])
    cfg["sim"]["topic_faults"] = False
    store = TelemetryStore(cfg, "sim")
    src = SimSource(store, cfg)
    src._register()
    now = 1000.0
    for _ in range(int(20 / src.DT)):
        now += src.DT
        src.tick(now)
    tel = store.telemetry_message()
    assert tel["attitude"] is not None and len(tel["joints"]["names"]) == 12
    assert tel["cmd_vel"] is not None  # /handle_state is the command source on group8
    h = {t["name"]: t for t in store.health_message({})["topics"]}
    assert h["/us_publisher/ultrasound_distance"]["range_m"] is not None


def test_proc_net_address_decoding():
    from lite3_bridge.pi_reporter import _hex_ip_port
    assert _hex_ip_port("4E0AA8C0:2231") == ("192.168.10.78", 0x2231)
    assert _hex_ip_port("0000000000000000FFFF00004E0AA8C0:0016") == ("192.168.10.78", 22)
    assert _hex_ip_port("00000000000000000000000001000000:0050")[0] == "::1"
