"""The window must stay usable while a batch reads or a workbook writes.

These drive the real threaded path -- the default executor, no inline
shortcut -- so they pump the Tk event loop themselves rather than relying on
mainloop, which never returns. The inline executor the other GUI tests use
would hide the one thing under test here.

Several tests hold a load open with a gate. That is the only way to observe
the window mid-batch: the sample files parse in well under a millisecond, so
without the gate the work is over before an assertion can look at it.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk

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

_BUTTONS = ("browse_button", "remove_button", "clear_button", "export_button")


def _states(app) -> set[str]:
    return {str(getattr(app, name).cget("state")) for name in _BUTTONS}


class _Gate:
    """A load that parks the worker on its first file until released.

    Stands in for the large KMZ nobody wants to keep in the repository.
    """

    def __init__(self, real):
        self._real = real
        self._released = threading.Event()
        self.started = threading.Event()
        self.calls: list[str] = []

    def __call__(self, path):
        self.calls.append(str(path))
        if not self.started.is_set():
            self.started.set()
            self._released.wait(timeout=10)
        return self._real(path)

    def release(self):
        self._released.set()

    def wait_for_work_to_begin(self):
        assert self.started.wait(timeout=10), "the worker never reached the first file"


@pytest.fixture
def app():
    from kmz_points.gui import App

    # No executor argument: this is the real one, a background thread.
    notifications = []
    instance = App(notify=lambda *args: notifications.append(args))
    instance.notifications = notifications
    yield instance
    instance.root.destroy()


@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "in")


@pytest.fixture
def gate(monkeypatch):
    from kmz_points import gui

    holder = _Gate(gui.load_file)
    monkeypatch.setattr(gui, "load_file", holder)
    yield holder
    # A test that failed before releasing would otherwise leave a worker
    # parked for ten seconds and the whole run waiting on it.
    holder.release()


class TestWorkLeavesTheMainThread:
    def test_loading_runs_off_the_main_thread(self, app, samples, monkeypatch):
        from kmz_points import gui

        real = gui.load_file
        threads = []

        def recording(path):
            threads.append(threading.current_thread())
            return real(path)

        monkeypatch.setattr(gui, "load_file", recording)
        app.add_paths([str(samples[0])])
        app.wait_until_idle()

        assert threads, "load_file was never called"
        assert threading.main_thread() not in threads

    def test_exporting_runs_off_the_main_thread(self, app, samples, tmp_path, monkeypatch):
        from kmz_points import gui

        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.wait_until_idle()

        real = gui.export_to_excel
        threads = []

        def recording(loaded, output_dir, *args, **kwargs):
            threads.append(threading.current_thread())
            return real(loaded, output_dir, *args, **kwargs)

        monkeypatch.setattr(gui, "export_to_excel", recording)
        app.output_dir.set(str(out))
        app.export()
        app.wait_until_idle()

        assert threads, "export_to_excel was never called"
        assert threading.main_thread() not in threads
        assert len(list(out.glob("points_*.xlsx"))) == 1

    def test_the_event_loop_keeps_running_while_a_file_loads(self, app, samples, gate):
        ticks = []

        def tick():
            ticks.append(time.monotonic())
            app.root.after(1, tick)

        app.root.after(1, tick)
        app.add_paths([str(samples[0])])
        gate.wait_for_work_to_begin()

        # Under the old code load_file ran here, on this thread, and not one
        # of these ticks could have fired until it returned.
        deadline = time.monotonic() + 5
        while len(ticks) < 20 and time.monotonic() < deadline:
            app.root.update()

        assert len(ticks) >= 20, "the main thread was blocked by the load"

        gate.release()
        app.wait_until_idle()
        assert len(app.loaded) == 1

    def test_the_worker_closes_over_no_widget(self, samples, tmp_path):
        from kmz_points import gui

        submitted = []

        class Capturing:
            """Records the work, then runs it inline so the window still works."""

            def submit(self, work):
                submitted.append(work)
                work()

        out = tmp_path / "out"
        out.mkdir()
        instance = gui.App(notify=lambda *args: None, executor=Capturing())
        try:
            instance.add_paths([str(p) for p in samples])
            instance.output_dir.set(str(out))
            instance.export()
        finally:
            instance.root.destroy()

        assert len(submitted) == 2, "expected one load job and one export job"
        for work in submitted:
            for cell in work.__closure__ or ():
                value = cell.cell_contents
                assert not isinstance(value, tk.Misc | tk.Variable | gui.App), value


class TestTheWindowSaysWhatItIsDoing:
    def test_the_buttons_are_disabled_while_a_batch_runs(self, app, samples, gate):
        app.add_paths([str(p) for p in samples])
        gate.wait_for_work_to_begin()
        app.root.update()

        assert _states(app) == {"disabled"}

        gate.release()
        app.wait_until_idle()

        assert _states(app) == {"normal"}

    def test_the_status_line_says_a_batch_is_being_read(self, app, samples, gate):
        app.add_paths([str(p) for p in samples])
        gate.wait_for_work_to_begin()

        assert "Reading 3 file(s)" in app.status.get()

        gate.release()
        app.wait_until_idle()
        assert app.status.get() == "3 file(s) loaded, 7 point(s) found."

    def test_the_workbook_is_written_with_the_window_still_alive(
        self, app, samples, tmp_path, monkeypatch
    ):
        from kmz_points import gui

        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.wait_until_idle()

        # The export equivalent of the load gate: hold openpyxl open so the
        # window can be inspected while the write is in flight. The stub reads
        # no widget -- doing that from the worker is what this whole
        # arrangement forbids, and Tk raises if you try.
        real = gui.export_to_excel
        started, release = threading.Event(), threading.Event()

        def blocking(loaded, output_dir, *args, **kwargs):
            started.set()
            release.wait(timeout=10)
            return real(loaded, output_dir, *args, **kwargs)

        monkeypatch.setattr(gui, "export_to_excel", blocking)
        app.output_dir.set(str(out))
        app.export()
        assert started.wait(timeout=10), "the export never reached the worker"

        assert app.status.get() == "Writing the workbook..."
        assert _states(app) == {"disabled"}

        release.set()
        app.wait_until_idle()

        assert "7 point(s) extracted" in app.status.get()
        assert _states(app) == {"normal"}


class TestWorkArrivingMidBatch:
    def test_files_added_while_busy_are_picked_up(self, app, samples, gate):
        app.add_paths([str(samples[0])])
        gate.wait_for_work_to_begin()

        assert _states(app) == {"disabled"}, "the first batch should still be running"
        app.add_paths([str(samples[1]), str(samples[2])])

        gate.release()
        app.wait_until_idle()

        assert [item.name for item in app.loaded] == [p.name for p in samples]
        assert app.file_list.size() == 3

    def test_a_file_added_twice_mid_batch_is_still_loaded_once(self, app, samples, gate):
        app.add_paths([str(samples[0])])
        gate.wait_for_work_to_begin()
        app.add_paths([str(samples[0])])

        gate.release()
        app.wait_until_idle()

        assert app.file_list.size() == 1

    def test_export_is_refused_while_a_batch_is_loading(self, app, samples, gate, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        gate.wait_for_work_to_begin()

        app.output_dir.set(str(out))
        app.export()

        assert "still working" in app.status.get().lower()

        gate.release()
        app.wait_until_idle()

        # Refused, not deferred: a workbook written from half a batch would be
        # missing files the list already shows.
        assert list(out.glob("*.xlsx")) == []


class TestFailuresStillSurface:
    def test_an_unreadable_file_is_listed_as_failed(self, app, tmp_path):
        app.add_paths([str(tmp_path / "absent.kml")])
        app.wait_until_idle()

        assert "FAILED" in app.file_list.get(0)
        assert _states(app) == {"normal"}

    def test_a_loader_that_raises_does_not_strand_the_window(self, app, samples, monkeypatch):
        from kmz_points import gui

        def exploding(path):
            raise RuntimeError("boom")

        monkeypatch.setattr(gui, "load_file", exploding)
        app.add_paths([str(samples[0])])
        app.wait_until_idle()

        assert "boom" in app.file_list.get(0)
        assert _states(app) == {"normal"}

    def test_an_export_failure_is_reported_and_the_window_comes_back(
        self, app, samples, tmp_path, monkeypatch
    ):
        from kmz_points import gui

        out = tmp_path / "out"
        out.mkdir()
        app.add_paths([str(p) for p in samples])
        app.wait_until_idle()

        def exploding(loaded, output_dir, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(gui, "export_to_excel", exploding)
        app.output_dir.set(str(out))
        app.export()
        app.wait_until_idle()

        assert "disk full" in app.status.get()
        assert app.notifications[-1][0] == "error"
        assert _states(app) == {"normal"}


class TestClosingMidBatch:
    def test_the_worker_gives_up_when_the_window_goes(self, samples, gate):
        from kmz_points.gui import App

        instance = App(notify=lambda *args: None)
        handler = instance.root.protocol("WM_DELETE_WINDOW")
        assert handler.endswith("_on_close"), handler

        instance.add_paths([str(p) for p in samples])
        gate.wait_for_work_to_begin()

        instance._on_close()  # what the window's close button calls
        gate.release()

        # The worker checks the flag between files, so it stops rather than
        # parsing the remaining two into a queue nobody will ever drain.
        deadline = time.monotonic() + 0.5
        while len(gate.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gate.calls == [str(samples[0])]
