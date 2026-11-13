// Spreadsheet authoring uses the bundled public artifact-tool API only.
import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const args = Object.fromEntries(process.argv.slice(2).reduce((a,v,i,all)=>i%2?a:[...a,[v.replace(/^--/,''),all[i+1]]],[]));
const model = JSON.parse(await fs.readFile(args.model,'utf8'));
await fs.access(args.output).then(()=>{throw new Error('Refuse to overwrite workbook');},()=>{});
const wb=Workbook.create();
const main=wb.worksheets.add('人工补充'), sources=wb.worksheets.add('候选与来源');
const names=['人工补充','候选与来源'];
const sets=[{sheet:main,headers:model.headers,rows:model.rows,widths:[22,19,46,27,34,22,46,22,30,30,38,18],table:'IdentitySupplement'},
  {sheet:sources,headers:model.source_headers,rows:model.source_rows,widths:[15,19,42,22,34,44,30,16,42,24,12,52,24,26,24,22],table:'IdentitySources'}];
for (const set of sets) {
  const {sheet,headers,rows,widths}=set, end=String.fromCharCode(64+headers.length), last=5+rows.length;
  sheet.showGridLines=false;
  const body=sheet.getRange(`A5:${end}${Math.max(last,6)}`);
  body.format={font:{name:'Arial',size:10,color:'#233247'},verticalAlignment:'center',wrapText:true};
  body.setNumberFormat('@');
  sheet.getRange(`A5:${end}5`).values=[headers];
  if(rows.length) sheet.getRange(`A6:${end}${last}`).values=rows;
  for(let i=0;i<widths.length;i++) sheet.getRange(`${String.fromCharCode(65+i)}1:${String.fromCharCode(65+i)}${Math.max(last,6)}`).format.columnWidth=widths[i];
  sheet.getRange(`A5:${end}5`).format={fill:'#193B54',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:32,wrapText:true};
  if(rows.length) sheet.getRange(`A6:${end}${last}`).format.rowHeight=56;
  sheet.getRange('B2').values=[[sheet===main?'人工补充':'候选与来源']];
  sheet.getRange(`B2:${end}2`).format={font:{name:'Arial',size:18,bold:true,color:'#193B54'},rowHeight:36};
  sheet.getRange('B3').values=[[sheet===main?'仅填浅黄项':'只读参考']];
  sheet.getRange('C3').values=[[sheet===main?'缺证据留空。来源编号可逗号分隔；填写依据和“确认”后，仍须维护侧预览确认。':'按商品编码筛选来源。规格原文仅供参考；同批资料不计跨批覆盖。']];
  sheet.getRange(`B3:${end}3`).format={font:{name:'Arial',size:10,color:'#52657A'},rowHeight:56,wrapText:true};
  sheet.freezePanes.freezeRows(5); sheet.freezePanes.freezeColumns(2);
  if(rows.length) sheet.tables.add(`A5:${end}${last}`,true,set.table);
}
if(model.rows.length) {
  const last=model.rows.length+5;
  main.getRange(`F6:L${last}`).format.fill='#F0F3F6';
  for(const col of ['F','K','L']) main.getRange(`${col}6:${col}${last}`).format.fill='#FFF2CC';
  const mapping={japanese_name:'G',version:'H',specification:'I',material_reference:'J'};
  // Group contiguous ranges to keep styling compact on the 1,894-case real form.
  for(const [field,col] of Object.entries(mapping)) {
    let start=null;
    for(let i=0;i<=model.rows.length;i++) {
      const needed=i<model.rows.length&&(model.case_fields[model.rows[i][0]]||[]).includes(field);
      if(needed&&start===null) start=i+6;
      if(!needed&&start!==null){main.getRange(`${col}${start}:${col}${i+5}`).format.fill='#FFF2CC';start=null;}
    }
  }
  main.getRange(`L6:L${last}`).dataValidation={rule:{type:'list',values:['确认']}};
}
// Optional explicit cell edits support isolated synthetic acceptance fixtures only.
if(args.edits) for(const edit of JSON.parse(await fs.readFile(args.edits,'utf8'))) {
  const target=wb.worksheets.getItem(edit.sheet).getRange(edit.cell);
  if(edit.formula)target.formulas=[[edit.formula]];else target.values=[[edit.value]];
}
wb.recalculate();
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:1000})).ndjson);
await fs.mkdir(path.dirname(args.output),{recursive:true});
if(args.previews) {
  await fs.mkdir(args.previews,{recursive:true});
  for(let i=0;i<names.length;i++) {
    const preview=await wb.render({sheetName:names[i],range:i?'A2:F9':'A2:F9',scale:1,format:'png'});
    await fs.writeFile(path.join(args.previews,`sheet-${i+1}.png`),new Uint8Array(await preview.arrayBuffer()));
  }
}
await (await SpreadsheetFile.exportXlsx(wb)).save(args.output);
console.log(JSON.stringify({workbook:args.output,cases:model.rows.length,source_rows:model.source_rows.length}));
