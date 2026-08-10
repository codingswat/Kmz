/**
 * Writing an xlsx, by hand.
 *
 * This is the part of a browser port with no obvious library answer: the
 * workbook needs merged header bands, per-column fills, number formats and
 * more than one sheet, and the widely used community spreadsheet libraries
 * either drop styling or bring a large dependency to get it back. An xlsx is
 * a zip of XML, so writing the XML directly costs less than it sounds and
 * leaves nothing about the layout out of reach.
 *
 * Strings are written inline rather than through a shared-strings table.
 * That is slightly larger on disk and considerably simpler to be correct
 * about.
 *
 * Runs unchanged in a browser and in Node.
 */

import { zip } from "./zip.js";

const SHEET_MIME =
  "application/vnd.openxmlformats-officedocument.spreadsheetml";

/** XML-escape a text node or attribute value. */
export function escapeXml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** 0-based column index to a spreadsheet letter: 0 -> A, 26 -> AA. */
export function columnLetter(index) {
  let letter = "";
  let remaining = index + 1;
  while (remaining > 0) {
    const part = (remaining - 1) % 26;
    letter = String.fromCharCode(65 + part) + letter;
    remaining = Math.floor((remaining - part) / 26);
  }
  return letter;
}

/**
 * Collects the fonts, fills and number formats a workbook uses.
 *
 * Every distinct combination becomes one entry in styles.xml, and a cell
 * carries the index. Deduplicating here rather than at the call site keeps
 * the sheet-building code talking about appearance instead of indices.
 */
export class Styles {
  constructor() {
    this.fonts = [{ bold: false, colour: null, size: null }];
    this.fills = [null, null]; // slots 0 and 1 are reserved by the format
    this.numberFormats = [];
    this.cellFormats = [{ font: 0, fill: 0, numberFormat: 0, alignment: null }];
  }

  _index(list, value, compare) {
    const found = list.findIndex((existing) => compare(existing, value));
    if (found !== -1) return found;
    list.push(value);
    return list.length - 1;
  }

  /** Register a look and get the id a cell should carry. */
  style({ bold = false, colour = null, size = null, fill = null, numberFormat = null, centred = false } = {}) {
    const font = this._index(
      this.fonts,
      { bold, colour, size },
      (a, b) => a.bold === b.bold && a.colour === b.colour && a.size === b.size,
    );

    let fillId = 0;
    if (fill) {
      const at = this.fills.indexOf(fill);
      fillId = at === -1 ? this.fills.push(fill) - 1 : at;
    }

    let numberFormatId = 0;
    if (numberFormat) {
      const at = this.numberFormats.indexOf(numberFormat);
      const position = at === -1 ? this.numberFormats.push(numberFormat) - 1 : at;
      numberFormatId = 164 + position; // ids below 164 are reserved built-ins
    }

    return this._index(
      this.cellFormats,
      { font, fill: fillId, numberFormat: numberFormatId, alignment: centred ? "center" : null },
      (a, b) =>
        a.font === b.font &&
        a.fill === b.fill &&
        a.numberFormat === b.numberFormat &&
        a.alignment === b.alignment,
    );
  }

  toXml() {
    const fonts = this.fonts
      .map(
        (font) =>
          "<font>" +
          (font.bold ? "<b/>" : "") +
          `<sz val="${font.size || 11}"/>` +
          (font.colour ? `<color rgb="FF${font.colour}"/>` : "") +
          '<name val="Calibri"/></font>',
      )
      .join("");

    const fills = this.fills
      .map((fill, index) => {
        if (index === 0) return '<fill><patternFill patternType="none"/></fill>';
        if (index === 1) return '<fill><patternFill patternType="gray125"/></fill>';
        return `<fill><patternFill patternType="solid"><fgColor rgb="FF${fill}"/><bgColor indexed="64"/></patternFill></fill>`;
      })
      .join("");

    const numberFormats = this.numberFormats
      .map(
        (format, index) =>
          `<numFmt numFmtId="${164 + index}" formatCode="${escapeXml(format)}"/>`,
      )
      .join("");

    const cellFormats = this.cellFormats
      .map((entry) => {
        const alignment = entry.alignment
          ? `<alignment horizontal="${entry.alignment}" vertical="center"/>`
          : "";
        return (
          `<xf numFmtId="${entry.numberFormat}" fontId="${entry.font}" fillId="${entry.fill}" borderId="0" xfId="0"` +
          ` applyFont="1" applyFill="1"${entry.numberFormat ? ' applyNumberFormat="1"' : ""}` +
          `${alignment ? ' applyAlignment="1"' : ""}>${alignment}</xf>`
        );
      })
      .join("");

    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      `<numFmts count="${this.numberFormats.length}">${numberFormats}</numFmts>` +
      `<fonts count="${this.fonts.length}">${fonts}</fonts>` +
      `<fills count="${this.fills.length}">${fills}</fills>` +
      '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>' +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      `<cellXfs count="${this.cellFormats.length}">${cellFormats}</cellXfs>` +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
      "</styleSheet>"
    );
  }
}

function cellXml(reference, cell) {
  if (cell === null || cell === undefined) return "";
  const { value, style } = cell;
  if (value === null || value === undefined || value === "") {
    // Still emitted when styled, so a banner's fill covers the whole row
    // rather than stopping at its text.
    return style ? `<c r="${reference}" s="${style}"/>` : "";
  }

  const styleAttribute = style ? ` s="${style}"` : "";
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${reference}"${styleAttribute}><v>${value}</v></c>`;
  }
  return (
    `<c r="${reference}"${styleAttribute} t="inlineStr">` +
    `<is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`
  );
}

function sheetXml({ rows, merges = [], columnWidths = [], freezeRow = 0 }) {
  const cols = columnWidths.length
    ? "<cols>" +
      columnWidths
        .map(
          (width, index) =>
            `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`,
        )
        .join("") +
      "</cols>"
    : "";

  const pane = freezeRow
    ? `<sheetView workbookViewId="0"><pane ySplit="${freezeRow}" topLeftCell="A${freezeRow + 1}" activePane="bottomLeft" state="frozen"/></sheetView>`
    : '<sheetView workbookViewId="0"/>';

  const body = rows
    .map((cells, rowIndex) => {
      const number = rowIndex + 1;
      const rendered = cells
        .map((cell, columnIndex) => cellXml(columnLetter(columnIndex) + number, cell))
        .join("");
      return rendered ? `<row r="${number}">${rendered}</row>` : "";
    })
    .join("");

  const mergeXml = merges.length
    ? `<mergeCells count="${merges.length}">` +
      merges.map((range) => `<mergeCell ref="${range}"/>`).join("") +
      "</mergeCells>"
    : "";

  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<sheetViews>${pane}</sheetViews>` +
    cols +
    `<sheetData>${body}</sheetData>` +
    mergeXml +
    "</worksheet>"
  );
}

/**
 * Build an xlsx from sheets.
 *
 * Each sheet is `{name, rows, merges, columnWidths, freezeRow}`; each row is
 * an array of `{value, style}` or null. Returns the file as bytes, which a
 * browser can hand to a download and Node can write to disk.
 */
export function buildWorkbook(sheets, styles) {
  const files = {
    "[Content_Types].xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      `<Override PartName="/xl/workbook.xml" ContentType="${SHEET_MIME}.sheet.main+xml"/>` +
      sheets
        .map(
          (_sheet, index) =>
            `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="${SHEET_MIME}.worksheet+xml"/>`,
        )
        .join("") +
      `<Override PartName="/xl/styles.xml" ContentType="${SHEET_MIME}.styles+xml"/>` +
      "</Types>",

    "_rels/.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      "</Relationships>",

    "xl/workbook.xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
      sheets
        .map(
          (sheet, index) =>
            `<sheet name="${escapeXml(sheet.name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`,
        )
        .join("") +
      "</sheets></workbook>",

    "xl/_rels/workbook.xml.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      sheets
        .map(
          (_sheet, index) =>
            `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`,
        )
        .join("") +
      `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
      "</Relationships>",

    "xl/styles.xml": styles.toXml(),
  };

  sheets.forEach((sheet, index) => {
    files[`xl/worksheets/sheet${index + 1}.xml`] = sheetXml(sheet);
  });

  return zip(files);
}
