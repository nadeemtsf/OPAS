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
}
