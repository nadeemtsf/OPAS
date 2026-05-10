#define _USE_MATH_DEFINES
#include <cmath>
#include <vector>
#include <pybind11/pybind11.h>

namespace py = pybind11;

static constexpr double kEarthRadiusKm = 6371.0;

static inline double haversine_km(double lat1, double lon1, double lat2, double lon2) {
    const double deg_to_rad = M_PI / 180.0;
    lat1 *= deg_to_rad;
    lon1 *= deg_to_rad;
    lat2 *= deg_to_rad;
    lon2 *= deg_to_rad;
    const double dlat = lat2 - lat1;
    const double dlon = lon2 - lon1;
    const double a = std::sin(dlat / 2.0) * std::sin(dlat / 2.0) +
                     std::cos(lat1) * std::cos(lat2) * std::sin(dlon / 2.0) * std::sin(dlon / 2.0);
    return kEarthRadiusKm * 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
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

bool any_within_km(const py::sequence &wp_lats,
                   const py::sequence &wp_lons,
                   double target_lat,
                   double target_lon,
                   double proximity_km) {
    const auto lats = to_vec(wp_lats);
    const auto lons = to_vec(wp_lons);
    const size_t n = lats.size();
    if (n == 0 || lons.size() != n) {
        return false;
    }
    for (size_t i = 0; i < n; ++i) {
        if (haversine_km(lats[i], lons[i], target_lat, target_lon) < proximity_km) {
            return true;
        }
    }
    return false;
}

bool any_threat(const py::sequence &wp_lats,
                const py::sequence &wp_lons,
                const py::sequence &wp_alts,
                const py::sequence &sat_lats,
                const py::sequence &sat_lons,
                const py::sequence &sat_alts,
                double target_alt,
                double proximity_km,
                double alt_threshold_km) {
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
        if (std::fabs(s_alts[i] - target_alt) > alt_threshold_km) {
            continue;
        }
        if (haversine_km(w_lats[i], w_lons[i], s_lats[i], s_lons[i]) < proximity_km) {
            return true;
        }
    }
    return false;
}

PYBIND11_MODULE(opas_math, m) {
    m.doc() = "OPAS native math helpers";
    m.def("any_within_km", &any_within_km, "Any waypoint within proximity");
    m.def("any_threat", &any_threat, "Any threat within proximity with altitude gate",
          py::arg("wp_lats"), py::arg("wp_lons"), py::arg("wp_alts"),
          py::arg("sat_lats"), py::arg("sat_lons"), py::arg("sat_alts"),
          py::arg("target_alt"), py::arg("proximity_km"), py::arg("alt_threshold_km") = 50.0);
}
