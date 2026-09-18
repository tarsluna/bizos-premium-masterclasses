import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync import Whop, acquire, ensure_upload, fetch_fathom, fetch_mux, sync_one


class SyncTests(unittest.TestCase):
    def test_pagination_visits_every_page(self):
        api = Whop('test')
        with patch.object(api, 'request', side_effect=[{'data': [{'id': 'a'}], 'page_info': {'has_next_page': True, 'end_cursor': 'next'}}, {'data': [{'id': 'b'}], 'page_info': {'has_next_page': False}}]) as req:
            self.assertEqual([x['id'] for x in api.list('courses', experience_id='exp')], ['a', 'b'])
            self.assertEqual(req.call_args.kwargs['params']['after'], 'next')

    def test_fathom_only_fetches_supplied_share_and_its_transcript(self):
        page = '<div data-page="{&quot;props&quot;:{&quot;copyTranscriptUrl&quot;:&quot;https://fathom.video/calls/12/copy_transcript?token=abc&quot;,&quot;duration&quot;:70,&quot;call&quot;:{&quot;started_at&quot;:&quot;2026-09-17&quot;}}}"></div>'
        with patch('scripts.sync.curl_text', side_effect=[page, json.dumps({'plain_text': '0:00 - Alice\n  Bonjour.\n\n1:09 - Bob\n  Fin.'})]):
            cues, meta = fetch_fathom('https://fathom.video/share/abc')
            self.assertEqual(len(cues), 2)
            self.assertEqual(meta['source'], 'Fathom')

    def test_new_fathom_link_replaces_cached_whop_captions(self):
        lesson = {'id': 'lesson', 'content': None, 'video_asset': {'id': 'video', 'duration_seconds': 60}}
        whop = ([{'start': 0, 'end': 60, 'text': 'Sous-titres'}], {'source': 'Whop', 'duration_seconds': 60})
        fathom = ([{'start': 0, 'end': 60, 'text': 'Original Fathom', 'speaker': 'Alice'}], {'source': 'Fathom', 'duration_seconds': 60})
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.sync.fetch_mux', return_value=whop) as mux, patch('scripts.sync.fetch_fathom', return_value=fathom) as ft:
            self.assertEqual(acquire(lesson, Path(tmp)), whop)
            self.assertEqual(acquire(lesson, Path(tmp)), whop)
            mux.assert_called_once()
            lesson['content'] = 'https://fathom.video/share/verified'
            self.assertEqual(acquire(lesson, Path(tmp)), fathom)
            self.assertEqual(acquire(lesson, Path(tmp)), fathom)
            ft.assert_called_once_with('https://fathom.video/share/verified')

    def test_mux_fetches_every_segment_and_preserves_final_words(self):
        responses = {
            'https://stream.mux.com/video.m3u8': '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="fr",URI="sub/fr.m3u8"',
            'https://stream.mux.com/sub/fr.m3u8': '#EXTM3U\none.vtt\ntwo.vtt\n#EXT-X-ENDLIST',
            'https://stream.mux.com/sub/one.vtt': 'WEBVTT\n\n00:00.000 --> 00:30.000\nDébut\n',
            'https://stream.mux.com/sub/two.vtt': 'WEBVTT\n\n00:30.000 --> 01:00.000\nDerniers mots\n',
        }
        lesson = {'video_asset': {'status': 'ready', 'playback_id': 'video', 'duration_seconds': 60}}
        with patch('scripts.sync.http_text', side_effect=lambda url: responses[url]):
            cues, meta = fetch_mux(lesson, None)
        self.assertEqual([x['text'] for x in cues], ['Début', 'Derniers mots'])
        self.assertEqual(cues[-1]['end'], 60)
        self.assertEqual(meta['duration_seconds'], 60)

    def test_concurrent_video_change_refuses_description_write(self):
        api = Whop('test')
        original = {'id': 'lesson', 'video_asset': {'id': 'original'}}
        changed = {'id': 'lesson', 'video_asset': {'id': 'replacement'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(api, 'request', return_value=changed) as request:
            with self.assertRaisesRegex(ValueError, 'source a changé'):
                sync_one(api, original, [{'start': 0, 'end': 60, 'text': 'Ancien'}], 'Whop', Path(tmp), True)
            self.assertEqual(request.call_count, 1)

    def test_sync_readback_and_backup_and_dry_run(self):
        class API:
            def __init__(self): self.value = {'id': 'lesn_a', 'title': 'Demo', 'content': None}; self.patches = 0
            def request(self, path, method='GET', body=None):
                if method == 'PATCH': self.value.update(body); self.patches += 1
                return dict(self.value)
        cues = [{'start': 0, 'end': 60, 'text': 'Bonjour.'}]
        with tempfile.TemporaryDirectory() as tmp:
            api = API(); state = Path(tmp)
            self.assertEqual(sync_one(api, api.value, cues, 'Whop', state, False), 'planned')
            self.assertEqual(api.patches, 0)
            self.assertEqual(sync_one(api, api.value, cues, 'Whop', state, True), 'updated')
            self.assertEqual(api.patches, 1)
            self.assertEqual(sync_one(api, api.value, cues, 'Whop', state, True), 'unchanged')
            self.assertEqual(api.patches, 1)
            self.assertEqual(len(list((state / 'backups').glob('*.json'))), 1)

    def test_large_transcript_attached_in_full_without_removing_video_attachment(self):
        class API:
            def __init__(self): self.value = {'id': 'lesn_a', 'content': None, 'attachments': [{'id': 'file_video'}]}
            def request(self, path, method='GET', body=None):
                if method == 'PATCH': self.value.update(body)
                return dict(self.value)
        api = API()
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.sync.ensure_upload', return_value='file_transcript') as upload:
            result = sync_one(api, api.value, [{'start': 0, 'end': 60, 'text': 'x' * 70000}], 'Whop', Path(tmp), True,
                              markdown='complete markdown', transcript_url='https://github.com/a/b/file.md')
            self.assertEqual(result, 'updated')
            self.assertLess(len(api.value['content']), 65000)
            self.assertEqual(api.value['attachments'], [{'id': 'file_video'}, {'id': 'file_transcript'}])
            self.assertEqual(upload.call_args.args[2], b'complete markdown')

    def test_members_reader_removes_only_managed_downloads_and_never_uploads(self):
        class API:
            def __init__(self): self.value={'id':'lesn_a','content':None,'attachments':[{'id':'file_video'},{'id':'file_old_transcript'}]}
            def request(self,path,method='GET',body=None):
                if method=='PATCH': self.value.update(body)
                return dict(self.value)
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.sync.ensure_upload') as upload:
            state=Path(tmp);(state/'uploads').mkdir();(state/'uploads'/'lesn_a-old.json').write_text(json.dumps({'id':'file_old_transcript'}))
            api=API()
            result=sync_one(api,api.value,[{'start':0,'end':60,'text':'Private text'}],'Fathom',state,True,
                markdown='Private text',transcript_url='https://whop.com/bizos/exp_reader/app/lesn_a',members_only=True)
            self.assertEqual(result,'updated');upload.assert_not_called()
            self.assertEqual(api.value['attachments'],[{'id':'file_video'}])
            self.assertIn('Lire et copier',api.value['content'])
            self.assertNotIn('Private text',api.value['content'])
            self.assertNotIn('Markdown intégral',api.value['content'])
            self.assertEqual(sync_one(api,api.value,[],'Fathom',state,True,transcript_url='https://whop.com/bizos/exp_reader/app/lesn_a',members_only=True),'unchanged')

    def test_upload_is_verified_byte_for_byte_and_reused_without_duplicate(self):
        class API:
            def __init__(self):self.posts=0
            def request(self,path,method='GET',body=None):
                if method=='POST':
                    self.posts+=1
                    return {'id':'file_demo','upload_url':'https://upload.example/test','upload_headers':{}}
                return {'id':'file_demo','upload_status':'ready','url':'https://download.example/test'}
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.sync.urllib.request.urlopen',return_value=Response()),patch('scripts.sync.http_text',return_value='Tout le texte'):
            api=API();state=Path(tmp)
            self.assertEqual(ensure_upload(api,'lesn_a',b'Tout le texte',state),'file_demo')
            self.assertEqual(ensure_upload(api,'lesn_a',b'Tout le texte',state),'file_demo')
            self.assertEqual(api.posts,1)
            with self.assertRaisesRegex(ValueError,'diffère'):
                ensure_upload(api,'lesn_b',b'Texte tronque',state)


if __name__ == '__main__': unittest.main()
