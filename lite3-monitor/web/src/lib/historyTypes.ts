// Monitoring-session schema stored as JSON files on the Mac (data/history/*.json).

export interface Sample {
  t: number; // epoch ms (browser clock)
  link: "live" | "stale" | "lost" | "connecting";
  pose_valid: boolean;
  x: number | null;
  y: number | null;
  yaw: number | null;
  frame: string | null;
  speed: number | null;
  linear: number | null;
  angular: number | null;
  cmd_linear: number | null;
  state: string | null;
  frontiers: number | null;
  distance_m: number | null;
  known_area_m2: number | null;
  coverage_pct: number | null;
  rates: Record<string, number | null>;
}

export type EventLevel = "info" | "warn" | "error";

export interface SessionEvent {
  t: number;
  level: EventLevel;
  kind: string;
  message: string;
}

export interface RateSummary {
  min: number;
  avg: number;
  max: number;
  n: number;
}

export interface SessionSummary {
  duration_s: number;
  samples: number;
  distance_m: number;
  max_speed: number;
  avg_moving_speed: number;
  final_known_area_m2: number | null;
  final_coverage_pct: number | null;
  final_frontiers: number | null;
  link_lost_count: number;
  link_lost_s: number;
  stall_events: number;
  error_events: number;
  warn_events: number;
  topic_rates: Record<string, RateSummary>;
}

export interface SessionMeta {
  id: string;
  label: string;
  notes: string;
  mode: "sim" | "ros" | "unknown";
  robot: { hostname: string | null; robot_name: string | null; ros_domain_id: number | null };
  started_at: number;
  ended_at: number | null;
  updated_at: number;
  summary: SessionSummary;
}

export interface Session extends SessionMeta {
  version: 1;
  samples: Sample[];
  events: SessionEvent[];
}

export const MAX_SAMPLES = 4 * 3600; // 4 h at 1 Hz
export const MAX_EVENTS = 2000;
export const SESSION_ID_RE = /^[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$/;
