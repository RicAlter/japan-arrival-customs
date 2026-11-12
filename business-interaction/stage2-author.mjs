import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const p=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const require=createRequire(path.join(p.artifact_node_modules,'..','stage2-runtime.cjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const w=Workbook.create(),s=w.worksheets.add('invoice (計算)');
s.getRange('V1:AM1').values=[p.headers];
for(const r of p.rows){
 const n=r.row;
 s.getRange(`K${n}:M${n}`).values=[[r.total_pieces,Number(r.quantity),Number(r.price)]];
 s.getRange(`N${n}`).values=[[Number(r.amount)]];
 if(r.rounded_price!==null)s.getRange(`I${n}`).formulas=[[`=ROUND(M${n}/(K${n}/L${n}),0)`]];
 s.getRange(`V${n}:AM${n}`).values=[r.values];
 const formulas={Z:`=K${n}/L${n}`,AB:`=M${n}/Z${n}`,AC:`=I${n}*K${n}`,AD:`=AC${n}-N${n}`,
   AG:`=M${n}*AE${n}`,AH:`=M${n}*(1+AE${n})*AF${n}`,AJ:`=(AG${n}+AH${n})*L${n}`};
 if(r.values[0]!==null&&r.values[1]!==null)formulas.X=`=V${n}*W${n}`;
 if(r.values[2]!==null&&r.values[3]!==null)formulas.Y=`=K${n}/X${n}`;
 if(r.values[3]!==null)formulas.AA=`=L${n}/Y${n}`;
 if(r.values[13]!==null)formulas.AI=`=(AG${n}+AH${n})*AA${n}`;
 const offset={Z:4,AB:6,AC:7,AD:8,AG:11,AH:12,AJ:14,X:2,Y:3,AA:5,AI:13};
 for(const [c,f]of Object.entries(formulas))if(r.values[offset[c]]!==null)s.getRange(c+n).formulas=[[f]];
}
w.recalculate();
for(const r of p.rows){
 const values=s.getRange(`V${r.row}:AM${r.row}`).values[0];
 for(let i=0;i<15;i++)if(r.values[i]!==null&&Math.abs(Number(values[i])-r.values[i])>1e-7)throw Error(`Recalculation differs row ${r.row} col ${i}`);
}
await(await SpreadsheetFile.exportXlsx(w)).save(p.draft_file);
