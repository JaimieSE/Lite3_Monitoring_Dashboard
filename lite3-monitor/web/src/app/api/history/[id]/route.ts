import { NextResponse } from "next/server";
import { deleteSession, loadSession, saveSession } from "@/lib/historyStore";
import { SESSION_ID_RE } from "@/lib/historyTypes";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: Request, { params }: Params) {
  const { id } = await params;
  if (!SESSION_ID_RE.test(id)) return NextResponse.json({ error: "invalid id" }, { status: 400 });
  const s = await loadSession(id);
  return s ? NextResponse.json(s) : NextResponse.json({ error: "not found" }, { status: 404 });
}

/** Edit label / notes only. */
export async function PATCH(req: Request, { params }: Params) {
  const { id } = await params;
  if (!SESSION_ID_RE.test(id)) return NextResponse.json({ error: "invalid id" }, { status: 400 });
  const s = await loadSession(id);
  if (!s) return NextResponse.json({ error: "not found" }, { status: 404 });
  const body = (await req.json()) as { label?: string; notes?: string };
  if (typeof body.label === "string") s.label = body.label.slice(0, 120);
  if (typeof body.notes === "string") s.notes = body.notes.slice(0, 4000);
  await saveSession(s);
  return NextResponse.json({ ok: true });
}

export async function DELETE(_req: Request, { params }: Params) {
  const { id } = await params;
  if (!SESSION_ID_RE.test(id)) return NextResponse.json({ error: "invalid id" }, { status: 400 });
  return (await deleteSession(id)) ? NextResponse.json({ ok: true }) : NextResponse.json({ error: "not found" }, { status: 404 });
}
