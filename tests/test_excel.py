"""Excel writer tests -- every assertion is made against a reopened workbook."""

import io
from datetime import datetime

import openpyxl
import pytest
from openpyxl import load_workbook

from kmz_points.excel import EXCEL_CELL_LIMIT, output_filename, write_workbook
from kmz_points.models import Point
from kmz_points.table import build_table_rows, headers


def make_point(alt=120.5, description="desc"):
    return Point(
        name="Alpha",
        description=description,
        lon=38.123456,
        lat=34.567890,
        alt=alt,
        source_file="a.kml",
    )


def write_and_reopen(tmp_path, points):
    path = tmp_path / "out.xlsx"
    write_workbook(build_table_rows(points), path)
    return openpyxl.load_workbook(path)


class TestOutputFilename:
    def test_uses_the_specified_pattern(self):
        stamp = datetime(2026, 8, 6, 14, 35)
        assert output_filename(stamp) == "points_20260806_1435.xlsx"

    def test_pads_single_digit_components(self):
        stamp = datetime(2026, 1, 2, 3, 4)
        assert output_filename(stamp) == "points_20260102_0304.xlsx"


class TestHeaderRow:
    def test_header_matches_the_table_layout(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        written = [c.value for c in sheet[1]]
        assert written == headers()

    def test_header_is_bold(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        assert all(c.font.bold for c in sheet[1])

    def test_top_row_is_frozen(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        assert sheet.freeze_panes == "A2"

    def test_column_widths_are_set(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        widths = [d.width for d in sheet.column_dimensions.values()]
        assert len(widths) == len(headers())
        assert all(w and w > 0 for w in widths)


class TestCellTypes:
    def test_decimal_degrees_are_stored_as_numbers(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        cell = sheet.cell(row=2, column=headers().index("Lat (DD)") + 1)
        assert isinstance(cell.value, float)
        assert cell.value == pytest.approx(34.567890)

    def test_decimal_degrees_display_six_places(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        cell = sheet.cell(row=2, column=headers().index("Lat (DD)") + 1)
        assert cell.number_format == "0.000000"

    def test_easting_is_stored_as_a_number(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        cell = sheet.cell(row=2, column=headers().index("Easting (m)") + 1)
        assert isinstance(cell.value, int)
        assert cell.value == 419595

    def test_altitude_is_stored_as_a_number(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        cell = sheet.cell(row=2, column=headers().index("Altitude (m)") + 1)
        assert cell.value == pytest.approx(120.5)

    def test_dms_column_is_stored_as_text(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point()]).active
        cell = sheet.cell(row=2, column=headers().index("Lat (DMS)") + 1)
        assert isinstance(cell.value, str)
        assert cell.value == "34° 34' 4.40\" N"

    def test_missing_altitude_leaves_the_cell_empty(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point(alt=None)]).active
        cell = sheet.cell(row=2, column=headers().index("Altitude (m)") + 1)
        assert cell.value is None


class TestOversizedContent:
    def test_description_longer_than_excel_allows_is_truncated(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point(description="x" * 40000)]).active
        cell = sheet.cell(row=2, column=headers().index("Description") + 1)
        assert len(cell.value) <= EXCEL_CELL_LIMIT

    def test_truncation_is_marked_rather_than_silent(self, tmp_path):
        sheet = write_and_reopen(tmp_path, [make_point(description="x" * 40000)]).active
        cell = sheet.cell(row=2, column=headers().index("Description") + 1)
        assert cell.value.endswith("...")


class TestRows:
    def test_every_point_gets_a_row(self, tmp_path):
        book = write_and_reopen(tmp_path, [make_point(), make_point(), make_point()])
        assert book.active.max_row == 4  # header + 3

    def test_empty_input_still_writes_a_header(self, tmp_path):
        book = write_and_reopen(tmp_path, [])
        assert [c.value for c in book.active[1]] == headers()
        assert book.active.max_row == 1


class TestWritingToAStream:
    """The web service needs a workbook in memory, never on disk."""

    def test_a_stream_target_produces_a_readable_workbook(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer)
        buffer.seek(0)
        sheet = load_workbook(buffer).active
        assert [c.value for c in sheet[1]] == headers()
        assert sheet.max_row == 2

    def test_a_stream_target_returns_no_path(self):
        assert write_workbook(build_table_rows([make_point()]), io.BytesIO()) is None

    def test_a_path_target_still_returns_its_path(self, tmp_path):
        target = tmp_path / "out.xlsx"
        assert write_workbook(build_table_rows([make_point()]), target) == target


class TestIssuesSheet:
    """A browser download has nowhere to show a warning, so failures ride
    along inside the workbook."""

    def test_no_issues_means_no_second_sheet(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer)
        buffer.seek(0)
        assert load_workbook(buffer).sheetnames == ["Points"]

    def test_issues_are_listed_on_their_own_sheet(self):
        buffer = io.BytesIO()
        write_workbook(
            build_table_rows([make_point()]),
            buffer,
            issues=["broken.kmz: not a readable KMZ archive"],
        )
        buffer.seek(0)
        book = load_workbook(buffer)
        assert book.sheetnames == ["Points", "Issues"]
        listed = [row[0].value for row in book["Issues"].iter_rows(min_row=2)]
        assert listed == ["broken.kmz: not a readable KMZ archive"]

    def test_the_points_sheet_stays_first(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer, issues=["a problem"])
        buffer.seek(0)
        # Opening the file must land on the data, not on the complaints.
        assert load_workbook(buffer).active.title == "Points"

    def test_an_empty_issue_list_adds_no_sheet(self, tmp_path):
        target = tmp_path / "out.xlsx"
        write_workbook(build_table_rows([make_point()]), target, issues=[])
        assert load_workbook(target).sheetnames == ["Points"]
