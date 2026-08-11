"""Table-building tests.

The column layout lives in one place so it can be re-ordered later; these
tests pin the contract that layout has to satisfy.

The sheet now has 24 columns split into four labelled bands (separation,
Combined D,M,S, separated D,M,S, details), and several headers repeat across
bands -- "longitude"/"latitude" appear in both the separation and Combined
bands, and "D"/"M"/"S" appear twice within the separated band, once for
latitude and once for longitude. ``column_index`` from kmz_points.table is
used instead of a local duplicate so a repeated header must be disambiguated
by band, the same rule the production code enforces.
"""

from kmz_points.models import Point
from kmz_points.table import (
    COLUMNS,
    COMBINED,
    SEPARATED,
    SEPARATION,
    build_table_rows,
    column_index,
    headers,
)

# Mirrors COLUMNS exactly, duplicates included, so test_headers_match_the_
# specified_layout pins the full 24-column order without importing COLUMNS
# itself.
EXPECTED_HEADERS = [
    "Name",
    "longitude",
    "latitude",
    "elevation",
    "#",
    "longitude",
    "latitude",
    "lat",
    "D",
    "M",
    "S",
    "long",
    "D",
    "M",
    "S",
    "Description",
    "Attributes",
    "Lat (DDM)",
    "Lon (DDM)",
    "UTM Zone",
    "Easting (m)",
    "Northing (m)",
    "MGRS",
    "Source File",
]


def make_point(
    lat=34.567890,
    lon=38.123456,
    alt=120.5,
    name="Alpha",
    source="a.kml",
    attributes="",
):
    return Point(
        name=name,
        description="desc",
        lon=lon,
        lat=lat,
        alt=alt,
        source_file=source,
        attributes=attributes,
    )


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
        number = column_index("#", band=COMBINED)
        assert [r[number] for r in rows] == [1, 2, 3]

    def test_name_and_source_are_carried_through(self):
        row = build_table_rows([make_point(name="Alpha", source="b.kmz")])[0]
        assert row[column_index("Name")] == "Alpha"
        assert row[column_index("Source File")] == "b.kmz"


class TestAttributes:
    """ExtendedData reaches the sheet already flattened, so the row builder
    only has to place it. The column it is placed in is the interesting part:
    both row builders emit positional arrays, so a cell in the wrong place
    shifts every column after it."""

    def test_the_flattened_extended_data_is_carried_through(self):
        row = build_table_rows([make_point(attributes="k=v; j=w")])[0]
        assert row[column_index("Attributes")] == "k=v; j=w"

    def test_a_placemark_with_no_extended_data_leaves_an_empty_cell(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Attributes")] == ""

    def test_it_sits_immediately_after_description(self):
        assert column_index("Attributes") == column_index("Description") + 1

    def test_it_does_not_displace_the_columns_after_it(self):
        row = build_table_rows([make_point(attributes="k=v")])[0]
        assert row[column_index("Lat (DDM)")] == "34° 34.0734' N"
        assert row[column_index("Source File")] == "a.kml"


class TestNumericCells:
    def test_decimal_degrees_are_floats_not_strings(self):
        row = build_table_rows([make_point()])[0]
        lat = column_index("latitude", band=SEPARATION)
        lon = column_index("longitude", band=SEPARATION)
        assert row[lat] == 34.567890
        assert row[lon] == 38.123456
        assert isinstance(row[lat], float)
        assert isinstance(row[lon], float)

    def test_easting_and_northing_are_integers(self):
        row = build_table_rows([make_point()])[0]
        easting = column_index("Easting (m)")
        northing = column_index("Northing (m)")
        assert row[easting] == 419595
        assert row[northing] == 3825474
        assert isinstance(row[easting], int)

    def test_altitude_is_a_float(self):
        row = build_table_rows([make_point(alt=120.5)])[0]
        assert row[column_index("elevation", band=SEPARATION)] == 120.5

    def test_missing_altitude_is_none_not_zero(self):
        row = build_table_rows([make_point(alt=None)])[0]
        assert row[column_index("elevation", band=SEPARATION)] is None


class TestFormattedTextCells:
    def test_ddm_columns_are_formatted_strings(self):
        row = build_table_rows([make_point()])[0]
        assert row[column_index("Lat (DDM)")] == "34° 34.0734' N"
        assert row[column_index("Lon (DDM)")] == "38° 7.4074' E"

    def test_dms_columns_are_formatted_strings(self):
        row = build_table_rows([make_point()])[0]
        lat = column_index("latitude", band=COMBINED)
        lon = column_index("longitude", band=COMBINED)
        assert row[lat] == "34° 34' 4.40\" N"
        assert row[lon] == "38° 7' 24.44\" E"

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


class TestSeparatedDegreesMinutesSeconds:
    """D/M/S are magnitudes -- degrees cannot carry a sign for a value between
    -1 and 0 -- so the hemisphere lives in the repeated decimal column beside
    them instead. Uses the same latitude as the "Bravo" sample point
    (-0.180653): south, but with a whole-degree part of 0, which has no sign
    of its own."""

    def test_lat_degrees_are_a_magnitude_even_when_south(self):
        row = build_table_rows([make_point(lat=-0.180653, lon=-78.467834)])[0]
        lat = column_index("lat", band=SEPARATED)
        d, m, s = lat + 1, lat + 2, lat + 3
        assert row[d] == 0
        assert row[m] == 10
        assert row[s] == 50.35
        assert row[d] >= 0 and row[m] >= 0 and row[s] >= 0

    def test_the_repeated_decimal_keeps_the_sign(self):
        row = build_table_rows([make_point(lat=-0.180653, lon=-78.467834)])[0]
        lat = column_index("lat", band=SEPARATED)
        assert row[lat] == -0.180653
        assert row[lat] < 0

    def test_lon_degrees_are_also_a_magnitude(self):
        row = build_table_rows([make_point(lat=-0.180653, lon=-78.467834)])[0]
        long_ = column_index("long", band=SEPARATED)
        d, m, s = long_ + 1, long_ + 2, long_ + 3
        assert row[d] == 78
        assert row[m] == 28
        assert row[s] == 4.2
        assert row[long_] == -78.467834
        assert row[long_] < 0

    def test_a_positive_point_still_matches_its_magnitude(self):
        # Guards against a test that would pass merely because abs() and the
        # signed value happen to look the same for a negative-only check.
        row = build_table_rows([make_point(lat=34.567890, lon=38.123456)])[0]
        lat = column_index("lat", band=SEPARATED)
        long_ = column_index("long", band=SEPARATED)
        assert row[lat + 1] == 34
        assert row[long_ + 1] == 38
        assert row[lat] == 34.567890
        assert row[long_] == 38.123456
