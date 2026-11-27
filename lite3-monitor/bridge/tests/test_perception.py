"""Pi perception panels: scene-request joining, mission log reading, stored-image lookup and relay."""
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer

from fastapi.testclient import TestClient

from lite3_bridge.config import load_config
from lite3_bridge.perception import MissionReports, PiPerception
from lite3_bridge.pi_reporter import find_scene_image, make_handler
from lite3_bridge.server import create_app
from lite3_bridge.state import TelemetryStore
from lite3_bridge.system_stats import SystemStats

from .test_bridge import _sim_app

S = 10**9


def ev(kind, rid="scene-1", stamp=5 * S, **extra):
    return json.dumps(dict(event=kind, request_id=rid, capture_stamp_ns=stamp, frame=7,
                           frame_id="camera_color_optical_frame", trigger={"kind": "object", "label": "hand_tools"},
                           encounter_ids=["object-1"], **extra))


def test_scene_requests_join_by_id_and_restart_reuses_ids():
    p = PiPerception({"max_requests": 3})
    p.on_scene_event(ev("scene_pending"), 10.0, wall=1000.0)
    snap = p.snapshot(11.0)
    assert snap["requests"][0]["status"] == "pending" and snap["requests"][0]["latency_s"] is None
    p.on_scene_event(ev("scene_result", scene={"type": "workshop", "evidence": ["pegboard"]}), 12.5)
    r = p.snapshot(13.0)["requests"][0]
    assert r["status"] == "result" and r["room"] == "workshop" and r["latency_s"] == 2.5 and r["evidence"] == ["pegboard"]
    # Pi service restarted: scene-1 again with a new capture stamp is a NEW request
    p.on_scene_event(ev("scene_pending", stamp=99 * S), 20.0)
    r = p.snapshot(21.0)["requests"][0]
    assert r["status"] == "pending" and r["capture_stamp_ns"] == 99 * S and r["room"] is None
    p.on_scene_event(ev("scene_failed", stamp=99 * S, error="TimeoutError"), 22.0)
    assert p.snapshot(22.0)["requests"][0]["error"] == "TimeoutError"
    for i in range(2, 6):
        p.on_scene_event(ev("scene_pending", rid=f"scene-{i}", stamp=i * S), 30.0 + i)
    ids = [x["request_id"] for x in p.snapshot(40.0)["requests"]]
    assert ids == ["scene-5", "scene-4", "scene-3"]          # newest first, at most max_requests
    p.on_scene_event("not json", 41.0)
    assert p.snapshot(41.0)["bad_messages"] == 1


def test_latest_detections_summary():
    p = PiPerception()
    assert p.snapshot(0.0) is None
    p.on_detections(json.dumps({"frame": 12, "objects": [{"name": "person", "class": 0, "confidence": 0.6234}],
                                "qr_codes": [{"text": "My friend is in the market.", "corners": []}],
                                "warning_sign_candidates": [{"box": [1, 2, 3, 4]}, {"label": "flammable"}],
                                "stair_curtain": {"obstacle": "stairs", "reason": "confirmed", "distance_m": 0.8}}), 5.0)
    latest = p.snapshot(6.5)["latest"]
    assert latest["objects"] == [{"name": "person", "confidence": 0.62}] and latest["age_s"] == 1.5
    assert latest["qr"] == ["My friend is in the market."] and latest["signs"] == [None, "flammable"]
    assert latest["stair"] == {"obstacle": "stairs", "reason": "confirmed", "distance_m": 0.8}


def _report(task, response, payload_extra=None):
    payload = {"group_id": "group08_TEST", "task_id": task, "task_type": "qr", "scene_type": "", "label": "",
               "pos": None, "message": "hi"}
    payload.update(payload_extra or {})
    return json.dumps({"time": 1.0, "url": "http://x/task_report_B", "payload": payload,
                       "http_status": 200 if response != "dry_run" else None, "response": response}) + "\n"


def test_mission_reports_newest_run_and_empty_new_run(tmp_path):
    old = tmp_path / "competition-20261125-233931-physical"
    new = tmp_path / "competition-20261125-235522-physical"
    old.mkdir(); new.mkdir()
    (old / "mission_reports.jsonl").write_text(_report("M01", "dry_run"))
    accepted = json.dumps({"status": "accepted", "task_id": "M04", "score": 5, "max_score": 5,
                           "evaluation": {"message": True}, "course": "B"})
    (new / "mission_reports.jsonl").write_text(_report("M04", accepted) + "garbage\n")
    reader = MissionReports({"reports_glob": str(tmp_path / "competition-*" / "mission_reports.jsonl")})
    out = reader.sample()
    assert out["run"] == new.name and len(out["reports"]) == 1
    r = out["reports"][0]
    assert r["accepted"] and r["score"] == 5 and r["max_score"] == 5 and r["course"] == "B" and not r["dry_run"]
    assert reader.sample() is out                             # unchanged file: cached, not re-parsed
    newest = tmp_path / "competition-20261126-001500-physical"
    newest.mkdir()
    assert reader.sample() == {"run": newest.name, "file_mtime": None, "reports": []}   # never the old run's reports
    assert MissionReports({"reports_glob": ""}).sample() is None


def _scene_store(tmp_path):
    a = tmp_path / "20261125-235520"
    b = tmp_path / "20261126-001000"
    for d, stamp in ((a, 111), (b, 222)):
        d.mkdir()
        (d / "scene-1.jpg").write_bytes(b"\xff\xd8\xff" + d.name.encode())
        (d / "requests.jsonl").write_text(json.dumps({"request_id": "scene-1", "capture_stamp_ns": stamp}) + "\n")
    (b / "scene-2.jpg").write_bytes(b"\xff\xd8\xffpending")   # still waiting for Claude: not listed yet
    return a, b


def test_find_scene_image_picks_folder_by_stamp_and_rejects_bad_input(tmp_path):
    a, b = _scene_store(tmp_path)
    assert find_scene_image(str(tmp_path), "scene-1", "111") == str(a / "scene-1.jpg")
    assert find_scene_image(str(tmp_path), "scene-1", "222") == str(b / "scene-1.jpg")
    assert find_scene_image(str(tmp_path), "scene-2", "333") == str(b / "scene-2.jpg")   # pending: newest folder
    for rid, stamp in (("../../etc/passwd", "1"), ("scene-1.jpg", "111"), ("scene-1", "1;rm"), ("scene-1", "")):
        assert find_scene_image(str(tmp_path), rid, stamp) is None
    assert find_scene_image(None, "scene-1", "111") is None


def test_pi_reporter_serves_stored_image_and_bridge_relays_it(tmp_path):
    a, _ = _scene_store(tmp_path)
    stats = SystemStats({"compute": {"components": []}}, simulated=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stats, ["127.0.0.1"], str(tmp_path)))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = load_config()
        cfg["peers"] = [{"name": "Pi", "host": "127.0.0.1", "stats_port": port}]
        store = TelemetryStore(cfg, "ros")

        class Source:
            def link_is_down(self):
                return False

        app = create_app(store, cfg, Source(), {"hostname": "test"})
        with TestClient(app) as client:
            r = client.get("/api/pi/scene_image", params={"request_id": "scene-1", "stamp": "111"})
            assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
            assert r.content == (a / "scene-1.jpg").read_bytes()
            srv.shutdown()                                  # cached: still served after the Pi goes away
            assert client.get("/api/pi/scene_image", params={"request_id": "scene-1", "stamp": "111"}).status_code == 200
            assert client.get("/api/pi/scene_image", params={"request_id": "scene-9", "stamp": "111"}).status_code == 404
            assert client.get("/api/pi/scene_image", params={"request_id": "../x", "stamp": "1"}).status_code == 400
            assert client.post("/api/pi/scene_image").status_code == 405          # GET only
    finally:
        srv.server_close()


def test_sim_health_has_perception_and_missions():
    src, app, _ = _sim_app()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                deadline = time.time() + 10
                seen = None
                while time.time() < deadline and seen is None:
                    m = ws.receive_json()
                    if m["type"] == "health" and m.get("perception") and m.get("missions"):
                        seen = m
                assert seen, "no perception/missions in health"
                assert seen["perception"]["latest"] is not None and seen["perception"]["requests"]
                assert seen["missions"]["reports"][0]["task_id"] == "M04"
    finally:
        src.stop()
