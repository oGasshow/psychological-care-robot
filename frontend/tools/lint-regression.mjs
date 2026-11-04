/** Keep normal ESLint enabled; reject diagnostics beyond the recorded old debt. */
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {ESLint} from 'eslint';

const baseline=JSON.parse(await readFile(new URL('../eslint-baseline.json',import.meta.url),'utf8'));
const counts=new Map();
const key=row=>JSON.stringify([row.file,row.rule,row.severity,row.message]);
for(const row of baseline.diagnostics)counts.set(key(row),(counts.get(key(row))||0)+1);
const results=await new ESLint().lintFiles(['.']);
const introduced=[];
let errors=0,warnings=0;
for(const result of results){
  errors+=result.errorCount;warnings+=result.warningCount;
  for(const message of result.messages){
    const row={file:path.relative(process.cwd(),result.filePath).split(path.sep).join('/'),rule:message.ruleId,severity:message.severity,message:message.message};
    const remaining=counts.get(key(row))||0;
    if(remaining)counts.set(key(row),remaining-1);
    else introduced.push({...row,line:message.line});
  }
}
console.log(JSON.stringify({baseline_commit:baseline.baseline_commit,full_repository_errors:errors,full_repository_warnings:warnings,new_diagnostics:introduced},null,2));
if(introduced.length)process.exitCode=1;
