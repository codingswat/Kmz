"""Web front end.

A third shell over the pipeline, alongside gui.py and cli.py. LAN only, one
shared password, nothing retained: uploads live in a per-request temporary
directory and the workbook streams back from memory.
"""

from __future__ import annotations

import hmac
import io
import secrets
import tempfile
import threading
import time
from pathlib import Path

from flask import (
    Flask,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from kmz_points.excel import output_filename
from kmz_points.pipeline import LoadedFile, export_to_stream, load_file
from kmz_points.templates import LOGIN_PAGE, UPLOAD_PAGE

ALLOWED_SUFFIXES = (".kml", ".kmz")

# Filenames over 255 bytes raise OSError on macOS and Linux. The cap is well
# under that so the temp directory prefix cannot push a name over the limit.
MAX_STEM = 100

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_WINDOW_SECONDS = 60.0


class LoginAttempts:
    """How many times each address has just got the password wrong.

    What this buys, precisely: one shared password on a plain-HTTP office LAN
    can be guessed at whatever rate the server will answer, and answering
    thousands a second is what makes a short password worthless. Five tries a
    minute makes that useless and makes it obvious. It does NOT make the
    service safe to expose to the internet, and BUILDING.md still says so --
    nothing here changes the threat model, it only removes the free ride.

    Kept in memory and nowhere else. The service already retains nothing and
    mints a new SECRET_KEY per run, so a lockout surviving a restart would be
    the one piece of state that outlived everything else.

    Per address rather than global, even though everyone behind one office NAT
    shares an address. Coarse in that direction is tolerable; the alternative
    is one person's typo locking out the whole office.
    """

    def __init__(self, limit: int = DEFAULT_MAX_ATTEMPTS,
                 window: float = DEFAULT_WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        # serve.py runs this with several worker threads, so every read and
        # write below is shared mutable state.
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent(self, stamps: list[float], now: float) -> list[float]:
        return [t for t in stamps if now - t < self.window]

    def _evict(self, now: float) -> None:
        """Drop addresses whose failures have all aged out.

        Without this the table is a slow leak keyed by anything that can reach
        the port. With it the bound is exact: at most one entry per address
        that has failed within the last ``window`` seconds.
        """
        for address in list(self._failures):
            kept = self._recent(self._failures[address], now)
            if kept:
                self._failures[address] = kept
            else:
                del self._failures[address]

    def blocked(self, address: str) -> bool:
        """Whether this address has spent its attempts."""
        now = time.monotonic()
        with self._lock:
            return len(self._recent(self._failures.get(address, []), now)) >= self.limit

    def record_failure(self, address: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            self._failures.setdefault(address, []).append(now)

    def clear(self, address: str) -> None:
        """Forget an address's failures, because it just got the password right."""
        with self._lock:
            self._failures.pop(address, None)

    def tracked(self) -> int:
        """How many addresses are currently held. For tests and diagnostics."""
        with self._lock:
            return len(self._failures)


def _format_mb(num_bytes: int) -> str:
    """A human figure for an upload cap, e.g. ``50`` rather than ``50.0``.

    Falls back to KB below a megabyte: %g renders a 1000-byte cap as
    ``0.000953674``, which read as gibberish on the over-the-limit page.
    """
    megabytes = num_bytes / (1024 * 1024)
    if megabytes < 1:
        return f"{num_bytes / 1024:.3g} KB"
    return f"{megabytes:g} MB"


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


def create_app(
    password: str,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    attempt_window: float = DEFAULT_WINDOW_SECONDS,
) -> Flask:
    """Build the web app.

    A factory rather than a module-level app so each test gets its own
    instance with its own password, upload cap and attempt counter.
    """
    if not password:
        raise ValueError("a password is required")

    app = Flask(__name__)
    app.config.update(
        # Generated per run and never persisted: restarting signs everyone
        # out, which suits a service that keeps nothing.
        SECRET_KEY=secrets.token_urlsafe(32),
        MAX_CONTENT_LENGTH=max_upload_bytes,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    upload_limit = _format_mb(max_upload_bytes)

    def _upload_page(summary=None, warnings=()):
        return render_template_string(
            UPLOAD_PAGE,
            summary=summary,
            warnings=list(warnings),
            upload_limit=upload_limit,
        )

    def signed_in() -> bool:
        return session.get("authenticated") is True

    @app.get("/")
    def index():
        if not signed_in():
            return render_template_string(LOGIN_PAGE, error=None)
        return _upload_page()

    expected = password.encode("utf-8")
    attempts = LoginAttempts(max_attempts, attempt_window)
    app.extensions["login_attempts"] = attempts

    @app.post("/login")
    def login():
        address = request.remote_addr or "unknown"

        if attempts.blocked(address):
            # 429 rather than a delay. Sleeping here would hold a worker
            # thread for the duration, which turns a guessing attempt into a
            # denial of service against the colleagues this is protecting.
            return (
                render_template_string(
                    LOGIN_PAGE,
                    error=(
                        f"Too many wrong passwords. Wait "
                        f"{int(attempt_window)} seconds and try again."
                    ),
                ),
                429,
            )

        # compare_digest so a wrong password cannot be found by timing, and
        # on bytes rather than str: it rejects str operands that are not both
        # ASCII, which would 500 on any accented password.
        supplied = request.form.get("password", "").encode("utf-8")
        if hmac.compare_digest(supplied, expected):
            attempts.clear(address)
            session["authenticated"] = True
            return redirect(url_for("index"))

        attempts.record_failure(address)
        return render_template_string(LOGIN_PAGE, error="Wrong password."), 401

    @app.post("/convert")
    def convert():
        if not signed_in():
            return redirect(url_for("index"))

        uploads = [f for f in request.files.getlist("files") if f.filename]
        if not uploads:
            return (
                _upload_page(warnings=["Choose at least one .kml or .kmz file."]),
                400,
            )

        # Everything happens inside here and is gone when the block exits,
        # whatever the outcome.
        with tempfile.TemporaryDirectory() as workspace:
            loaded: list[LoadedFile] = []

            for index, upload in enumerate(uploads):
                display = Path(upload.filename).name or "upload"
                name = safe_upload_name(upload.filename, index)

                if name is None:
                    # Report it the same way an unreadable file is reported,
                    # so it counts as a failure in the summary.
                    loaded.append(
                        LoadedFile(
                            path=Path(display),
                            error=f"{display}: not a .kml or .kmz file",
                        )
                    )
                    continue

                # Each upload gets its own numbered subdirectory rather than
                # sharing workspace's root: two uploads whose names sanitise
                # to the same value (two files both called doc.kml) would
                # otherwise land on the same path and one would overwrite the
                # other on disk. The saved filename itself is untouched, so
                # it still reads correctly in warnings and the Issues sheet.
                upload_dir = Path(workspace) / str(index)
                upload_dir.mkdir()
                destination = upload_dir / name
                upload.save(destination)
                loaded.append(load_file(destination))

            buffer = io.BytesIO()
            summary = export_to_stream(loaded, buffer)

        # Areas count as much as points. A file holding nothing but shapes
        # produces a workbook with an Areas sheet, and keying this off points
        # alone threw that workbook away and showed the summary instead.
        if summary.points_extracted == 0 and summary.areas_extracted == 0:
            return _upload_page(summary=summary.as_text(), warnings=summary.warnings)

        buffer.seek(0)
        response = send_file(
            buffer,
            mimetype=XLSX_MIME,
            as_attachment=True,
            download_name=output_filename(),
        )

        # The page cannot see a download finish -- no navigation, no load
        # event -- so echoing the token back as a cookie is what lets it stop
        # showing "Converting…". Not HttpOnly: the page has to read it. It
        # carries no meaning beyond "your download started".
        token = request.form.get("download_token", "")
        if token:
            response.set_cookie("download_token", token, samesite="Lax")
        return response

    @app.errorhandler(413)
    def too_large(_error):
        # Werkzeug's bare "413 Request Entity Too Large" page names no limit
        # and offers no way back. Render the same upload page instead, with
        # a message that says why and how big is too big, while still
        # answering 413 so a script or the test suite can tell what happened.
        message = (
            f"That upload is over the {upload_limit} limit. "
            "Choose fewer or smaller files."
        )
        return _upload_page(warnings=[message]), 413

    return app
