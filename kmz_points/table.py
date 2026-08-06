"""The one place the output table's shape is defined.

COLUMNS drives the header row, the cell order and the Excel cell types, so
re-ordering or adding a column is a change to this list and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from kmz_points.convert import format_ddm, format_dms, to_mgrs, to_utm
from kmz_points.models import Point


@dataclass(frozen=True)
class Column:
    header: str
    kind: str  # "number" -> real Excel number; "text" -> string cell
    number_format: str | None = None


COLUMNS: list[Column] = [
    Column("No.", "number", "0"),
    Column("Name", "text"),
    Column("Description", "text"),
    Column("Lat (DD)", "number", "0.000000"),
    Column("Lon (DD)", "number", "0.000000"),
    Column("Lat (DDM)", "text"),
    Column("Lon (DDM)", "text"),
    Column("Lat (DMS)", "text"),
    Column("Lon (DMS)", "text"),
    Column("UTM Zone", "text"),
    Column("Easting (m)", "number", "0"),
    Column("Northing (m)", "number", "0"),
    Column("MGRS", "text"),
    Column("Altitude (m)", "number", "0.00"),
    Column("Source File", "text"),
]


def headers() -> list[str]:
    return [column.header for column in COLUMNS]


def _row_for(index: int, point: Point) -> list:
    """Build one row. Order must match COLUMNS."""
    utm_point = to_utm(point.lat, point.lon)
    mgrs_reference = to_mgrs(point.lat, point.lon)

    return [
        index,
        point.name,
        point.description,
        # DD columns carry the float so they stay sortable; the six-decimal
        # presentation is applied as a number format, not by stringifying.
        round(point.lat, 6),
        round(point.lon, 6),
        format_ddm(point.lat, "lat"),
        format_ddm(point.lon, "lon"),
        format_dms(point.lat, "lat"),
        format_dms(point.lon, "lon"),
        utm_point.zone if utm_point else "",
        utm_point.easting if utm_point else None,
        utm_point.northing if utm_point else None,
        mgrs_reference or "",
        point.alt,
        point.source_file,
    ]


def build_table_rows(points: list[Point]) -> list[list]:
    """Convert points into table rows, numbered from 1 across the whole batch."""
    return [_row_for(number, point) for number, point in enumerate(points, start=1)]
