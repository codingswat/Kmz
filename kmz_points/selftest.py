"""End-to-end self check for a packaged build.

PyInstaller bundles can link and launch while still failing at runtime:
tkinterdnd2 loads a platform-specific tkdnd Tcl library, and mgrs loads
libmgrs through ctypes using a path computed from its own __file__. Both
resolve lazily, so importing them proves nothing. This exercises them.

Run against a frozen binary with ``--selftest``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# A point with a known answer in every format we produce.
_LAT, _LON = 34.567890, 38.123456
_EXPECTED_UTM = "37S 419595 E 3825474 N"
_EXPECTED_MGRS = "37SDU1959425474"
_EXPECTED_ROWS = 7  # what write_samples() yields


def _check_tkdnd() -> tuple[bool, str]:
    """Report whether drag-and-drop is usable. Never fatal -- Browse still works."""
    try:
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
        root.withdraw()
        root.destroy()
        return True, "tkdnd: available"
    except Exception as exc:
        return True, f"tkdnd: unavailable, Browse fallback in use ({type(exc).__name__})"


def run_selftest() -> tuple[int, str]:
    """Exercise the full pipeline. Returns (exit_code, report)."""
    lines: list[str] = []
    failures: list[str] = []

    def record(name: str, ok: bool, detail: str):
        lines.append(f"  {'ok  ' if ok else 'FAIL'} {name}: {detail}")
        if not ok:
            failures.append(name)

    from kmz_points.convert import to_mgrs, to_utm
    from kmz_points.pipeline import run
    from kmz_points.samples import write_samples

    # parse + archive, over a real KML and a real KMZ
    with tempfile.TemporaryDirectory() as workspace:
        workspace = Path(workspace)
        try:
            samples = write_samples(workspace / "in")
            summary = run(samples, workspace / "out")
            ok = summary.points_extracted == _EXPECTED_ROWS
            record("parse", ok, f"{summary.points_extracted} points from 3 files")
        except Exception as exc:
            summary = None
            record("parse", False, f"{type(exc).__name__}: {exc}")

        # UTM -- pure Python, but confirms the wheel is present
        try:
            utm_point = to_utm(_LAT, _LON)
            label = utm_point.label if utm_point else "<none>"
            record("utm", label == _EXPECTED_UTM, label)
        except Exception as exc:
            record("utm", False, f"{type(exc).__name__}: {exc}")

        # MGRS -- the ctypes/libmgrs path, the most fragile part of a bundle
        try:
            reference = to_mgrs(_LAT, _LON)
            record("mgrs", reference == _EXPECTED_MGRS, reference or "<none>")
        except Exception as exc:
            record("mgrs", False, f"{type(exc).__name__}: {exc}")

        # excel -- write a workbook and read it back
        try:
            import openpyxl

            if summary and summary.output_path:
                from kmz_points.excel import data_rows

                sheet = openpyxl.load_workbook(summary.output_path).active
                # Not max_row: the sheet has three header rows and one banner
                # per source file, so its height is not the point count.
                rows = len(data_rows(sheet))
                record("excel", rows == _EXPECTED_ROWS, f"{rows} rows read back")
            else:
                record("excel", False, "no workbook was written")
        except Exception as exc:
            record("excel", False, f"{type(exc).__name__}: {exc}")

    _dnd_ok, dnd_detail = _check_tkdnd()
    lines.append(f"  --   {dnd_detail}")

    verdict = "PASS" if not failures else f"FAIL ({', '.join(failures)})"
    report = "Self test\n" + "\n".join(lines) + f"\n{verdict}"
    return (0 if not failures else 1), report


if __name__ == "__main__":  # pragma: no cover
    code, report = run_selftest()
    print(report)
    raise SystemExit(code)
