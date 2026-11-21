import type { Sample, SessionEvent, SessionSummary, RateSummary } from "./historyTypes.ts";

/** Pure summary computation shared by the browser recorder and the API route. */
export function summarize(samples: Sample[], events: SessionEvent[]): SessionSummary {
  const n = samples.length;
  const duration = n > 1 ? (samples[n - 1].t - samples[0].t) / 1000 : 0;
  let maxSpeed = 0;
  let movingSum = 0;
  let movingN = 0;
  let distance = 0;
  let lostCount = 0;
  let lostMs = 0;
  let prevLost = false;
  const rateAcc: Record<string, { min: number; max: number; sum: number; n: number }> = {};

  for (let i = 0; i < n; i++) {
    const s = samples[i];
    const live = s.link === "live" && s.pose_valid;
    if (live && s.speed != null) {
      maxSpeed = Math.max(maxSpeed, s.speed);
      if (s.speed > 0.03) {
        movingSum += s.speed;
        movingN++;
      }
    }
    if (s.distance_m != null) distance = Math.max(distance, s.distance_m);
    const lost = s.link === "lost";
    if (lost && !prevLost) lostCount++;
    if (lost && i > 0) lostMs += s.t - samples[i - 1].t;
    prevLost = lost;
    if (s.link === "live") {
      for (const [topic, hz] of Object.entries(s.rates)) {
        if (hz == null) continue;
        const a = (rateAcc[topic] ??= { min: Infinity, max: -Infinity, sum: 0, n: 0 });
        a.min = Math.min(a.min, hz);
        a.max = Math.max(a.max, hz);
        a.sum += hz;
        a.n++;
      }
    }
  }
  const topic_rates: Record<string, RateSummary> = {};
  for (const [k, a] of Object.entries(rateAcc)) {
    topic_rates[k] = { min: round(a.min), avg: round(a.sum / a.n), max: round(a.max), n: a.n };
  }
  const last = [...samples].reverse();
  const lastKnown = last.find((s) => s.known_area_m2 != null);
  const lastCov = last.find((s) => s.coverage_pct != null);
  const lastFr = last.find((s) => s.frontiers != null);
  return {
    duration_s: round(duration, 1),
    samples: n,
    distance_m: round(distance),
    max_speed: round(maxSpeed),
    avg_moving_speed: movingN ? round(movingSum / movingN) : 0,
    final_known_area_m2: lastKnown?.known_area_m2 ?? null,
    final_coverage_pct: lastCov?.coverage_pct ?? null,
    final_frontiers: lastFr?.frontiers ?? null,
    link_lost_count: lostCount,
    link_lost_s: round(lostMs / 1000, 1),
    stall_events: events.filter((e) => e.kind === "stall" && e.level !== "info").length,
    error_events: events.filter((e) => e.level === "error").length,
    warn_events: events.filter((e) => e.level === "warn").length,
    topic_rates,
  };
}

function round(v: number, d = 2): number {
  const f = 10 ** d;
  return Math.round(v * f) / f;
}

const CSV_FIXED = [
  "t_iso", "t_ms", "elapsed_s", "link", "pose_valid", "x", "y", "yaw", "frame", "speed", "linear", "angular",
  "cmd_linear", "state", "frontiers", "distance_m", "known_area_m2", "coverage_pct",
] as const;

function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function samplesToCsv(samples: Sample[]): string {
  const topics = Array.from(new Set(samples.flatMap((s) => Object.keys(s.rates)))).sort();
  const header = [...CSV_FIXED, ...topics.map((t) => `rate_hz:${t}`)];
  const t0 = samples[0]?.t ?? 0;
  const rows = samples.map((s) => {
    const fixed = [
      new Date(s.t).toISOString(), s.t, ((s.t - t0) / 1000).toFixed(1), s.link, s.pose_valid, s.x, s.y, s.yaw,
      s.frame, s.speed, s.linear, s.angular, s.cmd_linear, s.state, s.frontiers, s.distance_m, s.known_area_m2,
      s.coverage_pct,
    ];
    return [...fixed, ...topics.map((t) => s.rates[t])].map(csvCell).join(",");
  });
  return [header.map(csvCell).join(","), ...rows].join("\n") + "\n";
}

export function eventsToCsv(events: SessionEvent[]): string {
  const rows = events.map((e) => [new Date(e.t).toISOString(), e.t, e.level, e.kind, e.message].map(csvCell).join(","));
  return ["t_iso,t_ms,level,kind,message", ...rows].join("\n") + "\n";
}
