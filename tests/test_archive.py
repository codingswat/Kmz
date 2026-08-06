"""KMZ archive tests."""

import zipfile

import pytest

from kmz_points.archive import ArchiveError, read_kml_bytes

MINIMAL_KML = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'


def make_kmz(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


class TestPlainKML:
    def test_reads_a_kml_file_verbatim(self, tmp_path):
        kml = tmp_path / "a.kml"
        kml.write_bytes(MINIMAL_KML)
        assert read_kml_bytes(kml) == MINIMAL_KML

    def test_extension_check_is_case_insensitive(self, tmp_path):
        kml = tmp_path / "a.KML"
        kml.write_bytes(MINIMAL_KML)
        assert read_kml_bytes(kml) == MINIMAL_KML


class TestKMZ:
    def test_prefers_doc_kml(self, tmp_path):
        kmz = make_kmz(
            tmp_path / "a.kmz",
            {"other.kml": b"<kml>wrong</kml>", "doc.kml": MINIMAL_KML},
        )
        assert read_kml_bytes(kmz) == MINIMAL_KML

    def test_falls_back_to_the_first_kml_when_no_doc_kml(self, tmp_path):
        kmz = make_kmz(tmp_path / "a.kmz", {"files/only.kml": MINIMAL_KML})
        assert read_kml_bytes(kmz) == MINIMAL_KML

    def test_finds_doc_kml_in_a_subdirectory(self, tmp_path):
        kmz = make_kmz(tmp_path / "a.kmz", {"nested/doc.kml": MINIMAL_KML})
        assert read_kml_bytes(kmz) == MINIMAL_KML

    def test_ignores_non_kml_entries(self, tmp_path):
        kmz = make_kmz(
            tmp_path / "a.kmz",
            {"images/pin.png": b"\x89PNG", "doc.kml": MINIMAL_KML},
        )
        assert read_kml_bytes(kmz) == MINIMAL_KML

    def test_kmz_with_no_kml_inside_raises_archive_error(self, tmp_path):
        kmz = make_kmz(tmp_path / "a.kmz", {"readme.txt": b"nothing here"})
        with pytest.raises(ArchiveError):
            read_kml_bytes(kmz)

    def test_corrupt_archive_raises_archive_error(self, tmp_path):
        broken = tmp_path / "a.kmz"
        broken.write_bytes(b"this is not a zip file")
        with pytest.raises(ArchiveError):
            read_kml_bytes(broken)


class TestUnknownInput:
    def test_unsupported_extension_raises_archive_error(self, tmp_path):
        other = tmp_path / "a.txt"
        other.write_bytes(b"hello")
        with pytest.raises(ArchiveError):
            read_kml_bytes(other)

    def test_missing_file_raises_archive_error(self, tmp_path):
        with pytest.raises(ArchiveError):
            read_kml_bytes(tmp_path / "nope.kml")
