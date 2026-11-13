import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const args=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,all)=>i%2?a:[...a,[v.replace(/^--/,''),all[i+1]]],[]));
const model=JSON.parse(await fs.readFile(args.model,'utf8'));
await fs.access(args.output).then(()=>{throw new Error('Refuse to overwrite output');},()=>{});
const wb=Workbook.create(),s=wb.worksheets.add('本批业务异常');
const m=model.metrics,last=13+model.exceptions.length;
s.showGridLines=false;
s.getRange(`A1:H${Math.max(last,15)}`).format={font:{name:'Arial',size:10,color:'#233247'},verticalAlignment:'center'};
const widths=[24,16,20,54,24,28,26,44];
for(let i=0;i<widths.length;i++)s.getRange(`${String.fromCharCode(65+i)}1:${String.fromCharCode(65+i)}${Math.max(last,15)}`).format.columnWidth=widths[i];
s.getRange('A2').values=[['本批业务异常']];
s.getRange('A2').format={font:{name:'Arial',size:14,bold:true,color:'#193B54'},rowHeight:30};
s.getRange('D2').values=[[model.batch_label]];
s.getRange('A3').values=[['原表行数']];s.getRange('B3').values=[[m.rows]];
s.getRange('D3').values=[['仅展示影响当前两张受控草稿的新增事项']];
s.getRange('A5:D8').values=[['分类','数量','单位','本批处理'],
 ['影响当前报单',m.current_business_task_rows,'原行','见下方清单；只处理当前缺值或冲突'],
 ['已有确认值',m.confirmed_rows_no_repeat,'原行','保留原确认名称、材质和计算输入，无需重复填写'],
 ['资料库长期完善',m.long_term_unique_cases_retained,'商品项','后台保留，不要求本批补齐版本或规格']];
s.getRange('A5:D5').format={fill:'#193B54',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:26,horizontalAlignment:'center'};
s.getRange('A6:D8').format.rowHeight=36;
s.getRange('D6:D8').format.wrapText=true;
s.getRange('B3').setNumberFormat('#,##0');s.getRange('B6:B8').setNumberFormat('#,##0');
s.getRange('D9').values=[['长期项与已确认行重叠，数量不可相加。']];
s.getRange('D9').format={font:{name:'Arial',size:10,italic:true,color:'#52657A'},rowHeight:25};
s.getRange('A10').values=[['正式外发']];s.getRange('B10').values=[['继续关闭']];
s.getRange('D10').values=[['正式关务缺项、身份和权限门禁保持原样。']];
s.getRange('B10').format={fill:'#FFF2CC',font:{name:'Arial',size:10,bold:true,color:'#7A4B00'},rowHeight:28};
s.getRange('A13:H13').values=[model.headers];
s.getRange('A13:H13').format={fill:'#193B54',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28,wrapText:true,horizontalAlignment:'center'};
if(model.exceptions.length){
 s.getRange(`A14:H${last}`).values=model.exceptions;
 s.getRange(`A14:H${last}`).format={rowHeight:42,wrapText:true};
 s.getRange(`C14:C${last}`).setNumberFormat('@');
 s.getRange(`E14:F${last}`).format.fill='#FFC7CE';
 s.tables.add(`A13:H${last}`,true,'CurrentBusinessExceptions');
 s.freezePanes.freezeRows(13);
}else{
 s.getRange('D11').values=[[`本批无新增需补填项，无需填写原${m.before_technical_manual_cases.toLocaleString('en-US')}项。`]];
 s.getRange('D11').format.rowHeight=32;
}
wb.recalculate();
console.log((await wb.inspect({kind:'region',sheetId:s.name,range:'A5:D10',maxChars:1600,tableMaxRows:6,tableMaxCols:4})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
await fs.mkdir(path.dirname(args.output),{recursive:true});
await fs.mkdir(args.previews,{recursive:true});
const preview=await wb.render({sheetName:s.name,range:'A1:H15',scale:1,format:'png'});
await fs.writeFile(path.join(args.previews,'business-list.png'),new Uint8Array(await preview.arrayBuffer()));
await (await SpreadsheetFile.exportXlsx(wb)).save(args.output);
console.log(JSON.stringify({exceptions:model.exceptions.length,currentRequired:m.current_required_input_cells}));
