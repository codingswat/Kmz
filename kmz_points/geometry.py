"""Measuring shapes.

Separate from convert.py, which converts one point at a time and knows nothing
about how points relate to each other. Everything here is a pure function and
nothing raises: an unmeasurable shape comes back as a Measurement carrying the
reason, so one bad polygon can never abort a batch.

The area is FLAT MAP AREA -- the shape as traced on a map, not surface area
following the terrain. A sloping hillside's true surface is larger than its
footprint, and the elevation data needed to compute that is not in a KML.

Measurement is on the ELLIPSOID, not on a projection. Corners used to be
forced into a single UTM zone and run through the shoelace formula, which cost
up to 0.2% and refused anything polar or wider than one zone. Area now comes
from the spherical excess on the authalic sphere -- the sphere with the same
surface area as WGS-84 -- and perimeter from a Vincenty inverse per edge.

Measured against geographiclib over the 138 measurable shapes in the CI
fixtures: on anything the size of a plot, which is every shape a real file has
produced, the error is between 5e-12 and 3e-8 relative, against 2.0e-3 for the
shoelace it replaces. It grows with the shape, reaching 1.6e-5 on the largest
one the extent ceiling below admits. Perimeter agrees to 1.8e-8 throughout.

No dependency was added for this. geographiclib would be exact to millimetres
in Python and would need roughly 780 lines of ported numerics vendored into
web/src to keep the browser version in step. Running the SAME formula in both
languages makes parity exact by construction rather than something to chase,
which is worth more here than decimal places that sit well below the precision
of a KML coordinate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kmz_points.models import Area, Point

# WGS-84, the ellipsoid every KML coordinate is expressed on.
_SEMI_MAJOR = 6378137.0
_FLATTENING = 1 / 298.257223563
_SEMI_MINOR = _SEMI_MAJOR * (1 - _FLATTENING)
_ECCENTRICITY_SQUARED = _FLATTENING * (2 - _FLATTENING)
_ECCENTRICITY = math.sqrt(_ECCENTRICITY_SQUARED)


def _authalic_q(sin_lat: float) -> float:
    """The area function q, whose value at the pole scales the whole sphere.

    q(sin lat) is proportional to the area of the ellipsoid between the
    equator and that latitude, so a latitude mapped by q/q(1) keeps areas
    rather than angles -- which is the whole trick.
    """
    return (1 - _ECCENTRICITY_SQUARED) * (
        sin_lat / (1 - _ECCENTRICITY_SQUARED * sin_lat * sin_lat)
        - (1 / (2 * _ECCENTRICITY))
        * math.log((1 - _ECCENTRICITY * sin_lat) / (1 + _ECCENTRICITY * sin_lat))
    )


_Q_AT_POLE = _authalic_q(1.0)
# The sphere with WGS-84's surface area: 6371007.1809 m.
_AUTHALIC_RADIUS = _SEMI_MAJOR * math.sqrt(_Q_AT_POLE / 2)


def _authalic_latitude(lat_degrees: float) -> float:
    """Geodetic latitude mapped onto the sphere of equal area."""
    ratio = _authalic_q(math.sin(math.radians(lat_degrees))) / _Q_AT_POLE
    # Clamped because the ratio is 1 at the pole to within rounding, and asin
    # of 1.0000000000000002 raises.
    return math.asin(max(-1.0, min(1.0, ratio)))


# Vincenty converges in a handful of iterations for anything this tool
# measures. The cap is there so a pathological pair cannot spin forever, not
# because it is expected to be reached.
_VINCENTY_ITERATIONS = 200
_VINCENTY_TOLERANCE = 1e-12

# Public so web/test/generate-fixtures.py can put them in the fixture and the
# browser version can be asserted against the same two numbers. A ceiling that
# drifted between the implementations would refuse a shape in one and measure
# it in the other, which is the failure this whole file is arranged to prevent.
#
# THIS IS THE ONE NUMBER IN THE DESIGN CHOSEN BY JUDGEMENT RATHER THAN
# MEASUREMENT. Dropping the projection dropped the only thing that used to
# catch a mis-keyed coordinate: a single wrong digit turns a parcel into a
# continent and the new maths would measure it without complaint. Every real
# shape in the CI fixtures -- everything but the handful added to sit either
# side of this line -- is under 0.05 degrees, so 10 leaves about two hundred
# times headroom over anything real while still catching a corner displaced to
# another continent. Raise it if a real file ever hits it. It
# replaces a 6-degree limit that existed because of the projection, so it is
# deliberately not 6.
MAX_EXTENT_DEGREES = 10.0

# Above this many corners the self-intersection check is skipped and the shape
# is measured. The check is naive all-pairs, which is microseconds on the tens
# to low hundreds of corners a real ring has and quadratic beyond that.
CROSSING_CHECK_CORNER_LIMIT = 512

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
#
# Nothing here interpolates a caught exception's text. That is why the two
# earlier projection refusals are gone rather than reworded: they carried a
# Python library's wording into a banner an end user reads, and no
# implementation in another language could reproduce it.
NOT_ENOUGH_CORNERS = "needs at least 3 distinct corners, found {count}"
CORNER_OFF_THE_WORLD = "has a corner that is not a place on Earth"
TOO_LARGE = "is larger than any plot this tool is meant to measure"
OUTLINE_CROSSES_ITSELF = "its outline crosses itself"
# A hole that could not be measured used to be skipped in silence, which
# reported a plot with a courtyard as LARGER than it is. A wrong number that
# looks reasonable is the worst failure mode here, so the whole shape is now
# refused and the hole's own reason is carried through.
HOLE_NOT_MEASURABLE = "has a hole that cannot be measured: it {problem}"
HOLES_COVER_EVERYTHING = "its holes cover the whole shape, leaving no area"

REFUSALS = [
    NOT_ENOUGH_CORNERS,
    CORNER_OFF_THE_WORLD,
    TOO_LARGE,
    OUTLINE_CROSSES_ITSELF,
    HOLE_NOT_MEASURABLE,
    HOLES_COVER_EVERYTHING,
]


@dataclass(frozen=True)
class Measurement:
    """An area and the distance round it, or the reason there is neither."""

    square_metres: float | None
    problem: str | None = None
    # Defaulted so Measurement(size) and Measurement(None, reason) keep
    # working; it is None for exactly the shapes square_metres is None for.
    perimeter_metres: float | None = None

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
    that as a real corner adds a zero-length edge to every sum here.
    """
    kept: list[Point] = []
    for point in ring:
        if kept and point.lat == kept[-1].lat and point.lon == kept[-1].lon:
            continue
        kept.append(point)
    while len(kept) > 1 and kept[0].lat == kept[-1].lat and kept[0].lon == kept[-1].lon:
        kept.pop()
    return kept


def _folded(degrees: float) -> float:
    """An angle folded into (-180, 180].

    A loop rather than a remainder because the two languages disagree about
    the sign of `%`: JavaScript keeps the sign of its left operand where
    Python takes its right, so the obvious one-liner folds +357 correctly and
    leaves -357 exactly where it was. Deltas here are at most a full turn, so
    this runs at most twice.
    """
    while degrees > 180.0:
        degrees -= 360.0
    while degrees <= -180.0:
        degrees += 360.0
    return degrees


def _unwrapped_longitudes(ring: list[Point]) -> list[float]:
    """Longitudes walked round the ring with the antimeridian jump taken out.

    Raw min and max would call any ring straddling 180 degrees 359 degrees
    wide and refuse it, when what it actually spans is metres. Stepping by the
    folded difference gives the span a person would measure, and it is also
    the coordinate the crossing check needs -- two edges either side of the
    antimeridian are neighbours on the ground and must be compared as such.
    """
    values = [ring[0].lon]
    for index in range(1, len(ring)):
        step = _folded(ring[index].lon - ring[index - 1].lon)
        values.append(values[index - 1] + step)
    return values


def _off_the_world(point: Point) -> bool:
    """True when a corner is not a place on Earth.

    NaN and infinity get here from a coordinate the parser could not make
    sense of, and they would otherwise travel silently through every formula
    below. The TypeError guard keeps the promise that nothing raises: a
    coordinate that is not a number is not a place either.
    """
    try:
        return not (
            math.isfinite(point.lat)
            and math.isfinite(point.lon)
            and -90.0 <= point.lat <= 90.0
            and -180.0 <= point.lon <= 180.0
        )
    except TypeError:
        return True


def _ring_problem(ring: list[Point]) -> str | None:
    """Why this ring cannot be measured, or None if it can.

    Everything a hole is checked for too. The crossing check is not here: it
    applies to the outline alone -- see _crosses_itself.
    """
    if len(ring) < 3:
        return NOT_ENOUGH_CORNERS.format(count=len(ring))

    if any(_off_the_world(point) for point in ring):
        return CORNER_OFF_THE_WORLD

    latitudes = [point.lat for point in ring]
    longitudes = _unwrapped_longitudes(ring)
    if (
        max(latitudes) - min(latitudes) > MAX_EXTENT_DEGREES
        or max(longitudes) - min(longitudes) > MAX_EXTENT_DEGREES
    ):
        return TOO_LARGE

    return None


def _orientation(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float
) -> float:
    """Which way the path A to B to C turns: positive left, negative right.

    Only its sign is read, and the arithmetic is four multiplications of
    doubles, so both languages compute the same bits.
    """
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _within(
    ax: float, ay: float, bx: float, by: float, px: float, py: float
) -> bool:
    """True when P, already known to be collinear with AB, lies inside it."""
    return (
        min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)
    )


def _segments_cross(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
) -> bool:
    """True when segment first-second meets segment third-fourth.

    Touching counts. Two edges of a ring that are not neighbours have no
    business sharing a point, and a figure-8 pinched at a single corner is as
    unmeasurable as one whose lobes overlap.
    """
    ax, ay = first
    bx, by = second
    cx, cy = third
    dx, dy = fourth

    d1 = _orientation(cx, cy, dx, dy, ax, ay)
    d2 = _orientation(cx, cy, dx, dy, bx, by)
    d3 = _orientation(ax, ay, bx, by, cx, cy)
    d4 = _orientation(ax, ay, bx, by, dx, dy)

    # The ordinary case: each segment has the other's endpoints on opposite
    # sides of it.
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True

    # And the collinear ones, where an endpoint lies on the other segment.
    return (
        (d1 == 0 and _within(cx, cy, dx, dy, ax, ay))
        or (d2 == 0 and _within(cx, cy, dx, dy, bx, by))
        or (d3 == 0 and _within(ax, ay, bx, by, cx, cy))
        or (d4 == 0 and _within(ax, ay, bx, by, dx, dy))
    )


def _crosses_itself(ring: list[Point]) -> bool:
    """True when the outline crosses or touches itself away from a corner.

    Naive all-pairs over non-adjacent edges, in degrees. A sweep line would be
    asymptotically better and would need a tuned event queue and a comparison
    budget -- constants that no cross-check could hold identical between the
    two languages, in exchange for microseconds on rings this size.

    Only the outer ring is checked. Whether a hole sits inside the outline, or
    whether two holes overlap, is deliberately out of scope: neither makes the
    reported number meaningless the way a crossed outline does, and both cost
    a containment test this file does not otherwise need.
    """
    count = len(ring)
    if count > CROSSING_CHECK_CORNER_LIMIT:
        return False

    longitudes = _unwrapped_longitudes(ring)
    corners = [(longitudes[i], ring[i].lat) for i in range(count)]

    for i in range(count):
        for j in range(i + 1, count):
            # Adjacent edges share an endpoint by construction, so they always
            # "touch". The gap is on the index, and count - 1 is the wraparound
            # pair -- the last edge ends where the first one starts.
            if j - i in (1, count - 1):
                continue
            if _segments_cross(
                corners[i],
                corners[(i + 1) % count],
                corners[j],
                corners[(j + 1) % count],
            ):
                return True
    return False


def _ring_area(ring: list[Point]) -> float:
    """Area of one ring on the authalic sphere, in square metres.

    Each corner's geodetic latitude becomes the authalic latitude -- the
    latitude on a sphere of equal area -- and the spherical excess is summed
    edge by edge in the TANGENT form. The naive excess formula loses all its
    significant digits on a polygon a few hundred metres across, which is the
    normal case here; this form keeps them.

    Absolute, because the signed sum is negative for one winding direction and
    a shape's size does not depend on which way round it was drawn. Taking the
    magnitude per ring is also what makes a hole's winding irrelevant.
    """
    count = len(ring)
    half_tangents = [
        math.tan(_authalic_latitude(point.lat) / 2) for point in ring
    ]

    total = 0.0
    for i in range(count):
        j = (i + 1) % count
        # Folding the step into (-pi, pi] is the whole antimeridian handling:
        # a ring crossing 180 degrees needs no special case.
        delta = math.radians(_folded(ring[j].lon - ring[i].lon))
        first, second = half_tangents[i], half_tangents[j]
        total += 2 * math.atan2(
            math.tan(delta / 2) * (first + second), 1 + first * second
        )

    return abs(total) * _AUTHALIC_RADIUS * _AUTHALIC_RADIUS


def _vincenty(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres along the ellipsoid between two points.

    Vincenty's inverse formula. It is iterative and famously fails to converge
    for near-antipodal points; the extent ceiling means nothing here is more
    than a few degrees across, so the loop is a handful of passes and the
    iteration cap is a guard rather than a working limit.
    """
    reduced1 = math.atan((1 - _FLATTENING) * math.tan(math.radians(lat1)))
    reduced2 = math.atan((1 - _FLATTENING) * math.tan(math.radians(lat2)))
    sin_u1, cos_u1 = math.sin(reduced1), math.cos(reduced1)
    sin_u2, cos_u2 = math.sin(reduced2), math.cos(reduced2)

    difference = math.radians(_folded(lon2 - lon1))
    angle = difference

    sin_sigma = 0.0
    cos_sigma = 1.0
    sigma = 0.0
    cos_sq_alpha = 1.0
    cos_2sigma_m = 0.0

    for _ in range(_VINCENTY_ITERATIONS):
        sin_angle, cos_angle = math.sin(angle), math.cos(angle)
        # Written out rather than through hypot: the two languages' hypot are
        # separately implemented, and this is four multiplications and a
        # square root that both compute to the same bits.
        across = cos_u2 * sin_angle
        along = cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_angle
        sin_sigma = math.sqrt(across * across + along * along)
        # Coincident corners. A ring can hold two of them, and 0/0 below is a
        # ZeroDivisionError in Python and a NaN in JavaScript -- neither is a
        # distance, and both would poison the sum.
        if sin_sigma == 0.0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_angle
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_angle / sin_sigma
        cos_sq_alpha = 1 - sin_alpha * sin_alpha
        # Zero along the equator, where there is no vertex to measure from.
        cos_2sigma_m = (
            cos_sigma - 2 * sin_u1 * sin_u2 / cos_sq_alpha if cos_sq_alpha else 0.0
        )
        correction = (
            _FLATTENING
            / 16
            * cos_sq_alpha
            * (4 + _FLATTENING * (4 - 3 * cos_sq_alpha))
        )
        previous = angle
        angle = difference + (1 - correction) * _FLATTENING * sin_alpha * (
            sigma
            + correction
            * sin_sigma
            * (
                cos_2sigma_m
                + correction * cos_sigma * (-1 + 2 * cos_2sigma_m * cos_2sigma_m)
            )
        )
        if abs(angle - previous) < _VINCENTY_TOLERANCE:
            break

    u_squared = (
        cos_sq_alpha
        * (_SEMI_MAJOR * _SEMI_MAJOR - _SEMI_MINOR * _SEMI_MINOR)
        / (_SEMI_MINOR * _SEMI_MINOR)
    )
    term_a = 1 + u_squared / 16384 * (
        4096 + u_squared * (-768 + u_squared * (320 - 175 * u_squared))
    )
    term_b = (
        u_squared / 1024 * (256 + u_squared * (-128 + u_squared * (74 - 47 * u_squared)))
    )
    delta_sigma = (
        term_b
        * sin_sigma
        * (
            cos_2sigma_m
            + term_b
            / 4
            * (
                cos_sigma * (-1 + 2 * cos_2sigma_m * cos_2sigma_m)
                - term_b
                / 6
                * cos_2sigma_m
                * (-3 + 4 * sin_sigma * sin_sigma)
                * (-3 + 4 * cos_2sigma_m * cos_2sigma_m)
            )
        )
    )
    return _SEMI_MINOR * term_a * (sigma - delta_sigma)


def _ring_perimeter(ring: list[Point]) -> float:
    """The distance round one ring, edge by edge along the ellipsoid.

    The outline only. A hole's boundary is a second fence rather than part of
    the first, and the banner names one shape's outline.
    """
    count = len(ring)
    total = 0.0
    for i in range(count):
        j = (i + 1) % count
        total += _vincenty(ring[i].lat, ring[i].lon, ring[j].lat, ring[j].lon)
    return total


def polygon_area(outer: list[Point], holes: list[list[Point]]) -> Measurement:
    """Area of a polygon on the ellipsoid, holes subtracted, and its perimeter.

    Each ring is measured by its own spherical excess and subtracted by
    magnitude, so no ring's winding direction changes the answer and no two
    rings are measured against different grids the way a forced projection
    made possible.
    """
    ring = _distinct_corners(outer)

    problem = _ring_problem(ring)
    if problem is not None:
        return Measurement(None, problem)

    if _crosses_itself(ring):
        # Both the shoelace and the excess return a signed sum for a crossed
        # ring, in which the lobes partly cancel. The number that would come
        # out is the area of nothing at all.
        return Measurement(None, OUTLINE_CROSSES_ITSELF)

    total = _ring_area(ring)
    for hole in holes:
        hole_ring = _distinct_corners(hole)
        hole_problem = _ring_problem(hole_ring)
        if hole_problem is not None:
            return Measurement(None, HOLE_NOT_MEASURABLE.format(problem=hole_problem))
        total -= _ring_area(hole_ring)

    if total <= 0:
        return Measurement(None, HOLES_COVER_EVERYTHING)

    return Measurement(total, None, _ring_perimeter(ring))


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
