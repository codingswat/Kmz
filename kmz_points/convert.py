"""Coordinate conversions.

Pure functions -- no I/O, no logging, no global state beyond a lazily built
MGRS handle. Every function is total: out-of-range input yields None rather
than an exception, so one bad point can never abort a batch.

Rounding carries. Formatting 34.99999999 by truncating degrees and rounding
minutes independently gives "34 deg 60.0000'", which is not a coordinate. Each
formatter rounds the smallest unit first, then propagates any overflow upward.
"""

from __future__ import annotations

from dataclasses import dataclass

import utm as _utm

_HEMISPHERES = {"lat": ("N", "S"), "lon": ("E", "W")}

# UTM is only defined between these latitudes; beyond them use UPS instead.
_UTM_MIN_LAT = -80.0
_UTM_MAX_LAT = 84.0

_mgrs_handle = None


def _hemisphere(value: float, axis: str) -> str:
    try:
        positive, negative = _HEMISPHERES[axis]
    except KeyError:
        raise ValueError(f"axis must be 'lat' or 'lon', got {axis!r}") from None
    return positive if value >= 0 else negative


def _in_range(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def format_dd(value: float) -> str:
    """Signed decimal degrees to 6 places: ``34.567890``."""
    rounded = round(value, 6)
    if rounded == 0:
        rounded = 0.0  # collapse -0.0 so tiny negatives don't render as "-0.000000"
    return f"{rounded:.6f}"


def format_ddm(value: float, axis: str) -> str:
    """Degrees and decimal minutes: ``34° 34.0734' N``."""
    hemisphere = _hemisphere(value, axis)
    magnitude = abs(value)

    degrees = int(magnitude)
    minutes = round((magnitude - degrees) * 60, 4)
    if minutes >= 60:
        minutes -= 60
        degrees += 1

    return f"{degrees}° {minutes:.4f}' {hemisphere}"


def format_dms(value: float, axis: str) -> str:
    """Degrees, minutes and seconds: ``34° 34' 4.40" N``."""
    hemisphere = _hemisphere(value, axis)
    magnitude = abs(value)

    degrees = int(magnitude)
    total_minutes = (magnitude - degrees) * 60
    minutes = int(total_minutes)
    seconds = round((total_minutes - minutes) * 60, 2)

    if seconds >= 60:
        seconds -= 60
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        degrees += 1

    return f'{degrees}° {minutes}\' {seconds:.2f}" {hemisphere}'


@dataclass(frozen=True)
class UtmPoint:
    """A UTM position. ``zone`` carries the latitude band, e.g. ``37S``."""

    zone: str
    easting: int
    northing: int

    @property
    def label(self) -> str:
        return f"{self.zone} {self.easting} E {self.northing} N"


def to_utm(lat: float, lon: float) -> UtmPoint | None:
    """Convert to UTM, or None where UTM is undefined (polar regions)."""
    if not _in_range(lat, lon) or not (_UTM_MIN_LAT <= lat <= _UTM_MAX_LAT):
        return None
    try:
        easting, northing, zone_number, band = _utm.from_latlon(lat, lon)
    except Exception:
        return None
    return UtmPoint(f"{zone_number}{band}", round(easting), round(northing))


def to_mgrs(lat: float, lon: float) -> str | None:
    """Convert to an MGRS grid reference, or None if it cannot be computed."""
    global _mgrs_handle
    if not _in_range(lat, lon):
        return None
    try:
        if _mgrs_handle is None:
            import mgrs

            _mgrs_handle = mgrs.MGRS()
        return _mgrs_handle.toMGRS(lat, lon)
    except Exception:
        return None
