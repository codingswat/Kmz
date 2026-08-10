"""The one place the output table's shape is defined.

COLUMNS drives the header rows, the cell order and the Excel cell types, so
re-ordering or adding a column is a change to this list and nothing else.

Columns are grouped into bands. A band becomes a merged title across the top
of its columns, optionally with a second merged caption beneath it, so the
sheet reads as four labelled blocks rather than one undifferentiated row of
headers.
"""

from __future__ import annotations

from dataclasses import dataclass

from kmz_points.convert import dms_parts, format_ddm, format_dms, to_mgrs, to_utm
from kmz_points.models import Point


@dataclass(frozen=True)
class Band:
    """A labelled group of adjacent columns."""

    title: str
    caption: str | None = None  # second header row, e.g. "decimal degrees"
    fill: str | None = None  # title cell colour, aarrggbb without the alpha
    caption_fill: str | None = None


SEPARATION = Band("separation", "decimal degrees", "F8CBAD", "BDD7EE")
COMBINED = Band("Combined D,M,S", None, "B4C7E7")
SEPARATED = Band("separated D,M,S", None, "E2EFDA")
DETAILS = Band("details", None, "D9D9D9")


@dataclass(frozen=True)
class Column:
    header: str
    kind: str  # "number" -> real Excel number; "text" -> string cell
    band: Band
    number_format: str | None = None
    fill: str | None = None  # header cell colour
    font_colour: str | None = None


COLUMNS: list[Column] = [
    # separation -- decimal degrees
    Column("longitude", "number", SEPARATION, "0.000000", "F4B183"),
    Column("latitude", "number", SEPARATION, "0.000000", "F4B183"),
    Column("elevation", "number", SEPARATION, "0.00", "F4B183"),
    # Combined D,M,S
    Column("#", "number", COMBINED, "0", "2F5597", "FFFFFF"),
    Column("longitude", "text", COMBINED, None, "2F5597", "FFFFFF"),
    Column("latitude", "text", COMBINED, None, "2F5597", "FFFFFF"),
    # separated D,M,S -- the decimal repeats beside its own breakdown, and is
    # what carries the hemisphere, since D is a magnitude.
    Column("lat", "number", SEPARATED, "0.000000", "DDEBF7"),
    Column("D", "number", SEPARATED, "0", "DDEBF7"),
    Column("M", "number", SEPARATED, "0", "DDEBF7"),
    Column("S", "number", SEPARATED, "0.00", "DDEBF7"),
    Column("long", "number", SEPARATED, "0.000000", "E2EFDA"),
    Column("D", "number", SEPARATED, "0", "E2EFDA"),
    Column("M", "number", SEPARATED, "0", "E2EFDA"),
    Column("S", "number", SEPARATED, "0.00", "E2EFDA"),
    # details -- everything the mock-up does not show but nobody wanted to lose
    Column("Name", "text", DETAILS, None, "D9D9D9"),
    Column("Description", "text", DETAILS, None, "D9D9D9"),
    Column("Lat (DDM)", "text", DETAILS, None, "D9D9D9"),
    Column("Lon (DDM)", "text", DETAILS, None, "D9D9D9"),
    Column("UTM Zone", "text", DETAILS, None, "D9D9D9"),
    Column("Easting (m)", "number", DETAILS, "0", "D9D9D9"),
    Column("Northing (m)", "number", DETAILS, "0", "D9D9D9"),
    Column("MGRS", "text", DETAILS, None, "D9D9D9"),
    Column("Source File", "text", DETAILS, None, "D9D9D9"),
]

# Several headers repeat across bands -- "longitude" appears in two bands and
# D/M/S in two halves of one -- so a name alone does not identify a column.
SOURCE_FILE_INDEX = next(
    i for i, c in enumerate(COLUMNS) if c.header == "Source File"
)
NUMBER_INDEX = next(i for i, c in enumerate(COLUMNS) if c.header == "#")


def headers() -> list[str]:
    return [column.header for column in COLUMNS]


def column_index(header: str, band: Band | None = None) -> int:
    """Where a column sits, 0-based.

    A header alone is no longer unique -- "longitude" appears in two bands and
    D/M/S in both halves of the separated band -- so anything looking up a
    repeated header must say which band it means. Raises rather than silently
    returning the first match, because picking the wrong longitude column is
    exactly the sort of bug that reads as correct.
    """
    matches = [
        i
        for i, column in enumerate(COLUMNS)
        if column.header == header and (band is None or column.band is band)
    ]
    if not matches:
        raise KeyError(f"no column {header!r} in band {band.title if band else 'any'}")
    if len(matches) > 1:
        raise KeyError(
            f"{header!r} appears in several bands; pass band= to say which one"
        )
    return matches[0]


def bands() -> list[tuple[Band, int, int]]:
    """Each band with the inclusive column range it covers, 0-based."""
    spans: list[tuple[Band, int, int]] = []
    for index, column in enumerate(COLUMNS):
        if spans and spans[-1][0] is column.band:
            band, start, _ = spans[-1]
            spans[-1] = (band, start, index)
        else:
            spans.append((column.band, index, index))
    return spans


def _row_for(index: int, point: Point) -> list:
    """Build one row. Order must match COLUMNS."""
    utm_point = to_utm(point.lat, point.lon)
    mgrs_reference = to_mgrs(point.lat, point.lon)

    lat_d, lat_m, lat_s = dms_parts(point.lat)
    lon_d, lon_m, lon_s = dms_parts(point.lon)

    # DD columns carry the float so they stay sortable; the six-decimal
    # presentation is applied as a number format, not by stringifying.
    latitude = round(point.lat, 6)
    longitude = round(point.lon, 6)

    return [
        longitude,
        latitude,
        point.alt,
        index,
        format_dms(point.lon, "lon"),
        format_dms(point.lat, "lat"),
        latitude,
        lat_d,
        lat_m,
        lat_s,
        longitude,
        lon_d,
        lon_m,
        lon_s,
        point.name,
        point.description,
        format_ddm(point.lat, "lat"),
        format_ddm(point.lon, "lon"),
        utm_point.zone if utm_point else "",
        utm_point.easting if utm_point else None,
        utm_point.northing if utm_point else None,
        mgrs_reference or "",
        point.source_file,
    ]


def build_table_rows(points: list[Point]) -> list[list]:
    """Convert points into table rows, numbered from 1 across the whole batch."""
    return [_row_for(number, point) for number, point in enumerate(points, start=1)]
