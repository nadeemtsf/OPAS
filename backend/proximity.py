import logging
from math import radians, sin, cos, sqrt, exp

log = logging.getLogger("opas")

WGS84_A = 6378.137
WGS84_E2 = 0.00669437999014
COMBINED_HBR_M = 10.0

try:
    import opas_math
    HAS_NATIVE_MATH = True
except Exception:
    opas_math = None
    HAS_NATIVE_MATH = False


def geodetic_to_ecef(lat_deg, lon_deg, alt_km):
    lat = radians(lat_deg)
    lon = radians(lon_deg)
    n = WGS84_A / sqrt(1 - WGS84_E2 * sin(lat) ** 2)
    x = (n + alt_km) * cos(lat) * cos(lon)
    y = (n + alt_km) * cos(lat) * sin(lon)
    z = (n * (1 - WGS84_E2) + alt_km) * sin(lat)
    return x, y, z


def dist_3d_km(lat1, lon1, alt1, lat2, lon2, alt2):
    x1, y1, z1 = geodetic_to_ecef(lat1, lon1, alt1)
    x2, y2, z2 = geodetic_to_ecef(lat2, lon2, alt2)
    return sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


def screening_radius_km(base_km, tle_age_days):
    if tle_age_days is None or tle_age_days <= 0:
        return base_km
    return min(base_km + 2.0 * tle_age_days ** 1.5, 200.0)


def estimate_sigma_m(tle_age_days):
    if tle_age_days is None or tle_age_days <= 0:
        return 1000.0
    return 1000.0 + 2000.0 * tle_age_days ** 1.5


def compute_pc(miss_distance_m, sigma_m, hbr_m=COMBINED_HBR_M):
    if sigma_m <= 0:
        return 0.0
    s2 = sigma_m ** 2
    return min((hbr_m ** 2 / (2 * s2)) * exp(-(miss_distance_m ** 2) / (2 * s2)), 1.0)


def threat_level_from_pc(pc):
    if pc >= 1e-4:
        return "RED"
    if pc >= 1e-5:
        return "YELLOW"
    if pc >= 1e-7:
        return "WATCH"
    return "GREEN"


def proximity_severity(distance_km):
    if distance_km < 5:
        return "CRITICAL"
    if distance_km < 25:
        return "HIGH"
    if distance_km < 100:
        return "MODERATE"
    return "LOW"
