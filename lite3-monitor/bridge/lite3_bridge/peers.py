"""Health of helper computers on the robot (e.g. the Raspberry Pi), checked from the NUC.

Read-only and lightweight, every `interval_s`:
  * reachability: a TCP connect to the peer's SSH port (no login, nothing sent),
    measuring the connect time; the SSH banner the peer announces is recorded;
  * optional stats: GET http://<host>:<stats_port>/stats from lite3_bridge.pi_reporter
    running on the peer (power / throttling, temperature, CPU, memory, SD card).
No credentials are stored or used.
"""
from __future__ import annotations

import json
import math
import random
import socket
import time
import urllib.request
from typing import Any, Dict, List, Optional

from .pi_reporter import decode_throttled


def tcp_probe(host: str, port: int, timeout: float = 1.5) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            rtt = (time.monotonic() - t0) * 1000.0
            s.settimeout(0.5)
            banner = ""
            try:
                banner = s.recv(64).decode("ascii", "replace").strip()
            except OSError:
                pass
            return {"online": True, "rtt_ms": round(rtt, 1), "banner": banner[:60] or None}
    except OSError as exc:
        return {"online": False, "rtt_ms": None, "banner": None, "error": str(exc)[:80]}


def fetch_stats(host: str, port: int, timeout: float = 1.5) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/stats", timeout=timeout) as r:
            return {"stats": json.loads(r.read().decode())}
    except Exception as exc:  # reporter not running / not allowed / network
        return {"stats": None, "stats_error": str(exc)[:100]}


class PeerMonitor:
    def __init__(self, cfg: Dict[str, Any], simulated: bool):
        self.peers: List[Dict[str, Any]] = [p for p in (cfg.get("peers") or []) if p.get("host") or simulated]
        self.simulated = simulated
        self.state: Dict[str, Dict[str, Any]] = {}
        self._t0 = time.time()
        self._rng = random.Random(5)
        if simulated and not self.peers:
            self.peers = [{"name": "Raspberry Pi (sim)", "host": "sim", "expected_hostname": "group8pi"}]

    def sample(self) -> List[Dict[str, Any]]:
        out = []
        now = time.monotonic()
        for p in self.peers:
            name = p.get("name") or p.get("host")
            prev = self.state.get(name, {})
            if self.simulated:
                res = self._simulated(p)
            else:
                res = tcp_probe(p["host"], int(p.get("ssh_port", 22)))
                if p.get("stats_port"):
                    res.update(fetch_stats(p["host"], int(p["stats_port"])))
            if res.get("online"):
                res["last_seen"] = now
            elif prev.get("last_seen"):
                res["last_seen"] = prev["last_seen"]
            stats = res.get("stats")
            exp = p.get("expected_hostname")
            identity_ok = None
            if stats and exp:
                identity_ok = stats.get("hostname") == exp
            self.state[name] = res
            out.append({
                "name": name,
                "host_label": p.get("label") or ("simulated" if self.simulated else "configured host"),
                "online": bool(res.get("online")),
                "rtt_ms": res.get("rtt_ms"),
                "banner": res.get("banner"),
                "error": res.get("error"),
                "last_seen_age_s": None if not res.get("last_seen") else round(now - res["last_seen"], 1),
                "stats_configured": bool(p.get("stats_port")) or self.simulated,
                "stats": stats,
                "stats_error": res.get("stats_error"),
                "expected_hostname": exp,
                "identity_ok": identity_ok,
                "temp_warn_c": float(p.get("temp_warn_c", 75)),
                "temp_crit_c": float(p.get("temp_crit_c", 82)),
            })
        return out

    def _simulated(self, p: Dict[str, Any]) -> Dict[str, Any]:
        t = time.time() - self._t0
        phase = t % 300.0
        under_v = 200.0 <= phase < 215.0        # brief under-voltage every 5 min
        offline = 280.0 <= phase < 290.0        # brief network loss every 5 min
        if offline:
            return {"online": False, "rtt_ms": None, "banner": None, "error": "timed out (simulated)"}
        raw = 0
        if under_v:
            raw |= 0x1 | 0x4
        if t > 200.0:
            raw |= 0x10000 | 0x40000            # "occurred since boot" bits stay set
        temp = round(56 + 6 * math.sin(t / 40.0) + (8 if under_v else 0) + self._rng.uniform(-0.5, 0.5), 1)
        stats = {
            "hostname": p.get("expected_hostname") or "pi", "model": "Raspberry Pi 4 Model B Rev 1.5 (simulated)",
            "uptime_s": round(t + 3600), "throttled_raw": hex(raw), "throttle": decode_throttled(raw),
            "cpu_total_pct": round(18 + 8 * math.sin(t / 25.0), 1), "load1": 0.6, "cores": 4,
            "mem_used_mb": 820.0, "mem_total_mb": 3790.0,
            "temps": [{"label": "cpu_thermal", "c": temp}], "temp_max_c": temp,
            "disk_free_gb": 18.3, "disk_total_gb": 29.7, "cpu_mhz": 600 if under_v else 1500, "cpu_max_mhz": 1500,
            "top": [{"name": "python3", "component": "Other", "cpu_pct": 12.0, "rss_mb": 60.0}],
        }
        return {"online": True, "rtt_ms": round(self._rng.uniform(4, 25), 1), "banner": "SSH-2.0-OpenSSH (sim)",
                "stats": stats}
