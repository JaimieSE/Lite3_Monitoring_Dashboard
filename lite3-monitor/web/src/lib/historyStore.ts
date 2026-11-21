// Server-only: JSON-file storage for monitoring sessions on this Mac.
import { promises as fs } from "node:fs";
import path from "node:path";
import { MAX_EVENTS, MAX_SAMPLES, SESSION_ID_RE, type Session, type SessionMeta } from "./historyTypes";
import { summarize } from "./summary";

export function historyDir(): string {
  return process.env.LITE3_HISTORY_DIR || path.join(process.cwd(), "data", "history");
}

function fileFor(id: string): string {
  if (!SESSION_ID_RE.test(id)) throw new Error("invalid session id");
  return path.join(historyDir(), `${id}.json`);
}

export function validateSession(body: unknown): Session {
  const s = body as Session;
  if (!s || typeof s !== "object") throw new Error("body must be an object");
  if (typeof s.id !== "string" || !SESSION_ID_RE.test(s.id)) throw new Error("invalid id");
  if (!Array.isArray(s.samples) || !Array.isArray(s.events)) throw new Error("samples/events must be arrays");
  if (s.samples.length > MAX_SAMPLES || s.events.length > MAX_EVENTS) throw new Error("session too large");
  if (typeof s.started_at !== "number") throw new Error("started_at required");
  return {
    version: 1,
    id: s.id,
    label: String(s.label ?? "").slice(0, 120),
    notes: String(s.notes ?? "").slice(0, 4000),
    mode: s.mode === "sim" || s.mode === "ros" ? s.mode : "unknown",
    robot: {
      hostname: s.robot?.hostname ?? null,
      robot_name: s.robot?.robot_name ?? null,
      ros_domain_id: s.robot?.ros_domain_id ?? null,
    },
    started_at: s.started_at,
    ended_at: typeof s.ended_at === "number" ? s.ended_at : null,
    updated_at: Date.now(),
    samples: s.samples,
    events: s.events,
    summary: summarize(s.samples, s.events), // recomputed server-side
  };
}

export async function saveSession(s: Session): Promise<void> {
  await fs.mkdir(historyDir(), { recursive: true });
  const file = fileFor(s.id);
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(s));
  await fs.rename(tmp, file); // atomic replace
}

export async function loadSession(id: string): Promise<Session | null> {
  try {
    return JSON.parse(await fs.readFile(fileFor(id), "utf8")) as Session;
  } catch {
    return null;
  }
}

export async function deleteSession(id: string): Promise<boolean> {
  try {
    await fs.unlink(fileFor(id));
    return true;
  } catch {
    return false;
  }
}

export async function listSessions(): Promise<SessionMeta[]> {
  let names: string[] = [];
  try {
    names = (await fs.readdir(historyDir())).filter((n) => n.endsWith(".json"));
  } catch {
    return [];
  }
  const out: SessionMeta[] = [];
  for (const n of names) {
    const id = n.slice(0, -5);
    if (!SESSION_ID_RE.test(id)) continue;
    const s = await loadSession(id);
    if (!s) continue;
    const { samples: _s, events: _e, ...meta } = s;
    out.push(meta);
  }
  return out.sort((a, b) => b.started_at - a.started_at);
}
