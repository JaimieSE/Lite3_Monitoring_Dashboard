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

test("link delay summary ignores failed probes", () => {
  const samples = [10, 20, 30, null, 1000].map((v, i) => s(i * 1000, { link_rtt_ms: v }));
  const sum = summarize(samples, []);
  assert.deepEqual(sum.link_rtt_ms, { median: 30, p95: 1000, max: 1000 });
  assert.equal(summarize([s(0)], []).link_rtt_ms, null);
});

test("nuc temperature summary: max and time at/above 80 °C", () => {
  const samples = [60, 82, 85, 79, 90].map((v, i) => s(i * 1000, { nuc_temp_c: v }));
  const sum = summarize(samples, []);
  assert.deepEqual(sum.nuc_temp, { max_c: 90, hot_s: 3 });
  assert.equal(summarize([s(0)], []).nuc_temp, null);
  assert.ok(samplesToCsv(samples).split("\n")[0].includes("nuc_temp_c"));
});

import { tempLevelWithHysteresis } from "../src/lib/thermal.ts";

test("temperature level has 3 °C hysteresis so readings near a threshold do not flap", () => {
  assert.equal(tempLevelWithHysteresis(91, 80, 90, "warn"), "crit");
  assert.equal(tempLevelWithHysteresis(88, 80, 90, "crit"), "crit"); // stays critical until < 87
  assert.equal(tempLevelWithHysteresis(86.9, 80, 90, "crit"), "warn");
  assert.equal(tempLevelWithHysteresis(78, 80, 90, "warn"), "warn"); // stays hot until < 77
  assert.equal(tempLevelWithHysteresis(76, 80, 90, "warn"), "ok");
  assert.equal(tempLevelWithHysteresis(79, 80, 90, "ok"), "ok");
  assert.equal(tempLevelWithHysteresis(null, 80, 90, "ok"), "unknown");
});
