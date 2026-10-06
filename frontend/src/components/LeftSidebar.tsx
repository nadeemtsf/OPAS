import type { SafeWindow, WindowDiagnostics } from "../types";
import { PRESETS } from "../constants";

interface Props {
  preset: number;
  targetLat: number;
  targetLon: number;
  targetAlt: number;
  inclination: number;
  launchTime: string;
  loading: boolean;
  status: "safe" | "danger" | null;
  searchHoursInput: number;
  findingWindows: boolean;
  safeWindows: SafeWindow[];
  windowSearchDone: boolean;
  windowSearchHours: number | null;
  windowElapsed: number | null;
  windowSearchError: string | null;
  windowDiagnostics: WindowDiagnostics | null;
  collisionError: string | null;
  onPresetChange: (index: number) => void;
  onLatChange: (v: number) => void;
  onLonChange: (v: number) => void;
  onAltChange: (v: number) => void;
  onIncChange: (v: number) => void;
  onLaunchTimeChange: (v: string) => void;
  onSearchHoursChange: (v: number) => void;
  onCheckCollision: () => void;
  onFindSafeWindows: () => void;
  onApplyWindow: (iso: string) => void;
  onCancelWindowSearch: () => void;
}

const inputClass =
  "mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500";

const phases: Record<string, string> = {
  loading_catalogue: "Reading orbital data",
  preparing_orbital_data: "Preparing predictions",
  orbital_data_ready: "Orbital data ready",
  coarse_discovery: "Discovering candidate regions",
  minute_discovery: "Checking minute launches",
  fine_verification: "Checking candidate launches every 10 seconds",
  window_validation: "Validating qualifying spans every 5 seconds",
  complete: "Verification completed",
};

function downloadDiagnostics(props: Props) {
  const blob = new Blob([JSON.stringify({ diagnostics: props.windowDiagnostics,
    windows: props.safeWindows, error: props.windowSearchError }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `opas-window-check-${props.windowDiagnostics?.request_id ?? "incomplete"}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function LeftSidebar(props: Props) {
  return (
    <div className="w-72 shrink-0 flex flex-col p-5 border-r border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 overflow-y-auto">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
        Mission Parameters
      </h2>

      <fieldset disabled={props.loading || props.findingWindows} className="space-y-3 disabled:opacity-60">
        <div>
          <span className="text-xs text-gray-500">Mission Profile</span>
          <select
            value={props.preset}
            onChange={(e) => props.onPresetChange(+e.target.value)}
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
            <input type="number" step="0.01" value={props.targetLat}
              onChange={(e) => props.onLatChange(+e.target.value)}
              className={inputClass} />
          </div>
          <div>
            <span className="text-xs text-gray-500">Lon</span>
            <input type="number" step="0.01" value={props.targetLon}
              onChange={(e) => props.onLonChange(+e.target.value)}
              className={inputClass} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <span className="text-xs text-gray-500">Altitude (km)</span>
            <input type="number" step="1" value={props.targetAlt}
              onChange={(e) => props.onAltChange(+e.target.value)}
              className={inputClass} />
          </div>
          <div>
            <span className="text-xs text-gray-500">Inclination (°)</span>
            <input type="number" step="0.1" value={props.inclination}
              onChange={(e) => props.onIncChange(+e.target.value)}
              className={inputClass} />
          </div>
        </div>

        <div>
          <span className="text-xs text-gray-500">Launch Time (UTC)</span>
          <input type="datetime-local" step="0.001" value={props.launchTime}
            onChange={(e) => props.onLaunchTimeChange(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`} />
        </div>
      </fieldset>

      <button
        onClick={props.onCheckCollision}
        disabled={props.loading || props.findingWindows}
        className="mt-5 w-full rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 py-2.5 text-sm font-semibold transition cursor-pointer"
      >
        {props.loading ? "Checking..." : "Check Collision Risk"}
      </button>

      {props.collisionError && (
        <p role="alert" className="mt-2 text-xs text-red-400">{props.collisionError}</p>
      )}

      {(
        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2">
            <select
              value={props.searchHoursInput}
              disabled={props.findingWindows || props.loading}
              onChange={(e) => props.onSearchHoursChange(Number(e.target.value))}
              className="flex-1 rounded bg-gray-800 border border-gray-700 text-white text-xs px-2 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value={1}>1 hour (quick test)</option>
              <option value={6}>6 hours</option>
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={72}>72 hours</option>
              <option value={120}>5 days</option>
              <option value={168}>7 days</option>
              <option value={336}>14 days</option>
            </select>
            <button
              onClick={props.onFindSafeWindows}
              disabled={props.findingWindows || props.loading}
              className="flex-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 py-2 text-xs font-semibold transition cursor-pointer"
            >
              {props.findingWindows ? `Scanning ${props.searchHoursInput}h...` : "Find Safe Window"}
            </button>
          </div>
          {props.findingWindows && (
            <button onClick={props.onCancelWindowSearch} className="text-xs text-gray-400 underline cursor-pointer">
              Cancel search
            </button>
          )}
          {props.searchHoursInput > 72 && (
            <p className="text-[10px] text-yellow-400/80">
              Large search window — this may take a while depending on debris count.
            </p>
          )}
        </div>
      )}

      {(props.findingWindows || props.windowDiagnostics) && (
        <section aria-live="polite" className="mt-3 rounded border border-blue-800/40 bg-blue-950/30 p-3 text-[11px] space-y-2">
          <p className="font-medium text-blue-300">
            {props.windowSearchError ? "Verification incomplete" :
              phases[props.windowDiagnostics?.phase ?? ""] ?? "Connecting to scanner"}
          </p>
          <p className="text-gray-400">Elapsed: {props.windowElapsed ?? 0}s</p>
          {props.windowDiagnostics && (
            <>
              <p>Objects in altitude filter: {props.windowDiagnostics.candidates_checked ?? "loading"}</p>
              <p>Launch checks: {props.windowDiagnostics.checked_launch_samples ?? 0}<br />
                Clear: {props.windowDiagnostics.clear_launch_samples ?? 0} · Obstructed: {props.windowDiagnostics.obstructed_launch_samples ?? 0}</p>
              <p>Candidate spans: {props.windowDiagnostics.candidate_spans ?? 0}</p>
              {(props.windowDiagnostics.phase_total ?? 0) > 0 && props.findingWindows && (
                <p>Current group: {props.windowDiagnostics.phase_completed ?? 0}/{props.windowDiagnostics.phase_total} checks</p>
              )}
              <p>Extra 5s checks: {props.windowDiagnostics.extra_validation_checks ?? 0}<br />
                New obstructions: {props.windowDiagnostics.validation_obstructed_samples ?? 0}</p>
              <p className="text-gray-400">Clearance applies to sampled launches in the post-ascent model.</p>
              <details>
                <summary className="cursor-pointer text-blue-300">Request and model details</summary>
                <div className="mt-2 text-gray-400 space-y-1 break-words">
                  <p>Request: {props.windowDiagnostics.request_id}</p>
                  <p>Screening radius: {props.windowDiagnostics.radius_min_km ?? "—"}–{props.windowDiagnostics.radius_max_km ?? "—"} km</p>
                  <p>Flight checked: {props.windowDiagnostics.flight_start_seconds ?? "—"}–{props.windowDiagnostics.flight_end_seconds ?? "—"} seconds after launch</p>
                  <p>{props.windowDiagnostics.scope}</p>
                </div>
              </details>
              <button onClick={() => downloadDiagnostics(props)} className="text-blue-300 underline cursor-pointer">
                Download check details
              </button>
            </>
          )}
        </section>
      )}

      {props.safeWindows.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            Checked Launch Windows {props.windowSearchHours && `(${props.windowSearchHours}h scan)`}
          </h3>
          <ul className="space-y-2">
            {props.safeWindows.map((w, i) => (
              <li
                key={i}
                className="rounded bg-green-900/30 border border-green-800/40"
              >
                <button onClick={() => props.onApplyWindow(w.start)} disabled={props.loading || props.findingWindows}
                  className="w-full text-left p-3 cursor-pointer hover:bg-green-900/50 disabled:opacity-50 transition">
                <p className="text-xs text-green-400 font-medium">
                  {new Date(w.start).toLocaleString()}
                </p>
                <p className="text-[10px] text-gray-400 mt-1">
                  {w.duration_minutes} min · ends {new Date(w.end).toLocaleTimeString()}
                </p>
                <p className="text-[10px] text-green-400 mt-1">
                  {w.verification?.checked_launches} clear launch checks · max gap {w.verification?.max_launch_gap_seconds}s
                </p>
                <p className="text-[10px] text-gray-400 mt-1">Endpoints, duration and coverage checked</p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {props.windowSearchError && (
        <div className="mt-3 rounded bg-red-900/30 border border-red-800/40 p-3">
          <p className="text-xs text-red-400 font-medium">Window search incomplete</p>
          <p className="text-[10px] text-gray-400 mt-1">{props.windowSearchError}</p>
        </div>
      )}

      {props.windowSearchDone && !props.windowSearchError && props.safeWindows.length === 0 && (
        <div className="mt-3 rounded bg-yellow-900/30 border border-yellow-800/40 p-3">
          <p className="text-xs text-yellow-400 font-medium">No qualifying checked window found within {props.windowSearchHours ?? props.searchHoursInput}h.</p>
          <p className="text-[10px] text-gray-400 mt-1">
            Consider increasing the search window, adjusting altitude, or changing inclination.
          </p>
        </div>
      )}
    </div>
  );
}
