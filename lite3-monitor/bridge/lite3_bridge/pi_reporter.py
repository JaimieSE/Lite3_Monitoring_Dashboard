"""Read-only health reporter for a Raspberry Pi (or any small Linux helper computer).

Run ON the Pi, standard library only (no pip install):

    cd ~/Lite3_Monitoring_Dashboard/lite3-monitor/bridge
    python3 -m lite3_bridge.pi_reporter --allow-from <NUC-IP> [--port 8766]

It serves ONE thing: GET /stats -> JSON with hostname, model, power/throttling
flags, temperature, CPU, memory and SD-card space. It reads /proc and /sys only
(the same information `vcgencmd get_throttled`, `top` and `df` show), runs no
commands, accepts no input, and answers only the allow-listed address(es).
Stopping it (Ctrl+C) has no effect on anything else on the Pi.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from .system_stats import SystemStats, _read

# Bits of the firmware's get_throttled value (same as `vcgencmd get_throttled`).
THROTTLE_BITS = {
    0: "under_voltage_now", 1: "freq_capped_now", 2: "throttled_now", 3: "soft_temp_limit_now",
    16: "under_voltage_occurred", 17: "freq_capped_occurred", 18: "throttled_occurred",
    19: "soft_temp_limit_occurred",
}


def decode_throttled(value: Optional[int]) -> Optional[Dict[str, bool]]:
    if value is None:
        return None
    return {name: bool(value & (1 << bit)) for bit, name in THROTTLE_BITS.items()}


def read_throttled() -> Optional[int]:
    """The firmware exposes get_throttled in sysfs on Raspberry Pi OS kernels."""
    for path in ("/sys/devices/platform/soc/soc:firmware/get_throttled",
                 *glob.glob("/sys/devices/platform/soc*/*firmware*/get_throttled")):
        raw = _read(path)
        if raw:
            try:
                return int(raw.strip(), 16)  # accepts "0x50005" and "50005"
            except ValueError:
                continue
    return None


def read_undervoltage_alarm() -> Optional[bool]:
    """Newer kernels: rpi_volt hwmon sensor with an in0_lcrit_alarm (1 = under-voltage now)."""
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if (_read(f"{d}/name") or "").strip() == "rpi_volt":
            raw = _read(f"{d}/in0_lcrit_alarm")
            if raw and raw.strip() in ("0", "1"):
                return raw.strip() == "1"
    return None


def pi_stats(stats: SystemStats) -> Dict[str, Any]:
    base = stats.sample() or {}
    throttled = read_throttled()
    flags = decode_throttled(throttled)
    uv_alarm = read_undervoltage_alarm()
    if flags is None and uv_alarm is not None:
        flags = {"under_voltage_now": uv_alarm}
    uptime = None
    raw = _read("/proc/uptime")
    if raw:
        try:
            uptime = round(float(raw.split()[0]))
        except (ValueError, IndexError):
            pass
    disk_total_gb = None
    try:
        st = os.statvfs("/")
        disk_total_gb = round(st.f_blocks * st.f_frsize / 1e9, 1)
        base["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
    except OSError:
        pass
    return {
        "hostname": socket.gethostname(),
        "model": (_read("/proc/device-tree/model") or "").strip("\x00\n ") or None,
        "uptime_s": uptime,
        "throttled_raw": None if throttled is None else hex(throttled),
        "throttle": flags,
        "cpu_total_pct": base.get("cpu_total_pct"),
        "load1": base.get("load1"),
        "cores": base.get("cores"),
        "mem_used_mb": base.get("mem_used_mb"),
        "mem_total_mb": base.get("mem_total_mb"),
        "temps": base.get("temps") or [],
        "temp_max_c": base.get("temp_max_c"),
        "disk_free_gb": base.get("disk_free_gb"),
        "disk_total_gb": disk_total_gb,
        "cpu_mhz": base.get("cpu_mhz"),
        "cpu_max_mhz": base.get("cpu_max_mhz"),
        "top": (base.get("top") or [])[:5],
        "time": time.time(),
    }


def make_handler(stats: SystemStats, allow: List[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "lite3-pi-reporter/1"

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the Pi console quiet
            pass

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if allow and self.client_address[0] not in allow:
                self.send_error(403, "not allowed")
                return
            if self.path.split("?")[0] != "/stats":
                self.send_error(404)
                return
            body = json.dumps(pi_stats(stats)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Raspberry Pi health reporter")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--bind", default="0.0.0.0", help="address to listen on (default: all)")
    ap.add_argument("--allow-from", action="append", default=[],
                    help="client IP allowed to read /stats (repeat; normally the NUC's IP). Required.")
    args = ap.parse_args(argv)
    if not args.allow_from:
        print("Refusing to start without --allow-from <NUC-IP> (only that machine may read the stats).",
              file=sys.stderr)
        return 2
    stats = SystemStats({"compute": {"components": []}}, simulated=False)
    stats.sample()  # prime CPU counters
    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(stats, args.allow_from))
    print(f"lite3 pi reporter (read-only) on {args.bind}:{args.port}, allowed: {', '.join(args.allow_from)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
