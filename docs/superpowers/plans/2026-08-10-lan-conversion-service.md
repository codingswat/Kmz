# LAN Conversion Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let colleagues on the office LAN convert KML/KMZ files to Excel through a browser page served from the owner's laptop.

**Architecture:** A third shell over the existing `kmz_points/pipeline.py`, alongside `gui.py` (tkinter) and `cli.py` (argparse). The web layer owns HTTP and temporary files and nothing else; all parsing and workbook writing stays in the modules that already do it. Uploads live in a per-request temporary directory and the workbook streams back from memory, so nothing is retained.

**Tech Stack:** Python 3.12, Flask 3.1, Werkzeug 3.1, openpyxl 3.1, pytest.

## Global Constraints

- Flask must **not** enter the packaged `.exe`/`.dmg`. `build.spec` excludes it.
- Nothing is written outside a per-request `tempfile.TemporaryDirectory()`.
- The existing 178 tests must keep passing, unchanged.
- New tests must be headless — no display, no network — so they run on all four CI platforms.
- No TLS. This is plain HTTP on a trusted LAN, an accepted limitation recorded in the spec.
- `read_kml_bytes` rejects any path whose suffix is not `.kml` or `.kmz`. Any filename handling must preserve the extension.
- Run tests with `.venv/bin/python -m pytest`, not a bare `pytest`.

---

### Task 1: Let `write_workbook` write to a stream

`export_to_stream` (Task 2) needs a workbook in memory rather than on disk. `write_workbook` currently calls `Path(target)` unconditionally, which raises `TypeError` on a `BytesIO`.

**Files:**
- Modify: `kmz_points/excel.py:44-70`
- Test: `tests/test_excel.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `write_workbook(rows: list[list], target: str | Path | BinaryIO, issues: list[str] | None = None) -> Path | None` — returns the `Path` written when given a path, `None` when given a stream. Both existing call sites pass the target positionally, so the rename from `path` to `target` breaks nothing, and both omit `issues`, so the desktop app's output is byte-for-byte unchanged.

`issues` exists because a browser download has nowhere to put a warning: the
response body is the workbook itself. When a batch part-fails, the failures ride
along inside the file on a second sheet named `Issues`. Only the web path passes
it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_excel.py`, after the existing imports:

```python
import io

from openpyxl import load_workbook
```

Then add this class at the end of the file:

```python
class TestWritingToAStream:
    """The web service needs a workbook in memory, never on disk."""

    def test_a_stream_target_produces_a_readable_workbook(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer)
        buffer.seek(0)
        sheet = load_workbook(buffer).active
        assert [c.value for c in sheet[1]] == headers()
        assert sheet.max_row == 2

    def test_a_stream_target_returns_no_path(self):
        assert write_workbook(build_table_rows([make_point()]), io.BytesIO()) is None

    def test_a_path_target_still_returns_its_path(self, tmp_path):
        target = tmp_path / "out.xlsx"
        assert write_workbook(build_table_rows([make_point()]), target) == target


class TestIssuesSheet:
    """A browser download has nowhere to show a warning, so failures ride
    along inside the workbook."""

    def test_no_issues_means_no_second_sheet(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer)
        buffer.seek(0)
        assert load_workbook(buffer).sheetnames == ["Points"]

    def test_issues_are_listed_on_their_own_sheet(self):
        buffer = io.BytesIO()
        write_workbook(
            build_table_rows([make_point()]),
            buffer,
            issues=["broken.kmz: not a readable KMZ archive"],
        )
        buffer.seek(0)
        book = load_workbook(buffer)
        assert book.sheetnames == ["Points", "Issues"]
        listed = [row[0].value for row in book["Issues"].iter_rows(min_row=2)]
        assert listed == ["broken.kmz: not a readable KMZ archive"]

    def test_the_points_sheet_stays_first(self):
        buffer = io.BytesIO()
        write_workbook(build_table_rows([make_point()]), buffer, issues=["a problem"])
        buffer.seek(0)
        # Opening the file must land on the data, not on the complaints.
        assert load_workbook(buffer).active.title == "Points"

    def test_an_empty_issue_list_adds_no_sheet(self, tmp_path):
        target = tmp_path / "out.xlsx"
        write_workbook(build_table_rows([make_point()]), target, issues=[])
        assert load_workbook(target).sheetnames == ["Points"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_excel.py::TestWritingToAStream -v`

Expected: FAIL with `TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'BytesIO'`

- [ ] **Step 3: Write minimal implementation**

In `kmz_points/excel.py`, add `BinaryIO` to the imports:

```python
from typing import BinaryIO
```

Replace the signature and docstring:

```python
def write_workbook(
    rows: list[list],
    target: str | Path | BinaryIO,
    issues: list[str] | None = None,
) -> Path | None:
    """Write rows to an xlsx file, or into an open binary stream.

    The web service needs the workbook in memory, so a stream is accepted as
    well as a path. Returns the path written, or None for a stream.

    ``issues`` adds a second sheet naming files that could not be read. A
    browser download has nowhere else to report them: the response body is the
    workbook. The desktop app passes nothing and its output is unchanged.
    """
    book = Workbook()
```

Note the removed `path = Path(path)` line — the target is not converted up front any more.

Then replace the final two lines of the function:

```python
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path
```

with:

```python
    if issues:
        # Appended after Points, so opening the file lands on the data.
        notes = book.create_sheet("Issues")
        notes.append(["Issue"])
        notes["A1"].font = Font(bold=True)
        for line in issues:
            notes.append([_fit(line)])
        notes.column_dimensions["A"].width = _MAX_WIDTH

    if isinstance(target, (str, Path)):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        book.save(path)
        return path

    book.save(target)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_excel.py -v`

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add kmz_points/excel.py tests/test_excel.py
git commit -m "Let write_workbook write into a stream as well as a file"
```

---

### Task 2: Split the batch aggregation and add `export_to_stream`

`export_to_excel` currently does two jobs: aggregating a batch into a `BatchSummary`, and writing a file. The web service needs the first without the second.

**Files:**
- Modify: `kmz_points/pipeline.py:86-115`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `write_workbook(rows, target) -> Path | None` from Task 1.
- Produces:
  - `_collect(loaded: list[LoadedFile]) -> tuple[list[Point], BatchSummary]` — private.
  - `export_to_stream(loaded: list[LoadedFile], stream: BinaryIO) -> BatchSummary` — writes the workbook into `stream`, or writes nothing when the batch yields no points. **Always leaves `summary.output_path` as `None`**, because a stream has no path. Callers decide whether a workbook exists from `summary.points_extracted`, never from `output_path`.
  - `export_to_excel(loaded, output_dir, when=None) -> BatchSummary` — signature and behaviour unchanged.

There is deliberately no `when` parameter on `export_to_stream`: it would be unused, since the download filename is chosen by the caller via `output_filename()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`. The file already imports `export_to_excel, load_file, run` from `kmz_points.pipeline` — extend that import to include `export_to_stream`, and add `import io` at the top.

```python
class TestExportToStream:
    """The web service path: same batch, no file on disk."""

    def test_the_stream_holds_a_readable_workbook(self, samples, tmp_path):
        loaded = [load_file(p) for p in samples]
        buffer = io.BytesIO()
        export_to_stream(loaded, buffer)
        buffer.seek(0)
        sheet = openpyxl.load_workbook(buffer).active
        assert sheet.max_row - 1 == SAMPLE_POINT_TOTAL

    def test_the_summary_matches_the_file_based_export(self, samples, tmp_path):
        # Guards the _collect split: the two paths must not drift.
        loaded = [load_file(p) for p in samples]
        to_file = export_to_excel([load_file(p) for p in samples], tmp_path)
        to_stream = export_to_stream(loaded, io.BytesIO())

        assert to_stream.files_read == to_file.files_read
        assert to_stream.files_failed == to_file.files_failed
        assert to_stream.points_extracted == to_file.points_extracted
        assert to_stream.features_skipped == to_file.features_skipped
        assert to_stream.warnings == to_file.warnings

    def test_no_points_writes_nothing_to_the_stream(self, tmp_path):
        empty = tmp_path / "empty.kml"
        empty.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
        buffer = io.BytesIO()
        summary = export_to_stream([load_file(empty)], buffer)
        assert summary.points_extracted == 0
        assert buffer.getvalue() == b""

    def test_output_path_is_never_set_for_a_stream(self, samples):
        loaded = [load_file(p) for p in samples]
        assert export_to_stream(loaded, io.BytesIO()).output_path is None

    def test_a_failed_file_is_named_inside_the_workbook(self, samples, tmp_path):
        # The browser gets the file and nothing else, so this is the only
        # place a partial failure can be reported.
        broken = tmp_path / "broken.kmz"
        broken.write_bytes(b"this is not a zip")
        loaded = [load_file(p) for p in list(samples) + [broken]]

        buffer = io.BytesIO()
        summary = export_to_stream(loaded, buffer)
        buffer.seek(0)
        book = openpyxl.load_workbook(buffer)

        assert summary.points_extracted == SAMPLE_POINT_TOTAL
        assert "Issues" in book.sheetnames
        listed = " ".join(
            str(row[0].value) for row in book["Issues"].iter_rows(min_row=2)
        )
        assert "broken.kmz" in listed

    def test_a_clean_batch_has_no_issues_sheet(self, samples):
        loaded = [load_file(p) for p in samples]
        buffer = io.BytesIO()
        export_to_stream(loaded, buffer)
        buffer.seek(0)
        assert openpyxl.load_workbook(buffer).sheetnames == ["Points"]

    def test_the_file_export_gains_no_issues_sheet(self, samples, tmp_path):
        # The desktop app's output must not change shape.
        broken = tmp_path / "broken.kmz"
        broken.write_bytes(b"this is not a zip")
        loaded = [load_file(p) for p in list(samples) + [broken]]

        summary = export_to_excel(loaded, tmp_path)
        assert openpyxl.load_workbook(summary.output_path).sheetnames == ["Points"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py::TestExportToStream -v`

Expected: FAIL at collection with `ImportError: cannot import name 'export_to_stream'`

- [ ] **Step 3: Write minimal implementation**

In `kmz_points/pipeline.py`, add to the imports:

```python
from typing import BinaryIO
```

Replace the whole body of `export_to_excel` (lines 86-115) with these three functions:

```python
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
```

- [ ] **Step 4: Run the whole suite to verify nothing regressed**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. The count rises from 178 by the tests added in Tasks 1 and 2; no pre-existing test may fail.

- [ ] **Step 5: Commit**

```bash
git add kmz_points/pipeline.py tests/test_pipeline.py
git commit -m "Share the batch summary between the file and stream exports"
```

---

### Task 3: Safe upload filenames

The riskiest input handling in the feature, isolated so it can be tested without HTTP.

`secure_filename` alone is wrong here. It strips non-ASCII characters, so a valid upload named `地図.kml` becomes `kml` — no extension — and `read_kml_bytes` then rejects it as "not a .kml or .kmz file". Verified against Werkzeug 3.1.8:

```
'../../evil.kml' -> 'evil.kml'
'地図.kml'        -> 'kml'
'.kml'           -> 'kml'
''               -> ''
```

**Files:**
- Modify: `requirements.txt`
- Create: `kmz_points/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ALLOWED_SUFFIXES = (".kml", ".kmz")`
  - `MAX_STEM = 100`
  - `safe_upload_name(raw: str, index: int) -> str | None` — a filename safe to write that keeps the suffix the pipeline checks, or `None` if the upload is not a KML/KMZ.

- [ ] **Step 1: Add the dependency**

This task is the first to import Werkzeug, so the dependency is declared here
rather than later — otherwise this task's own tests cannot pass on a clean
checkout, and its commit would leave CI red.

Append to `requirements.txt`:

```
# Web service. Only needed to run the LAN service (serve.py); the desktop app
# never imports Flask, and build.spec excludes it from the bundle.
flask>=3.0
```

Werkzeug arrives as a Flask dependency and is not listed separately.

Install it: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: Write the failing test**

Create `tests/test_server.py`:

```python
"""Web service tests.

Flask's test client, so these need no network and no display and run
unchanged on every CI platform.
"""

from kmz_points.server import safe_upload_name


class TestSafeUploadName:
    def test_a_plain_name_is_kept(self):
        assert safe_upload_name("doc.kml", 0) == "doc.kml"

    def test_a_traversal_attempt_loses_its_path(self):
        assert safe_upload_name("../../evil.kml", 0) == "evil.kml"

    def test_a_windows_path_keeps_no_directory_part(self):
        # Asserted as an invariant, not a literal: Path().stem resolves
        # backslashes on Windows but not on POSIX, so the exact string
        # differs by platform while the property that matters does not.
        result = safe_upload_name(r"C:\data\a.kmz", 0)
        assert result.endswith(".kmz")
        assert "/" not in result and "\\" not in result and ":" not in result

    def test_spaces_are_replaced(self):
        assert safe_upload_name("my places.kml", 0) == "my_places.kml"

    def test_a_non_ascii_name_keeps_its_extension(self):
        # secure_filename alone would return "kml", which read_kml_bytes
        # rejects as not a KML file.
        assert safe_upload_name("地図.kml", 3) == "upload_3.kml"

    def test_the_suffix_check_is_case_insensitive(self):
        assert safe_upload_name("DOC.KML", 0) == "DOC.kml"

    def test_a_non_kml_upload_is_refused(self):
        assert safe_upload_name("notes.txt", 0) is None

    def test_a_name_with_no_suffix_is_refused(self):
        assert safe_upload_name("README", 0) is None

    def test_an_absurdly_long_name_is_shortened(self):
        # Filenames over 255 bytes raise OSError 63 on macOS and Linux, which
        # would surface as an unhandled 500 when the upload is saved.
        result = safe_upload_name("x" * 400 + ".kml", 0)
        assert len(result) <= 104
        assert result.endswith(".kml")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'kmz_points.server'`

- [ ] **Step 4: Write minimal implementation**

Create `kmz_points/server.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`

Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add kmz_points/server.py tests/test_server.py requirements.txt
git commit -m "Keep the extension when sanitising an upload filename"
```

---

### Task 4: The app factory and the password gate

**Files:**
- Modify: `kmz_points/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `safe_upload_name` from Task 3. Flask is already in `requirements.txt` from Task 3.
- Produces:
  - `DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024`
  - `create_app(password: str, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> Flask` — raises `ValueError` on an empty password. Routes `GET /` and `POST /login`. Task 5 adds `POST /convert` to the same factory.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` — extend the import line and add the fixtures and class:

```python
import pytest

from kmz_points.server import create_app, safe_upload_name

PASSWORD = "correct horse"


@pytest.fixture
def client():
    app = create_app(PASSWORD)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def signed_in(client):
    client.post("/login", data={"password": PASSWORD})
    return client


class TestPasswordGate:
    def test_an_empty_password_is_refused_at_startup(self):
        with pytest.raises(ValueError):
            create_app("")

    def test_the_front_page_asks_for_the_password(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "password" in body.lower()

    def test_the_wrong_password_is_rejected(self, client):
        response = client.post("/login", data={"password": "wrong"})
        assert response.status_code == 401

    def test_the_right_password_opens_the_upload_page(self, signed_in):
        body = signed_in.get("/").get_data(as_text=True)
        assert ".kml" in body

    def test_the_session_survives_between_requests(self, signed_in):
        assert ".kml" in signed_in.get("/").get_data(as_text=True)
        assert ".kml" in signed_in.get("/").get_data(as_text=True)

    def test_a_non_ascii_password_works(self):
        # hmac.compare_digest refuses str operands that are not both ASCII:
        # "TypeError: comparing strings with non-ASCII characters is not
        # supported". Comparing str would turn every login into a 500 for any
        # owner who picks an accented password, and for any colleague who
        # typos one into the field.
        app = create_app("contraseña")
        app.config["TESTING"] = True
        client = app.test_client()

        assert client.post("/login", data={"password": "wrong"}).status_code == 401
        assert client.post("/login", data={"password": "contraseña"}).status_code == 302

    def test_a_non_ascii_attempt_against_an_ascii_password_is_refused(self, client):
        assert client.post("/login", data={"password": "wrøng"}).status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestPasswordGate -v`

Expected: FAIL at collection with `ImportError: cannot import name 'create_app'`

- [ ] **Step 3: Write minimal implementation**

In `kmz_points/server.py`, extend the imports:

```python
import hmac
import secrets
from pathlib import Path

from flask import (
    Flask,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
```

Add the constant next to `ALLOWED_SUFFIXES`:

```python
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
```

Add the two page templates at module level, below the constants:

```python
_LOGIN_PAGE = """<!doctype html>
<title>KML / KMZ Point Extractor</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 34rem; margin: 4rem auto;
         padding: 0 1rem; color: #1f2933; }
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
         padding: 0 1rem; color: #1f2933; }
  .summary { background: #f2f4f7; padding: 1rem; border-radius: .4rem;
             white-space: pre-line; }
  .warning { color: #b54708; }
  input, button { font: inherit; padding: .5rem; }
</style>
<h1>KML / KMZ Point Extractor</h1>
<p>Choose one or more .kml or .kmz files. You will get one Excel workbook back.</p>
<form method="post" action="{{ url_for('convert') }}" enctype="multipart/form-data">
  <input type="file" name="files" accept=".kml,.kmz" multiple required>
  <button type="submit">Convert</button>
</form>
{% if summary %}<div class="summary">{{ summary }}</div>{% endif %}
{% for warning in warnings %}<p class="warning">{{ warning }}</p>{% endfor %}
"""
```

Add the factory:

```python
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

    def signed_in() -> bool:
        return session.get("authenticated") is True

    @app.get("/")
    def index():
        if not signed_in():
            return render_template_string(_LOGIN_PAGE, error=None)
        return render_template_string(_UPLOAD_PAGE, summary=None, warnings=[])

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

    return app
```

Note `_UPLOAD_PAGE` references `url_for('convert')`, which does not exist until Task 5. **Task 4's tests will fail until Task 5 is complete** unless a placeholder exists, so add this stub inside `create_app` now, directly below `login`:

```python
    @app.post("/convert")
    def convert():
        raise NotImplementedError("Task 5")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`

Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add kmz_points/server.py tests/test_server.py
git commit -m "Gate the web service behind a shared team password"
```

---

### Task 5: The conversion route

**Files:**
- Modify: `kmz_points/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `safe_upload_name` (Task 3), `create_app` (Task 4), `export_to_stream` (Task 2), and the existing `load_file` and `LoadedFile` from `kmz_points.pipeline`, plus `output_filename` from `kmz_points.excel`.
- Produces: `POST /convert`, replacing the Task 4 stub. Returns the workbook as an attachment when `summary.points_extracted > 0`, otherwise re-renders the upload page with the summary.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`. Extend the imports:

```python
import io
from pathlib import Path

from openpyxl import load_workbook

from kmz_points.samples import write_samples
```

Add a fixture and helper next to the others:

```python
@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "in")


def payload(paths):
    """The multipart body the convert route expects."""
    return {
        "files": [(io.BytesIO(Path(p).read_bytes()), Path(p).name) for p in paths]
    }


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
```

Then the class:

```python
class TestConvert:
    def test_converting_needs_a_session(self, client, samples):
        response = client.post("/convert", data=payload(samples))
        assert response.status_code == 302

    def test_the_samples_come_back_as_a_workbook(self, signed_in, samples):
        response = signed_in.post("/convert", data=payload(samples))
        assert response.status_code == 200
        assert response.mimetype == XLSX_MIME
        sheet = load_workbook(io.BytesIO(response.data)).active
        assert sheet.max_row - 1 == 7  # header plus the 7 sample points

    def test_the_download_is_named_by_the_usual_pattern(self, signed_in, samples):
        response = signed_in.post("/convert", data=payload(samples))
        disposition = response.headers["Content-Disposition"]
        assert "points_" in disposition and disposition.endswith(".xlsx")

    def test_a_broken_file_does_not_stop_the_good_ones(self, signed_in, samples, tmp_path):
        broken = tmp_path / "broken.kmz"
        broken.write_bytes(b"this is not a zip")
        response = signed_in.post("/convert", data=payload(list(samples) + [broken]))
        assert response.status_code == 200
        assert response.mimetype == XLSX_MIME
        sheet = load_workbook(io.BytesIO(response.data))["Points"]
        assert sheet.max_row - 1 == 7  # the good files still all came through

    def test_the_failure_is_named_in_the_downloaded_workbook(
        self, signed_in, samples, tmp_path
    ):
        # Not `b"broken.kmz" in response.data`: an xlsx is a zip, so the text
        # is compressed and that check fails even when the sheet is present.
        # Confirmed against a prototype before this test was written.
        broken = tmp_path / "broken.kmz"
        broken.write_bytes(b"this is not a zip")
        response = signed_in.post("/convert", data=payload(list(samples) + [broken]))

        book = load_workbook(io.BytesIO(response.data))
        assert "Issues" in book.sheetnames
        listed = " ".join(
            str(row[0].value) for row in book["Issues"].iter_rows(min_row=2)
        )
        assert "broken.kmz" in listed

    def test_a_batch_with_no_points_returns_a_summary_not_a_download(
        self, signed_in, tmp_path
    ):
        empty = tmp_path / "empty.kml"
        empty.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
        response = signed_in.post("/convert", data=payload([empty]))
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        assert "No points found" in response.get_data(as_text=True)

    def test_a_non_kml_upload_is_reported_not_crashed(self, signed_in, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("nothing to see")
        response = signed_in.post("/convert", data=payload([notes]))
        assert response.status_code == 200
        assert "notes.txt" in response.get_data(as_text=True)

    def test_sending_no_files_is_reported(self, signed_in):
        response = signed_in.post("/convert", data={"files": []})
        assert response.status_code == 400
        assert "at least one" in response.get_data(as_text=True).lower()

    def test_an_oversized_upload_is_refused(self, samples):
        app = create_app(PASSWORD, max_upload_bytes=1000)
        app.config["TESTING"] = True
        small = app.test_client()
        small.post("/login", data={"password": PASSWORD})
        response = small.post(
            "/convert", data={"files": [(io.BytesIO(b"x" * 5000), "big.kml")]}
        )
        assert response.status_code == 413

    def test_nothing_is_left_behind_on_disk(self, signed_in, samples, monkeypatch, tmp_path):
        # tempfile.tempdir is pinned to a directory only this test uses.
        # Scanning the shared system temp directory instead would fail
        # whenever any unrelated process happened to create a file mid-test.
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))

        signed_in.post("/convert", data=payload(samples))

        assert list(scratch.iterdir()) == []

    def test_a_traversal_filename_cannot_escape_the_workspace(
        self, signed_in, samples, monkeypatch, tmp_path
    ):
        # The same check as safe_upload_name's unit test, but driven through
        # the real route, which is where it actually matters.
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))

        body = Path(samples[0]).read_bytes()
        response = signed_in.post(
            "/convert", data={"files": [(io.BytesIO(body), "../../evil.kml")]}
        )

        assert response.status_code == 200
        assert list(scratch.iterdir()) == []
        assert not (tmp_path / "evil.kml").exists()
        assert not (tmp_path.parent / "evil.kml").exists()
```

Those two tests need `import tempfile` at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestConvert -v`

Expected: FAIL with `NotImplementedError: Task 5`

- [ ] **Step 3: Write minimal implementation**

In `kmz_points/server.py`, extend the imports:

```python
import io
import tempfile

from flask import send_file

from kmz_points.excel import output_filename
from kmz_points.pipeline import LoadedFile, export_to_stream, load_file
```

Add the mimetype next to the other constants:

```python
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
```

Replace the Task 4 stub with:

```python
    @app.post("/convert")
    def convert():
        if not signed_in():
            return redirect(url_for("index"))

        uploads = [f for f in request.files.getlist("files") if f.filename]
        if not uploads:
            return (
                render_template_string(
                    _UPLOAD_PAGE,
                    summary=None,
                    warnings=["Choose at least one .kml or .kmz file."],
                ),
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

                destination = Path(workspace) / name
                upload.save(destination)
                loaded.append(load_file(destination))

            buffer = io.BytesIO()
            summary = export_to_stream(loaded, buffer)

        if summary.points_extracted == 0:
            return render_template_string(
                _UPLOAD_PAGE, summary=summary.as_text(), warnings=summary.warnings
            )

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype=XLSX_MIME,
            as_attachment=True,
            download_name=output_filename(),
        )
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS, with no pre-existing test failing.

- [ ] **Step 5: Commit**

```bash
git add kmz_points/server.py tests/test_server.py
git commit -m "Convert uploaded files and stream one workbook back"
```

---

### Task 6: The launcher

**Files:**
- Create: `serve.py`
- Test: `tests/test_serve.py`

**Interfaces:**
- Consumes: `create_app` from Task 4.
- Produces: `lan_address() -> str` and `main() -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_serve.py`:

```python
"""Launcher tests. The server itself is never started."""

import ipaddress

import pytest

import serve


class TestLanAddress:
    def test_it_reports_the_outbound_interface_address(self, monkeypatch):
        # The address is faked, because asserting only "is valid IPv4" would
        # also pass when the fallback fired -- 127.0.0.1 is a valid address,
        # and it is exactly the value that means this function failed.
        class Probe:
            def connect(self, _address):
                pass

            def getsockname(self):
                return ("192.168.1.42", 54321)

            def close(self):
                pass

        monkeypatch.setattr(serve.socket, "socket", lambda *a, **k: Probe())
        assert serve.lan_address() == "192.168.1.42"

    def test_the_real_call_still_returns_a_parseable_address(self):
        # No claim about which address: a runner with no route legitimately
        # gets the loopback fallback.
        ipaddress.IPv4Address(serve.lan_address())

    def test_it_falls_back_when_there_is_no_route(self, monkeypatch):
        class DeadSocket:
            def connect(self, _address):
                raise OSError("no route to host")

            def getsockname(self):  # pragma: no cover - never reached
                raise AssertionError("should not be asked")

            def close(self):
                pass

        monkeypatch.setattr(serve.socket, "socket", lambda *a, **k: DeadSocket())
        assert serve.lan_address() == "127.0.0.1"


class TestMain:
    def test_an_empty_password_stops_before_starting(self, monkeypatch, capsys):
        monkeypatch.setenv("KMZ_PASSWORD", "   ")
        assert serve.main() == 1
        assert "password" in capsys.readouterr().out.lower()

    def test_the_shared_url_is_printed(self, monkeypatch, capsys):
        monkeypatch.setenv("KMZ_PASSWORD", "hunter2")
        started = {}

        def fake_run(**kwargs):
            started.update(kwargs)

        monkeypatch.setattr(serve, "_run_app", fake_run)
        assert serve.main() == 0

        printed = capsys.readouterr().out
        assert f":{serve.DEFAULT_PORT}" in printed
        assert started["host"] == "0.0.0.0"
        assert started["threaded"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'serve'`

- [ ] **Step 3: Write minimal implementation**

Create `serve.py` at the repo root, alongside the existing `run.py`:

```python
#!/usr/bin/env python3
"""Start the LAN conversion service.

Colleagues open the printed URL in a browser on the same network. Nothing is
kept: uploads live in a per-request temporary directory and the workbook
streams back from memory.

The password comes from KMZ_PASSWORD, or is prompted for.
"""

from __future__ import annotations

import os
import socket
from getpass import getpass

from kmz_points.server import create_app

DEFAULT_PORT = 8000


def lan_address() -> str:
    """The address colleagues should use, not 127.0.0.1.

    Opening a UDP socket towards a routable address makes the OS choose the
    outbound interface, which is the one colleagues can reach. Nothing is
    actually sent.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _run_app(**kwargs) -> None:
    """Indirection so tests can start everything except the server itself."""
    create_app(kwargs.pop("password")).run(**kwargs)


def main() -> int:
    password = os.environ.get("KMZ_PASSWORD") or getpass("Password for colleagues: ")
    if not password.strip():
        print("A password is required.")
        return 1

    print()
    print(f"  Share this:  http://{lan_address()}:{DEFAULT_PORT}")
    print("  Stop with Ctrl-C")
    print()
    print("  The address can change if your laptop gets a new one from DHCP.")
    print()

    # threaded, so one large conversion does not block everyone else.
    _run_app(password=password, host="0.0.0.0", port=DEFAULT_PORT, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add serve.py tests/test_serve.py
git commit -m "Add a launcher that prints the URL to share"
```

---

### Task 7: Keep Flask out of the desktop bundle

`run.py` never imports Flask, so PyInstaller should not collect it — but that is an accident of the import graph rather than a stated rule, and Task 4 put Flask into `requirements.txt`, which CI installs before building. Make it explicit and prove it.

**Files:**
- Modify: `build.spec`
- Modify: `BUILDING.md`

**Interfaces:**
- Consumes: nothing. Independent of Tasks 1-6 at runtime.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Add the exclusion**

In `build.spec`, extend the existing `excludes` list:

```python
    excludes=["pytest", "numpy", "pandas", "matplotlib", "flask", "werkzeug", "jinja2"],
```

- [ ] **Step 2: Rebuild and prove Flask is absent**

Run:

```bash
.venv/bin/pyinstaller build.spec --noconfirm
```

Do **not** check this with `strings`. A onefile bundle is compressed, so
`strings` finds nothing for any bundled module — it reports 0 for `openpyxl`,
which is definitely present — and would therefore report success no matter
what. Read the archive instead.

First the positive control, proving the check can see bundled modules at all:

```bash
.venv/bin/python -m PyInstaller.utils.cliutils.archive_viewer -l -r dist/KmzPoints.app/Contents/MacOS/KmzPoints | grep -ci openpyxl
```

Expected: a number well above zero (176 at the time of writing).

Then the check itself:

```bash
.venv/bin/python -m PyInstaller.utils.cliutils.archive_viewer -l -r dist/KmzPoints.app/Contents/MacOS/KmzPoints | grep -ciE "flask|werkzeug|jinja2"
```

Expected: `0`. If the positive control is also 0, the check is broken — stop
and fix the check before trusting the result.

- [ ] **Step 3: Confirm the desktop app still works**

Run: `./dist/KmzPoints.app/Contents/MacOS/KmzPoints --selftest`

Expected: the usual report ending in `PASS`, with `ok` for parse, utm, mgrs and excel.

- [ ] **Step 4: Document how to run the service**

Add this section to `BUILDING.md`, immediately before the "The warning message"
heading. The outer fence below is four backticks so the inner ```bash block
survives copy-and-paste — paste everything between the four-backtick markers.

````markdown
## Running the service for colleagues

The desktop app and the service are separate. Colleagues do not install
anything; they open a browser.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python serve.py
```

It prints the address to share, for example `http://192.168.1.42:8000`. Give
colleagues that link and the password you chose. Stop it with Ctrl-C.

Three things to know:

- It only works while your laptop is awake, running the command, and on the
  same network. Colleagues cannot tell "down" from "you went home".
- The address can change when your laptop gets a new one from DHCP.
- Traffic is plain HTTP, so the password and the files are readable by anyone
  who can watch that network. It is meant for a trusted office LAN.
````

- [ ] **Step 5: Run the whole suite one last time**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add build.spec BUILDING.md
git commit -m "Keep Flask out of the desktop bundle and document the service"
```

---

## Verification

After Task 7, the following must all hold:

- `.venv/bin/python -m pytest -q` passes, with the 178 pre-existing tests among them.
- `python serve.py` prints a LAN URL and serves the page.
- `./dist/KmzPoints.app/Contents/MacOS/KmzPoints --selftest` still ends in `PASS`.
- The frozen binary contains no Flask.
- CI is green on Windows, both macOS runners, and Linux, with no workflow changes.
