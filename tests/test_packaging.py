"""The package metadata must describe what the code actually needs.

These are not style checks. A dependency that is declared but not importable,
or importable but not declared, breaks a fresh `pip install .` -- which is
exactly the case nobody exercises locally because the venv already has
everything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# tomllib joined the standard library in 3.11, and this package supports 3.10.
# tomli is the same parser under its pre-adoption name, and the dev extra
# installs it only where it is actually needed.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def metadata() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_exists():
    assert PYPROJECT.is_file(), "pyproject.toml is the package definition"


def test_requirements_txt_is_gone():
    # Two files claiming to list the dependencies is one file too many; they
    # drifted apart once already.
    legacy = PYPROJECT.parent / "requirements.txt"
    assert not legacy.exists(), "requirements.txt was replaced by pyproject.toml"


def test_every_core_dependency_is_importable(metadata):
    # The headless CLI path must work with the core set alone -- no extras.
    modules = {
        "lxml": "lxml",
        "utm": "utm",
        "openpyxl": "openpyxl",
        "mgrs": "mgrs",
        "packaging": "packaging",
    }
    declared = " ".join(metadata["project"]["dependencies"])
    for distribution, module in modules.items():
        assert distribution in declared, f"{distribution} is used but not declared"
        __import__(module)


def test_flask_is_not_a_core_dependency(metadata):
    # The desktop app never imports Flask, and build.spec excludes it from the
    # frozen bundle. Promoting it to core would put it back in every install.
    declared = " ".join(metadata["project"]["dependencies"]).lower()
    assert "flask" not in declared
    assert "waitress" not in declared


def test_the_web_extra_carries_the_service_dependencies(metadata):
    web = " ".join(metadata["project"]["optional-dependencies"]["web"]).lower()
    assert "flask" in web
    # waitress serves it in production; without this the CI build job's pytest
    # and the lint job both fail on an unresolvable import.
    assert "waitress" in web


def test_entry_points_resolve(metadata):
    scripts = metadata["project"]["scripts"]
    assert scripts["kmz-points"] == "kmz_points.cli:main"

    from kmz_points.cli import main as cli_main

    assert callable(cli_main)


def test_requires_python_matches_the_readme(metadata):
    assert metadata["project"]["requires-python"] == ">=3.10"
