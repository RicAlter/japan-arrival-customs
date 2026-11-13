import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire}from 'node:module';
import {pathToFileURL}from 'node:url';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const require=createRequire(path.join(p.artifact_node_modules,'..','presentation-runtime.cjs'));
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const col=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
const literal=v=>typeof v==='string'&&/^[=+@-]/.test(v)?"'"+v:v;
for(const b of p.books){
 if(crypto.createHash('sha256').update(await fs.readFile(b.source)).digest('hex')!==b.source_sha256)throw Error('Source changed');
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(b.source)),s=wb.worksheets.getItem(b.sheet);
 const last=b.values.length,right=col(b.columns);
 s.getRange(`A1:${right}${b.source_rows}`).clear({applyTo:'all'});
 s.getRange(`A1:${right}${last}`).values=b.values.map(r=>r.map(literal));
 s.getRange(`A1:${right}1`).values=[b.headers];
 s.getRange(`A1:${right}${last}`).format.font={name:'Arial',size:10,color:'#202C38'};
 s.getRange(`A1:${right}${last}`).format.fill='#FFFFFF';
 s.getRange(`A1:${right}${last}`).format.verticalAlignment='center';
 s.getRange(`A1:${right}${last}`).format.wrapText=true;
 s.getRange(`A1:${right}${last}`).format.numberFormat=b.formats;
 for(let i=0;i<b.heights.length;i++)s.getRange(`A${i+1}:${right}${i+1}`).format.rowHeight=b.heights[i];
 for(const f of b.formulas)s.getRange(f.cell).formulas=[[f.formula]];
 s.getRange(`A1:${right}1`).format={fill:'#344B63',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:36,horizontalAlignment:'center'};
 s.getRange(`A1:${right}1`).format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};
 s.getRange(`A${last}:${right}${last}`).format={fill:'#F2F4F6',font:{name:'Arial',size:10,bold:true,color:'#202C38'},rowHeight:26};
 s.freezePanes.freezeRows(1);s.freezePanes.freezeColumns(3);s.showGridLines=false;
 wb.recalculate();
 const actual=s.getRange(`A2:${right}${last}`).values;
 for(let i=0;i<actual.length;i++)for(let j=0;j<b.columns;j++){
  const expected=b.values[i+1][j];
  if(typeof expected==='number'&&(!Number.isFinite(Number(actual[i][j]))||Math.abs(Number(actual[i][j])-expected)>1e-7))throw Error(`Presentation recalculation mismatch ${b.kind} ${i+2}/${j+1}`);
 }
 const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1200});
 await fs.writeFile(path.join(p.output_dir,b.kind+'-errors.ndjson'),scan.ndjson);
 const preview=await wb.render({sheetName:b.sheet,range:b.kind==='customs'?'A1:S8':'E1:U8',format:'png',scale:1});
 await fs.writeFile(path.join(p.output_dir,b.kind+'-preview.png'),new Uint8Array(await preview.arrayBuffer()));
 await(await SpreadsheetFile.exportXlsx(wb)).save(b.output);
}
console.log(JSON.stringify({files:p.books.map(b=>b.output),data_rows:p.rows,presentation_only:true}));
