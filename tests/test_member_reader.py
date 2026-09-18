import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.member_reader import export_reader
from scripts.sync import run


class MemberReaderTests(unittest.TestCase):
    def test_full_text_stays_in_server_bundle_and_not_in_public_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';cache.mkdir()
            (cache/'lesn_a.transcript.json').write_text(json.dumps({'cues':[{'start':0,'end':60,'speaker':'Alice','text':'Texte intégral.'}]}))
            digest=export_reader([{'id':'lesn_a','title':'Demo','file':'demo.md','course':'Septembre','source':'Fathom'}],cache,root)
            entries=json.loads((root/'reader/data/transcripts.json').read_text())
            self.assertIn('Alice : Texte intégral.',entries[0]['text'])
            self.assertEqual(len(digest),64)
            self.assertFalse((root/'reader/public').exists())

    def test_failed_reader_deploy_never_replaces_working_whop_links(self):
        class API:
            key='whop-test'
            def request(self,path,**kwargs):
                if path.startswith('experiences/'):
                    return {'company':{'id':'biz_test'},'is_public':False,'app':{'id':'app_reader'}}
                if path=='courses/cors_a':return {'chapters':[{'lessons':[{'id':'lesn_a'}]}]}
                if path=='course_lessons/lesn_a':return {'id':'lesn_a','title':'Demo','visibility':'visible','content':None}
                raise AssertionError(path)
            def list(self,*args,**kwargs):return [{'id':'cors_a','title':'Septembre','visibility':'visible'}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'token').write_text('github-test')
            config={'state_dir':str(root/'state'),'whop_env_file':'unused','company_id':'biz_test','experience_id':'exp_original','github_token_file':str(root/'token'),'github_repo':'owner/repo','member_reader':{'experience_id':'exp_reader','app_id':'app_reader'}}
            with patch('scripts.sync.ROOT',root),patch('scripts.sync.env_value',return_value='whop-test'),patch('scripts.sync.Whop',return_value=API()),patch('scripts.sync.acquire',return_value=([{'start':0,'end':60,'text':'Texte'}],{'source':'Fathom'})),patch('scripts.member_reader.export_reader',return_value='digest'),patch('scripts.member_reader.deploy_reader',side_effect=ValueError('deploy failed')) as deploy,patch('scripts.sync.sync_one',return_value='updated') as sync:
                with self.assertRaisesRegex(ValueError,'deploy failed'):run(config,apply=True)
                sync.assert_not_called()
                deploy.side_effect=None
                self.assertEqual(run(config,apply=True),0)
                self.assertTrue(sync.call_args.kwargs['members_only'])
                self.assertEqual(sync.call_args.kwargs['transcript_url'],'https://whop.com/bizos/exp_reader/app/lesn_a')


if __name__=='__main__':unittest.main()
