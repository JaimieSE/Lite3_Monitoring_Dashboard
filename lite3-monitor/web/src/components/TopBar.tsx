"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTelemetry } from "./TelemetryProvider";
import { StatusPill, type Level } from "./ui";
import { fmtAge, fmtDuration } from "@/lib/format";

export function TopBar() {
  const { client, recorder, autoRecord, setAutoRecord } = useTelemetry();
  const path = usePathname();
  const hello = client.hello;
  const link = client.link;
  const telAge = client.ageMs("telemetry");

  const linkLevel: Level = link === "live" ? "good" : link === "stale" ? "warn" : link === "lost" ? "crit" : "idle";
  const linkText =
    link === "live" ? "Live" : link === "stale" ? "Stale" : link === "lost" ? "Telemetry lost" : "Connecting";

  const session = recorder.session;
  const recElapsed = session ? ((session.ended_at ?? Date.now()) - session.started_at) / 1000 : null;

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold tracking-[0.18em] text-ink">LITE3</span>
          <span className="text-2xs uppercase tracking-[0.2em] text-faint">Mission control · read-only</span>
        </div>

        <nav className="flex items-center gap-1 text-xs">
          {[
            ["/", "Live"],
            ["/history", "History"],
          ].map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`rounded px-2 py-1 font-medium ${path === href ? "bg-panel2 text-ink" : "text-muted hover:text-ink"}`}
            >
              {label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2 text-xs">
          {hello?.mode === "sim" ? (
            <StatusPill level="warn">Simulation</StatusPill>
          ) : hello?.mode === "ros" ? (
            <StatusPill level={client.identityProblem ? "crit" : hello.identity.verified ? "good" : "warn"}>
              {client.identityProblem ? "Identity mismatch" : hello.identity.verified ? "Robot verified" : "Identity unverified"}
            </StatusPill>
          ) : null}
          {hello ? (
            <span className="num text-muted" title={`fingerprint ${hello.identity.machine_fingerprint}`}>
              {hello.identity.robot_name} @ {hello.identity.hostname}
              {hello.mode === "ros" ? ` · domain ${hello.identity.ros_domain_id}` : ""}
            </span>
          ) : (
            <span className="num text-faint">{client.bridgeUrl || "…"}</span>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3 text-xs">
          <span className="flex items-center gap-2">
            <StatusPill level={linkLevel} className={link === "lost" ? "lost-pulse" : ""}>
              {linkText}
            </StatusPill>
            <span className="num w-16 text-muted" title="time since last telemetry message">
              {telAge == null ? "—" : fmtAge(telAge / 1000)}
            </span>
          </span>

          <span className="h-4 w-px bg-line" />

          <span className="flex items-center gap-2">
            {recorder.recording ? (
              <>
                <span className="flex items-center gap-1.5 text-crit">
                  <span className="lost-pulse inline-block h-2 w-2 rounded-full bg-crit" />
                  <span className="text-2xs font-semibold uppercase tracking-wider">Rec</span>
                </span>
                <span className="num text-ink" title="session elapsed">{fmtDuration(recElapsed)}</span>
                {recorder.lastFlushOk === false ? (
                  <StatusPill level="serious">{recorder.flushError ?? "save failed"}</StatusPill>
                ) : null}
                <button
                  onClick={() => void recorder.stop()}
                  className="rounded border border-line px-2 py-0.5 text-2xs font-semibold uppercase tracking-wider text-muted hover:text-ink"
                >
                  Stop
                </button>
              </>
            ) : (
              <button
                onClick={() => recorder.start()}
                disabled={!client.hello || !!client.identityProblem}
                className="rounded border border-line px-2 py-0.5 text-2xs font-semibold uppercase tracking-wider text-muted hover:text-ink disabled:opacity-40"
              >
                Record session
              </button>
            )}
            <label className="flex cursor-pointer items-center gap-1 text-2xs text-faint" title="Start recording automatically when telemetry arrives">
              <input type="checkbox" checked={autoRecord} onChange={(e) => setAutoRecord(e.target.checked)} className="accent-[rgb(var(--s1))]" />
              auto
            </label>
          </span>
        </div>
      </div>
    </header>
  );
}
