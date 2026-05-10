import type { HoveredDebris } from "../types";

interface Props {
  hoveredDebris: HoveredDebris;
}

export function DebrisTooltip({ hoveredDebris }: Props) {
  return (
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
  );
}
