"use client";

import { Fragment, useState } from "react";
import { useTelemetry } from "./TelemetryProvider";
import { Dot, Metric, Panel, StatusPill, topicLevel, type Level } from "./ui";
import { TimeSeriesChart, type Series } from "./TimeSeriesChart";
import { deg, fmt, fmtAge, fmtBytesRate, fmtDuration } from "@/lib/format";
import { latestPerTask, reportOutcome, sceneImageUrl, scoreTotal } from "@/lib/perception";
import type { MissionReport, SceneRequest } from "@/lib/types";

/** Wraps live values: greys them out and labels them when they are not live. */
function LiveGate({ live, children }: { live: boolean; children: React.ReactNode }) {
  return (
    <div className="relative">
      <div className={live ? "" : "opacity-40 grayscale"}>{children}</div>
      {!live ? (
        <span className="absolute right-2 top-1 rounded bg-panel2 px-1 text-2xs font-semibold uppercase tracking-wider text-warn">not live</span>
      ) : null}
    </div>
  );
}

export function RobotPanel() {
  const { client, recorder } = useTelemetry();
  const t = client.identityProblem ? null : client.telemetry;
  const linkLive = client.link === "live" && !client.identityProblem;
  const pose = t?.pose;
  const vel = t?.velocity;
  const poseLevel: Level = !pose ? "crit" : client.poseLive ? "good" : "warn";
  const navStatus = t?.nav.status;
  const navLevel: Level =
    navStatus === "EXECUTING" || navStatus === "ACCEPTED" ? "good" : navStatus === "ABORTED" ? "crit" : navStatus === "SUCCEEDED" ? "good" : "idle";
  const session = recorder.session;

  return (
    <Panel
      title="Robot overview"
      right={
        <StatusPill level={poseLevel}>{!pose ? "no pose" : client.poseLive ? `pose ${fmtAge(pose.age_s)}` : "pose stale"}</StatusPill>
      }
    >
      <LiveGate live={client.poseLive}>
        <div className="grid grid-cols-4 gap-x-3 gap-y-2 px-3 py-2">
          <Metric label="X" value={fmt(pose?.x, 2)} unit="m" />
          <Metric label="Y" value={fmt(pose?.y, 2)} unit="m" />
          <Metric label="Yaw" value={fmt(deg(pose?.yaw), 1)} unit="°" />
          <Metric label="Frame" value={<span className="text-sm">{pose?.frame ?? "—"}</span>} sub={pose ? `via ${pose.source}` : undefined} />
        </div>
      </LiveGate>
      <LiveGate live={linkLive && !!vel?.valid}>
        <div className="grid grid-cols-4 gap-x-3 gap-y-2 border-t border-line px-3 py-2">
          <Metric label="Linear" value={fmt(vel?.linear, 2)} unit="m/s" sub={t?.cmd_vel?.linear != null ? `cmd ${fmt(t.cmd_vel.linear, 2)}` : undefined} />
          <Metric label="Lateral" value={fmt(vel?.lateral, 2)} unit="m/s" />
          <Metric label="Angular" value={fmt(vel?.angular, 2)} unit="rad/s" sub={t?.cmd_vel?.angular != null ? `cmd ${fmt(t.cmd_vel.angular, 2)}` : undefined} />
          <Metric label="Speed" value={fmt(vel?.speed, 2)} unit="m/s" sub={vel?.source === "estimated" ? "estimated" : undefined} />
        </div>
      </LiveGate>
      <LiveGate live={linkLive}>
      <div className="grid grid-cols-4 gap-x-3 gap-y-2 border-t border-line px-3 py-2">
        <Metric
          label="Navigation"
          value={<StatusPill level={navLevel}>{navStatus ?? "n/a"}</StatusPill>}
          sub={t?.nav.status_age_s != null ? `${fmtAge(t.nav.status_age_s)} ago` : "no status topic"}
        />
        <Metric label="To goal" value={fmt(t?.nav.distance_to_goal_m, 2)} unit="m" sub={t?.nav.global_path_length_m != null ? `path ${fmt(t.nav.global_path_length_m, 1)} m` : undefined} />
        <Metric label="Mission time" value={fmtDuration(t?.exploration.runtime_s)} sub="since first motion" />
        <Metric
          label="Session"
          value={session ? fmtDuration(((session.ended_at ?? Date.now()) - session.started_at) / 1000) : "—"}
          sub={recorder.recording ? "recording" : session ? "stopped" : "not recording"}
        />
      </div>
      </LiveGate>
    </Panel>
  );
}

export function ExplorationPanel() {
  const { client } = useTelemetry();
  const t = client.identityProblem ? null : client.telemetry;
  const ex = t?.exploration;
  const ms = client.mapStats; // available even with the map stream off
  const live = client.link === "live" && !client.identityProblem;
  const stateLevel: Level = !ex
    ? "idle"
    : ex.stalled
      ? "crit"
      : ex.state === "STATIONARY" || ex.state === "NO POSE"
        ? "warn"
        : ex.state === "COMPLETE?" || ex.moving
          ? "good"
          : "idle";
  const cov = ms?.coverage_pct;
  return (
    <Panel
      title="Exploration"
      right={ex ? <span className="text-2xs text-faint">state {ex.state_source}</span> : null}
    >
      <LiveGate live={live}>
        <div className="flex items-center justify-between px-3 pt-2">
          <StatusPill level={stateLevel} className="!text-xs">{ex?.state ?? "no data"}</StatusPill>
          {ex?.stalled ? <span className="num text-2xs text-crit">stalled {fmtAge(ex.stalled_for_s)}</span> : null}
        </div>
        <div className="grid grid-cols-3 gap-x-3 gap-y-2 px-3 py-2">
          <Metric label="Frontiers" value={ex?.frontier_count ?? "—"} sub={ex?.frontier_count == null ? "no frontier topic" : undefined} />
          <Metric
            label="Distance"
            value={fmt(ex?.distance_travelled_m, 1)}
            unit="m"
            sub={ex?.pose_jumps ? `${ex.pose_jumps} position jump${ex.pose_jumps === 1 ? "" : "s"} ignored` : undefined}
            level={ex?.pose_jumps ? "warn" : undefined}
          />
          <Metric label="Runtime" value={fmtDuration(ex?.runtime_s)} />
          <Metric
            label={cov != null ? "Coverage" : "Known area"}
            value={cov != null ? fmt(cov, 1) : fmt(ms?.known_area_m2, 1)}
            unit={cov != null ? "%" : "m²"}
            sub={ms ? `${fmt(ms.free_area_m2, 1)} m² free` : "no map"}
          />
          <Metric label="Stationary" value={fmtAge(ex?.stationary_s)} level={ex && (ex.stationary_s ?? 0) > 10 && !ex.moving ? "warn" : undefined} />
          <Metric label="Stall events" value={ex?.stall_events ?? "—"} level={ex && ex.stall_events > 0 ? "warn" : undefined} />
        </div>
      </LiveGate>
    </Panel>
  );
}

export function TfDiagPanel({ className = "" }: { className?: string }) {
  const { client } = useTelemetry();
  const t = client.identityProblem ? null : client.telemetry;
  const h = client.identityProblem ? null : client.health;
  const tf = t?.tf;
  const diag = h?.diagnostics;
  const live = client.link === "live";
  const flags = (h?.topics ?? []).filter((x) => x.role === "status_flag");
  return (
    <Panel
      title="TF & diagnostics"
      right={
        <StatusPill level={!tf ? "idle" : tf.required === false && tf.chain.length === 0 ? "idle" : tf.ok ? "good" : "warn"}>
          {!tf ? "no tf" : tf.required === false && tf.chain.length === 0 ? "tf not used" : tf.ok ? "tf ok" : "tf issue"}
        </StatusPill>
      }
      bodyClass="overflow-auto scroll-thin"
      className={className}
    >
      <LiveGate live={live}>
      {flags.length ? (
        <div className="border-b border-line px-3 py-2 text-2xs">
          <div className="mb-1 text-faint">Robot sensor status</div>
          <div className="flex flex-wrap gap-1">
            {flags.map((f) => {
              const lv: Level = f.status === "missing" ? "idle" : f.value === true && f.status !== "error" ? "good" : "crit";
              const text = f.status === "missing" ? "missing" : f.value === true ? "alive" : f.value === false ? "NOT alive" : "no data";
              return (
                <span key={f.name} title={`${f.name}: ${f.note || "ok"}`}>
                  <StatusPill level={lv}>
                    <span className="normal-case tracking-normal">{f.label ?? f.name} · {text}</span>
                  </StatusPill>
                </span>
              );
            })}
          </div>
        </div>
      ) : null}
      <div className="px-3 py-2 text-2xs">
        <div className="mb-1 text-faint">base frame: <span className="num text-muted">{tf?.base_frame ?? "—"}</span></div>
        <div className="flex flex-wrap items-center gap-1">
          {tf?.chain.map((e, i) => (
            <span key={i} className="num flex items-center gap-1">
              {i === 0 ? <span className="text-muted">{e.parent}</span> : null}
              <span className="text-faint">→</span>
              <span className={!e.static && (e.age_s ?? 0) > 1 ? "text-warn" : "text-ink"}>{e.child}</span>
              <span className="text-faint">({e.static ? "static" : fmtAge(e.age_s)})</span>
            </span>
          ))}
        </div>
        {tf?.errors.map((e) => (
          <div key={e} className="mt-1 text-warn">▲ {e}</div>
        ))}
        {tf?.notes?.map((e) => (
          <div key={e} className="mt-1 text-faint">● {e}</div>
        ))}
      </div>
      <div className="border-t border-line px-3 py-2 text-2xs">
        {diag ? (
          <>
            <div className="mb-1 flex gap-3">
              <span className="flex items-center gap-1"><Dot level="good" />{diag.ok} ok</span>
              <span className="flex items-center gap-1"><Dot level="warn" />{diag.warn} warn</span>
              <span className="flex items-center gap-1"><Dot level="crit" />{diag.error} error</span>
              <span className="flex items-center gap-1"><Dot level="idle" />{diag.stale} stale</span>
              <span className="ml-auto text-faint">{fmtAge(diag.age_s)} ago</span>
            </div>
            {diag.items.slice(0, 8).map((d) => (
              <div key={d.name} className="flex items-center gap-2 leading-5">
                <Dot level={d.level === 0 ? "good" : d.level === 1 ? "warn" : d.level === 2 ? "crit" : "idle"} />
                <span className="truncate text-muted">{d.name}</span>
                <span className="ml-auto truncate text-ink">{d.message}</span>
              </div>
            ))}
          </>
        ) : (
          <span className="text-faint">No diagnostics topic</span>
        )}
      </div>
      </LiveGate>
    </Panel>
  );
}

export function HealthPanel() {
  const { client } = useTelemetry();
  const h = client.identityProblem ? null : client.health;
  const live = client.link === "live";
  const topics = h?.topics ?? [];
  const bad = topics.filter((t) => t.status === "error" || t.status === "missing").length;
  const warn = topics.filter((t) => t.status === "warn").length;
  const level: Level = !h ? "idle" : bad ? "crit" : warn ? "warn" : "good";
  return (
    <Panel
      title="System health"
      right={
        <span className="flex items-center gap-2">
          {h ? <span className="text-2xs text-faint">{h.nodes.count} nodes · {topics.length} topics</span> : null}
          <StatusPill level={level}>{!h ? "no data" : bad ? `${bad} failing` : warn ? `${warn} degraded` : "all nominal"}</StatusPill>
        </span>
      }
      bodyClass="overflow-auto scroll-thin"
      className="h-full"
    >
      <LiveGate live={live}>
        <table className="w-full text-2xs">
          <thead className="sticky top-0 bg-panel text-left text-faint">
            <tr className="border-b border-line">
              <th className="px-3 py-1 font-medium">Topic</th>
              <th className="py-1 font-medium">Role</th>
              <th className="py-1 text-right font-medium">Rate</th>
              <th className="w-24 py-1 pl-2 font-medium">vs expected</th>
              <th className="py-1 text-right font-medium">Data</th>
              <th className="py-1 text-right font-medium">Age</th>
              <th className="py-1 text-right font-medium">Pubs</th>
              <th className="px-3 py-1 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {topics.map((t) => {
              const ref = t.expected_hz ?? t.min_hz;
              const frac = ref && t.rate_hz != null ? Math.min(1.2, t.rate_hz / ref) : null;
              const lv = topicLevel(t.status);
              return (
                <tr key={t.name} className="border-b border-line/50 hover:bg-panel2">
                  <td className="px-3 py-1">
                    <span className="flex items-center gap-1.5">
                      <Dot level={lv} />
                      <span className="num text-ink">{t.name}</span>
                    </span>
                  </td>
                  <td className="py-1 text-muted">{t.role}</td>
                  <td className="num py-1 text-right text-ink">{t.status === "missing" ? "—" : fmt(t.rate_hz, 1)}</td>
                  <td className="py-1 pl-2">
                    {frac != null ? (
                      <div className="relative h-1.5 w-20 rounded-sm bg-panel2" title={`${fmt(t.rate_hz, 1)} / ${ref} Hz`}>
                        <div
                          className={`absolute inset-y-0 left-0 rounded-sm ${lv === "good" ? "bg-good" : lv === "warn" ? "bg-warn" : "bg-crit"}`}
                          style={{ width: `${(frac / 1.2) * 100}%` }}
                        />
                        <div className="absolute inset-y-[-2px] w-px bg-muted" style={{ left: `${(1 / 1.2) * 100}%` }} />
                      </div>
                    ) : (
                      <span className="text-faint">event</span>
                    )}
                  </td>
                  <td className="num py-1 text-right text-muted">{t.status === "missing" ? "—" : fmtBytesRate(t.bytes_per_s)}</td>
                  <td className="num py-1 text-right text-muted">{fmtAge(t.age_s)}</td>
                  <td className={`num py-1 text-right ${t.publishers > 1 && t.note.includes("cross-robot") ? "text-warn" : "text-muted"}`}>{t.publishers}</td>
                  <td className="max-w-[260px] truncate px-3 py-1 text-muted" title={t.note}>{t.note}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {h && (h.missing_roles.length > 0 || (h.inactive_roles?.length ?? 0) > 0 || h.nodes.missing_expected.length > 0) ? (
          <div className="space-y-0.5 px-3 py-2 text-2xs">
            {h.inactive_roles?.length ? (
              <div className="text-faint">
                Inactive until their software runs (e.g. navigation): {h.inactive_roles.join(", ")}
              </div>
            ) : null}
            {h.missing_roles.length ? (
              <div className="text-muted">
                <span className="text-faint">Roles with no matching topic: </span>
                {h.missing_roles.join(", ")}
              </div>
            ) : null}
            {h.nodes.missing_expected.length ? (
              <div className="text-crit">■ Missing expected nodes: {h.nodes.missing_expected.join(", ")}</div>
            ) : null}
          </div>
        ) : null}
        {h ? (
          <div className="num flex flex-wrap gap-x-4 border-t border-line px-3 py-1.5 text-2xs text-faint">
            <span>bridge {h.bridge.mode} · up {fmtDuration(h.bridge.uptime_s)}</span>
            <span>clients {h.bridge.clients} (+{h.bridge.map_clients} map)</span>
            <span>
              link rtt {client.linkStats.rttMs == null ? "—" : `${Math.round(client.linkStats.rttMs)} ms`} · rx{" "}
              {(client.linkStats.kbpsMain + client.linkStats.kbpsMap).toFixed(1)} kB/s
            </span>
            <span>superseded frames {h.bridge.dropped_frames}</span>
            <span>tf throttled {h.bridge.tf_dropped}</span>
            <span>source: {h.source.message}</span>
          </div>
        ) : null}
      </LiveGate>
    </Panel>
  );
}

export function EventLog() {
  const { client } = useTelemetry();
  const [filter, setFilter] = useState<"all" | "warn">("all");
  const evs = [...client.events].reverse().filter((e) => filter === "all" || e.level !== "info");
  return (
    <Panel
      title="Event log"
      right={
        <span className="flex gap-1">
          {(["all", "warn"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`rounded px-1.5 text-2xs ${filter === f ? "bg-panel2 text-ink" : "text-faint hover:text-ink"}`}>
              {f === "all" ? "all" : "problems"}
            </button>
          ))}
        </span>
      }
      bodyClass="overflow-auto scroll-thin"
      className="h-full"
    >
      <ul className="divide-y divide-line/50 text-2xs">
        {evs.length === 0 ? <li className="px-3 py-2 text-faint">No events yet</li> : null}
        {evs.map((e, i) => (
          <li key={`${e.t}-${i}`} className="flex gap-2 px-3 py-1">
            <span className="num shrink-0 text-faint">{new Date(e.t).toLocaleTimeString()}</span>
            <span className={`shrink-0 ${e.level === "error" ? "text-crit" : e.level === "warn" ? "text-warn" : "text-muted"}`}>
              {e.level === "error" ? "■" : e.level === "warn" ? "▲" : "●"}
            </span>
            <span className="text-ink">{e.message}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

const WINDOWS = [
  { label: "1m", ms: 60_000 },
  { label: "5m", ms: 300_000 },
  { label: "10m", ms: 600_000 },
];

export function LiveCharts() {
  const { client } = useTelemetry();
  const [win, setWin] = useState(WINDOWS[0]);
  const now = Date.now();
  const domain: [number, number] = [now - win.ms, now];
  const fmtX = (x: number) => {
    const d = Math.round((x - now) / 1000);
    return d === 0 ? "now" : `${d}s`;
  };
  const hide = !!client.identityProblem;
  const vel = hide ? [] : client.vel;

  const linear: Series[] = [
    { key: "m", label: "Measured", color: "s1", points: vel.map((p) => ({ x: p.t, y: p.linear })) },
    { key: "c", label: "Commanded", color: "s2", dashed: true, points: vel.map((p) => ({ x: p.t, y: p.cmdLinear })) },
  ];
  const angular: Series[] = [
    { key: "m", label: "Measured", color: "s1", points: vel.map((p) => ({ x: p.t, y: p.angular })) },
    { key: "c", label: "Commanded", color: "s2", dashed: true, points: vel.map((p) => ({ x: p.t, y: p.cmdAngular })) },
  ];

  // Sensor rates as % of expected (common base), so different Hz scales share one axis.
  const roles = client.health?.roles ?? {};
  const pick = [
    { role: "scan", color: "s1" },
    { role: "odometry", color: "s2" },
    { role: "imu", color: "s3" },
  ];
  const expected: Record<string, number | null> = {};
  for (const t of client.health?.topics ?? []) expected[t.name] = t.expected_hz ?? t.min_hz;
  const rateSeries: Series[] = pick
    .map(({ role, color }) => {
      const name = roles[role];
      if (!name || !expected[name]) return null;
      const ref = expected[name]!;
      return {
        key: name,
        label: name,
        color,
        points: (hide ? [] : client.rates).map((r) => ({ x: r.t, y: r.rates[name] == null ? null : (100 * r.rates[name]!) / ref })),
      } as Series;
    })
    .filter((s): s is Series => s !== null);

  const cov = hide ? [] : client.coverage;
  const useCov = cov.some((c) => c.coveragePct != null);
  const covSeries: Series[] = [
    {
      key: "a",
      label: useCov ? "Coverage" : "Known area",
      color: "s3",
      points: cov.map((c) => ({ x: c.t, y: useCov ? c.coveragePct : c.knownArea })),
    },
  ];

  const lat = hide ? [] : client.latency;
  const latencySeries: Series[] = [
    { key: "rtt", label: "Round trip", color: "s1", points: lat.map((p) => ({ x: p.t, y: p.rtt })) },
    { key: "tr", label: "Telemetry one-way", color: "s2", dashed: true, points: lat.map((p) => ({ x: p.t, y: p.transit })) },
  ];

  return (
    <Panel
      title="Live trends"
      right={
        <span className="flex gap-1">
          {WINDOWS.map((w) => (
            <button key={w.label} onClick={() => setWin(w)} className={`rounded px-1.5 text-2xs ${win === w ? "bg-panel2 text-ink" : "text-faint hover:text-ink"}`}>
              {w.label}
            </button>
          ))}
        </span>
      }
    >
      <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 xl:grid-cols-5">
        <ChartBox title="Linear velocity">
          <TimeSeriesChart series={linear} domain={domain} unit="m/s" xFormat={fmtX} minSpan={0.4} />
        </ChartBox>
        <ChartBox title="Angular velocity">
          <TimeSeriesChart series={angular} domain={domain} unit="rad/s" xFormat={fmtX} minSpan={0.4} />
        </ChartBox>
        <ChartBox title="Sensor rate, % of expected">
          <TimeSeriesChart series={rateSeries} domain={domain} unit="%" digits={0} xFormat={fmtX} refLine={{ y: 100, label: "expected" }} minSpan={20} emptyText="no rate data" />
        </ChartBox>
        <ChartBox title="Link delay (Wi-Fi + tunnel)">
          <TimeSeriesChart series={latencySeries} domain={domain} unit="ms" digits={0} xFormat={fmtX} minSpan={50} emptyText="no probes yet" />
        </ChartBox>
        <ChartBox title={useCov ? "Map coverage" : "Explored (known) area"}>
          <TimeSeriesChart series={covSeries} domain={domain} unit={useCov ? "%" : "m²"} digits={1} xFormat={fmtX} minSpan={1} emptyText="no map yet" />
        </ChartBox>
      </div>
    </Panel>
  );
}

function ChartBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-2xs font-medium text-muted">{title}</div>
      {children}
    </div>
  );
}

/** Horizontal bar with a text value: one series, so no legend; colour is identity, not status. */
function Bar({ label, value, max, text, sub }: { label: string; value: number; max: number; text: string; sub?: string }) {
  const pct = max > 0 ? Math.min(100, (100 * value) / max) : 0;
  return (
    <div className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-2 py-0.5 text-2xs">
      <span className="truncate text-muted" title={label}>{label}</span>
      <div className="h-2 rounded-sm bg-panel2">
        <div className="h-2 rounded-sm bg-s1" style={{ width: `${Math.max(pct, value > 0 ? 1.5 : 0)}%` }} />
      </div>
      <span className="num min-w-[7rem] whitespace-nowrap text-right text-ink">
        {text}
        {sub ? <span className="text-faint"> · {sub}</span> : null}
      </span>
    </div>
  );
}

export function ComputePanel() {
  const { client } = useTelemetry();
  const c = client.identityProblem ? null : client.health?.compute ?? null;
  const live = client.link === "live";
  const tLevel: Level = client.tempLevel === "crit" ? "crit" : client.tempLevel === "warn" ? "warn" : client.tempLevel === "ok" ? "good" : "idle";
  const cpuLevel: Level = c?.cpu_total_pct == null ? "idle" : c.cpu_total_pct >= 90 ? "crit" : c.cpu_total_pct >= 75 ? "warn" : "good";
  const maxComp = Math.max(100, ...(c?.components ?? []).map((x) => x.cpu_pct));
  return (
    <Panel
      title="NUC compute"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={c?.simulated ? <span className="text-2xs text-warn">simulated</span> : <span className="text-2xs text-faint">from /proc · every 2 s</span>}
    >
      <LiveGate live={live}>
        {!c ? (
          <div className="px-3 py-2 text-2xs text-faint">No compute data yet</div>
        ) : c.error ? (
          <div className="px-3 py-2 text-2xs text-warn">▲ {c.error}</div>
        ) : (
          <>
            <div className="grid grid-cols-4 gap-x-3 gap-y-2 px-3 py-2">
              <Metric label="CPU (all cores)" value={fmt(c.cpu_total_pct, 0)} unit="%" level={cpuLevel} sub={`${c.cores} cores · load ${fmt(c.load1, 2)}`} />
              <Metric
                label="Memory"
                value={c.mem_used_mb == null ? "—" : (c.mem_used_mb / 1024).toFixed(1)}
                unit={c.mem_total_mb ? `/ ${(c.mem_total_mb / 1024).toFixed(1)} GB` : "GB"}
              />
              <Metric
                label="Hottest sensor"
                value={fmt(c.temp_max_c, 0)}
                unit="°C"
                level={tLevel}
                sub={client.throttlingNow ? `throttling · ${c.cpu_mhz}/${c.cpu_max_mhz} MHz` : client.tempPeak ? `peak ${client.tempPeak.c} °C` : c.temps[0]?.label ?? "no sensors"}
              />
              <Metric label="Disk free" value={fmt(c.disk_free_gb, 0)} unit="GB" level={c.disk_free_gb != null && c.disk_free_gb < 5 ? "warn" : undefined} />
            </div>
            {c.temps.length > 1 ? (
              <div className="flex flex-wrap gap-x-4 gap-y-0.5 border-t border-line px-3 py-1.5 text-2xs">
                {c.temps.map((t) => (
                  <span key={t.label} className="num">
                    <span className="text-faint">{t.label}</span>{" "}
                    <span className={t.c >= (c.temp_crit_c ?? 90) ? "text-crit" : t.c >= (c.temp_warn_c ?? 80) ? "text-warn" : "text-ink"}>
                      {t.c} °C
                    </span>
                  </span>
                ))}
                {c.throttle_count != null ? <span className="num text-faint">throttle events {c.throttle_count}</span> : null}
              </div>
            ) : null}
            <div className="border-t border-line px-3 py-2">
              <div className="mb-1 flex justify-between text-2xs text-faint">
                <span>CPU by component (% of one core, like top)</span>
                <span>memory</span>
              </div>
              {c.components.map((x) => (
                <Bar key={x.name} label={x.name} value={x.cpu_pct} max={maxComp} text={`${x.cpu_pct.toFixed(1)} %`} sub={`${Math.round(x.rss_mb)} MB`} />
              ))}
              {c.components.length === 0 ? <div className="text-2xs text-faint">no busy processes</div> : null}
            </div>
            <div className="border-t border-line px-3 py-2 text-2xs">
              <div className="mb-1 text-faint">Busiest processes</div>
              {c.top.slice(0, 6).map((p, i) => (
                <div key={`${p.name}-${i}`} className="flex gap-2 leading-5">
                  <span className="num w-32 truncate text-ink">{p.name}</span>
                  <span className="flex-1 truncate text-muted">{p.component}</span>
                  <span className="num w-14 text-right text-ink">{p.cpu_pct.toFixed(1)} %</span>
                  <span className="num w-16 text-right text-muted">{Math.round(p.rss_mb)} MB</span>
                </div>
              ))}
            </div>
          </>
        )}
      </LiveGate>
    </Panel>
  );
}

export function DataRatePanel() {
  const { client } = useTelemetry();
  const h = client.identityProblem ? null : client.health;
  const live = client.link === "live";
  const measured = (h?.topics ?? []).filter((t) => t.bytes_per_s != null && t.status !== "missing")
    .sort((a, b) => (b.bytes_per_s ?? 0) - (a.bytes_per_s ?? 0));
  const total = measured.reduce((a, t) => a + (t.bytes_per_s ?? 0), 0);
  const max = Math.max(1, ...measured.map((t) => t.bytes_per_s ?? 0));
  const ls = client.linkStats;
  return (
    <Panel
      title="Data per topic"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={<span className="num text-2xs text-faint">monitored total {fmtBytesRate(total)}</span>}
    >
      <LiveGate live={live}>
        <div className="px-3 py-2">
          {measured.map((t) => (
            <Bar key={t.name} label={t.label ? `${t.name}` : t.name} value={t.bytes_per_s ?? 0} max={max}
              text={fmtBytesRate(t.bytes_per_s)} sub={t.rate_hz != null ? `${t.rate_hz.toFixed(0)} Hz` : undefined} />
          ))}
          {measured.length === 0 ? <div className="text-2xs text-faint">No measurements yet</div> : null}
        </div>
        <div className="space-y-1 border-t border-line px-3 py-2 text-2xs text-faint">
          <div>
            Measured on the NUC from the size of each message the monitor already receives.
            Camera images and LiDAR point clouds are <span className="text-muted">not received on purpose</span> (heavy);
            their programs&apos; CPU shows in NUC compute. Measure their data rate once with{" "}
            <span className="num text-muted">discover-remote.sh 8 --heavy</span>.
          </div>
          <div className="num">
            Wi-Fi to this laptop: {ls.kbpsMain.toFixed(1)} kB/s telemetry + {ls.kbpsMap.toFixed(1)} kB/s map
          </div>
        </div>
      </LiveGate>
    </Panel>
  );
}

const TEMP_WINDOWS = [
  { label: "1m", ms: 60_000 },
  { label: "5m", ms: 300_000 },
  { label: "15m", ms: 900_000 },
  { label: "30m", ms: 1_800_000 },
];
// Fixed categorical slots: NUC first, robot sources after it (never status colours).
const TEMP_SLOTS = ["s2", "s1", "s3", "s5", "s7"];

function levelOf(l: string): Level {
  return l === "crit" ? "crit" : l === "warn" ? "warn" : l === "ok" ? "good" : "idle";
}

function TempTile({ title, c, level, sub, slot }: { title: string; c: number | null; level: Level; sub: string; slot: string }) {
  return (
    <div className="rounded border border-line bg-panel2 px-2.5 py-1.5">
      <div className="flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: `rgb(var(--${slot}))` }} />
        <span className="label truncate">{title}</span>
      </div>
      <div className="mt-0.5 flex items-baseline justify-between gap-2">
        <span className="num text-xl leading-tight text-ink">
          {c == null ? "—" : c.toFixed(1)}
          <span className="ml-0.5 text-2xs text-muted">°C</span>
        </span>
        <StatusPill level={level}>{level === "crit" ? "overheating" : level === "warn" ? "hot" : level === "good" ? "ok" : "n/a"}</StatusPill>
      </div>
      <div className="truncate text-2xs text-faint">{sub}</div>
    </div>
  );
}

/** NUC and robot temperatures over time, with thresholds. */
export function TemperaturePanel() {
  const { client } = useTelemetry();
  const [win, setWin] = useState(TEMP_WINDOWS[1]);
  const live = client.link === "live" && !client.identityProblem;
  const c = client.identityProblem ? null : client.health?.compute ?? null;
  const robot = client.robotTemps;
  const now = Date.now();
  const domain: [number, number] = [now - win.ms, now];
  const pts = client.identityProblem ? [] : client.temps;
  const fmtX = (x: number) => {
    const d = Math.round((x - now) / 1000);
    if (d === 0) return "now";
    return Math.abs(d) >= 120 ? `${Math.round(d / 60)}m` : `${d}s`;
  };
  const series: Series[] = [];
  if (c && c.temp_max_c != null) {
    series.push({ key: "nuc", label: "NUC (hottest sensor)", color: TEMP_SLOTS[0], points: pts.map((p) => ({ x: p.t, y: p.max })) });
  }
  robot.forEach((r, i) => {
    series.push({ key: r.name, label: r.label, color: TEMP_SLOTS[(i + 1) % TEMP_SLOTS.length], points: pts.map((p) => ({ x: p.t, y: p.robot[r.label] ?? null })) });
  });
  const peers = client.identityProblem ? [] : client.health?.peers ?? [];
  peers.forEach((pe, i) => {
    series.push({ key: `peer-${pe.name}`, label: pe.name, color: TEMP_SLOTS[(robot.length + i + 1) % TEMP_SLOTS.length], points: pts.map((p) => ({ x: p.t, y: p.robot[pe.name] ?? null })) });
  });
  const warnRef = c?.temp_warn_c ?? robot.find((r) => r.warn != null)?.warn ?? 80;
  return (
    <Panel
      title="Temperatures"
      className="h-full"
      right={
        <span className="flex items-center gap-2">
          {c?.simulated || robot.some((r) => r.label.includes("(sim)")) ? <span className="text-2xs text-warn">simulated</span> : null}
          {TEMP_WINDOWS.map((w) => (
            <button key={w.label} onClick={() => setWin(w)} className={`rounded px-1.5 text-2xs ${win === w ? "bg-panel2 text-ink" : "text-faint hover:text-ink"}`}>
              {w.label}
            </button>
          ))}
        </span>
      }
    >
      <LiveGate live={live}>
        <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-[15rem_1fr]">
          <div className="flex flex-col gap-2">
            <TempTile
              title="NUC (hottest sensor)"
              c={c?.temp_max_c ?? null}
              level={levelOf(client.tempLevel)}
              slot={TEMP_SLOTS[0]}
              sub={
                c?.temp_max_c == null
                  ? "no NUC sensors found"
                  : client.throttlingNow
                    ? `throttling · ${c.cpu_mhz}/${c.cpu_max_mhz} MHz`
                    : `${c.temps[0]?.label ?? ""}${client.tempPeak ? ` · peak ${client.tempPeak.c} °C` : ""}`
              }
            />
            {robot.map((r, i) => (
              <TempTile
                key={r.name}
                title={r.label}
                c={r.c}
                level={r.status === "missing" ? "idle" : levelOf(client.robotTempLevel(r.name))}
                slot={TEMP_SLOTS[(i + 1) % TEMP_SLOTS.length]}
                sub={r.status === "missing" ? `${r.name} not found` : `warn ${r.warn ?? "—"} · critical ${r.crit ?? "—"} °C`}
              />
            ))}
            {peers.map((pe, i) => (
              <TempTile
                key={`peer-${pe.name}`}
                title={pe.name}
                c={pe.online ? pe.stats?.temp_max_c ?? null : null}
                level={!pe.online ? "crit" : levelOf(client.peerTempLevel(pe.name))}
                slot={TEMP_SLOTS[(robot.length + i + 1) % TEMP_SLOTS.length]}
                sub={!pe.online ? "offline" : pe.stats ? `warn ${pe.temp_warn_c} · critical ${pe.temp_crit_c} °C` : "online · reporter not running"}
              />
            ))}
            {robot.length === 0 ? (
              <div className="rounded border border-dashed border-line px-2.5 py-2 text-2xs text-faint">
                Robot temperature: no source configured. The robot does not publish motor / body temperatures on
                domain 8 yet - add the topic to <span className="num text-muted">temperature_topics</span> in the bridge
                config when the team finds it.
              </div>
            ) : null}
          </div>
          <div className="min-w-0">
            <TimeSeriesChart
              series={series}
              domain={domain}
              height={210}
              unit="°C"
              digits={1}
              includeZero={false}
              minSpan={15}
              xFormat={fmtX}
              refLine={{ y: warnRef, label: "warn" }}
              emptyText="no temperature data yet"
            />
            <div className="mt-1 text-2xs text-faint">
              Dashed line: warning level ({warnRef} °C). NUC warn {c?.temp_warn_c ?? 80} °C / critical {c?.temp_crit_c ?? 90} °C.
              Hover the graph for exact values.
            </div>
          </div>
        </div>
      </LiveGate>
    </Panel>
  );
}

const THROTTLE_LABELS: [string, string][] = [
  ["under_voltage", "Under-voltage"],
  ["throttled", "CPU throttled"],
  ["freq_capped", "Clock capped"],
  ["soft_temp_limit", "Soft temp limit"],
];

/** Helper computers on the robot (Raspberry Pi): reachability, power, temperature, resources. */
export function PeerPanel() {
  const { client } = useTelemetry();
  const peers = client.identityProblem ? [] : client.health?.peers ?? [];
  const live = client.link === "live";
  if (!peers.length) {
    return (
      <Panel title="Raspberry Pi" className="h-full">
        <div className="px-3 py-2 text-2xs text-faint">
          No helper computer configured. Add it under <span className="num text-muted">peers</span> in
          <span className="num text-muted"> bridge/config/local.yaml</span> on the NUC (see the start-up manual).
        </div>
      </Panel>
    );
  }
  return (
    <Panel title={peers.length === 1 ? peers[0].name : "Helper computers"} className="h-full" bodyClass="overflow-auto scroll-thin">
      <LiveGate live={live}>
        {peers.map((pe) => {
          const st = pe.stats;
          const th = st?.throttle ?? null;
          const tl = client.peerTempLevel(pe.name);
          return (
            <div key={pe.name} className="border-b border-line/60 px-3 py-2 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill level={pe.online ? "good" : "crit"} className={!pe.online ? "lost-pulse" : ""}>
                  {pe.online ? `online · ${pe.rtt_ms} ms` : "offline"}
                </StatusPill>
                {pe.identity_ok === false ? <StatusPill level="crit">wrong device: {st?.hostname}</StatusPill> : null}
                {pe.identity_ok === true ? <span className="num text-2xs text-good">● {st?.hostname} verified</span> : null}
                {!pe.online && pe.last_seen_age_s != null ? (
                  <span className="text-2xs text-faint">last seen {fmtAge(pe.last_seen_age_s)} ago</span>
                ) : null}
              </div>
              {st ? (
                <>
                  <div className="mt-1 truncate text-2xs text-faint">{st.model ?? "unknown model"} · up {fmtDuration(st.uptime_s)}</div>
                  <div className="mt-2 grid grid-cols-4 gap-x-3 gap-y-2">
                    <Metric label="Temperature" value={fmt(st.temp_max_c, 1)} unit="°C"
                      level={tl === "crit" ? "crit" : tl === "warn" ? "warn" : tl === "ok" ? "good" : undefined} />
                    <Metric label="CPU" value={fmt(st.cpu_total_pct, 0)} unit="%"
                      sub={st.cpu_mhz != null ? `${st.cpu_mhz}/${st.cpu_max_mhz} MHz` : undefined} />
                    <Metric label="Memory" value={st.mem_used_mb == null ? "—" : (st.mem_used_mb / 1024).toFixed(1)}
                      unit={st.mem_total_mb ? `/ ${(st.mem_total_mb / 1024).toFixed(1)} GB` : "GB"} />
                    <Metric label="SD free" value={fmt(st.disk_free_gb, 1)} unit="GB"
                      level={st.disk_free_gb != null && st.disk_free_gb < 2 ? "warn" : undefined} />
                  </div>
                  <div className="mt-2 text-2xs">
                    <div className="mb-1 text-faint">
                      Power &amp; throttling <span className="num">{st.throttled_raw ?? ""}</span>
                    </div>
                    {th ? (
                      <div className="grid grid-cols-[auto_auto_auto] gap-x-3 gap-y-0.5">
                        <span />
                        <span className="text-faint">now</span>
                        <span className="text-faint">since boot</span>
                        {THROTTLE_LABELS.map(([k, label]) => (
                          <Fragment key={k}>
                            <span className="text-muted">{label}</span>
                            <span>{th[`${k}_now`] ? <StatusPill level="crit">yes</StatusPill> : <span className="text-good">● no</span>}</span>
                            <span>{th[`${k}_occurred`] ? <span className="text-warn">▲ yes</span> : <span className="text-faint">no</span>}</span>
                          </Fragment>
                        ))}
                      </div>
                    ) : (
                      <span className="text-faint">not available on this device</span>
                    )}
                    {th?.under_voltage_now || th?.under_voltage_occurred ? (
                      <div className="mt-1 text-warn">
                        ▲ Under-voltage means the Pi&apos;s power supply is too weak (e.g. powered from the NUC&apos;s USB-C).
                        Use a proper 5 V / 3 A (Pi 4) or 5 A (Pi 5) supply.
                      </div>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="mt-1 text-2xs text-faint">
                  {pe.online
                    ? pe.stats_configured
                      ? `Health reporter not answering (${pe.stats_error ?? "no data"}). Start it on the Pi - see the start-up manual.`
                      : "Reachability only. Start the read-only reporter on the Pi for power, temperature and SD space."
                    : pe.error ?? "not reachable"}
                </div>
              )}
            </div>
          );
        })}
      </LiveGate>
    </Panel>
  );
}

const LOG_LEVELS: Record<number, { label: string; cls: string }> = {
  10: { label: "DEBUG", cls: "text-faint" },
  20: { label: "INFO", cls: "text-muted" },
  30: { label: "WARN", cls: "text-warn" },
  40: { label: "ERROR", cls: "text-crit" },
  50: { label: "FATAL", cls: "text-crit" },
};

/** Live robot log (/rosout): warnings and errors from all ROS programs, like a terminal. */
export function RobotLogPanel() {
  const { client } = useTelemetry();
  const [minLevel, setMinLevel] = useState(20);
  const [q, setQ] = useState("");
  const live = client.link === "live";
  const rows = [...client.robotLogs].reverse()
    .filter((l) => l.level >= minLevel)
    .filter((l) => !q || `${l.node} ${l.msg}`.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 200);
  const hasRosout = !!client.health?.roles?.rosout;
  return (
    <Panel
      title="Robot log"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={
        <span className="flex items-center gap-1">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter…"
            className="w-24 rounded border border-line bg-panel2 px-1.5 text-2xs text-ink" />
          {[[20, "info+"], [30, "warn+"], [40, "errors"]].map(([lv, label]) => (
            <button key={lv as number} onClick={() => setMinLevel(lv as number)}
              className={`rounded px-1.5 text-2xs ${minLevel === lv ? "bg-panel2 text-ink" : "text-faint hover:text-ink"}`}>
              {label}
            </button>
          ))}
        </span>
      }
    >
      <LiveGate live={live}>
        {!hasRosout ? (
          <div className="px-3 py-2 text-2xs text-faint">No /rosout topic on this domain (the robot log appears when ROS programs publish it).</div>
        ) : rows.length === 0 ? (
          <div className="px-3 py-2 text-2xs text-faint">No log lines yet at this level.</div>
        ) : null}
        <ul className="font-mono text-2xs">
          {rows.map((l) => {
            const lv = LOG_LEVELS[l.level] ?? { label: String(l.level), cls: "text-muted" };
            return (
              <li key={`${l.id}@${l.t}`} className="flex gap-2 border-b border-line/40 px-3 py-0.5">
                <span className="shrink-0 text-faint">{new Date(l.t * 1000).toLocaleTimeString()}</span>
                <span className={`w-11 shrink-0 ${lv.cls}`}>{lv.label}</span>
                <span className="w-36 shrink-0 truncate text-muted" title={l.node}>{l.node}</span>
                <span className={`min-w-0 break-words ${l.level >= 30 ? lv.cls : "text-ink"}`}>{l.msg}</span>
              </li>
            );
          })}
        </ul>
        {client.health?.logs_dropped ? (
          <div className="px-3 py-1 text-2xs text-faint">{client.health.logs_dropped} lines skipped during log storms (rate limit)</div>
        ) : null}
      </LiveGate>
    </Panel>
  );
}

function legOf(joint: string): string {
  const m = joint.match(/^([A-Za-z]{2})[_-]/);
  return m ? m[1].toUpperCase() : "";
}

/** Robot body: posture (tilt), obstacle distance, command vs actual speed, leg effort. */
export function BodyPanel() {
  const { client } = useTelemetry();
  const t = client.identityProblem ? null : client.telemetry;
  const h = client.identityProblem ? null : client.health;
  const live = client.link === "live";
  const at = t?.attitude ?? null;
  const tiltLv: Level = !at?.valid ? "idle" : client.tiltLevel === "crit" ? "crit" : client.tiltLevel === "warn" ? "warn" : "good";
  const ranges = (h?.topics ?? []).filter((x) => x.role === "range");
  const cmd = t?.cmd_vel;
  const cmdFresh = cmd?.age_s != null && cmd.age_s < 1;
  const cmdActive = cmdFresh && (Math.abs(cmd!.linear ?? 0) > 0.05 || Math.abs(cmd!.angular ?? 0) > 0.1);
  const speed = t?.velocity?.valid ? t.velocity.speed : null;
  const cmdState: [Level, string] = !cmdFresh
    ? ["idle", "no command data"]
    : !cmdActive
      ? ["idle", "no motion commanded"]
      : t?.exploration.stalled
        ? ["crit", "commanded but NOT moving"]
        : (speed ?? 0) > 0.03 || Math.abs(t?.velocity?.angular ?? 0) > 0.1
          ? ["good", "moving as commanded"]
          : ["warn", "commanded, not moving yet"];
  const j = t?.joints;
  const effMax = Math.max(1, ...(j?.effort ?? []).map((e) => Math.abs(e ?? 0)));
  return (
    <Panel title="Robot body" className="h-full" bodyClass="overflow-auto scroll-thin">
      <LiveGate live={live}>
        {/* posture */}
        <div className="px-3 py-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="label">Posture (IMU)</span>
            <StatusPill level={tiltLv}>{!at ? "no IMU data" : tiltLv === "crit" ? "tipping risk" : tiltLv === "warn" ? "tilted" : tiltLv === "good" ? "upright" : "stale"}</StatusPill>
          </div>
          <div className="grid grid-cols-4 gap-x-3">
            <Metric label="Tilt" value={fmt(at?.tilt_deg, 1)} unit="°" level={tiltLv === "good" ? undefined : tiltLv === "idle" ? undefined : tiltLv} sub={at ? `warn ${at.tilt_warn_deg}° · crit ${at.tilt_crit_deg}°` : undefined} />
            <Metric label="Roll" value={fmt(at?.roll_deg, 1)} unit="°" />
            <Metric label="Pitch" value={fmt(at?.pitch_deg, 1)} unit="°" />
            <Metric label="Accel" value={fmt(at?.acc_g, 2)} unit="g" sub={client.maxTilt ? `max tilt ${client.maxTilt.toFixed(1)}°` : undefined} />
          </div>
          {at ? (
            <div className="relative mt-1.5 h-1.5 rounded-sm bg-panel2" title="tilt from upright, 0-45°">
              <div className={`absolute inset-y-0 left-0 rounded-sm ${tiltLv === "crit" ? "bg-crit" : tiltLv === "warn" ? "bg-warn" : "bg-good"}`}
                style={{ width: `${Math.min(100, ((at.tilt_deg ?? 0) / 45) * 100)}%` }} />
              <div className="absolute inset-y-[-2px] w-px bg-muted" style={{ left: `${(at.tilt_warn_deg / 45) * 100}%` }} />
              <div className="absolute inset-y-[-2px] w-px bg-muted" style={{ left: `${(at.tilt_crit_deg / 45) * 100}%` }} />
            </div>
          ) : null}
        </div>

        {/* obstacle distance */}
        <div className="border-t border-line px-3 py-2">
          <div className="label mb-1">Obstacle distance</div>
          {ranges.length === 0 ? <div className="text-2xs text-faint">No distance sensor configured</div> : null}
          {ranges.map((r) => {
            const lv = client.rangeLevels.get(r.name) ?? "unknown";
            const level: Level = r.status === "missing" ? "idle" : lv === "crit" ? "crit" : lv === "warn" ? "warn" : lv === "ok" ? "good" : "idle";
            const max = r.range_max_m ?? 5;
            const clear = r.range_m != null && r.range_m >= max - 0.05;
            return (
              <div key={r.name} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-2xs">
                <span className="truncate text-muted">{r.label ?? r.name}</span>
                <div className="relative h-2 rounded-sm bg-panel2">
                  <div className={`absolute inset-y-0 left-0 rounded-sm ${level === "crit" ? "bg-crit" : level === "warn" ? "bg-warn" : "bg-s3"}`}
                    style={{ width: `${Math.min(100, ((r.range_m ?? 0) / max) * 100)}%` }} />
                </div>
                <span className="flex items-center gap-1.5">
                  <span className="num text-ink">{r.range_m == null ? "—" : clear ? `clear (≥${max} m)` : `${r.range_m.toFixed(2)} m`}</span>
                  <StatusPill level={level}>{level === "crit" ? "very close" : level === "warn" ? "close" : level === "good" ? "ok" : "n/a"}</StatusPill>
                </span>
              </div>
            );
          })}
        </div>

        {/* command vs actual */}
        <div className="border-t border-line px-3 py-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="label">Command vs actual</span>
            <StatusPill level={cmdState[0]}>{cmdState[1]}</StatusPill>
          </div>
          <div className="grid grid-cols-4 gap-x-3">
            <Metric label="Cmd linear" value={cmdFresh ? fmt(cmd?.linear, 2) : "—"} unit="m/s" />
            <Metric label="Actual" value={fmt(speed, 2)} unit="m/s" />
            <Metric label="Cmd turn" value={cmdFresh ? fmt(cmd?.angular, 2) : "—"} unit="rad/s" />
            <Metric label="Actual" value={t?.velocity?.valid ? fmt(t.velocity.angular, 2) : "—"} unit="rad/s" />
          </div>
          <div className="mt-0.5 text-2xs text-faint">source: {h?.roles?.cmd_vel ?? "none"}</div>
        </div>

        {/* leg effort */}
        <div className="border-t border-line px-3 py-2">
          <div className="label mb-1">Leg effort (joint load)</div>
          {!j || j.names.length === 0 ? (
            <div className="text-2xs text-faint">No joint data</div>
          ) : j.effort.length === 0 ? (
            <div className="text-2xs text-faint">The robot does not publish joint effort ({j.names.length} joints, positions only)</div>
          ) : (
            <div className="grid grid-flow-col gap-x-4" style={{ gridTemplateRows: `repeat(${Math.ceil(j.names.length / 2)}, auto)` }}>
              {j.names.map((n, i) => (
                <div key={n} className="grid grid-cols-[4.5rem_1fr_3rem] items-center gap-1.5 text-2xs leading-4">
                  <span className={`truncate ${legOf(n) === "FL" || legOf(n) === "HL" ? "text-muted" : "text-faint"}`}>{n}</span>
                  <div className="h-1.5 rounded-sm bg-panel2">
                    <div className="h-1.5 rounded-sm bg-s1" style={{ width: `${(Math.abs(j.effort[i] ?? 0) / effMax) * 100}%` }} />
                  </div>
                  <span className="num text-right text-ink">{fmt(j.effort[i], 1)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </LiveGate>
    </Panel>
  );
}

/** Compact "is the Pi live, and what is it sending / receiving" view. */
export function PiLinkPanel() {
  const { client } = useTelemetry();
  const peers = client.identityProblem ? [] : client.health?.peers ?? [];
  const pe = peers[0];
  const live = client.link === "live";
  if (!pe) {
    return (
      <Panel title="Pi link" className="h-full">
        <div className="px-3 py-2 text-2xs text-faint">No Raspberry Pi configured (see start-up manual §1b).</div>
      </Panel>
    );
  }
  const net = pe.online ? pe.stats?.net ?? null : null;
  const rx = net ? net.interfaces.reduce((a, i) => a + i.rx_Bps, 0) : null;
  const tx = net ? net.interfaces.reduce((a, i) => a + i.tx_Bps, 0) : null;
  const rxp = net ? net.interfaces.reduce((a, i) => a + i.rx_pps, 0) : null;
  const txp = net ? net.interfaces.reduce((a, i) => a + i.tx_pps, 0) : null;
  const hist = client.peerTraffic.get(pe.name) ?? [];
  const now = Date.now();
  const conns = (net?.connections ?? []).filter((c) => !c.loopback);
  const talking = conns.filter((c) => c.state !== "LISTEN");
  const listening = conns.filter((c) => c.state === "LISTEN");
  return (
    <Panel
      title={`${pe.name.replace(" (sim)", "")} link`}
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={pe.name.includes("(sim)") ? <span className="text-2xs text-warn">simulated</span> : undefined}
    >
      <LiveGate live={live}>
        <div className="flex items-center gap-3 px-3 pt-2">
          <span className={`inline-flex h-3 w-3 rounded-full ${pe.online ? "bg-good" : "bg-crit lost-pulse"}`} aria-hidden />
          <span className={`text-lg font-bold tracking-[0.15em] ${pe.online ? "text-good" : "text-crit"}`}>{pe.online ? "LIVE" : "OFFLINE"}</span>
          <span className="num text-2xs text-muted">
            {pe.online ? `${pe.rtt_ms} ms` : pe.last_seen_age_s != null ? `last seen ${fmtAge(pe.last_seen_age_s)} ago` : "never seen"}
          </span>
        </div>
        {net ? (
          <>
            <div className="grid grid-cols-2 gap-x-3 px-3 pt-2">
              <Metric label="Receiving" value={fmtBytesRate(rx)} sub={`${fmt(rxp, 0)} packets/s`} />
              <Metric label="Sending" value={fmtBytesRate(tx)} sub={`${fmt(txp, 0)} packets/s`} />
            </div>
            <div className="px-3 pt-1">
              <TimeSeriesChart
                height={90}
                domain={[now - 120_000, now]}
                unit="kB/s"
                digits={1}
                minSpan={1}
                xFormat={(x) => { const d = Math.round((x - now) / 1000); return d === 0 ? "now" : `${d}s`; }}
                series={[
                  { key: "rx", label: "Receiving", color: "s1", points: hist.map((h) => ({ x: h.t, y: h.rx })) },
                  { key: "tx", label: "Sending", color: "s2", points: hist.map((h) => ({ x: h.t, y: h.tx })) },
                ]}
              />
            </div>
            <div className="px-3 py-2 text-2xs">
              <div className="mb-0.5 text-faint">Talking to ({talking.length})</div>
              {talking.slice(0, 8).map((c, i) => (
                <div key={i} className="flex gap-2 leading-5">
                  <span className="num w-8 uppercase text-faint">{c.proto}</span>
                  <span className="w-24 truncate text-muted">{c.process ?? "?"}</span>
                  <span className={`num truncate ${c.to_nuc ? "text-s3" : "text-ink"}`}>
                    :{c.local_port} → {c.to_nuc ? "NUC" : c.remote}:{c.remote_port}
                  </span>
                </div>
              ))}
              {talking.length === 0 ? <div className="text-faint">no open connections</div> : null}
              {listening.length ? (
                <div className="mt-1 text-faint">
                  Listening: {listening.map((c) => `${c.process ?? "?"} :${c.local_port}`).join(" · ")}
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="px-3 py-2 text-2xs text-faint">
            {pe.online
              ? "Online. Start the read-only reporter on the Pi to see what it sends and receives (start-up manual §1b)."
              : pe.error ?? "Not reachable."}
          </div>
        )}
      </LiveGate>
    </Panel>
  );
}

/** Detections older than this are shown as not live (the Pi publishes ~0.6 frames/s). */
const PI_DETECTIONS_STALE_S = 5;

export function PiDetectionsPanel() {
  const { client } = useTelemetry();
  const p = client.identityProblem ? null : client.health?.perception ?? null;
  const d = p?.latest ?? null;
  const live = client.link === "live" && d != null && d.age_s <= PI_DETECTIONS_STALE_S;
  return (
    <Panel
      title="Pi sees now"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={d ? <span className="num text-2xs text-faint">frame {d.frame ?? "—"} · {fmtAge(d.age_s)} ago</span> : undefined}
    >
      {!d ? (
        <div className="px-3 py-2 text-2xs text-faint">
          No Pi detections received. The bridge listens on the Pi perception topics (config: topics.pi_detections).
        </div>
      ) : (
        <LiveGate live={live}>
          <div className="space-y-2 px-3 py-2 text-xs">
            <div>
              <div className="label">Objects</div>
              <div className="flex flex-wrap gap-1 pt-0.5">
                {d.objects.length ? d.objects.map((o, i) => (
                  <span key={i} className="rounded border border-line bg-panel2 px-1.5 py-0.5">
                    {o.name} <span className="num text-faint">{fmt(o.confidence, 2)}</span>
                  </span>
                )) : <span className="text-faint">none</span>}
              </div>
            </div>
            <div>
              <div className="label">QR code</div>
              <div className="pt-0.5">{d.qr.length ? d.qr.map((q, i) => <div key={i} className="break-words">“{q}”</div>) : <span className="text-faint">none</span>}</div>
            </div>
            <div>
              <div className="label">Hazard signs</div>
              <div className="pt-0.5">
                {d.signs.length ? d.signs.map((sg) => sg ?? "unidentified triangle").join(" · ") : <span className="text-faint">none</span>}
              </div>
            </div>
            <div>
              <div className="label">Stairs / curtain</div>
              <div className="flex items-center gap-2 pt-0.5">
                <StatusPill level={d.stair.reason === "confirmed" ? "good" : d.stair.reason === "timestamp_mismatch" || d.stair.reason === "stale_camera" ? "warn" : "idle"}>
                  {d.stair.reason === "confirmed" ? d.stair.obstacle ?? "confirmed" : d.stair.reason ?? "unknown"}
                </StatusPill>
                {d.stair.distance_m != null ? <span className="num text-muted">{fmt(d.stair.distance_m, 2)} m</span> : null}
              </div>
            </div>
            <div className="text-2xs text-faint">{p?.frames ?? 0} frames · {p?.events ?? 0} scene events received{p && p.bad_messages ? ` · ${p.bad_messages} unreadable` : ""}</div>
          </div>
        </LiveGate>
      )}
    </Panel>
  );
}

function sceneLevel(r: SceneRequest): Level {
  if (r.status === "failed") return "crit";
  if (r.status === "pending") return "idle";
  return !r.room || r.room === "unknown" ? "warn" : "good";
}

export function SceneChecksPanel() {
  const { client } = useTelemetry();
  const reqs = client.identityProblem ? [] : client.health?.perception?.requests ?? [];
  const live = client.link === "live";
  const answered = reqs.filter((r) => r.status === "result");
  const named = answered.filter((r) => r.room && r.room !== "unknown").length;
  return (
    <Panel
      title="Claude scene checks"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={reqs.length ? <span className="num text-2xs text-faint">{named}/{answered.length} rooms named</span> : undefined}
    >
      {!reqs.length ? (
        <div className="px-3 py-2 text-2xs text-faint">No Claude scene checks since the bridge started. Pictures are only shown when the Pi already stored them.</div>
      ) : (
        <LiveGate live={live}>
          <div className="grid grid-cols-1 gap-2 p-2 sm:grid-cols-2">
            {reqs.map((r) => {
              const img = sceneImageUrl(client.bridgeUrl, r);
              return (
                <div key={`${r.request_id}-${r.capture_stamp_ns}`} className="rounded border border-line bg-panel2 p-1.5 text-2xs">
                  {img ? (
                    // eslint-disable-next-line @next/next/no-img-element -- bridge-relayed stored JPEG
                    <img src={img} alt={`What Claude saw for ${r.request_id}`} loading="lazy"
                      className="mb-1 aspect-[4/3] w-full rounded object-cover"
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                  ) : null}
                  <div className="flex items-center justify-between gap-1">
                    <span className="num font-semibold">{r.request_id}</span>
                    <StatusPill level={sceneLevel(r)}>{r.status === "result" ? (r.room ?? "no room") : r.status}</StatusPill>
                  </div>
                  <div className="truncate text-muted">
                    {r.trigger ? `${r.trigger.kind}: ${r.trigger.label}` : "—"}
                  </div>
                  <div className="num text-faint">
                    {r.latency_s != null ? `answered in ${fmt(r.latency_s, 1)} s · ` : ""}{fmtAge(r.age_s)} ago
                  </div>
                  {r.error ? <div className="break-words text-crit">{r.error}</div> : null}
                  {r.evidence.length ? <div className="break-words text-faint">{r.evidence.join(" · ")}</div> : null}
                </div>
              );
            })}
          </div>
        </LiveGate>
      )}
    </Panel>
  );
}

function outcomeLevel(r: MissionReport): Level {
  const o = reportOutcome(r);
  return o === "accepted" ? "good" : o === "dry run" ? "idle" : "crit";
}

export function MissionReportsPanel() {
  const { client } = useTelemetry();
  const m = client.identityProblem ? null : client.health?.missions ?? null;
  const latest = m ? latestPerTask(m.reports) : [];
  const total = m ? scoreTotal(m.reports) : null;
  return (
    <Panel
      title="Mission reports"
      className="h-full"
      bodyClass="overflow-auto scroll-thin"
      right={m ? <span className="num text-2xs text-faint">{m.run}</span> : undefined}
    >
      {!m ? (
        <div className="px-3 py-2 text-2xs text-faint">No mission log configured (config: pi_perception.reports_glob).</div>
      ) : !latest.length ? (
        <div className="px-3 py-2 text-2xs text-faint">Nothing reported in this run yet.</div>
      ) : (
        <LiveGate live={client.link === "live"}>
          {total && total.scored ? (
            <div className="px-3 pt-2">
              <Metric label="Server score (latest per task)" value={`${total.score} / ${total.max}`} sub={`${total.scored} task(s) scored by the server`} />
            </div>
          ) : null}
          <table className="mt-1 w-full text-2xs">
            <tbody>
              {latest.map((r) => (
                <tr key={r.task_id} className="border-t border-line align-top">
                  <td className="num px-3 py-1 font-semibold">{r.task_id}</td>
                  <td className="py-1">
                    <div className="break-words">
                      {r.task_type === "qr" ? `“${r.message}”` : [r.scene_type || "—", r.label || null, r.pos ? `[${r.pos.join(", ")}]` : "no pos"].filter(Boolean).join(" · ")}
                    </div>
                    {r.evaluation ? (
                      <div className="text-faint">
                        {Object.entries(r.evaluation).map(([k, ok]) => `${k} ${ok ? "✔" : "✘"}`).join("  ")}
                      </div>
                    ) : null}
                    {r.reason ? <div className="text-crit">{r.reason}</div> : null}
                  </td>
                  <td className="px-3 py-1 text-right">
                    <StatusPill level={outcomeLevel(r)}>{reportOutcome(r)}</StatusPill>
                    {r.score != null && r.max_score != null ? <div className="num pt-0.5 text-muted">{r.score}/{r.max_score}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </LiveGate>
      )}
    </Panel>
  );
}
