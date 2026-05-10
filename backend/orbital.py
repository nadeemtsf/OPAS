from math import radians, degrees, sin, cos, asin, atan2, sqrt, pi
from datetime import datetime, timezone, timedelta
from skyfield.api import EarthSatellite

from db import ts

EARTH_R = 6371


def propagate_at(doc, t):
    sat = EarthSatellite(doc["tle_line1"], doc["tle_line2"], doc["name"], ts)
    sub = sat.at(t).subpoint()
    return sat, sub.latitude.degrees, sub.longitude.degrees, sub.elevation.km


def generate_trajectory(launch_lat, launch_lon, alt_km, inc_deg, steps=120):
    inc = radians(max(inc_deg, 0.5))
    r = EARTH_R + alt_km
    period = 2 * pi * sqrt(r ** 3 / 398600.4418) / 60
    drift = 360 / 1440

    sin_lat = sin(radians(launch_lat))
    sin_inc = sin(inc)
    u0 = asin(max(-1.0, min(1.0, sin_lat / sin_inc)))
    lon0 = degrees(atan2(cos(inc) * sin(u0), cos(u0)))

    step_sec = (period * 60) / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))

    waypoints = []
    for i in range(steps + 1):
        u = u0 + (i / steps) * 2 * pi
        wlat = degrees(asin(sin_inc * sin(u)))
        wlon = launch_lon + degrees(atan2(cos(inc) * sin(u), cos(u))) - lon0 - drift * period * i / steps
        wlon = ((wlon + 540) % 360) - 180
        wp_alt = alt_km * min(1.0, i / ascent_steps) if ascent_steps > 0 else alt_km
        waypoints.append({"lat": round(wlat, 4), "lon": round(wlon, 4), "alt": round(wp_alt, 2)})
    return waypoints


def tle_epoch_age_days(tle_line1):
    try:
        yr2 = int(tle_line1[18:20])
        day_frac = float(tle_line1[20:32])
        year = yr2 + (1900 if yr2 >= 57 else 2000)
        epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
        return (datetime.now(timezone.utc) - epoch).total_seconds() / 86400.0
    except Exception:
        return None
