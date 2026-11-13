import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const plan=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const w=await SpreadsheetFile.importXlsx(await FileBlob.load(plan.input));const s=w.worksheets.getItem(plan.sheet);
for(const [col,title] of Object.entries(plan.headers)){
 const ref=col==='T'?'M1':col==='U'?'N1':col==='Q'?'G1':col==='R'||col==='S'?'F1':col+'1';
 s.getRange(col+'1').copyFrom(s.getRange(ref),'all');s.getRange(col+'1').values=[[title]];s.getRange(col+'1').format.wrapText=true;
}
for(const record of plan.records){const c=s.getRange(record.cell);c.values=[[record.kind==='number'?Number(record.value):record.value]];c.format.fill=record.color==='red'?'#F4CCCC':'#FFF2CC';}
s.getRange('G2:G1276').format.numberFormat='#,##0.########';s.getRange('Q2:Q1276').format.numberFormat='#,##0.########';
s.getRange('E2:F1276').format.wrapText=true;s.getRange('R2:S1276').format.wrapText=true;
for(const [col,width] of [['Q',20],['R',28],['S',28],['T',16],['U',28]])s.getRange(col+':'+col).format.columnWidth=width;
s.getRange('E2:F1276').format.autofitRows();
w.recalculate();
console.log((await w.inspect({kind:'region',sheetId:plan.sheet,range:'E2:H6',maxChars:1400,tableMaxRows:5,tableMaxCols:4})).ndjson);
for(const [name,range] of [['basic-fields','E2:H6'],['quantity-units','O1:U6'],['manual-material','M507:U511']]){
 const im=await w.render({sheetName:plan.sheet,range,scale:1.1,format:'png'});
 await fs.writeFile(new URL(name+'.png','file:///'+plan.artifact_output.replaceAll('\\','/')),new Uint8Array(await im.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(w)).save(plan.artifact_output);
