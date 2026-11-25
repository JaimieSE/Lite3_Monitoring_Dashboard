import type { MissionReport, SceneRequest } from "./types.ts";

/** URL of the stored picture Claude was shown, relayed read-only by the bridge from the Pi. */
export function sceneImageUrl(bridgeUrl: string, req: Pick<SceneRequest, "request_id" | "capture_stamp_ns">): string | null {
  if (!bridgeUrl || req.capture_stamp_ns == null) return null;
  try {
    const u = new URL(bridgeUrl);
    u.protocol = u.protocol === "wss:" ? "https:" : "http:";
    u.pathname = "/api/pi/scene_image";
    u.search = new URLSearchParams({ request_id: req.request_id, stamp: String(req.capture_stamp_ns) }).toString();
    return u.toString();
  } catch {
    return null;
  }
}

/** The scoring server keeps only the latest submission per task: newest report per task, in task order. */
export function latestPerTask(reports: MissionReport[]): MissionReport[] {
  const byTask = new Map<string, MissionReport>();
  for (const r of reports) byTask.set(r.task_id, r);
  return [...byTask.values()].sort((a, b) => a.task_id.localeCompare(b.task_id));
}

/** Sum of the latest scores the server returned (practice server only; competition may not return scores). */
export function scoreTotal(reports: MissionReport[]): { score: number; max: number; scored: number } {
  let score = 0, max = 0, scored = 0;
  for (const r of latestPerTask(reports)) {
    if (r.score != null && r.max_score != null) {
      score += r.score;
      max += r.max_score;
      scored += 1;
    }
  }
  return { score, max, scored };
}

export function reportOutcome(r: MissionReport): "dry run" | "accepted" | "rejected" | "no answer" {
  if (r.dry_run) return "dry run";
  if (r.accepted) return "accepted";
  return r.http_status == null ? "no answer" : "rejected";
}
