/**
 * Turning a batch into the workbook.
 *
 * A port of kmz_points/excel.py's layout: three header rows, data from row 4,
 * a grey banner naming each source file, an Areas sheet where each area is a
 * banner and its corners, and an Issues sheet when anything failed.
 */

import { buildWorkbook, columnLetter, Styles } from "./xlsx.js";
import { bands, buildTableRows, COLUMNS, headers, SOURCE_FILE_INDEX } from "./table.js";

export const BAND_TITLE_ROW = 1;
export const BAND_CAPTION_ROW = 2;
export const HEADER_ROW = 3;
export const FIRST_DATA_ROW = 4;

const BANNER_FILL = "A6A6A6";
// Holes sit inside an area, so their banner is lighter than the area's own.
const HOLE_BANNER_FILL = "D9D9D9";

const MIN_WIDTH = 8;
const MAX_WIDTH = 60;
const WIDTH_PADDING = 2;

// openpyxl turns a leading "=" into a live formula, and a spreadsheet reading
// this file will do the same. The other leading symbols are left alone: they
// matter when a person types into a cell or imports a CSV, not for a string
// written into a sheet.
function defuse(value) {
  if (typeof value !== "string") return value;
  return value.startsWith("=") ? `'${value}` : value;
}

function cell(value, style) {
  if (value === null || value === undefined) return style ? { value: null, style } : null;
  return { value: defuse(value), style };
}

class Look {
  constructor() {
    this.styles = new Styles();
    this.bandTitle = new Map();
    this.bandCaption = new Map();
    this.header = [];
    this.number = [];

    for (const column of COLUMNS) {
      this.header.push(
        this.styles.style({
          bold: true,
          fill: column.fill,
          colour: column.fontColour || null,
          centred: true,
        }),
      );
      this.number.push(
        column.numberFormat
          ? this.styles.style({ numberFormat: column.numberFormat })
          : 0,
      );
    }

    for (const { band } of bands()) {
      this.bandTitle.set(
        band,
        this.styles.style({ bold: true, size: 12, fill: band.fill, centred: true }),
      );
      this.bandCaption.set(
        band,
        this.styles.style({ fill: band.captionFill || band.fill, centred: true }),
      );
    }

    this.banner = this.styles.style({
      bold: true,
      colour: "FFFFFF",
      fill: BANNER_FILL,
      centred: true,
    });
    this.holeBanner = this.styles.style({
      bold: true,
      fill: HOLE_BANNER_FILL,
      centred: true,
    });
    this.plain = this.styles.style({});
  }
}

function headerRows(look) {
  const width = COLUMNS.length;
  const title = Array.from({ length: width }, () => null);
  const caption = Array.from({ length: width }, () => null);
  const merges = [];

  for (const { band, start, end } of bands()) {
    const first = columnLetter(start);
    const last = columnLetter(end);
    title[start] = cell(band.title, look.bandTitle.get(band));

    if (band.caption) {
      caption[start] = cell(band.caption, look.bandCaption.get(band));
      merges.push(`${first}${BAND_TITLE_ROW}:${last}${BAND_TITLE_ROW}`);
      merges.push(`${first}${BAND_CAPTION_ROW}:${last}${BAND_CAPTION_ROW}`);
    } else {
      // No caption, so the title claims both rows rather than leaving a
      // blank band beneath it.
      caption[start] = cell(null, look.bandTitle.get(band));
      merges.push(`${first}${BAND_TITLE_ROW}:${last}${BAND_CAPTION_ROW}`);
    }
  }

  const names = COLUMNS.map((column, index) => cell(column.header, look.header[index]));
  return { rows: [title, caption, names], merges };
}

function bannerRow(text, style) {
  // The text sits in the first cell; the rest are emitted styled so the fill
  // covers the row even where a reader ignores the merge.
  const row = Array.from({ length: COLUMNS.length }, () => cell(null, style));
  row[0] = cell(text, style);
  return row;
}

function dataRow(values, look) {
  return values.map((value, index) => cell(value, look.number[index] || look.plain));
}

function columnWidths(allRows) {
  return COLUMNS.map((column, index) => {
    let longest = column.header.length;
    for (const values of allRows) {
      const value = values[index];
      if (value === null || value === undefined) continue;
      longest = Math.max(longest, String(value).length);
    }
    return Math.min(Math.max(longest + WIDTH_PADDING, MIN_WIDTH), MAX_WIDTH);
  });
}

function pointsSheet(rows, look) {
  const { rows: header, merges } = headerRows(look);
  const body = [];
  let currentFile = null;
  let rowNumber = FIRST_DATA_ROW;

  for (const values of rows) {
    const source = values[SOURCE_FILE_INDEX];
    if (source !== currentFile) {
      currentFile = source;
      body.push(bannerRow(source, look.banner));
      merges.push(`A${rowNumber}:${columnLetter(COLUMNS.length - 1)}${rowNumber}`);
      rowNumber += 1;
    }
    body.push(dataRow(values, look));
    rowNumber += 1;
  }

  return {
    name: "Points",
    rows: [...header, ...body],
    merges,
    columnWidths: columnWidths(rows),
    freezeRow: HEADER_ROW,
  };
}

function areaBannerText(measured) {
  const { area, measurement } = measured;
  const name = area.name || "<unnamed>";
  const corners = `${cornerCount(area)} corners`;

  if (measurement.squareMetres === null) {
    return `${name} — area not measured: ${measurement.problem} · ${corners}`;
  }

  const round = (value, places) =>
    value.toLocaleString("en-US", {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    });

  return (
    `${name} — ${round(measurement.squareMetres, 0)} m² · ` +
    `${round(measurement.hectares, 3)} ha · ` +
    `${round(measurement.squareKilometres, 6)} km² · ${corners}`
  );
}

/** Corners a reader would count: KML repeats the first coordinate last. */
export function cornerCount(area) {
  const ring = area.outer;
  if (
    ring.length > 1 &&
    ring[0].lat === ring[ring.length - 1].lat &&
    ring[0].lon === ring[ring.length - 1].lon
  ) {
    return ring.length - 1;
  }
  return ring.length;
}

function areasSheet(measuredAreas, look) {
  const { rows: header, merges } = headerRows(look);
  const body = [];
  const allRows = [];
  let rowNumber = FIRST_DATA_ROW;

  const wide = `${columnLetter(COLUMNS.length - 1)}`;

  for (const measured of measuredAreas) {
    body.push(bannerRow(areaBannerText(measured), look.banner));
    merges.push(`A${rowNumber}:${wide}${rowNumber}`);
    rowNumber += 1;

    const rings = [[null, measured.area.outer]];
    (measured.area.holes || []).forEach((hole, position) => {
      rings.push([`hole ${position + 1} — ${hole.length} corners`, hole]);
    });

    for (const [label, corners] of rings) {
      if (label !== null) {
        body.push(bannerRow(label, look.holeBanner));
        merges.push(`A${rowNumber}:${wide}${rowNumber}`);
        rowNumber += 1;
      }
      // Numbering restarts within each ring, which is what makes a corner
      // list readable.
      for (const values of buildTableRows(corners)) {
        allRows.push(values);
        body.push(dataRow(values, look));
        rowNumber += 1;
      }
    }
  }

  return {
    name: "Areas",
    rows: [...header, ...body],
    merges,
    columnWidths: columnWidths(allRows),
    freezeRow: HEADER_ROW,
  };
}

function issuesSheet(issues, look) {
  const heading = look.styles.style({ bold: true });
  return {
    name: "Issues",
    rows: [[cell("Issue", heading)], ...issues.map((line) => [cell(line, 0)])],
    merges: [],
    columnWidths: [MAX_WIDTH],
    freezeRow: 0,
  };
}

/**
 * Build the workbook bytes for a batch.
 *
 * Sheet order is Points, Areas, Issues -- the data first, the complaints last,
 * so opening the file lands on something useful.
 */
export function buildBatchWorkbook({ rows, areas = [], issues = [] }) {
  const look = new Look();
  const sheets = [pointsSheet(rows, look)];
  if (areas.length) sheets.push(areasSheet(areas, look));
  if (issues.length) sheets.push(issuesSheet(issues, look));
  return buildWorkbook(sheets, look.styles);
}

/** ``points_YYYYMMDD_HHMMSS.xlsx`` for the given moment (default: now). */
export function outputFilename(when = new Date()) {
  const pad = (value, width = 2) => String(value).padStart(width, "0");
  return (
    `points_${when.getFullYear()}${pad(when.getMonth() + 1)}${pad(when.getDate())}` +
    `_${pad(when.getHours())}${pad(when.getMinutes())}${pad(when.getSeconds())}.xlsx`
  );
}

export { headers };
