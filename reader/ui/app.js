const $=id=>document.getElementById(id);
let lessons=[],selected=null,sequence=0;
async function request(query='') {
  const response=await fetch('/api/reader'+query,{cache:'no-store',credentials:'same-origin'});
  const data=await response.json();
  if(!response.ok){const error=new Error(data.error || 'Lecture indisponible.');error.status=response.status;throw error}
  return data;
}
function lock(message){sequence++;selected=null;$('text').value='';$('content').hidden=true;$('notice').textContent=message}
function list(){
  $('list').replaceChildren();
  const query=$('search').value.toLocaleLowerCase('fr');
  for(const lesson of lessons.filter(x=>(x.title+' '+x.course).toLocaleLowerCase('fr').includes(query))){
    const button=document.createElement('button');button.type='button';button.textContent=lesson.title;button.setAttribute('aria-current',String(lesson.id===selected));
    const small=document.createElement('small');small.textContent=lesson.course;button.append(small);button.addEventListener('click',()=>open(lesson.id));$('list').append(button);
  }
}
async function open(id){
  const version=++sequence;$('notice').textContent='Chargement de la transcription…';$('content').hidden=true;$('text').value='';
  try{const lesson=await request('?lesson='+encodeURIComponent(id));if(version!==sequence)return;selected=id;$('title').textContent=lesson.title;$('collection').textContent=lesson.course;$('meta').textContent=lesson.source+' · Texte intégral';$('text').value=lesson.text;$('content').hidden=false;$('notice').textContent='';history.replaceState(null,'','#'+id);list()}
  catch(error){if(version===sequence)lock(error.message)}
}
$('copy').addEventListener('click',async()=>{
  if(!selected)return;
  $('copy').disabled=true;
  try{
    const lesson=await request('?lesson='+encodeURIComponent(selected));
    try{await navigator.clipboard.writeText(lesson.text);$('copy').textContent='Copié !'}
    catch{$('text').focus();$('text').select();$('notice').textContent='Le texte est sélectionné. Utilise ⌘C sur Mac ou Ctrl+C sur Windows pour le copier.'}
  }catch(error){lock(error.message)}finally{$('copy').disabled=false;setTimeout(()=>$('copy').textContent='Tout copier',2000)}
});
$('search').addEventListener('input',list);
async function recheck(){if(!selected)return;try{await request('?check=1')}catch(error){lock(error.message)}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)recheck()});
window.addEventListener('pageshow',recheck);
setInterval(recheck,60000);
try{
  const result=await request();lessons=result.lessons;list();
  const candidate=location.hash.slice(1) || location.pathname.split('/').find(x=>x.startsWith('lesn_'));
  const first=lessons.find(x=>x.id===candidate)||lessons[0];
  if(first)await open(first.id);else lock('Les transcriptions arrivent bientôt.');
}catch(error){lock(error.message)}
