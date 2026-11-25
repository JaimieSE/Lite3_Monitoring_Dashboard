"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Panel, StatusPill } from "@/components/ui";
import { TimeSeriesChart, type Series } from "@/components/TimeSeriesChart";
import { fmt, fmtDuration, fmtTime } from "@/lib/format";
import type { Session, SessionMeta } from "@/lib/historyTypes";

// Fixed categorical slots for compared runs, assigned by selection order.
const SLOTS = ["s1", "s2", "s3", "s4"];
const MAX_COMPARE = 4;

export default function HistoryPage() {
  const [list, setList] = useState<SessionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<Record<string, Session>>({});

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/history", { cache: "no-store" });
      setList(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load history");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    for (const id of selected) {
      if (loaded[id]) continue;
      void fetch(`/api/history/${id}`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((s: Session | null) => s && setLoaded((m) => ({ ...m, [id]: s })));
    }
  }, [selected, loaded]);

  const toggle = (id: string) =>
    setSelected((sel) => (sel.includes(id) ? sel.filter((x) => x !== id) : sel.length >= MAX_COMPARE ? sel : [...sel, id]));

  const remove = async (id: string) => {
    if (!confirm("Delete this session permanently from this Mac?")) return;
    await fetch(`/api/history/${id}`, { method: "DELETE" });
    setSelected((s) => s.filter((x) => x !== id));
    void refresh();
  };

  const sessions = selected.map((id) => loaded[id]).filter(Boolean) as Session[];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between px-1">
        <h1 className="text-sm font-semibold uppercase tracking-[0.18em] text-muted">Test history · recorded sessions</h1>
        <span className="text-2xs text-faint">Stored locally on this Mac. Select one run for details, up to {MAX_COMPARE} to compare.</span>
      </div>

      <Panel title={`Sessions (${list?.length ?? "…"})`} right={<button onClick={refresh} className="text-2xs text-faint hover:text-ink">refresh</button>}>
        {error ? <div className="px-3 py-2 text-2xs text-crit">{error}</div> : null}
        <div className="max-h-[340px] overflow-auto scroll-thin">
          <table className="w-full text-2xs">
            <thead className="sticky top-0 bg-panel text-left text-faint">
              <tr className="border-b border-line">
                <th className="w-8 px-3 py-1" />
                <th className="py-1 font-medium">Session</th>
                <th className="py-1 font-medium">Started</th>
                <th className="py-1 font-medium">Source</th>
                <th className="py-1 text-right font-medium">Duration</th>
                <th className="py-1 text-right font-medium">Distance</th>
                <th className="py-1 text-right font-medium">Explored</th>
                <th className="py-1 text-right font-medium">Max speed</th>
                <th className="py-1 text-right font-medium">Link losses</th>
                <th className="py-1 text-right font-medium">Stalls</th>
                <th className="py-1 text-right font-medium">Errors</th>
                <th className="px-3 py-1 text-right font-medium">Export</th>
              </tr>
            </thead>
            <tbody>
              {list?.length === 0 ? (
                <tr>
                  <td colSpan={12} className="px-3 py-3 text-faint">No sessions yet. Recording starts automatically on the Live page when telemetry arrives.</td>
                </tr>
              ) : null}
              {list?.map((s) => {
                const idx = selected.indexOf(s.id);
                return (
                  <tr key={s.id} className={`cursor-pointer border-b border-line/50 hover:bg-panel2 ${idx >= 0 ? "bg-panel2" : ""}`} onClick={() => toggle(s.id)}>
                    <td className="px-3 py-1">
                      <span
                        className="inline-block h-3 w-3 rounded-sm border border-line"
                        style={idx >= 0 ? { background: `rgb(var(--${SLOTS[idx]}))`, borderColor: "transparent" } : undefined}
                      />
                    </td>
                    <td className="py-1 text-ink">
                      {s.label}
                      {s.ended_at == null ? (
                        Date.now() - s.updated_at < 30_000 ? (
                          <span className="ml-2 text-crit">● recording</span>
                        ) : (
                          <span className="ml-2 text-faint" title="The tab closed before the session was stopped; data up to the last save is kept.">unfinished</span>
                        )
                      ) : null}
                    </td>
                    <td className="num py-1 text-muted">{fmtTime(s.started_at)}</td>
                    <td className="py-1">
                      <StatusPill level={s.mode === "sim" ? "warn" : "idle"}>{s.mode === "sim" ? "sim" : s.robot.hostname ?? "live"}</StatusPill>
                    </td>
                    <td className="num py-1 text-right">{fmtDuration(s.summary.duration_s)}</td>
                    <td className="num py-1 text-right">{fmt(s.summary.distance_m, 1)} m</td>
                    <td className="num py-1 text-right">
                      {s.summary.final_coverage_pct != null ? `${fmt(s.summary.final_coverage_pct, 1)} %` : `${fmt(s.summary.final_known_area_m2, 1)} m²`}
                    </td>
                    <td className="num py-1 text-right">{fmt(s.summary.max_speed, 2)}</td>
                    <td className={`num py-1 text-right ${s.summary.link_lost_count ? "text-warn" : ""}`}>{s.summary.link_lost_count}</td>
                    <td className={`num py-1 text-right ${s.summary.stall_events ? "text-warn" : ""}`}>{s.summary.stall_events}</td>
                    <td className={`num py-1 text-right ${s.summary.error_events ? "text-crit" : ""}`}>{s.summary.error_events}</td>
                    <td className="px-3 py-1 text-right" onClick={(e) => e.stopPropagation()}>
                      <span className="flex justify-end gap-2">
                        <a className="text-s1 hover:underline" href={`/api/history/${s.id}/export?format=json`}>JSON</a>
                        <a className="text-s1 hover:underline" href={`/api/history/${s.id}/export?format=csv`}>CSV</a>
                        <a className="text-s1 hover:underline" href={`/api/history/${s.id}/export?format=csv&what=events`}>events</a>
                        <button className="text-faint hover:text-crit" onClick={() => void remove(s.id)}>delete</button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {sessions.length === 1 ? <SessionDetail s={sessions[0]} onSaved={refresh} /> : null}
      {sessions.length >= 2 ? <Compare sessions={sessions} /> : null}
    </div>
  );
}

function elapsedFmt(x: number) {
  return fmtDuration(x);
}

function SessionDetail({ s, onSaved }: { s: Session; onSaved: () => void }) {
  const t0 = s.samples[0]?.t ?? s.started_at;
  const end = s.samples[s.samples.length - 1]?.t ?? t0 + 1000;
  const domain: [number, number] = [0, Math.max(1, (end - t0) / 1000)];
  const topics = Object.keys(s.summary.topic_rates).sort();
  const [topic, setTopic] = useState<string>(topics.find((t) => t.includes("scan")) ?? topics[0] ?? "");
  const [label, setLabel] = useState(s.label);
  const [notes, setNotes] = useState(s.notes);
  const x = (t: number) => (t - t0) / 1000;
  const useCov = s.samples.some((p) => p.coverage_pct != null);

  const save = async () => {
    await fetch(`/api/history/${s.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ label, notes }) });
    onSaved();
  };

  const sm = s.summary;
  return (
    <div className="grid grid-cols-12 gap-2">
      <Panel title="Session details" className="col-span-12 xl:col-span-4">
        <div className="space-y-2 p-3 text-2xs">
          <input value={label} onChange={(e) => setLabel(e.target.value)} className="w-full rounded border border-line bg-panel2 px-2 py-1 text-xs text-ink" />
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes (test conditions, arena, config changes…)"
            rows={3}
            className="w-full rounded border border-line bg-panel2 px-2 py-1 text-xs text-ink"
          />
          <button onClick={save} className="rounded border border-line px-2 py-0.5 text-2xs font-semibold uppercase tracking-wider text-muted hover:text-ink">Save label & notes</button>
          <SummaryGrid s={s} />
          <div className="text-faint">
            {s.robot.robot_name} @ {s.robot.hostname ?? "?"} {s.mode === "ros" ? `· domain ${s.robot.ros_domain_id}` : "· simulation"} · {sm.samples} samples
          </div>
        </div>
      </Panel>
      <Panel title="Trajectory" className="col-span-12 h-[340px] xl:col-span-4">
        <Trajectory sessions={[s]} />
      </Panel>
      <Panel title="Events" className="col-span-12 h-[340px] xl:col-span-4" bodyClass="overflow-auto scroll-thin">
        <ul className="divide-y divide-line/50 text-2xs">
          {s.events.map((e, i) => (
            <li key={i} className="flex gap-2 px-3 py-1">
              <span className="num shrink-0 text-faint">+{fmtDuration((e.t - t0) / 1000)}</span>
              <span className={e.level === "error" ? "text-crit" : e.level === "warn" ? "text-warn" : "text-muted"}>
                {e.level === "error" ? "■" : e.level === "warn" ? "▲" : "●"}
              </span>
              <span className="text-ink">{e.message}</span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel
        title="Recorded telemetry"
        className="col-span-12"
        right={
          <select value={topic} onChange={(e) => setTopic(e.target.value)} className="rounded border border-line bg-panel2 px-1 text-2xs text-ink">
            {topics.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        }
      >
        <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <div className="mb-1 text-2xs text-muted">Speed</div>
            <TimeSeriesChart domain={domain} unit="m/s" xFormat={elapsedFmt} minSpan={0.4} height={140}
              series={[{ key: "v", label: "Speed", color: "s1", points: s.samples.map((p) => ({ x: x(p.t), y: p.speed })) }]} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">{useCov ? "Coverage" : "Known area"}</div>
            <TimeSeriesChart domain={domain} unit={useCov ? "%" : "m²"} xFormat={elapsedFmt} digits={1} minSpan={1} height={140}
              series={[{ key: "a", label: "Area", color: "s3", points: s.samples.map((p) => ({ x: x(p.t), y: useCov ? p.coverage_pct : p.known_area_m2 })) }]} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">Rate of {topic || "—"}</div>
            <TimeSeriesChart domain={domain} unit="Hz" xFormat={elapsedFmt} digits={1} minSpan={2} height={140}
              series={[{ key: "r", label: topic, color: "s2", points: s.samples.map((p) => ({ x: x(p.t), y: p.rates[topic] ?? null })) }]} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">Temperatures</div>
            <TimeSeriesChart domain={domain} unit="°C" xFormat={elapsedFmt} digits={1} minSpan={10} height={140} includeZero={false}
              refLine={{ y: 80, label: "warn" }} emptyText="not recorded"
              series={[
                { key: "t", label: "NUC", color: "s2", points: s.samples.map((p) => ({ x: x(p.t), y: p.nuc_temp_c ?? null })) },
                ...(s.samples.some((p) => p.robot_temp_c != null)
                  ? [{ key: "r", label: "Robot (hottest)", color: "s1", points: s.samples.map((p) => ({ x: x(p.t), y: p.robot_temp_c ?? null })) }]
                  : []),
              ]} />
          </div>
        </div>
      </Panel>
    </div>
  );
}

function SummaryGrid({ s }: { s: Session }) {
  const sm = s.summary;
  const items: [string, string][] = [
    ["Duration", fmtDuration(sm.duration_s)],
    ["Distance", `${fmt(sm.distance_m, 1)} m`],
    ["Max speed", `${fmt(sm.max_speed, 2)} m/s`],
    ["Avg moving", `${fmt(sm.avg_moving_speed, 2)} m/s`],
    ["Known area", `${fmt(sm.final_known_area_m2, 1)} m²`],
    ["Coverage", sm.final_coverage_pct != null ? `${fmt(sm.final_coverage_pct, 1)} %` : "n/a"],
    ["Frontiers left", sm.final_frontiers != null ? String(sm.final_frontiers) : "n/a"],
    ["Link losses", `${sm.link_lost_count} (${fmt(sm.link_lost_s, 0)} s)`],
    ["Link delay", sm.link_rtt_ms ? `${sm.link_rtt_ms.median} ms (p95 ${sm.link_rtt_ms.p95})` : "n/a"],
    ["NUC max temp", sm.nuc_temp ? `${sm.nuc_temp.max_c} °C (${sm.nuc_temp.hot_s} s ≥ 80 °C)` : "n/a"],
    ["Robot max temp", sm.robot_temp_max_c != null ? `${sm.robot_temp_max_c} °C` : "n/a"],
    ["Max tilt", sm.max_tilt_deg != null ? `${sm.max_tilt_deg.toFixed(1)}°` : "n/a"],
    ["Closest obstacle", sm.min_obstacle_m != null ? `${sm.min_obstacle_m.toFixed(2)} m` : "n/a"],
    ["Stalls", String(sm.stall_events)],
    ["Errors / warns", `${sm.error_events} / ${sm.warn_events}`],
  ];
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
      {items.map(([k, v]) => (
        <div key={k}>
          <div className="label">{k}</div>
          <div className="num text-xs text-ink">{v}</div>
        </div>
      ))}
    </div>
  );
}

function Compare({ sessions }: { sessions: Session[] }) {
  const allTopics = useMemo(
    () => Array.from(new Set(sessions.flatMap((s) => Object.keys(s.summary.topic_rates)))).sort(),
    [sessions],
  );
  const [topic, setTopic] = useState(allTopics.find((t) => t.includes("scan")) ?? allTopics[0] ?? "");
  const maxDur = Math.max(1, ...sessions.map((s) => s.summary.duration_s));
  const domain: [number, number] = [0, maxDur];
  const series = (f: (p: Session["samples"][number]) => number | null): Series[] =>
    sessions.map((s, i) => {
      const t0 = s.samples[0]?.t ?? s.started_at;
      return { key: s.id, label: s.label, color: SLOTS[i], points: s.samples.map((p) => ({ x: (p.t - t0) / 1000, y: f(p) })) };
    });
  const rows: [string, (s: Session) => string][] = [
    ["Started", (s) => fmtTime(s.started_at)],
    ["Source", (s) => (s.mode === "sim" ? "simulation" : s.robot.hostname ?? "live")],
    ["Duration", (s) => fmtDuration(s.summary.duration_s)],
    ["Distance (m)", (s) => fmt(s.summary.distance_m, 1)],
    ["Known area (m²)", (s) => fmt(s.summary.final_known_area_m2, 1)],
    ["Coverage (%)", (s) => fmt(s.summary.final_coverage_pct, 1)],
    ["Area / minute (m²)", (s) => (s.summary.final_known_area_m2 != null && s.summary.duration_s > 0 ? fmt(s.summary.final_known_area_m2 / (s.summary.duration_s / 60), 2) : "—")],
    ["Max speed (m/s)", (s) => fmt(s.summary.max_speed, 2)],
    ["Avg moving speed (m/s)", (s) => fmt(s.summary.avg_moving_speed, 2)],
    ["Link losses", (s) => `${s.summary.link_lost_count} (${fmt(s.summary.link_lost_s, 0)} s)`],
    ["Link delay median / p95 (ms)", (s) => (s.summary.link_rtt_ms ? `${s.summary.link_rtt_ms.median} / ${s.summary.link_rtt_ms.p95}` : "—")],
    ["NUC max temp (°C) / time ≥ 80 °C", (s) => (s.summary.nuc_temp ? `${s.summary.nuc_temp.max_c} / ${s.summary.nuc_temp.hot_s} s` : "—")],
    ["Robot max temp (°C)", (s) => (s.summary.robot_temp_max_c != null ? String(s.summary.robot_temp_max_c) : "—")],
    ["Max tilt (°) / closest obstacle (m)", (s) => `${s.summary.max_tilt_deg != null ? s.summary.max_tilt_deg.toFixed(1) : "—"} / ${s.summary.min_obstacle_m != null ? s.summary.min_obstacle_m.toFixed(2) : "—"}`],
    ["Stall events", (s) => String(s.summary.stall_events)],
    ["Errors / warnings", (s) => `${s.summary.error_events} / ${s.summary.warn_events}`],
    [`${topic} avg Hz (min)`, (s) => (s.summary.topic_rates[topic] ? `${fmt(s.summary.topic_rates[topic].avg, 1)} (${fmt(s.summary.topic_rates[topic].min, 1)})` : "—")],
  ];
  return (
    <div className="grid grid-cols-12 gap-2">
      <Panel
        title={`Compare ${sessions.length} runs`}
        className="col-span-12 xl:col-span-7"
        right={
          <select value={topic} onChange={(e) => setTopic(e.target.value)} className="rounded border border-line bg-panel2 px-1 text-2xs text-ink">
            {allTopics.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        }
      >
        <table className="w-full text-2xs">
          <thead>
            <tr className="border-b border-line">
              <th className="px-3 py-1 text-left font-medium text-faint">Metric</th>
              {sessions.map((s, i) => (
                <th key={s.id} className="px-3 py-1 text-right font-medium text-ink">
                  <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: `rgb(var(--${SLOTS[i]}))` }} />
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, f]) => (
              <tr key={k} className="border-b border-line/50">
                <td className="px-3 py-1 text-muted">{k}</td>
                {sessions.map((s) => (
                  <td key={s.id} className="num px-3 py-1 text-right text-ink">{f(s)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Trajectories" className="col-span-12 h-[380px] xl:col-span-5">
        <Trajectory sessions={sessions} />
      </Panel>
      <Panel title="Overlaid by elapsed time" className="col-span-12">
        <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <div className="mb-1 text-2xs text-muted">Speed</div>
            <TimeSeriesChart domain={domain} unit="m/s" xFormat={elapsedFmt} minSpan={0.4} height={150} series={series((p) => p.speed)} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">Known area</div>
            <TimeSeriesChart domain={domain} unit="m²" xFormat={elapsedFmt} digits={1} minSpan={1} height={150} series={series((p) => p.known_area_m2)} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">Rate of {topic}</div>
            <TimeSeriesChart domain={domain} unit="Hz" xFormat={elapsedFmt} digits={1} minSpan={2} height={150} series={series((p) => p.rates[topic] ?? null)} />
          </div>
          <div>
            <div className="mb-1 text-2xs text-muted">NUC temperature</div>
            <TimeSeriesChart domain={domain} unit="°C" xFormat={elapsedFmt} digits={1} minSpan={10} height={150} includeZero={false}
              refLine={{ y: 80, label: "warn" }} emptyText="not recorded" series={series((p) => p.nuc_temp_c ?? null)} />
          </div>
        </div>
      </Panel>
    </div>
  );
}

/** Plots recorded (valid, live) poses only. */
function Trajectory({ sessions }: { sessions: Session[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const draw = () => {
      const c = canvas.current, w = wrap.current;
      if (!c || !w) return;
      const dpr = window.devicePixelRatio || 1;
      const W = w.clientWidth, H = w.clientHeight;
      c.width = W * dpr; c.height = H * dpr; c.style.width = `${W}px`; c.style.height = `${H}px`;
      const ctx = c.getContext("2d")!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const pts = sessions.flatMap((s) => s.samples.filter((p) => p.pose_valid && p.x != null));
      if (!pts.length) {
        ctx.fillStyle = "rgb(95,104,117)";
        ctx.font = "11px system-ui";
        ctx.fillText("no valid poses recorded", 12, 20);
        return;
      }
      const xs = pts.map((p) => p.x!), ys = pts.map((p) => p.y!);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY, 1);
      const sc = (0.88 * Math.min(W, H)) / span;
      const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
      const sx = (x: number) => W / 2 + (x - cx) * sc, sy = (y: number) => H / 2 - (y - cy) * sc;
      // 1 m grid
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = 1;
      for (let gx = Math.floor(minX - span); gx <= maxX + span; gx++) { ctx.beginPath(); ctx.moveTo(sx(gx), 0); ctx.lineTo(sx(gx), H); ctx.stroke(); }
      for (let gy = Math.floor(minY - span); gy <= maxY + span; gy++) { ctx.beginPath(); ctx.moveTo(0, sy(gy)); ctx.lineTo(W, sy(gy)); ctx.stroke(); }
      sessions.forEach((s, i) => {
        const v = getComputedStyle(document.documentElement).getPropertyValue(`--${SLOTS[i]}`).trim().split(/\s+/).join(",");
        ctx.strokeStyle = `rgb(${v})`;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.beginPath();
        let pen = false;
        for (const p of s.samples) {
          if (!p.pose_valid || p.x == null || p.y == null) { pen = false; continue; }
          if (pen) ctx.lineTo(sx(p.x), sy(p.y)); else ctx.moveTo(sx(p.x), sy(p.y));
          pen = true;
        }
        ctx.stroke();
        const first = s.samples.find((p) => p.pose_valid && p.x != null);
        if (first) {
          ctx.fillStyle = `rgb(${v})`;
          ctx.beginPath(); ctx.arc(sx(first.x!), sy(first.y!), 4, 0, Math.PI * 2); ctx.fill();
        }
      });
      ctx.fillStyle = "rgb(95,104,117)";
      ctx.font = "10px ui-monospace, Menlo, monospace";
      ctx.fillText("grid 1 m · dot = start · gaps = pose not live", 8, H - 8);
    };
    draw();
    const ro = new ResizeObserver(draw);
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [sessions]);
  return (
    <div ref={wrap} className="h-full w-full">
      <canvas ref={canvas} className="block" />
    </div>
  );
}
