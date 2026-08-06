"""GUI tests.

Widget construction needs a display; these run under Xvfb in CI and skip
elsewhere. The drop-payload parser is pure and always runs -- it is the part
of the drag-and-drop path most likely to break silently, because tkdnd
brace-quotes any path containing a space.
"""

import os

import pytest

from kmz_points.gui import parse_drop_payload
from kmz_points.samples import write_samples

pytestmark_gui = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="no display available"
)


class TestParseDropPayload:
    def test_single_plain_path(self):
        assert parse_drop_payload("/tmp/a.kml") == ["/tmp/a.kml"]

    def test_multiple_plain_paths(self):
        assert parse_drop_payload("/tmp/a.kml /tmp/b.kmz") == ["/tmp/a.kml", "/tmp/b.kmz"]

    def test_braced_path_containing_spaces(self):
        assert parse_drop_payload("{/tmp/my places.kml}") == ["/tmp/my places.kml"]

    def test_mix_of_braced_and_plain(self):
        payload = "{/tmp/my places.kml} /tmp/b.kmz {/tmp/other file.kmz}"
        assert parse_drop_payload(payload) == [
            "/tmp/my places.kml",
            "/tmp/b.kmz",
            "/tmp/other file.kmz",
        ]

    def test_windows_style_path(self):
        assert parse_drop_payload(r"C:\data\a.kml") == [r"C:\data\a.kml"]

    def test_empty_payload(self):
        assert parse_drop_payload("") == []

    def test_whitespace_only_payload(self):
        assert parse_drop_payload("   ") == []


@pytestmark_gui
class TestApp:
    @pytest.fixture
    def app(self):
        from kmz_points.gui import App

        # Record notifications instead of opening modals, which would block
        # forever with nobody there to dismiss them.
        notifications = []
        instance = App(notify=lambda *args: notifications.append(args))
        instance.notifications = notifications
        yield instance
        instance.root.destroy()

    @pytest.fixture
    def samples(self, tmp_path):
        return write_samples(tmp_path / "in")

    def test_window_builds(self, app):
        assert app.root.title()

    def test_drop_zone_shows_the_expected_prompt(self, app):
        assert "Drag KML / KMZ files here" in app.drop_label.cget("text")

    def test_adding_files_lists_them_with_point_counts(self, app, samples):
        app.add_paths([str(p) for p in samples])
        entries = app.file_list.get(0, "end")
        assert len(entries) == 3
        assert any("simple.kml" in e and "2 point" in e for e in entries)
        assert any("nested.kml" in e and "3 point" in e for e in entries)

    def test_unreadable_file_is_listed_as_failed_not_dropped(self, app, tmp_path):
        app.add_paths([str(tmp_path / "absent.kml")])
        assert "FAILED" in app.file_list.get(0)

    def test_the_same_file_is_not_added_twice(self, app, samples):
        app.add_paths([str(samples[0])])
        app.add_paths([str(samples[0])])
        assert app.file_list.size() == 1

    def test_output_folder_defaults_to_the_first_inputs_folder(self, app, samples):
        app.add_paths([str(p) for p in samples])
        assert app.output_dir.get() == str(samples[0].parent)

    def test_removing_a_selection_drops_it_from_the_list(self, app, samples):
        app.add_paths([str(p) for p in samples])
        app.file_list.selection_set(0)
        app.remove_selected()
        assert app.file_list.size() == 2

    def test_removing_updates_the_loaded_files_too(self, app, samples):
        app.add_paths([str(p) for p in samples])
        app.file_list.selection_set(0)
        app.remove_selected()
        assert len(app.loaded) == 2

    def test_export_writes_a_workbook_and_reports_it(self, app, samples, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        assert len(list(out.glob("points_*.xlsx"))) == 1

    def test_export_summary_reaches_the_status_bar(self, app, samples, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        assert "7 point" in app.status.get()

    def test_export_with_nothing_loaded_reports_rather_than_crashing(self, app):
        app.export()
        assert "No files" in app.status.get()

    def test_successful_export_raises_a_completion_notification(
        self, app, samples, tmp_path
    ):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        kinds = [kind for kind, _title, _message in app.notifications]
        assert "info" in kinds

    def test_completion_notification_names_the_output_file(
        self, app, samples, tmp_path
    ):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        message = app.notifications[-1][2]
        assert "points_" in message and "7 point(s) extracted" in message
