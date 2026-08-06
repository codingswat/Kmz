"""Writing the table out as a workbook."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from kmz_points.table import COLUMNS, headers

# Hard limit imposed by the xlsx format; a longer string makes the file
# unopenable rather than merely ugly.
EXCEL_CELL_LIMIT = 32767

_MIN_WIDTH = 8
_MAX_WIDTH = 60
_WIDTH_PADDING = 2


def output_filename(when: datetime | None = None) -> str:
    """``points_YYYYMMDD_HHMM.xlsx`` for the given moment (default: now)."""
    when = when or datetime.now()
    return f"points_{when:%Y%m%d_%H%M}.xlsx"


def _fit(value):
    """Clamp a cell value to what Excel will accept."""
    if isinstance(value, str) and len(value) > EXCEL_CELL_LIMIT:
        return value[: EXCEL_CELL_LIMIT - 3] + "..."
    return value


def _column_width(header: str, values: list) -> float:
    longest = max(
        [len(header)] + [len(str(v)) for v in values if v is not None],
        default=len(header),
    )
    return min(max(longest + _WIDTH_PADDING, _MIN_WIDTH), _MAX_WIDTH)


def write_workbook(rows: list[list], path: str | Path) -> Path:
    """Write rows to an xlsx file and return the path written."""
    path = Path(path)
    book = Workbook()
    sheet = book.active
    sheet.title = "Points"

    sheet.append(headers())
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"

    for row in rows:
        sheet.append([_fit(value) for value in row])

    for index, column in enumerate(COLUMNS, start=1):
        letter = get_column_letter(index)
        if column.number_format:
            for cell in sheet[letter][1:]:  # data rows only, skip the header
                cell.number_format = column.number_format
        sheet.column_dimensions[letter].width = _column_width(
            column.header, [row[index - 1] for row in rows]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path
