"""Area measurement tests.

Areas are checked against an independent approximation rather than against
numbers this code produced, so a wrong implementation cannot define its own
expected answer. Near a given latitude a degree of latitude is about 111,320 m
and a degree of longitude about 111,320 * cos(lat) m, which is accurate enough
to catch any real error while tolerating a spherical estimate's own sub-percent
error.

The 1% tolerance is deliberately NOT widened for the ellipsoidal engine. Its
worst disagreement with this estimate across everything here is 0.67%, which
is the estimate's error and not the engine's -- if one of these fails, the
implementation is what changed.
"""

import math

import pytest

from kmz_points.geometry import (
    CROSSING_CHECK_CORNER_LIMIT,
    MAX_EXTENT_DEGREES,
    Measurement,
    polygon_area,
)
from kmz_points.models import Point

_METRES_PER_DEGREE = 111_320.0


def corner(lat, lon):
    return Point(name="", description="", lon=lon, lat=lat, alt=None, source_file="a.kml")


def box(lat, lon, size):
    """A square-ish box with its south-west corner at (lat, lon)."""
    return [
        corner(lat, lon),
        corner(lat, lon + size),
        corner(lat + size, lon + size),
        corner(lat + size, lon),
    ]


def approximate_area(lat, size):
    """Independent estimate of a `size` x `size` degree box at `lat`."""
    height = size * _METRES_PER_DEGREE
    width = size * _METRES_PER_DEGREE * math.cos(math.radians(lat + size / 2))
    return height * width


def approximate_perimeter(lat, size):
    """Independent estimate of the distance round that same box."""
    height = size * _METRES_PER_DEGREE
    width = size * _METRES_PER_DEGREE * math.cos(math.radians(lat + size / 2))
    return 2 * (height + width)


def wheel(count, lat=10.0, lon=20.0, radius=0.01, swap=None):
    """A `count`-corner ring on a circle, optionally tangled by one swap.

    Swapping two corners crosses the two edges that used to end at them, which
    is how a ring of a chosen size gets an intersection to find.
    """
    ring = [
        corner(
            lat + radius * math.sin(2 * math.pi * index / count),
            lon + radius * math.cos(2 * math.pi * index / count),
        )
        for index in range(count)
    ]
    if swap is not None:
        first, second = swap
        ring[first], ring[second] = ring[second], ring[first]
    return ring


class TestKnownShapes:
    def test_a_small_box_matches_an_independent_estimate(self):
        measured = polygon_area(box(0.0, 30.0, 0.01), [])
        expected = approximate_area(0.0, 0.01)
        assert measured.problem is None
        assert measured.square_metres == pytest.approx(expected, rel=0.01)

    def test_a_box_away_from_the_equator_also_matches(self):
        # Longitude degrees shorten with latitude; a box at 50N is much smaller
        # than the same box of degrees at the equator.
        measured = polygon_area(box(50.0, 30.0, 0.01), [])
        expected = approximate_area(50.0, 0.01)
        assert measured.square_metres == pytest.approx(expected, rel=0.01)

    def test_a_southern_box_is_measured_the_same_as_a_northern_one(self):
        north = polygon_area(box(40.0, 30.0, 0.01), []).square_metres
        south = polygon_area(box(-40.01, 30.0, 0.01), []).square_metres
        assert south == pytest.approx(north, rel=0.01)


class TestWindingAndClosure:
    def test_winding_order_does_not_change_the_area(self):
        clockwise = box(10.0, 20.0, 0.01)
        anticlockwise = list(reversed(clockwise))
        assert polygon_area(clockwise, []).square_metres == pytest.approx(
            polygon_area(anticlockwise, []).square_metres
        )

    def test_area_is_never_negative(self):
        # The excess sum is signed, like the shoelace sum before it;
        # forgetting the absolute value gives a negative area for one
        # winding direction.
        for ring in (box(10.0, 20.0, 0.01), list(reversed(box(10.0, 20.0, 0.01)))):
            assert polygon_area(ring, []).square_metres > 0

    def test_a_repeated_closing_corner_is_not_counted_twice(self):
        # KML writes rings closed: the last coordinate repeats the first.
        # Treating that as a real corner adds a zero-length edge, which is
        # free in the area sum and not free in the perimeter.
        ring = box(10.0, 20.0, 0.01)
        closed = ring + [ring[0]]
        assert polygon_area(closed, []).square_metres == pytest.approx(
            polygon_area(ring, []).square_metres
        )


class TestHoles:
    def test_a_hole_is_subtracted(self):
        outer = box(10.0, 20.0, 0.02)
        hole = box(10.005, 20.005, 0.01)
        whole = polygon_area(outer, []).square_metres
        hole_only = polygon_area(hole, []).square_metres
        assert polygon_area(outer, [hole]).square_metres == pytest.approx(
            whole - hole_only
        )

    def test_several_holes_are_all_subtracted(self):
        outer = box(10.0, 20.0, 0.03)
        first = box(10.002, 20.002, 0.005)
        second = box(10.015, 20.015, 0.005)
        expected = (
            polygon_area(outer, []).square_metres
            - polygon_area(first, []).square_metres
            - polygon_area(second, []).square_metres
        )
        assert polygon_area(outer, [first, second]).square_metres == pytest.approx(
            expected
        )

    def test_a_hole_bigger_than_its_outline_does_not_go_negative(self):
        outer = box(10.0, 20.0, 0.01)
        swallowing = box(10.0, 20.0, 0.05)
        result = polygon_area(outer, [swallowing])
        assert result.square_metres is None
        assert "hole" in result.problem.lower()


class TestUnmeasurableShapes:
    def test_two_corners_enclose_nothing(self):
        result = polygon_area([corner(10.0, 20.0), corner(10.01, 20.0)], [])
        assert result.square_metres is None
        assert "corner" in result.problem.lower()

    def test_repeated_corners_do_not_count_as_distinct(self):
        same = corner(10.0, 20.0)
        result = polygon_area([same, same, same], [])
        assert result.square_metres is None

    def test_an_empty_ring_is_refused(self):
        assert polygon_area([], []).square_metres is None

    def test_a_corner_off_the_world_is_refused(self):
        past_the_pole = box(10.0, 20.0, 0.01)
        past_the_pole[2] = corner(90.5, 20.01)
        result = polygon_area(past_the_pole, [])
        assert result.square_metres is None
        assert "not a place" in result.problem

    def test_a_longitude_past_the_antimeridian_is_refused(self):
        # 181 degrees is not a place. It used to surface as a projection
        # library's exception text, which the browser version could not
        # reproduce word for word.
        result = polygon_area(box(10.0, 180.5, 0.01), [])
        assert result.square_metres is None
        assert "not a place" in result.problem


class TestShapesTheProjectionUsedToRefuse:
    """Two refusals went away with the projection that caused them."""

    def test_a_polar_shape_is_measured(self):
        measured = polygon_area(box(85.0, 20.0, 0.01), [])
        assert measured.problem is None
        assert measured.square_metres == pytest.approx(
            approximate_area(85.0, 0.01), rel=0.01
        )

    def test_a_shape_beside_the_pole_is_measured(self):
        measured = polygon_area(box(89.98, 20.0, 0.01), [])
        assert measured.problem is None
        assert measured.square_metres == pytest.approx(
            approximate_area(89.98, 0.01), rel=0.01
        )

    def test_a_shape_wider_than_one_utm_zone_is_measured(self):
        # Six degrees is the width of a zone, and nothing here has zones now.
        wide = [
            corner(10.0, 0.0),
            corner(10.0, 6.25),
            corner(10.1, 6.25),
            corner(10.1, 0.0),
        ]
        assert polygon_area(wide, []).problem is None


class TestTheExtentCeiling:
    def test_exactly_at_the_ceiling_is_measured(self):
        # The ceiling is what a shape must EXCEED, so the boundary itself is
        # on the measurable side of it.
        assert polygon_area(box(0.0, 30.0, MAX_EXTENT_DEGREES), []).problem is None

    def test_just_over_the_ceiling_in_longitude_is_refused(self):
        result = polygon_area(box(0.0, 30.0, MAX_EXTENT_DEGREES + 1e-6), [])
        assert result.square_metres is None
        assert "larger than any plot" in result.problem

    def test_just_over_the_ceiling_in_latitude_is_refused(self):
        tall = [
            corner(0.0, 30.0),
            corner(0.0, 30.01),
            corner(MAX_EXTENT_DEGREES + 0.001, 30.01),
            corner(MAX_EXTENT_DEGREES + 0.001, 30.0),
        ]
        assert polygon_area(tall, []).square_metres is None

    def test_a_shape_straddling_the_antimeridian_is_not_called_wide(self):
        # Raw longitudes would put this ring 359.98 degrees across. What it
        # actually spans is 0.02, and the ceiling has to see that.
        across = [
            corner(10.0, 179.99),
            corner(10.0, -179.99),
            corner(10.01, -179.99),
            corner(10.01, 179.99),
        ]
        measured = polygon_area(across, [])
        assert measured.problem is None
        # The same box measured away from the antimeridian, to the metre.
        elsewhere = polygon_area(
            [
                corner(10.0, 20.0),
                corner(10.0, 20.02),
                corner(10.01, 20.02),
                corner(10.01, 20.0),
            ],
            [],
        )
        assert measured.square_metres == pytest.approx(elsewhere.square_metres)


class TestSelfIntersectingOutlines:
    def test_a_bowtie_is_refused(self):
        bowtie = [
            corner(10.0, 20.0),
            corner(10.0, 20.01),
            corner(10.01, 20.0),
            corner(10.01, 20.01),
        ]
        result = polygon_area(bowtie, [])
        assert result.square_metres is None
        assert result.problem == "its outline crosses itself"

    def test_a_lollipop_is_refused(self):
        lollipop = [
            corner(10.0, 20.0),
            corner(10.0, 20.01),
            corner(10.01, 20.01),
            corner(10.01, 20.0),
            corner(10.005, 20.005),
            corner(10.005, 20.02),
        ]
        assert polygon_area(lollipop, []).square_metres is None

    def test_a_figure_of_eight_pinched_at_one_corner_is_refused(self):
        # The two lobes share a single corner and cross nowhere. Two edges
        # that are not neighbours have no business touching at all.
        pinched = [
            corner(10.0, 20.0),
            corner(10.0, 20.01),
            corner(10.005, 20.005),
            corner(10.01, 20.01),
            corner(10.01, 20.0),
            corner(10.005, 20.005),
        ]
        assert polygon_area(pinched, []).square_metres is None

    def test_a_concave_outline_is_not_mistaken_for_a_crossed_one(self):
        # An L. Concave, and perfectly measurable.
        shape = [
            corner(10.0, 20.0),
            corner(10.0, 20.02),
            corner(10.01, 20.02),
            corner(10.01, 20.01),
            corner(10.02, 20.01),
            corner(10.02, 20.0),
        ]
        measured = polygon_area(shape, [])
        assert measured.problem is None
        # Three quarters of the 0.02 box it is cut from.
        whole = polygon_area(box(10.0, 20.0, 0.02), []).square_metres
        assert measured.square_metres == pytest.approx(whole * 0.75, rel=0.001)

    def test_corners_in_a_straight_line_are_not_a_crossing(self):
        # A midpoint on each side of a square. Every one of them makes two
        # edges collinear, which is where a touching test goes wrong.
        with_midpoints = [
            corner(10.0, 20.0),
            corner(10.0, 20.005),
            corner(10.0, 20.01),
            corner(10.005, 20.01),
            corner(10.01, 20.01),
            corner(10.01, 20.005),
            corner(10.01, 20.0),
            corner(10.005, 20.0),
        ]
        measured = polygon_area(with_midpoints, [])
        assert measured.problem is None
        assert measured.square_metres == pytest.approx(
            polygon_area(box(10.0, 20.0, 0.01), []).square_metres, rel=1e-6
        )

    def test_the_check_runs_at_the_corner_ceiling(self):
        tangled = wheel(CROSSING_CHECK_CORNER_LIMIT, swap=(10, 100))
        assert len(tangled) == CROSSING_CHECK_CORNER_LIMIT
        assert polygon_area(tangled, []).problem == "its outline crosses itself"

    def test_the_check_is_skipped_one_corner_past_the_ceiling(self):
        # Deliberate: past the ceiling the shape is measured rather than
        # refused, because a quadratic check on an enormous ring would cost
        # more than the wrong number it prevents.
        tangled = wheel(CROSSING_CHECK_CORNER_LIMIT + 1, swap=(10, 100))
        assert polygon_area(tangled, []).problem is None

    def test_a_ring_at_the_ceiling_that_is_fine_is_measured(self):
        measured = polygon_area(wheel(CROSSING_CHECK_CORNER_LIMIT), [])
        assert measured.problem is None
        # A 512-sided polygon inscribed in a circle of 0.01 degrees.
        radius = 0.01 * _METRES_PER_DEGREE * math.cos(math.radians(10.0))
        tall = 0.01 * _METRES_PER_DEGREE
        assert measured.square_metres == pytest.approx(math.pi * radius * tall, rel=0.01)


class TestHolesThatCannotBeMeasured:
    """A broken hole refuses the shape rather than being skipped.

    It used to be skipped with a bare `continue`, which reported a plot with a
    courtyard as LARGER than it is and said nothing on the sheet about why.
    """

    def test_a_hole_with_two_corners_refuses_the_shape(self):
        outer = box(10.0, 20.0, 0.02)
        broken = [corner(10.005, 20.005), corner(10.005, 20.01)]
        result = polygon_area(outer, [broken])
        assert result.square_metres is None
        assert result.problem == (
            "has a hole that cannot be measured: it needs at least 3 distinct "
            "corners, found 2"
        )

    def test_a_hole_off_the_world_refuses_the_shape(self):
        outer = box(10.0, 20.0, 0.02)
        broken = box(10.005, 20.005, 0.005)
        broken[1] = corner(10.005, 181.0)
        result = polygon_area(outer, [broken])
        assert result.square_metres is None
        assert "hole" in result.problem

    def test_the_refused_shape_is_the_one_that_used_to_read_too_large(self):
        # The number that used to come back was the outline's own area, with
        # the courtyard silently left in it.
        outer = box(10.0, 20.0, 0.02)
        broken = [corner(10.005, 20.005), corner(10.005, 20.01)]
        assert polygon_area(outer, []).square_metres > 0
        assert polygon_area(outer, [broken]).square_metres is None


class TestPerimeter:
    def test_a_box_matches_an_independent_estimate(self):
        measured = polygon_area(box(0.0, 30.0, 0.01), [])
        assert measured.perimeter_metres == pytest.approx(
            approximate_perimeter(0.0, 0.01), rel=0.01
        )

    def test_a_box_away_from_the_equator_also_matches(self):
        measured = polygon_area(box(50.0, 30.0, 0.01), [])
        assert measured.perimeter_metres == pytest.approx(
            approximate_perimeter(50.0, 0.01), rel=0.01
        )

    def test_the_outline_is_measured_and_not_the_holes(self):
        # A hole changes the area and leaves the outline exactly where it was.
        outer = box(10.0, 20.0, 0.02)
        hole = box(10.005, 20.005, 0.01)
        assert polygon_area(outer, [hole]).perimeter_metres == pytest.approx(
            polygon_area(outer, []).perimeter_metres
        )

    def test_winding_order_does_not_change_it(self):
        ring = box(10.0, 20.0, 0.01)
        assert polygon_area(list(reversed(ring)), []).perimeter_metres == pytest.approx(
            polygon_area(ring, []).perimeter_metres
        )

    def test_a_repeated_corner_adds_nothing(self):
        # A zero-length edge is a Vincenty inverse between coincident points,
        # which is 0 divided by 0 unless it is guarded.
        ring = box(10.0, 20.0, 0.01)
        doubled = [ring[0], ring[0], ring[1], ring[2], ring[2], ring[3]]
        assert polygon_area(doubled, []).perimeter_metres == pytest.approx(
            polygon_area(ring, []).perimeter_metres
        )

    def test_a_refused_shape_has_no_perimeter(self):
        assert polygon_area([], []).perimeter_metres is None


class TestNothingRaises:
    """The invariant the whole module is arranged around.

    Every one of these is a shape a real file has produced or could produce,
    and every one of them must come back as a Measurement carrying a reason.
    """

    @pytest.mark.parametrize(
        "ring",
        [
            [],
            [corner(10.0, 20.0)],
            [corner(10.0, 20.0), corner(10.01, 20.0)],
            [corner(10.0, 20.0)] * 3,
            [corner(float("nan"), 20.0), corner(10.0, 20.01), corner(10.01, 20.0)],
            [corner(10.0, float("nan")), corner(10.0, 20.01), corner(10.01, 20.0)],
            [corner(float("inf"), 20.0), corner(10.0, 20.01), corner(10.01, 20.0)],
            [corner(float("-inf"), 20.0), corner(10.0, 20.01), corner(10.01, 20.0)],
            [corner(10.0, float("inf")), corner(10.0, 20.01), corner(10.01, 20.0)],
            [corner(float("nan"), float("nan"))] * 4,
            [corner(1e308, 1e308), corner(-1e308, 1e308), corner(0.0, -1e308)],
            [corner(90.0, 0.0), corner(-90.0, 90.0), corner(0.0, 180.0)],
        ],
    )
    def test_a_degenerate_ring_returns_a_measurement(self, ring):
        result = polygon_area(ring, [])
        assert isinstance(result, Measurement)
        assert result.square_metres is None
        assert result.problem

    def test_a_degenerate_hole_returns_a_measurement(self):
        result = polygon_area(box(10.0, 20.0, 0.01), [[corner(float("nan"), 20.0)] * 3])
        assert isinstance(result, Measurement)
        assert result.problem

    def test_a_corner_that_is_not_a_number_at_all_is_not_a_place(self):
        # Nothing in this repository constructs one, and the promise is that
        # nothing raises rather than that nothing is malformed.
        ring = [corner("north", "east"), corner("south", "west"), corner(1.0, 2.0)]
        result = polygon_area(ring, [])
        assert result.problem == "has a corner that is not a place on Earth"


class TestUnits:
    def test_hectares_and_square_kilometres_derive_from_square_metres(self):
        measurement = Measurement(square_metres=1_234_567.0)
        assert measurement.hectares == pytest.approx(123.4567)
        assert measurement.square_kilometres == pytest.approx(1.234567)

    def test_units_are_none_when_the_area_is(self):
        measurement = Measurement(square_metres=None, problem="nope")
        assert measurement.hectares is None
        assert measurement.square_kilometres is None
