"use client";

import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { TelemetryClient } from "@/lib/client";
import { Recorder } from "@/lib/recorder";
import type { DashboardConfig } from "@/lib/types";

interface Ctx {
  client: TelemetryClient;
  recorder: Recorder;
  version: number;
  autoRecord: boolean;
  setAutoRecord: (v: boolean) => void;
  setMapEnabled: (v: boolean) => void;
}

const TelemetryContext = createContext<Ctx | null>(null);

const AUTO_KEY = "lite3.autoRecord";
const MAP_KEY = "lite3.mapStream";

function readMap(): boolean {
  try {
    return localStorage.getItem(MAP_KEY) !== "0";
  } catch {
    return true;
  }
}

function readAuto(): boolean {
  try {
    return localStorage.getItem(AUTO_KEY) !== "0";
  } catch {
    return true;
  }
}

export function TelemetryProvider({ children }: { children: React.ReactNode }) {
  const clientRef = useRef<TelemetryClient | null>(null);
  if (!clientRef.current) clientRef.current = new TelemetryClient();
  const client = clientRef.current;

  const [recVersion, setRecVersion] = useState(0);
  const recorderRef = useRef<Recorder | null>(null);
  if (!recorderRef.current) recorderRef.current = new Recorder(client, () => setRecVersion((v) => v + 1));
  const recorder = recorderRef.current;

  const [autoRecord, setAutoRecordState] = useState(true);
  useEffect(() => setAutoRecordState(readAuto()), []);
  const setAutoRecord = (v: boolean) => {
    setAutoRecordState(v);
    try {
      localStorage.setItem(AUTO_KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  /** Map stream on/off: remembered per browser. Off closes the map socket entirely. */
  const setMapEnabled = (v: boolean) => {
    client.setMapEnabled(v);
    try {
      localStorage.setItem(MAP_KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  const version = useSyncExternalStore(client.subscribe, client.getVersion, () => 0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let cfg: DashboardConfig = { bridgeUrl: "ws://127.0.0.1:8765/ws", expectedHostname: null, expectedDomainId: null };
      try {
        const r = await fetch("/api/config", { cache: "no-store" });
        if (r.ok) cfg = await r.json();
      } catch {
        /* fall back to defaults */
      }
      if (!cancelled) client.start(cfg, readMap());
    })();
    const unload = () => recorder.flushOnUnload();
    window.addEventListener("beforeunload", unload);
    window.addEventListener("pagehide", unload);
    return () => {
      cancelled = true;
      window.removeEventListener("beforeunload", unload);
      window.removeEventListener("pagehide", unload);
      client.stop();
    };
  }, [client, recorder]);

  // Auto-start a recording when live telemetry first arrives from a verified source.
  useEffect(() => {
    // Only once per page load: after a manual Stop, the user decides when to record again.
    if (autoRecord && recorder.session === null && client.link === "live" && !client.identityProblem && client.hello) {
      recorder.start();
    }
  }, [version, autoRecord, client, recorder]);

  return (
    <TelemetryContext.Provider value={{ client, recorder, version: version + recVersion * 1e6, autoRecord, setAutoRecord, setMapEnabled }}>
      {children}
    </TelemetryContext.Provider>
  );
}

export function useTelemetry(): Ctx {
  const c = useContext(TelemetryContext);
  if (!c) throw new Error("useTelemetry outside TelemetryProvider");
  return c;
}
