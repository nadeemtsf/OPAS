import { useState, useRef, useCallback, useMemo } from "react";
import axios from "axios";
import Globe from "react-globe.gl";
import * as THREE from "three";

import type { Threat, GlobePoint, TrajectoryPoint, SafeWindow, GlobeInstance } from "./types";
import { API_BASE, EARTH_RADIUS_KM, PRESETS } from "./constants";
import { generateReport } from "./utils/reportGenerator";
import { useGlobeSize } from "./hooks/useGlobeSize";
import { useGlobeDebris } from "./hooks/useGlobeDebris";
import { StatusBar } from "./components/StatusBar";
import { LeftSidebar } from "./components/LeftSidebar";
import { RightSidebar } from "./components/RightSidebar";
import { DebrisTooltip } from "./components/DebrisTooltip";

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
  const [safeWindows, setSafeWindows] = useState<SafeWindow[]>([]);
  const [findingWindows, setFindingWindows] = useState(false);
  const [windowSearchDone, setWindowSearchDone] = useState(false);
  const [windowSearchHours, setWindowSearchHours] = useState<number | null>(null);
  const [searchHoursInput, setSearchHoursInput] = useState(24);
  const [windowElapsed, setWindowElapsed] = useState<number | null>(null);

  const globeRef = useRef<GlobeInstance>(undefined);
  const { containerRef, globeSize } = useGlobeSize();
  const { hoveredDebris } = useGlobeDebris(globeRef);

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
          <div>Miss distance: <span style="color: #fca5a5;">${t.distance_km.toFixed(1)} km</span></div>
          ${t.severity ? `<div>Severity: <span style="color: ${t.severity === "CRITICAL" ? "#fca5a5" : t.severity === "HIGH" ? "#fdba74" : t.severity === "MODERATE" ? "#fde68a" : "#6ee7b7"};">${t.severity}</span></div>` : ""}
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
      const params: Record<string, string | number> = {
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
    setWindowElapsed(null);
    const t0 = performance.now();
    try {
      const { data } = await axios.get(`${API_BASE}/safe-windows`, {
        params: { target_lat: targetLat, target_lon: targetLon, target_alt: targetAlt, inclination, search_hours: searchHoursInput },
      });
      setSafeWindows(data.windows);
      setWindowSearchHours(data.search_hours);
      setWindowSearchDone(true);
    } catch (err) {
      console.error(err);
      setSafeWindows([]);
      setWindowSearchDone(true);
    } finally {
      setWindowElapsed(Math.round((performance.now() - t0) / 1000));
      setFindingWindows(false);
    }
  }

  function applyWindow(iso: string) {
    const dt = new Date(iso);
    const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setLaunchTime(local);
    runCollisionCheck(local);
  }

  function handleGenerateReport() {
    generateReport({ status, threats, targetLat, targetLon, targetAlt, inclination, launchTime, checkedCount });
  }

  const pathsData = useMemo(
    () => (trajectory.length ? [{ points: trajectory }] : []),
    [trajectory],
  );

  const customThreeObject = useCallback((d: object) => {
    const pt = d as GlobePoint;
    const geo = new THREE.SphereGeometry(pt.radius, 8, 8);
    const mat = new THREE.MeshBasicMaterial({
      color: pt.color,
      transparent: true,
      opacity: pt.opacity ?? 1,
      depthWrite: (pt.opacity ?? 1) > 0.5,
    });
    return new THREE.Mesh(geo, mat);
  }, []);

  const customThreeObjectUpdate = useCallback((obj: THREE.Object3D, d: object) => {
    const pt = d as GlobePoint;
    Object.assign(obj.position, globeRef.current?.getCoords(pt.lat, pt.lng, pt.alt));
  }, []);

  const customLayerLabel = useCallback((d: object) => (d as GlobePoint).label, []);
  const pathColor = useCallback(() => "#10b981", []);

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <StatusBar status={status} threatCount={threats.length} checkedCount={checkedCount} />

      <div className="flex flex-1 min-h-0">
        <LeftSidebar
          preset={preset}
          targetLat={targetLat}
          targetLon={targetLon}
          targetAlt={targetAlt}
          inclination={inclination}
          launchTime={launchTime}
          loading={loading}
          status={status}
          searchHoursInput={searchHoursInput}
          findingWindows={findingWindows}
          safeWindows={safeWindows}
          windowSearchDone={windowSearchDone}
          windowSearchHours={windowSearchHours}
          windowElapsed={windowElapsed}
          onPresetChange={applyPreset}
          onLatChange={(v) => { setTargetLat(v); setPreset(0); }}
          onLonChange={(v) => { setTargetLon(v); setPreset(0); }}
          onAltChange={(v) => { setTargetAlt(v); setPreset(0); }}
          onIncChange={(v) => { setInclination(v); setPreset(0); }}
          onLaunchTimeChange={setLaunchTime}
          onSearchHoursChange={setSearchHoursInput}
          onCheckCollision={checkCollision}
          onFindSafeWindows={findSafeWindows}
          onApplyWindow={applyWindow}
        />

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

        {threats.length > 0 && (
          <RightSidebar
            threats={threats}
            selectedThreat={selectedThreat}
            onSelectThreat={setSelectedThreat}
            onFocusThreat={focusThreat}
            onGenerateReport={handleGenerateReport}
          />
        )}
      </div>

      {hoveredDebris && <DebrisTooltip hoveredDebris={hoveredDebris} />}
    </div>
  );
}
