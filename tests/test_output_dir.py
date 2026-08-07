"""Output folder validation.

A hand-typed path used to be accepted as-is and the folder chain created
silently, so a typo produced a workbook somewhere unexpected instead of an
error.
"""

import os
import sys

import pytest

from kmz_points.pipeline import validate_output_dir

# Both are read by skipif decorators, which run at collection time -- so
# os.geteuid, which does not exist on Windows, cannot be called unguarded
# there or the whole module fails to import.
ON_WINDOWS = sys.platform == "win32"
AS_ROOT = not ON_WINDOWS and os.geteuid() == 0


class TestAcceptsUsableFolders:
    def test_existing_writable_folder_is_accepted(self, tmp_path):
        assert validate_output_dir(tmp_path) is None

    def test_trailing_whitespace_is_tolerated(self, tmp_path):
        assert validate_output_dir(f"  {tmp_path}  ") is None


class TestRejectsUnusableFolders:
    def test_empty_path_is_rejected(self):
        assert validate_output_dir("") is not None

    def test_whitespace_only_path_is_rejected(self):
        assert validate_output_dir("   ") is not None

    def test_missing_folder_is_rejected(self, tmp_path):
        assert validate_output_dir(tmp_path / "does-not-exist") is not None

    def test_missing_folder_message_names_the_path(self, tmp_path):
        missing = tmp_path / "nope"
        assert str(missing) in validate_output_dir(missing)

    def test_a_file_is_not_a_folder(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("hello")
        assert validate_output_dir(target) is not None

    def test_nested_missing_path_is_rejected_not_created(self, tmp_path):
        # The exact shape of the bug: /out/tmp/demo/in typed by mistake
        deep = tmp_path / "out" / "tmp" / "demo" / "in"
        assert validate_output_dir(deep) is not None
        assert not deep.exists(), "validation must not create the folder"

    @pytest.mark.skipif(AS_ROOT, reason="root bypasses write permissions")
    @pytest.mark.skipif(
        ON_WINDOWS,
        reason="Windows ignores the mkdir mode, and os.access does not consult "
        "directory ACLs, so a locked folder still reports as writable",
    )
    def test_unwritable_folder_is_rejected(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o500)
        assert validate_output_dir(locked) is not None


class TestMessages:
    def test_messages_are_human_readable(self, tmp_path):
        message = validate_output_dir(tmp_path / "missing")
        assert message[0].isupper()
        assert "Traceback" not in message
