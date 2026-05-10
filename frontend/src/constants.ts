export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
export const EARTH_RADIUS_KM = 6371;

export const PRESETS = [
  { label: "Custom", lat: 28.573, lon: -80.649, alt: 400, inc: 51.6 },
  { label: "ISS Resupply (Cape Canaveral)", lat: 28.573, lon: -80.649, alt: 420, inc: 51.6 },
  { label: "Starlink Deploy (Cape Canaveral)", lat: 28.573, lon: -80.649, alt: 550, inc: 53.0 },
  { label: "Sun-Sync SSO (Vandenberg)", lat: 34.632, lon: -120.611, alt: 705, inc: 98.2 },
  { label: "Polar Orbit (Vandenberg)", lat: 34.632, lon: -120.611, alt: 800, inc: 90.0 },
  { label: "GEO Transfer (Kourou)", lat: 5.236, lon: -52.768, alt: 35786, inc: 6.0 },
];
