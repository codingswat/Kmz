"""Writing the table out as a workbook."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from kmz_points.table import (
    COLUMNS,
    NUMBER_INDEX,
    SOURCE_FILE_INDEX,
    bands,
    headers,
)

# Hard limit imposed by the xlsx format; a longer string makes the file
# unopenable rather than merely ugly.
EXCEL_CELL_LIMIT = 32767

_MIN_WIDTH = 8
_MAX_WIDTH = 60
_WIDTH_PADDING = 2

# Three header rows: band titles, band captions, then the column names. Data
# starts at row 4, and a grey banner naming the source file precedes each
# file's rows.
BAND_TITLE_ROW = 1
BAND_CAPTION_ROW = 2
HEADER_ROW = 3
FIRST_DATA_ROW = 4

_BANNER_FILL = "A6A6A6"
_CENTRED = Alignment(horizontal="center", vertical="center")


def _fill(colour: str) -> PatternFill:
    return PatternFill("solid", fgColor=colour)


def data_rows(sheet) -> list[tuple]:
    """The point rows of a Points sheet, skipping headers and file banners.

    max_row is no longer the point count: the sheet carries three header rows
    and one banner per source file. A banner sets only its first cell, so the
    numbered "#" column tells the two apart.
    """
    return [
        row
        for row in sheet.iter_rows(min_row=FIRST_DATA_ROW)
        if row[NUMBER_INDEX].value is not None
    ]


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


def _write_header(sheet) -> None:
    """Band titles, band captions, then the column names."""
    for band, start, end in bands():
        first = get_column_letter(start + 1)
        last = get_column_letter(end + 1)

        title = sheet.cell(row=BAND_TITLE_ROW, column=start + 1, value=band.title)
        title.font = Font(bold=True, size=12)
        title.alignment = _CENTRED
        if band.fill:
            title.fill = _fill(band.fill)

        caption = sheet.cell(row=BAND_CAPTION_ROW, column=start + 1)
        if band.caption:
            caption.value = band.caption
            caption.alignment = _CENTRED
            if band.caption_fill:
                caption.fill = _fill(band.caption_fill)
            sheet.merge_cells(f"{first}{BAND_CAPTION_ROW}:{last}{BAND_CAPTION_ROW}")
            sheet.merge_cells(f"{first}{BAND_TITLE_ROW}:{last}{BAND_TITLE_ROW}")
        else:
            # No caption, so the title claims both rows rather than leaving a
            # blank band beneath it.
            sheet.merge_cells(
                start_row=BAND_TITLE_ROW,
                start_column=start + 1,
                end_row=BAND_CAPTION_ROW,
                end_column=end + 1,
            )
            if band.fill:
                caption.fill = _fill(band.fill)

    for index, column in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=HEADER_ROW, column=index, value=column.header)
        cell.font = Font(bold=True)
        cell.alignment = _CENTRED
        if column.fill:
            cell.fill = _fill(column.fill)
        if column.font_colour:
            cell.font = Font(bold=True, color=column.font_colour)


def _write_body(sheet, rows: list[list]) -> list[int]:
    """Write the rows, banner-separated by source file.

    Returns the row numbers holding data, so number formats skip the banners.
    Grouping walks consecutive runs rather than sorting: points already arrive
    in file order, and sorting would renumber the batch out of sequence.
    """
    data_rows: list[int] = []
    current_file = None
    row_number = FIRST_DATA_ROW

    for row in rows:
        source = row[SOURCE_FILE_INDEX]
        if source != current_file:
            current_file = source
            banner = sheet.cell(row=row_number, column=1, value=source)
            banner.font = Font(bold=True, color="FFFFFF")
            banner.alignment = _CENTRED
            banner.fill = _fill(_BANNER_FILL)
            sheet.merge_cells(
                start_row=row_number,
                start_column=1,
                end_row=row_number,
                end_column=len(COLUMNS),
            )
            row_number += 1

        for index, value in enumerate(row, start=1):
            sheet.cell(row=row_number, column=index, value=_fit(value))
        data_rows.append(row_number)
        row_number += 1

    return data_rows


def write_workbook(
    rows: list[list],
    target: str | Path | BinaryIO,
    issues: list[str] | None = None,
) -> Path | None:
    """Write rows to an xlsx file, or into an open binary stream.

    The web service needs the workbook in memory, so a stream is accepted as
    well as a path. Returns the path written, or None for a stream.

    ``issues`` adds a second sheet naming files that could not be read. A
    browser download has nowhere else to report them: the response body is the
    workbook. The desktop app passes nothing and its output is unchanged.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Points"

    _write_header(sheet)
    data_rows = _write_body(sheet, rows)
    sheet.freeze_panes = f"A{FIRST_DATA_ROW}"

    for index, column in enumerate(COLUMNS, start=1):
        letter = get_column_letter(index)
        if column.number_format:
            for row_number in data_rows:
                sheet.cell(row=row_number, column=index).number_format = (
                    column.number_format
                )
        sheet.column_dimensions[letter].width = _column_width(
            column.header, [row[index - 1] for row in rows]
        )

    if issues:
        # Appended after Points, so opening the file lands on the data.
        notes = book.create_sheet("Issues")
        notes.append(["Issue"])
        notes["A1"].font = Font(bold=True)
        for line in issues:
            notes.append([_fit(line)])
        notes.column_dimensions["A"].width = _MAX_WIDTH

    if isinstance(target, (str, Path)):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        book.save(path)
        return path

    book.save(target)
    return None
