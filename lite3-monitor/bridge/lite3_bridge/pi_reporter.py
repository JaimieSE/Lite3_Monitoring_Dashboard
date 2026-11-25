"""Read-only health reporter for a Raspberry Pi (or any small Linux helper computer).

Run ON the Pi, standard library only (no pip install):

    cd ~/Lite3_Monitoring_Dashboard/lite3-monitor/bridge
    python3 -m lite3_bridge.pi_reporter --allow-from <NUC-IP> [--port 8766]

It serves ONE thing: GET /stats -> JSON with hostname, model, power/throttling
flags, temperature, CPU, memory, SD-card space, and network activity (bytes /
packets per second per interface, open connections and listening ports with the
owning process name - like `ifconfig` and `ss -tunap`; no message contents). It reads /proc and /sys only
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
from typing import Any, Dict, List, Optional, Tuple

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


TCP_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1", "05": "FIN_WAIT2",
              "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK", "0A": "LISTEN", "0B": "CLOSING"}


def _hex_ip_port(s: str) -> Tuple[str, int]:
    ip_hex, port_hex = s.split(":")
    port = int(port_hex, 16)
    if len(ip_hex) == 8:  # IPv4, little-endian
        ip = ".".join(str(int(ip_hex[i:i + 2], 16)) for i in (6, 4, 2, 0))
    else:  # IPv6: 4 little-endian 32-bit words
        words = [ip_hex[i:i + 8] for i in range(0, 32, 8)]
        b = b"".join(bytes.fromhex(w)[::-1] for w in words)
        if b[:12] == b"\x00" * 10 + b"\xff\xff":  # IPv4-mapped
            ip = ".".join(str(x) for x in b[12:])
        else:
            ip = socket.inet_ntop(socket.AF_INET6, b)
    return ip, port


def _socket_owners() -> Dict[str, str]:
    """socket inode -> process name, from /proc/<pid>/fd (only processes we may inspect)."""
    owners: Dict[str, str] = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        comm = (_read(f"/proc/{pid}/comm") or "?").strip()[:15]
        for fd in fds:
            try:
                target = os.readlink(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if target.startswith("socket:["):
                owners[target[8:-1]] = comm
    return owners


def connections(peer_ips: List[str], limit: int = 30) -> List[Dict[str, Any]]:
    """Open TCP connections / listening ports and active UDP sockets (like `ss -tunap`)."""
    owners = _socket_owners()
    out: List[Dict[str, Any]] = []
    for proto, path in (("tcp", "/proc/net/tcp"), ("tcp", "/proc/net/tcp6"), ("udp", "/proc/net/udp"),
                        ("udp", "/proc/net/udp6")):
        lines = (_read(path) or "").splitlines()[1:]
        for ln in lines:
            f = ln.split()
            if len(f) < 10:
                continue
            try:
                lip, lport = _hex_ip_port(f[1])
                rip, rport = _hex_ip_port(f[2])
            except (ValueError, OSError):
                continue
            state = TCP_STATES.get(f[3], f[3]) if proto == "tcp" else ("CONNECTED" if rport else "OPEN")
            if proto == "tcp" and state not in ("ESTABLISHED", "LISTEN", "SYN_SENT"):
                continue
            if proto == "udp" and lport == 0:
                continue
            loop = lip.startswith("127.") or lip == "::1"
            out.append({"proto": proto, "state": state, "local_port": lport, "remote": None if not rport else rip,
                        "remote_port": rport or None, "process": owners.get(f[9]), "loopback": loop,
                        "to_nuc": rip in peer_ips})
    # most interesting first: to the NUC, then established, then listening; skip loopback noise
    out.sort(key=lambda c: (not c["to_nuc"], c["loopback"], c["state"] != "ESTABLISHED", c["state"] != "LISTEN"))
    return out[:limit]


class NetCounters:
    """Bytes / packets per second per network interface, from /proc/net/dev deltas."""

    def __init__(self) -> None:
        self.prev: Dict[str, Tuple[float, int, int, int, int]] = {}

    def sample(self) -> List[Dict[str, Any]]:
        now = time.monotonic()
        out = []
        for ln in (_read("/proc/net/dev") or "").splitlines()[2:]:
            if ":" not in ln:
                continue
            name, rest = ln.split(":", 1)
            name = name.strip()
            v = rest.split()
            if name == "lo" or len(v) < 10:
                continue
            rxb, rxp, txb, txp = int(v[0]), int(v[1]), int(v[8]), int(v[9])
            prev = self.prev.get(name)
            self.prev[name] = (now, rxb, rxp, txb, txp)
            if prev is None or now - prev[0] <= 0:
                continue
            dt = now - prev[0]
            out.append({"iface": name, "rx_Bps": round((rxb - prev[1]) / dt), "tx_Bps": round((txb - prev[3]) / dt),
                        "rx_pps": round((rxp - prev[2]) / dt, 1), "tx_pps": round((txp - prev[4]) / dt, 1),
                        "rx_total_mb": round(rxb / 1e6, 1), "tx_total_mb": round(txb / 1e6, 1)})
        return out


def pi_stats(stats: SystemStats, net: Optional["NetCounters"] = None, peer_ips: Optional[List[str]] = None) -> Dict[str, Any]:
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
        "net": None if net is None else {"interfaces": net.sample(), "connections": connections(peer_ips or [])},
        "time": time.time(),
    }


def make_handler(stats: SystemStats, allow: List[str]):
    net = NetCounters()
    net.sample()  # prime counters
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
            body = json.dumps(pi_stats(stats, net, allow)).encode()
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
