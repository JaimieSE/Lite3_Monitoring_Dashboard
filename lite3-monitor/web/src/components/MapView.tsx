"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTelemetry } from "./TelemetryProvider";
import { fmt, fmtAge } from "@/lib/format";
import type { DecodedMap } from "@/lib/types";

// Lite3 footprint (approx., metres) used only for drawing.
const BODY_L = 0.61;
const BODY_W = 0.32;

interface View {
  scale: number; // px per metre
  cx: number; // world x at canvas centre
  cy: number;
  follow: boolean;
  /** Re-fit whenever the map grows, until the user pans/zooms. */
  autoFit: boolean;
  fittedVersion: number;
}

interface Layers {
  trail: boolean;
  paths: boolean;
  frontiers: boolean;
  goal: boolean;
  grid: boolean;
}

function cssRgb(name: string, alpha = 1): string {
  if (typeof window === "undefined") return "#888";
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return `rgb(${v.split(/\s+/).join(",")},${alpha})`;
}

/** Render the occupancy grid into an offscreen canvas (1 px per cell). */
function renderGrid(map: DecodedMap): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = map.width;
  c.height = map.height;
  const ctx = c.getContext("2d")!;
  const img = ctx.createImageData(map.width, map.height);
  const d = img.data;
  const cells = map.cells;
  // Unknown is near-background; explored free space is a lifted slate; walls are bright.
  for (let i = 0; i < cells.length; i++) {
    const v = cells[i];
    const o = i * 4;
    if (v === 255) {
      d[o] = 14; d[o + 1] = 17; d[o + 2] = 22; d[o + 3] = 255;
    } else if (v >= 65) {
      d[o] = 222; d[o + 1] = 228; d[o + 2] = 236; d[o + 3] = 255;
    } else {
      // 0 (free) .. 64 (uncertain): blend from free slate towards grey
      const k = v / 64;
      d[o] = 38 + k * 70; d[o + 1] = 50 + k * 62; d[o + 2] = 64 + k * 54; d[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

export function MapView() {
  const { client, version, setMapEnabled } = useTelemetry();
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const gridRef = useRef<{ version: number; canvas: HTMLCanvasElement } | null>(null);
  const viewRef = useRef<View>({ scale: 40, cx: 0, cy: 0, follow: false, autoFit: true, fittedVersion: -1 });
  const dragRef = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);
  const [layers, setLayers] = useState<Layers>({ trail: true, paths: true, frontiers: true, goal: true, grid: true });
  const [follow, setFollow] = useState(false);
  const [autoFit, setAutoFit] = useState(true);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [scaleBar, setScaleBar] = useState({ px: 40, m: 1 });
  const layersRef = useRef(layers);
  layersRef.current = layers;

  const fit = useCallback(() => {
    const map = client.map;
    const el = wrapRef.current;
    const v = viewRef.current;
    if (!map || !el) return;
    const w = map.width * map.resolution;
    const h = map.height * map.resolution;
    v.scale = Math.max(4, Math.min(400, 0.92 * Math.min(el.clientWidth / w, el.clientHeight / h)));
    v.cx = map.origin.x + w / 2;
    v.cy = map.origin.y + h / 2;
    v.follow = false;
    v.autoFit = true;
    v.fittedVersion = map.version;
    setFollow(false);
    setAutoFit(true);
  }, [client]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const W = wrap.clientWidth;
    const H = wrap.clientHeight;
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
    }
    const ctx = canvas.getContext("2d")!;
    const v = viewRef.current;
    const L = layersRef.current;
    const identityBad = !!client.identityProblem;
    const map = identityBad ? null : client.map;
    const tel = identityBad ? null : client.telemetry;
    const paths = identityBad ? null : client.paths;
    const pose = tel?.pose ?? null;
    const live = client.poseLive;

    if (map && v.autoFit && v.fittedVersion !== map.version) fit();
    // Without a grid (no map / map stream off) "fit" frames the trail and the robot.
    if (!map && v.autoFit && pose) {
      const pts: [number, number][] = [[pose.x, pose.y]];
      if (paths?.trail.frame === pose.frame) pts.push(...paths.trail.points);
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const [x, y] of pts) {
        x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
      const w = Math.max(x1 - x0, 4), h = Math.max(y1 - y0, 4); // at least 4 m across
      v.scale = Math.max(4, Math.min(120, 0.8 * Math.min(W / w, H / h)));
      v.cx = (x0 + x1) / 2;
      v.cy = (y0 + y1) / 2;
    }
    if (v.follow && pose && pose.map_frame) {
      v.cx = pose.x;
      v.cy = pose.y;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "rgb(9,11,14)";
    ctx.fillRect(0, 0, W, H);

    // world -> screen: x right, y up
    const s = v.scale;
    ctx.setTransform(dpr * s, 0, 0, -dpr * s, dpr * (W / 2 - v.cx * s), dpr * (H / 2 + v.cy * s));
    const px = 1 / s; // one screen pixel in metres

    if (map) {
      if (!gridRef.current || gridRef.current.version !== map.version) {
        gridRef.current = { version: map.version, canvas: renderGrid(map) };
      }
      ctx.save();
      ctx.imageSmoothingEnabled = false;
      ctx.translate(map.origin.x, map.origin.y);
      ctx.rotate(map.origin.yaw);
      ctx.drawImage(gridRef.current.canvas, 0, 0, map.width * map.resolution, map.height * map.resolution);
      ctx.restore();
    }

    // 1 m grid
    if (L.grid && s >= 12) {
      const x0 = Math.floor(v.cx - W / 2 / s), x1 = Math.ceil(v.cx + W / 2 / s);
      const y0 = Math.floor(v.cy - H / 2 / s), y1 = Math.ceil(v.cy + H / 2 / s);
      ctx.beginPath();
      for (let x = x0; x <= x1; x++) { ctx.moveTo(x, y0); ctx.lineTo(x, y1); }
      for (let y = y0; y <= y1; y++) { ctx.moveTo(x0, y); ctx.lineTo(x1, y); }
      ctx.strokeStyle = "rgba(255,255,255,0.045)";
      ctx.lineWidth = px;
      ctx.stroke();
      // origin axes
      ctx.beginPath();
      ctx.moveTo(0, 0); ctx.lineTo(0.5, 0);
      ctx.strokeStyle = "rgba(208,59,59,0.7)"; ctx.lineWidth = 2 * px; ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, 0); ctx.lineTo(0, 0.5);
      ctx.strokeStyle = "rgba(12,163,12,0.7)"; ctx.stroke();
    }

    // Draw in the map frame when there is a map; otherwise in the robot pose's own
    // frame (e.g. "odom" for robots running without a map).
    const mapFrame = map ? (client.hello?.frames.map ?? "map") : (pose?.frame ?? client.hello?.frames.map ?? "map");
    const polyline = (pts: [number, number][], color: string, width: number, dash: number[] = []) => {
      if (pts.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.strokeStyle = color;
      ctx.lineWidth = width * px;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.setLineDash(dash.map((d) => d * px));
      ctx.stroke();
      ctx.setLineDash([]);
    };

    if (paths && L.trail && paths.trail.frame === mapFrame) polyline(paths.trail.points, cssRgb("s7", 0.75), 2);
    if (paths && L.paths) {
      if (paths.global?.frame === mapFrame) polyline(paths.global.points, cssRgb("s1", 0.95), 2);
      if (paths.local?.frame === mapFrame) polyline(paths.local.points, cssRgb("s2", 0.95), 2.5);
    }
    if (paths?.frontiers && L.frontiers && paths.frontiers.frame === mapFrame) {
      ctx.strokeStyle = cssRgb("s3", 0.95);
      ctx.fillStyle = cssRgb("s3", 0.25);
      ctx.lineWidth = 2 * px;
      for (const [x, y] of paths.frontiers.points) {
        ctx.beginPath();
        ctx.arc(x, y, 5 * px, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    }
    const goal = tel?.nav.goal;
    if (goal && L.goal && goal.frame === mapFrame) {
      const r = 9 * px;
      ctx.strokeStyle = cssRgb("s5", 1);
      ctx.lineWidth = 2 * px;
      ctx.beginPath();
      ctx.arc(goal.x, goal.y, r, 0, Math.PI * 2);
      ctx.moveTo(goal.x - r * 1.6, goal.y); ctx.lineTo(goal.x + r * 1.6, goal.y);
      ctx.moveTo(goal.x, goal.y - r * 1.6); ctx.lineTo(goal.x, goal.y + r * 1.6);
      ctx.stroke();
      if (pose && pose.map_frame && live) polyline([[pose.x, pose.y], [goal.x, goal.y]], cssRgb("s5", 0.5), 1, [4, 4]);
    }

    // robot
    if (pose && (pose.map_frame || !map)) {
      ctx.save();
      ctx.translate(pose.x, pose.y);
      ctx.rotate(pose.yaw);
      const l = Math.max(BODY_L, 14 * px), w = Math.max(BODY_W, 8 * px);
      ctx.beginPath();
      ctx.rect(-l / 2, -w / 2, l, w);
      if (live) {
        ctx.fillStyle = cssRgb("s1", 0.9);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.lineWidth = 2 * px;
        ctx.stroke();
      } else {
        ctx.strokeStyle = "rgba(150,158,170,0.9)";
        ctx.lineWidth = 2 * px;
        ctx.setLineDash([4 * px, 3 * px]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // heading arrow
      ctx.beginPath();
      ctx.moveTo(l / 2 + 10 * px, 0);
      ctx.lineTo(l / 2 - 2 * px, 5 * px);
      ctx.lineTo(l / 2 - 2 * px, -5 * px);
      ctx.closePath();
      ctx.fillStyle = live ? "rgba(255,255,255,0.95)" : "rgba(150,158,170,0.9)";
      ctx.fill();
      ctx.restore();
    }

    // screen-space overlays
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (pose && !live && (pose.map_frame || !map)) {
      const sx = W / 2 + (pose.x - v.cx) * s;
      const sy = H / 2 - (pose.y - v.cy) * s;
      const age = client.link === "live" ? pose.age_s : (client.ageMs("telemetry") ?? 0) / 1000 + pose.age_s;
      const text = `LAST KNOWN · ${fmtAge(age)} ago`;
      ctx.font = "600 11px ui-monospace, Menlo, monospace";
      const tw = ctx.measureText(text).width;
      ctx.fillStyle = "rgba(9,11,14,0.85)";
      ctx.fillRect(sx + 14, sy - 24, tw + 10, 18);
      ctx.fillStyle = "rgb(150,158,170)";
      ctx.fillText(text, sx + 19, sy - 11);
    }
    if (client.link === "lost" || client.link === "stale") {
      ctx.fillStyle = client.link === "lost" ? "rgba(9,11,14,0.45)" : "rgba(9,11,14,0.2)";
      ctx.fillRect(0, 0, W, H);
    }
  }, [client, fit]);

  // redraw on new data (throttled by the client) and on a slow timer for age labels
  useEffect(() => {
    const id = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(id);
  }, [version, layers, draw]);
  useEffect(() => {
    const t = setInterval(() => requestAnimationFrame(draw), 500);
    const ro = new ResizeObserver(() => requestAnimationFrame(draw));
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => {
      clearInterval(t);
      ro.disconnect();
    };
  }, [draw]);

  // scale bar: pick a round length ~80-160 px
  useEffect(() => {
    const s = viewRef.current.scale;
    const candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50];
    const m = candidates.find((c) => c * s >= 70) ?? 50;
    setScaleBar({ px: m * s, m });
  }, [version]);

  const toWorld = (e: React.MouseEvent) => {
    const r = wrapRef.current!.getBoundingClientRect();
    const v = viewRef.current;
    return { x: v.cx + (e.clientX - r.left - r.width / 2) / v.scale, y: v.cy - (e.clientY - r.top - r.height / 2) / v.scale };
  };

  const onWheel = (e: React.WheelEvent) => {
    const v = viewRef.current;
    if (v.autoFit) {
      v.autoFit = false;
      setAutoFit(false);
    }
    const before = toWorld(e);
    v.scale = Math.max(3, Math.min(600, v.scale * Math.exp(-e.deltaY * 0.0015)));
    if (!v.follow) {
      const after = toWorld(e);
      v.cx += before.x - after.x;
      v.cy += before.y - after.y;
    }
    requestAnimationFrame(draw);
  };

  const onDown = (e: React.MouseEvent) => {
    dragRef.current = { x: e.clientX, y: e.clientY, cx: viewRef.current.cx, cy: viewRef.current.cy };
  };
  const onMove = (e: React.MouseEvent) => {
    setCursor(toWorld(e));
    const d = dragRef.current;
    if (!d) return;
    const v = viewRef.current;
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3 && (v.follow || v.autoFit)) {
      v.follow = false;
      v.autoFit = false;
      setFollow(false);
      setAutoFit(false);
    }
    v.cx = d.cx - (e.clientX - d.x) / v.scale;
    v.cy = d.cy + (e.clientY - d.y) / v.scale;
    requestAnimationFrame(draw);
  };
  const onUp = () => {
    dragRef.current = null;
  };

  const toggleFollow = () => {
    const v = viewRef.current;
    v.follow = !v.follow;
    v.autoFit = false;
    setFollow(v.follow);
    setAutoFit(false);
    requestAnimationFrame(draw);
  };

  const map = client.identityProblem ? null : client.map;
  const pose = client.telemetry?.pose;
  const mapAge = client.health?.map?.age_s ?? null;
  const btn = (on: boolean) =>
    `rounded border px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wider ${on ? "border-s1/60 bg-s1/15 text-ink" : "border-line bg-panel/90 text-muted hover:text-ink"}`;

  return (
    <div className="relative h-full min-h-[420px] w-full overflow-hidden rounded-b-md">
      <div
        ref={wrapRef}
        className="absolute inset-0 cursor-grab active:cursor-grabbing"
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={() => {
          onUp();
          setCursor(null);
        }}
        onDoubleClick={fit}
      >
        <canvas ref={canvasRef} className="block" />
      </div>

      {/* toolbar */}
      <div className="absolute left-2 top-2 flex flex-wrap gap-1">
        <MapStreamToggle
          state={client.mapLink}
          kbps={client.linkStats.kbpsMap}
          onToggle={() => setMapEnabled(!client.mapEnabled)}
        />
        <span className="mx-0.5 w-px self-stretch bg-line" />
        <button className={btn(follow)} onClick={toggleFollow}>Follow</button>
        <button className={btn(autoFit)} onClick={fit} title="Fit the whole map and keep fitting as it grows">Fit</button>
        {(Object.keys(layers) as (keyof Layers)[]).map((k) => (
          <button key={k} className={btn(layers[k])} onClick={() => setLayers((l) => ({ ...l, [k]: !l[k] }))}>
            {k}
          </button>
        ))}
      </div>

      {/* legend */}
      <div className="pointer-events-none absolute bottom-12 right-2 rounded border border-line bg-panel/90 px-2 py-1.5 text-2xs text-muted">
        <LegendRow swatch={<span className="inline-block h-2.5 w-3.5 rounded-sm bg-s1 ring-1 ring-white/80" />} label="Robot (live)" />
        <LegendRow swatch={<span className="inline-block h-2.5 w-3.5 rounded-sm border border-dashed border-muted" />} label="Robot (last known)" />
        <LegendRow swatch={<span className="inline-block h-0.5 w-3.5 bg-s1" />} label="Global path" />
        <LegendRow swatch={<span className="inline-block h-0.5 w-3.5 bg-s2" />} label="Local path" />
        <LegendRow swatch={<span className="inline-block h-0.5 w-3.5 bg-s7" />} label="Trail" />
        <LegendRow swatch={<span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-s3" />} label="Frontier" />
        <LegendRow swatch={<span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-s5" />} label="Nav goal" />
        {map ? <div className="mt-1 flex items-center gap-1.5 border-t border-line pt-1">
          <span className="inline-block h-2.5 w-2.5 bg-[rgb(38,50,64)]" /> free
          <span className="ml-1 inline-block h-2.5 w-2.5 bg-[rgb(222,228,236)]" /> occupied
          <span className="ml-1 inline-block h-2.5 w-2.5 border border-line bg-[rgb(14,17,22)]" /> unknown
        </div> : null}
      </div>

      {/* banners */}
      {client.identityProblem ? (
        <Banner tone="crit" title="IDENTITY MISMATCH — DATA HIDDEN" detail={client.identityProblem} />
      ) : client.link === "lost" ? (
        <Banner
          tone="crit"
          title="TELEMETRY LOST"
          detail={`No data for ${fmtAge((client.ageMs("telemetry") ?? 0) / 1000)} · reconnecting to ${client.bridgeUrl} · positions shown are NOT live`}
          pulse
        />
      ) : client.link === "connecting" ? (
        <Banner tone="idle" title="CONNECTING" detail={`Waiting for bridge at ${client.bridgeUrl || "…"}`} />
      ) : client.link === "stale" ? (
        <Banner tone="warn" title="TELEMETRY DELAYED" detail="Updates are late — values may be out of date" />
      ) : pose && !pose.valid ? (
        <Banner tone="warn" title="POSE STALE" detail={`Robot pose is ${fmtAge(pose.age_s)} old (source: ${pose.source})`} />
      ) : pose && !pose.map_frame && map ? (
        <Banner tone="warn" title="NO MAP→ROBOT TRANSFORM" detail={`Pose only available in '${pose.frame}' frame; robot not drawn on map`} />
      ) : null}

      {/* bottom strip */}
      <div className="pointer-events-none absolute bottom-2 left-2 right-2 flex items-end justify-between gap-2 text-2xs">
        <div className="num rounded border border-line bg-panel/90 px-2 py-1 text-muted">
          {cursor ? `x ${cursor.x.toFixed(2)}  y ${cursor.y.toFixed(2)} m` : "scroll: zoom · drag: pan · dbl-click: fit"}
        </div>
        <div className="num rounded border border-line bg-panel/90 px-2 py-1 text-muted">
          {map ? (
            <>
              map {map.width}×{map.height} @ {fmt(map.resolution, 2)} m · v{map.version} · age{" "}
              <span className={client.health?.map?.stale ? "text-warn" : ""}>{fmtAge(mapAge)}</span>
            </>
          ) : !client.health?.map ? (
            <>no map · position from {client.telemetry?.pose?.source ?? "—"} in frame {client.telemetry?.pose?.frame ?? "—"}</>
          ) : client.mapLink === "off" || client.mapLink === "disabled" ? (
            <>
              map stream {client.mapLink} · SLAM map v{client.health?.map?.version ?? "—"} · explored{" "}
              {fmt(client.mapStats?.known_area_m2, 1)} m² (stats only)
            </>
          ) : (
            "waiting for map…"
          )}
        </div>
        <div className="flex flex-col items-center rounded border border-line bg-panel/90 px-2 py-1 text-muted">
          <div className="h-1.5 border-x border-b border-muted" style={{ width: scaleBar.px }} />
          <span className="num">{scaleBar.m} m</span>
        </div>
      </div>
    </div>
  );
}

function LegendRow({ swatch, label }: { swatch: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-1.5 leading-5">
      <span className="flex w-4 justify-center">{swatch}</span>
      {label}
    </div>
  );
}

function Banner({ tone, title, detail, pulse }: { tone: "crit" | "warn" | "idle"; title: string; detail: string; pulse?: boolean }) {
  const cls =
    tone === "crit" ? "border-crit bg-crit/90 text-white" : tone === "warn" ? "border-warn bg-warn/90 text-black" : "border-line bg-panel2/95 text-ink";
  return (
    <div className={`absolute left-1/2 top-12 z-10 w-[min(90%,640px)] -translate-x-1/2 rounded border-2 px-4 py-2 text-center shadow-lg ${cls} ${pulse ? "lost-pulse" : ""}`}>
      <div className="text-base font-bold tracking-[0.2em]">{title}</div>
      <div className="text-xs opacity-90">{detail}</div>
    </div>
  );
}

function MapStreamToggle({ state, kbps, onToggle }: { state: string; kbps: number; onToggle: () => void }) {
  const on = state === "live" || state === "connecting";
  const disabled = state === "disabled";
  const label = disabled ? "Map: disabled" : on ? `Map stream: on${state === "live" ? ` · ${kbps.toFixed(1)} kB/s` : " · connecting"}` : "Map stream: off";
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      title={
        disabled
          ? "The bridge config has layers.map.enabled: false"
          : on
            ? "Stop streaming the occupancy grid to save Wi-Fi bandwidth. Pose, paths, health and coverage keep updating."
            : "Start streaming the occupancy grid again"
      }
      className={`flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wider disabled:opacity-50 ${
        on ? "border-s3/60 bg-s3/15 text-ink" : "border-line bg-panel/90 text-muted hover:text-ink"
      }`}
    >
      <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${on ? "bg-s3" : "border border-muted"}`} />
      <span className="num normal-case tracking-normal">{label}</span>
    </button>
  );
}
