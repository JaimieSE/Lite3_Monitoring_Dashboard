"""Compute usage of the machine the bridge runs on (the NUC), grouped by component.

Read-only: reads /proc and /sys exactly like `top` / `sensors` would. Nothing is
started, signalled or changed. Only process *names* (comm, max 15 chars) and the
component they were matched to leave this module - never full command lines,
which can contain arguments the team may not want shown.

On machines without /proc (macOS) or in simulator mode, plausible simulated
numbers are produced and marked `simulated: true`.
"""
from __future__ import annotations

import math
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

PROC = "/proc"


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


class SystemStats:
    def __init__(self, cfg: Dict[str, Any], simulated: bool):
        ccfg = cfg.get("compute") or {}
        self.enabled = bool(ccfg.get("enabled", True))
        self.components: List[Tuple[str, List[str]]] = [
            (c["name"], [m.lower() for m in c.get("match", [])]) for c in (ccfg.get("components") or [])
        ]
        self.simulated = simulated or not os.path.isdir(PROC)
        self.clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.ncpu = os.cpu_count() or 1
        self._prev_total: Optional[Tuple[int, int]] = None  # (total jiffies, idle jiffies)
        self._prev_proc: Dict[int, int] = {}
        self._prev_t: Optional[float] = None
        self._match_cache: Dict[int, Tuple[str, str]] = {}  # pid -> (comm, component)
        self._rng = random.Random(3)
        th = (cfg.get("compute") or {}).get("temperature") or {}
        self.temp_warn_c = float(th.get("warn_c", 80))
        self.temp_crit_c = float(th.get("crit_c", 90))
        self._sim_start = time.time()
        self._sim_throttle = 0

    # ------------------------------------------------------------------ public
    def sample(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if self.simulated:
            return self._simulated()
        try:
            return self._real()
        except Exception as exc:  # never let stats break telemetry
            return {"error": str(exc)[:200], "simulated": False}

    # -------------------------------------------------------------------- real
    def _component_for(self, pid: int, comm: str) -> str:
        cached = self._match_cache.get(pid)
        if cached and cached[0] == comm:
            return cached[1]
        raw = _read(f"{PROC}/{pid}/cmdline") or ""
        hay = (comm + " " + raw.replace("\x00", " ")).lower()
        comp = "Other"
        for name, patterns in self.components:
            if any(p in hay for p in patterns):
                comp = name
                break
        self._match_cache[pid] = (comm, comp)
        return comp

    def _real(self) -> Dict[str, Any]:
        now = time.monotonic()
        cpu_line = (_read(f"{PROC}/stat") or "").splitlines()[0].split()
        vals = [int(v) for v in cpu_line[1:]]
        total, idle = sum(vals[:8]), vals[3] + (vals[4] if len(vals) > 4 else 0)
        cpu_total_pct = None
        if self._prev_total is not None:
            dt_total = total - self._prev_total[0]
            dt_idle = idle - self._prev_total[1]
            if dt_total > 0:
                cpu_total_pct = round(100.0 * (1.0 - dt_idle / dt_total), 1)
        self._prev_total = (total, idle)

        dt_wall = None if self._prev_t is None else now - self._prev_t
        self._prev_t = now
        procs: List[Dict[str, Any]] = []
        seen = set()
        page_kb = os.sysconf("SC_PAGE_SIZE") / 1024 if hasattr(os, "sysconf") else 4
        for entry in os.listdir(PROC):
            if not entry.isdigit():
                continue
            pid = int(entry)
            stat = _read(f"{PROC}/{pid}/stat")
            if not stat:
                continue
            try:
                lp, rp = stat.index("("), stat.rindex(")")
                comm = stat[lp + 1:rp][:15]
                fields = stat[rp + 2:].split()
                jiffies = int(fields[11]) + int(fields[12])  # utime + stime
                rss_mb = int(fields[21]) * page_kb / 1024.0
            except (ValueError, IndexError):
                continue
            seen.add(pid)
            prev = self._prev_proc.get(pid)
            self._prev_proc[pid] = jiffies
            if prev is None or dt_wall is None or dt_wall <= 0:
                continue
            cpu = 100.0 * (jiffies - prev) / (dt_wall * self.clk_tck)  # % of ONE core, like top
            if cpu < 0.05 and rss_mb < 20:
                continue
            procs.append({"pid": pid, "name": comm, "component": self._component_for(pid, comm),
                          "cpu_pct": round(cpu, 1), "rss_mb": round(rss_mb, 1)})
        for pid in list(self._prev_proc):
            if pid not in seen:
                del self._prev_proc[pid]
                self._match_cache.pop(pid, None)

        out = self._assemble(cpu_total_pct, procs, self._meminfo(), self._loadavg(), self._temps(),
                             self._disk(), simulated=False)
        out.update(self._cpufreq())
        return out

    @staticmethod
    def _cpufreq() -> Dict[str, Any]:
        """Average current vs maximum CPU clock and thermal-throttle counters (if exposed)."""
        base = "/sys/devices/system/cpu"
        cur, mx, throttle = [], [], 0
        found_throttle = False
        try:
            cpus = [d for d in os.listdir(base) if d.startswith("cpu") and d[3:].isdigit()]
        except OSError:
            cpus = []
        for c in cpus:
            f = _read(f"{base}/{c}/cpufreq/scaling_cur_freq")
            m = _read(f"{base}/{c}/cpufreq/cpuinfo_max_freq")
            if f and m and f.strip().isdigit() and m.strip().isdigit():
                cur.append(int(f) / 1000.0)
                mx.append(int(m) / 1000.0)
            for name in ("core_throttle_count", "package_throttle_count"):
                t = _read(f"{base}/{c}/thermal_throttle/{name}")
                if t and t.strip().isdigit():
                    found_throttle = True
                    throttle += int(t)
        return {
            "cpu_mhz": round(sum(cur) / len(cur)) if cur else None,
            "cpu_max_mhz": round(sum(mx) / len(mx)) if mx else None,
            "throttle_count": throttle if found_throttle else None,
        }

    @staticmethod
    def _meminfo() -> Dict[str, Optional[float]]:
        info: Dict[str, int] = {}
        for line in (_read(f"{PROC}/meminfo") or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal")
        avail = info.get("MemAvailable")
        if not total:
            return {"used_mb": None, "total_mb": None}
        return {"used_mb": round((total - (avail or 0)) / 1024, 0), "total_mb": round(total / 1024, 0)}

    @staticmethod
    def _loadavg() -> Optional[float]:
        raw = _read(f"{PROC}/loadavg")
        try:
            return float(raw.split()[0]) if raw else None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _temps() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        base = "/sys/class/hwmon"
        try:
            for hw in sorted(os.listdir(base)):
                name = (_read(f"{base}/{hw}/name") or hw).strip()
                for f in sorted(os.listdir(f"{base}/{hw}")):
                    if f.startswith("temp") and f.endswith("_input"):
                        raw = _read(f"{base}/{hw}/{f}")
                        label = (_read(f"{base}/{hw}/{f.replace('_input', '_label')}") or "").strip()
                        if raw and raw.strip().lstrip("-").isdigit():
                            out.append({"label": f"{name} {label}".strip()[:32], "c": round(int(raw) / 1000.0, 1)})
        except OSError:
            pass
        if not out:
            base = "/sys/class/thermal"
            try:
                for z in sorted(os.listdir(base)):
                    if z.startswith("thermal_zone"):
                        raw = _read(f"{base}/{z}/temp")
                        typ = (_read(f"{base}/{z}/type") or z).strip()
                        if raw and raw.strip().lstrip("-").isdigit():
                            out.append({"label": typ[:32], "c": round(int(raw) / 1000.0, 1)})
            except OSError:
                pass
        out.sort(key=lambda t: -t["c"])
        return out[:8]

    @staticmethod
    def _disk() -> Optional[float]:
        try:
            st = os.statvfs(os.path.expanduser("~"))
            return round(st.f_bavail * st.f_frsize / 1e9, 1)
        except OSError:
            return None

    def _assemble(self, cpu_total: Optional[float], procs: List[Dict[str, Any]], mem: Dict[str, Any],
                  load1: Optional[float], temps: List[Dict[str, Any]], disk_free_gb: Optional[float],
                  simulated: bool) -> Dict[str, Any]:
        comps: Dict[str, Dict[str, Any]] = {}
        order = [n for n, _ in self.components] + ["Other"]
        for p in procs:
            c = comps.setdefault(p["component"], {"name": p["component"], "cpu_pct": 0.0, "rss_mb": 0.0,
                                                  "processes": 0})
            c["cpu_pct"] += p["cpu_pct"]
            c["rss_mb"] += p["rss_mb"]
            c["processes"] += 1
        comp_list = sorted(comps.values(), key=lambda c: order.index(c["name"]) if c["name"] in order else 99)
        for c in comp_list:
            c["cpu_pct"] = round(c["cpu_pct"], 1)
            c["rss_mb"] = round(c["rss_mb"], 0)
        top = sorted(procs, key=lambda p: -p["cpu_pct"])[:10]
        return {
            "simulated": simulated,
            "cores": self.ncpu,
            "cpu_total_pct": cpu_total,
            "load1": load1,
            "mem_used_mb": mem["used_mb"],
            "mem_total_mb": mem["total_mb"],
            "temps": temps,
            "temp_max_c": temps[0]["c"] if temps else None,
            "temp_warn_c": self.temp_warn_c,
            "temp_crit_c": self.temp_crit_c,
            "disk_free_gb": disk_free_gb,
            "components": comp_list,
            "top": [{k: p[k] for k in ("name", "component", "cpu_pct", "rss_mb")} for p in top],
        }

    # --------------------------------------------------------------- simulated
    def _simulated(self) -> Dict[str, Any]:
        t = time.time()
        r = self._rng
        wob = lambda base, amp: max(0.0, base + amp * math.sin(t / 7.0 + base) + r.uniform(-amp, amp) / 2)  # noqa: E731
        procs = [
            {"name": "component_conta", "component": self._name_like("camera"), "cpu_pct": wob(38, 6), "rss_mb": 410},
            {"name": "livox_ros_drive", "component": self._name_like("livox"), "cpu_pct": wob(14, 3), "rss_mb": 95},
            {"name": "domain_bridge", "component": self._name_like("domain_bridge"), "cpu_pct": wob(22, 5), "rss_mb": 160},
            {"name": "lite3_motion", "component": self._name_like("lite3_motion"), "cpu_pct": wob(9, 2), "rss_mb": 60},
            {"name": "python3", "component": self._name_like("lite3_bridge"), "cpu_pct": wob(2.5, 0.8), "rss_mb": 70},
            {"name": "gnome-shell", "component": "Other", "cpu_pct": wob(4, 2), "rss_mb": 300},
        ]
        for p in procs:
            p["cpu_pct"] = round(p["cpu_pct"], 1)
        total = round(min(100.0, sum(p["cpu_pct"] for p in procs) / self.ncpu + r.uniform(1, 3)), 1)
        # Heat episodes: every 4 min the package heats to ~92 C for ~40 s, so the warnings,
        # throttling indicator and chart can be exercised without a robot.
        phase = (t - self._sim_start) % 240.0
        heat = 0.0
        if 150.0 <= phase < 230.0:
            x = (phase - 150.0) / 80.0
            heat = 34.0 * math.sin(math.pi * x)
        pkg = round(wob(58, 2) + heat, 1)
        temps = [{"label": "coretemp Package id 0", "c": pkg},
                 {"label": "coretemp Core 0", "c": round(pkg - 2.5, 1)},
                 {"label": "acpitz", "c": round(wob(45, 1) + heat / 3, 1)}]
        out = self._assemble(total, procs, {"used_mb": 5200.0, "total_mb": 15800.0}, round(wob(2.1, 0.4), 2),
                             temps, 182.4, simulated=True)
        throttling = pkg >= 90.0
        if throttling:
            self._sim_throttle += 7
        out.update({"cpu_mhz": 1200 if throttling else 2800, "cpu_max_mhz": 4200,
                    "throttle_count": self._sim_throttle})
        return out

    def _name_like(self, needle: str) -> str:
        for name, patterns in self.components:
            if any(p in needle.lower() or needle.lower() in p for p in patterns):
                return name
        return "Other"
