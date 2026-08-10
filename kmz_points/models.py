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


@dataclass(frozen=True)
class Area:
    """One extracted Polygon: an outline, and any holes cut out of it.

    Corners are Points so they render through the same row builder as ordinary
    points, with every conversion already in place. A corner is a point that
    happens to belong to a shape.
    """

    name: str
    description: str
    outer: list[Point]
    holes: list[list[Point]] = field(default_factory=list)
    source_file: str = ""

    @property
    def corner_count(self) -> int:
        """Corners a reader would count.

        KML writes rings closed, repeating the first coordinate last, so the
        raw list has one more entry than the shape has corners -- a square
        would otherwise be reported as having five.
        """
        ring = self.outer
        if (
            len(ring) > 1
            and ring[0].lat == ring[-1].lat
            and ring[0].lon == ring[-1].lon
        ):
            return len(ring) - 1
        return len(ring)


@dataclass
class ParseResult:
    """What a single document yielded, plus what was ignored along the way."""

    points: list[Point] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchSummary:
    """Outcome of processing a batch of files."""

    files_read: int = 0
    files_failed: int = 0
    points_extracted: int = 0
    areas_extracted: int = 0
    features_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    output_path: str | None = None

    def as_text(self) -> str:
        lines = [
            f"{self.files_read} file(s) read",
            f"{self.points_extracted} point(s) extracted",
            f"{self.areas_extracted} area(s) extracted",
            f"{self.features_skipped} non-point feature(s) skipped",
        ]
        if self.files_failed:
            lines.append(f"{self.files_failed} file(s) failed")
        if self.output_path:
            lines.append(f"Saved to {self.output_path}")
        return "\n".join(lines)
