import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire}from 'node:module';
import {pathToFileURL}from 'node:url';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
if(p.schema!=='pending-reference-flow-test/20261113'||p.formal_output!==false)throw Error('Explicit local test payload required');
const require=createRequire(path.join(p.artifact_node_modules,'..','test-final-runtime.cjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const literal=v=>typeof v==='string'&&/^[=+@-]/.test(v)?"'"+v:v;
const column=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
for(const kind of ['internal','customs']){
 const view=p[kind],wb=Workbook.create(),s=wb.worksheets.add(kind==='internal'?'内部到货表':'海关报关单');
 const end=view.rows.length+3,last=end+1,cols=view.headers.length,right=column(cols);
 s.showGridLines=false;s.getRange(`A1:${right}${last}`).format.font={name:'Arial',size:10,color:'#243342'};
 s.getRange(`A1:${right}${last}`).format.verticalAlignment='center';
 s.getRange('A1').values=[[p.batch+' '+s.name+'（流程测试）']];s.getRange('A1').format.font={name:'Arial',size:14,bold:true,color:'#963A21'};
 s.getRange('A2').values=[['本次保留未核项继续测试，黄色为参考/待核，红色为缺值；正式外发关闭。']];
 s.getRange(`A1:${right}2`).format.rowHeight=26;
 s.getRange(`A3:${right}3`).values=[view.headers];
 s.getRange(`A3:${right}3`).format={fill:'#344B63',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:38,horizontalAlignment:'center'};
 s.getRange(`A4:${right}${end}`).values=view.rows.map(r=>r.map(literal));
 for(const col of(kind==='internal'?['A','B','C','D','S']:['A','B'])){
  s.getRange(`${col}4:${col}${end}`).setNumberFormat('@');
  s.getRange(`${col}4:${col}${end}`).format.horizontalAlignment='left';
 }
 s.getRange(`A4:${right}${end}`).format.wrapText=true;s.getRange(`A4:${right}${end}`).format.rowHeight=42;
 const widths=kind==='internal'?[18,9,20,20,52,28,58,13,13,18,19,15,18,17,15,20,20,20,24,22,20]:[18,20,58,14,13,15,20,15,18,18,13,13,18,18,20,20,15,18,20];
 widths.forEach((width,i)=>s.getRange(`${column(i+1)}1:${column(i+1)}${last}`).format.columnWidth=width);
 for(let i=0;i<view.rows.length;i++){
  const n=i+4,r=view.rows[i];let lines=1;
  r.forEach((v,c)=>{if(typeof v==='string'){const units=[...v].reduce((a,ch)=>a+(ch.charCodeAt(0)>255?2:1),0);lines=Math.max(lines,Math.ceil(units/Math.max(8,widths[c]-2)));}});
  if(lines>2)s.getRange(`A${n}:${right}${n}`).format.rowHeight=lines*14+8;
  if(kind==='customs')s.getRange(`P${n}`).formulas=[[`=F${n}*G${n}`]];
  else{
   s.getRange(`K${n}`).formulas=[[`=I${n}*J${n}`]];
   if(r[13]!==null)s.getRange(`N${n}`).formulas=[[`=I${n}/H${n}`]];
   if(r[16]!==null)s.getRange(`Q${n}`).formulas=[[`=J${n}*O${n}`]];
   if(r[15]!==null)s.getRange(`P${n}`).formulas=[[`=J${n}*(1+O${n})*${p.vat_rates[i]}`]];
   if(r[17]!==null)s.getRange(`R${n}`).formulas=[[`=(P${n}+Q${n})*N${n}`]];
   if(r[20]!==null)s.getRange(`U${n}`).formulas=[[`=(P${n}+Q${n})*I${n}`]];
  }
 }
 s.getRange(`A${last}`).values=[['合计']];s.getRange(`A${last}:${right}${last}`).format.font.bold=true;
 if(kind==='internal'){
  s.getRange(`K${last}`).formulas=[[`=SUM(K4:K${end})`]];
  if(view.rows.every(r=>r[20]!==null))s.getRange(`U${last}`).formulas=[[`=SUM(U4:U${end})`]];
  s.getRange(`O4:O${end}`).setNumberFormat('0.00%');
  const w=wb.worksheets.add(p.weights.name),count=p.weights.rows.length;
  w.showGridLines=false;w.getRange(`A1:H${count}`).values=p.weights.rows.map(r=>r.map(literal));
  for(const f of p.weights.formulas)w.getRange(f.cell).formulas=[[f.formula]];
  w.getRange(`A1:H${count}`).format.font={name:'Arial',size:10};w.getRange(`A1:H${count}`).format.rowHeight=20;
  w.getRange('A1:H1').format={fill:'#344B63',font:{name:'Arial',size:10,color:'#FFFFFF',bold:true},wrapText:true,rowHeight:34};
  [22,16,18,22,18,18,18,23].forEach((width,i)=>w.getRange(`${column(i+1)}1:${column(i+1)}${count}`).format.columnWidth=width);
  w.freezePanes.freezeRows(1);
 }else{
  for(const col of ['P','Q','S'])s.getRange(`${col}${last}`).formulas=[[`=SUM(${col}4:${col}${end})`]];
 }
 for(const [address,color]of Object.entries(p.colors[kind]))s.getRange(address).format.fill=color==='red'?'#FFC7CE':'#FFF2CC';
 if(p.totals.original_amount!==p.totals.rounded_amount)s.getRange((kind==='internal'?'K':'P')+last).format.fill='#FFF2CC';
 s.freezePanes.freezeRows(3);s.freezePanes.freezeColumns(3);
 wb.recalculate();
 const actual=s.getRange(`A4:${right}${end}`).values;
 for(let i=0;i<actual.length;i++)for(let j=0;j<cols;j++)if(typeof view.rows[i][j]==='number'&&(!Number.isFinite(Number(actual[i][j]))||Math.abs(Number(actual[i][j])-view.rows[i][j])>1e-7))throw Error(`Recalculation mismatch ${kind} ${i+4}/${j+1}`);
 const preview=await wb.render({sheetName:s.name,range:kind==='internal'?'E1:U9':'A1:S9',format:'png',scale:1});
 await fs.writeFile(path.join(p.output_dir,kind+'-preview.png'),new Uint8Array(await preview.arrayBuffer()));
 if(kind==='internal'){
  const weights=await wb.render({sheetName:p.weights.name,range:'A1:H10',format:'png',scale:1});
  await fs.writeFile(path.join(p.output_dir,'weights-preview.png'),new Uint8Array(await weights.arrayBuffer()));
 }
 const filename=p.batch+(kind==='internal'?'_内部到货表_流程测试.xlsx':'_海关报关单_流程测试.xlsx');
 await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(p.output_dir,filename));
}
console.log(JSON.stringify({files:2,test_only:true,formal_output:false}));
