"""Conversion tests.

Reference DDM/DMS values are computed by hand (degrees, minutes = frac*60,
seconds = frac*60) rather than taken from the implementation. UTM and MGRS
references come from the utm/mgrs libraries, which are the authorities here --
our code only wraps and formats them.
"""

import pytest

from kmz_points.convert import format_dd, format_ddm, format_dms, to_mgrs, to_utm

# name, lat, lon
REF1 = 34.567890, 38.123456  # mid-latitude, northern + eastern
REF2 = 0.0, 0.0  # null island -- zero on both axes
REF3 = -33.856784, 151.215297  # Sydney -- southern + eastern
REF4 = -0.180653, -78.467834  # Quito -- southern + western, sub-degree latitude


class TestFormatDD:
    def test_positive_value_has_six_decimals(self):
        assert format_dd(34.567890) == "34.567890"

    def test_negative_value_keeps_sign(self):
        assert format_dd(-78.467834) == "-78.467834"

    def test_zero_is_unsigned(self):
        assert format_dd(0.0) == "0.000000"

    def test_tiny_negative_does_not_render_as_negative_zero(self):
        assert format_dd(-0.0000001) == "0.000000"

    def test_rounds_to_six_decimals(self):
        assert format_dd(1.23456789) == "1.234568"


class TestFormatDDM:
    def test_reference_latitude(self):
        assert format_ddm(REF1[0], "lat") == "34° 34.0734' N"

    def test_reference_longitude(self):
        assert format_ddm(REF1[1], "lon") == "38° 7.4074' E"

    def test_southern_latitude_uses_S(self):
        assert format_ddm(REF3[0], "lat") == "33° 51.4070' S"

    def test_western_longitude_uses_W(self):
        assert format_ddm(REF4[1], "lon") == "78° 28.0700' W"

    def test_sub_degree_southern_latitude(self):
        assert format_ddm(REF4[0], "lat") == "0° 10.8392' S"

    def test_zero_latitude_is_north(self):
        assert format_ddm(0.0, "lat") == "0° 0.0000' N"

    def test_zero_longitude_is_east(self):
        assert format_ddm(0.0, "lon") == "0° 0.0000' E"

    def test_minutes_never_display_as_sixty(self):
        # naive formatting yields "34° 60.0000' N"
        assert format_ddm(34.99999999, "lat") == "35° 0.0000' N"

    def test_carry_over_on_negative_value(self):
        assert format_ddm(-0.99999999, "lat") == "1° 0.0000' S"

    def test_north_pole(self):
        assert format_ddm(90.0, "lat") == "90° 0.0000' N"

    def test_south_pole(self):
        assert format_ddm(-90.0, "lat") == "90° 0.0000' S"

    def test_antimeridian_east(self):
        assert format_ddm(180.0, "lon") == "180° 0.0000' E"

    def test_antimeridian_west(self):
        assert format_ddm(-180.0, "lon") == "180° 0.0000' W"

    def test_rejects_unknown_axis(self):
        with pytest.raises(ValueError):
            format_ddm(10.0, "elevation")


class TestFormatDMS:
    def test_reference_latitude(self):
        assert format_dms(REF1[0], "lat") == "34° 34' 4.40\" N"

    def test_reference_longitude(self):
        assert format_dms(REF1[1], "lon") == "38° 7' 24.44\" E"

    def test_southern_latitude_uses_S(self):
        assert format_dms(REF3[0], "lat") == "33° 51' 24.42\" S"

    def test_eastern_longitude(self):
        assert format_dms(REF3[1], "lon") == "151° 12' 55.07\" E"

    def test_western_longitude_uses_W(self):
        assert format_dms(REF4[1], "lon") == "78° 28' 4.20\" W"

    def test_zero_is_north(self):
        assert format_dms(0.0, "lat") == "0° 0' 0.00\" N"

    def test_seconds_never_display_as_sixty(self):
        # naive formatting yields "34° 0' 60.00"" -- seconds must carry into minutes
        assert format_dms(34.0166666, "lat") == "34° 1' 0.00\" N"

    def test_carry_cascades_from_seconds_through_minutes_to_degrees(self):
        # naive formatting yields "34° 59' 60.00""
        assert format_dms(34.99999999, "lat") == "35° 0' 0.00\" N"

    def test_carry_over_on_negative_value(self):
        assert format_dms(-0.99999999, "lat") == "1° 0' 0.00\" S"

    def test_north_pole(self):
        assert format_dms(90.0, "lat") == "90° 0' 0.00\" N"

    def test_antimeridian_west(self):
        assert format_dms(-180.0, "lon") == "180° 0' 0.00\" W"

    def test_rejects_unknown_axis(self):
        with pytest.raises(ValueError):
            format_dms(10.0, "elevation")


class TestToUTM:
    def test_reference_point(self):
        r = to_utm(*REF1)
        assert (r.zone, r.easting, r.northing) == ("37S", 419595, 3825474)

    def test_label_matches_spec_format(self):
        assert to_utm(*REF1).label == "37S 419595 E 3825474 N"

    def test_null_island(self):
        r = to_utm(*REF2)
        assert (r.zone, r.easting, r.northing) == ("31N", 166021, 0)

    def test_southern_hemisphere_uses_band_letter_not_hemisphere(self):
        # 56H -- H is the latitude band, not "hemisphere south"
        r = to_utm(*REF3)
        assert (r.zone, r.easting, r.northing) == ("56H", 334900, 6252291)

    def test_southern_western_point(self):
        r = to_utm(*REF4)
        assert (r.zone, r.easting, r.northing) == ("17M", 781858, 9980013)

    def test_easting_and_northing_are_whole_numbers(self):
        r = to_utm(*REF1)
        assert isinstance(r.easting, int) and isinstance(r.northing, int)

    def test_returns_none_above_utm_limit(self):
        # UTM is undefined beyond 84N; must not raise
        assert to_utm(89.5, 10.0) is None

    def test_returns_none_below_utm_limit(self):
        assert to_utm(-85.0, 10.0) is None


class TestToMGRS:
    def test_reference_point(self):
        assert to_mgrs(*REF1) == "37SDU1959425474"

    def test_null_island(self):
        assert to_mgrs(*REF2) == "31NAA6602100000"

    def test_southern_hemisphere(self):
        assert to_mgrs(*REF3) == "56HLH3490052290"

    def test_returns_none_when_undefined_rather_than_raising(self):
        assert to_mgrs(91.0, 0.0) is None
