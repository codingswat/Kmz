"""The GUI must refuse to export into a folder that does not exist."""

import pytest

from kmz_points.samples import write_samples


def _tk_usable() -> bool:
    try:
        import tkinter

        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _tk_usable(), reason="no usable Tk display")


@pytest.fixture
def app():
    from kmz_points.gui import App, _Inline

    # Inline, so loading and exporting -- both threaded in the real window --
    # have finished by the time the call returns.
    notifications = []
    instance = App(
        notify=lambda *args: notifications.append(args), executor=_Inline()
    )
    instance.notifications = notifications
    yield instance
    instance.root.destroy()


@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "in")


class TestRejectsBadFolder:
    def test_missing_folder_writes_nothing(self, app, samples, tmp_path):
        missing = tmp_path / "out" / "typo" / "path"
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(missing))
        app.export()
        assert not missing.exists()

    def test_missing_folder_is_reported_in_the_status_bar(self, app, samples, tmp_path):
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(tmp_path / "nope"))
        app.export()
        assert "does not exist" in app.status.get().lower()

    def test_missing_folder_raises_an_error_notification(self, app, samples, tmp_path):
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(tmp_path / "nope"))
        app.export()
        assert app.notifications[-1][0] == "error"

    def test_a_file_as_output_folder_is_rejected(self, app, samples, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x")
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(target))
        app.export()
        assert app.notifications[-1][0] == "error"


class TestStillExportsWhenFolderIsGood:
    def test_valid_folder_exports_as_before(self, app, samples, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        assert len(list(out.glob("points_*.xlsx"))) == 1

    def test_valid_folder_still_reports_success(self, app, samples, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.output_dir.set(str(out))
        app.export()
        assert app.notifications[-1][0] == "info"
