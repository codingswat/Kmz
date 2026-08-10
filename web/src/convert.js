/**
 * Coordinate conversions.
 *
 * A port of kmz_points/convert.py. Pure functions, no I/O. Every function is
 * total: out-of-range input yields null rather than throwing, so one bad
 * point can never abort a batch.
 *
 * UTM and MGRS are implemented here rather than pulled from a library
 * because the Python side gets MGRS from a compiled C library, which has no
 * browser equivalent. The formulas are the standard ones and the results are
 * checked against the Python implementation, coordinate by coordinate.
 *
 * Rounding carries. Formatting 34.99999999 by truncating degrees and
 * rounding minutes independently gives "34 deg 60.0000'", which is not a
 * coordinate, so each formatter rounds the smallest unit first and
 * propagates any overflow upward.
 */

// WGS 84.
const A = 6378137.0;
const F = 1 / 298.257223563;
const E2 = F * (2 - F);
const E_PRIME2 = E2 / (1 - E2);
const K0 = 0.9996;

const UTM_MIN_LAT = -80.0;
const UTM_MAX_LAT = 84.0;

const RAD = Math.PI / 180;

/** The latitude band letter, C through X with I and O skipped. */
export function latitudeBand(lat) {
  if (lat < UTM_MIN_LAT || lat > UTM_MAX_LAT) return null;
  const letters = "CDEFGHJKLMNPQRSTUVWXX";
  return letters[Math.floor((lat + 80) / 8)];
}

function zoneNumber(lat, lon) {
  // Two exceptions to the regular 6-degree grid, both long-standing.
  if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) return 32;
  if (lat >= 72 && lat < 84 && lon >= 0) {
    if (lon < 9) return 31;
    if (lon < 21) return 33;
    if (lon < 33) return 35;
    if (lon < 42) return 37;
  }
  return Math.floor((lon + 180) / 6) + 1;
}

function inRange(lat, lon) {
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

/**
 * Project to UTM. Returns {zone, band, easting, northing} or null where UTM
 * is undefined. `forceZone` keeps a shape's corners on one grid.
 */
export function toUtm(lat, lon, forceZone = null) {
  if (!inRange(lat, lon)) return null;
  if (lat < UTM_MIN_LAT || lat > UTM_MAX_LAT) return null;

  const zone = forceZone || zoneNumber(lat, lon);
  const band = latitudeBand(lat);

  const latRad = lat * RAD;
  const lonRad = lon * RAD;
  const centralMeridian = ((zone - 1) * 6 - 180 + 3) * RAD;

  const n = A / Math.sqrt(1 - E2 * Math.sin(latRad) ** 2);
  const t = Math.tan(latRad) ** 2;
  const c = E_PRIME2 * Math.cos(latRad) ** 2;
  const a = Math.cos(latRad) * (lonRad - centralMeridian);

  const m =
    A *
    ((1 - E2 / 4 - (3 * E2 ** 2) / 64 - (5 * E2 ** 3) / 256) * latRad -
      ((3 * E2) / 8 + (3 * E2 ** 2) / 32 + (45 * E2 ** 3) / 1024) *
        Math.sin(2 * latRad) +
      ((15 * E2 ** 2) / 256 + (45 * E2 ** 3) / 1024) * Math.sin(4 * latRad) -
      ((35 * E2 ** 3) / 3072) * Math.sin(6 * latRad));

  const easting =
    K0 *
      n *
      (a +
        ((1 - t + c) * a ** 3) / 6 +
        ((5 - 18 * t + t ** 2 + 72 * c - 58 * E_PRIME2) * a ** 5) / 120) +
    500000.0;

  let northing =
    K0 *
    (m +
      n *
        Math.tan(latRad) *
        (a ** 2 / 2 +
          ((5 - t + 9 * c + 4 * c ** 2) * a ** 4) / 24 +
          ((61 - 58 * t + t ** 2 + 600 * c - 330 * E_PRIME2) * a ** 6) / 720));

  if (lat < 0) northing += 10000000.0; // false northing in the south

  return { zone, band, easting, northing };
}

/** ``37S 419595 E 3825474 N`` */
export function utmLabel(point) {
  if (!point) return "";
  return `${point.zone}${point.band} ${Math.round(point.easting)} E ${Math.round(point.northing)} N`;
}

// MGRS 100km square lettering, the AA scheme WGS 84 uses. I and O are absent
// throughout: they are too easily read as 1 and 0.
const COLUMN_LETTERS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"];
const ROW_LETTERS = ["ABCDEFGHJKLMNPQRSTUV", "FGHJKLMNPQRSTUVABCDE"];

/**
 * An MGRS grid reference at 1 m precision, e.g. ``37SDU1959425474``, or null
 * where it cannot be computed.
 */
export function toMgrs(lat, lon) {
  const point = toUtm(lat, lon);
  if (!point) return null;

  const { zone, band, easting, northing } = point;

  const columnSet = (zone - 1) % 3;
  const columnIndex = Math.floor(easting / 100000) - 1;
  if (columnIndex < 0 || columnIndex > 7) return null;
  const columnLetter = COLUMN_LETTERS[columnSet][columnIndex];

  const rowSet = (zone - 1) % 2;
  const rowIndex = Math.floor(northing / 100000) % 20;
  const rowLetter = ROW_LETTERS[rowSet][rowIndex];

  const eastPart = String(Math.floor(easting % 100000)).padStart(5, "0");
  const northPart = String(Math.floor(northing % 100000)).padStart(5, "0");

  // Zone is zero-padded to two digits, as MGRS references conventionally
  // are: "02CNS...", not "2CNS...".
  const zonePart = String(zone).padStart(2, "0");
  return `${zonePart}${band}${columnLetter}${rowLetter}${eastPart}${northPart}`;
}

/** Signed decimal degrees to six places: ``34.567890``. */
export function formatDd(value) {
  const rounded = Math.round(value * 1e6) / 1e6;
  // Collapse -0 so a tiny negative does not render as "-0.000000".
  return (rounded === 0 ? 0 : rounded).toFixed(6);
}

function hemisphere(value, axis) {
  if (axis === "lat") return value >= 0 ? "N" : "S";
  return value >= 0 ? "E" : "W";
}

/**
 * Whole degrees, whole minutes and seconds, all as MAGNITUDES.
 *
 * The sign is deliberately not carried: degrees cannot express it for a value
 * between -1 and 0, since a latitude of -0.180653 is south but its
 * whole-degree part is 0, and 0 has no sign. Callers pair these with the
 * signed decimal, which is what tells you the hemisphere.
 */
export function dmsParts(value) {
  const magnitude = Math.abs(value);
  let degrees = Math.floor(magnitude);
  const totalMinutes = (magnitude - degrees) * 60;
  let minutes = Math.floor(totalMinutes);
  let seconds = Math.round((totalMinutes - minutes) * 60 * 100) / 100;

  if (seconds >= 60) {
    seconds -= 60;
    minutes += 1;
  }
  if (minutes >= 60) {
    minutes -= 60;
    degrees += 1;
  }
  return { degrees, minutes, seconds };
}

/** ``34° 34.0734' N`` */
export function formatDdm(value, axis) {
  const side = hemisphere(value, axis);
  const magnitude = Math.abs(value);
  let degrees = Math.floor(magnitude);
  let minutes = Math.round((magnitude - degrees) * 60 * 1e4) / 1e4;
  if (minutes >= 60) {
    minutes -= 60;
    degrees += 1;
  }
  return `${degrees}° ${minutes.toFixed(4)}' ${side}`;
}

/** ``34° 34' 4.40" N`` */
export function formatDms(value, axis) {
  const side = hemisphere(value, axis);
  const { degrees, minutes, seconds } = dmsParts(value);
  return `${degrees}° ${minutes}' ${seconds.toFixed(2)}" ${side}`;
}
