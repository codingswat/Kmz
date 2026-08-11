"""Desktop front end.

A thin shell over the pipeline: this module owns widgets and the list of
loaded files, and nothing else. Drag-and-drop is optional -- if tkinterdnd2
or the underlying tkdnd library is missing, the window still opens and the
Browse button does the same job.

Reading files and writing the workbook happen on a worker thread, because a
large KMZ takes long enough on the main thread that Windows paints the window
"Not Responding" and people force-quit an app that was working fine. Tk is
not thread-safe -- only the thread that created a widget may touch it -- so
the split is strict: the worker runs pipeline calls and posts plain data to a
queue, and a poll on the main thread drains that queue and performs every
widget update. Nothing calls root.after from the worker; Tk's own
documentation is ambiguous about whether that is allowed, and the poll costs
nothing.
"""

from __future__ import annotations

import contextlib
import queue
import re
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import Literal, Protocol

from kmz_points.models import BatchSummary
from kmz_points.pipeline import (
    LoadedFile,
    export_to_excel,
    load_file,
    validate_output_dir,
)

DROP_PROMPT = "Drag KML / KMZ files here"
FILE_TYPES = [("KML and KMZ files", "*.kml *.kmz"), ("All files", "*.*")]

# Visual tokens, kept together so the window can be restyled without hunting
# hex codes through the layout code.
_INK = "#1f2933"  # primary text
_MUTED = "#6b7785"  # hints, section labels
_PAGE = "#f2f4f7"  # window background
_SURFACE = "#ffffff"  # raised areas: the file list
_BORDER = "#d5dce5"
_DROP_FILL = "#eaf2fd"
_DROP_EDGE = "#a9c6e8"
_ACCENT = "#2563eb"
_ACCENT_LIT = "#1d4ed8"
_SELECTION = "#dbeafe"

_GAP = 8  # spacing unit; every pad below is a multiple of it


def _scaled(
    base: tkfont.Font,
    factor: float,
    weight: Literal["normal", "bold"] = "normal",
) -> tkfont.Font:
    """A copy of the platform's default font at a different size.

    Tk reports negative sizes in pixels and positive ones in points, and
    scaling by a factor keeps the right sign either way -- hard-coding a size
    would be tiny on one platform and oversized on another.
    """
    font = base.copy()
    font.configure(size=int(base.cget("size") * factor), weight=weight)
    return font


def _apply_theme(root: tk.Misc) -> None:
    """Style the ttk widgets.

    'clam' is used on every platform rather than each one's native theme,
    because the native themes -- aqua in particular -- ignore requested
    button colours, and the accent on the export button is what marks it out
    as the action the window is for.
    """
    style = ttk.Style(root)
    # A Tcl build without clam; native styling still works.
    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")

    base = tkfont.nametofont("TkDefaultFont")

    style.configure(".", background=_PAGE, foreground=_INK, font=base)
    style.configure("TFrame", background=_PAGE)
    style.configure("TLabel", background=_PAGE, foreground=_INK)
    style.configure("Section.TLabel", foreground=_MUTED, font=_scaled(base, 0.9))
    style.configure("Status.TLabel", foreground=_MUTED, font=_scaled(base, 0.9))

    style.configure(
        "TButton",
        background=_SURFACE,
        foreground=_INK,
        bordercolor=_BORDER,
        focuscolor=_ACCENT,
        borderwidth=1,
        padding=(12, 6),
    )
    style.map(
        "TButton",
        background=[("pressed", _SELECTION), ("active", "#eef1f5")],
        bordercolor=[("active", _DROP_EDGE)],
    )

    style.configure(
        "Accent.TButton",
        background=_ACCENT,
        foreground="#ffffff",
        bordercolor=_ACCENT,
        borderwidth=0,
        padding=(12, 10),
        font=_scaled(base, 1.0, weight="bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", _ACCENT_LIT), ("active", _ACCENT_LIT)],
        foreground=[("disabled", "#e5e7eb")],
    )

    style.configure(
        "TEntry",
        fieldbackground=_SURFACE,
        bordercolor=_BORDER,
        insertcolor=_INK,
        padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", _ACCENT)])
    style.configure("TSeparator", background=_BORDER)

# tkdnd hands over a space-separated list, brace-quoting any entry that
# contains a space: "{/tmp/my places.kml} /tmp/b.kmz"
_DROP_ENTRY = re.compile(r"\{([^}]*)\}|(\S+)")


def parse_drop_payload(data: str) -> list[str]:
    """Split a tkdnd drop payload into individual paths."""
    if not data or not data.strip():
        return []
    return [braced or plain for braced, plain in _DROP_ENTRY.findall(data)]


def _make_root() -> tuple[tk.Tk, bool]:
    """Return a root window and whether drag-and-drop is available on it."""
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk(), True
    except Exception:
        # tkinterdnd2 missing, or tkdnd not installed for this Tcl build.
        return tk.Tk(), False


def _dialog_notify(kind: str, title: str, message: str) -> None:
    """Default notifier: a modal dialog."""
    {
        "info": messagebox.showinfo,
        "warning": messagebox.showwarning,
        "error": messagebox.showerror,
    }[kind](title, message)


# ----------------------------------------------------------------- workers

_POLL_MS = 50  # how often the main thread looks for results
_IDLE_TICK = 0.005  # how long wait_until_idle sleeps between pumps

# There is deliberately no Cancel button. A batch runs for seconds to tens of
# seconds and the worker can only stop between files, so Cancel would be
# unable to interrupt the one thing slow enough to make anybody press it --
# a single large file's parse. A button that appears to stop the work and
# does not is a worse lie than a clear message saying what is happening.


@dataclass
class _FileLoaded:
    """One input finished parsing."""

    item: LoadedFile


@dataclass
class _LoadDone:
    """The batch is over, however many files it managed."""


@dataclass
class _Exported:
    """The workbook run finished; the summary says whether anything was written."""

    summary: BatchSummary


@dataclass
class _ExportFailed:
    """The workbook could not be written at all."""

    error: str


_Message = _FileLoaded | _LoadDone | _Exported | _ExportFailed


class _Executor(Protocol):
    """Where pipeline work runs. Injected so tests can make it synchronous."""

    def submit(self, work: Callable[[], None]) -> None: ...


class _Background:
    """Runs work off the main thread; results return through the queue.

    A fresh daemon thread per batch rather than a pool: batches are already
    serialised by the busy flag, so a pool would add a shutdown to get wrong
    on the way out and nothing else.
    """

    def submit(self, work: Callable[[], None]) -> None:
        threading.Thread(target=work, daemon=True).start()


class _Inline:
    """Runs work immediately on the calling thread. For tests."""

    def submit(self, work: Callable[[], None]) -> None:
        work()


def _load_job(
    paths: list[Path],
    results: queue.Queue[_Message],
    cancelled: threading.Event,
) -> Callable[[], None]:
    """Build the work a load batch performs off the main thread.

    A module-level closure over paths, the queue and a flag, rather than a
    method: with no ``self`` in scope there is no route from the worker to a
    widget, which is the property that keeps this safe rather than merely
    careful.
    """

    def work() -> None:
        for path in paths:
            if cancelled.is_set():  # the window closed mid-batch
                return
            try:
                item = load_file(path)
            except Exception as exc:
                # load_file promises never to raise and keeps that promise.
                # Belt and braces anyway: a worker that died here would leave
                # the buttons disabled forever with nothing on screen saying
                # why, which is the failure this module exists to avoid.
                item = LoadedFile(path=path, error=f"{path.name}: {exc}")
            results.put(_FileLoaded(item))
        results.put(_LoadDone())

    return work


def _export_job(
    loaded: list[LoadedFile],
    output_dir: str,
    results: queue.Queue[_Message],
) -> Callable[[], None]:
    """Build the work an export performs off the main thread."""

    def work() -> None:
        try:
            summary = export_to_excel(loaded, output_dir)
        except Exception as exc:  # a full-stop failure, e.g. unwritable folder
            results.put(_ExportFailed(str(exc)))
        else:
            results.put(_Exported(summary))

    return work


def _row_label(item: LoadedFile) -> str:
    """One line of the loaded-files list."""
    if not item.ok:
        return f"{item.name}  -  FAILED: {item.error}"
    skipped = f", {item.skipped} skipped" if item.skipped else ""
    return f"{item.name}  -  {item.point_count} point(s){skipped}"


class App:
    def __init__(self, notify=None, executor=None):
        # Notifications are injected so the window can be driven headlessly --
        # a modal dialog blocks forever when there is nobody to dismiss it.
        self.notify = notify or _dialog_notify
        # The executor is injected for the same reason: tests hand in one that
        # runs the work inline, so an assertion on the line after add_paths
        # sees a finished batch instead of a thread that has barely started.
        self._executor: _Executor = executor or _Background()

        self.root, self.dnd_available = _make_root()
        self.root.title("KML / KMZ Point Extractor")
        self.root.geometry("760x560")
        self.root.minsize(620, 460)

        self.loaded: list[LoadedFile] = []
        self.output_dir = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Add KML or KMZ files to begin.")

        self._results: queue.Queue[_Message] = queue.Queue()
        self._cancelled = threading.Event()
        self._busy = False
        self._pending: list[str] = []  # dropped or browsed mid-batch
        self._batch_total = 0
        self._batch_done = 0
        self._poll_id: str | None = None

        self._build_widgets()
        self._enable_drop()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build_widgets(self):
        _apply_theme(self.root)
        self.root.configure(background=_PAGE)
        base = tkfont.nametofont("TkDefaultFont")

        outer = ttk.Frame(self.root, padding=_GAP * 2)
        outer.pack(fill="both", expand=True)

        # A flat hairline rather than a ridge bevel: highlightthickness draws
        # the border without the 3D groove, which reads as a target area
        # instead of a sunken panel.
        drop_frame = tk.Frame(
            outer,
            height=_GAP * 17,
            background=_DROP_FILL,
            highlightbackground=_DROP_EDGE,
            highlightcolor=_DROP_EDGE,
            highlightthickness=1,
            borderwidth=0,
        )
        drop_frame.pack(fill="x")
        drop_frame.pack_propagate(False)
        self.drop_frame = drop_frame

        self.drop_label = tk.Label(
            drop_frame,
            text=DROP_PROMPT,
            background=_DROP_FILL,
            foreground=_INK,
            font=_scaled(base, 1.35, weight="bold"),
        )
        self.drop_label.pack(expand=True, pady=(_GAP * 2, 0))

        self.drop_hint = tk.Label(
            drop_frame,
            text="or use Browse below",
            background=_DROP_FILL,
            foreground=_MUTED,
            font=_scaled(base, 0.9),
        )
        self.drop_hint.pack(pady=(_GAP // 2, _GAP * 2))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(_GAP * 2, 0))
        self.browse_button = ttk.Button(buttons, text="Browse...", command=self.browse)
        self.browse_button.pack(side="left")
        self.remove_button = ttk.Button(
            buttons, text="Remove selected", command=self.remove_selected
        )
        self.remove_button.pack(side="left", padx=_GAP)
        self.clear_button = ttk.Button(buttons, text="Clear all", command=self.clear_all)
        self.clear_button.pack(side="left")

        ttk.Label(outer, text="LOADED FILES", style="Section.TLabel").pack(
            anchor="w", pady=(_GAP * 2, _GAP // 2)
        )
        list_frame = tk.Frame(
            outer,
            background=_SURFACE,
            highlightbackground=_BORDER,
            highlightcolor=_BORDER,
            highlightthickness=1,
            borderwidth=0,
        )
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.file_list = tk.Listbox(
            list_frame,
            selectmode="extended",
            yscrollcommand=scrollbar.set,
            height=10,
            background=_SURFACE,
            foreground=_INK,
            selectbackground=_SELECTION,
            selectforeground=_INK,
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",  # the dotted underline reads as a rendering fault
        )
        scrollbar.config(command=self.file_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.file_list.pack(
            side="left", fill="both", expand=True, padx=_GAP // 2, pady=_GAP // 2
        )

        ttk.Label(outer, text="OUTPUT FOLDER", style="Section.TLabel").pack(
            anchor="w", pady=(_GAP * 2, _GAP // 2)
        )
        output_row = ttk.Frame(outer)
        output_row.pack(fill="x")
        ttk.Entry(output_row, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(output_row, text="Choose...", command=self.choose_output_dir).pack(
            side="left", padx=(_GAP, 0)
        )

        self.export_button = ttk.Button(
            outer,
            text="Export to Excel",
            command=self.export,
            style="Accent.TButton",
        )
        self.export_button.pack(fill="x", pady=(_GAP * 2, _GAP * 2))

        # Everything that would mutate the file list or read it while a worker
        # is using it. The output folder row stays live: choosing where the
        # workbook goes costs nothing and is the one thing worth doing while
        # a batch reads.
        self._work_buttons = (
            self.browse_button,
            self.remove_button,
            self.clear_button,
            self.export_button,
        )

        ttk.Separator(outer).pack(fill="x")
        ttk.Label(
            outer, textvariable=self.status, anchor="w", style="Status.TLabel"
        ).pack(fill="x", pady=(_GAP, 0))

    def _enable_drop(self):
        if not self.dnd_available:
            self.drop_hint.config(text="Drag-and-drop unavailable - use Browse below")
            return
        try:
            from tkinterdnd2 import DND_FILES

            for widget in (self.drop_frame, self.drop_label, self.drop_hint):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            self.dnd_available = False
            self.drop_hint.config(text="Drag-and-drop unavailable - use Browse below")

    def _on_drop(self, event):
        self.add_paths(parse_drop_payload(event.data))

    # ------------------------------------------------------------- actions

    def browse(self):
        paths = filedialog.askopenfilenames(
            title="Select KML or KMZ files", filetypes=FILE_TYPES
        )
        if paths:
            self.add_paths(list(paths))

    def choose_output_dir(self):
        chosen = filedialog.askdirectory(title="Choose output folder")
        if chosen:
            self.output_dir.set(chosen)

    def add_paths(self, paths: list[str]):
        """Queue paths for loading, skipping any already in the list.

        Returns as soon as the work is handed off. Paths arriving while a
        batch is running wait their turn rather than being dropped -- dragging
        a second folder in is a normal thing to do while the first reads.
        """
        self._pending.extend(paths)
        if not self._busy:
            self._start_load()

    def remove_selected(self):
        for index in sorted(self.file_list.curselection(), reverse=True):
            del self.loaded[index]
        self._refresh_file_list()
        self.status.set(f"{len(self.loaded)} file(s) loaded.")

    def clear_all(self):
        self.loaded.clear()
        self._refresh_file_list()
        self.status.set("Cleared.")

    def export(self):
        if self._busy:
            # Refused rather than queued: exporting half a batch would produce
            # a workbook missing files the user can see in the list.
            self.status.set("Still working. Wait for the current batch to finish.")
            return

        if not self.loaded:
            self.status.set("No files loaded. Add KML or KMZ files first.")
            return

        target = self.output_dir.get().strip() or str(self.loaded[0].path.parent)

        problem = validate_output_dir(target)
        if problem:
            self.status.set(problem)
            self.notify("error", "Cannot export", problem)
            return

        self._set_busy(True)
        # No progress bar. Writing a workbook is one openpyxl call with no
        # progress to report, and a bar that moved on a timer would say
        # something the program does not know.
        self.status.set("Writing the workbook...")
        # A copy, so the list the worker walks cannot be the one the main
        # thread is free to keep changing.
        self._submit(_export_job(list(self.loaded), target, self._results))

    def wait_until_idle(self, timeout: float = 10.0) -> None:
        """Pump the Tk event loop until no work is outstanding.

        For tests and anything else driving the window without mainloop: the
        poll that collects worker results is an after callback, so with no
        event loop turning, results never arrive.
        """
        deadline = time.monotonic() + timeout
        while self._busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(_IDLE_TICK)

    # ------------------------------------------------------------ internal

    def _start_load(self):
        """Begin a batch from whatever is pending. Main thread only."""
        known = {str(item.path) for item in self.loaded}
        batch: list[Path] = []
        for raw in self._pending:
            path = Path(raw)
            if str(path) in known:
                continue
            known.add(str(path))
            batch.append(path)
        self._pending.clear()

        if not batch:  # every path was already in the list
            self._report_loaded()
            return

        self._batch_total = len(batch)
        self._batch_done = 0
        self._set_busy(True)
        self.status.set(f"Reading {len(batch)} file(s)...")
        self._submit(_load_job(batch, self._results, self._cancelled))

    def _submit(self, work):
        """Hand work to the executor and pick up anything it has already done.

        The drain is what makes an inline executor work: that one finishes
        before submit returns, so this is where its results get applied and a
        test needs no event loop at all. On a thread the queue is normally
        still empty here and the poll below does the real collecting.
        """
        self._executor.submit(work)
        self._drain()
        if self._busy:
            self._schedule_poll()

    def _schedule_poll(self):
        if self._poll_id is None:
            self._poll_id = self.root.after(_POLL_MS, self._poll)

    def _poll(self):
        self._poll_id = None
        self._drain()
        if self._busy:
            self._schedule_poll()

    def _drain(self):
        """Apply every result the worker has posted. Main thread only.

        This is the only place widgets and self.loaded change in response to
        worker output, which is what makes the threading safe.
        """
        while True:
            try:
                message = self._results.get_nowait()
            except queue.Empty:
                return
            self._apply(message)

    def _apply(self, message: _Message) -> None:
        if isinstance(message, _FileLoaded):
            self._file_loaded(message.item)
        elif isinstance(message, _LoadDone):
            self._load_finished()
        elif isinstance(message, _Exported):
            self._export_finished(message.summary)
        else:
            self._set_busy(False)
            self.status.set(f"Export failed: {message.error}")
            self.notify("error", "Export failed", message.error)

    def _file_loaded(self, item: LoadedFile) -> None:
        self.loaded.append(item)
        self.file_list.insert("end", _row_label(item))
        if not self.output_dir.get():
            self.output_dir.set(str(item.path.parent))

        self._batch_done += 1
        self.status.set(f"Read {self._batch_done} of {self._batch_total} file(s)...")

    def _load_finished(self) -> None:
        self._set_busy(False)
        if self._pending:  # arrived while that batch was running
            self._start_load()
            return
        self._report_loaded()

    def _export_finished(self, summary: BatchSummary) -> None:
        self._set_busy(False)
        self.status.set(summary.as_text().replace("\n", "   |   "))
        if summary.output_path:
            self.notify("info", "Export complete", summary.as_text())
        else:
            self.notify("warning", "Nothing exported", summary.as_text())

    def _report_loaded(self) -> None:
        total = sum(item.point_count for item in self.loaded)
        self.status.set(f"{len(self.loaded)} file(s) loaded, {total} point(s) found.")

    def _set_busy(self, busy: bool) -> None:
        """Flip the window between working and idle. Main thread only."""
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in self._work_buttons:
            button.config(state=state)

    def _on_close(self):
        """Leave without waiting for the worker.

        Worker threads are daemons and check the cancelled flag between files,
        so closing mid-batch cannot hang the process. What must not happen is
        a queued poll firing against widgets that no longer exist.

        Closing during an export can leave a half-written workbook behind,
        because one openpyxl call has no point to stop at. That is the cost of
        a window that closes when asked; before this, the click simply queued
        behind the export and the window sat there looking crashed.
        """
        self._cancelled.set()
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self.root.destroy()

    def _refresh_file_list(self):
        self.file_list.delete(0, "end")
        for item in self.loaded:
            self.file_list.insert("end", _row_label(item))

    def run(self):  # pragma: no cover - blocks on the event loop
        self.root.mainloop()


def main():  # pragma: no cover - entry point
    App().run()


if __name__ == "__main__":  # pragma: no cover
    main()
