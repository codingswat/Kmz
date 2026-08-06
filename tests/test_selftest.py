"""Tests for the frozen-bundle self check.

This is what CI runs against the built .exe/.dmg/binary. A bundle can link and
launch while still failing to load tkdnd or libmgrs, so the check has to
exercise those, not just import the package.
"""

from kmz_points.selftest import run_selftest


class TestSelfTest:
    def test_passes_in_a_working_environment(self):
        code, report = run_selftest()
        assert code == 0, report

    def test_report_names_every_check(self):
        _code, report = run_selftest()
        for check in ("parse", "utm", "mgrs", "excel"):
            assert check in report

    def test_report_states_the_overall_result(self):
        _code, report = run_selftest()
        assert "PASS" in report

    def test_exercises_mgrs_rather_than_just_importing_it(self):
        # A bundle missing libmgrs imports mgrs fine and fails at first call.
        _code, report = run_selftest()
        assert "37SDU1959425474" in report

    def test_reports_whether_drag_and_drop_is_available(self):
        _code, report = run_selftest()
        assert "tkdnd" in report

    def test_writes_and_reads_back_a_real_workbook(self):
        _code, report = run_selftest()
        assert "7 rows" in report
