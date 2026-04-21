"""US state geographic lookup — bounding boxes plus closest-centroid disambiguation.

Precision is state-level, which matches the scope of every synthesis rule
that uses this module. County-level precision is out of scope; if a point
falls inside two adjacent states' bounding boxes, we pick the state whose
centroid is closest. If no state centroid is within 500 km, we return None
(the point isn't in the US).
"""

from __future__ import annotations

from math import radians, sin, cos, asin, sqrt

# (min_lat, max_lat, min_lon, max_lon) per state.
# Derived from public Census Bureau state extents, rounded to 2 decimals.
STATE_BOUNDING_BOXES: dict[str, tuple[float, float, float, float]] = {
    "Alabama":        (30.14, 35.01, -88.47, -84.89),
    "Alaska":         (51.21, 71.44, -172.42, -129.97),
    "Arizona":        (31.33, 37.01, -114.82, -109.05),
    "Arkansas":       (33.00, 36.50, -94.62, -89.64),
    "California":     (32.53, 42.01, -124.41, -114.13),
    "Colorado":       (36.99, 41.00, -109.06, -102.04),
    "Connecticut":    (40.98, 42.05, -73.73, -71.79),
    "Delaware":       (38.45, 39.84, -75.79, -75.05),
    "District of Columbia": (38.79, 38.99, -77.12, -76.91),
    "Florida":        (24.52, 31.00, -87.63, -80.03),
    "Georgia":        (30.36, 35.00, -85.61, -80.84),
    "Hawaii":         (18.91, 28.40, -178.33, -154.81),
    "Idaho":          (41.99, 49.00, -117.24, -111.04),
    "Illinois":       (36.97, 42.51, -91.51, -87.01),
    "Indiana":        (37.77, 41.76, -88.10, -84.78),
    "Iowa":           (40.38, 43.50, -96.64, -90.14),
    "Kansas":         (36.99, 40.00, -102.05, -94.59),
    "Kentucky":       (36.50, 39.15, -89.57, -81.96),
    "Louisiana":      (28.93, 33.02, -94.04, -88.82),
    "Maine":          (43.06, 47.46, -71.08, -66.95),
    "Maryland":       (37.89, 39.72, -79.49, -75.05),
    "Massachusetts":  (41.19, 42.89, -73.51, -69.93),
    "Michigan":       (41.70, 48.31, -90.42, -82.13),
    "Minnesota":      (43.50, 49.38, -97.24, -89.49),
    "Mississippi":    (30.17, 34.99, -91.66, -88.10),
    "Missouri":       (35.99, 40.61, -95.77, -89.10),
    "Montana":        (44.36, 49.00, -116.05, -104.04),
    "Nebraska":       (40.00, 43.00, -104.05, -95.31),
    "Nevada":         (35.00, 42.00, -120.01, -114.04),
    "New Hampshire":  (42.70, 45.31, -72.56, -70.61),
    "New Jersey":     (38.93, 40.70, -75.56, -73.89),
    "New Mexico":     (31.33, 37.00, -109.05, -103.00),
    "New York":       (40.47, 45.02, -79.76, -71.87),
    "North Carolina": (33.84, 36.59, -84.32, -75.46),
    "North Dakota":   (45.94, 49.00, -104.05, -96.55),
    "Ohio":           (38.40, 42.33, -84.82, -80.52),
    "Oklahoma":       (33.62, 37.00, -103.00, -94.43),
    "Oregon":         (41.99, 46.29, -124.57, -116.46),
    "Pennsylvania":   (39.72, 42.27, -80.52, -74.69),
    "Rhode Island":   (41.15, 42.02, -71.91, -71.12),
    "South Carolina": (32.03, 35.22, -83.35, -78.54),
    "South Dakota":   (42.48, 45.95, -104.06, -96.44),
    "Tennessee":      (34.98, 36.68, -90.31, -81.65),
    "Texas":          (25.84, 36.50, -106.65, -93.51),
    "Utah":           (36.99, 42.00, -114.05, -109.04),
    "Vermont":        (42.73, 45.02, -73.44, -71.47),
    "Virginia":       (36.54, 39.47, -83.68, -75.24),
    "Washington":     (45.54, 49.00, -124.85, -116.92),
    "West Virginia":  (37.20, 40.64, -82.64, -77.72),
    "Wisconsin":      (42.49, 47.08, -92.89, -86.77),
    "Wyoming":        (40.99, 45.01, -111.06, -104.05),
}

STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "Alabama":        (32.81, -86.79),
    "Alaska":         (64.20, -149.49),
    "Arizona":        (34.87, -111.76),
    "Arkansas":       (34.75, -92.44),
    "California":     (37.18, -119.47),
    "Colorado":       (39.00, -105.55),
    "Connecticut":    (41.60, -72.76),
    "Delaware":       (39.00, -75.50),
    "District of Columbia": (38.90, -77.02),
    "Florida":        (28.63, -82.45),
    "Georgia":        (32.65, -83.44),
    "Hawaii":         (20.29, -156.37),
    "Idaho":          (44.39, -114.61),
    "Illinois":       (40.04, -89.20),
    "Indiana":        (39.90, -86.28),
    "Iowa":           (42.07, -93.50),
    "Kansas":         (38.50, -98.38),
    "Kentucky":       (37.53, -85.30),
    "Louisiana":      (31.06, -92.01),
    "Maine":          (45.37, -69.24),
    "Maryland":       (39.06, -76.80),
    "Massachusetts":  (42.26, -71.81),
    "Michigan":       (44.94, -86.00),
    "Minnesota":      (46.28, -94.30),
    "Mississippi":    (32.74, -89.68),
    "Missouri":       (38.36, -92.46),
    "Montana":        (46.97, -109.53),
    "Nebraska":       (41.53, -99.79),
    "Nevada":         (39.33, -116.63),
    "New Hampshire":  (43.68, -71.58),
    "New Jersey":     (40.19, -74.67),
    "New Mexico":     (34.42, -106.11),
    "New York":       (42.95, -75.53),
    "North Carolina": (35.55, -79.39),
    "North Dakota":   (47.45, -100.47),
    "Ohio":           (40.29, -82.79),
    "Oklahoma":       (35.59, -97.49),
    "Oregon":         (44.13, -120.55),
    "Pennsylvania":   (40.87, -77.80),
    "Rhode Island":   (41.68, -71.56),
    "South Carolina": (33.91, -80.89),
    "South Dakota":   (44.44, -100.23),
    "Tennessee":      (35.86, -86.36),
    "Texas":          (31.48, -99.33),
    "Utah":           (39.32, -111.67),
    "Vermont":        (44.07, -72.67),
    "Virginia":       (37.52, -78.86),
    "Washington":     (47.38, -120.45),
    "West Virginia":  (38.64, -80.62),
    "Wisconsin":      (44.62, -89.99),
    "Wyoming":        (42.99, -107.55),
}

MAX_CENTROID_KM = 500.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def lat_lon_to_state(lat: float, lon: float) -> str | None:
    """Return canonical US state name for a point, or None if outside the US.

    If multiple bounding boxes match, resolve by nearest centroid. If the
    nearest centroid is more than MAX_CENTROID_KM away, the point is
    treated as not-in-the-US.
    """
    matches = [
        name for name, (min_lat, max_lat, min_lon, max_lon) in STATE_BOUNDING_BOXES.items()
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    best_name = None
    best_dist = float("inf")
    for name in matches:
        c_lat, c_lon = STATE_CENTROIDS[name]
        dist = _haversine_km(lat, lon, c_lat, c_lon)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    if best_dist > MAX_CENTROID_KM:
        return None
    return best_name


def cities_to_state_map(cities: list[dict]) -> dict[str, str]:
    """Pre-compute city_name → US state for each US city with coords.

    Non-US cities and cities without coords are omitted from the result.
    The caller looks up `state = mapping.get(city_name)` and short-circuits
    recording when the lookup returns None.
    """
    mapping: dict[str, str] = {}
    for c in cities:
        if not isinstance(c, dict):
            continue
        name = c.get("city") or c.get("name")
        lat = c.get("latitude")
        lon = c.get("longitude")
        if not name or lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        state = lat_lon_to_state(lat_f, lon_f)
        if state is not None:
            mapping[name] = state
    return mapping
