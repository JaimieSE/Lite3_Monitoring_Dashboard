// Framework-independent telemetry client.
//
// * RECEIVE-ONLY websockets: the dashboard never calls send() on a socket.
//   - main stream  /ws      telemetry, health, paths (always on)
//   - map stream   /ws/map  occupancy grid (optional; opened only while the map
//                           layer is on, so switching it off saves bandwidth)
// * Link delay: a 1 Hz GET /api/clock probe (no parameters, changes nothing)
//   gives round-trip time and the bridge/browser clock offset, from which the
//   one-way delay of each telemetry message is estimated.
// * Reconnects forever with capped exponential backoff + jitter; a watchdog
//   closes "half-open" sockets (common after Wi-Fi drops).
// * Freshness is measured with the browser's own clock at receipt time.

import { decodeMap } from "./mapDecode";
import type {
  BridgeMsg, DashboardConfig, DecodedMap, HealthMsg, HelloMsg, LinkState, LinkStats, MapMsg, PathsMsg,
  TelemetryMsg, TopicStatus,
} from "./types";
import type { EventLevel, SessionEvent } from "./historyTypes";

export const STALE_AFTER_MS = 1500;
export const LOST_AFTER_MS = 3500;
const SOCKET_DEAD_AFTER_MS = 6000;
const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 5000;
const PROBE_INTERVAL_MS = 1000;
const PROBE_TIMEOUT_MS = 2500;

export interface VelPoint { t: number; linear: number | null; angular: number | null; cmdLinear: number | null; cmdAngular: number | null }
export interface RatePoint { t: number; rates: Record<string, number | null> }
export interface CoveragePoint { t: number; knownArea: number | null; coveragePct: number | null; frontiers: number | null }
export interface LatencyPoint { t: number; rtt: number | null; transit: number | null }
export interface TempPoint { t: number; max: number | null; sensors: Record<string, number>; robot: Record<string, number | null> }
/** A robot temperature source (from the bridge's temperature_topics). */
export interface RobotTemp { name: string; label: string; c: number | null; warn: number | null; crit: number | null; status: string }


import { lowLevelWithHysteresis, tempLevelWithHysteresis, type TempLevel } from "./thermal";
export { tempLevelWithHysteresis, type TempLevel };
export type MapLinkState = "off" | "disabled" | "connecting" | "live";

function cap<T>(arr: T[], n: number) {
  if (arr.length > n) arr.splice(0, arr.length - n);
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

/** One receive-only websocket with its own reconnect loop. */
class Channel {
  ws: WebSocket | null = null;
  open = false;
  lastRx = 0;
  bytes = 0;
  private stopped = true;
  private backoff = BACKOFF_MIN_MS;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private url: () => string,
    private onMessage: (data: string) => void,
    private onChange: () => void,
    private deadAfterMs: number | null,
  ) {}

  get running() {
    return !this.stopped;
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    this.open = false;
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
  }

  /** Drop the current socket and reconnect (used after a Wi-Fi drop). */
  recycle() {
    if (this.stopped) return;
    const ws = this.ws;
    this.ws = null;
    this.open = false;
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
    this.schedule();
  }

  /** Returns true if the socket looked dead and was recycled. */
  watchdog(now: number): boolean {
    if (this.deadAfterMs != null && this.ws && this.open && now - this.lastRx > this.deadAfterMs) {
      this.recycle();
      return true;
    }
    return false;
  }

  private connect() {
    if (this.stopped) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url());
    } catch {
      this.schedule();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.open = true;
      this.backoff = BACKOFF_MIN_MS;
      this.lastRx = Date.now();
      this.onChange();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      this.lastRx = Date.now();
      this.bytes += ev.data.length;
      this.onMessage(ev.data);
    };
    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null;
        this.open = false;
        this.schedule();
        this.onChange();
      }
    };
  }

  private schedule() {
    if (this.stopped || this.timer) return;
    const delay = this.backoff * (0.8 + Math.random() * 0.4);
    this.backoff = Math.min(BACKOFF_MAX_MS, this.backoff * 1.7);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }
}

export class TelemetryClient {
  config: DashboardConfig | null = null;
  hello: HelloMsg | null = null;
  telemetry: TelemetryMsg | null = null;
  health: HealthMsg | null = null;
  paths: PathsMsg | null = null;
  map: DecodedMap | null = null;
  mapError: string | null = null;

  link: LinkState = "connecting";
  everConnected = false;
  lastRx: Record<string, number> = {};
  lostSince: number | null = null;
  outages = 0;
  identityProblem: string | null = null;

  /** User preference: stream the occupancy grid. */
  mapEnabled = true;
  linkStats: LinkStats = {
    rttMs: null, rttLastMs: null, transitMs: null, clockOffsetMs: null, probeFailures: 0, kbpsMain: 0, kbpsMap: 0,
  };

  vel: VelPoint[] = [];
  rates: RatePoint[] = [];
  coverage: CoveragePoint[] = [];
  latency: LatencyPoint[] = [];
  /** Robot log (/rosout), newest last, de-duplicated by id. */
  robotLogs: import("./types").RobotLog[] = [];
  tiltLevel: TempLevel = "unknown";
  rangeLevels = new Map<string, TempLevel>();
  private seenLogs = new Set<string>();
  maxTilt = 0;
  /** Per helper computer: received / sent kB/s and response time over time. */
  peerTraffic = new Map<string, { t: number; rx: number | null; tx: number | null; rtt: number | null }[]>();
  temps: TempPoint[] = [];
  /** Highest NUC temperature seen since the page was opened. */
  tempPeak: { c: number; t: number } | null = null;
  events: SessionEvent[] = [];

  private main: Channel;
  private mapCh: Channel;
  private stopped = true;
  private watchdogTimer: ReturnType<typeof setInterval> | null = null;
  private probeTimer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<() => void>();
  private eventListeners = new Set<(e: SessionEvent) => void>();
  private version = 0;
  private notifyPending = false;
  private prevTopicStatus = new Map<string, TopicStatus>();
  private prevStalled = false;
  private prevJumps = 0;
  private prevNav: string | null = null;
  private prevState: string | null = null;
  private prevTfOk: boolean | null = null;
  private prevMapStatsVersion = -1;
  private mapDecoding = false;
  private pendingMap: MapMsg | null = null;
  private probes: { rtt: number; offset: number; t: number }[] = [];
  private transits: number[] = [];
  private probing = false;
  private lastRateCalc = Date.now();
  private byteWindow: { t: number; main: number; map: number }[] = [];
  private highLatency = false;
  private prevTempLevel: TempLevel = "unknown";
  private robotTempLevels = new Map<string, TempLevel>();
  private peerPrev = new Map<string, { online: boolean; uv: boolean; thr: boolean; id: boolean | null; tl: TempLevel }>();
  private prevThrottle: number | null = null;
  private throttleEpisode: { start: number; events: number } | null = null;
  private lastThrottleAt = 0;

  constructor() {
    this.main = new Channel(() => this.bridgeUrl, (d) => this.handle(d, "main"), () => this.notify(), SOCKET_DEAD_AFTER_MS);
    this.mapCh = new Channel(() => mapUrl(this.bridgeUrl), (d) => this.handle(d, "map"), () => this.notify(), null);
  }

  // ------------------------------------------------------------ lifecycle
  start(config: DashboardConfig, mapEnabled = true) {
    this.config = config;
    this.mapEnabled = mapEnabled;
    this.stopped = false;
    this.main.start();
    this.syncMapChannel();
    this.watchdogTimer = setInterval(() => this.tick(), 250);
    this.probeTimer = setInterval(() => void this.probe(), PROBE_INTERVAL_MS);
  }

  stop() {
    this.stopped = true;
    if (this.watchdogTimer) clearInterval(this.watchdogTimer);
    if (this.probeTimer) clearInterval(this.probeTimer);
    this.main.stop();
    this.mapCh.stop();
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = () => this.version;

  onEvent(fn: (e: SessionEvent) => void) {
    this.eventListeners.add(fn);
    return () => this.eventListeners.delete(fn);
  }

  /** Throttled change notification (max ~6 Hz) to keep React work bounded. */
  private notify() {
    if (this.notifyPending) return;
    this.notifyPending = true;
    setTimeout(() => {
      this.notifyPending = false;
      this.version++;
      this.listeners.forEach((l) => l());
    }, 160);
  }

  get bridgeUrl() {
    return this.config?.bridgeUrl ?? "";
  }

  // ---------------------------------------------------------- map layer
  /** Switch the occupancy-grid stream on/off. Off = the map socket is closed. */
  setMapEnabled(on: boolean) {
    if (on === this.mapEnabled) return;
    this.mapEnabled = on;
    this.emit("info", "map", on ? "Map stream switched ON" : "Map stream switched OFF (saving bandwidth)");
    this.syncMapChannel();
    this.notify();
  }

  get bridgeAllowsMap(): boolean {
    return this.hello?.layers?.map?.enabled !== false;
  }

  get mapLink(): MapLinkState {
    if (!this.bridgeAllowsMap) return "disabled";
    if (!this.mapEnabled) return "off";
    return this.mapCh.open && this.map ? "live" : "connecting";
  }

  private syncMapChannel() {
    const want = !this.stopped && this.mapEnabled && this.bridgeAllowsMap;
    if (want) this.mapCh.start();
    else {
      this.mapCh.stop();
      // never keep showing a grid we are no longer receiving
      this.map = null;
      this.pendingMap = null;
    }
  }

  // ------------------------------------------------------------ watchdog
  private tick() {
    const now = Date.now();
    if (this.main.watchdog(now)) this.mapCh.recycle(); // Wi-Fi drop: refresh both sockets

    if (now - this.lastRateCalc >= 1000) {
      // bandwidth averaged over the last ~5 s (the map arrives in bursts every few seconds)
      this.byteWindow.push({ t: now, main: this.main.bytes, map: this.mapCh.bytes });
      this.main.bytes = 0;
      this.mapCh.bytes = 0;
      this.lastRateCalc = now;
      while (this.byteWindow.length > 1 && now - this.byteWindow[0].t > 5000) this.byteWindow.shift();
      const span = Math.max(1, (now - this.byteWindow[0].t) / 1000 + 1);
      this.linkStats.kbpsMain = this.byteWindow.reduce((a, b) => a + b.main, 0) / 1024 / span;
      this.linkStats.kbpsMap = this.byteWindow.reduce((a, b) => a + b.map, 0) / 1024 / span;
    }

    const lastTel = this.lastRx.telemetry ?? 0;
    let next: LinkState;
    if (!this.everConnected) next = "connecting";
    else if (!this.main.open || now - lastTel > LOST_AFTER_MS) next = "lost";
    else if (now - lastTel > STALE_AFTER_MS) next = "stale";
    else next = "live";

    if (next !== this.link) {
      const prev = this.link;
      this.link = next;
      if (next === "lost") {
        this.lostSince = now;
        this.outages++;
        this.emit("error", "link", "TELEMETRY LOST - no data from bridge");
      } else if (next === "live" && prev === "lost" && this.lostSince) {
        this.emit("info", "link", `Telemetry restored after ${((now - this.lostSince) / 1000).toFixed(1)} s`);
        this.lostSince = null;
      } else if (next === "stale" && prev === "live") {
        this.emit("warn", "link", "Telemetry delayed (stale)");
      }
      this.notify();
    }
    if (next === "lost") {
      // explicit gaps so charts never bridge across an outage
      const lastV = this.vel[this.vel.length - 1];
      if (!lastV || lastV.linear !== null || now - lastV.t > 1000) {
        this.vel.push({ t: now, linear: null, angular: null, cmdLinear: null, cmdAngular: null });
      }
      this.notify();
    }
  }

  // ---------------------------------------------------------- link delay
  /** GET /api/clock: round-trip time + clock offset (NTP-style, best of recent samples). */
  private async probe() {
    if (this.probing || this.stopped || !this.bridgeUrl) return;
    this.probing = true;
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    const p0 = performance.now();
    const w0 = Date.now();
    try {
      const r = await fetch(clockUrl(this.bridgeUrl), { cache: "no-store", signal: ctrl.signal });
      const body = (await r.json()) as { t: number };
      const rtt = performance.now() - p0;
      const w1 = w0 + rtt;
      const offset = body.t * 1000 - (w0 + w1) / 2;
      this.probes.push({ rtt, offset, t: w1 });
      cap(this.probes, 30);
      const recent = this.probes.slice(-5).map((p) => p.rtt);
      // the sample with the smallest round trip gives the most accurate offset
      const best = this.probes.reduce((a, b) => (b.rtt < a.rtt ? b : a));
      this.linkStats.rttMs = median(recent);
      this.linkStats.rttLastMs = rtt;
      this.linkStats.clockOffsetMs = best.offset;
      this.linkStats.probeFailures = 0;
    } catch {
      this.linkStats.probeFailures++;
      this.linkStats.rttLastMs = null;
    } finally {
      clearTimeout(to);
      this.probing = false;
    }
    const ls = this.linkStats;
    const ok = ls.probeFailures === 0;
    this.latency.push({ t: Date.now(), rtt: ok ? ls.rttLastMs : null, transit: ok ? ls.transitMs : null });
    cap(this.latency, 900);
    const high = ok && (ls.rttMs ?? 0) > 500;
    if (high !== this.highLatency) {
      this.highLatency = high;
      if (high) this.emit("warn", "link", `High link delay: ${Math.round(ls.rttMs ?? 0)} ms round trip`);
      else if (ok) this.emit("info", "link", `Link delay back to normal (${Math.round(ls.rttMs ?? 0)} ms)`);
    }
    this.notify();
  }

  // -------------------------------------------------------------- inbound
  private handle(raw: string, stream: "main" | "map") {
    let msg: BridgeMsg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const now = Date.now();
    if (stream === "map") {
      if (msg.type === "map") {
        this.lastRx.map = now;
        this.onMap(msg);
      }
      this.notify();
      return;
    }
    this.lastRx[msg.type] = now;
    switch (msg.type) {
      case "hello":
        this.onHello(msg);
        break;
      case "telemetry":
        this.everConnected = true;
        this.onTelemetry(msg, now);
        break;
      case "health":
        this.onHealth(msg, now);
        break;
      case "paths":
        this.paths = msg;
        break;
    }
    this.notify();
  }

  private onHello(h: HelloMsg) {
    const prevHost = this.hello?.identity.hostname;
    this.hello = h;
    this.identityProblem = null;
    const cfg = this.config;
    if (h.mode === "ros" && cfg) {
      if (cfg.expectedHostname && h.identity.hostname !== cfg.expectedHostname) {
        this.identityProblem = `bridge hostname "${h.identity.hostname}" != expected "${cfg.expectedHostname}"`;
      } else if (cfg.expectedDomainId != null && h.identity.ros_domain_id !== cfg.expectedDomainId) {
        this.identityProblem = `ROS_DOMAIN_ID ${h.identity.ros_domain_id} != expected ${cfg.expectedDomainId}`;
      }
    }
    if (prevHost && prevHost !== h.identity.hostname) {
      // connected to a different machine: drop everything from the previous one
      this.map = null;
      this.paths = null;
      this.telemetry = null;
      this.health = null;
      this.vel = [];
      this.rates = [];
      this.coverage = [];
      this.latency = [];
      this.temps = [];
      this.tempPeak = null;
      this.robotTempLevels.clear();
      this.peerPrev.clear();
      this.robotLogs = [];
      this.seenLogs.clear();
      this.peerTraffic.clear();
      this.rangeLevels.clear();
      this.probes = [];
      this.transits = [];
      this.prevTopicStatus.clear();
      this.mapCh.recycle();
      this.emit("warn", "identity", `Bridge identity changed: ${prevHost} -> ${h.identity.hostname}`);
    }
    if (this.identityProblem) this.emit("error", "identity", `IDENTITY MISMATCH: ${this.identityProblem}`);
    for (const w of h.identity.warnings) this.emit("warn", "identity", w);
    if (!this.bridgeAllowsMap) this.emit("info", "map", "Map stream disabled in bridge config (layers.map.enabled)");
    this.syncMapChannel();
    this.emit("info", "link", `Connected to ${h.mode === "sim" ? "SIMULATOR" : h.identity.hostname} (bridge ${h.bridge_version})`);
  }

  private onTelemetry(m: TelemetryMsg, now: number) {
    this.telemetry = m;
    // one-way delay estimate: browser receipt time vs bridge send time corrected by clock offset
    const off = this.linkStats.clockOffsetMs;
    if (off != null) {
      this.transits.push(Math.max(0, now - (m.server_time * 1000 - off)));
      cap(this.transits, 10);
      this.linkStats.transitMs = median(this.transits);
    }
    const v = m.velocity;
    const valid = !!v?.valid;
    this.vel.push({
      t: now,
      linear: valid ? (v!.linear ?? v!.speed) : null,
      angular: valid ? v!.angular : null,
      cmdLinear: m.cmd_vel?.age_s != null && m.cmd_vel.age_s < 1 ? m.cmd_vel.linear : null,
      cmdAngular: m.cmd_vel?.age_s != null && m.cmd_vel.age_s < 1 ? m.cmd_vel.angular : null,
    });
    cap(this.vel, 6000);

    const at = m.attitude;
    if (at && at.valid) {
      const lv = tempLevelWithHysteresis(at.tilt_deg, at.tilt_warn_deg, at.tilt_crit_deg, this.tiltLevel);
      if (lv !== this.tiltLevel && this.tiltLevel !== "unknown") {
        if (lv === "crit") this.emit("error", "posture", `ROBOT TILTED ${at.tilt_deg}° (roll ${at.roll_deg}°, pitch ${at.pitch_deg}°) - risk of falling`);
        else if (lv === "warn") this.emit("warn", "posture", `Robot tilted ${at.tilt_deg}° (roll ${at.roll_deg}°, pitch ${at.pitch_deg}°)`);
        else this.emit("info", "posture", `Robot upright again (${at.tilt_deg}°)`);
      }
      this.tiltLevel = lv;
      this.maxTilt = Math.max(this.maxTilt, at.tilt_deg ?? 0);
    }
    const ex = m.exploration;
    if (ex.pose_jumps != null && ex.pose_jumps > this.prevJumps && ex.last_jump) {
      const j = ex.last_jump;
      this.emit("warn", "pose", `Position estimate jumped ${j.distance_m.toFixed(2)} m `
        + `(${j.from[0]}, ${j.from[1]} → ${j.to[0]}, ${j.to[1]}) - localisation/TF correction, not real movement`);
    }
    this.prevJumps = ex.pose_jumps ?? 0;
    if (ex.stalled !== this.prevStalled) {
      if (ex.stalled) this.emit("warn", "stall", "Robot STALLED: trying to move but no progress");
      else this.emit("info", "stall", "Stall cleared");
      this.prevStalled = ex.stalled;
    }
    if (ex.state !== this.prevState) {
      if (this.prevState !== null) this.emit("info", "exploration", `Exploration state: ${this.prevState} -> ${ex.state}`);
      this.prevState = ex.state;
    }
    const nav = m.nav.status;
    if (nav !== this.prevNav) {
      if (nav) this.emit(nav === "ABORTED" ? "warn" : "info", "nav", `Navigation status: ${nav}`);
      this.prevNav = nav;
    }
    if (m.tf.ok !== this.prevTfOk) {
      if (!m.tf.ok) this.emit("warn", "tf", `TF problem: ${m.tf.errors[0] ?? "unknown"}`);
      else if (this.prevTfOk === false) this.emit("info", "tf", "TF chain OK");
      this.prevTfOk = m.tf.ok;
    }
  }

  private onHealth(h: HealthMsg, now: number) {
    this.health = h;
    for (const l of h.logs ?? []) {
      // id restarts when the bridge restarts, so identify a line by id AND time
      const key = `${l.id}@${l.t}`;
      if (this.seenLogs.has(key)) continue;
      this.seenLogs.add(key);
      if (this.seenLogs.size > 2000) this.seenLogs = new Set(Array.from(this.seenLogs).slice(-1000));
      this.robotLogs.push(l);
      if (l.level >= 40) this.emit("error", "robotlog", `[${l.node}] ${l.msg}`);
    }
    cap(this.robotLogs, 500);
    for (const t of h.topics) {
      if (t.role !== "range") continue;
      const prev = this.rangeLevels.get(t.name) ?? "unknown";
      const lv = t.status === "missing" ? "unknown" : lowLevelWithHysteresis(t.range_m ?? null, t.range_warn_m ?? null, t.range_crit_m ?? null, prev);
      if (lv !== prev && lv !== "unknown" && prev !== "unknown") {
        if (lv === "crit") this.emit("error", "obstacle", `${t.label ?? t.name}: obstacle VERY close (${t.range_m?.toFixed(2)} m)`);
        else if (lv === "warn") this.emit("warn", "obstacle", `${t.label ?? t.name}: obstacle close (${t.range_m?.toFixed(2)} m)`);
      }
      this.rangeLevels.set(t.name, lv);
    }
    const rates: Record<string, number | null> = {};
    for (const t of h.topics) {
      rates[t.name] = t.status === "missing" ? null : t.rate_hz;
      const prev = this.prevTopicStatus.get(t.name);
      // Temperature topics: hot/too-hot events come from onCompute (with hysteresis);
      // here only report the topic disappearing or coming back.
      if (t.role === "temperature" && prev !== t.status && t.status !== "missing" && prev !== "missing") {
        this.prevTopicStatus.set(t.name, t.status);
        continue;
      }
      if (prev !== t.status) {
        if (t.status === "error" || t.status === "missing") this.emit("error", "topic", `${t.name}: ${t.status.toUpperCase()} ${t.note}`);
        else if (t.status === "warn") this.emit("warn", "topic", `${t.name}: ${t.note}`);
        else if (prev && (prev === "error" || prev === "missing" || prev === "warn")) this.emit("info", "topic", `${t.name}: recovered`);
        this.prevTopicStatus.set(t.name, t.status);
      }
    }
    this.rates.push({ t: now, rates });
    cap(this.rates, 900);
    this.onCompute(h, now);
    // coverage comes from health so it keeps working with the map stream off
    const ms = h.map?.stats;
    if (h.map && ms && h.map.version !== this.prevMapStatsVersion) {
      this.prevMapStatsVersion = h.map.version;
      this.coverage.push({
        t: now,
        knownArea: ms.known_area_m2,
        coveragePct: ms.coverage_pct,
        frontiers: this.telemetry?.exploration.frontier_count ?? null,
      });
      cap(this.coverage, 900);
    }
  }

  /** NUC temperature trend, threshold events and thermal-throttling detection. */
  private onCompute(h: HealthMsg, now: number) {
    const robot: Record<string, number | null> = {};
    for (const rt of this.robotTemps) {
      robot[rt.label] = rt.c;
      const prev = this.robotTempLevels.get(rt.name) ?? "unknown";
      const lv = tempLevelWithHysteresis(rt.c, rt.warn, rt.crit, prev);
      if (lv !== prev && lv !== "unknown") {
        if (lv === "crit") this.emit("error", "thermal", `ROBOT OVERHEATING: ${rt.label} ${rt.c} °C ≥ ${rt.crit} °C`);
        else if (lv === "warn") this.emit("warn", "thermal", `Robot hot: ${rt.label} ${rt.c} °C ≥ ${rt.warn} °C`);
        else if (prev === "warn" || prev === "crit") this.emit("info", "thermal", `${rt.label} back to normal (${rt.c} °C)`);
      }
      this.robotTempLevels.set(rt.name, lv);
    }
    // Helper computers (Raspberry Pi): their temperature joins the graph as "<name>".
    for (const pe of h.peers ?? []) {
      robot[pe.name] = pe.online ? pe.stats?.temp_max_c ?? null : null;
      this.peerEvents(pe);
      // traffic history for the Pi link graph (sum over interfaces, kB/s); gaps while offline
      const ifs = pe.online ? pe.stats?.net?.interfaces ?? null : null;
      const arr = this.peerTraffic.get(pe.name) ?? [];
      arr.push({
        t: now,
        rx: ifs ? ifs.reduce((a, i) => a + i.rx_Bps, 0) / 1024 : null,
        tx: ifs ? ifs.reduce((a, i) => a + i.tx_Bps, 0) / 1024 : null,
        rtt: pe.online ? pe.rtt_ms : null,
      });
      cap(arr, 900);
      this.peerTraffic.set(pe.name, arr);
    }
    const c = h.compute && !h.compute.error ? h.compute : null;
    const sensors: Record<string, number> = {};
    for (const t of c?.temps.slice(0, 4) ?? []) sensors[t.label] = t.c;
    if (c || this.robotTemps.length || (h.peers ?? []).length) {
      this.temps.push({ t: now, max: c?.temp_max_c ?? null, sensors, robot });
      cap(this.temps, 1800); // 30 min at 1 Hz
    }
    if (!c) return;
    if (c.temp_max_c != null && (!this.tempPeak || c.temp_max_c > this.tempPeak.c)) this.tempPeak = { c: c.temp_max_c, t: now };
    const level = tempLevelWithHysteresis(c.temp_max_c, c.temp_warn_c ?? 80, c.temp_crit_c ?? 90, this.prevTempLevel);
    this.nucTempLevel = level;
    if (level !== this.prevTempLevel && level !== "unknown") {
      const where = c.temps[0]?.label ?? "NUC";
      if (level === "crit") this.emit("error", "thermal", `NUC OVERHEATING: ${c.temp_max_c} °C (${where}) ≥ ${c.temp_crit_c} °C`);
      else if (level === "warn") this.emit("warn", "thermal", `NUC hot: ${c.temp_max_c} °C (${where}) ≥ ${c.temp_warn_c} °C`);
      else if (this.prevTempLevel === "warn" || this.prevTempLevel === "crit") this.emit("info", "thermal", `NUC temperature back to normal (${c.temp_max_c} °C)`);
      this.prevTempLevel = level;
    }
    // Throttling: one event when it starts, one when it has stopped for 10 s (with a total),
    // never one per health message.
    if (c.throttle_count != null) {
      if (this.prevThrottle != null && c.throttle_count > this.prevThrottle) {
        if (this.throttleEpisode == null) {
          this.throttleEpisode = { start: now, events: 0 };
          this.emit("warn", "thermal", `CPU thermal throttling started (${c.temp_max_c} °C) - the NUC is slowing its CPU to protect itself`);
        }
        this.throttleEpisode.events += c.throttle_count - this.prevThrottle;
        this.lastThrottleAt = now;
      } else if (this.throttleEpisode && now - this.lastThrottleAt > 10_000) {
        const secs = ((this.lastThrottleAt - this.throttleEpisode.start) / 1000).toFixed(0);
        this.emit("info", "thermal", `CPU throttling stopped (${this.throttleEpisode.events} events over ${secs} s)`);
        this.throttleEpisode = null;
      }
      this.prevThrottle = c.throttle_count;
    }
  }

  private nucTempLevel: TempLevel = "unknown";

  private peerEvents(pe: import("./types").PeerStatus) {
    const prev = this.peerPrev.get(pe.name);
    const th = pe.stats?.throttle ?? null;
    const uv = !!th?.under_voltage_now;
    const thr = !!(th?.throttled_now || th?.freq_capped_now);
    const tl = tempLevelWithHysteresis(pe.online ? pe.stats?.temp_max_c ?? null : null, pe.temp_warn_c, pe.temp_crit_c, prev?.tl ?? "unknown");
    if (prev) {
      if (prev.online && !pe.online) this.emit("error", "peer", `${pe.name} OFFLINE (not answering on the network)`);
      if (!prev.online && pe.online) this.emit("info", "peer", `${pe.name} back online (${pe.rtt_ms} ms)`);
      if (!prev.uv && uv) this.emit("error", "peer", `${pe.name} UNDER-VOLTAGE: power supply too weak - it may slow down or reboot`);
      if (prev.uv && !uv && pe.online) this.emit("info", "peer", `${pe.name} power back to normal`);
      if (!prev.thr && thr) this.emit("warn", "peer", `${pe.name} is throttling its CPU (power or heat)`);
      if (tl !== prev.tl && tl !== "unknown") {
        if (tl === "crit") this.emit("error", "thermal", `${pe.name} OVERHEATING: ${pe.stats?.temp_max_c} °C`);
        else if (tl === "warn") this.emit("warn", "thermal", `${pe.name} hot: ${pe.stats?.temp_max_c} °C`);
        else if (prev.tl === "warn" || prev.tl === "crit") this.emit("info", "thermal", `${pe.name} temperature back to normal`);
      }
    }
    if (pe.identity_ok === false && prev?.id !== false) {
      this.emit("error", "identity", `${pe.name}: hostname "${pe.stats?.hostname}" is not the expected "${pe.expected_hostname}" - check the address`);
    }
    this.peerPrev.set(pe.name, { online: pe.online, uv, thr, id: pe.identity_ok, tl });
  }

  peerTempLevel(name: string): TempLevel {
    return this.peerPrev.get(name)?.tl ?? "unknown";
  }

  /** Current NUC temperature level (bridge-configured thresholds, with 3 °C hysteresis). */
  get tempLevel(): TempLevel {
    const c = this.identityProblem ? null : this.health?.compute;
    if (!c || c.temp_max_c == null) return "unknown";
    return this.nucTempLevel;
  }

  /** Robot temperatures reported through the bridge's temperature_topics. */
  get robotTemps(): RobotTemp[] {
    if (this.identityProblem || !this.health) return [];
    return this.health.topics
      .filter((t) => t.role === "temperature")
      .map((t) => ({
        name: t.name, label: t.label ?? t.name, c: t.status === "missing" ? null : t.temp_c ?? null,
        warn: t.temp_warn_c ?? null, crit: t.temp_crit_c ?? null, status: t.status,
      }));
  }

  robotTempLevel(name: string): TempLevel {
    return this.robotTempLevels.get(name) ?? "unknown";
  }

  /** True when the CPU is currently clocked well below its maximum while hot (throttling). */
  get throttlingNow(): boolean {
    const c = this.health?.compute;
    return !!c && c.cpu_mhz != null && c.cpu_max_mhz != null && this.tempLevel !== "ok" && c.cpu_mhz < 0.6 * c.cpu_max_mhz;
  }

  private onMap(m: MapMsg) {
    if (!this.mapEnabled) return;
    // decode at most one map at a time; keep only the newest pending one
    this.pendingMap = m;
    if (this.mapDecoding) return;
    void this.decodeLoop();
  }

  private async decodeLoop() {
    this.mapDecoding = true;
    while (this.pendingMap) {
      const m = this.pendingMap;
      this.pendingMap = null;
      try {
        const decoded = await decodeMap(m);
        if (this.mapEnabled) this.map = decoded;
        this.mapError = null;
      } catch (e) {
        this.mapError = e instanceof Error ? e.message : String(e);
      }
      this.notify();
    }
    this.mapDecoding = false;
  }

  // --------------------------------------------------------------- events
  emit(level: EventLevel, kind: string, message: string) {
    const e: SessionEvent = { t: Date.now(), level, kind, message };
    this.events.push(e);
    cap(this.events, 300);
    this.eventListeners.forEach((l) => l(e));
  }

  // ------------------------------------------------------------- helpers
  /** True only when the robot pose can be presented as LIVE. */
  get poseLive(): boolean {
    return this.link === "live" && !this.identityProblem && !!this.telemetry?.pose?.valid;
  }

  /** Map statistics (from health; available even with the map stream off). */
  get mapStats() {
    return this.identityProblem ? null : this.health?.map?.stats ?? null;
  }

  ageMs(kind: string): number | null {
    const t = this.lastRx[kind];
    return t ? Date.now() - t : null;
  }
}

export function mapUrl(bridgeUrl: string): string {
  try {
    const u = new URL(bridgeUrl);
    u.pathname = u.pathname.replace(/\/+$/, "") + "/map";
    return u.toString();
  } catch {
    return bridgeUrl.replace(/\/+$/, "") + "/map";
  }
}

export function clockUrl(bridgeUrl: string): string {
  const u = new URL(bridgeUrl);
  u.protocol = u.protocol === "wss:" ? "https:" : "http:";
  u.pathname = "/api/clock";
  u.search = "";
  return u.toString();
}
