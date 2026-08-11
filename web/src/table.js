/**
 * The one place the output table's shape is defined.
 *
 * A port of kmz_points/table.py, and it must stay in step with it: the two
 * implementations are only interchangeable while they produce the same
 * columns in the same order.
 *
 * Columns are grouped into bands. A band becomes a merged title across the
 * top of its columns, optionally with a second merged caption beneath, so the
 * sheet reads as four labelled blocks rather than one undifferentiated row.
 */

import { dmsParts, formatDdm, formatDms, toMgrs, toUtm, utmLabel } from "./convert.js";

// Name leads the table: it is what a reader scans for, and a row is much
// easier to find by its name than by its longitude.
export const IDENTITY = { title: "name", caption: null, fill: "D9D9D9" };
export const SEPARATION = {
  title: "separation",
  caption: "decimal degrees",
  fill: "F8CBAD",
  captionFill: "BDD7EE",
};
export const COMBINED = { title: "Combined D,M,S", caption: null, fill: "B4C7E7" };
export const SEPARATED = { title: "separated D,M,S", caption: null, fill: "E2EFDA" };
export const DETAILS = { title: "details", caption: null, fill: "D9D9D9" };

/** header, kind, band, numberFormat, fill, fontColour */
export const COLUMNS = [
  // name -- first, because it is what a reader looks for
  { header: "Name", kind: "text", band: IDENTITY, fill: "D9D9D9" },

  { header: "longitude", kind: "number", band: SEPARATION, numberFormat: "0.000000", fill: "F4B183" },
  { header: "latitude", kind: "number", band: SEPARATION, numberFormat: "0.000000", fill: "F4B183" },
  { header: "elevation", kind: "number", band: SEPARATION, numberFormat: "0.00", fill: "F4B183" },

  { header: "#", kind: "number", band: COMBINED, numberFormat: "0", fill: "2F5597", fontColour: "FFFFFF" },
  { header: "longitude", kind: "text", band: COMBINED, fill: "2F5597", fontColour: "FFFFFF" },
  { header: "latitude", kind: "text", band: COMBINED, fill: "2F5597", fontColour: "FFFFFF" },

  // The decimal repeats beside its own breakdown, and is what carries the
  // hemisphere, since D is a magnitude.
  { header: "lat", kind: "number", band: SEPARATED, numberFormat: "0.000000", fill: "DDEBF7" },
  { header: "D", kind: "number", band: SEPARATED, numberFormat: "0", fill: "DDEBF7" },
  { header: "M", kind: "number", band: SEPARATED, numberFormat: "0", fill: "DDEBF7" },
  { header: "S", kind: "number", band: SEPARATED, numberFormat: "0.00", fill: "DDEBF7" },
  { header: "long", kind: "number", band: SEPARATED, numberFormat: "0.000000", fill: "E2EFDA" },
  { header: "D", kind: "number", band: SEPARATED, numberFormat: "0", fill: "E2EFDA" },
  { header: "M", kind: "number", band: SEPARATED, numberFormat: "0", fill: "E2EFDA" },
  { header: "S", kind: "number", band: SEPARATED, numberFormat: "0.00", fill: "E2EFDA" },

  { header: "Description", kind: "text", band: DETAILS, fill: "D9D9D9" },
  { header: "Lat (DDM)", kind: "text", band: DETAILS, fill: "D9D9D9" },
  { header: "Lon (DDM)", kind: "text", band: DETAILS, fill: "D9D9D9" },
  { header: "UTM Zone", kind: "text", band: DETAILS, fill: "D9D9D9" },
  { header: "Easting (m)", kind: "number", band: DETAILS, numberFormat: "0", fill: "D9D9D9" },
  { header: "Northing (m)", kind: "number", band: DETAILS, numberFormat: "0", fill: "D9D9D9" },
  { header: "MGRS", kind: "text", band: DETAILS, fill: "D9D9D9" },
  { header: "Source File", kind: "text", band: DETAILS, fill: "D9D9D9" },
];

export const SOURCE_FILE_INDEX = COLUMNS.findIndex((c) => c.header === "Source File");
export const NUMBER_INDEX = COLUMNS.findIndex((c) => c.header === "#");

export function headers() {
  return COLUMNS.map((column) => column.header);
}

/** Each band with the inclusive column range it covers, 0-based. */
export function bands() {
  const spans = [];
  COLUMNS.forEach((column, index) => {
    const last = spans[spans.length - 1];
    if (last && last.band === column.band) last.end = index;
    else spans.push({ band: column.band, start: index, end: index });
  });
  return spans;
}

function round6(value) {
  return Math.round(value * 1e6) / 1e6;
}

/** Build one row. Order must match COLUMNS. */
export function rowFor(index, point) {
  const utm = toUtm(point.lat, point.lon);
  const mgrs = toMgrs(point.lat, point.lon);
  const lat = dmsParts(point.lat);
  const lon = dmsParts(point.lon);

  // DD columns carry the number so they stay sortable; the six-decimal
  // presentation is a number format, not a stringified value.
  const latitude = round6(point.lat);
  const longitude = round6(point.lon);

  return [
    point.name,
    longitude,
    latitude,
    point.alt,
    index,
    formatDms(point.lon, "lon"),
    formatDms(point.lat, "lat"),
    latitude,
    lat.degrees,
    lat.minutes,
    lat.seconds,
    longitude,
    lon.degrees,
    lon.minutes,
    lon.seconds,
    point.description,
    formatDdm(point.lat, "lat"),
    formatDdm(point.lon, "lon"),
    utm ? `${utm.zone}${utm.band}` : "",
    utm ? Math.round(utm.easting) : null,
    utm ? Math.round(utm.northing) : null,
    mgrs || "",
    point.sourceFile,
  ];
}

/** Convert points into rows, numbered from 1 across the whole batch. */
export function buildTableRows(points) {
  return points.map((point, index) => rowFor(index + 1, point));
}

export { utmLabel };
