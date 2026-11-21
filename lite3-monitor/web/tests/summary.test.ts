import { test } from "node:test";
import assert from "node:assert/strict";
import { samplesToCsv, summarize } from "../src/lib/summary.ts";
import type { Sample } from "../src/lib/historyTypes.ts";

function s(t: number, over: Partial<Sample> = {}): Sample {
  return {
    t, link: "live", pose_valid: true, x: 0, y: 0, yaw: 0, frame: "map", speed: 0.5, linear: 0.5, angular: 0,
    cmd_linear: 0.5, state: "MOVING", frontiers: 3, distance_m: t / 1000, known_area_m2: 10, coverage_pct: null,
    rates: { "/scan": 10 }, ...over,
  };
}

test("summary counts outages and ignores non-live speeds", () => {
  const samples = [s(0), s(1000), s(2000, { link: "lost", speed: 9 }), s(3000, { link: "lost", speed: 9 }), s(4000)];
  const sum = summarize(samples, [{ t: 0, level: "warn", kind: "stall", message: "x" }]);
  assert.equal(sum.duration_s, 4);
  assert.equal(sum.link_lost_count, 1);
  assert.equal(sum.link_lost_s, 2);
  assert.equal(sum.max_speed, 0.5);
  assert.equal(sum.stall_events, 1);
  assert.equal(sum.topic_rates["/scan"].avg, 10);
});

test("csv has header + one row per sample and escapes commas", () => {
  const csv = samplesToCsv([s(0, { state: "A,B" }), s(1000)]);
  const lines = csv.trim().split("\n");
  assert.equal(lines.length, 3);
  assert.ok(lines[0].includes("rate_hz:/scan"));
  assert.ok(lines[1].includes('"A,B"'));
});
