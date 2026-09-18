"""Server-only transcript bundle and deployment before any Whop link migration."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

from .transcripts import cue_line, group_cues


def export_reader(entries, cache, root):
    result=[]
    for entry in entries:
        if not entry.get('file'):
            continue
        data=json.loads((cache/(entry['id']+'.transcript.json')).read_text())
        result.append({k:entry.get(k) for k in ('id','title','course','source','whop_url')})
        result[-1]['text']='\n\n'.join(cue_line(c) for c in group_cues(data['cues']))
    if not result:
        raise ValueError('Aucune transcription à déployer')
    path=root/'reader/data/transcripts.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    encoded=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    temp=path.with_suffix('.tmp');temp.write_bytes(encoded);temp.replace(path)
    return hashlib.sha256(encoded).hexdigest()


def verify_locked(origin):
    if origin!='https://bizos-premium-transcriptions.vercel.app':
        raise ValueError('Origine du lecteur inattendue')
    try:
        with urllib.request.urlopen(origin+'/api/reader',timeout=30) as response:
            raise ValueError('Le lecteur accepte une requête anonyme')
    except urllib.error.HTTPError as exc:
        if exc.code!=401 or 'application/json' not in exc.headers.get('Content-Type','') or 'no-store' not in exc.headers.get('Cache-Control',''):
            raise ValueError('Protection du lecteur non confirmée') from None
        body=json.loads(exc.read())
        if body.get('error')!='Ouvre ce lecteur depuis BizOS Premium sur Whop.':
            raise ValueError('Réponse inattendue du lecteur')


def deploy_reader(config,digest,root):
    state=Path(config['state_dir']);record=state/'reader-deploy.json';reader=config['member_reader']
    fingerprint=hashlib.sha256(digest.encode())
    for name in ('api/reader.js','lib/reader.js','ui/index.html','ui/app.js','ui/style.css','build.js','package.json','package-lock.json','vercel.json','.vercelignore'):
        fingerprint.update(name.encode());fingerprint.update((root/'reader'/name).read_bytes())
    digest=fingerprint.hexdigest()
    old=json.loads(record.read_text()) if record.exists() else {}
    if old.get('sha256')!=digest:
        cli=reader['vercel_cli']
        # No authentication value is placed on the command line; use Vercel's existing account login.
        result=subprocess.run([cli,'--prod','--yes','--cwd',str(root/'reader')],capture_output=True,text=True,timeout=600)
        (state/'reader-deploy.log').write_text(result.stdout+'\n'+result.stderr)
        if result.returncode:
            raise ValueError('Déploiement du lecteur échoué : aucune modification Whop')
        verify_locked(reader['origin'])
        record.write_text(json.dumps({'sha256':digest,'origin':reader['origin']})+'\n')
    else:
        verify_locked(reader['origin'])
