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
