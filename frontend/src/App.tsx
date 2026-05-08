import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import axios from "axios";
import Globe from "react-globe.gl";
import * as THREE from "three";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface Debris {
  name: string;
  norad_id: number;
  altitude_km: number;
  location: { type: string; coordinates: [number, number] };
}

interface Threat extends Debris {
  distance_meters: number;
  altitude_diff_km?: number;
  closest_approach_time?: string;
  approach_location?: { lat: number; lon: number };
  tle_age_days?: number;
  confidence?: string;
}

interface GlobePoint {
  lat: number;
  lng: number;
  alt: number;
  color: string;
  label: string;
  radius: number;
  opacity?: number;
}

interface TrajectoryPoint {
  lat: number;
  lng: number;
  alt: number;
}

const EARTH_RADIUS_KM = 6371;

const DEBRIS_GEO = new THREE.SphereGeometry(0.5, 6, 6);
const DEBRIS_MAT = new THREE.MeshBasicMaterial({
  color: 0x64b4ff,
  transparent: true,
  opacity: 0.7,
});

interface DebrisInstance {
  lat: number;
  lng: number;
  alt: number;
  name: string;
  norad_id: number;
  altitude_km: number;
}

interface HoveredDebris {
  x: number;
  y: number;
  data: DebrisInstance;
}

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
  const [selectedThreat, setSelectedThreat] = useState<number | null>(null);
  const [customData, setCustomData] = useState<GlobePoint[]>([]);
  const [trajectory, setTrajectory] = useState<TrajectoryPoint[]>([]);
  const [safeWindows, setSafeWindows] = useState<{ start: string; end: string; duration_minutes: number }[]>([]);
  const [findingWindows, setFindingWindows] = useState(false);
  const [windowSearchDone, setWindowSearchDone] = useState(false);
  const [windowSearchHours, setWindowSearchHours] = useState<number | null>(null);

  const debrisRef = useRef<DebrisInstance[]>([]);
  const instancedRef = useRef<THREE.InstancedMesh | null>(null);
  const [debrisReady, setDebrisReady] = useState(false);
  const [hoveredDebris, setHoveredDebris] = useState<HoveredDebris | null>(null);
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
    axios.get(`${API_BASE}/debris?limit=5000`).then(({ data }) => {
      debrisRef.current = data.debris.map((d: Debris) => ({
        lat: d.location.coordinates[1],
        lng: d.location.coordinates[0],
        alt: d.altitude_km / EARTH_RADIUS_KM,
        name: d.name,
        norad_id: d.norad_id,
        altitude_km: d.altitude_km,
      }));
      setDebrisReady(true);
      rebuildPoints([]);
    });
  }, []);

  useEffect(() => {
    if (!debrisReady || !globeRef.current) return;

    const globe = globeRef.current;
    const scene = globe.scene();

    if (instancedRef.current) {
      scene.remove(instancedRef.current);
      instancedRef.current.dispose();
    }

    const pts = debrisRef.current;
    if (pts.length === 0) return;

    const mesh = new THREE.InstancedMesh(DEBRIS_GEO, DEBRIS_MAT, pts.length);
    const dummy = new THREE.Object3D();

    for (let i = 0; i < pts.length; i++) {
      const coords = globe.getCoords(pts[i].lat, pts[i].lng, pts[i].alt);
      if (coords) {
        dummy.position.set(coords.x, coords.y, coords.z);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
    }
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
    instancedRef.current = mesh;

    return () => {
      if (instancedRef.current) {
        scene.remove(instancedRef.current);
      }
    };
  }, [debrisReady]);

  useEffect(() => {
    if (!debrisReady || !globeRef.current) return;

    const globe = globeRef.current;
    const renderer = globe.renderer();
    const camera = globe.camera();
    const canvas: HTMLCanvasElement = renderer.domElement;

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let rafId: number | null = null;
    let lastEvent: MouseEvent | null = null;

    function setAutoRotate(enabled: boolean) {
      const controls = globeRef.current?.controls?.();
      if (controls) controls.autoRotate = enabled;
    }

    function tick() {
      rafId = null;
      if (!lastEvent || !instancedRef.current) return;

      const rect = canvas.getBoundingClientRect();
      mouse.x = ((lastEvent.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((lastEvent.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObject(instancedRef.current);

      if (intersects.length > 0 && intersects[0].instanceId !== undefined) {
        const id = intersects[0].instanceId;
        const debris = debrisRef.current[id];
        if (debris) {
          setHoveredDebris({ x: lastEvent.clientX, y: lastEvent.clientY, data: debris });
          setAutoRotate(false);
          return;
        }
      }
      setHoveredDebris(null);
      setAutoRotate(true);
    }

    function onMouseMove(e: MouseEvent) {
      lastEvent = e;
      if (rafId === null) {
        rafId = requestAnimationFrame(tick);
      }
    }

    function onMouseLeave() {
      setHoveredDebris(null);
      setAutoRotate(true);
    }

    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseleave", onMouseLeave);

    return () => {
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mouseleave", onMouseLeave);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [debrisReady]);

  useEffect(() => {
    function enable() {
      const controls = globeRef.current?.controls?.();
      if (controls) {
        controls.autoRotate = true;
        controls.autoRotateSpeed = 0.25;
      }
    }
    enable();
    const timer = setTimeout(enable, 200);
    return () => clearTimeout(timer);
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
    setSelectedThreat(null);
  }

  function rebuildPoints(threatList: Threat[]) {
    const pts: GlobePoint[] = [];

    for (const t of threatList) {
      const threatLabel = `
        <div style="background: rgba(15,23,42,0.95); color: white; padding: 8px 12px; border-radius: 6px; font-size: 11px; line-height: 1.6; border: 1px solid rgba(239,68,68,0.5); font-family: ui-monospace, monospace; white-space: nowrap;">
          <div style="font-weight: 600; color: #fca5a5; margin-bottom: 4px;">⚠ ${t.name}</div>
          <div style="color: #9ca3af;">NORAD ${t.norad_id}</div>
          <div>Altitude: <span style="color: #fff;">${t.altitude_km.toFixed(1)} km</span></div>
          <div>Miss distance: <span style="color: #fca5a5;">${(t.distance_meters / 1000).toFixed(1)} km</span></div>
          ${t.confidence ? `<div>Confidence: <span style="color: ${t.confidence === "high" ? "#6ee7b7" : t.confidence === "medium" ? "#fde68a" : "#fca5a5"};">${t.confidence}</span></div>` : ""}
        </div>
      `;

      pts.push({
        lat: t.location.coordinates[1],
        lng: t.location.coordinates[0],
        alt: t.altitude_km / EARTH_RADIUS_KM,
        color: "#ef4444",
        label: threatLabel,
        radius: 0.6,
      });

      pts.push({
        lat: t.location.coordinates[1],
        lng: t.location.coordinates[0],
        alt: t.altitude_km / EARTH_RADIUS_KM,
        color: "#ef4444",
        label: threatLabel,
        radius: 2.0,
        opacity: 0.12,
      });
    }

    pts.push({
      lat: targetLat,
      lng: targetLon,
      alt: targetAlt / EARTH_RADIUS_KM,
      color: "#10b981",
      label: `
        <div style="background: rgba(15,23,42,0.95); color: white; padding: 8px 12px; border-radius: 6px; font-size: 11px; line-height: 1.6; border: 1px solid rgba(16,185,129,0.5); font-family: ui-monospace, monospace; white-space: nowrap;">
          <div style="font-weight: 600; color: #6ee7b7; margin-bottom: 4px;">▲ LAUNCH POINT</div>
          <div>Position: <span style="color: #fff;">${targetLat.toFixed(2)}°, ${targetLon.toFixed(2)}°</span></div>
          <div>Altitude: <span style="color: #fff;">${targetAlt} km</span></div>
        </div>
      `,
      radius: 0.8,
    });

    setCustomData(pts);
  }

  async function runCollisionCheck(effectiveTime: string) {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        target_lat: targetLat,
        target_lon: targetLon,
        target_alt: targetAlt,
        inclination,
        launch_time: new Date(effectiveTime).toISOString(),
      };
      const { data } = await axios.get(`${API_BASE}/alert`, { params });
      setStatus(data.status);
      setThreats(data.threats);
      setCheckedCount(data.candidates_checked ?? null);
      setTrajectory(data.trajectory ?? []);
      setSafeWindows([]);
      setWindowSearchDone(false);
      setSelectedThreat(null);
      rebuildPoints(data.threats);
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

  async function checkCollision() {
    let effectiveTime = launchTime;
    if (!effectiveTime) {
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      effectiveTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
      setLaunchTime(effectiveTime);
    }
    await runCollisionCheck(effectiveTime);
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
      const { data } = await axios.get(`${API_BASE}/safe-windows`, {
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
    runCollisionCheck(local);
  }

  function generateReport() {
    const lines = [
      "OPAS — COLLISION RISK REPORT",
      "=".repeat(50),
      `Generated: ${new Date().toUTCString()}`,
      `Status:    ${status?.toUpperCase()}${threats.length > 0 ? ` — ${threats.length} risk(s)` : ""}`,
      "",
      "MISSION PARAMETERS",
      "-".repeat(50),
      `Launch Site:      ${targetLat}°, ${targetLon}°`,
      `Target Altitude:  ${targetAlt} km`,
      `Inclination:      ${inclination}°`,
      `Launch Time:      ${launchTime ? new Date(launchTime).toUTCString() : "Not specified"}`,
      `Objects Checked:  ${checkedCount?.toLocaleString() ?? "N/A"}`,
      "",
      `COLLISION RISKS (${threats.length})`,
      "-".repeat(50),
    ];

    threats.forEach((t, i) => {
      lines.push("");
      lines.push(`[${i + 1}] ${t.name}`);
      lines.push(`    NORAD ID:          ${t.norad_id}`);
      lines.push(`    Miss Distance:     ${(t.distance_meters / 1000).toFixed(2)} km (${t.distance_meters.toFixed(0)} m)`);
      lines.push(`    Debris Altitude:   ${t.altitude_km.toFixed(1)} km${t.altitude_diff_km != null ? ` (Δ ${t.altitude_diff_km.toFixed(1)} km)` : ""}`);
      lines.push(`    Debris Position:   ${t.location.coordinates[1].toFixed(4)}°, ${t.location.coordinates[0].toFixed(4)}°`);
      if (t.closest_approach_time) {
        lines.push(`    Closest Approach:  ${new Date(t.closest_approach_time).toUTCString()}`);
      }
      if (t.approach_location) {
        lines.push(`    Approach Location: ${t.approach_location.lat.toFixed(4)}°, ${t.approach_location.lon.toFixed(4)}°`);
      }
    });

    lines.push("");
    lines.push("=".repeat(50));
    lines.push("Generated by OPAS (Orbital Proximity Alert System)");

    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `opas-report-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const pathsData = useMemo(
    () => (trajectory.length ? [{ points: trajectory }] : []),
    [trajectory],
  );

  const customThreeObject = useCallback((d: any) => {
    const geo = new THREE.SphereGeometry(d.radius, 8, 8);
    const mat = new THREE.MeshBasicMaterial({
      color: d.color,
      transparent: true,
      opacity: d.opacity ?? 1,
      depthWrite: (d.opacity ?? 1) > 0.5,
    });
    return new THREE.Mesh(geo, mat);
  }, []);

  const customThreeObjectUpdate = useCallback((obj: any, d: any) => {
    Object.assign(obj.position, globeRef.current?.getCoords(d.lat, d.lng, d.alt));
  }, []);

  const customLayerLabel = useCallback((d: any) => d.label, []);
  const pathColor = useCallback(() => "#10b981", []);

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
              {findingWindows ? "Scanning 24h..." : "Find A Safer Launch Window"}
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
                      {new Date(w.start).toLocaleString()}
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
            customThreeObject={customThreeObject}
            customThreeObjectUpdate={customThreeObjectUpdate}
            customLayerLabel={customLayerLabel}
            pathsData={pathsData}
            pathPoints="points"
            pathPointLat="lat"
            pathPointLng="lng"
            pathPointAlt="alt"
            pathColor={pathColor}
            pathDashLength={0.05}
            pathDashGap={0.008}
            pathDashAnimateTime={15000}
            pathStroke={2}
            animateIn={true}
          />
        </div>

        {/* Right sidebar — collision results */}
        {threats.length > 0 && (
          <div className="w-80 shrink-0 border-l border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Collision Risks ({threats.length})
              </h2>
              <button
                onClick={generateReport}
                className="text-[10px] text-blue-400 hover:text-blue-300 font-medium transition cursor-pointer"
              >
                Download Report
              </button>
            </div>
            <ul className="flex-1 overflow-y-auto">
              {threats.map((t) => (
                <li
                  key={t.norad_id}
                  onClick={() => setSelectedThreat(selectedThreat === t.norad_id ? null : t.norad_id)}
                  className={`px-5 py-3 border-b border-gray-800/40 cursor-pointer transition ${
                    selectedThreat === t.norad_id ? "bg-gray-800/70" : "hover:bg-gray-800/50"
                  }`}
                >
                  <p className="text-xs font-medium text-white">{t.name}</p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] text-gray-500">NORAD {t.norad_id}</span>
                    <span className="text-[10px] text-gray-500">{t.altitude_km.toFixed(1)} km</span>
                    <span className="text-[10px] text-red-400 font-medium">
                      {(t.distance_meters / 1000).toFixed(1)} km away
                    </span>
                  </div>

                  {t.confidence && (
                    <span className={`mt-1 inline-block text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                      t.confidence === "high" ? "bg-green-900/50 text-green-400" :
                      t.confidence === "medium" ? "bg-yellow-900/50 text-yellow-400" :
                      t.confidence === "low" ? "bg-orange-900/50 text-orange-400" :
                      "bg-red-900/50 text-red-400"
                    }`}>
                      {t.confidence} confidence
                      {t.tle_age_days != null && ` · ${t.tle_age_days}d old`}
                    </span>
                  )}

                  {selectedThreat === t.norad_id && (
                    <div className="mt-2 pt-2 border-t border-gray-700/50 space-y-2">
                      {t.closest_approach_time && (
                        <div>
                          <span className="text-[10px] text-gray-500">Closest Approach Time</span>
                          <p className="text-[11px] text-white">
                            {new Date(t.closest_approach_time).toLocaleString()}
                          </p>
                        </div>
                      )}
                      {t.approach_location && (
                        <div>
                          <span className="text-[10px] text-gray-500">Approach Location</span>
                          <p className="text-[11px] text-white">
                            {t.approach_location.lat.toFixed(4)}°, {t.approach_location.lon.toFixed(4)}°
                          </p>
                        </div>
                      )}
                      <div>
                        <span className="text-[10px] text-gray-500">Debris Position</span>
                        <p className="text-[11px] text-white">
                          {t.location.coordinates[1].toFixed(4)}°, {t.location.coordinates[0].toFixed(4)}°
                        </p>
                      </div>
                      <div className="flex gap-4">
                        <div>
                          <span className="text-[10px] text-gray-500">Miss Distance</span>
                          <p className="text-[11px] text-white">
                            {(t.distance_meters / 1000).toFixed(2)} km
                          </p>
                        </div>
                        {t.altitude_diff_km != null && (
                          <div>
                            <span className="text-[10px] text-gray-500">Altitude Δ</span>
                            <p className="text-[11px] text-white">{t.altitude_diff_km.toFixed(1)} km</p>
                          </div>
                        )}
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); focusThreat(t); }}
                        className="w-full mt-1 rounded bg-gray-700 hover:bg-gray-600 py-1.5 text-[10px] font-medium transition cursor-pointer"
                      >
                        Focus on Globe
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {hoveredDebris && (
        <div
          className="fixed pointer-events-none z-50"
          style={{ left: hoveredDebris.x + 12, top: hoveredDebris.y + 12 }}
        >
          <div className="bg-slate-900/95 text-white px-3 py-2 rounded-md text-[11px] leading-relaxed border border-blue-400/40 font-mono whitespace-nowrap shadow-lg">
            <div className="font-semibold text-blue-300 mb-1">{hoveredDebris.data.name}</div>
            <div className="text-gray-400">NORAD {hoveredDebris.data.norad_id}</div>
            <div>Altitude: <span className="text-white">{hoveredDebris.data.altitude_km.toFixed(1)} km</span></div>
            <div>Position: <span className="text-white">{hoveredDebris.data.lat.toFixed(2)}°, {hoveredDebris.data.lng.toFixed(2)}°</span></div>
          </div>
        </div>
      )}
    </div>
  );
}
