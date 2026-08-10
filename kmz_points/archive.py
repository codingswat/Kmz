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


# Read in chunks rather than in one call, so the cap can be enforced while
# decompressing instead of after.
_CHUNK_BYTES = 1024 * 1024


def _kml_entry_names(archive: zipfile.ZipFile) -> list[str]:
    return [n for n in archive.namelist() if n.lower().endswith(".kml")]


def _too_big(archive_name: str, entry: str, size: int) -> str:
    # Rounded up, not floored: flooring rendered one byte over the cap as
    # "would expand to 200 MB, over the 200 MB limit".
    megabytes = -(-size // (1024 * 1024))
    return (
        f"{archive_name}: {entry} would expand to about {megabytes} MB, "
        f"over the {MAX_KML_BYTES // (1024 * 1024)} MB limit"
    )


def _read_bounded(archive: zipfile.ZipFile, entry: str, archive_name: str) -> bytes:
    """Decompress an entry, stopping the moment it exceeds the cap.

    archive.read() would allocate the whole thing first, so a member that
    under-declares its size defeats a check made against the declared value
    alone. Reading a chunk at a time bounds the memory to the cap plus one
    chunk however the archive describes itself.
    """
    collected = bytearray()
    with archive.open(entry) as stream:
        while True:
            # Never ask for more than it would take to prove the cap is
            # breached. A fixed chunk larger than the cap would decompress the
            # whole entry in one call, which is the very thing being avoided.
            allowance = MAX_KML_BYTES + 1 - len(collected)
            chunk = stream.read(min(_CHUNK_BYTES, allowance))
            if not chunk:
                return bytes(collected)
            collected.extend(chunk)
            if len(collected) > MAX_KML_BYTES:
                raise ArchiveError(_too_big(archive_name, entry, len(collected)))


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
            # Two checks, because either alone is escapable. The declared
            # size refuses an honest bomb without touching it; reading in
            # bounded chunks refuses one that lies, since nothing stops an
            # archive declaring 1 KB and carrying 300 MB.
            info = archive.getinfo(chosen)
            if info.file_size > MAX_KML_BYTES:
                raise ArchiveError(_too_big(path.name, chosen, info.file_size))
            return _read_bounded(archive, chosen, path.name)
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
