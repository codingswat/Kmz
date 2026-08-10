"""Measuring shapes.

Separate from convert.py, which converts one point at a time and knows nothing
about how points relate to each other. Everything here is a pure function and
nothing raises: an unmeasurable shape comes back as a Measurement carrying the
reason, so one bad polygon can never abort a batch.

The area is FLAT MAP AREA -- the shape as traced on a map, not surface area
following the terrain. A sloping hillside's true surface is larger than its
footprint, and the elevation data needed to compute that is not in a KML.
"""

from __future__ import annotations

from dataclasses import dataclass

import utm as _utm

from kmz_points.models import Point

# UTM is undefined outside this band; the poles use UPS instead.
_UTM_MIN_LAT = -80.0
_UTM_MAX_LAT = 84.0

# Forcing every corner into a single zone is what keeps the grid consistent,
# but distortion grows with distance from that zone's central meridian. A zone
# is 6 degrees wide, so beyond that span the projection stops being trustworthy
# and a refusal beats a confident wrong number.
_MAX_LONGITUDE_SPAN = 6.0

_SQUARE_METRES_PER_HECTARE = 10_000.0
_SQUARE_METRES_PER_SQUARE_KM = 1_000_000.0


@dataclass(frozen=True)
class Measurement:
    """An area, or the reason there isn't one."""

    square_metres: float | None
    problem: str | None = None

    @property
    def hectares(self) -> float | None:
        if self.square_metres is None:
            return None
        return self.square_metres / _SQUARE_METRES_PER_HECTARE

    @property
    def square_kilometres(self) -> float | None:
        if self.square_metres is None:
            return None
        return self.square_metres / _SQUARE_METRES_PER_SQUARE_KM


def _distinct_corners(ring: list[Point]) -> list[Point]:
    """Drop consecutive duplicates, including the repeated closing corner.

    KML writes rings closed, repeating the first coordinate last. Counting
    that as a real corner adds a zero-width sliver to the shoelace sum.
    """
    kept: list[Point] = []
    for point in ring:
        if kept and point.lat == kept[-1].lat and point.lon == kept[-1].lon:
            continue
        kept.append(point)
    while len(kept) > 1 and kept[0].lat == kept[-1].lat and kept[0].lon == kept[-1].lon:
        kept.pop()
    return kept


def _shoelace(projected: list[tuple[float, float]]) -> float:
    """Area of a simple polygon from its corners, in the units they are in.

    Absolute, because the signed sum is negative for one winding direction and
    a shape's area does not depend on which way round it was drawn.
    """
    total = 0.0
    for (x1, y1), (x2, y2) in zip(projected, projected[1:] + projected[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _project(ring: list[Point], zone: int) -> list[tuple[float, float]]:
    """Corners as metres in one fixed UTM zone."""
    projected = []
    for point in ring:
        easting, northing, _zone_number, _band = _utm.from_latlon(
            point.lat, point.lon, force_zone_number=zone
        )
        projected.append((easting, northing))
    return projected


def _ring_problem(ring: list[Point]) -> str | None:
    """Why this ring cannot be measured, or None if it can."""
    if len(ring) < 3:
        return f"needs at least 3 distinct corners, found {len(ring)}"

    latitudes = [p.lat for p in ring]
    if min(latitudes) < _UTM_MIN_LAT or max(latitudes) > _UTM_MAX_LAT:
        return (
            "lies outside the range UTM covers "
            f"({_UTM_MIN_LAT:g} to {_UTM_MAX_LAT:g} degrees latitude)"
        )

    longitudes = [p.lon for p in ring]
    span = max(longitudes) - min(longitudes)
    if span > _MAX_LONGITUDE_SPAN:
        return (
            f"spans {span:.1f} degrees of longitude, more than the "
            f"{_MAX_LONGITUDE_SPAN:g} a single UTM zone covers"
        )

    return None


def polygon_area(outer: list[Point], holes: list[list[Point]]) -> Measurement:
    """Flat map area of a polygon, holes subtracted.

    Every corner -- outer and holes alike -- is projected in the zone of the
    outer ring's centroid. Letting each corner pick its own zone would mix two
    different grids and produce a meaningless number for any shape near a zone
    boundary.
    """
    ring = _distinct_corners(outer)

    problem = _ring_problem(ring)
    if problem is not None:
        return Measurement(None, problem)

    # One zone for the whole shape, chosen from the outer ring's centre.
    centre_lon = (max(p.lon for p in ring) + min(p.lon for p in ring)) / 2
    centre_lat = (max(p.lat for p in ring) + min(p.lat for p in ring)) / 2
    try:
        _e, _n, zone, _band = _utm.from_latlon(centre_lat, centre_lon)
    except Exception as exc:
        return Measurement(None, f"could not be projected ({exc})")

    try:
        total = _shoelace(_project(ring, zone))
        for hole in holes:
            hole_ring = _distinct_corners(hole)
            if _ring_problem(hole_ring) is not None:
                continue  # a hole too broken to measure simply is not subtracted
            total -= _shoelace(_project(hole_ring, zone))
    except Exception as exc:
        return Measurement(None, f"could not be measured ({exc})")

    if total <= 0:
        return Measurement(
            None, "its holes cover the whole shape, leaving no area"
        )

    return Measurement(total)
