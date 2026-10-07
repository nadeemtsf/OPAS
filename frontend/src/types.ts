export interface Debris {
  name: string;
  norad_id: number;
  altitude_km: number;
  location: { type: string; coordinates: [number, number] };
}

export interface Threat extends Debris {
  distance_km: number;
  altitude_diff_km?: number;
  closest_approach_time?: string;
  approach_location?: { lat: number; lon: number };
  tle_age_days?: number;
  severity?: string;
  collision_probability?: number;
  threat_level?: string;
  position_uncertainty_km?: number;
}

export interface GlobePoint {
  lat: number;
  lng: number;
  alt: number;
  color: string;
  label: string;
  radius: number;
  opacity?: number;
}

export interface TrajectoryPoint {
  lat: number;
  lng: number;
  alt: number;
}

export interface DebrisInstance {
  lat: number;
  lng: number;
  alt: number;
  name: string;
  norad_id: number;
  altitude_km: number;
}

export interface HoveredDebris {
  x: number;
  y: number;
  data: DebrisInstance;
}

export interface SafeWindow {
  start: string;
  end: string;
  duration_minutes: number;
  verification?: {
    status: "passed";
    checked_launches: number;
    max_launch_gap_seconds: number;
    unsafe_launches: number;
    duration_seconds: number;
    endpoints_checked: boolean;
    horizon_checked: boolean;
    duration_checked: boolean;
    coverage_checked: boolean;
  };
}

export interface WindowDiagnostics {
  evidence?: { inputs_sha256_uncompressed: string; inputs_url: string;
    checks_url: string; result_url: string };
  request_id: string;
  status: "running" | "complete" | "incomplete";
  phase: string;
  elapsed_seconds: number;
  phase_completed?: number;
  phase_total?: number;
  candidates_checked?: number;
  checked_launch_samples?: number;
  clear_launch_samples?: number;
  obstructed_launch_samples?: number;
  candidate_spans?: number;
  qualifying_spans?: number;
  near_qualifying_spans?: number;
  returned_windows?: number;
  extra_validation_checks?: number;
  validation_obstructed_samples?: number;
  verification_step_seconds?: number;
  radius_min_km?: number | null;
  radius_max_km?: number | null;
  flight_start_seconds?: number;
  flight_end_seconds?: number;
  search_start_utc?: string;
  search_end_utc?: string;
  scope?: string;
}

export interface WindowSearchResponse {
  search_hours: number;
  candidates_checked: number;
  windows: SafeWindow[];
  diagnostics: WindowDiagnostics;
}
