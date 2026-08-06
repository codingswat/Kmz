"""Table-building tests.

The column layout lives in one place so it can be re-ordered later; these
tests pin the contract that layout has to satisfy.
"""

from kmz_points.models import Point
from kmz_points.table import COLUMNS, build_table_rows, headers

EXPECTED_HEADERS = [
    "No.",
    "Name",
    "Description",
    "Lat (DD)",
    "Lon (DD)",
    "Lat (DDM)",
    "Lon (DDM)",
    "Lat (DMS)",
    "Lon (DMS)",
    "UTM Zone",
    "Easting (m)",
    "Northing (m)",
    "MGRS",
    "Altitude (m)",
    "Source File",
]


def make_point(lat=34.567890, lon=38.123456, alt=120.5, name="Alpha", source="a.kml"):
    return Point(
        name=name,
        description="desc",
        lon=lon,
        lat=lat,
        alt=alt,
        source_file=source,
    )


def column_index(header):
    return EXPECTED_HEADERS.index(header)


class TestHeaders:
    def test_headers_match_the_specified_layout(self):
        assert headers() == EXPECTED_HEADERS

    def test_every_column_declares_a_kind(self):
        assert all(c.kind in ("number", "text") for c in COLUMNS)

    def test_headers_are_derived_from_the_column_specs(self):
        assert headers() == [c.header for c in COLUMNS]


class TestRowValues:
    def test_one_row_per_point(self):
        rows = build_table_rows([make_point(), make_point()])
        assert len(rows) == 2

    def test_row_width_matches_header_width(self):
        row = build_table_rows([make_point()])[0]
        assert len(row) == len(EXPECTED_HEADERS)

    def test_numbering_starts_at_one_and_increments(self):
        rows = build_table_rows([make_point(), make_point(), make_point()])
        assert [r[column_index("No.")] for r in rows] == [1, 2, 3]

    def test_name_and_source_are_carried_through(self):
        row = build_table_rows([make_point(name="Alpha", source="b.kmz")])[0]
        assert row[column_index("Name")] == "Alpha"
        assert row[column_index("Source File")] == "b.kmz"


class TestNumericCells:
    def test_decimal_degrees_are_floats_not_strings(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Lat (DD)")] == 34.567890
        assert row[column_index("Lon (DD)")] == 38.123456
        assert isinstance(row[column_index("Lat (DD)")], float)
        assert isinstance(row[column_index("Lon (DD)")], float)

    def test_easting_and_northing_are_integers(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Easting (m)")] == 419595
        assert row[column_index("Northing (m)")] == 3825474
        assert isinstance(row[column_index("Easting (m)")], int)

    def test_altitude_is_a_float(self):
        row = build_table_rows([make_point(alt=120.5)])[0]
        assert row[column_index("Altitude (m)")] == 120.5

    def test_missing_altitude_is_none_not_zero(self):
        row = build_table_rows([make_point(alt=None)])[0]
        assert row[column_index("Altitude (m)")] is None


class TestFormattedTextCells:
    def test_ddm_columns_are_formatted_strings(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Lat (DDM)")] == "34° 34.0734' N"
        assert row[column_index("Lon (DDM)")] == "38° 7.4074' E"

    def test_dms_columns_are_formatted_strings(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Lat (DMS)")] == "34° 34' 4.40\" N"
        assert row[column_index("Lon (DMS)")] == "38° 7' 24.44\" E"

    def test_utm_zone_carries_the_band_letter(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("UTM Zone")] == "37S"

    def test_mgrs_is_populated(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("MGRS")] == "37SDU1959425474"


class TestUndefinedConversions:
    def test_polar_point_leaves_utm_cells_empty_rather_than_failing(self):
        row = build_table_rows([make_point(lat=89.5, lon=10.0)])[0]
        assert row[column_index("UTM Zone")] == ""
        assert row[column_index("Easting (m)")] is None
        assert row[column_index("Northing (m)")] is None

    def test_polar_point_still_produces_ddm_and_dms(self):
        row = build_table_rows([make_point(lat=89.5, lon=10.0)])[0]
        assert row[column_index("Lat (DDM)")] == "89° 30.0000' N"

    def test_row_is_still_full_width_when_conversions_are_undefined(self):
        row = build_table_rows([make_point(lat=89.5, lon=10.0)])[0]
        assert len(row) == len(EXPECTED_HEADERS)
