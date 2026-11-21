// Framework-independent telemetry client.
//
// * RECEIVE-ONLY: it opens a websocket to the bridge and never calls send().
// * Reconnects forever with capped exponential backoff + jitter.
// * A watchdog closes "half-open" sockets (common after Wi-Fi drops) so the
//   reconnect loop kicks in instead of silently showing frozen data.
// * Freshness is measured with the browser's own clock at receipt time.

import { decodeMap } from "./mapDecode";
import type {
  BridgeMsg, DashboardConfig, DecodedMap, HealthMsg, HelloMsg, LinkState, MapMsg, PathsMsg, TelemetryMsg,
  TopicStatus,
} from "./types";
import type { EventLevel, SessionEvent } from "./historyTypes";

export const STALE_AFTER_MS = 1500;
export const LOST_AFTER_MS = 3500;
const SOCKET_DEAD_AFTER_MS = 6000;
const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 5000;

export interface VelPoint { t: number; linear: number | null; angular: number | null; cmdLinear: number | null; cmdAngular: number | null }
export interface RatePoint { t: number; rates: Record<string, number | null> }
export interface CoveragePoint { t: number; knownArea: number | null; coveragePct: number | null; frontiers: number | null }

function cap<T>(arr: T[], n: number) {
  if (arr.length > n) arr.splice(0, arr.length - n);
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
  socketOpen = false;
  everConnected = false;
  connectAttempts = 0;
  lastRx: Record<string, number> = {};
  lastAnyRx = 0;
  lostSince: number | null = null;
  outages = 0;
  identityProblem: string | null = null;

  vel: VelPoint[] = [];
  rates: RatePoint[] = [];
  coverage: CoveragePoint[] = [];
  events: SessionEvent[] = [];

  private ws: WebSocket | null = null;
  private stopped = false;
  private backoff = BACKOFF_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<() => void>();
  private eventListeners = new Set<(e: SessionEvent) => void>();
  private version = 0;
  private notifyPending = false;
  private prevTopicStatus = new Map<string, TopicStatus>();
  private prevStalled = false;
  private prevNav: string | null = null;
  private prevState: string | null = null;
  private prevTfOk: boolean | null = null;
  private mapDecoding = false;
  private pendingMap: MapMsg | null = null;

  // ------------------------------------------------------------ lifecycle
  start(config: DashboardConfig) {
    this.config = config;
    this.stopped = false;
    this.connect();
    this.watchdog = setInterval(() => this.tick(), 250);
  }

  stop() {
    this.stopped = true;
    if (this.watchdog) clearInterval(this.watchdog);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
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

  // ----------------------------------------------------------- connection
  private connect() {
    if (this.stopped || !this.config) return;
    this.connectAttempts++;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.config.bridgeUrl);
    } catch (e) {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.socketOpen = true;
      this.backoff = BACKOFF_MIN_MS;
      this.lastAnyRx = Date.now();
      this.notify();
    };
    ws.onmessage = (ev) => this.handle(ev.data);
    ws.onerror = () => {
      /* onclose follows */
    };
    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null;
        this.socketOpen = false;
        this.scheduleReconnect();
        this.notify();
      }
    };
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    const delay = this.backoff * (0.8 + Math.random() * 0.4);
    this.backoff = Math.min(BACKOFF_MAX_MS, this.backoff * 1.7);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** Bridge URL for display. */
  get bridgeUrl() {
    return this.config?.bridgeUrl ?? "";
  }

  // ------------------------------------------------------------ watchdog
  private tick() {
    const now = Date.now();
    // half-open socket: no bytes for a long time -> force reconnect
    if (this.ws && this.socketOpen && now - this.lastAnyRx > SOCKET_DEAD_AFTER_MS) {
      const dead = this.ws;
      this.ws = null;
      this.socketOpen = false;
      try {
        dead.close();
      } catch {
        /* ignore */
      }
      this.scheduleReconnect();
    }
    const lastTel = this.lastRx.telemetry ?? 0;
    let next: LinkState;
    if (!this.everConnected) next = "connecting";
    else if (!this.socketOpen || now - lastTel > LOST_AFTER_MS) next = "lost";
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

  // -------------------------------------------------------------- inbound
  private handle(raw: unknown) {
    if (typeof raw !== "string") return;
    let msg: BridgeMsg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const now = Date.now();
    this.lastAnyRx = now;
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
      case "map":
        this.onMap(msg);
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
      this.prevTopicStatus.clear();
      this.emit("warn", "identity", `Bridge identity changed: ${prevHost} -> ${h.identity.hostname}`);
    }
    if (this.identityProblem) this.emit("error", "identity", `IDENTITY MISMATCH: ${this.identityProblem}`);
    for (const w of h.identity.warnings) this.emit("warn", "identity", w);
    this.emit("info", "link", `Connected to ${h.mode === "sim" ? "SIMULATOR" : h.identity.hostname} (bridge ${h.bridge_version})`);
  }

  private onTelemetry(m: TelemetryMsg, now: number) {
    this.telemetry = m;
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

    const ex = m.exploration;
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
    const rates: Record<string, number | null> = {};
    for (const t of h.topics) {
      rates[t.name] = t.status === "missing" ? null : t.rate_hz;
      const prev = this.prevTopicStatus.get(t.name);
      if (prev !== t.status) {
        if (t.status === "error" || t.status === "missing") this.emit("error", "topic", `${t.name}: ${t.status.toUpperCase()} ${t.note}`);
        else if (t.status === "warn") this.emit("warn", "topic", `${t.name}: ${t.note}`);
        else if (prev && (prev === "error" || prev === "missing" || prev === "warn")) this.emit("info", "topic", `${t.name}: recovered`);
        this.prevTopicStatus.set(t.name, t.status);
      }
    }
    this.rates.push({ t: now, rates });
    cap(this.rates, 900);
  }

  private onMap(m: MapMsg) {
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
        this.map = await decodeMap(m);
        this.mapError = null;
        this.coverage.push({
          t: Date.now(),
          knownArea: m.stats.known_area_m2,
          coveragePct: m.stats.coverage_pct,
          frontiers: this.telemetry?.exploration.frontier_count ?? null,
        });
        cap(this.coverage, 900);
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

  ageMs(kind: string): number | null {
    const t = this.lastRx[kind];
    return t ? Date.now() - t : null;
  }
}
