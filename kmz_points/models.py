"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Point:
    """One extracted placemark point.

    ``lon``/``lat`` are stored in the order KML uses them, not the order they
    are displayed in.
    """

    name: str
    description: str
    lon: float
    lat: float
    alt: float | None
    source_file: str


@dataclass
class ParseResult:
    """Points found in a single document, plus what was ignored along the way."""

    points: list[Point] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchSummary:
    """Outcome of processing a batch of files."""

    files_read: int = 0
    files_failed: int = 0
    points_extracted: int = 0
    features_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    output_path: str | None = None

    def as_text(self) -> str:
        lines = [
            f"{self.files_read} file(s) read",
            f"{self.points_extracted} point(s) extracted",
            f"{self.features_skipped} non-point feature(s) skipped",
        ]
        if self.files_failed:
            lines.append(f"{self.files_failed} file(s) failed")
        if self.output_path:
            lines.append(f"Saved to {self.output_path}")
        return "\n".join(lines)
