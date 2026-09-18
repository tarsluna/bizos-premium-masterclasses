#!/usr/bin/env python3
"""Weekly Whop → complete transcripts → Whop descriptions and public Markdown.

All credentials, signed URLs, snapshots and logs remain outside the Git repository.
Run with --apply to write Whop, and --publish to commit/push generated files.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .transcripts import merge_cues, parse_vtt, parse_fathom_text, validate_transcript, render_markdown, merge_description

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def env_value(path, name):
    for line in Path(path).read_text().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key.strip().removeprefix('export ') == name:
            return shlex.split(value)[0]
    raise ValueError(f'Configuration manquante : {name}')


def http_text(url, headers=None, method='GET', body=None):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=headers or {}, method=method,
                                         data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f'HTTP {exc.code} ({urllib.parse.urlsplit(url).hostname})') from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise RuntimeError('Réseau indisponible') from None
        time.sleep(min(30, 2 ** (attempt + 1)))


def curl_text(url):
    if urllib.parse.urlsplit(url).hostname != 'fathom.video':
        raise ValueError('Domaine Fathom inattendu')
    result = subprocess.run(['/usr/bin/curl', '--silent', '--show-error', '--fail', '--location', '--max-time', '60',
                             '--retry', '3', '--user-agent', 'Mozilla/5.0', url], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Lecture Fathom impossible (curl {result.returncode})')
    return result.stdout


class Whop:
    def __init__(self, key):
        self.key = key

    def request(self, path, method='GET', body=None, params=None):
        url = 'https://api.whop.com/api/v1/' + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        return json.loads(http_text(url, {'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'}, method, body))

    def list(self, path, **params):
        params = dict(params, first=100)
        seen = set()
        while True:
            page = self.request(path, params=dict(params))
            yield from page['data']
            info = page.get('page_info', {})
            if not info.get('has_next_page'):
                return
            cursor = info.get('end_cursor')
            if not cursor or cursor in seen:
                raise ValueError('Pagination Whop incohérente')
            seen.add(cursor)
            params['after'] = cursor


def fetch_fathom(url):
    if not re.fullmatch(r'https://fathom\.video/share/[A-Za-z0-9_-]+', url):
        raise ValueError('Lien Fathom invalide')
    page = curl_text(url)
    match = re.search(r'data-page="([^"]*)"', page)
    if not match:
        raise ValueError('Page de partage Fathom sans données')
    props = json.loads(html.unescape(match[1]))['props']
    target = props.get('copyTranscriptUrl')
    if not target:
        raise ValueError('Transcription Fathom indisponible')
    transcript = json.loads(curl_text(target))
    cues = parse_fathom_text(transcript['plain_text'])
    duration = props.get('duration')
    validate_transcript(cues, duration)
    return cues, {'source': 'Fathom', 'recorded_at': props.get('call', {}).get('started_at'), 'duration_seconds': duration}


def fetch_mux(lesson, cache):
    video = lesson.get('video_asset')
    if not video or video.get('status') != 'ready':
        raise ValueError('Vidéo ou sous-titres pas encore disponibles')
    playback = video.get('signed_playback_id') or video.get('playback_id')
    token = video.get('signed_video_playback_token')
    url = f'https://stream.mux.com/{playback}.m3u8'
    if token:
        url += '?' + urllib.parse.urlencode({'token': token})
    manifest = http_text(url)
    tracks = [line for line in manifest.splitlines() if 'TYPE=SUBTITLES' in line and 'LANGUAGE="fr"' in line]
    if not tracks:
        raise ValueError('Sous-titres français pas encore disponibles')
    playlist_url = urllib.parse.urljoin(url, re.search(r'URI="([^"]+)"', tracks[0])[1])
    playlist = http_text(playlist_url)
    if '#EXT-X-ENDLIST' not in playlist:
        raise ValueError('Sous-titres encore en traitement')
    urls = [urllib.parse.urljoin(playlist_url, line) for line in playlist.splitlines() if line and not line.startswith('#')]
    def segment(u):
        return parse_vtt(http_text(u))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        cues = merge_cues(list(pool.map(segment, urls)))
    validate_transcript(cues, video.get('duration_seconds'))
    return cues, {'source': 'Sous-titres français Whop / Mux', 'duration_seconds': video.get('duration_seconds')}


def source_signature(lesson):
    video = lesson.get('video_asset') or {}
    # Only the original share link and video identity, never expiring playback tokens.
    links = sorted(set(re.findall(r'https://fathom\.video/share/[A-Za-z0-9_-]+', lesson.get('content') or '')))
    return hashlib.sha256(json.dumps([video.get('id'), video.get('asset_id'), video.get('duration_seconds'), links]).encode()).hexdigest()


def acquire(lesson, cache):
    path = cache / (lesson['id'] + '.transcript.json')
    sig = source_signature(lesson)
    if path.exists():
        data = json.loads(path.read_text())
        if data['signature'] == sig:
            validate_transcript(data['cues'], data['meta'].get('duration_seconds'))
            return data['cues'], data['meta']
    links = list(dict.fromkeys(re.findall(r'https://fathom\.video/share/[A-Za-z0-9_-]+', lesson.get('content') or '')))
    if len(links) > 1:
        raise ValueError('Plusieurs enregistrements Fathom : association manuelle nécessaire')
    if links:
        cues, meta = fetch_fathom(links[0])
    else:
        cues, meta = fetch_mux(lesson, cache)
    atomic_json(path, {'signature': sig, 'cues': cues, 'meta': meta})
    return cues, meta


def ensure_upload(api, lesson_id, data, state):
    digest = hashlib.sha256(data).hexdigest()
    path = state / 'uploads' / (lesson_id + '-' + digest + '.json')
    cached = json.loads(path.read_text()) if path.exists() else None
    if cached:
        existing = api.request('files/' + cached['id'])
        if existing['upload_status'] == 'ready':
            return existing['id']
        if existing['upload_status'] != 'failed':
            raise ValueError('Fichier Whop précédent encore en traitement')
    created = api.request('files', method='POST', body={'filename': 'transcription--' + lesson_id + '.md', 'visibility': 'private'})
    # Preserve upload identity immediately so a subsequent run cannot create duplicates silently.
    atomic_json(path, {'id': created['id'], 'sha256': digest})
    req = urllib.request.Request(created['upload_url'], data=data, headers=created['upload_headers'], method='PUT')
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status not in (200, 201, 204):
            raise ValueError('Échec de téléversement Whop')
    for attempt in range(20):
        uploaded = api.request('files/' + created['id'])
        if uploaded['upload_status'] == 'ready':
            raw = http_text(uploaded['url']).encode()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Le fichier téléchargé diffère de la transcription complète')
            return uploaded['id']
        if uploaded['upload_status'] == 'failed':
            break
        time.sleep(3)
    raise ValueError('Le fichier Whop n’est pas prêt')


def sync_one(api, lesson, cues, source, state, apply, markdown=None, transcript_url=None):
    # Re-read immediately before writing so a previous inventory cannot clobber user edits.
    live = api.request('course_lessons/' + lesson['id'])
    if source_signature(live) != source_signature(lesson):
        raise ValueError('La vidéo source a changé depuis la collecte')
    def description(value):
        desired = merge_description(value, cues, source, transcript_url)
        if len(desired) > 64000:
            if not transcript_url or markdown is None:
                raise ValueError('Description trop longue : fichier complet requis')
            desired = merge_description(value, [], source, transcript_url)
        if len(desired) > 65000:
            raise ValueError('Description existante trop longue pour ajouter le lien')
        return desired
    desired = description(live.get('content'))
    if not apply:
        return 'unchanged' if desired == live.get('content') else 'planned'
    payload = {'content': desired}
    if markdown is not None:
        fid = ensure_upload(api, lesson['id'], markdown.encode(), state)
        live = api.request('course_lessons/' + lesson['id'])
        if source_signature(live) != source_signature(lesson):
            raise ValueError('La vidéo source a changé pendant le téléversement')
        payload['content'] = description(live.get('content'))
        managed = {json.loads(p.read_text())['id'] for p in (state / 'uploads').glob(lesson['id'] + '-*.json')}
        payload['attachments'] = [{'id': a['id']} for a in live.get('attachments', []) if a['id'] not in managed and a['id'] != fid] + [{'id': fid}]
    unchanged = payload['content'] == live.get('content')
    if 'attachments' in payload:
        unchanged = unchanged and {x['id'] for x in payload['attachments']} == {x['id'] for x in live.get('attachments', [])}
    if unchanged:
        return 'unchanged'
    backup = state / 'backups' / (lesson['id'] + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    atomic_json(backup, {'id': lesson['id'], 'content': live.get('content'), 'attachments': [{'id': a['id']} for a in live.get('attachments', [])]})
    api.request('course_lessons/' + lesson['id'], method='PATCH', body=payload)
    readback = api.request('course_lessons/' + lesson['id'])
    if readback.get('content') != payload['content']:
        raise ValueError('Le contenu relu sur Whop diffère du contenu envoyé')
    if 'attachments' in payload and {a['id'] for a in readback.get('attachments', [])} != {a['id'] for a in payload['attachments']}:
        raise ValueError('Les pièces jointes relues diffèrent des fichiers envoyés')
    return 'updated'


def slug(title):
    value = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:100] or 'masterclass'


def check_public_text(text, secrets):
    if any(secret and secret in text for secret in secrets):
        raise ValueError('Secret détecté dans un export')
    if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.|X-Amz-Signature=', text):
        raise ValueError('Jeton ou URL signée détecté dans un export')


def publish(config):
    env = dict(os.environ, BIZOS_GITHUB_TOKEN_FILE=config['github_token_file'], GIT_TERMINAL_PROMPT='0')
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout.strip()
    expected = 'https://github.com/' + config['github_repo'] + '.git'
    if git('remote', 'get-url', 'origin') != expected:
        raise ValueError('Dépôt Git distant inattendu')
    git('add', '--', 'transcriptions', 'catalogue.json', 'README.md')
    if git('diff', '--cached', '--name-only'):
        git('commit', '-m', 'Synchroniser les transcriptions BizOS Premium')
    helper = '!' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'scripts' / 'git_credential.py'))
    git('-c', 'credential.helper=', '-c', 'credential.helper=' + helper, 'push', 'origin', 'HEAD:main')
    if git('-c', 'credential.helper=', '-c', 'credential.helper=' + helper, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != git('rev-parse', 'HEAD'):
        raise ValueError('Vérification GitHub échouée')


def write_index(entries):
    # A failed fetch does not delete a previously published transcript.
    atomic_json(ROOT / 'catalogue.json', entries)
    completed = [e for e in entries if e.get('file')]
    lines = ['# BizOS Premium — Masterclasses', '', 'Transcriptions complètes des rediffusions de [BizOS Premium](https://whop.com/bizos/).', '',
             f'{len(completed)} transcriptions disponibles sur {len(entries)} séances répertoriées.', '',
             'Les transcriptions sont automatiques et peuvent contenir des erreurs, notamment sur les noms propres. Les horodatages permettent de revenir à la vidéo originale.', '',
             '| Collection | Masterclass | Source |', '| --- | --- | --- |']
    for e in entries:
        title = e['title'].replace('|', '\\|')
        link = f'[{title}]({e["file"]})' if e.get('file') else title + ' — transcription en attente'
        lines.append(f'| {e["course"]} | {link} | {e.get("source", "À récupérer")} |')
    lines += ['', '## Synchronisation', '', 'Le script local vérifie les rediffusions chaque semaine, ajoute les transcriptions disponibles dans les descriptions Whop et met à jour ce dépôt.', '',
              'Voir [le guide de maintenance](docs/maintenance.md) pour lancer une synchronisation, consulter les erreurs ou restaurer une description.', '',
              '## Sources techniques', '',
              '- [API Whop : descriptions des leçons](https://docs.whop.com/api-reference/course-lessons/update-course-lesson)',
              '- [Mux : sous-titres et transcriptions](https://www.mux.com/docs/guides/add-autogenerated-captions-and-use-transcripts)', '',
              'Les vidéos restent hébergées chez Whop. Aucun jeton, secret ni lien de lecture signé n’est publié ici.', '']
    (ROOT / 'README.md').write_text('\n'.join(lines))


def run(config, apply=False, do_publish=False):
    state = Path(config['state_dir'])
    cache = state / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    api = Whop(env_value(config['whop_env_file'], 'WHOP_API_KEY'))
    company = api.request('experiences/' + config['experience_id'])
    if company.get('company', {}).get('id') != config['company_id']:
        raise ValueError('Expérience Whop hors du compte autorisé')
    entries, errors = [], []
    old = {e['id']: e for e in json.loads((ROOT / 'catalogue.json').read_text())} if (ROOT / 'catalogue.json').exists() else {}
    for course in api.list('courses', experience_id=config['experience_id']):
        if course.get('visibility') != 'visible':
            continue
        details = api.request('courses/' + course['id'])
        for chapter in details['chapters']:
            for item in chapter['lessons']:
                lesson = api.request('course_lessons/' + item['id'])
                if lesson.get('visibility') != 'visible':
                    continue
                lid = lesson['id']
                entry = {'id': lid, 'title': lesson['title'].strip(), 'course': course['title'],
                         'whop_url': f'https://whop.com/bizos/{config["experience_id"]}/app/courses/{course["id"]}/lessons/{lid}/'}
                try:
                    cues, meta = acquire(lesson, cache)
                    entry.update(meta)
                    entry['file'] = old.get(lid, {}).get('file') or f'transcriptions/{slug(course["title"])}/{slug(lesson["title"])}--{lid}.md'
                    entry['segments'] = len(cues)
                    entry['last_timestamp_seconds'] = cues[-1]['end']
                    markdown = render_markdown(entry, cues)
                    check_public_text(markdown, [api.key, Path(config['github_token_file']).read_text().strip()])
                    result = sync_one(api, lesson, cues, meta['source'], state, apply, markdown=markdown,
                                      transcript_url='https://github.com/' + config['github_repo'] + '/blob/main/' + entry['file'])
                    path = ROOT / entry['file']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(markdown)
                    print(json.dumps({'id': lid, 'title': entry['title'], 'status': result, 'segments': len(cues)}, ensure_ascii=False), flush=True)
                except (RuntimeError, ValueError, KeyError) as exc:
                    entry = dict(old.get(lid, {}), **entry)
                    # Error strings intentionally omit raw responses, signed URLs and credentials.
                    reason = str(exc) if not isinstance(exc, KeyError) else 'Format de réponse inattendu'
                    errors.append({'id': lid, 'reason': reason})
                    print(json.dumps({'id': lid, 'status': 'pending', 'reason': reason}, ensure_ascii=False), flush=True)
                entries.append(entry)
    if not entries:
        raise ValueError('Inventaire vide : arrêt sans publication')
    write_index(entries)
    if do_publish:
        publish(config)
    report = {'finished_at': datetime.now(timezone.utc).isoformat(), 'lessons': len(entries), 'available': sum(bool(e.get('file')) for e in entries), 'apply': apply, 'published': do_publish, 'errors': errors}
    atomic_json(state / 'last-run.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.publish and not args.apply:
        parser.error('--publish nécessite --apply')
    config = json.loads(Path(args.config).read_text())
    os.umask(0o077)
    state = Path(config['state_dir'])
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'sync.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Une synchronisation est déjà en cours.', flush=True)
            return 0
        try:
            return run(config, args.apply, args.publish)
        except Exception as exc:
            atomic_json(state / 'last-failure.json', {'at': datetime.now(timezone.utc).isoformat(), 'error_type': type(exc).__name__})
            print('Échec de synchronisation : ' + type(exc).__name__, file=sys.stderr, flush=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
