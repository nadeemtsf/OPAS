import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import axios from "axios";
import Globe, { type GlobeMethods } from "react-globe.gl";
import * as THREE from "three";

import type { Threat, GlobePoint, TrajectoryPoint, SafeWindow, WindowDiagnostics } from "./types";
import { API_BASE, EARTH_RADIUS_KM, PRESETS } from "./constants";
import { generateReport } from "./utils/reportGenerator";
import { launchTimeForRequest, utcLaunchTimeValue } from "./utils/launchTime";
import { readWindowStream } from "./utils/windowSearch";
import { http } from "./utils/http";
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
  const [searchHoursInput, setSearchHoursInput] = useState(6);
  const [windowElapsed, setWindowElapsed] = useState<number | null>(null);
  const [windowSearchError, setWindowSearchError] = useState<string | null>(null);
  const [windowDiagnostics, setWindowDiagnostics] = useState<WindowDiagnostics | null>(null);
  const [collisionError, setCollisionError] = useState<string | null>(null);
  const checkedWindowTime = useRef<string | null>(null);
  const windowAbort = useRef<AbortController | null>(null);
  const windowStarted = useRef(0);

  useEffect(() => () => windowAbort.current?.abort(), []);
  useEffect(() => {
    if (!findingWindows) return;
    const timer = setInterval(() => setWindowElapsed(Math.round((performance.now()-windowStarted.current)/1000)), 1000);
    return () => clearInterval(timer);
  }, [findingWindows]);

  function clearResults() {
    setTrajectory([]);
    setCustomData([]);
    setStatus(null);
    setThreats([]);
    setCheckedCount(null);
    setSafeWindows([]);
    setWindowSearchDone(false);
    setWindowDiagnostics(null);
    setWindowSearchError(null);
    setCollisionError(null);
    checkedWindowTime.current = null;
  }

  const globeRef = useRef<GlobeMethods>(undefined);
  const { containerRef, globeSize } = useGlobeSize();
  const { hoveredDebris } = useGlobeDebris(globeRef);

  function applyPreset(index: number) {
    clearResults();
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
    setWindowSearchError(null);
    checkedWindowTime.current = null;
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
    setCollisionError(null);
    try {
      const params: Record<string, string | number> = {
        target_lat: targetLat,
        target_lon: targetLon,
        target_alt: targetAlt,
        inclination,
        launch_time: launchTimeForRequest(effectiveTime, checkedWindowTime.current),
      };
      const { data } = await http.get(`${API_BASE}/alert`, { params });
      setStatus(data.status);
      setThreats(data.threats);
      setCheckedCount(data.candidates_checked ?? null);
      setTrajectory(data.trajectory ?? []);
      setSelectedThreat(null);
      rebuildPoints(data.threats);
      if (globeRef.current) {
        globeRef.current.pointOfView({ lat: targetLat, lng: targetLon, altitude: 2 }, 1000);
      }
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setCollisionError(typeof detail === "string" ? detail : "The collision check could not be completed. Check the request log.");
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
      effectiveTime = utcLaunchTimeValue(new Date().toISOString());
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
    setSafeWindows([]);
    setWindowSearchDone(false);
    setWindowSearchError(null);
    setWindowSearchHours(null);
    setWindowElapsed(null);
    setWindowDiagnostics(null);
    const controller = new AbortController();
    windowAbort.current = controller;
    const t0 = performance.now();
    windowStarted.current = t0;
    const parameters = { target_lat: targetLat, target_lon: targetLon, target_alt: targetAlt,
      inclination, search_hours: searchHoursInput };
    console.info("[OPAS] Window search started", parameters);
    try {
      const query = new URLSearchParams(Object.entries(parameters).map(([key, value]) => [key, String(value)]));
      const response = await fetch(`${API_BASE}/safe-windows/stream?${query}`, { signal: controller.signal });
      let lastPhase = "";
      const data = await readWindowStream(response, progress => {
        setWindowDiagnostics(progress);
        if (progress.phase !== lastPhase || progress.phase === "complete") {
          console.info("[OPAS] Window search progress", progress);
          lastPhase = progress.phase;
        }
      });
      setSafeWindows(data.windows);
      setWindowDiagnostics(data.diagnostics);
      setWindowSearchHours(data.search_hours);
      setWindowSearchDone(true);
      console.info("[OPAS] Window verification completed", data);
    } catch (err) {
      setSafeWindows([]);
      const message = controller.signal.aborted ? "Search cancelled. No windows were accepted."
        : err instanceof Error ? err.message : "The window search could not be completed. Please retry.";
      setWindowSearchError(message);
      setWindowDiagnostics(previous => previous ? { ...previous, status: "incomplete" } : null);
      console.error("[OPAS] Window search incomplete", message);
    } finally {
      setWindowElapsed(Math.round((performance.now() - t0) / 1000));
      setFindingWindows(false);
      windowAbort.current = null;
    }
  }

  function applyWindow(iso: string) {
    const value = utcLaunchTimeValue(iso);
    checkedWindowTime.current = iso;
    setLaunchTime(value);
    runCollisionCheck(value);
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
          windowSearchError={windowSearchError}
          windowDiagnostics={windowDiagnostics}
          collisionError={collisionError}
          onPresetChange={applyPreset}
          onLatChange={(v) => { clearResults(); setTargetLat(v); setPreset(0); }}
          onLonChange={(v) => { clearResults(); setTargetLon(v); setPreset(0); }}
          onAltChange={(v) => { clearResults(); setTargetAlt(v); setPreset(0); }}
          onIncChange={(v) => { clearResults(); setInclination(v); setPreset(0); }}
          onLaunchTimeChange={(value) => {
            checkedWindowTime.current = null;
            setLaunchTime(value);
          }}
          onSearchHoursChange={setSearchHoursInput}
          onCheckCollision={checkCollision}
          onFindSafeWindows={findSafeWindows}
          onApplyWindow={applyWindow}
          onCancelWindowSearch={() => windowAbort.current?.abort()}
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
