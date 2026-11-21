"use client";

import { useEffect, useRef, useState } from "react";

export interface Series {
  key: string;
  label: string;
  /** CSS variable name of a categorical slot, e.g. "s1". Never a status colour. */
  color: string;
  dashed?: boolean;
  points: { x: number; y: number | null }[];
}

interface Props {
  series: Series[];
  domain: [number, number];
  height?: number;
  unit?: string;
  digits?: number;
  includeZero?: boolean;
  minSpan?: number;
  refLine?: { y: number; label: string };
  xFormat?: (x: number) => string;
  emptyText?: string;
}

function rgbVar(name: string, a = 1) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return `rgb(${v.split(/\s+/).join(",")},${a})`;
}

function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

const PAD = { l: 38, r: 8, t: 6, b: 16 };

/**
 * Lightweight canvas line chart: one y-axis, 2 px lines, recessive grid,
 * legend + crosshair tooltip. Null values break the line (outages are gaps).
 */
export function TimeSeriesChart({
  series, domain, height = 120, unit = "", digits = 2, includeZero = true, minSpan = 0.1, refLine,
  xFormat = (x) => new Date(x).toLocaleTimeString(), emptyText = "no data",
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [width, setWidth] = useState(300);
  const geo = useRef({ lo: 0, hi: 1, x0: 0, x1: 1, W: 300, H: height });

  useEffect(() => {
    const ro = new ResizeObserver(() => setWidth(wrapRef.current?.clientWidth ?? 300));
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const [x0, x1] = domain;
  const visible = series.map((s) => ({ ...s, pts: s.points.filter((p) => p.x >= x0 && p.x <= x1) }));
  const ys = visible.flatMap((s) => s.pts.map((p) => p.y).filter((y): y is number => y != null && Number.isFinite(y)));
  const hasData = ys.length > 0;

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const W = width;
    const H = height;
    c.width = W * dpr;
    c.height = H * dpr;
    c.style.width = `${W}px`;
    c.style.height = `${H}px`;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    let lo = hasData ? Math.min(...ys) : 0;
    let hi = hasData ? Math.max(...ys) : 1;
    if (refLine) {
      lo = Math.min(lo, refLine.y);
      hi = Math.max(hi, refLine.y);
    }
    if (includeZero) {
      lo = Math.min(lo, 0);
      hi = Math.max(hi, 0);
    }
    if (hi - lo < minSpan) {
      const mid = (hi + lo) / 2;
      lo = includeZero && lo >= 0 ? 0 : mid - minSpan / 2;
      hi = lo + minSpan;
    }
    const padY = (hi - lo) * 0.08;
    hi += padY;
    if (!(includeZero && lo === 0)) lo -= padY;
    geo.current = { lo, hi, x0, x1, W, H };

    const sx = (x: number) => PAD.l + ((x - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
    const sy = (y: number) => PAD.t + (1 - (y - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);

    ctx.font = "10px ui-monospace, Menlo, monospace";
    ctx.textBaseline = "middle";
    for (const t of niceTicks(lo, hi, 3)) {
      const y = sy(t);
      ctx.strokeStyle = "rgba(255,255,255,0.06)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(PAD.l, Math.round(y) + 0.5);
      ctx.lineTo(W - PAD.r, Math.round(y) + 0.5);
      ctx.stroke();
      ctx.fillStyle = "rgb(95,104,117)";
      ctx.textAlign = "right";
      ctx.fillText(Math.abs(t) >= 100 ? t.toFixed(0) : t.toFixed(t % 1 === 0 ? 0 : 1), PAD.l - 4, y);
    }
    ctx.textAlign = "left";
    ctx.fillText(xFormat(x0), PAD.l, H - 6);
    ctx.textAlign = "right";
    ctx.fillText(xFormat(x1), W - PAD.r, H - 6);

    if (refLine) {
      const y = sy(refLine.y);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = "rgba(255,255,255,0.25)";
      ctx.beginPath();
      ctx.moveTo(PAD.l, y);
      ctx.lineTo(W - PAD.r, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const s of visible) {
      ctx.strokeStyle = rgbVar(s.color);
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.setLineDash(s.dashed ? [4, 3] : []);
      ctx.beginPath();
      let pen = false;
      for (const p of s.pts) {
        if (p.y == null || !Number.isFinite(p.y)) {
          pen = false;
          continue;
        }
        const X = sx(p.x), Y = sy(p.y);
        if (pen) ctx.lineTo(X, Y);
        else ctx.moveTo(X, Y);
        pen = true;
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (hoverX != null && hoverX >= x0 && hoverX <= x1) {
      const X = sx(hoverX);
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(X, PAD.t);
      ctx.lineTo(X, H - PAD.b);
      ctx.stroke();
      for (const s of visible) {
        const p = nearest(s.pts, hoverX);
        if (!p || p.y == null) continue;
        ctx.beginPath();
        ctx.arc(sx(p.x), sy(p.y), 4, 0, Math.PI * 2);
        ctx.fillStyle = rgbVar(s.color);
        ctx.fill();
        ctx.strokeStyle = "rgb(17,20,25)";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
  });

  const onMove = (e: React.MouseEvent) => {
    const r = wrapRef.current!.getBoundingClientRect();
    const g = geo.current;
    const fx = (e.clientX - r.left - PAD.l) / (g.W - PAD.l - PAD.r);
    setHoverX(fx < 0 || fx > 1 ? null : g.x0 + fx * (g.x1 - g.x0));
  };

  const tip = hoverX != null ? visible.map((s) => ({ s, p: nearest(s.pts, hoverX) })) : null;
  const tipLeft = hoverX != null ? PAD.l + ((hoverX - x0) / (x1 - x0 || 1)) * (width - PAD.l - PAD.r) : 0;

  return (
    <div className="relative w-full">
      {series.length > 1 ? (
        <div className="mb-0.5 flex flex-wrap gap-x-3 px-1 text-2xs text-muted">
          {series.map((s) => (
            <span key={s.key} className="flex items-center gap-1">
              <svg width="14" height="6" aria-hidden>
                <line x1="0" y1="3" x2="14" y2="3" stroke={`rgb(var(--${s.color}))`} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
              </svg>
              {s.label}
            </span>
          ))}
          {unit ? <span className="ml-auto text-faint">{unit}</span> : null}
        </div>
      ) : unit ? (
        <div className="mb-0.5 px-1 text-right text-2xs text-faint">{unit}</div>
      ) : null}
      <div ref={wrapRef} className="relative" onMouseMove={onMove} onMouseLeave={() => setHoverX(null)}>
        <canvas ref={canvasRef} className="block" />
        {!hasData ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-2xs text-faint">{emptyText}</div>
        ) : null}
        {tip && hasData ? (
          <div
            className="pointer-events-none absolute top-1 z-10 rounded border border-line bg-panel2/95 px-2 py-1 text-2xs shadow"
            style={{ left: Math.min(Math.max(tipLeft + 8, 0), width - 150), minWidth: 130 }}
          >
            <div className="num mb-0.5 text-faint">{xFormat(hoverX!)}</div>
            {tip.map(({ s, p }) => (
              <div key={s.key} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1 text-muted">
                  <span className="inline-block h-0.5 w-2.5" style={{ background: `rgb(var(--${s.color}))` }} />
                  {s.label}
                </span>
                <span className="num text-ink">{p?.y == null ? "—" : p.y.toFixed(digits)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function nearest(pts: { x: number; y: number | null }[], x: number) {
  if (!pts.length) return null;
  let lo = 0, hi = pts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].x < x) lo = mid;
    else hi = mid;
  }
  return Math.abs(pts[lo].x - x) <= Math.abs(pts[hi].x - x) ? pts[lo] : pts[hi];
}
