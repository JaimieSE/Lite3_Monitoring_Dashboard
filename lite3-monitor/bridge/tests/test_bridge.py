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
    assert cfg["layers"]["map"]["enabled"] is False and cfg["frames"]["tf_required"] is False
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
    # first window is averaged with 0 -> about half of 72 kB/s
    assert 30000 < h["/leg_odom2"]["bytes_per_s"] < 40000
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
