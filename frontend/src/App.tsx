import { useState, useEffect, useRef } from "react";
import axios from "axios";
import Globe from "react-globe.gl";
import * as THREE from "three";

interface Debris {
  name: string;
  norad_id: number;
  altitude_km: number;
  location: { type: string; coordinates: [number, number] };
}

interface Threat extends Debris {
  distance_meters: number;
}

interface GlobePoint {
  lat: number;
  lng: number;
  alt: number;
  color: string;
  label: string;
  radius: number;
}

interface TrajectoryPoint {
  lat: number;
  lng: number;
  alt: number;
}

const EARTH_RADIUS_KM = 6371;

const PRESETS = [
  { label: "Custom", lat: 28.573, lon: -80.649, alt: 400, inc: 51.6 },
  { label: "ISS Resupply (Cape Canaveral)", lat: 28.573, lon: -80.649, alt: 420, inc: 51.6 },
  { label: "Starlink Deploy (Cape Canaveral)", lat: 28.573, lon: -80.649, alt: 550, inc: 53.0 },
  { label: "Sun-Sync SSO (Vandenberg)", lat: 34.632, lon: -120.611, alt: 705, inc: 98.2 },
  { label: "Polar Orbit (Vandenberg)", lat: 34.632, lon: -120.611, alt: 800, inc: 90.0 },
  { label: "GEO Transfer (Kourou)", lat: 5.236, lon: -52.768, alt: 35786, inc: 6.0 },
];

export default function App() {
  const [preset, setPreset] = useState(0);
  const [targetLat, setTargetLat] = useState(28.573);
  const [targetLon, setTargetLon] = useState(-80.649);
  const [targetAlt, setTargetAlt] = useState(400);
  const [inclination, setInclination] = useState(51.6);
  const [launchTime, setLaunchTime] = useState("");
  const [status, setStatus] = useState<"safe" | "danger" | null>(null);
  const [threats, setThreats] = useState<Threat[]>([]);
  const [checkedCount, setCheckedCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [customData, setCustomData] = useState<GlobePoint[]>([]);
  const [trajectory, setTrajectory] = useState<TrajectoryPoint[]>([]);
  const [safeWindows, setSafeWindows] = useState<{ start: string; end: string; duration_minutes: number }[]>([]);
  const [findingWindows, setFindingWindows] = useState(false);
  const [windowSearchDone, setWindowSearchDone] = useState(false);
  const [windowSearchHours, setWindowSearchHours] = useState<number | null>(null);

  const debrisRef = useRef<GlobePoint[]>([]);
  const globeRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [globeSize, setGlobeSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        setGlobeSize({ w: containerRef.current.clientWidth, h: containerRef.current.clientHeight });
      }
    }
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  useEffect(() => {
    axios.get("http://localhost:8000/debris?limit=5000").then(({ data }) => {
      const pts: GlobePoint[] = data.debris.map((d: Debris) => ({
        lat: d.location.coordinates[1],
        lng: d.location.coordinates[0],
        alt: d.altitude_km / EARTH_RADIUS_KM,
        color: "rgba(100,180,255,0.7)",
        label: `${d.name} — ${d.altitude_km} km`,
        radius: 0.5,
      }));
      debrisRef.current = pts;
      rebuildPoints(pts, []);
    });
  }, []);

  function applyPreset(index: number) {
    setPreset(index);
    const p = PRESETS[index];
    setTargetLat(p.lat);
    setTargetLon(p.lon);
    setTargetAlt(p.alt);
    setInclination(p.inc);
    setTrajectory([]);
    setStatus(null);
    setThreats([]);
    setCheckedCount(null);
    setSafeWindows([]);
    setWindowSearchDone(false);
    setWindowSearchHours(null);
  }

  function rebuildPoints(debris: GlobePoint[], threatList: Threat[]) {
    const pts: GlobePoint[] = [...debris];

    for (const t of threatList) {
      pts.push({
        lat: t.location.coordinates[1],
        lng: t.location.coordinates[0],
        alt: t.altitude_km / EARTH_RADIUS_KM,
        color: "#ef4444",
        label: `${t.name} (NORAD ${t.norad_id}) — ${t.altitude_km} km`,
        radius: 0.6,
      });
    }

    pts.push({
      lat: targetLat,
      lng: targetLon,
      alt: targetAlt / EARTH_RADIUS_KM,
      color: "#10b981",
      label: "LAUNCH POINT",
      radius: 0.8,
    });

    setCustomData(pts);
  }

  async function checkCollision() {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        target_lat: targetLat,
        target_lon: targetLon,
        target_alt: targetAlt,
        inclination,
      };
      if (launchTime) params.launch_time = new Date(launchTime).toISOString();

      const { data } = await axios.get("http://localhost:8000/alert", { params });
      setStatus(data.status);
      setThreats(data.threats);
      setCheckedCount(data.candidates_checked ?? null);
      setTrajectory(data.trajectory ?? []);
      setSafeWindows([]);
      rebuildPoints(debrisRef.current, data.threats);
      if (globeRef.current) {
        globeRef.current.pointOfView({ lat: targetLat, lng: targetLon, altitude: 2 }, 1000);
      }
    } catch (err) {
      console.error(err);
      setStatus(null);
      setThreats([]);
      setTrajectory([]);
    } finally {
      setLoading(false);
    }
  }

  function focusThreat(t: Threat) {
    if (globeRef.current) {
      globeRef.current.pointOfView(
        { lat: t.location.coordinates[1], lng: t.location.coordinates[0], altitude: 1 },
        800,
      );
    }
  }

  async function findSafeWindows() {
    setFindingWindows(true);
    setWindowSearchDone(false);
    setWindowSearchHours(null);
    try {
      const { data } = await axios.get("http://localhost:8000/safe-windows", {
        params: { target_lat: targetLat, target_lon: targetLon, target_alt: targetAlt, inclination },
      });
      setSafeWindows(data.windows);
      setWindowSearchHours(data.search_hours);
      setWindowSearchDone(true);
    } catch (err) {
      console.error(err);
      setSafeWindows([]);
      setWindowSearchDone(true);
    } finally {
      setFindingWindows(false);
    }
  }

  function applyWindow(iso: string) {
    const dt = new Date(iso);
    const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setLaunchTime(local);
    setSafeWindows([]);
    setStatus(null);
    setThreats([]);
  }

  const inputClass =
    "mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500";

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Top status bar */}
      <div className="h-12 shrink-0 bg-gray-900/95 border-b border-gray-800 px-5 flex items-center justify-between z-20">
        <div className="flex items-center gap-4">
          <h1 className="text-sm font-bold tracking-widest text-white">OPAS</h1>
          <span className="text-[10px] text-gray-500 uppercase tracking-widest hidden sm:inline">
            Orbital Proximity Alert System
          </span>
        </div>
        <div className="flex items-center gap-3">
          {status && (
            <div
              className={`px-3 py-1 rounded text-xs font-bold uppercase tracking-wider ${
                status === "safe"
                  ? "bg-green-900/60 text-green-400"
                  : "bg-red-900/60 text-red-400"
              }`}
            >
              {status}
              {threats.length > 0 && ` — ${threats.length} risk${threats.length > 1 ? "s" : ""}`}
            </div>
          )}
          {checkedCount !== null && (
            <span className="text-[10px] text-gray-500">
              {checkedCount.toLocaleString()} checked
            </span>
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar — inputs only */}
        <div className="w-72 shrink-0 flex flex-col p-5 border-r border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 overflow-y-auto">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
            Mission Parameters
          </h2>

          <div className="space-y-3">
            <div>
              <span className="text-xs text-gray-500">Mission Profile</span>
              <select
                value={preset}
                onChange={(e) => applyPreset(+e.target.value)}
                className={inputClass}
              >
                {PRESETS.map((p, i) => (
                  <option key={i} value={i}>{p.label}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-xs text-gray-500">Lat</span>
                <input type="number" step="0.01" value={targetLat}
                  onChange={(e) => { setTargetLat(+e.target.value); setPreset(0); }}
                  className={inputClass} />
              </div>
              <div>
                <span className="text-xs text-gray-500">Lon</span>
                <input type="number" step="0.01" value={targetLon}
                  onChange={(e) => { setTargetLon(+e.target.value); setPreset(0); }}
                  className={inputClass} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-xs text-gray-500">Altitude (km)</span>
                <input type="number" step="1" value={targetAlt}
                  onChange={(e) => { setTargetAlt(+e.target.value); setPreset(0); }}
                  className={inputClass} />
              </div>
              <div>
                <span className="text-xs text-gray-500">Inclination (°)</span>
                <input type="number" step="0.1" value={inclination}
                  onChange={(e) => { setInclination(+e.target.value); setPreset(0); }}
                  className={inputClass} />
              </div>
            </div>

            <div>
              <span className="text-xs text-gray-500">Launch Time (UTC)</span>
              <input type="datetime-local" value={launchTime}
                onChange={(e) => setLaunchTime(e.target.value)}
                className={`${inputClass} [color-scheme:dark]`} />
            </div>
          </div>

          <button
            onClick={checkCollision}
            disabled={loading}
            className="mt-5 w-full rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 py-2.5 text-sm font-semibold transition cursor-pointer"
          >
            {loading ? "Checking..." : "Check Collision Risk"}
          </button>

          {status === "danger" && (
            <button
              onClick={findSafeWindows}
              disabled={findingWindows}
              className="mt-2 w-full rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 py-2.5 text-sm font-semibold transition cursor-pointer"
            >
              {findingWindows ? "Scanning 24h..." : "Find Safe Launch Windows"}
            </button>
          )}

          {safeWindows.length > 0 && (
            <div className="mt-3">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Safe Windows {windowSearchHours && `(${windowSearchHours}h scan)`}
              </h3>
              <ul className="space-y-2">
                {safeWindows.map((w, i) => (
                  <li
                    key={i}
                    onClick={() => applyWindow(w.start)}
                    className="rounded bg-green-900/30 border border-green-800/40 p-3 cursor-pointer hover:bg-green-900/50 transition"
                  >
                    <p className="text-xs text-green-400 font-medium">
                      {new Date(w.start).toUTCString().slice(0, -4)} UTC
                    </p>
                    <p className="text-[10px] text-gray-400 mt-1">
                      {w.duration_minutes} min window
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {windowSearchDone && safeWindows.length === 0 && (
            <div className="mt-3 rounded bg-yellow-900/30 border border-yellow-800/40 p-3">
              <p className="text-xs text-yellow-400 font-medium">No safe windows found</p>
              <p className="text-[10px] text-gray-400 mt-1">
                Searched up to 72h with 50 km proximity threshold. Consider adjusting altitude or inclination.
              </p>
            </div>
          )}
        </div>

        {/* Globe */}
        <div ref={containerRef} className="flex-1 flex items-center justify-center overflow-hidden min-w-0">
          <Globe
            ref={globeRef}
            width={globeSize.w}
            height={globeSize.h}
            globeImageUrl="https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
            backgroundColor="rgba(0,0,0,0)"
            customLayerData={customData}
            customThreeObject={(d: any) => {
              const geo = new THREE.SphereGeometry(d.radius, 8, 8);
              const mat = new THREE.MeshBasicMaterial({
                color: d.color,
                transparent: true,
                opacity: d.color.includes("rgba") ? 0.7 : 1,
              });
              return new THREE.Mesh(geo, mat);
            }}
            customThreeObjectUpdate={(obj: any, d: any) => {
              Object.assign(obj.position, globeRef.current?.getCoords(d.lat, d.lng, d.alt));
            }}
            customLayerLabel={(d: any) => d.label}
            pathsData={trajectory.length ? [{ points: trajectory }] : []}
            pathPoints="points"
            pathPointLat="lat"
            pathPointLng="lng"
            pathPointAlt="alt"
            pathColor={() => "#10b981"}
            pathDashLength={0.05}
            pathDashGap={0.008}
            pathDashAnimateTime={15000}
            pathStroke={2}
            animateIn={true}
          />
        </div>

        {/* Right sidebar — collision results */}
        {threats.length > 0 && (
          <div className="w-72 shrink-0 border-l border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Collision Risks ({threats.length})
              </h2>
            </div>
            <ul className="flex-1 overflow-y-auto">
              {threats.map((t) => (
                <li
                  key={t.norad_id}
                  onClick={() => focusThreat(t)}
                  className="px-5 py-3 border-b border-gray-800/40 hover:bg-gray-800/50 cursor-pointer transition"
                >
                  <p className="text-xs font-medium text-white">{t.name}</p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] text-gray-500">NORAD {t.norad_id}</span>
                    <span className="text-[10px] text-gray-500">{t.altitude_km.toFixed(1)} km</span>
                    <span className="text-[10px] text-red-400 font-medium">
                      {(t.distance_meters / 1000).toFixed(1)} km away
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
