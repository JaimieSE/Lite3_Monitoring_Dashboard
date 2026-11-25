"""Pi perception and mission reporting, observed read-only (protocol `health.perception`, `health.missions`).

* `PiPerception` keeps what the Pi publishes on ROS (std_msgs/String JSON, see the robot's
  live_mission/PI_SCENE_EVENTS.md):
    - `/group8pi/perception/detections`    latest objects, QR text, hazard signs, stair/curtain state
    - `/group8pi/perception/scene_events`  scene_pending / scene_result / scene_failed per Claude request
  Requests are joined by `request_id`; at most `max_requests` are kept (oldest dropped).
* `MissionReports` reads the robot's own mission log (one JSON line per POST: payload, HTTP status and the
  scoring server's answer) from the newest run folder matching `reports_glob`. Read only, re-read only when
  the file changes. Nothing is ever sent to the scoring server from here.

Cheap by design: the topics are small and slow (< 1 Hz), and the file is stat'ed every health sample.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

HAZARD_LABELS = ("high_voltage", "radioactive", "chemical", "biological", "flammable")


class PiPerception:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.max_requests = int(cfg.get("max_requests", 20))
        self.lock = threading.Lock()
        self.latest: Optional[Dict[str, Any]] = None
        self.latest_t: Optional[float] = None
        self.frames = 0
        self.requests: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.events = 0
        self.bad_messages = 0

    # ------------------------------------------------------------------ input
    def on_detections(self, text: str, now: float) -> None:
        try:
            rec = json.loads(text)
            stair = rec.get("stair_curtain") or {}
            latest = {
                "frame": rec.get("frame"),
                "objects": [{"name": str(o.get("name")), "confidence": round(float(o.get("confidence", 0)), 2)}
                            for o in rec.get("objects") or []][:12],
                "qr": [str(c.get("text")) for c in rec.get("qr_codes") or [] if c.get("text")][:4],
                "signs": [s.get("label") if s.get("label") in HAZARD_LABELS else None
                          for s in rec.get("warning_sign_candidates") or []][:6],
                "stair": {"obstacle": stair.get("obstacle"), "reason": stair.get("reason"),
                          "distance_m": stair.get("distance_m")},
            }
        except (ValueError, TypeError, AttributeError):
            with self.lock:
                self.bad_messages += 1
            return
        with self.lock:
            self.latest, self.latest_t = latest, now
            self.frames += 1

    def on_scene_event(self, text: str, now: float, wall: Optional[float] = None) -> None:
        wall = time.time() if wall is None else wall
        try:
            ev = json.loads(text)
            kind, rid = ev["event"], str(ev["request_id"])
        except (ValueError, TypeError, KeyError):
            with self.lock:
                self.bad_messages += 1
            return
        with self.lock:
            self.events += 1
            req = self.requests.get(rid)
            if req is None or (kind == "scene_pending" and req.get("capture_stamp_ns") != ev.get("capture_stamp_ns")):
                # new request (ids restart when the Pi service restarts: a new stamp means a new request)
                req = {"request_id": rid, "status": "pending", "t_pending": None, "t_done": None,
                       "requested_at": wall, "room": None, "evidence": [], "error": None}
                self.requests.pop(rid, None)
                self.requests[rid] = req
                while len(self.requests) > self.max_requests:
                    self.requests.popitem(last=False)
            req.update(capture_stamp_ns=ev.get("capture_stamp_ns"), frame=ev.get("frame"),
                       trigger=ev.get("trigger"), encounter_ids=ev.get("encounter_ids") or [])
            if kind == "scene_pending":
                req["t_pending"] = now
            elif kind in ("scene_result", "scene_failed"):
                req["status"] = "result" if kind == "scene_result" else "failed"
                req["t_done"] = now
                scene = ev.get("scene") or {}
                req["room"] = scene.get("type")
                req["evidence"] = [str(e) for e in scene.get("evidence") or []][:4]
                req["error"] = ev.get("error")

    # --------------------------------------------------------------- snapshot
    def snapshot(self, now: float) -> Optional[Dict[str, Any]]:
        with self.lock:
            if self.latest is None and not self.requests:
                return None
            requests: List[Dict[str, Any]] = []
            for req in reversed(self.requests.values()):
                latency = None
                if req["t_pending"] is not None and req["t_done"] is not None:
                    latency = round(req["t_done"] - req["t_pending"], 2)
                requests.append({
                    "request_id": req["request_id"], "status": req["status"],
                    "trigger": req.get("trigger"), "encounter_ids": req.get("encounter_ids", []),
                    "frame": req.get("frame"), "capture_stamp_ns": req.get("capture_stamp_ns"),
                    "room": req["room"], "evidence": req["evidence"], "error": req["error"],
                    "latency_s": latency, "requested_at": req["requested_at"],
                    "age_s": round(now - (req["t_done"] or req["t_pending"] or now), 1),
                })
            return {
                "latest": None if self.latest is None else dict(self.latest, age_s=round(now - self.latest_t, 1)),
                "frames": self.frames, "events": self.events, "bad_messages": self.bad_messages,
                "requests": requests,
            }


class MissionReports:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.pattern = os.path.expanduser(cfg.get("reports_glob") or "")
        self.max_reports = int(cfg.get("max_reports", 20))
        self._key: Optional[tuple] = None
        self._cache: Optional[Dict[str, Any]] = None

    def sample(self) -> Optional[Dict[str, Any]]:
        """The newest run folder (run folders are named by start time, so the last name is the newest).

        A run that has not reported anything yet shows an empty list, never the previous run's reports.
        Re-parsed only when the file's size or mtime changed."""
        if not self.pattern:
            return None
        folders = sorted(glob.glob(os.path.dirname(self.pattern)))
        if not folders:
            return None
        path = os.path.join(folders[-1], os.path.basename(self.pattern))
        run = os.path.basename(folders[-1])
        try:
            st = os.stat(path)
        except OSError:
            return {"run": run, "file_mtime": None, "reports": []}
        key = (path, st.st_size, st.st_mtime)
        if key == self._key:
            return self._cache
        reports: List[Dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                        payload = entry["payload"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    try:
                        answer = json.loads(entry.get("response") or "")
                    except (ValueError, TypeError):
                        answer = None
                    answer = answer if isinstance(answer, dict) else {}
                    reports.append({
                        "t": entry.get("time"), "task_id": payload.get("task_id"),
                        "task_type": payload.get("task_type"), "scene_type": payload.get("scene_type"),
                        "label": payload.get("label"), "pos": payload.get("pos"), "message": payload.get("message"),
                        "http_status": entry.get("http_status"), "dry_run": entry.get("response") == "dry_run",
                        "accepted": answer.get("status") == "accepted", "score": answer.get("score"),
                        "max_score": answer.get("max_score"), "evaluation": answer.get("evaluation"),
                        "reason": answer.get("reason"), "course": answer.get("course"),
                    })
        except OSError:
            return None
        self._key = key
        self._cache = {"run": run, "file_mtime": st.st_mtime,
                       "reports": reports[-self.max_reports:]}
        return self._cache
