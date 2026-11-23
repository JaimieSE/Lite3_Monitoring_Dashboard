// Temperature threshold logic, shared by the live client and tests (no imports).

export type TempLevel = "unknown" | "ok" | "warn" | "crit";

export const HYSTERESIS_C = 3;
/** Threshold level with hysteresis: a level is only left once the value is 3 °C below it. */
export function tempLevelWithHysteresis(v: number | null, warn: number | null, crit: number | null, prev: TempLevel): TempLevel {
  if (v == null) return "unknown";
  if (crit != null && (v >= crit || (prev === "crit" && v >= crit - HYSTERESIS_C))) return "crit";
  if (warn != null && (v >= warn || ((prev === "warn" || prev === "crit") && v >= warn - HYSTERESIS_C))) return "warn";
  return "ok";
}
