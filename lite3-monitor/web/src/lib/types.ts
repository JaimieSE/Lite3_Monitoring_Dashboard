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
  attitude?: Attitude | null;
  joints?: { names: string[]; effort: (number | null)[]; velocity: (number | null)[]; age_s: number } | null;
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
  /** For role "range" (ultrasound etc.): distance in metres; lower is worse. */
  range_m?: number | null;
  range_warn_m?: number | null;
  range_crit_m?: number | null;
  range_max_m?: number | null;
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
  peers?: PeerStatus[];
  /** Raspberry Pi perception seen on ROS (detections, Claude scene checks); null when none yet. */
  perception?: PerceptionHealth | null;
  /** The robot's own mission-report log (newest run); null when not configured. */
  missions?: MissionsHealth | null;
  logs?: RobotLog[];
  logs_dropped?: number;
  inactive_roles?: string[];
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

/** A helper computer on the robot (e.g. the Raspberry Pi), checked from the NUC. */
export interface PeerStatus {
  name: string;
  host_label: string;
  online: boolean;
  rtt_ms: number | null;
  banner: string | null;
  error?: string | null;
  last_seen_age_s: number | null;
  stats_configured: boolean;
  stats: PeerStats | null;
  stats_error?: string | null;
  expected_hostname: string | null;
  identity_ok: boolean | null;
  temp_warn_c: number;
  temp_crit_c: number;
}

export interface PeerStats {
  hostname: string;
  model: string | null;
  uptime_s: number | null;
  throttled_raw: string | null;
  throttle: Record<string, boolean> | null;
  cpu_total_pct: number | null;
  load1: number | null;
  cores: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  temps: { label: string; c: number }[];
  temp_max_c: number | null;
  disk_free_gb: number | null;
  disk_total_gb: number | null;
  cpu_mhz: number | null;
  cpu_max_mhz: number | null;
  /** Network activity on the Pi (like ifconfig / ss); no message contents. */
  net?: {
    interfaces: { iface: string; rx_Bps: number; tx_Bps: number; rx_pps: number; tx_pps: number; rx_total_mb: number; tx_total_mb: number }[];
    connections: { proto: string; state: string; local_port: number; remote: string | null; remote_port: number | null; process: string | null; loopback: boolean; to_nuc: boolean }[];
  } | null;
}

export interface Attitude {
  roll_deg: number | null;
  pitch_deg: number | null;
  tilt_deg: number | null;
  acc_g: number | null;
  gyro_dps: number | null;
  source: string | null;
  age_s: number;
  valid: boolean;
  tilt_warn_deg: number;
  tilt_crit_deg: number;
}

/** One robot log line from /rosout. level: 10 debug, 20 info, 30 warn, 40 error, 50 fatal. */
export interface RobotLog {
  id: number;
  t: number;
  level: number;
  node: string;
  msg: string;
}

/** Latest detection record from the Pi (health.perception.latest). */
export interface PiDetections {
  frame: number | null;
  objects: { name: string; confidence: number }[];
  qr: string[];
  /** Identified hazard label, or null for an unidentified yellow triangle. */
  signs: (string | null)[];
  stair: { obstacle: string | null; reason: string | null; distance_m: number | null };
  age_s: number;
}

/** One Claude scene check made by the Pi (joined from scene_pending / scene_result / scene_failed). */
export interface SceneRequest {
  request_id: string;
  status: "pending" | "result" | "failed";
  trigger: { kind: string; label: string } | null;
  encounter_ids: string[];
  frame: number | null;
  capture_stamp_ns: number | null;
  room: string | null;
  evidence: string[];
  error: string | null;
  latency_s: number | null;
  /** Bridge wall-clock seconds when the bridge first saw the request. */
  requested_at: number;
  age_s: number;
}

export interface PerceptionHealth {
  latest: PiDetections | null;
  frames: number;
  events: number;
  bad_messages: number;
  /** Newest first. */
  requests: SceneRequest[];
}

/** One line of the robot's mission_reports.jsonl: what was POSTed and what the scoring server answered. */
export interface MissionReport {
  t: number | null;
  task_id: string;
  task_type: string;
  scene_type: string;
  label: string;
  pos: [number, number] | null;
  message: string;
  http_status: number | null;
  dry_run: boolean;
  accepted: boolean;
  score: number | null;
  max_score: number | null;
  evaluation: Record<string, boolean> | null;
  reason: string | null;
  course: string | null;
}

export interface MissionsHealth {
  run: string;
  file_mtime: number | null;
  reports: MissionReport[];
}
