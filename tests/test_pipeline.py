"""Pipeline tests, including a full end-to-end run over generated samples."""

import openpyxl
import pytest

from kmz_points.pipeline import export_to_excel, load_file, run
from kmz_points.samples import write_samples
from kmz_points.table import headers

# What write_samples() is defined to produce.
SAMPLE_POINT_TOTAL = 7
SAMPLE_SKIPPED_TOTAL = 2


@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "samples")


class TestWriteSamples:
    def test_creates_the_three_sample_inputs(self, samples):
        assert sorted(p.name for p in samples) == [
            "nested.kml",
            "sample.kmz",
            "simple.kml",
        ]

    def test_samples_exist_on_disk(self, samples):
        assert all(p.is_file() for p in samples)


class TestLoadFile:
    def test_loads_a_plain_kml(self, samples):
        simple = next(p for p in samples if p.name == "simple.kml")
        result = load_file(simple)
        assert result.point_count == 2
        assert result.error is None

    def test_loads_a_kmz(self, samples):
        kmz = next(p for p in samples if p.name == "sample.kmz")
        result = load_file(kmz)
        assert result.point_count == 2
        assert result.error is None

    def test_counts_non_point_features_without_extracting_them(self, samples):
        nested = next(p for p in samples if p.name == "nested.kml")
        result = load_file(nested)
        assert result.point_count == 3
        assert result.skipped == 2

    def test_points_are_attributed_to_their_source_file(self, samples):
        simple = next(p for p in samples if p.name == "simple.kml")
        assert {p.source_file for p in load_file(simple).points} == {"simple.kml"}

    def test_missing_file_is_reported_not_raised(self, tmp_path):
        result = load_file(tmp_path / "absent.kml")
        assert result.error is not None
        assert result.points == []

    def test_kmz_without_kml_is_reported_not_raised(self, tmp_path):
        import zipfile

        broken = tmp_path / "empty.kmz"
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("readme.txt", "nothing")
        assert load_file(broken).error is not None

    def test_file_with_zero_points_is_not_an_error(self, tmp_path):
        empty = tmp_path / "empty.kml"
        empty.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
        result = load_file(empty)
        assert result.error is None
        assert result.point_count == 0


class TestExport:
    def test_writes_a_workbook_named_by_pattern(self, samples, tmp_path):
        loaded = [load_file(p) for p in samples]
        summary = export_to_excel(loaded, tmp_path)
        assert summary.output_path is not None
        name = summary.output_path.rsplit("/", 1)[-1]
        assert name.startswith("points_") and name.endswith(".xlsx")

    def test_summary_counts_every_file_and_point(self, samples, tmp_path):
        summary = export_to_excel([load_file(p) for p in samples], tmp_path)
        assert summary.files_read == 3
        assert summary.points_extracted == SAMPLE_POINT_TOTAL
        assert summary.features_skipped == SAMPLE_SKIPPED_TOTAL
        assert summary.files_failed == 0

    def test_failed_files_are_counted_and_do_not_stop_the_export(
        self, samples, tmp_path
    ):
        loaded = [load_file(p) for p in samples] + [load_file(tmp_path / "absent.kml")]
        summary = export_to_excel(loaded, tmp_path)
        assert summary.files_failed == 1
        assert summary.points_extracted == SAMPLE_POINT_TOTAL
        assert summary.output_path is not None

    def test_export_with_no_points_writes_nothing_and_says_so(self, tmp_path):
        summary = export_to_excel([], tmp_path)
        assert summary.output_path is None
        assert summary.warnings


class TestEndToEnd:
    def test_run_produces_a_readable_workbook(self, samples, tmp_path):
        out = tmp_path / "out"
        summary = run(samples, out)
        book = openpyxl.load_workbook(summary.output_path)
        assert [c.value for c in book.active[1]] == headers()

    def test_every_extracted_point_becomes_a_row(self, samples, tmp_path):
        summary = run(samples, tmp_path / "out")
        book = openpyxl.load_workbook(summary.output_path)
        assert book.active.max_row == SAMPLE_POINT_TOTAL + 1

    def test_numbering_runs_unbroken_across_the_whole_batch(self, samples, tmp_path):
        summary = run(samples, tmp_path / "out")
        sheet = openpyxl.load_workbook(summary.output_path).active
        numbers = [sheet.cell(row=r, column=1).value for r in range(2, sheet.max_row + 1)]
        assert numbers == list(range(1, SAMPLE_POINT_TOTAL + 1))

    def test_no_mandatory_cell_is_left_empty(self, samples, tmp_path):
        summary = run(samples, tmp_path / "out")
        sheet = openpyxl.load_workbook(summary.output_path).active
        # Altitude and Description are legitimately optional; everything else
        # must be populated for every row.
        optional = {"Altitude (m)", "Description"}
        required = [
            i for i, h in enumerate(headers(), start=1) if h not in optional
        ]
        for row in range(2, sheet.max_row + 1):
            for column in required:
                value = sheet.cell(row=row, column=column).value
                assert value not in (None, ""), (
                    f"row {row} column {headers()[column - 1]!r} is empty"
                )

    def test_all_three_source_files_are_represented(self, samples, tmp_path):
        summary = run(samples, tmp_path / "out")
        sheet = openpyxl.load_workbook(summary.output_path).active
        column = headers().index("Source File") + 1
        sources = {sheet.cell(row=r, column=column).value for r in range(2, sheet.max_row + 1)}
        assert sources == {"simple.kml", "nested.kml", "sample.kmz"}

    def test_output_lands_in_the_requested_directory(self, samples, tmp_path):
        out = tmp_path / "chosen"
        summary = run(samples, out)
        assert summary.output_path.startswith(str(out))
