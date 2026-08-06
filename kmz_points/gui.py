"""Desktop front end.

A thin shell over the pipeline: this module owns widgets and the list of
loaded files, and nothing else. Drag-and-drop is optional -- if tkinterdnd2
or the underlying tkdnd library is missing, the window still opens and the
Browse button does the same job.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from kmz_points.pipeline import LoadedFile, export_to_excel, load_file

DROP_PROMPT = "Drag KML / KMZ files here"
FILE_TYPES = [("KML and KMZ files", "*.kml *.kmz"), ("All files", "*.*")]

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


class App:
    def __init__(self, notify=None):
        # Notifications are injected so the window can be driven headlessly --
        # a modal dialog blocks forever when there is nobody to dismiss it.
        self.notify = notify or _dialog_notify
        self.root, self.dnd_available = _make_root()
        self.root.title("KML / KMZ Point Extractor")
        self.root.geometry("760x560")
        self.root.minsize(620, 460)

        self.loaded: list[LoadedFile] = []
        self.output_dir = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Add KML or KMZ files to begin.")

        self._build_widgets()
        self._enable_drop()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        drop_frame = tk.Frame(
            outer, height=120, relief="ridge", borderwidth=2, background="#f4f6f8"
        )
        drop_frame.pack(fill="x")
        drop_frame.pack_propagate(False)
        self.drop_frame = drop_frame

        self.drop_label = tk.Label(
            drop_frame,
            text=DROP_PROMPT,
            background="#f4f6f8",
            foreground="#33475b",
            font=("TkDefaultFont", 13, "bold"),
        )
        self.drop_label.pack(expand=True)

        self.drop_hint = tk.Label(
            drop_frame,
            text="or use Browse below",
            background="#f4f6f8",
            foreground="#7b8794",
        )
        self.drop_hint.pack(pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 6))
        ttk.Button(buttons, text="Browse...", command=self.browse).pack(side="left")
        ttk.Button(buttons, text="Remove selected", command=self.remove_selected).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Clear all", command=self.clear_all).pack(side="left")

        ttk.Label(outer, text="Loaded files").pack(anchor="w", pady=(8, 2))
        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.file_list = tk.Listbox(
            list_frame, selectmode="extended", yscrollcommand=scrollbar.set, height=10
        )
        scrollbar.config(command=self.file_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.file_list.pack(side="left", fill="both", expand=True)

        output_row = ttk.Frame(outer)
        output_row.pack(fill="x", pady=(10, 6))
        ttk.Label(output_row, text="Output folder").pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(output_row, text="Choose...", command=self.choose_output_dir).pack(
            side="left"
        )

        ttk.Button(outer, text="Export to Excel", command=self.export).pack(
            fill="x", pady=(6, 8), ipady=4
        )

        ttk.Separator(outer).pack(fill="x")
        ttk.Label(outer, textvariable=self.status, anchor="w").pack(
            fill="x", pady=(6, 0)
        )

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
        """Load each path, skipping any already in the list."""
        known = {str(item.path) for item in self.loaded}
        added = 0

        for raw in paths:
            path = Path(raw)
            if str(path) in known:
                continue
            item = load_file(path)
            self.loaded.append(item)
            known.add(str(path))
            added += 1

        if added:
            self._refresh_file_list()
            if not self.output_dir.get():
                self.output_dir.set(str(self.loaded[0].path.parent))

        total = sum(item.point_count for item in self.loaded)
        self.status.set(f"{len(self.loaded)} file(s) loaded, {total} point(s) found.")

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
        if not self.loaded:
            self.status.set("No files loaded. Add KML or KMZ files first.")
            return

        target = self.output_dir.get() or str(self.loaded[0].path.parent)
        try:
            summary = export_to_excel(self.loaded, target)
        except Exception as exc:  # a full-stop failure, e.g. unwritable folder
            self.status.set(f"Export failed: {exc}")
            self.notify("error", "Export failed", str(exc))
            return

        self.status.set(summary.as_text().replace("\n", "   |   "))
        if summary.output_path:
            self.notify("info", "Export complete", summary.as_text())
        else:
            self.notify("warning", "Nothing exported", summary.as_text())

    # ------------------------------------------------------------ internal

    def _refresh_file_list(self):
        self.file_list.delete(0, "end")
        for item in self.loaded:
            if item.ok:
                skipped = f", {item.skipped} skipped" if item.skipped else ""
                label = f"{item.name}  -  {item.point_count} point(s){skipped}"
            else:
                label = f"{item.name}  -  FAILED: {item.error}"
            self.file_list.insert("end", label)

    def run(self):  # pragma: no cover - blocks on the event loop
        self.root.mainloop()


def main():  # pragma: no cover - entry point
    App().run()


if __name__ == "__main__":  # pragma: no cover
    main()
