"""CLI tests. The CLI exists so the whole pipeline is runnable without a display."""

import pytest

from kmz_points.cli import main
from kmz_points.samples import write_samples


@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "in")


def xlsx_files(directory):
    return sorted(directory.glob("points_*.xlsx"))


class TestExport:
    def test_exits_zero_and_writes_a_workbook(self, samples, tmp_path, capsys):
        out = tmp_path / "out"
        code = main([str(p) for p in samples] + ["-o", str(out)])
        assert code == 0
        assert len(xlsx_files(out)) == 1

    def test_prints_a_summary(self, samples, tmp_path, capsys):
        main([str(p) for p in samples] + ["-o", str(tmp_path / "out")])
        printed = capsys.readouterr().out
        assert "7 point(s) extracted" in printed
        assert "2 non-point feature(s) skipped" in printed

    def test_defaults_output_to_the_first_inputs_folder(self, samples, capsys):
        code = main([str(p) for p in samples])
        assert code == 0
        assert len(xlsx_files(samples[0].parent)) == 1


class TestFailureHandling:
    def test_unreadable_file_is_reported_and_exits_nonzero(self, tmp_path, capsys):
        code = main([str(tmp_path / "absent.kml"), "-o", str(tmp_path)])
        assert code == 1
        assert "absent.kml" in capsys.readouterr().out

    def test_a_bad_file_does_not_stop_the_good_ones(self, samples, tmp_path, capsys):
        args = [str(p) for p in samples] + [str(tmp_path / "absent.kml")]
        code = main(args + ["-o", str(tmp_path / "out")])
        assert code == 0
        assert len(xlsx_files(tmp_path / "out")) == 1


class TestSampleGeneration:
    def test_make_samples_writes_the_three_inputs(self, tmp_path, capsys):
        code = main(["--make-samples", str(tmp_path / "generated")])
        assert code == 0
        assert len(list((tmp_path / "generated").iterdir())) == 3
