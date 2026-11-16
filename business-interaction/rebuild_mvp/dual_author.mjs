import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const require=createRequire(`${p.node_modules}/../projection-runtime.cjs`);
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
if(p.verify_only){
  const result=[];
  for(const view of p.views){
    const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(view.path));
    let exercise=null;
    if(view.exercise_formulas){
      const s=wb.worksheets.getItem(view.sheet),f=s.getRange('F2'),g=s.getRange('G2'),amount=s.getRange('P2');
      const originalF=f.values[0][0],originalG=g.values[0][0],originalP=amount.values[0][0];
      g.values=[[null]];wb.recalculate();const missing=amount.values[0][0];
      g.values=[[0]];wb.recalculate();const zero=amount.values[0][0];
      g.values=[[originalG]];f.values=[[originalF+1]];wb.recalculate();const changed=amount.values[0][0];
      if(![null,''].includes(missing)||zero!==0||changed!==(originalF+1)*originalG)throw Error('Projection formula boundary failed');
      f.values=[[originalF]];g.values=[[originalG]];wb.recalculate();
      if(amount.values[0][0]!==originalP)throw Error('Projection formula restore failed');
      exercise={engine:'Artifact in-memory disposable verification; no save to delivered file',original:originalP,missing,zero,changed,restored:amount.values[0][0]};
    }
    const scan=await wb.inspect({kind:'table',range:`'${view.sheet}'!${view.range}`,tableMaxRows:5,tableMaxCols:10,maxChars:1600});
    const png=await wb.render({sheetName:view.sheet,range:view.range,scale:1,format:'png'});
    await fs.writeFile(view.preview,new Uint8Array(await png.arrayBuffer()));
    result.push({sheet:view.sheet,inspection:scan.ndjson,preview:view.preview,exercise});
  }
  await fs.writeFile(p.receipt,JSON.stringify(result,null,2));process.exit(0);
}
const wb=Workbook.create(),s=wb.worksheets.add(p.sheet);
const right='AG',last=p.matrix.length;
const literal=v=>typeof v==='string'&&/^[=+@-]/.test(v)?"'"+v:v;
s.getRange(`A1:${right}${last}`).values=p.matrix.map(row=>row.map(literal));
s.getRange(`A1:${right}${last}`).format.font={name:'Arial',size:10};
s.getRange(`A1:${right}${last}`).format.rowHeight=p.layout.data_height||50;
s.getRange(`A1:${right}${last}`).format.verticalAlignment='center';
s.getRange(`A1:${right}${last}`).format.wrapText=true;
s.getRange(`A1:${right}1`).format.font.bold=true;
s.getRange(`A1:${right}1`).format.rowHeight=p.layout.header_height||43;
for(const d of Object.values(p.layout.column_dimensions)){
  const first=Math.max(1,d.min),end=Math.min(33,d.max);
  if(first<=end)s.getRangeByIndexes(0,first-1,last,end-first+1).format.columnWidth=d.width;
}
for(const [cell,formula]of Object.entries(p.formulas))s.getRange(cell).formulas=[['='+formula]];
for(const [cell,state]of Object.entries(p.marks))s.getRange(cell).format.fill=state==='pending'?'#FCE4D6':'#FFF2CC';
for(const merge of p.merges)s.mergeCells(merge);
s.freezePanes.freezeRows(1);s.showGridLines=false;
wb.recalculate();
const check=await wb.inspect({kind:'table',range:`'${p.sheet}'!E1:S${Math.min(last,5)}`,tableMaxRows:5,tableMaxCols:15,maxChars:1500});
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1800});
await fs.writeFile(p.inspection,JSON.stringify({check:check.ndjson,errors:errors.ndjson},null,2));
await(await SpreadsheetFile.exportXlsx(wb)).save(p.output);
