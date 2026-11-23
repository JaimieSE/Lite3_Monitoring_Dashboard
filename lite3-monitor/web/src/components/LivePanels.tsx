"use client";

import { useState } from "react";
import { useTelemetry } from "./TelemetryProvider";
import { Dot, Metric, Panel, StatusPill, topicLevel, type Level } from "./ui";
import { TimeSeriesChart, type Series } from "./TimeSeriesChart";
import { deg, fmt, fmtAge, fmtDuration } from "@/lib/format";

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
          <Metric label="Distance" value={fmt(ex?.distance_travelled_m, 1)} unit="m" />
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
      right={<StatusPill level={!tf ? "idle" : tf.ok ? "good" : "warn"}>{!tf ? "no tf" : tf.ok ? "tf ok" : "tf issue"}</StatusPill>}
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
                  <td className="num py-1 text-right text-muted">{fmtAge(t.age_s)}</td>
                  <td className={`num py-1 text-right ${t.publishers > 1 && t.note.includes("cross-robot") ? "text-warn" : "text-muted"}`}>{t.publishers}</td>
                  <td className="max-w-[260px] truncate px-3 py-1 text-muted" title={t.note}>{t.note}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {h && (h.missing_roles.length > 0 || h.nodes.missing_expected.length > 0) ? (
          <div className="space-y-0.5 px-3 py-2 text-2xs">
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
