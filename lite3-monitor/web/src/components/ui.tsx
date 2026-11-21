import type { ReactNode } from "react";

export type Level = "good" | "warn" | "serious" | "crit" | "idle";

const DOT: Record<Level, string> = {
  good: "bg-good",
  warn: "bg-warn",
  serious: "bg-serious",
  crit: "bg-crit",
  idle: "bg-faint",
};
const TEXT: Record<Level, string> = {
  good: "text-good",
  warn: "text-warn",
  serious: "text-serious",
  crit: "text-crit",
  idle: "text-muted",
};
const ICON: Record<Level, string> = { good: "●", warn: "▲", serious: "▲", crit: "■", idle: "○" };

/** Status indicator: colour + shape + text, never colour alone. */
export function StatusPill({ level, children, className = "" }: { level: Level; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border border-line bg-panel2 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wider ${TEXT[level]} ${className}`}>
      <span aria-hidden className="text-[9px] leading-none">{ICON[level]}</span>
      {children}
    </span>
  );
}

export function Dot({ level }: { level: Level }) {
  return <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[level]}`} />;
}

export function Panel({ title, right, children, className = "", bodyClass = "" }: {
  title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`}>
      <header className="panel-title">
        <span>{title}</span>
        {right ? <span className="normal-case tracking-normal">{right}</span> : null}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

export function Metric({ label, value, unit, sub, level, big = false }: {
  label: string; value: ReactNode; unit?: string; sub?: ReactNode; level?: Level; big?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="label truncate">{label}</div>
      <div className={`num truncate ${big ? "text-xl" : "text-base"} leading-tight ${level ? TEXT[level] : "text-ink"}`}>
        {value}
        {unit ? <span className="ml-0.5 text-2xs text-muted">{unit}</span> : null}
      </div>
      {sub ? <div className="truncate text-2xs text-faint">{sub}</div> : null}
    </div>
  );
}

export function topicLevel(status: string): Level {
  switch (status) {
    case "ok":
      return "good";
    case "warn":
      return "warn";
    case "error":
    case "missing":
      return "crit";
    default:
      return "idle";
  }
}
