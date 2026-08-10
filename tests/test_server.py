"""Web service tests.

Flask's test client, so these need no network and no display and run
unchanged on every CI platform.
"""

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
