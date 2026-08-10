"""KMZ archive tests."""

import struct
import zipfile

import pytest

from kmz_points.archive import MAX_KML_BYTES, ArchiveError, read_kml_bytes

MINIMAL_KML = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'


def make_kmz(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def make_oversized_kmz(path, declared_size, name="doc.kml"):
    """A small, genuinely tiny .kmz whose central directory and local file
    header both *claim* one entry expands to ``declared_size`` bytes.

    Building a real archive that big would make the test itself slow and
    memory-hungry -- exactly what the size check exists to avoid. zipfile
    always recomputes the true size when writing, so the declared size is
    patched into the raw bytes afterwards, which is also a faithful stand-in
    for what a real zip bomb looks like: a tiny file, a large lie in the
    metadata.
    """
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, MINIMAL_KML)
    raw = bytearray(buffer.getvalue())

    local_offset = raw.find(b"PK\x03\x04")
    central_offset = raw.find(b"PK\x01\x02")
    assert local_offset != -1 and central_offset != -1

    # Uncompressed size sits at byte 22 of a local file header and byte 24
    # of a central directory header (each a 4-byte little-endian integer).
    struct.pack_into("<I", raw, local_offset + 22, declared_size)
    struct.pack_into("<I", raw, central_offset + 24, declared_size)

    path.write_bytes(bytes(raw))
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


class TestDecompressionBomb:
    def test_an_entry_declaring_more_than_the_limit_is_refused(self, tmp_path):
        bomb = make_oversized_kmz(tmp_path / "bomb.kmz", MAX_KML_BYTES + 1)
        with pytest.raises(ArchiveError, match="bomb.kmz"):
            read_kml_bytes(bomb)

    def test_a_normal_kmz_still_reads(self, tmp_path):
        # The size check must not fire on ordinary, well within limit files.
        kmz = make_kmz(tmp_path / "a.kmz", {"doc.kml": MINIMAL_KML})
        assert read_kml_bytes(kmz) == MINIMAL_KML


class TestUnknownInput:
    def test_unsupported_extension_raises_archive_error(self, tmp_path):
        other = tmp_path / "a.txt"
        other.write_bytes(b"hello")
        with pytest.raises(ArchiveError):
            read_kml_bytes(other)

    def test_missing_file_raises_archive_error(self, tmp_path):
        with pytest.raises(ArchiveError):
            read_kml_bytes(tmp_path / "nope.kml")
