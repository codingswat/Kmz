"""Web front end.

A third shell over the pipeline, alongside gui.py and cli.py. LAN only, one
shared password, nothing retained: uploads live in a per-request temporary
directory and the workbook streams back from memory.
"""

from __future__ import annotations

from pathlib import Path

from werkzeug.utils import secure_filename

ALLOWED_SUFFIXES = (".kml", ".kmz")

# Filenames over 255 bytes raise OSError on macOS and Linux. The cap is well
# under that so the temp directory prefix cannot push a name over the limit.
MAX_STEM = 100


def safe_upload_name(raw: str, index: int) -> str | None:
    """A filename safe to write, keeping the suffix the pipeline checks.

    secure_filename on its own is not enough in two ways. It strips non-ASCII,
    so a valid upload called "地図.kml" comes back as "kml" with no suffix at
    all and read_kml_bytes then refuses it as not a KML file. And it does not
    cap length, so a 400-character name reaches the filesystem and raises
    OSError when saved. The suffix is taken from the original name, checked,
    and reattached to a bounded stem.

    Returns None when the upload is not a KML or KMZ.
    """
    suffix = Path(raw).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return None

    stem = secure_filename(Path(raw).stem)[:MAX_STEM] or f"upload_{index}"
    return f"{stem}{suffix}"
