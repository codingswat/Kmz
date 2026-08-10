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

ALLOWED_SUFFIXES = (".kml", ".kmz")

# Filenames over 255 bytes raise OSError on macOS and Linux. The cap is well
# under that so the temp directory prefix cannot push a name over the limit.
MAX_STEM = 100

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


_LOGIN_PAGE = """<!doctype html>
<title>KML / KMZ Point Extractor</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 34rem; margin: 4rem auto;
         padding: 0 1rem; color: #1f2933; background: #f2f4f7; }
  .error { color: #b42318; }
  input, button { font: inherit; padding: .5rem; }
</style>
<h1>KML / KMZ Point Extractor</h1>
<p>Enter the team password to continue.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('login') }}">
  <input type="password" name="password" autofocus>
  <button type="submit">Continue</button>
</form>
"""

_UPLOAD_PAGE = """<!doctype html>
<title>KML / KMZ Point Extractor</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;
         padding: 0 1rem; color: #1f2933; background: #f2f4f7; }
  .summary { background: #f2f4f7; padding: 1rem; border-radius: .4rem;
             border: 1px solid #d5dce5; white-space: pre-line; }
  .warning { color: #b54708; }
  input, button { font: inherit; padding: .5rem; }
</style>
<h1>KML / KMZ Point Extractor</h1>
<p>Choose one or more .kml or .kmz files. You will get one Excel workbook back.</p>
<p>Total upload size must be under {{ upload_limit }}.</p>
<form method="post" action="{{ url_for('convert') }}" enctype="multipart/form-data">
  <input type="file" name="files" accept=".kml,.kmz" multiple required>
  <button type="submit">Convert</button>
</form>
{% if summary %}<div class="summary">{{ summary }}</div>{% endif %}
{% for warning in warnings %}<p class="warning">{{ warning }}</p>{% endfor %}
"""


def create_app(password: str, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> Flask:
    """Build the web app.

    A factory rather than a module-level app so each test gets its own
    instance with its own password and upload cap.
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
            _UPLOAD_PAGE,
            summary=summary,
            warnings=list(warnings),
            upload_limit=upload_limit,
        )

    def signed_in() -> bool:
        return session.get("authenticated") is True

    @app.get("/")
    def index():
        if not signed_in():
            return render_template_string(_LOGIN_PAGE, error=None)
        return _upload_page()

    expected = password.encode("utf-8")

    @app.post("/login")
    def login():
        # compare_digest so a wrong password cannot be found by timing, and
        # on bytes rather than str: it rejects str operands that are not both
        # ASCII, which would 500 on any accented password.
        supplied = request.form.get("password", "").encode("utf-8")
        if hmac.compare_digest(supplied, expected):
            session["authenticated"] = True
            return redirect(url_for("index"))
        return render_template_string(_LOGIN_PAGE, error="Wrong password."), 401

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

        if summary.points_extracted == 0:
            return _upload_page(summary=summary.as_text(), warnings=summary.warnings)

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype=XLSX_MIME,
            as_attachment=True,
            download_name=output_filename(),
        )

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
