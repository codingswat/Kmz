"""Web service tests.

Flask's test client, so these need no network and no display and run
unchanged on every CI platform.
"""

import io
import tempfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from kmz_points.samples import write_samples
from kmz_points.server import create_app, safe_upload_name
from kmz_points.table import headers

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


@pytest.fixture
def samples(tmp_path):
    return write_samples(tmp_path / "in")


def payload(paths):
    """The multipart body the convert route expects."""
    return {
        "files": [(io.BytesIO(Path(p).read_bytes()), Path(p).name) for p in paths]
    }


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    def test_two_uploads_with_the_same_name_do_not_collide(self, signed_in):
        # "doc.kml" twice: both sanitise to the identical stem, so without a
        # per-upload subdirectory the second save can overwrite the first on
        # disk before both are accounted for.
        first = (
            '<?xml version="1.0"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            "<Placemark><name>Alpha</name>"
            "<Point><coordinates>1,2</coordinates></Point></Placemark>"
            "</Document></kml>"
        ).encode()
        second = (
            '<?xml version="1.0"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            "<Placemark><name>Bravo</name>"
            "<Point><coordinates>3,4</coordinates></Point></Placemark>"
            "</Document></kml>"
        ).encode()

        response = signed_in.post(
            "/convert",
            data={
                "files": [
                    (io.BytesIO(first), "doc.kml"),
                    (io.BytesIO(second), "doc.kml"),
                ]
            },
        )

        assert response.status_code == 200
        assert response.mimetype == XLSX_MIME
        sheet = load_workbook(io.BytesIO(response.data))["Points"]
        # A row count alone cannot tell a healthy batch from one where the
        # first upload was clobbered and the second double-counted: both
        # shapes have 2 data rows. Check the actual point names instead.
        name_column = headers().index("Name")
        names = {row[name_column].value for row in sheet.iter_rows(min_row=2)}
        assert names == {"Alpha", "Bravo"}
