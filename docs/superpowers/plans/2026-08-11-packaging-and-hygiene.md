# Packaging and Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the project real package metadata, a reproducible release build, and lint/type checking in CI, without changing any runtime behaviour.

**Architecture:** This is phase 1 of 6 implementing `docs/superpowers/specs/2026-08-11-review-improvements-design.md` (steps 1–4 of its ordering). It is deliberately behaviour-free: no output changes, no new refusals, no new columns. It lands first because `requirements.txt` and `build.spec` are contended by three later phases, and doing packaging last would guarantee a rebase.

**Tech Stack:** Python 3.10+, setuptools, ruff 0.16, mypy, pytest, GitHub Actions.

## Global Constraints

- **Nothing in this phase may change runtime behaviour.** The 331 Python tests and 12 node tests must pass identically before and after, with no test edited to accommodate a change.
- **Never enable ruff `BLE` or `DTZ`.** `BLE001` objects to broad `except Exception`, which is how this project guarantees a bad file never aborts a batch — it is documented in `kmz_points/pipeline.py`, `convert.py` and `geometry.py` module docstrings. `DTZ` objects to naive datetimes, but `output_filename()` deliberately uses local time so a user's workbook carries their own timestamp. Enabling either fights a deliberate, documented design decision.
- **Ruff line-length is 100**, which is the codebase's natural width. At 88 there are 14 violations; at 100 there are 2, both of which are `noqa`, not rewraps.
- Python floor is **3.10** (`README.md` states 3.10+; the code uses `X | Y` unions under `from __future__ import annotations`).
- Baseline to preserve: `pytest -q` → 331 passed. `node --test "web/test/*.test.mjs"` → 12 pass.

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `pyproject.toml` | Package metadata, dependencies, extras, entry points, ruff + mypy config | Create |
| `requirements.txt` | Superseded by `pyproject.toml` | Delete (Task 4) |
| `requirements-release.txt` | Pinned versions for reproducible release binaries | Create (Task 5) |
| `.gitignore` | Add `.DS_Store` | Modify |
| `README.md` | Test count; install instructions | Modify |
| `BUILDING.md` | Install instructions (3 sites) | Modify |
| `Run on Windows.bat` | Install instruction (1 site) | Modify |
| `build.spec` | Comment referencing requirements.txt | Modify |
| `.github/workflows/build.yml` | Install steps (2 sites), new `lint` job, release gating | Modify |
| `tests/test_packaging.py` | Asserts the package metadata is consistent and importable | Create (Task 4) |

---

## Task 1: Hygiene — gitignore, stray files, stale test count

**Files:**
- Modify: `.gitignore`
- Modify: `README.md:167`

**Interfaces:**
- Consumes: nothing
- Produces: nothing. Purely textual.

- [ ] **Step 1: Confirm the current test count**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1`

Expected: `331 passed in ...`. If the number differs, use the number you observe in Step 3 rather than 331.

- [ ] **Step 2: Add `.DS_Store` to `.gitignore`**

Append to the end of `.gitignore`:

```gitignore

# macOS Finder metadata, created just by opening a folder in the GUI.
.DS_Store
```

- [ ] **Step 3: Correct the stale test count in `README.md`**

`README.md` line 167 currently reads:

```markdown
301 tests. The GUI tests need a display and skip without one; on a headless
```

Replace `301` with the count from Step 1:

```markdown
331 tests. The GUI tests need a display and skip without one; on a headless
```

- [ ] **Step 4: Verify nothing else regressed**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `331 passed`

Run: `git status --porcelain`
Expected: `.DS_Store` no longer appears as untracked. `M .gitignore` and `M README.md` appear.

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md
git commit -m "Ignore .DS_Store, and correct the test count

The README has said 301 since before the areas work landed; it is 331."
```

**NOTE — do not delete `.claude/settings.local 2.json`.** It is the user's file and the spec assigns its removal to them, not to this work.

---

## Task 2: Ruff — configuration and the fixes it demands

**Files:**
- Create: `pyproject.toml` (ruff section only; Task 4 adds the rest)
- Modify: `kmz_points/cli.py`, `kmz_points/excel.py`, `kmz_points/gui.py`, `kmz_points/geometry.py`, `kmz_points/samples.py`
- Modify: `tests/test_gui.py`, `tests/test_kml_parser.py`, `tests/test_serve.py`, `tests/test_server.py`, `tests/test_table.py`
- Modify (permissions only): `run.py`, `serve.py`

**Interfaces:**
- Consumes: nothing
- Produces: `pyproject.toml` with a `[tool.ruff]` section. Task 3 appends `[tool.mypy]` to the same file; Task 4 prepends `[project]`.

- [ ] **Step 1: Create `pyproject.toml` with only the ruff configuration**

```toml
[tool.ruff]
# 100, not the default 88. At 88 fourteen existing lines violate; at 100 only
# two do, and both are KML fixtures that must not be rewrapped. The codebase
# was written at roughly this width.
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "C4", "EXE", "SIM"]

# BLE and DTZ are deliberately NOT selected.
#
# BLE001 objects to `except Exception`. This project's central invariant is
# that nothing raises on bad input -- a corrupt file, a malformed coordinate
# or an unmeasurable shape becomes a warning and the batch still exports.
# That is implemented with exactly the broad catches BLE forbids, and it is
# documented in the module docstrings of pipeline.py, convert.py and
# geometry.py. Enabling BLE would mean either 16 noqa comments or abandoning
# the invariant.
#
# DTZ objects to naive datetimes. output_filename() uses local time on
# purpose: a workbook called points_20260811_1432.xlsx should carry the
# timestamp the person who made it would recognise, not UTC.

[tool.ruff.lint.per-file-ignores]
# These two lines are CDATA inside KML fixture strings. Rewrapping them would
# insert a newline into the KML the parser reads, changing what the test
# actually exercises -- so the line stays long and the rule is silenced.
"kmz_points/samples.py" = ["E501"]
"tests/test_kml_parser.py" = ["E501"]
```

- [ ] **Step 2: Run ruff to see the failures**

Run: `.venv/bin/ruff check .`

Expected: 15 errors — 12 auto-fixable (`I001`, `F401`, `UP012`), plus `B905` in `geometry.py`, `SIM105` in `gui.py`, and `EXE001` on `run.py` and `serve.py`.

- [ ] **Step 3: Apply the automatic fixes**

Run: `.venv/bin/ruff check . --fix`

This sorts five import blocks, removes four genuinely unused imports (`os` in `test_gui.py`, `pytest` in `test_kml_parser.py` and `test_serve.py`, `DETAILS` in `test_table.py`), and rewrites two `.encode("utf-8")` calls in `test_server.py`.

- [ ] **Step 4: Fix `B905` by hand in `kmz_points/geometry.py:78`**

`zip()` without `strict=` silently truncates to the shorter argument. Here both arguments are the same length by construction, so `strict=True` documents that and would catch a future edit that broke it.

Replace:

```python
    for (x1, y1), (x2, y2) in zip(projected, projected[1:] + projected[:1]):
```

with:

```python
    # strict: both arguments are the same ring, so a length mismatch would be
    # a bug rather than an input we should tolerate.
    for (x1, y1), (x2, y2) in zip(
        projected, projected[1:] + projected[:1], strict=True
    ):
```

- [ ] **Step 5: Fix `SIM105` by hand in `kmz_points/gui.py:62-66`**

Replace:

```python
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # a Tcl build without clam; native styling still works
        pass
```

with:

```python
    style = ttk.Style(root)
    # A Tcl build without clam; native styling still works.
    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")
```

and add `import contextlib` to the import block at the top of `kmz_points/gui.py`, before `import re`:

```python
import contextlib
import re
import tkinter as tk
```

- [ ] **Step 6: Fix `EXE001` by making the two entry scripts executable**

Both files begin `#!/usr/bin/env python3` but are not executable, so the shebang is a lie. Make it true rather than deleting it — `BUILDING.md` and `README.md` both tell users to run `python run.py`, and a working `./run.py` is strictly better.

```bash
chmod +x run.py serve.py
git update-index --chmod=+x run.py serve.py
```

- [ ] **Step 7: Verify ruff is clean**

Run: `.venv/bin/ruff check .`
Expected: `All checks passed!`

- [ ] **Step 8: Verify no behaviour changed**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `331 passed`

This is the important check. Import sorting and unused-import removal are supposed to be inert; if the count moved, an import was load-bearing and must be restored with a comment saying why.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml kmz_points/ tests/ run.py serve.py
git commit -m "Adopt ruff, minus the two rules that fight the design

BLE001 forbids the broad excepts that implement 'nothing aborts a batch',
and DTZ forbids the local timestamps that name the workbook. Both are
deliberate and documented, so neither rule is selected.

Line length is 100, the width the code was written at. The two lines over
it are CDATA inside KML fixtures, where rewrapping would change what the
parser reads, so they are silenced per-file rather than reflowed."
```

---

## Task 3: Mypy — configuration and the six real errors

**Files:**
- Modify: `pyproject.toml` (append `[tool.mypy]`)
- Modify: `kmz_points/excel.py:273`, `kmz_points/selftest.py:52-55`, `kmz_points/gui.py:42`

**Interfaces:**
- Consumes: `pyproject.toml` from Task 2
- Produces: nothing new at runtime. `_scaled()` keeps its signature but with a narrowed `weight` parameter type.

- [ ] **Step 1: Append the mypy configuration to `pyproject.toml`**

```toml
[tool.mypy]
python_version = "3.10"
# Deliberately not --strict. The codebase is annotated but not exhaustively,
# and the aim here is a check that passes today and catches real mistakes
# tomorrow, not a migration project.
warn_redundant_casts = true
warn_unused_ignores = true
no_implicit_optional = true
check_untyped_defs = false

[[tool.mypy.overrides]]
# None of these ship type information. mgrs and utm are small C-backed or
# untyped packages; lxml's stubs live in a separate distribution that would
# be a new dev dependency for no benefit here.
module = [
    "lxml.*",
    "mgrs.*",
    "openpyxl.*",
    "tkinterdnd2.*",
    "utm.*",
    "geographiclib.*",
]
ignore_missing_imports = true
```

- [ ] **Step 2: Run mypy to see the six failures**

Run: `.venv/bin/mypy kmz_points/`

Expected: 6 errors in 3 files — one in `excel.py`, four in `selftest.py`, one in `gui.py`.

- [ ] **Step 3: Fix `excel.py:273` — the ring list's element type**

`rings` is inferred as `list[tuple[None, list[Point]]]` from its first element, so appending a `str` label fails. Annotate it with the type it is actually meant to hold.

Replace:

```python
        rings = [(None, measured.area.outer)]
```

with:

```python
        # The label is None for the outer ring and a banner string for a hole;
        # annotated because the first element alone would infer it as None-only.
        rings: list[tuple[str | None, list]] = [(None, measured.area.outer)]
```

- [ ] **Step 4: Fix `selftest.py:52` — rebinding a `str` to a `Path`**

`with tempfile.TemporaryDirectory() as workspace` binds `workspace: str`, and the next line rebinds it to a `Path`. Use a second name instead.

Replace:

```python
    with tempfile.TemporaryDirectory() as workspace:
        workspace = Path(workspace)
        try:
            samples = write_samples(workspace / "in")
            summary = run(samples, workspace / "out")
```

with:

```python
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        try:
            samples = write_samples(root / "in")
            summary = run(samples, root / "out")
```

Then run `grep -n "workspace" kmz_points/selftest.py` and replace every remaining `workspace /` with `root /` inside that `with` block. Leave the `with ... as workspace:` line itself unchanged.

- [ ] **Step 5: Fix `gui.py:42` — the font weight literal**

Tk's `configure(weight=...)` accepts only `"normal"` or `"bold"`. Say so.

Add to the import block at the top of `kmz_points/gui.py`:

```python
from typing import Literal
```

Replace:

```python
def _scaled(base: tkfont.Font, factor: float, weight: str = "normal") -> tkfont.Font:
```

with:

```python
def _scaled(
    base: tkfont.Font,
    factor: float,
    weight: Literal["normal", "bold"] = "normal",
) -> tkfont.Font:
```

- [ ] **Step 6: Verify mypy is clean**

Run: `.venv/bin/mypy kmz_points/`
Expected: `Success: no issues found in 15 source files`

- [ ] **Step 7: Verify ruff is still clean and behaviour is unchanged**

Run: `.venv/bin/ruff check .`
Expected: `All checks passed!`

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `331 passed`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml kmz_points/
git commit -m "Adopt mypy, and fix the six things it found

All six are real: a list whose element type was inferred from its first
entry, a str rebound to a Path inside a with-block, and a font weight that
Tk only accepts two values for."
```

---

## Task 4: Package metadata, and the end of `requirements.txt`

**Files:**
- Modify: `pyproject.toml` (prepend `[build-system]` and `[project]`)
- Delete: `requirements.txt`
- Modify: `README.md`, `BUILDING.md` (3 sites), `Run on Windows.bat`, `build.spec`, `.github/workflows/build.yml` (2 sites)
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `pyproject.toml` from Tasks 2 and 3
- Produces: installable distribution `kmz-points`; console script `kmz-points` → `kmz_points.cli:main`; GUI script `kmz-points-gui` → `kmz_points.gui:main`; extras `gui`, `web`, `dev`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_packaging.py`:

```python
"""The package metadata must describe what the code actually needs.

These are not style checks. A dependency that is declared but not importable,
or importable but not declared, breaks a fresh `pip install .` -- which is
exactly the case nobody exercises locally because the venv already has
everything.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def metadata() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_exists():
    assert PYPROJECT.is_file(), "pyproject.toml is the package definition"


def test_requirements_txt_is_gone(metadata):
    # Two files claiming to list the dependencies is one file too many; they
    # drifted apart once already.
    legacy = PYPROJECT.parent / "requirements.txt"
    assert not legacy.exists(), "requirements.txt was replaced by pyproject.toml"


def test_every_core_dependency_is_importable(metadata):
    # The desktop CLI path must work with the core set alone -- no extras.
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q`

Expected: FAIL. `test_pyproject_exists` passes (Task 2 created it), but `KeyError: 'project'` on the others, and `test_requirements_txt_is_gone` fails because the file is still there.

- [ ] **Step 3: Prepend the build system and project metadata to `pyproject.toml`**

Insert this **above** the existing `[tool.ruff]` section:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "kmz-points"
version = "1.1.0"
description = "Pull every point and area out of KML/KMZ files into one Excel workbook"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "lxml>=5.0",       # KML parsing
    "utm>=0.7",        # UTM easting/northing + latitude band
    "openpyxl>=3.1",   # Excel output
    "mgrs>=1.4",       # MGRS grid references
    # mgrs.core imports packaging at runtime without declaring it, so
    # installing mgrs alone fails with ModuleNotFoundError.
    "packaging>=23.0",
]

[project.optional-dependencies]
# Drag-and-drop. The GUI falls back to the Browse button when this is missing
# or the platform's tkdnd library will not load, so it is genuinely optional.
gui = ["tkinterdnd2>=0.4"]
# Only serve.py needs these. The desktop app never imports Flask and
# build.spec excludes it, waitress and their dependencies from the bundle.
web = ["flask>=3.0", "waitress>=3.0"]
dev = ["pytest>=8.0", "ruff>=0.16", "mypy>=1.8"]

[project.scripts]
kmz-points = "kmz_points.cli:main"

[project.gui-scripts]
# gui-scripts, not scripts: on Windows this produces a launcher with no
# console window behind the app.
kmz-points-gui = "kmz_points.gui:main"

[tool.setuptools]
packages = ["kmz_points"]
```

- [ ] **Step 4: Delete `requirements.txt` and update all eight references**

```bash
git rm requirements.txt
```

There are exactly eight live references across five files (historical documents under `docs/` are records of past decisions and must NOT be edited).

**`.github/workflows/build.yml`** — two sites. Replace both occurrences of:

```yaml
          pip install -r requirements.txt
```

In the `web` job, with:

```yaml
          pip install -e .
```

In the `build` job (which also installs pyinstaller on the following line), with:

```yaml
          pip install -e ".[gui,web,dev]"
```

**`BUILDING.md`** — three sites. Replace:

```
pip install -r requirements.txt pyinstaller
```

with:

```
pip install -e ".[gui,web,dev]" pyinstaller
```

in both the Mac and Windows build sections, and replace:

```bash
pip install -r requirements.txt
```

with:

```bash
pip install -e ".[web]"
```

in the "Running the service for colleagues" section.

**`README.md`** — one site. Replace:

```bash
pip install -r requirements.txt
```

with:

```bash
pip install -e ".[gui]"
```

**`Run on Windows.bat`** — one site. Replace `-r requirements.txt` with `-e ".[gui]"`.

**`build.spec`** — one site, a comment. Replace the phrase `They are in requirements.txt, so CI installs them before building` with `They are in the web extra, so CI installs them before building`.

- [ ] **Step 5: Verify the tests pass**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q`
Expected: `8 passed`

- [ ] **Step 6: Verify a clean install actually works**

This is the check the test cannot make from inside an already-populated venv.

```bash
python3 -m venv /tmp/kmz-install-check
/tmp/kmz-install-check/bin/pip install -q -e ".[gui,web,dev]"
/tmp/kmz-install-check/bin/kmz-points --help
/tmp/kmz-install-check/bin/python -m pytest -q 2>&1 | tail -1
rm -rf /tmp/kmz-install-check
```

Expected: the help text prints, and the suite reports `331 passed`.

- [ ] **Step 7: Verify nothing else regressed**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `339 passed` (331 baseline + 8 new packaging tests)

Run: `.venv/bin/ruff check . && .venv/bin/mypy kmz_points/`
Expected: both clean.

Run: `grep -rn "requirements\.txt" .github/ BUILDING.md README.md "Run on Windows.bat" build.spec`
Expected: no matches.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Replace requirements.txt with real package metadata

Extras make the shape explicit that was previously a comment: the desktop
app needs neither Flask nor waitress, and build.spec already excluded them.
Two console scripts, with the GUI one under gui-scripts so Windows does not
put a console window behind the app.

All eight live references updated. The ones under docs/ are records of past
decisions and are left alone."
```

---

## Task 5: Lockfile for release builds, and lint in CI

**Files:**
- Create: `requirements-release.txt`
- Modify: `.github/workflows/build.yml`

**Interfaces:**
- Consumes: `pyproject.toml` from Task 4
- Produces: a `lint` CI job that the `release` job depends on.

- [ ] **Step 1: Generate the lockfile**

```bash
.venv/bin/pip install --quiet pip-tools
.venv/bin/pip-compile --extra gui --extra web --output-file requirements-release.txt pyproject.toml
```

- [ ] **Step 2: Add a header explaining what it is for**

Prepend to `requirements-release.txt`, above pip-compile's own header:

```
#
# Pinned for RELEASE BUILDS ONLY.
#
# Developers install with `pip install -e ".[gui,web,dev]"` and get the
# flexible floors from pyproject.toml. This file exists so that a binary
# built from a tag six months from now is the same binary, rather than
# whatever happened to be newest on PyPI that morning.
#
# Regenerate with:
#   pip-compile --extra gui --extra web --output-file requirements-release.txt pyproject.toml
#
```

- [ ] **Step 3: Add the `lint` job to `.github/workflows/build.yml`**

Insert as a new top-level job, after the `web` job and before `build`:

```yaml
  lint:
    name: Lint and types
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[gui,web,dev]"

      - name: Ruff
        run: ruff check .

      - name: Mypy
        run: mypy kmz_points/
```

- [ ] **Step 4: Make the release build use the lockfile**

In the `build` job, replace:

```yaml
          pip install -e ".[gui,web,dev]"
          pip install pyinstaller
```

with:

```yaml
          # Pinned for the artifact we ship; the flexible floors are for
          # developers. -e . installs the package itself without re-resolving
          # its dependencies, which the lockfile has already fixed.
          pip install -r requirements-release.txt
          pip install -e . --no-deps
          pip install pytest pyinstaller
```

- [ ] **Step 5: Gate the release on lint as well**

Replace:

```yaml
    needs: [build, web]
```

with:

```yaml
    needs: [build, web, lint]
```

and extend the comment above it to name the third gate:

```yaml
    # Three gates, not one. The browser version is part of what ships, and a
    # release carrying code that does not lint or type-check is a release
    # nobody can safely patch in a hurry.
```

- [ ] **Step 6: Add a staleness check so the lockfile cannot silently rot**

Add to the `lint` job, after the Mypy step:

```yaml
      - name: Check the release lockfile is current
        run: |
          pip install pip-tools
          pip-compile --quiet --extra gui --extra web \
            --output-file /tmp/requirements-release.txt pyproject.toml
          diff -u requirements-release.txt /tmp/requirements-release.txt \
            || (echo "::error::requirements-release.txt is out of date. Run pip-compile and commit it." && exit 1)
```

- [ ] **Step 7: Verify the workflow is valid YAML and the jobs are wired**

```bash
.venv/bin/python -c "
import yaml, pathlib
w = yaml.safe_load(pathlib.Path('.github/workflows/build.yml').read_text())
print('jobs:', sorted(w['jobs']))
print('release needs:', w['jobs']['release']['needs'])
assert set(w['jobs']['release']['needs']) == {'build', 'web', 'lint'}
print('OK')
"
```

Expected: `jobs: ['build', 'lint', 'release', 'web']`, `release needs: ['build', 'web', 'lint']`, `OK`.

- [ ] **Step 8: Verify the lint job's commands pass locally**

Run: `.venv/bin/ruff check . && .venv/bin/mypy kmz_points/ && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: ruff clean, mypy clean, `339 passed`.

- [ ] **Step 9: Commit**

```bash
git add requirements-release.txt .github/workflows/build.yml
git commit -m "Pin the release build, and gate it on lint

Developers keep the flexible floors; the binaries we hand people are built
from pinned versions, so a build from a tag is reproducible rather than
dependent on what PyPI served that morning. A staleness check keeps the
lockfile honest, in the same shape as the existing one for the browser
bundle."
```

---

## Self-Review

**Spec coverage.** This plan implements steps 1–4 of the spec's ordering: hygiene and the test count (Task 1), ruff and mypy with a non-gating-then-gating lint job (Tasks 2, 3, 5), `pyproject.toml` with extras and entry points plus the removal of `requirements.txt` and its eight references (Task 4), and the release lockfile (Task 5). The spec's requirement that `waitress` be in the `web` extra is covered by Task 4 Step 3 and asserted by `test_the_web_extra_carries_the_service_dependencies`. The spec's instruction that the owner deletes `.claude/settings.local 2.json` is honoured by the explicit note in Task 1.

Not in this plan, by design: steps 5–15 of the spec, which are behavioural and belong to later phases.

**Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". Every code step carries the literal text to write. The one number an implementer must observe rather than copy is the test count in Task 1, which Step 1 tells them to measure.

**Type consistency.** `_scaled` is referenced only within `gui.py` and keeps its name and arity across Task 3. `main` is referenced as `kmz_points.cli:main` in the entry point and asserted by the same string in `test_entry_points_resolve`. The extras `gui`, `web`, `dev` are named identically in `pyproject.toml`, every install command, and the packaging tests.

**One known interaction with a later phase.** Task 2 Step 3 removes `import pytest` from `tests/test_serve.py` as unused. Phase 6 (the LAN service) adds throttling tests to that file which will need it again. That is correct: it is unused now, and ruff will flag its absence the moment it is needed. Do not pre-emptively keep it.
