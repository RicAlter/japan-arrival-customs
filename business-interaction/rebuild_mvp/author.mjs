import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile, FileBlob } from '@oai/artifact-tool';

if (process.argv[2] === '--verify') {
  const [file, mainName, weightName, outdir] = process.argv.slice(3);
  const read = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  for (const [name, range, suffix] of [[mainName,'A1:M5','main'], [mainName,'N1:X5','detail'], [weightName,'A1:J8','weight']]) {
    const blob = await read.render({sheetName:name,range,scale:1.2,format:'png'});
    await fs.writeFile(`${outdir}/${suffix}.png`,new Uint8Array(await blob.arrayBuffer()));
  }
  console.log((await read.inspect({kind:'table',range:`'${mainName}'!K1:M4`,tableMaxRows:4,tableMaxCols:3,maxChars:1200})).ndjson);
  process.exit(0);
}

const p = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const wb = Workbook.create();
const sheet = wb.worksheets.add(p.sheet);
const weight = wb.worksheets.add(p.weight_sheet);
sheet.showGridLines = false;
weight.showGridLines = false;
const last = p.matrix.length;
sheet.getRange(`A1:X${last}`).values = p.matrix;
const all = sheet.getRange(`A1:X${last}`);
all.format.font.name = 'Arial';
all.format.font.size = 10;
all.format.verticalAlignment = 'center';
all.format.wrapText = true;
all.format.rowHeight = 48;
sheet.getRange('A1:X1').format.rowHeight = 42;
sheet.getRange('A1:X1').format.font.bold = true;
sheet.getRange('A1:X1').format.horizontalAlignment = 'center';
sheet.getRange('A1:X1').format.fill = '#F2F2F2';
sheet.getRange('A1:X1').format.borders = {preset: 'all', style: 'thin', color: '#B7B7B7'};
for (const group of p.cols) {
  for (const col of group.children || []) {
    const a = col.attributes;
    sheet.getRangeByIndexes(0, Number(a.min)-1, last, Number(a.max)-Number(a.min)+1).format.columnWidth = Number(a.width);
  }
}
// Numeric source JANs remain numeric but must display all digits, never E+12.
sheet.getRange(`C2:C${last}`).setNumberFormat('0');
for (const col of ['D','Q']) sheet.getRange(`${col}2:${col}${last}`).setNumberFormat('@');
for (const col of ['K','L','M']) sheet.getRange(`${col}2:${col}${last}`).setNumberFormat('#,##0.##########');
sheet.freezePanes.freezeRows(1);
const done = new Set();
for (const issue of p.issues) {
  const col = p.value_columns[issue.field];
  if (!col || issue.row < 2) continue;
  const cell = `${col}${issue.row}`;
  if (done.has(cell)) continue;
  done.add(cell);
  sheet.getRange(cell).format.fill = /CONFLICT|AMBIGU/.test(issue.code || '') ? '#FCE4D6' : '#FFF2CC';
}
wb.recalculate();
console.log((await wb.inspect({kind: 'table', range: `'${p.sheet}'!A1:D4`, tableMaxRows: 4, tableMaxCols: 4, maxChars: 1000})).ndjson);
const preview = await wb.render({sheetName: p.sheet, range: 'A1:M5', scale: 1.2, format:'png'});
await fs.writeFile(p.preview, new Uint8Array(await preview.arrayBuffer()));
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(p.output);
