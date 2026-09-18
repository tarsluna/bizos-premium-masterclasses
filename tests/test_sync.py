import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync import Whop, fetch_fathom, sync_one


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


if __name__ == '__main__': unittest.main()
