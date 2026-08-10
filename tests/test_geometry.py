"""Area measurement tests.

Areas are checked against an independent approximation rather than against
numbers this code produced, so a wrong implementation cannot define its own
expected answer. Near a given latitude a degree of latitude is about 111,320 m
and a degree of longitude about 111,320 * cos(lat) m, which is accurate enough
to catch any real error while tolerating the projection's own sub-percent
distortion.
"""

import math

import pytest

from kmz_points.geometry import Measurement, polygon_area
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
        # The shoelace sum is signed; forgetting the absolute value gives a
        # negative area for one winding direction.
        for ring in (box(10.0, 20.0, 0.01), list(reversed(box(10.0, 20.0, 0.01)))):
            assert polygon_area(ring, []).square_metres > 0

    def test_a_repeated_closing_corner_is_not_counted_twice(self):
        # KML writes rings closed: the last coordinate repeats the first.
        # Treating that as a real corner is a classic shoelace bug.
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

    def test_a_polar_shape_is_refused_rather_than_guessed(self):
        result = polygon_area(box(85.0, 20.0, 0.01), [])
        assert result.square_metres is None
        assert "utm" in result.problem.lower()

    def test_a_shape_spanning_many_zones_is_refused(self):
        wide = [
            corner(10.0, 0.0),
            corner(10.0, 20.0),
            corner(10.1, 20.0),
            corner(10.1, 0.0),
        ]
        result = polygon_area(wide, [])
        assert result.square_metres is None
        assert "longitude" in result.problem.lower()

    def test_an_empty_ring_is_refused(self):
        assert polygon_area([], []).square_metres is None


class TestUnits:
    def test_hectares_and_square_kilometres_derive_from_square_metres(self):
        measurement = Measurement(square_metres=1_234_567.0)
        assert measurement.hectares == pytest.approx(123.4567)
        assert measurement.square_kilometres == pytest.approx(1.234567)

    def test_units_are_none_when_the_area_is(self):
        measurement = Measurement(square_metres=None, problem="nope")
        assert measurement.hectares is None
        assert measurement.square_kilometres is None
