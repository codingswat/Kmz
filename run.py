#!/usr/bin/env python3
"""Launch the KML/KMZ Point Extractor GUI.

``--selftest`` runs a headless end-to-end check instead of opening the window.
CI uses it to verify that a packaged build actually works, rather than only
that it compiled.
"""

import sys


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        from kmz_points.selftest import run_selftest

        code, report = run_selftest()
        print(report)
        return code

    from kmz_points.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
