#define _USE_MATH_DEFINES
#include <cmath>
#include <vector>
#include <pybind11/pybind11.h>

namespace py = pybind11;

static constexpr double kWGS84_A = 6378.137;
static constexpr double kWGS84_E2 = 0.00669437999014;

struct Vec3 { double x, y, z; };

static inline Vec3 geodetic_to_ecef(double lat_deg, double lon_deg, double alt_km) {
    const double deg = M_PI / 180.0;
    const double lat = lat_deg * deg;
    const double lon = lon_deg * deg;
    const double sin_lat = std::sin(lat);
    const double cos_lat = std::cos(lat);
    const double n = kWGS84_A / std::sqrt(1.0 - kWGS84_E2 * sin_lat * sin_lat);
    return {
        (n + alt_km) * cos_lat * std::cos(lon),
        (n + alt_km) * cos_lat * std::sin(lon),
        (n * (1.0 - kWGS84_E2) + alt_km) * sin_lat
    };
}

static inline double dist_3d(const Vec3 &a, const Vec3 &b) {
    const double dx = b.x - a.x;
    const double dy = b.y - a.y;
    const double dz = b.z - a.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

static std::vector<double> to_vec(const py::sequence &seq) {
    const size_t n = seq.size();
    std::vector<double> out;
    out.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        out.push_back(py::float_(seq[i]));
    }
    return out;
}

bool any_within_3d(const py::sequence &wp_lats,
                   const py::sequence &wp_lons,
                   const py::sequence &wp_alts,
                   double target_lat,
                   double target_lon,
                   double target_alt,
                   double proximity_km) {
    const auto lats = to_vec(wp_lats);
    const auto lons = to_vec(wp_lons);
    const auto alts = to_vec(wp_alts);
    const size_t n = lats.size();
    if (n == 0 || lons.size() != n || alts.size() != n) {
        return false;
    }
    const Vec3 target = geodetic_to_ecef(target_lat, target_lon, target_alt);
    for (size_t i = 0; i < n; ++i) {
        const Vec3 wp = geodetic_to_ecef(lats[i], lons[i], alts[i]);
        if (dist_3d(wp, target) < proximity_km) {
            return true;
        }
    }
    return false;
}

bool any_threat_3d(const py::sequence &wp_lats,
                   const py::sequence &wp_lons,
                   const py::sequence &wp_alts,
                   const py::sequence &sat_lats,
                   const py::sequence &sat_lons,
                   const py::sequence &sat_alts,
                   double proximity_km) {
    const auto w_lats = to_vec(wp_lats);
    const auto w_lons = to_vec(wp_lons);
    const auto w_alts = to_vec(wp_alts);
    const auto s_lats = to_vec(sat_lats);
    const auto s_lons = to_vec(sat_lons);
    const auto s_alts = to_vec(sat_alts);

    const size_t n = w_lats.size();
    if (n == 0 || w_lons.size() != n || w_alts.size() != n) {
        return false;
    }
    if (s_lats.size() != n || s_lons.size() != n || s_alts.size() != n) {
        return false;
    }

    for (size_t i = 0; i < n; ++i) {
        const Vec3 wp = geodetic_to_ecef(w_lats[i], w_lons[i], w_alts[i]);
        const Vec3 sat = geodetic_to_ecef(s_lats[i], s_lons[i], s_alts[i]);
        if (dist_3d(wp, sat) < proximity_km) {
            return true;
        }
    }
    return false;
}

bool any_threat_ecef(const py::sequence &wp_xs,
                     const py::sequence &wp_ys,
                     const py::sequence &wp_zs,
                     const py::sequence &sat_xs,
                     const py::sequence &sat_ys,
                     const py::sequence &sat_zs,
                     double proximity_km) {
    const auto wxs = to_vec(wp_xs), wys = to_vec(wp_ys), wzs = to_vec(wp_zs);
    const auto sxs = to_vec(sat_xs), sys = to_vec(sat_ys), szs = to_vec(sat_zs);

    const size_t n = wxs.size();
    if (n == 0 || wys.size() != n || wzs.size() != n) return false;
    if (sxs.size() != n || sys.size() != n || szs.size() != n) return false;

    const double r2 = proximity_km * proximity_km;
    for (size_t i = 0; i < n; ++i) {
        const double dx = sxs[i] - wxs[i];
        const double dy = sys[i] - wys[i];
        const double dz = szs[i] - wzs[i];
        if (dx * dx + dy * dy + dz * dz < r2) return true;
    }
    return false;
}

bool any_within_ecef(const py::sequence &wp_xs,
                     const py::sequence &wp_ys,
                     const py::sequence &wp_zs,
                     double tx, double ty, double tz,
                     double proximity_km) {
    const auto wxs = to_vec(wp_xs), wys = to_vec(wp_ys), wzs = to_vec(wp_zs);

    const size_t n = wxs.size();
    if (n == 0 || wys.size() != n || wzs.size() != n) return false;

    const double r2 = proximity_km * proximity_km;
    for (size_t i = 0; i < n; ++i) {
        const double dx = wxs[i] - tx;
        const double dy = wys[i] - ty;
        const double dz = wzs[i] - tz;
        if (dx * dx + dy * dy + dz * dz < r2) return true;
    }
    return false;
}

PYBIND11_MODULE(opas_math, m) {
    m.doc() = "OPAS native math helpers — 3D ECEF distance";
    m.def("any_within_3d", &any_within_3d, "Any waypoint within 3D proximity of a target",
          py::arg("wp_lats"), py::arg("wp_lons"), py::arg("wp_alts"),
          py::arg("target_lat"), py::arg("target_lon"), py::arg("target_alt"),
          py::arg("proximity_km"));
    m.def("any_threat_3d", &any_threat_3d, "Any sat position within 3D proximity of waypoints",
          py::arg("wp_lats"), py::arg("wp_lons"), py::arg("wp_alts"),
          py::arg("sat_lats"), py::arg("sat_lons"), py::arg("sat_alts"),
          py::arg("proximity_km"));
    m.def("any_threat_ecef", &any_threat_ecef, "Any pre-computed ECEF sat within proximity of ECEF waypoints",
          py::arg("wp_xs"), py::arg("wp_ys"), py::arg("wp_zs"),
          py::arg("sat_xs"), py::arg("sat_ys"), py::arg("sat_zs"),
          py::arg("proximity_km"));
    m.def("any_within_ecef", &any_within_ecef, "Any ECEF waypoint within proximity of a single ECEF target",
          py::arg("wp_xs"), py::arg("wp_ys"), py::arg("wp_zs"),
          py::arg("tx"), py::arg("ty"), py::arg("tz"),
          py::arg("proximity_km"));
}
