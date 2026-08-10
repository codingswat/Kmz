# PyInstaller build spec -- shared by Windows, macOS and Linux.
#
# Two dependencies do not survive a default freeze, because both resolve their
# native library at runtime from a path derived from their own __file__:
#
#   mgrs        ctypes-loads libmgrs from the directory *above* the mgrs
#               package. Under PyInstaller that parent directory is the bundle
#               root, so the library has to be collected to '.'.
#   tkinterdnd2 asks Tcl to `package require tkdnd` from a platform-specific
#               subdirectory of its own package folder, so that tree has to
#               keep its layout inside the bundle.
#
# Neither failure shows up at build time -- the freeze succeeds and the import
# succeeds. Run `--selftest` against the frozen build to actually exercise them.

import sys
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

import mgrs
import tkinterdnd2

site_packages = Path(mgrs.__file__).parent.parent


def _libmgrs() -> list[tuple[str, str]]:
    """Locate the compiled libmgrs, matching mgrs/core.py's own naming rules."""
    if sys.platform == "win32":
        from packaging.tags import cpython_tags

        tag = next(iter(cpython_tags()))
        candidates = [f"libmgrs.{tag.abi}-{tag.platform}.pyd"]
    else:
        soabi = sysconfig.get_config_var("SOABI")
        candidates = [f"libmgrs.{soabi}.so" if soabi else "", "libmgrs.so"]

    for name in filter(None, candidates):
        for directory in (site_packages, site_packages / "mgrs"):
            path = directory / name
            if path.exists():
                # '.' is the bundle root: what mgrs computes as ../ from itself.
                return [(str(path), ".")]

    raise SystemExit(
        f"build.spec: no libmgrs found in {site_packages}. "
        f"Looked for: {', '.join(filter(None, candidates))}. "
        "Reinstall with `pip install --force-reinstall mgrs`."
    )


# collect_data_files keeps the tkdnd/<platform>/ subtree at its original
# relative path, which is what TkinterDnD.py reconstructs at runtime.
datas = collect_data_files("tkinterdnd2")

binaries = _libmgrs()

hiddenimports = [
    "packaging.tags",  # imported by mgrs.core but not declared as a dependency
    "tkinterdnd2",
    "utm",
    "openpyxl",
    "lxml.etree",
    "lxml._elementpath",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Flask and its dependencies belong to serve.py, which is never frozen --
    # only the owner runs the server, colleagues just open a browser. They are
    # in requirements.txt, so CI installs them before building, and excluding
    # them explicitly keeps them out of the bundle rather than relying on
    # run.py's import graph never happening to reach them.
    excludes=[
        "pytest",
        "numpy",
        "pandas",
        "matplotlib",
        "flask",
        "werkzeug",
        "jinja2",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KmzPoints",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Windows and Linux: keep the console, because a windowed Windows build has
    # no stdout and `--selftest` would print nothing.
    #
    # macOS: must be windowed. PyInstaller stamps LSBackgroundOnly=True into the
    # .app's Info.plist for a console build, which denies the bundle a Dock icon
    # and a menu bar and stops its window being brought to the front -- the GUI
    # launches and is then unreachable. Nothing is lost: unlike Windows, a
    # windowed macOS binary still writes to an inherited stdout, so running the
    # inner Contents/MacOS/KmzPoints --selftest from a terminal still reports.
    console=sys.platform != "darwin",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="KmzPoints.app",
        icon=None,
        bundle_identifier="com.codingswat.kmzpoints",
        info_plist={
            "CFBundleName": "KML KMZ Point Extractor",
            "CFBundleDisplayName": "KML KMZ Point Extractor",
            "NSHighResolutionCapable": True,
        },
    )
