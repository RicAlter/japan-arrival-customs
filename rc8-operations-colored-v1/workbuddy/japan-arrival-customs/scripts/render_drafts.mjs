// Explicit rendering adapter. All business calculations and projections belong to Python.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const [input, outputDir, moduleRoot, ...flags] = process.argv.slice(2);
if (!input || !outputDir || !moduleRoot) throw new Error('payload, output directory and module root required');
const loader = createRequire(path.join(path.dirname(path.resolve(moduleRoot)), '__arrival_loader.cjs'));
const {Workbook, SpreadsheetFile} = await import(pathToFileURL(loader.resolve('@oai/artifact-tool')).href);
const payload = JSON.parse(await fs.readFile(input,'utf8'));
if (payload.schema !== 'japan-arrival/draft-pair-1' || payload.formal_output !== false) throw new Error('draft-only payload required');
const literal = value => typeof value === 'string' && /^[=+@-]/.test(value) ? "'"+value : value;
const widths = {
  customs: [7,17,20,32,14,28,16,14,25,20,12,57],
  internal: [7,17,20,65,25,20,20,17,15,15,15,17,15,20,12,38,20,22,25,57,55],
  weights: [25,18,22,54],
};
function makeSheet(wb, name, view, kind, title) {
  const sheet = wb.worksheets.add(name);
  const count = view.headers.length, lastRow = 6+view.rows.length;
  const all = sheet.getRangeByIndexes(0,0,Math.max(lastRow,7),count);
  all.format.font = {name:'Arial',size:10,color:'#17212B'};
  all.format.verticalAlignment = 'center';
  sheet.showGridLines = false;
  sheet.getRange('A2').values = [[title]];
  sheet.getRangeByIndexes(1,0,1,count).format.font = {name:'Arial',size:14,bold:true};
  sheet.getRange('A3').values = [[payload.warning]];
  sheet.getRangeByIndexes(2,0,1,count).format.font = {name:'Arial',size:10,color:'#9C2F20'};
  sheet.getRange('A4').values = [['明细版本SHA256：'+payload.basis_hash]];
  sheet.getRange('A5').values = [[`商品 ${payload.summary.rows} 行；物理箱数 ${payload.summary.cartons ?? '待确认'}；总重 ${payload.summary.weight_kg ?? '待确认'} KG`]];
  sheet.getRangeByIndexes(5,0,1,count).values = [view.headers];
  sheet.getRangeByIndexes(5,0,1,count).format = {fill:'#233C56',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',rowHeight:36};
  if (view.rows.length) {
    const body = sheet.getRangeByIndexes(6,0,view.rows.length,count);
    body.values = view.rows.map(row=>row.map(literal));
    body.format.wrapText = true;
    body.format.rowHeight = 38;
    body.format.numberFormat = view.rows.map(row=>row.map(value=>typeof value==='number' ? (Number.isInteger(value)?'#,##0':'#,##0.0##############') : (typeof value==='string' && /^\d+$/.test(value) ? '0'.repeat(value.length) : '@')));
    if (kind!=='weights') sheet.getRangeByIndexes(6,2,view.rows.length,1).format.horizontalAlignment='left';
    for (let ri=0;ri<view.rows.length;ri++) {
      let lines = 1;
      view.rows[ri].forEach((v,ci)=>{
        if (typeof v !== 'string') return;
        const cellLines=v.split('\n').reduce((total,line)=>{
          const units=[...line].reduce((n,c)=>n+(c.charCodeAt(0)>255 ? 2 : 1),0);
          return total+Math.max(1,Math.ceil(units/Math.max(8,widths[kind][ci]-2)));
        },0);
        lines = Math.max(lines,cellLines);
      });
      if (lines>2) sheet.getRangeByIndexes(ri+6,0,1,count).format.rowHeight = lines*14+8;
    }
    body.conditionalFormats.add('containsText',{text:'待确认',format:{fill:'#FFF1DB',font:{color:'#8A4B12'}}});
  }
  widths[kind].forEach((width,col)=>sheet.getRangeByIndexes(0,col,lastRow,col===count?0:1).format.columnWidth=width);
  sheet.freezePanes.freezeRows(6);
  if (kind !== 'weights') sheet.freezePanes.freezeColumns(3);
  return sheet;
}
const checks=[];
for (const [kind, filename, title] of [
  ['customs','海关报关单_受控测试草稿.xlsx','海关报关单（受控测试草稿）'],
  ['internal','内部到货单_受控测试草稿.xlsx','内部到货单（受控测试草稿）'],
]) {
  const wb=Workbook.create();
  makeSheet(wb,'商品明细',payload[kind],kind,title);
  makeSheet(wb,'箱重核对',payload.weights,'weights','箱数与总重量核对（受控测试草稿）');
  wb.recalculate();
  const sample=await wb.inspect({kind:'table',range:'商品明细!A6:L9',include:'values,formulas',tableMaxRows:4,tableMaxCols:12,maxChars:3500});
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1500});
  checks.push({kind,sample:sample.ndjson,errors:errors.ndjson});
  if (flags.includes('--previews')) {
    for (const sheetName of ['商品明细','箱重核对']) {
      const range=sheetName==='商品明细' ? (kind==='internal' ? 'A1:U11' : 'A1:L11') : 'A1:D12';
      const blob=await wb.render({sheetName,range,scale:1,format:'png'});
      await fs.writeFile(path.join(outputDir,`${kind}-${sheetName}.png`),new Uint8Array(await blob.arrayBuffer()));
    }
  }
  const file=await SpreadsheetFile.exportXlsx(wb);
  await file.save(path.join(outputDir,filename));
}
await fs.writeFile(path.join(outputDir,'renderer_checks.json'),JSON.stringify(checks,null,2)+'\n');
console.log(JSON.stringify({formal_output:false,files:2,basis_hash:payload.basis_hash}));
