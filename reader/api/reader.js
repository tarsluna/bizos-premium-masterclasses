import {readFile} from 'node:fs/promises';
import {createHandler} from '../lib/reader.js';
let catalogue;
export default createHandler({load:async()=>catalogue ||= JSON.parse(await readFile(new URL('../data/transcripts.json',import.meta.url),'utf8'))});
