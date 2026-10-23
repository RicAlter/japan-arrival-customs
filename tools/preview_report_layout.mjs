// Development evidence only. The Skill itself uses Python/openpyxl.
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const [modules, output, ...sources] = process.argv.slice(2);
const require = createRequire(import.meta.url);
const entry = require.resolve('@oai/artifact-tool', {paths:[modules]});
const {FileBlob, SpreadsheetFile} = await import(pathToFileURL(entry).href);
await fs.mkdir(output,{recursive:true});
const evidence=[];
for (let i=0;i<sources.length;i++) {
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(sources[i]));
  wb.recalculate();
  const names=(await wb.inspect({kind:'sheet',include:'id,name',maxChars:2500})).ndjson;
  const tasks=i===0 ? [['图片处理','A1:J5'],['图片处理','M1:S5']] : [['Sheet1','A1:F5'],['Sheet1','G1:T5'],['重さとサイズ (2)','A1:H5'],['①处理说明','A1:C9']];
  for (let j=0;j<tasks.length;j++) {
    const [sheetName,range]=tasks[j];
    const preview=await wb.render({sheetName,range,scale:1,format:'png'});
    await fs.writeFile(`${output}/report-${i}-${j}.png`,new Uint8Array(await preview.arrayBuffer()));
  }
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',
     options:{useRegex:true,maxResults:10},maxChars:2500,summary:'recalculated error scan'});
  evidence.push({source:sources[i],sheets:names,errors:errors.ndjson});
}
await fs.writeFile(`${output}/render-evidence.json`,JSON.stringify(evidence,null,2));
console.log(JSON.stringify(evidence));
