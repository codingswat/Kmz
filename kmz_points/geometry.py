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

from kmz_points.models import Area, Point

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

# Every reason a shape can be refused, written down once.
#
# They are templates rather than words spelled out at the point of refusal
# because the browser port has to reproduce them character for character: a
# refusal that reads differently in the two versions is the same defect as a
# number that differs, and harder to notice. web/test/refusal.test.mjs
# compares this list against the one in web/src/geometry.js, so a reason added
# to one side and not the other fails the build.
NOT_ENOUGH_CORNERS = "needs at least 3 distinct corners, found {count}"
OUTSIDE_UTM_RANGE = "lies outside the range UTM covers ({low} to {high} degrees latitude)"
LONGITUDE_TOO_WIDE = (
    "spans {span} degrees of longitude, more than the {limit} a single UTM zone covers"
)
# These two carried the caught exception's text, which was wrong twice over:
# it put a Python library's wording into a spreadsheet banner an end user
# reads, and it could never be reproduced by an implementation in another
# language, so the two versions refused the same shape with different words.
# Nothing is lost -- both branches mean "the projection rejected a coordinate
# that had already passed every check above", which is what the reader needs.
COULD_NOT_PROJECT = "could not be projected"
COULD_NOT_MEASURE = "could not be measured"
HOLES_COVER_EVERYTHING = "its holes cover the whole shape, leaving no area"

REFUSALS = [
    NOT_ENOUGH_CORNERS,
    OUTSIDE_UTM_RANGE,
    LONGITUDE_TOO_WIDE,
    COULD_NOT_PROJECT,
    COULD_NOT_MEASURE,
    HOLES_COVER_EVERYTHING,
]


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
    # strict: both arguments are the same ring, so a length mismatch would be
    # a bug rather than an input we should tolerate.
    for (x1, y1), (x2, y2) in zip(
        projected, projected[1:] + projected[:1], strict=True
    ):
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
        return NOT_ENOUGH_CORNERS.format(count=len(ring))

    latitudes = [p.lat for p in ring]
    if min(latitudes) < _UTM_MIN_LAT or max(latitudes) > _UTM_MAX_LAT:
        return OUTSIDE_UTM_RANGE.format(
            low=f"{_UTM_MIN_LAT:g}", high=f"{_UTM_MAX_LAT:g}"
        )

    longitudes = [p.lon for p in ring]
    span = max(longitudes) - min(longitudes)
    if span > _MAX_LONGITUDE_SPAN:
        return LONGITUDE_TOO_WIDE.format(
            span=f"{span:.1f}", limit=f"{_MAX_LONGITUDE_SPAN:g}"
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
    except Exception:
        return Measurement(None, COULD_NOT_PROJECT)

    try:
        total = _shoelace(_project(ring, zone))
        for hole in holes:
            hole_ring = _distinct_corners(hole)
            if _ring_problem(hole_ring) is not None:
                continue  # a hole too broken to measure simply is not subtracted
            total -= _shoelace(_project(hole_ring, zone))
    except Exception:
        return Measurement(None, COULD_NOT_MEASURE)

    if total <= 0:
        return Measurement(None, HOLES_COVER_EVERYTHING)

    return Measurement(total)


@dataclass(frozen=True)
class MeasuredArea:
    """An area paired with its size, ready to be written out.

    Pairing them here keeps the spreadsheet writer from importing the
    measurement maths, and keeps the pipeline from formatting banner text.
    """

    area: Area
    measurement: Measurement


def measure(area: Area) -> MeasuredArea:
    """Measure one area, holes included."""
    return MeasuredArea(area, polygon_area(area.outer, area.holes))
