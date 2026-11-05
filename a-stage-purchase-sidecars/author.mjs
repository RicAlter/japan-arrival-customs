import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const main=await SpreadsheetFile.importXlsx(await FileBlob.load(p.input));const s=main.worksheets.getItem(p.sheet);
s.getRange('Q1:R1276').copyFrom(s.getRange('T1:U1276'),'all');s.getRange('S1:U1316').clear();
s.getRange('Q:Q').format.columnWidth=16;s.getRange('R:R').format.columnWidth=28;
await (await SpreadsheetFile.exportXlsx(main)).save(p.main_authored);
const preview=await main.render({sheetName:p.sheet,range:'M1:R6',scale:1.1,format:'png'});
await fs.writeFile(path.join(p.output,'technical/main-preview.png'),new Uint8Array(await preview.arrayBuffer()));
let counter=0;
async function table(w,name,rows,note){
 const x=w.worksheets.add(name);const end=rows.length+4;
 x.getRange('A1:J1').merge();x.getRange('A1').values=[[name]];
 x.getRange('A2:J2').merge();x.getRange('A2').values=[[note]];
 x.getRange('A1:J1').format={fill:'#24415C',font:{bold:true,size:15,color:'#FFFFFF'},rowHeight:32};
 x.getRange('A2:J2').format={fill:'#FFF2CC',font:{size:11,color:'#4D4335'},wrapText:true,rowHeight:34};
 x.getRange('A4:O4').values=[p.query.headers];
 x.getRange(`A4:O${Math.max(end,5)}`).format={font:{name:'Arial',size:10},verticalAlignment:'center',rowHeight:42};
 x.getRange('A4:O4').format={fill:'#DCE6F1',font:{bold:true},wrapText:true,rowHeight:34};
 if(rows.length){
  const typed=rows.map(r=>r.map((v,i)=>[5,6,7].includes(i)&&v!==null?Number(v):v));
  x.getRange(`A5:O${end}`).values=typed;
  x.getRange(`F5:I${end}`).setNumberFormat('General');
  // Values remain literal strings; numeric display mask avoids scientific JANs
  // in renderers that coerce digit-only text. No identifiers are converted.
  x.getRange(`B5:B${end}`).setNumberFormat('0');
  x.getRange(`I5:I${end}`).formulas=rows.map((r,i)=>[`=IF(OR(G${i+5}="",H${i+5}=""),"",H${i+5}-G${i+5})`]);
  const t=x.tables.add(`A4:O${end}`,true,'Purchase'+(++counter));t.style='TableStyleMedium2';
 }
 x.getRange('A4:O4').format.fill='#24415C';x.getRange('A4:O4').format.font.color='#FFFFFF';
 const widths=[10,19,27,52,28,17,16,16,23,29,17,17,42,43,43];
 for(let i=0;i<15;i++)x.getRange(String.fromCharCode(65+i)+':'+String.fromCharCode(65+i)).format.columnWidth=widths[i];
 x.getRange(`D5:E${Math.max(end,5)}`).format.wrapText=true;x.getRange(`J5:O${Math.max(end,5)}`).format.wrapText=true;
 if(rows.length)x.getRange(`A5:O${end}`).format.autofitRows();
 x.freezePanes.freezeRows(4);x.freezePanes.freezeColumns(3);
 return x;
}
const query=Workbook.create();await table(query,'采购查询',p.query.rows,'采购原始记录查询；单位和适用范围待核。采购数量独立于日方Qty，不作自动换算或业务确认。');query.recalculate();
await (await SpreadsheetFile.exportXlsx(query)).save(p.query_file);
const check=Workbook.create();await table(check,'数量数值差异待核',p.query.differences,'仅列原数值不一致，单位未核实，暂不判定错数、短到或超到；可能存在分批到货。');
await table(check,'采购数量来源待核',p.query.missing,'缺少唯一采购数量或来源重复，不能用日方Qty代填；重复采购记录不在到货行重复分配。');check.recalculate();
await (await SpreadsheetFile.exportXlsx(check)).save(p.differences_file);
for(const [w,sheet,name] of [[query,'采购查询','query'],[check,'数量数值差异待核','differences']]){
 const im=await w.render({sheetName:sheet,range:'A1:J8',scale:1,format:'png'});
 await fs.writeFile(path.join(p.output,'technical/'+name+'-preview.png'),new Uint8Array(await im.arrayBuffer()));
 console.log((await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:5},summary:name+'-errors'})).ndjson);
}
