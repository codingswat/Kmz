"""Getting KML bytes out of a .kml or .kmz path.

A KMZ is a zip archive. The convention is a ``doc.kml`` at the root, but
exporters vary, so any .kml entry will do as a fallback.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


class ArchiveError(Exception):
    """Raised when no KML content can be read from a path."""


def _kml_entry_names(archive: zipfile.ZipFile) -> list[str]:
    return [n for n in archive.namelist() if n.lower().endswith(".kml")]


def _read_from_kmz(path: Path) -> bytes:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = _kml_entry_names(archive)
            if not candidates:
                raise ArchiveError(f"{path.name}: archive contains no .kml file")
            # Prefer doc.kml at any depth, else the first .kml present.
            chosen = next(
                (n for n in candidates if Path(n).name.lower() == "doc.kml"),
                candidates[0],
            )
            return archive.read(chosen)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"{path.name}: not a readable KMZ archive") from exc


def read_kml_bytes(path: str | Path) -> bytes:
    """Return the KML document bytes for a .kml or .kmz path."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix not in (".kml", ".kmz"):
        raise ArchiveError(f"{path.name}: not a .kml or .kmz file")
    if not path.is_file():
        raise ArchiveError(f"{path.name}: file not found")

    if suffix == ".kmz":
        return _read_from_kmz(path)

    try:
        return path.read_bytes()
    except OSError as exc:
        raise ArchiveError(f"{path.name}: could not be read ({exc})") from exc
