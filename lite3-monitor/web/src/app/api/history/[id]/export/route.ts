import { loadSession } from "@/lib/historyStore";
import { SESSION_ID_RE } from "@/lib/historyTypes";
import { eventsToCsv, samplesToCsv } from "@/lib/summary";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** GET /api/history/:id/export?format=json|csv&what=samples|events */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!SESSION_ID_RE.test(id)) return new Response("invalid id", { status: 400 });
  const s = await loadSession(id);
  if (!s) return new Response("not found", { status: 404 });
  const url = new URL(req.url);
  const format = url.searchParams.get("format") === "csv" ? "csv" : "json";
  const what = url.searchParams.get("what") === "events" ? "events" : "samples";
  if (format === "json") {
    return new Response(JSON.stringify(s, null, 2), {
      headers: {
        "content-type": "application/json",
        "content-disposition": `attachment; filename="lite3-session-${id}.json"`,
      },
    });
  }
  const body = what === "events" ? eventsToCsv(s.events) : samplesToCsv(s.samples);
  return new Response(body, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="lite3-session-${id}-${what}.csv"`,
    },
  });
}
