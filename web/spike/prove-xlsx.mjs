// Spike: can a browser-shaped module produce the workbook we actually ship?
// Exercises every feature that made this risky -- merged band titles, per
// column fills, number formats, a frozen pane, a full-width banner row, and
// a second sheet.
import { writeFileSync } from "node:fs";
import { buildWorkbook, Styles, columnLetter } from "../src/xlsx.js";

const styles = new Styles();
const bandTitle = styles.style({ bold: true, size: 12, fill: "F8CBAD", centred: true });
const caption   = styles.style({ fill: "BDD7EE", centred: true });
const header    = styles.style({ bold: true, fill: "F4B183", centred: true });
const headerDark= styles.style({ bold: true, colour: "FFFFFF", fill: "2F5597", centred: true });
const banner    = styles.style({ bold: true, colour: "FFFFFF", fill: "A6A6A6", centred: true });
const decimal   = styles.style({ numberFormat: "0.000000" });
const whole     = styles.style({ numberFormat: "0" });

const width = 6;
const blank = () => Array.from({ length: width }, () => null);

const rows = [];
rows[0] = blank(); rows[0][0] = { value: "separation", style: bandTitle };
rows[0][3] = { value: "Combined D,M,S", style: headerDark };
rows[1] = blank(); rows[1][0] = { value: "decimal degrees", style: caption };
rows[2] = [
  { value: "longitude", style: header }, { value: "latitude", style: header },
  { value: "elevation", style: header }, { value: "#", style: headerDark },
  { value: "longitude", style: headerDark }, { value: "latitude", style: headerDark },
];
// A banner: text in the first cell, every other cell styled so the fill runs
// the full width even though the merge only needs the first.
rows[3] = blank().map(() => ({ value: null, style: banner }));
rows[3][0] = { value: "simple.kml", style: banner };
rows[4] = [
  { value: 38.123456, style: decimal }, { value: 34.56789, style: decimal },
  { value: 120.5, style: decimal }, { value: 1, style: whole },
  { value: "38° 7' 24.44\" E" }, { value: "34° 34' 4.40\" N" },
];

const points = {
  name: "Points",
  rows,
  merges: ["A1:C1", "A2:C2", `D1:${columnLetter(width - 1)}2`, `A4:${columnLetter(width - 1)}4`],
  columnWidths: [14, 14, 12, 6, 20, 20],
  freezeRow: 3,
};

const areas = {
  name: "Areas",
  rows: [
    [{ value: "An area — 956,863 m² · 95.686 ha · 0.956863 km² · 4 corners", style: banner }],
    [{ value: 38.2, style: decimal }, { value: 34.6, style: decimal }],
  ],
  merges: ["A1:F1"],
  freezeRow: 0,
};

writeFileSync(process.argv[2], buildWorkbook([points, areas], styles));
console.log("wrote", process.argv[2]);
