// Wire protocol v1 - mirrors bridge/lite3_bridge (see docs/PROTOCOL.md).
// The bridge only ever sends these; the dashboard never sends anything back.

export interface Identity {
  robot_name: string;
  hostname: string;
  machine_fingerprint: string;
  ros_domain_id: number | null;
  ros_domain_id_explicit: boolean;
  rmw_implementation: string;
  ros_localhost_only: boolean;
  expected_hostname: string | null;
  expected_ros_domain_id: number | null;
  verified: boolean;
  warnings: string[];
}

export interface HelloMsg {
  type: "hello";
  protocol: number;
  bridge_version: string;
  stream: "main" | "map";
  layers: { map: { enabled: boolean } };
  mode: "sim" | "ros";
  read_only: boolean;
  identity: Identity;
  frames: { map: string; odom: string; base: string[] };
  rates: Record<string, number>;
  staleness: { pose_stale_s: number; tf_stale_s: number; map_stale_s: number };
  arena_area_m2: number | null;
  server_time: number;
}

export interface Pose {
  x: number;
  y: number;
  yaw: number;
  frame: string;
  source: "tf" | "odometry";
  age_s: number;
  valid: boolean;
  map_frame: boolean;
}

export interface Velocity {
  linear: number | null;
  lateral: number | null;
  angular: number | null;
  speed: number | null;
  age_s: number;
  valid: boolean;
  source: "odometry" | "estimated";
}

export interface TfEdgeInfo {
  parent: string;
  child: string;
  static: boolean;
  age_s: number | null;
}

export interface Exploration {
  state: string;
  state_source: "topic" | "inferred";
  frontier_count: number | null;
  distance_travelled_m: number | null;
  runtime_s: number | null;
  stationary_s: number | null;
  stalled: boolean;
  stalled_for_s: number | null;
  stall_events: number;
  moving: boolean;
  /** Sudden jumps of the position estimate (localisation / TF), excluded from distance. */
  pose_jumps?: number;
  last_jump?: { distance_m: number; age_s: number; from: [number, number]; to: [number, number] } | null;
}

export interface NavInfo {
  status: string | null;
  status_age_s: number | null;
  goal: { x: number; y: number; yaw: number; frame: string; age_s: number } | null;
  distance_to_goal_m: number | null;
  global_path_length_m: number | null;
}

export interface TelemetryMsg {
  type: "telemetry";
  seq: number;
  server_time: number;
  uptime_s: number;
  pose: Pose | null;
  velocity: Velocity | null;
  cmd_vel: { linear: number | null; angular: number | null; age_s: number | null } | null;
  nav: NavInfo;
  exploration: Exploration;
  tf: {
    base_frame: string | null;
    chain: TfEdgeInfo[];
    errors: string[];
    ok: boolean;
    /** false = robot without dynamic TF; pose comes from odometry by design. */
    required?: boolean;
    /** informational messages when TF is not required */
    notes?: string[];
  };
}

export type TopicStatus = "ok" | "warn" | "error" | "missing" | "idle";

export interface TopicHealth {
  role: string;
  name: string;
  type: string | null;
  decoded: boolean;
  expected_hz: number | null;
  min_hz: number | null;
  rate_hz: number | null;
  age_s: number | null;
  total: number;
  publishers: number;
  publisher_nodes: string[];
  status: TopicStatus;
  note: string;
  /** For role "status_flag": last std_msgs/Bool value from the robot (null = none yet). */
  value?: boolean | null;
  /** Display label for status flags, e.g. "IMU". */
  label?: string | null;
  /** Serialized data received per second (null = size unknown / not measured). */
  bytes_per_s?: number | null;
  /** For role "temperature": latest robot temperature (°C) and thresholds. */
  temp_c?: number | null;
  temp_warn_c?: number | null;
  temp_crit_c?: number | null;
}

/** CPU / memory of the machine running the bridge (the NUC), grouped by component. */
export interface ComputeStats {
  simulated: boolean;
  error?: string;
  cores: number;
  cpu_total_pct: number | null; // % of the whole machine (all cores)
  load1: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  temps: { label: string; c: number }[];
  temp_max_c: number | null;
  temp_warn_c?: number;
  temp_crit_c?: number;
  cpu_mhz?: number | null; // current average CPU clock
  cpu_max_mhz?: number | null;
  throttle_count?: number | null; // cumulative thermal-throttle events (null = not exposed)
  disk_free_gb: number | null;
  components: { name: string; cpu_pct: number; rss_mb: number; processes: number }[]; // cpu_pct = % of ONE core
  top: { name: string; component: string; cpu_pct: number; rss_mb: number }[];
}

export interface DiagnosticItem {
  name: string;
  level: number;
  message: string;
}

export interface HealthMsg {
  type: "health";
  seq: number;
  server_time: number;
  topics: TopicHealth[];
  roles: Record<string, string | null>;
  missing_roles: string[];
  nodes: { count: number; names: string[]; missing_expected: string[]; scan_age_s: number | null };
  diagnostics: { ok: number; warn: number; error: number; stale: number; items: DiagnosticItem[]; age_s: number } | null;
  map: {
    version: number;
    age_s: number;
    stale: boolean;
    width: number;
    height: number;
    resolution: number;
    stats: MapStats | null; // reported even when the map stream is off
  } | null;
  source: { ok: boolean; message: string };
  compute?: ComputeStats | null;
  bridge: {
    clients: number;
    map_clients: number;
    map_stream_enabled: boolean;
    dropped_frames: number;
    uptime_s: number;
    tf_dropped: number;
    mode: string;
    map_bytes: number;
  };
}

export interface PathData {
  frame: string;
  points: [number, number][];
  age_s: number;
  length_m: number | null;
}

export interface PathsMsg {
  type: "paths";
  seq: number;
  server_time: number;
  global: PathData | null;
  local: PathData | null;
  frontiers: { count: number; points: [number, number][]; frame: string; age_s: number } | null;
  /** null entries are breaks (pose jumps): never draw a line across them. */
  trail: { frame: string | null; points: ([number, number] | null)[] };
}

export interface MapStats {
  total_cells: number;
  free_cells: number;
  occupied_cells: number;
  unknown_cells: number;
  known_area_m2: number;
  free_area_m2: number;
  known_fraction: number;
  coverage_pct: number | null;
}

export interface MapMsg {
  type: "map";
  version: number;
  server_time: number;
  frame: string;
  resolution: number;
  width: number;
  height: number;
  full_width: number;
  full_height: number;
  origin: { x: number; y: number; yaw: number };
  encoding: "zlib+base64";
  data: string;
  stats: MapStats;
  bytes_compressed: number;
}

export type BridgeMsg = HelloMsg | TelemetryMsg | HealthMsg | PathsMsg | MapMsg;

/** A decoded occupancy grid ready for rendering. */
export interface DecodedMap {
  version: number;
  frame: string;
  resolution: number;
  width: number;
  height: number;
  origin: { x: number; y: number; yaw: number };
  cells: Uint8Array; // 255 unknown, 0 free, 1..100 occupancy
  stats: MapStats;
  receivedAt: number;
}

export type LinkState = "connecting" | "live" | "stale" | "lost";

/** Link-delay measurement (round trip through Wi-Fi + SSH tunnel). */
export interface LinkStats {
  rttMs: number | null; // median of recent probes
  rttLastMs: number | null;
  transitMs: number | null; // estimated one-way bridge -> browser delay for telemetry
  clockOffsetMs: number | null; // bridge clock - browser clock
  probeFailures: number; // consecutive
  kbpsMain: number; // received kB/s on the telemetry stream
  kbpsMap: number; // received kB/s on the map stream
}

export interface DashboardConfig {
  bridgeUrl: string;
  expectedHostname: string | null;
  expectedDomainId: number | null;
}
