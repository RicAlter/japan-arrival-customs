import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));const w=Workbook.create();const s=w.worksheets.add(p.sheet);
s.getRange('A1:J1').merge();s.getRange('A1').values=[['计算审核：原数量、内部计价及申报数量分开']];
s.getRange('A2:J2').merge();s.getRange('A2').values=[[p.mode==='synthetic'?'SYNTHETIC 隔离技术测试，非真实价格更新或真人确认；不得外发':'受控计算审核，包装参考需明确适用范围及计算确认；不得外发']];
s.getRange('A3:J3').merge();s.getRange('A3').values=[[p.version_token]];
s.getRange('A1:J1').format={fill:'#24415C',font:{bold:true,size:14,color:'#FFFFFF'},rowHeight:30};
s.getRange('A2:J2').format={fill:'#FFF2CC',font:{size:10,color:'#5D4522'},wrapText:true,rowHeight:30};
s.getRange('A3:J3').format={font:{size:9,color:'#777777'},rowHeight:16};
const last=p.rows.length+4;s.getRange('A4:AO4').values=[p.headers];
const numeric=new Set([0,5,7,9,11,12,13,16,17,18,23,24,28,33,34,35,36,39,40]);
s.getRange(`A5:AO${last}`).values=p.rows.map(r=>r.values.map((x,i)=>numeric.has(i)&&x!==null&&x!==''?Number(x):x));
s.getRange(`A4:AO${last}`).format={font:{name:'Arial',size:10},verticalAlignment:'center',rowHeight:30};
s.getRange('A4:AO4').format={fill:'#24415C',font:{bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:40};
function col(n){let r='';for(;n;n=Math.floor((n-1)/26))r=String.fromCharCode(65+(n-1)%26)+r;return r;}
const widths=[11,13,19,45,26,18,17,19,18,14,18,20,18,23,34,18,16,18,20,34,18,28,25,17,17,32,32,40,18,18,30,35,28,22,20,20,24,20,42,20,24];
for(let i=1;i<=41;i++)s.getRange(col(i)+':'+col(i)).format.columnWidth=widths[i-1];
for(const c of Object.keys(p.editable))s.getRange(c+'5:'+c+last).format.fill='#E8F1FA';
for(const c of ['F','H','J','M','AC','AI','AJ'])s.getRange(c+'5:'+c+last).format.fill='#FFF2CC';
for(const [c,formulas] of Object.entries(p.formulas))s.getRange(c+'5:'+c+last).formulas=formulas.map(f=>[f]);
for(const c of ['D','E','O','T','U','V','W','Z','AA','AB','AF','AM'])s.getRange(c+'5:'+c+last).format.wrapText=true;
s.freezePanes.freezeRows(4);s.freezePanes.freezeColumns(3);w.recalculate();
await (await SpreadsheetFile.exportXlsx(w)).save(p.draft_file);
for(const [name,range] of [['inputs','A1:N8'],['packaging','AH4:AO8']]){
const im=await w.render({sheetName:p.sheet,range,scale:1,format:'png'});await fs.writeFile(path.join(path.dirname(p.draft_file),name+'.png'),new Uint8Array(await im.arrayBuffer()));}
console.log((await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:5},summary:'formula-errors'})).ndjson);
