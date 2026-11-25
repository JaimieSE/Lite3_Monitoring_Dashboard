// Records a monitoring session at 1 Hz and persists it to the local Next.js
// API (/api/history), which writes JSON files on this Mac. Purely local -
// nothing is ever sent to the robot.

import type { TelemetryClient } from "./client";
import { MAX_EVENTS, MAX_SAMPLES, type Sample, type Session, type SessionEvent } from "./historyTypes";
import { summarize } from "./summary";

const FLUSH_EVERY_MS = 10_000;

function newId(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  const rand = Math.random().toString(36).slice(2, 6).padEnd(4, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${rand}`;
}

export class Recorder {
  session: Session | null = null;
  lastFlush = 0;
  lastFlushOk: boolean | null = null;
  flushError: string | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private unsubEvents: (() => void) | null = null;
  private flushing = false;
  private dirty = false;

  constructor(private client: TelemetryClient, private onChange: () => void) {}

  get recording() {
    return this.session !== null && this.session.ended_at === null;
  }

  start(label?: string) {
    if (this.recording) return;
    const c = this.client;
    const now = Date.now();
    const id = newId();
    this.session = {
      version: 1,
      id,
      label: label || `${c.hello?.mode === "sim" ? "Simulation" : "Live run"} ${new Date(now).toLocaleTimeString()}`,
      notes: "",
      mode: c.hello?.mode ?? "unknown",
      robot: {
        hostname: c.hello?.identity.hostname ?? null,
        robot_name: c.hello?.identity.robot_name ?? null,
        ros_domain_id: c.hello?.identity.ros_domain_id ?? null,
      },
      started_at: now,
      ended_at: null,
      updated_at: now,
      summary: summarize([], []),
      samples: [],
      events: [],
    };
    this.unsubEvents = c.onEvent((e) => this.addEvent(e));
    this.addEvent({ t: now, level: "info", kind: "session", message: "Recording started" });
    this.timer = setInterval(() => this.sample(), 1000);
    this.onChange();
  }

  async stop() {
    if (!this.session || !this.recording) return;
    this.addEvent({ t: Date.now(), level: "info", kind: "session", message: "Recording stopped" });
    this.session.ended_at = Date.now();
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.unsubEvents?.();
    this.unsubEvents = null;
    await this.flush(true);
    this.onChange();
  }

  private addEvent(e: SessionEvent) {
    if (!this.session) return;
    this.session.events.push(e);
    if (this.session.events.length > MAX_EVENTS) this.session.events.splice(0, this.session.events.length - MAX_EVENTS);
    this.dirty = true;
  }

  private sample() {
    const s = this.session;
    if (!s) return;
    const c = this.client;
    const tel = c.telemetry;
    const live = c.poseLive;
    const pose = live ? tel?.pose ?? null : null;
    const velOk = c.link === "live" && !!tel?.velocity?.valid;
    const rates: Record<string, number | null> = {};
    if (c.link === "live" && c.health) for (const t of c.health.topics) rates[t.name] = t.status === "missing" ? null : t.rate_hz;
    const smp: Sample = {
      t: Date.now(),
      link: c.link,
      pose_valid: live,
      x: pose?.x ?? null,
      y: pose?.y ?? null,
      yaw: pose?.yaw ?? null,
      frame: pose?.frame ?? null,
      speed: velOk ? tel!.velocity!.speed : null,
      linear: velOk ? tel!.velocity!.linear : null,
      angular: velOk ? tel!.velocity!.angular : null,
      cmd_linear: c.link === "live" ? tel?.cmd_vel?.linear ?? null : null,
      state: c.link === "live" ? tel?.exploration.state ?? null : null,
      frontiers: c.link === "live" ? tel?.exploration.frontier_count ?? null : null,
      distance_m: tel?.exploration.distance_travelled_m ?? null,
      known_area_m2: c.mapStats?.known_area_m2 ?? null,
      coverage_pct: c.mapStats?.coverage_pct ?? null,
      link_rtt_ms: c.linkStats.probeFailures === 0 && c.linkStats.rttLastMs != null ? Math.round(c.linkStats.rttLastMs) : null,
      transit_ms: c.link === "live" && c.linkStats.transitMs != null ? Math.round(c.linkStats.transitMs) : null,
      map_stream: c.mapLink === "live" || c.mapLink === "connecting",
      nuc_temp_c: c.link === "live" ? c.health?.compute?.temp_max_c ?? null : null,
      nuc_cpu_pct: c.link === "live" ? c.health?.compute?.cpu_total_pct ?? null : null,
      robot_temp_c: c.link === "live" ? maxOrNull(c.robotTemps.map((r) => r.c)) : null,
      tilt_deg: c.link === "live" && tel?.attitude?.valid ? tel.attitude.tilt_deg : null,
      obstacle_m: c.link === "live" ? minOrNull((c.health?.topics ?? []).filter((x) => x.role === "range").map((x) => x.range_m ?? null)) : null,
      rates,
    };
    s.samples.push(smp);
    if (s.samples.length > MAX_SAMPLES) s.samples.splice(0, s.samples.length - MAX_SAMPLES);
    s.updated_at = smp.t;
    this.dirty = true;
    if (smp.t - this.lastFlush > FLUSH_EVERY_MS) void this.flush();
    this.onChange();
  }

  async flush(force = false) {
    const s = this.session;
    if (!s || this.flushing || (!this.dirty && !force)) return;
    this.flushing = true;
    this.dirty = false;
    s.summary = summarize(s.samples, s.events);
    try {
      const res = await fetch("/api/history", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(s),
      });
      this.lastFlushOk = res.ok;
      this.flushError = res.ok ? null : `save failed (${res.status})`;
    } catch (e) {
      this.lastFlushOk = false;
      this.flushError = e instanceof Error ? e.message : "save failed";
      this.dirty = true;
    } finally {
      this.lastFlush = Date.now();
      this.flushing = false;
    }
  }

  /** Best-effort save when the tab closes. */
  flushOnUnload() {
    const s = this.session;
    if (!s || !this.recording) return;
    s.summary = summarize(s.samples, s.events);
    try {
      navigator.sendBeacon("/api/history", new Blob([JSON.stringify(s)], { type: "application/json" }));
    } catch {
      /* ignore */
    }
  }
}

function maxOrNull(xs: (number | null)[]): number | null {
  const v = xs.filter((x): x is number => x != null);
  return v.length ? Math.max(...v) : null;
}

function minOrNull(xs: (number | null)[]): number | null {
  const v = xs.filter((x): x is number => x != null);
  return v.length ? Math.min(...v) : null;
}
