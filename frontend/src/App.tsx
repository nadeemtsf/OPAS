import { useState } from "react";
import axios from "axios";
import { MapContainer, TileLayer, Circle, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";

interface Threat {
  name: string;
  norad_id: number;
  altitude_km: number;
  distance_meters: number;
  location: { type: string; coordinates: [number, number] };
}

const markerIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

function RecenterMap({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap();
  map.setView([lat, lon], map.getZoom());
  return null;
}

export default function App() {
  const [targetLat, setTargetLat] = useState(29.55);
  const [targetLon, setTargetLon] = useState(-95.1);
  const [targetAlt, setTargetAlt] = useState(400);
  const [status, setStatus] = useState<"safe" | "danger" | null>(null);
  const [threats, setThreats] = useState<Threat[]>([]);
  const [loading, setLoading] = useState(false);

  async function scanAirspace() {
    setLoading(true);
    try {
      const { data } = await axios.get("http://localhost:8000/alert", {
        params: { target_lat: targetLat, target_lon: targetLon, target_alt: targetAlt },
      });
      setStatus(data.status);
      setThreats(data.threats);
    } catch (err) {
      console.error(err);
      setStatus(null);
      setThreats([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Sidebar */}
      <div className="w-80 flex flex-col gap-4 p-6 border-r border-gray-800 bg-gray-900">
        <h1 className="text-xl font-bold tracking-wide text-white">OPAS Dashboard</h1>
        <p className="text-xs text-gray-500 uppercase tracking-widest">Orbital Proximity Alert System</p>

        <label className="text-sm text-gray-400">
          Latitude
          <input
            type="number"
            step="0.01"
            value={targetLat}
            onChange={(e) => setTargetLat(+e.target.value)}
            className="mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </label>
        <label className="text-sm text-gray-400">
          Longitude
          <input
            type="number"
            step="0.01"
            value={targetLon}
            onChange={(e) => setTargetLon(+e.target.value)}
            className="mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </label>
        <label className="text-sm text-gray-400">
          Altitude (km)
          <input
            type="number"
            step="1"
            value={targetAlt}
            onChange={(e) => setTargetAlt(+e.target.value)}
            className="mt-1 w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </label>

        <button
          onClick={scanAirspace}
          disabled={loading}
          className="mt-2 w-full rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 py-2 font-semibold transition"
        >
          {loading ? "Scanning..." : "Scan Airspace"}
        </button>

        {/* Status */}
        {status && (
          <div
            className={`mt-2 rounded px-4 py-3 text-center font-bold text-lg uppercase tracking-wider ${
              status === "safe" ? "bg-green-900/60 text-green-400" : "bg-red-900/60 text-red-400"
            }`}
          >
            {status}
          </div>
        )}

        {/* Threat list */}
        {threats.length > 0 && (
          <div className="mt-2 flex-1 overflow-y-auto">
            <h2 className="text-sm font-semibold text-gray-400 mb-2">
              Threats ({threats.length})
            </h2>
            <ul className="space-y-2">
              {threats.map((t) => (
                <li key={t.norad_id} className="rounded bg-gray-800 p-3 text-sm">
                  <p className="font-medium text-white">{t.name}</p>
                  <p className="text-gray-500">
                    NORAD {t.norad_id} &middot; {t.altitude_km.toFixed(1)} km
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Map */}
      <div className="flex-1">
        <MapContainer center={[targetLat, targetLon]} zoom={5} className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          <RecenterMap lat={targetLat} lon={targetLon} />
          <Circle
            center={[targetLat, targetLon]}
            radius={100000}
            pathOptions={{ color: "#3b82f6", fillOpacity: 0.08 }}
          />
          {threats.map((t) => (
            <Marker
              key={t.norad_id}
              position={[t.location.coordinates[1], t.location.coordinates[0]]}
              icon={markerIcon}
            >
              <Popup>
                <strong>{t.name}</strong>
                <br />
                NORAD {t.norad_id} &middot; {t.altitude_km.toFixed(1)} km
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}
