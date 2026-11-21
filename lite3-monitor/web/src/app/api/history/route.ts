import { NextResponse } from "next/server";
import { listSessions, saveSession, validateSession } from "@/lib/historyStore";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json(await listSessions());
}

/** Upsert a session recorded by this dashboard (local file storage only). */
export async function POST(req: Request) {
  try {
    const text = await req.text();
    if (text.length > 25 * 1024 * 1024) return NextResponse.json({ error: "too large" }, { status: 413 });
    const s = validateSession(JSON.parse(text));
    await saveSession(s);
    return NextResponse.json({ ok: true, id: s.id, summary: s.summary });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "invalid" }, { status: 400 });
  }
}
