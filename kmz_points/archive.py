"""Getting KML bytes out of a .kml or .kmz path.

A KMZ is a zip archive. The convention is a ``doc.kml`` at the root, but
exporters vary, so any .kml entry will do as a fallback.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


class ArchiveError(Exception):
    """Raised when no KML content can be read from a path."""


# Defends against a decompression ("zip") bomb: a small .kmz can declare an
# entry that expands to hundreds of megabytes or more, and archive.read()
# happily allocates and decompresses the full declared size before this
# module gets a chance to say no. A 510 KB crafted .kmz was measured
# expanding to 500 MB (+264 MB RSS) with no size check in place, and the
# service's threaded=True lets several such requests run at once. No
# legitimate KML document is anywhere near this large; 200 MB uncompressed
# is a generous ceiling for even an elaborate one.
MAX_KML_BYTES = 200 * 1024 * 1024


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
            # Checked against the entry's declared size before decompressing
            # it -- by the time archive.read() returns, the memory is already
            # spent.
            info = archive.getinfo(chosen)
            if info.file_size > MAX_KML_BYTES:
                # Rounded up, not floored: flooring rendered one byte over the
                # cap as "would expand to 200 MB, over the 200 MB limit".
                expanded_mb = -(-info.file_size // (1024 * 1024))
                raise ArchiveError(
                    f"{path.name}: {chosen} would expand to about "
                    f"{expanded_mb} MB, over the "
                    f"{MAX_KML_BYTES // (1024 * 1024)} MB limit"
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
