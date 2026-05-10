import type { SafeWindow } from "../types";
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
}

const inputClass =
  "mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500";

export function LeftSidebar(props: Props) {
  return (
    <div className="w-72 shrink-0 flex flex-col p-5 border-r border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 overflow-y-auto">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
        Mission Parameters
      </h2>

      <div className="space-y-3">
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
          <input type="datetime-local" step="1" value={props.launchTime}
            onChange={(e) => props.onLaunchTimeChange(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`} />
        </div>
      </div>

      <button
        onClick={props.onCheckCollision}
        disabled={props.loading}
        className="mt-5 w-full rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 py-2.5 text-sm font-semibold transition cursor-pointer"
      >
        {props.loading ? "Checking..." : "Check Collision Risk"}
      </button>

      {props.status === "danger" && (
        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2">
            <select
              value={props.searchHoursInput}
              onChange={(e) => props.onSearchHoursChange(Number(e.target.value))}
              className="flex-1 rounded bg-gray-800 border border-gray-700 text-white text-xs px-2 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={72}>72 hours</option>
              <option value={120}>5 days</option>
              <option value={168}>7 days</option>
              <option value={336}>14 days</option>
            </select>
            <button
              onClick={props.onFindSafeWindows}
              disabled={props.findingWindows}
              className="flex-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 py-2 text-xs font-semibold transition cursor-pointer"
            >
              {props.findingWindows ? `Scanning ${props.searchHoursInput}h...` : "Find Safe Window"}
            </button>
          </div>
          {props.searchHoursInput > 72 && (
            <p className="text-[10px] text-yellow-400/80">
              Large search window — this may take a while depending on debris count.
            </p>
          )}
        </div>
      )}

      {props.safeWindows.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            Safe Windows {props.windowSearchHours && `(${props.windowSearchHours}h scan${props.windowElapsed != null ? ` · ${props.windowElapsed}s` : ""})`}
          </h3>
          <ul className="space-y-2">
            {props.safeWindows.map((w, i) => (
              <li
                key={i}
                onClick={() => props.onApplyWindow(w.start)}
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

      {props.windowSearchDone && props.safeWindows.length === 0 && (
        <div className="mt-3 rounded bg-yellow-900/30 border border-yellow-800/40 p-3">
          <p className="text-xs text-yellow-400 font-medium">No safe windows found within {props.windowSearchHours ?? props.searchHoursInput}h.</p>
          <p className="text-[10px] text-gray-400 mt-1">
            Consider increasing the search window, adjusting altitude, or changing inclination.
          </p>
        </div>
      )}
    </div>
  );
}
