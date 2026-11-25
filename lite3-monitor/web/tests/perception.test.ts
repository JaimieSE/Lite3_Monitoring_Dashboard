import { test } from "node:test";
import assert from "node:assert/strict";
import { latestPerTask, reportOutcome, sceneImageUrl, scoreTotal } from "../src/lib/perception.ts";
import type { MissionReport } from "../src/lib/types.ts";

function r(task_id: string, over: Partial<MissionReport> = {}): MissionReport {
  return {
    t: 1, task_id, task_type: "object", scene_type: "kitchen", label: "", pos: [0, 0], message: "", http_status: 200,
    dry_run: false, accepted: true, score: 5, max_score: 10, evaluation: { scene_type: true }, reason: null, course: "B",
    ...over,
  };
}

test("scene image url goes to the bridge over http and encodes the request", () => {
  assert.equal(
    sceneImageUrl("ws://127.0.0.1:8765/ws", { request_id: "scene-3", capture_stamp_ns: 1795622251411856000 }),
    "http://127.0.0.1:8765/api/pi/scene_image?request_id=scene-3&stamp=1795622251411856000",
  );
  assert.equal(sceneImageUrl("", { request_id: "scene-3", capture_stamp_ns: 1 }), null);
  assert.equal(sceneImageUrl("ws://127.0.0.1:8765/ws", { request_id: "scene-3", capture_stamp_ns: null }), null);
});

test("only the latest report per task counts toward the total", () => {
  const reports = [r("M02", { score: 0 }), r("M04", { score: 5, max_score: 5 }), r("M02", { score: 5 }),
    r("M01", { dry_run: true, http_status: null, score: null, max_score: null })];
  assert.deepEqual(latestPerTask(reports).map((x) => [x.task_id, x.score]), [["M01", null], ["M02", 5], ["M04", 5]]);
  assert.deepEqual(scoreTotal(reports), { score: 10, max: 15, scored: 2 });
  assert.equal(reportOutcome(reports[3]), "dry run");
  assert.equal(reportOutcome(r("M03", { accepted: false })), "rejected");
  assert.equal(reportOutcome(r("M03", { accepted: false, http_status: null })), "no answer");
});
