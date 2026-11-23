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
            <LinkDelay />
            <NucTemp />
            <RobotTempPill />
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

/** Round-trip delay to the bridge (Wi-Fi + SSH tunnel), from the 1 Hz clock probe. */
function LinkDelay() {
  const { client } = useTelemetry();
  const ls = client.linkStats;
  const failed = ls.probeFailures >= 2 || ls.rttMs == null;
  const rtt = ls.rttMs ?? 0;
  const level: Level = failed ? (client.everConnected ? "crit" : "idle") : rtt < 150 ? "good" : rtt < 500 ? "warn" : "serious";
  const title = failed
    ? "Link delay probe failing (bridge unreachable)"
    : [
        `Round trip: ${Math.round(rtt)} ms (last ${ls.rttLastMs == null ? "—" : Math.round(ls.rttLastMs)} ms)`,
        `Telemetry one-way: ${ls.transitMs == null ? "—" : Math.round(ls.transitMs) + " ms"}`,
        `Clock offset bridge-Mac: ${ls.clockOffsetMs == null ? "—" : Math.round(ls.clockOffsetMs) + " ms"}`,
        `Received: ${ls.kbpsMain.toFixed(1)} kB/s telemetry + ${ls.kbpsMap.toFixed(1)} kB/s map`,
        `Dashboards connected to the bridge: ${client.health?.bridge.clients ?? "—"} (map: ${client.health?.bridge.map_clients ?? "—"})`,
      ].join("\n");
  return (
    <span title={title}>
      <StatusPill level={level}>
        <span className="normal-case tracking-normal">delay {failed ? "—" : `${Math.round(rtt)} ms`}</span>
      </StatusPill>
    </span>
  );
}

/** Always-visible NUC temperature (hottest sensor), with thresholds from the bridge config. */
function NucTemp() {
  const { client } = useTelemetry();
  const c = client.identityProblem ? null : client.health?.compute;
  if (!c || c.temp_max_c == null) return null;
  const lv = client.tempLevel;
  const level: Level = client.link !== "live" ? "idle" : lv === "crit" ? "crit" : lv === "warn" ? "warn" : "good";
  const title = [
    ...c.temps.map((t) => `${t.label}: ${t.c} °C`),
    `Warn ≥ ${c.temp_warn_c ?? 80} °C · critical ≥ ${c.temp_crit_c ?? 90} °C`,
    c.cpu_mhz != null ? `CPU clock ${c.cpu_mhz} / ${c.cpu_max_mhz} MHz` : "",
    client.tempPeak ? `Peak since page opened: ${client.tempPeak.c} °C at ${new Date(client.tempPeak.t).toLocaleTimeString()}` : "",
  ].filter(Boolean).join("\n");
  return (
    <span title={title}>
      <StatusPill level={level} className={lv === "crit" && client.link === "live" ? "lost-pulse" : ""}>
        <span className="normal-case tracking-normal">
          NUC {Math.round(c.temp_max_c)} °C{client.throttlingNow ? " · throttling" : ""}
        </span>
      </StatusPill>
    </span>
  );
}

/** Hottest robot temperature source (motors / body), if the bridge has any configured. */
function RobotTempPill() {
  const { client } = useTelemetry();
  const rts = client.robotTemps.filter((r) => r.c != null);
  if (!rts.length) return null;
  // Show the most serious source (each has its own thresholds), hottest as tie-breaker.
  const rank = (n: string) => ({ crit: 3, warn: 2, ok: 1, unknown: 0 })[client.robotTempLevel(n)];
  const hottest = rts.reduce((a, b) => (rank(b.name) > rank(a.name) || (rank(b.name) === rank(a.name) && (b.c ?? -1e9) > (a.c ?? -1e9)) ? b : a));
  const lv = client.robotTempLevel(hottest.name);
  const level: Level = client.link !== "live" ? "idle" : lv === "crit" ? "crit" : lv === "warn" ? "warn" : "good";
  return (
    <span title={rts.map((r) => `${r.label}: ${r.c} °C (warn ${r.warn ?? "—"}, critical ${r.crit ?? "—"})`).join("\n")}>
      <StatusPill level={level} className={lv === "crit" && client.link === "live" ? "lost-pulse" : ""}>
        <span className="normal-case tracking-normal">Robot {Math.round(hottest.c ?? 0)} °C{rts.length > 1 ? ` (${hottest.label.replace(" (sim)", "")})` : ""}</span>
      </StatusPill>
    </span>
  );
}
