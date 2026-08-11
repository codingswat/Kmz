/**
 * The browser side of the workbook comparison.
 *
 * Reduces the sheets buildBatchSheets produces to exactly the shape
 * kmz_points/workbook_facts.py reports for a workbook openpyxl wrote, so the
 * two can be compared without either side having to agree on bytes -- which
 * they never will, an openpyxl file and a hand-written one differing in zip
 * ordering, style encoding and whitespace no reader ever sees.
 *
 * Fonts, fills, colours and alignment are deliberately not included; see the
 * module docstring of workbook_facts.py for why.
 *
 * Lives in test/ rather than src/ because it is only ever used by the test
 * suite, and web/src/ is bundled into the single-file build.
 */

// Where xlsx.js starts its own number formats: ids below 164 are reserved by
// the format for built-ins, and 0 means the cell carries no format at all.
const FIRST_CUSTOM_FORMAT = 164;

const CELL_KEYS = ["row", "col", "value", "type", "numberFormat"];

function round(value, places) {
  const number = Number(value.toFixed(places));
  // -0 reads as 0 but is not equal to it under a strict deep-equal.
  return number === 0 ? 0 : number;
}

function numberFormatOf(styles, style) {
  const id = styles.cellFormats[style || 0].numberFormat;
  return id ? styles.numberFormats[id - FIRST_CUSTOM_FORMAT] : "General";
}

/** Value and type as xlsx.js would write them: finite numbers, else text. */
function typedValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return { value: round(value, 6), type: "n" };
  }
  return { value, type: "s" };
}

function sheetFacts(sheet, styles) {
  const cells = [];
  sheet.rows.forEach((row, rowIndex) => {
    row.forEach((cell, columnIndex) => {
      // A cell with nothing in it is emitted only so a banner's fill covers
      // the row, and fills are not compared -- so, like the Python side, it
      // says nothing about what the sheet contains.
      if (!cell || cell.value === null || cell.value === undefined || cell.value === "") {
        return;
      }
      cells.push({
        row: rowIndex + 1,
        col: columnIndex + 1,
        ...typedValue(cell.value),
        numberFormat: numberFormatOf(styles, cell.style),
      });
    });
  });

  return {
    name: sheet.name,
    freezeRow: sheet.freezeRow,
    columnWidths: sheet.columnWidths.map((width) => round(width, 2)),
    merges: [...sheet.merges].sort(),
    cells,
  };
}

/** The facts of a batch's sheets, as workbook_facts.py would state them. */
export function workbookFacts({ sheets, look }) {
  return { sheets: sheets.map((sheet) => sheetFacts(sheet, look.styles)) };
}

function show(value) {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

function describeCell(cell) {
  return cell ? `${show(cell.value)} (${cell.type}, ${cell.numberFormat})` : "nothing";
}

function listDifference(actual, expected, describe) {
  const shared = Math.min(actual.length, expected.length);
  for (let index = 0; index < shared; index += 1) {
    if (actual[index] !== expected[index]) {
      return describe(index, actual[index], expected[index]);
    }
  }
  if (actual.length === expected.length) return null;
  const index = shared;
  return describe(index, actual[index], expected[index]);
}

function cellsDifference(actual, expected) {
  const shared = Math.min(actual.length, expected.length);
  for (let index = 0; index < shared; index += 1) {
    const mine = actual[index];
    const theirs = expected[index];
    if (CELL_KEYS.every((key) => mine[key] === theirs[key])) continue;
    // Row and column are part of the comparison, so a cell one side wrote and
    // the other did not shows up here as a shift rather than as a wrong value.
    const at =
      mine.row === theirs.row && mine.col === theirs.col
        ? `row ${mine.row}, column ${mine.col}`
        : `row ${mine.row}, column ${mine.col} where Python has row ` +
          `${theirs.row}, column ${theirs.col}`;
    return `${at}: browser has ${describeCell(mine)}, Python has ${describeCell(theirs)}`;
  }

  if (actual.length === expected.length) return null;
  const extra = actual[shared] || expected[shared];
  return (
    `the browser wrote ${actual.length} cells and Python ${expected.length}; ` +
    `they first part ways at row ${extra.row}, column ${extra.col}: ` +
    `browser has ${describeCell(actual[shared])}, Python has ${describeCell(expected[shared])}`
  );
}

/**
 * Where two sets of facts first disagree, in one line, or null if they agree.
 *
 * A deep-equal on two workbooks of this size prints thousands of lines and
 * says nothing about which cell went wrong, which is the only thing anyone
 * reading the failure wants to know.
 */
export function firstDifference(actual, expected) {
  const names = (facts) => facts.sheets.map((sheet) => sheet.name).join(", ");
  if (actual.sheets.length !== expected.sheets.length) {
    return `the browser wrote sheets [${names(actual)}], Python [${names(expected)}]`;
  }

  for (const [index, mine] of actual.sheets.entries()) {
    const theirs = expected.sheets[index];
    const where = `sheet ${index + 1} (${theirs.name})`;

    if (mine.name !== theirs.name) {
      return `${where}: the browser calls it ${show(mine.name)}`;
    }
    if (mine.freezeRow !== theirs.freezeRow) {
      return `${where}: browser freezes ${mine.freezeRow} rows, Python ${theirs.freezeRow}`;
    }

    const widths = listDifference(
      mine.columnWidths,
      theirs.columnWidths,
      (at, ours, python) =>
        `${where}: column ${at + 1} is ${show(ours)} wide in the browser and ` +
        `${show(python)} in Python`,
    );
    if (widths) return widths;

    const merges = listDifference(
      mine.merges,
      theirs.merges,
      (at, ours, python) =>
        `${where}: merge ${at + 1} of ${theirs.merges.length} is ${show(ours)} in the ` +
        `browser and ${show(python)} in Python`,
    );
    if (merges) return merges;

    const cells = cellsDifference(mine.cells, theirs.cells);
    if (cells) return `${where}, ${cells}`;
  }

  return null;
}
