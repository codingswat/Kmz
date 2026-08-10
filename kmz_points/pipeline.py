"""Orchestration: files in, one workbook out.

Nothing here raises on bad input. A batch containing a corrupt file, a KMZ
with no KML inside, or a document with zero points still exports every point
it could read, and reports the rest as warnings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from kmz_points.archive import ArchiveError, read_kml_bytes
from kmz_points.excel import output_filename, write_workbook
from kmz_points.kml_parser import parse_document
from kmz_points.models import Area, BatchSummary, Point
from kmz_points.table import build_table_rows


@dataclass
class LoadedFile:
    """One input file's contribution to the batch."""

    path: Path
    points: list[Point] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def area_count(self) -> int:
        return len(self.areas)

    @property
    def ok(self) -> bool:
        return self.error is None


def validate_output_dir(path: str | Path) -> str | None:
    """Check a folder can receive the workbook.

    Returns an error message, or None if the folder is usable. Deliberately
    does not create anything -- a mistyped path should be reported, not
    quietly built, or the workbook lands somewhere the user will not find it.
    """
    text = str(path).strip()
    if not text:
        return "Choose an output folder."

    target = Path(text)
    if not target.exists():
        return f"Output folder does not exist: {target}"
    if not target.is_dir():
        return f"Output folder is not a folder: {target}"
    if not os.access(target, os.W_OK):
        return f"Output folder is not writable: {target}"
    return None


def load_file(path: str | Path) -> LoadedFile:
    """Read and parse one file. Never raises."""
    path = Path(path)

    try:
        data = read_kml_bytes(path)
    except ArchiveError as exc:
        return LoadedFile(path=path, error=str(exc))
    except Exception as exc:  # unreadable for a reason we did not anticipate
        return LoadedFile(path=path, error=f"{path.name}: {exc}")

    result = parse_document(data, path.name)
    return LoadedFile(
        path=path,
        points=result.points,
        areas=result.areas,
        skipped=result.skipped,
        warnings=list(result.warnings),
    )


def _collect(loaded: list[LoadedFile]) -> tuple[list[Point], BatchSummary]:
    """Reduce a batch to its points and its summary.

    Shared by both exports so the two paths cannot report a batch
    differently.
    """
    summary = BatchSummary()
    points: list[Point] = []

    for item in loaded:
        if item.ok:
            summary.files_read += 1
            summary.features_skipped += item.skipped
            points.extend(item.points)
        else:
            summary.files_failed += 1
            summary.warnings.append(item.error or f"{item.name}: failed")
        summary.warnings.extend(item.warnings)

    summary.points_extracted = len(points)
    return points, summary


def export_to_excel(
    loaded: list[LoadedFile],
    output_dir: str | Path,
    when: datetime | None = None,
) -> BatchSummary:
    """Write every loaded point into one workbook and summarise the batch."""
    points, summary = _collect(loaded)

    if not points:
        summary.warnings.append("No points found; nothing was written.")
        return summary

    destination = Path(output_dir) / output_filename(when)
    write_workbook(build_table_rows(points), destination)
    summary.output_path = str(destination)
    return summary


def export_to_stream(loaded: list[LoadedFile], stream: BinaryIO) -> BatchSummary:
    """Write the workbook into an open binary stream.

    ``output_path`` stays None -- a stream has no path -- so callers decide
    whether a workbook was produced from ``points_extracted``.

    Any warnings are written into the workbook itself. This is the browser
    path: the response body is the file, so there is nowhere else to tell
    someone that two of their five files were unreadable.
    """
    points, summary = _collect(loaded)

    if not points:
        summary.warnings.append("No points found; nothing was written.")
        return summary

    write_workbook(build_table_rows(points), stream, issues=summary.warnings)
    return summary


def run(
    paths: list[str | Path],
    output_dir: str | Path,
    when: datetime | None = None,
) -> BatchSummary:
    """Load every path and export in one call."""
    return export_to_excel([load_file(p) for p in paths], output_dir, when)
