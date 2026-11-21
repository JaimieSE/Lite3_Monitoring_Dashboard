"""FastAPI websocket server.

Output-only: the server pushes telemetry and IGNORES everything a client
sends. There are no POST/PUT/DELETE routes and no handler that could reach
ROS. Each client has one "latest value" slot per message type, so a slow
client can never cause unbounded memory growth or receive a backlog of
stale data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import __version__
from .mapcodec import encode_map
from .state import TelemetryStore

log = logging.getLogger("lite3_bridge.server")

PROTOCOL_VERSION = 1
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

    async def sender(self) -> None:
        while not self.closed:
            await self.event.wait()
            self.event.clear()
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
        self.clients: set = set()
        self.seq = 0
        self.map_sent_version = -1
        self.map_last_sent = 0.0
        self.map_cached: Optional[str] = None
        self.map_encoding = False
        self.messages_sent = 0

    def hello(self) -> str:
        frames = self.cfg["frames"]
        return json.dumps({
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "bridge_version": __version__,
            "mode": self.store.mode,
            "read_only": True,
            "identity": self.identity,
            "frames": frames,
            "rates": self.cfg["rates"],
            "staleness": self.cfg["staleness"],
            "arena_area_m2": self.cfg["exploration"].get("arena_area_m2"),
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
                        "dropped_frames": sum(c.dropped for c in self.clients),
                        "map_bytes": len(self.map_cached or ""),
                    })
                    if self.clients:
                        self._publish("health", health)
                if self.clients and t0 >= next_paths:
                    next_paths = t0 + paths_dt
                    self._publish("paths", self.store.paths_message())
                if self.clients and not self.map_encoding and t0 - self.map_last_sent >= map_dt:
                    version, raw = self.store.map_snapshot()
                    if raw is not None and version != self.map_sent_version:
                        self.map_encoding = True
                        asyncio.create_task(self._encode_and_send_map(version, raw))
            except Exception:
                log.exception("broadcast tick failed")
            await asyncio.sleep(max(0.0, tel_dt - (time.monotonic() - t0)))


    async def _encode_and_send_map(self, version: int, raw: Dict[str, Any]) -> None:
        try:
            ox, oy, oyaw = raw["origin"]
            enc = await asyncio.to_thread(
                encode_map, raw["data"], raw["width"], raw["height"], raw["resolution"], ox, oy, oyaw,
                raw["frame"], self.cfg["exploration"].get("arena_area_m2"))
            enc["type"] = "map"
            enc["version"] = version
            enc["server_time"] = time.time()
            self.map_cached = json.dumps(enc, separators=(",", ":"))
            self.map_sent_version = version
            self.map_last_sent = time.monotonic()
            if not self.source.link_is_down():
                for c in list(self.clients):
                    c.offer("map", self.map_cached)
        except Exception:
            log.exception("map encoding failed")
            self.map_last_sent = time.monotonic()
        finally:
            self.map_encoding = False

    def on_connect(self, client: Client) -> None:
        self.clients.add(client)
        client.offer("hello", self.hello())
        if self.map_cached is not None:
            client.offer("map", self.map_cached)


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

    @app.get("/healthz")
    async def healthz() -> Dict[str, Any]:
        return {"ok": True, "mode": store.mode, "read_only": True, "clients": len(bc.clients)}

    @app.get("/api/status")
    async def status() -> Dict[str, Any]:
        return {"identity": identity, "mode": store.mode, "read_only": True, "version": __version__,
                "uptime_s": round(time.monotonic() - store.started, 1), "clients": len(bc.clients),
                "roles": store.roles, "source": store.source_status}

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
        sender = asyncio.create_task(client.sender())
        log.info("client connected (%d total)", len(bc.clients))
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
            bc.clients.discard(client)
            log.info("client disconnected (%d remaining)", len(bc.clients))
            try:
                await ws.close()
            except Exception:
                pass

    return app
