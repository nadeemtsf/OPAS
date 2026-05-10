import type { Threat } from "../types";

interface Props {
  threats: Threat[];
  selectedThreat: number | null;
  onSelectThreat: (noradId: number | null) => void;
  onFocusThreat: (t: Threat) => void;
  onGenerateReport: () => void;
}

export function RightSidebar({ threats, selectedThreat, onSelectThreat, onFocusThreat, onGenerateReport }: Props) {
  return (
    <div className="w-80 shrink-0 border-l border-gray-800 bg-gray-900/90 backdrop-blur-sm z-10 flex flex-col overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Collision Risks ({threats.length})
        </h2>
        <button
          onClick={onGenerateReport}
          className="text-[10px] text-blue-400 hover:text-blue-300 font-medium transition cursor-pointer"
        >
          Download Report
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {threats.map((t) => (
          <li
            key={t.norad_id}
            onClick={() => onSelectThreat(selectedThreat === t.norad_id ? null : t.norad_id)}
            className={`px-5 py-3 border-b border-gray-800/40 cursor-pointer transition ${
              selectedThreat === t.norad_id ? "bg-gray-800/70" : "hover:bg-gray-800/50"
            }`}
          >
            <p className="text-xs font-medium text-white">{t.name}</p>
            <div className="flex items-center justify-between mt-1">
              <span className="text-[10px] text-gray-500">NORAD {t.norad_id}</span>
              <span className="text-[10px] text-gray-500">{t.altitude_km.toFixed(1)} km</span>
              <span className="text-[10px] text-red-400 font-medium">
                {t.distance_km.toFixed(1)} km away
              </span>
            </div>

            {t.severity && (
              <span className={`mt-1 inline-block text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                t.severity === "CRITICAL" ? "bg-red-900/50 text-red-400" :
                t.severity === "HIGH" ? "bg-orange-900/50 text-orange-400" :
                t.severity === "MODERATE" ? "bg-yellow-900/50 text-yellow-400" :
                "bg-green-900/50 text-green-400"
              }`}>
                {t.severity}
                {t.tle_age_days != null && ` · TLE ${t.tle_age_days}d old`}
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
                      {t.distance_km.toFixed(3)} km
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
                  onClick={(e) => { e.stopPropagation(); onFocusThreat(t); }}
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
  );
}
