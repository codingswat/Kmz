"""Headless entry point.

The GUI and the CLI drive the same pipeline; this one just needs no display,
which is what makes the whole path testable in CI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kmz_points.pipeline import load_file, export_to_excel
from kmz_points.samples import write_samples


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kmz-points",
        description="Extract points from KML/KMZ files into one Excel table.",
    )
    parser.add_argument("files", nargs="*", help="KML or KMZ files to read")
    parser.add_argument(
        "-o",
        "--output-dir",
        help="where to write the workbook (default: folder of the first input)",
    )
    parser.add_argument(
        "--make-samples",
        metavar="DIR",
        help="write sample KML/KMZ inputs to DIR and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.make_samples:
        for path in write_samples(args.make_samples):
            print(f"wrote {path}")
        return 0

    if not args.files:
        parser.error("no input files given")

    loaded = [load_file(path) for path in args.files]
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.files[0]).parent

    summary = export_to_excel(loaded, output_dir)

    for item in loaded:
        status = f"{item.point_count} point(s)" if item.ok else f"FAILED - {item.error}"
        print(f"{item.name}: {status}")
    print()
    print(summary.as_text())
    for warning in summary.warnings:
        print(f"  warning: {warning}")

    return 0 if summary.output_path else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
