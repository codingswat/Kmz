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


class TestDecompressionBombs:
    """A small .kmz can carry an entry that expands to hundreds of megabytes.
    The declared size is checked first, but nothing forces an archive to
    declare the truth, so the read is bounded as well."""

    def _bomb(self, path, declared_size=None, payload_mb=1):
        """A zip whose entry expands to payload_mb, optionally lying about it."""
        import struct

        data = b"<kml>" + b"A" * (payload_mb * 1024 * 1024) + b"</kml>"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", data)

        if declared_size is not None:
            # Rewrite the central directory's uncompressed size so the entry
            # under-declares what it really holds.
            raw = bytearray(path.read_bytes())
            marker = raw.rfind(b"PK\x01\x02")
            struct.pack_into("<I", raw, marker + 24, declared_size)
            path.write_bytes(raw)
        return path

    def test_an_honestly_declared_bomb_is_refused_before_reading(
        self, tmp_path, monkeypatch
    ):
        from kmz_points import archive as archive_module

        monkeypatch.setattr(archive_module, "MAX_KML_BYTES", 100_000)
        bomb = self._bomb(tmp_path / "bomb.kmz", payload_mb=1)

        # If it were read first, this would fire.
        def refuse(*args, **kwargs):
            raise AssertionError("the entry was decompressed before the check")

        monkeypatch.setattr(zipfile.ZipFile, "read", refuse)

        with pytest.raises(ArchiveError) as caught:
            read_kml_bytes(bomb)
        assert "bomb.kmz" in str(caught.value)
        assert "limit" in str(caught.value)

    def test_an_entry_that_lies_about_its_size_is_still_refused(
        self, tmp_path, monkeypatch
    ):
        from kmz_points import archive as archive_module

        monkeypatch.setattr(archive_module, "MAX_KML_BYTES", 100_000)
        # Declares 1 KB, actually holds a megabyte.
        liar = self._bomb(tmp_path / "liar.kmz", declared_size=1024, payload_mb=1)

        # The message is zipfile's, not ours: it validates the CRC when the
        # stream reaches the size the entry claimed, which happens before the
        # cap is breached. What matters is that it is refused rather than
        # returned, and that the memory was never spent -- the point of the
        # bounded read, covered by the unit test below.
        with pytest.raises(ArchiveError):
            read_kml_bytes(liar)

    def test_a_normal_kmz_is_unaffected(self, tmp_path):
        kmz = make_kmz(tmp_path / "fine.kmz", {"doc.kml": MINIMAL_KML})
        assert read_kml_bytes(kmz) == MINIMAL_KML

    def test_an_entry_right_at_the_limit_is_allowed(self, tmp_path, monkeypatch):
        from kmz_points import archive as archive_module

        payload = b"<kml>" + b"A" * 1000 + b"</kml>"
        monkeypatch.setattr(archive_module, "MAX_KML_BYTES", len(payload))
        kmz = make_kmz(tmp_path / "edge.kmz", {"doc.kml": payload})
        assert read_kml_bytes(kmz) == payload


class TestBoundedRead:
    """_read_bounded is what keeps an entry from being decompressed in full
    before it can be refused. Measured against a 300 MB payload declaring
    itself as 1 KB: reading it whole grew peak memory by 465 MB, and reading
    it bounded grew it by 2.8 MB."""

    class _EndlessStream:
        """A member that never stops yielding, like a bomb mid-decompression."""

        def __init__(self):
            self.served = 0

        def read(self, size):
            self.served += size
            return b"A" * size

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _FakeArchive:
        def __init__(self, stream):
            self.stream = stream

        def open(self, _entry):
            return self.stream

    def test_it_stops_instead_of_reading_forever(self, monkeypatch):
        from kmz_points import archive as archive_module

        monkeypatch.setattr(archive_module, "MAX_KML_BYTES", 10_000)
        stream = self._EndlessStream()

        with pytest.raises(ArchiveError) as caught:
            archive_module._read_bounded(
                self._FakeArchive(stream), "doc.kml", "bomb.kmz"
            )
        assert "limit" in str(caught.value)

    def test_it_reads_barely_more_than_the_cap(self, monkeypatch):
        from kmz_points import archive as archive_module

        monkeypatch.setattr(archive_module, "MAX_KML_BYTES", 10_000)
        stream = self._EndlessStream()

        with pytest.raises(ArchiveError):
            archive_module._read_bounded(
                self._FakeArchive(stream), "doc.kml", "bomb.kmz"
            )
        # One byte past the cap is enough to prove the breach; anything much
        # larger means a fixed chunk size is swallowing the whole entry.
        assert stream.served <= archive_module.MAX_KML_BYTES + 1

    def test_content_under_the_cap_comes_back_whole(self, monkeypatch):
        from kmz_points import archive as archive_module

        payload = b"<kml>small</kml>"

        class Once:
            def __init__(self):
                self.done = False

            def read(self, size):
                if self.done:
                    return b""
                self.done = True
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        result = archive_module._read_bounded(
            self._FakeArchive(Once()), "doc.kml", "fine.kmz"
        )
        assert result == payload


class TestBoundedReadIsActuallyUsed:
    """Wiring, not behaviour. _read_from_kmz could return archive.read()
    directly and every other test would still pass -- the difference is
    memory, which no assertion can see. Measured on a 300 MB payload
    declaring 1 KB: 465 MB peak the direct way, 2.8 MB bounded."""

    def test_reading_a_kmz_goes_through_the_bounded_reader(
        self, tmp_path, monkeypatch
    ):
        from kmz_points import archive as archive_module

        called = {}

        def spy(archive, entry, archive_name):
            called["entry"] = entry
            return MINIMAL_KML

        monkeypatch.setattr(archive_module, "_read_bounded", spy)
        kmz = make_kmz(tmp_path / "a.kmz", {"doc.kml": MINIMAL_KML})

        assert read_kml_bytes(kmz) == MINIMAL_KML
        assert called["entry"] == "doc.kml"
