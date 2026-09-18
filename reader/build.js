import {readFile,mkdir,copyFile} from 'node:fs/promises';
// Fail before deploy if the private server bundle is absent or malformed.
const entries=JSON.parse(await readFile(new URL('./data/transcripts.json',import.meta.url),'utf8'));
if(!entries.length || entries.some(x=>!x.id || !x.text))throw Error('Incomplete transcript bundle');
await mkdir('public',{recursive:true});
for(const name of ['index.html','app.js','style.css'])await copyFile('ui/'+name,'public/'+name);
console.log(`${entries.length} transcriptions packaged for the authenticated server function.`);
