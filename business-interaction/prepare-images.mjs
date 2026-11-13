import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const plan=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const w=Workbook.create();const s=w.worksheets.add(plan.sheet);
// Author a single native image anchor; Python expands it with original verified media bytes.
for(const item of plan.images.slice(0,1)){
 const raw=await fs.readFile(item.file);
 s.images.add({dataUrl:'data:image/'+(item.file.endsWith('.png')?'png':'jpeg')+';base64,'+raw.toString('base64'),anchor:{from:{row:item.row-1,col:4},extent:{widthPx:item.width,heightPx:item.height}}});
}
await (await SpreadsheetFile.exportXlsx(w)).save(plan.output);
