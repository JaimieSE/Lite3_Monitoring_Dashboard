"""FastAPI websocket server.

Output-only: the server pushes telemetry and IGNORES everything a client
sends. There are no POST/PUT/DELETE routes and no handler that could reach
ROS. Each client has one "latest value" slot per message type, so a slow
client can never cause unbounded memory growth or receive a backlog of
stale data.

Streams
  /ws       telemetry, health, paths (always on while the dashboard is open)
  /ws/map   occupancy grid only. Optional: the dashboard opens it only while the
            map layer is switched on. With no map clients the bridge does not
            encode or send the grid (it still computes small coverage stats).
            Choosing a stream = choosing which socket to open; no command is
            ever sent to the bridge.
  GET /api/clock  current bridge time, for round-trip link-delay measurement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import __version__
from .mapcodec import encode_map, grid_stats
from .state import TelemetryStore

log = logging.getLogger("lite3_bridge.server")

PROTOCOL_VERSION = 2
SEND_TIMEOUT_S = 5.0
# Send order when several slots are pending: small, time-critical first.
PRIORITY = ("hello", "telemetry", "health", "paths", "map")


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.slots: Dict[str, str] = {}
        self.event = asyncio.Event()
        self.dropped = 0
        self.closed = False

    def offer(self, kind: str, payload: str) -> None:
        if kind in self.slots:
            self.dropped += 1  # previous value superseded before it was sent
        self.slots[kind] = payload
        self.event.set()

    async def sender(self, delay_s: float = 0.0) -> None:
        while not self.closed:
            await self.event.wait()
            self.event.clear()
            if delay_s:  # simulator only: emulate a slow Wi-Fi link
                await asyncio.sleep(delay_s)
            for kind in PRIORITY:
                payload = self.slots.pop(kind, None)
                if payload is None:
                    continue
                await asyncio.wait_for(self.ws.send_text(payload), timeout=SEND_TIMEOUT_S)


class Broadcaster:
    def __init__(self, store: TelemetryStore, cfg: Dict[str, Any], source: Any, identity: Dict[str, Any]):
        self.store = store
        self.cfg = cfg
        self.source = source
        self.identity = identity
        self.clients: set = set()       # /ws
        self.map_clients: set = set()   # /ws/map
        self.map_enabled = bool(cfg.get("layers", {}).get("map", {}).get("enabled", True))
        self.seq = 0
        self.map_encoded_version = -1
        self.map_stats_version = -1
        self.map_last_processed = 0.0
        self.map_cached: Optional[str] = None
        self.map_busy = False
        self.messages_sent = 0

    def hello(self, stream: str = "main") -> str:
        return json.dumps({
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "bridge_version": __version__,
            "stream": stream,
            "mode": self.store.mode,
            "read_only": True,
            "identity": self.identity,
            "frames": self.cfg["frames"],
            "rates": self.cfg["rates"],
            "staleness": self.cfg["staleness"],
            "arena_area_m2": self.cfg["exploration"].get("arena_area_m2"),
            "layers": {"map": {"enabled": self.map_enabled}},
            "server_time": time.time(),
        })

    def _publish(self, kind: str, msg: Dict[str, Any]) -> None:
        if self.source.link_is_down():  # simulated Wi-Fi loss (sim mode only)
            return
        self.seq += 1
        msg["seq"] = self.seq
        payload = json.dumps(msg, separators=(",", ":"))
        for c in list(self.clients):
            c.offer(kind, payload)
        self.messages_sent += 1

    async def run(self) -> None:
        rates = self.cfg["rates"]
        tel_dt = 1.0 / float(rates["telemetry_hz"])
        health_dt = 1.0 / float(rates["health_hz"])
        paths_dt = 1.0 / float(rates["paths_hz"])
        map_dt = float(rates["map_min_interval_s"])
        next_health = next_paths = 0.0
        while True:
            t0 = time.monotonic()
            try:
                # Telemetry is built even with no clients so distance/trail keep integrating.
                tel = self.store.telemetry_message()
                if self.clients:
                    self._publish("telemetry", tel)
                if t0 >= next_health:
                    next_health = t0 + health_dt
                    health = self.store.health_message({
                        "clients": len(self.clients),
                        "map_clients": len(self.map_clients),
                        "map_stream_enabled": self.map_enabled,
                        "dropped_frames": sum(c.dropped for c in self.clients | self.map_clients),
                        "map_bytes": len(self.map_cached or "") if self.map_clients else 0,
                    })
                    if self.clients:
                        self._publish("health", health)
                if self.clients and t0 >= next_paths:
                    next_paths = t0 + paths_dt
                    self._publish("paths", self.store.paths_message())
                self._maybe_process_map(t0, map_dt)
            except Exception:
                log.exception("broadcast tick failed")
            await asyncio.sleep(max(0.0, tel_dt - (time.monotonic() - t0)))

    def _maybe_process_map(self, now: float, map_dt: float) -> None:
        if self.map_busy or now - self.map_last_processed < map_dt:
            return
        version, raw = self.store.map_snapshot()
        if raw is None:
            return
        want_encode = self.map_enabled and bool(self.map_clients) and version != self.map_encoded_version
        want_stats = version != self.map_stats_version
        if want_encode or want_stats:
            self.map_busy = True
            asyncio.create_task(self._process_map(version, raw, want_encode))

    async def _process_map(self, version: int, raw: Dict[str, Any], encode: bool) -> None:
        arena = self.cfg["exploration"].get("arena_area_m2")
        try:
            if encode:
                ox, oy, oyaw = raw["origin"]
                enc = await asyncio.to_thread(
                    encode_map, raw["data"], raw["width"], raw["height"], raw["resolution"], ox, oy, oyaw,
                    raw["frame"], arena)
                stats = enc["stats"]
                enc["type"] = "map"
                enc["version"] = version
                enc["server_time"] = time.time()
                self.map_cached = json.dumps(enc, separators=(",", ":"))
                self.map_encoded_version = version
                if not self.source.link_is_down():
                    for c in list(self.map_clients):
                        c.offer("map", self.map_cached)
            else:
                # Map stream off: only count cells (cheap) so coverage keeps working.
                stats = await asyncio.to_thread(grid_stats, raw["data"], raw["resolution"], arena)
            with self.store.lock:
                self.store.map_stats = stats
            self.map_stats_version = version
        except Exception:
            log.exception("map processing failed")
        finally:
            self.map_last_processed = time.monotonic()
            self.map_busy = False

    def on_connect(self, client: Client) -> None:
        self.clients.add(client)
        client.offer("hello", self.hello("main"))

    def on_map_connect(self, client: Client) -> None:
        self.map_clients.add(client)
        client.offer("hello", self.hello("map"))
        if self.map_cached is not None and self.map_encoded_version == self.store.map_version:
            client.offer("map", self.map_cached)
        # otherwise the next tick encodes the current grid for this client


async def _serve(ws: WebSocket, client: Client, clients: set, label: str, delay_s: float = 0.0) -> None:
    sender = asyncio.create_task(client.sender(delay_s))
    log.info("%s client connected (%d total)", label, len(clients))
    try:
        # Inbound frames are read only to detect disconnects and are DISCARDED.
        # The bridge never acts on anything a client sends.
        while True:
            receive = asyncio.create_task(ws.receive())
            done, _ = await asyncio.wait({receive, sender}, return_when=asyncio.FIRST_COMPLETED)
            if sender in done:
                receive.cancel()
                break
            msg = receive.result()
            if msg.get("type") == "websocket.disconnect":
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        client.closed = True
        client.event.set()
        sender.cancel()
        clients.discard(client)
        log.info("%s client disconnected (%d remaining)", label, len(clients))
        try:
            await ws.close()
        except Exception:
            pass


def create_app(store: TelemetryStore, cfg: Dict[str, Any], source: Any, identity: Dict[str, Any]) -> FastAPI:
    bc = Broadcaster(store, cfg, source, identity)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(bc.run())
        yield
        task.cancel()

    app = FastAPI(title="lite3-monitor bridge (read-only)", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.broadcaster = bc
    max_clients = int(cfg["server"].get("max_clients", 4))
    origins = set(cfg["server"].get("dashboard_origins") or [])
    # Simulator only: extra one-way delay to exercise the link-delay readout.
    sim_delay_s = float(cfg.get("sim", {}).get("latency_ms", 0) or 0) / 1000.0 if store.mode == "sim" else 0.0

    @app.get("/healthz")
    async def healthz() -> Dict[str, Any]:
        return {"ok": True, "mode": store.mode, "read_only": True, "clients": len(bc.clients)}

    @app.get("/api/clock")
    async def clock(request: Request) -> JSONResponse:
        """Bridge wall-clock time. Takes no input, changes nothing. Used by the dashboard
        to measure round-trip link delay and the Mac/NUC clock offset."""
        if source.link_is_down():  # simulated Wi-Fi loss also blocks probes
            await asyncio.sleep(SEND_TIMEOUT_S)
        if sim_delay_s:
            await asyncio.sleep(2 * sim_delay_s)  # request + response legs
        resp = JSONResponse({"t": time.time()}, headers={"Cache-Control": "no-store"})
        origin = request.headers.get("origin")
        if origin and origin in origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    @app.get("/api/status")
    async def status() -> Dict[str, Any]:
        return {"identity": identity, "mode": store.mode, "read_only": True, "version": __version__,
                "uptime_s": round(time.monotonic() - store.started, 1), "clients": len(bc.clients),
                "map_clients": len(bc.map_clients), "roles": store.roles, "source": store.source_status}

    @app.get("/api/discovery")
    async def discovery() -> JSONResponse:
        with store.lock:
            graph = {"nodes": list(store.graph["nodes"]), "topics": list(store.graph["topics"])}
            frames = sorted({e.child for e in store.tf_edges.values()} | {e.parent for e in store.tf_edges.values()})
            edges = [{"parent": e.parent, "child": e.child, "static": e.static} for e in store.tf_edges.values()]
        return JSONResponse({"graph": graph, "tf_frames": frames, "tf_edges": edges, "roles": store.roles})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        if len(bc.clients) >= max_clients:
            await ws.close(code=1013)  # try again later
            return
        await ws.accept()
        client = Client(ws)
        bc.on_connect(client)
        await _serve(ws, client, bc.clients, "telemetry", sim_delay_s)

    @app.websocket("/ws/map")
    async def ws_map_endpoint(ws: WebSocket) -> None:
        if not bc.map_enabled:
            await ws.close(code=1008)  # map layer disabled in bridge config
            return
        if len(bc.map_clients) >= max_clients:
            await ws.close(code=1013)
            return
        await ws.accept()
        client = Client(ws)
        bc.on_map_connect(client)
        await _serve(ws, client, bc.map_clients, "map", sim_delay_s)

    return app
