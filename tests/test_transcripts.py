import json
import unittest

from scripts.transcripts import parse_vtt, merge_cues, render_markdown, merge_description, from_fathom, parse_fathom_text, validate_transcript, group_cues


class TranscriptTests(unittest.TestCase):
    def test_vtt_preserves_text_and_absolute_time(self):
        cues = parse_vtt('WEBVTT\n\n12\n01:03:02.100 --> 01:03:04.000\n<v Alice>Bonjour &amp; bienvenue\nà tous.</v>\n')
        self.assertEqual(cues, [{'start': 3782.1, 'end': 3784.0, 'text': 'Bonjour & bienvenue à tous.'}])

    def test_segment_boundary_duplicates_removed_without_losing_repetitions(self):
        a = {'start': 28.0, 'end': 32.0, 'text': 'Oui.'}
        b = {'start': 33.0, 'end': 34.0, 'text': 'Oui.'}
        self.assertEqual(merge_cues([[a], [a, b]]), [a, b])

    def test_description_preserves_links_and_user_notes_on_both_sides(self):
        original = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Ressource', 'marks': [{'type': 'link', 'attrs': {'href': 'https://example.org'}}]}]}]}
        cues = [{'start': 1.0, 'end': 4.0, 'text': 'Bonjour.'}]
        once = merge_description(json.dumps(original), cues, 'Fathom')
        self.assertEqual(json.loads(once)['content'][0], original['content'][0])
        self.assertEqual(merge_description(once, cues, 'Fathom'), once)
        changed = json.loads(once)
        note = {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Note ajoutée après'}]}
        changed['content'].append(note)
        again = json.loads(merge_description(json.dumps(changed), cues, 'Fathom'))
        self.assertEqual(again['content'][-1], note)

    def test_unclosed_managed_block_is_rejected(self):
        doc = {'type': 'doc', 'content': [{'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': 'Transcription intégrale'}]}]}
        with self.assertRaises(ValueError):
            merge_description(json.dumps(doc), [{'start': 0, 'end': 1, 'text': 'bonjour'}], 'Whop')

    def test_markdown_original_is_preserved(self):
        result = merge_description('## Ressources\n\n[Support](https://example.org)', [{'start': 0, 'end': 1, 'text': 'Salut'}], 'Whop')
        self.assertTrue(result.startswith('## Ressources\n\n[Support](https://example.org)'))
        self.assertEqual(merge_description(result, [{'start': 0, 'end': 1, 'text': 'Salut'}], 'Whop'), result)

    def test_markdown_escapes_markup_without_changing_spoken_text(self):
        output = render_markdown({'title': 'Test', 'whop_url': 'https://whop.com/bizos/', 'source': 'Fathom'}, [{'start': 1, 'end': 3, 'speaker': 'Alice', 'text': '<script>texte</script> [x](https://example.org)'}])
        self.assertNotIn('<script>', output)
        self.assertIn('00:00:01', output)
        self.assertIn('Alice', output)

    def test_fathom_does_not_export_invitee_email_metadata(self):
        cues = from_fathom([{'timestamp': '00:01:03', 'text': 'Bonjour.', 'speaker': {'display_name': 'Alice', 'matched_calendar_invitee_email': 'private@example.org'}}])
        self.assertEqual(cues[0]['start'], 63)
        self.assertNotIn('private@example.org', json.dumps(cues))

    def test_empty_and_truncated_transcripts_fail(self):
        with self.assertRaises(ValueError): validate_transcript([], 3600)
        with self.assertRaises(ValueError): validate_transcript([{'start': 0, 'end': 2, 'text': 'Bonjour.'}], 3600)
        validate_transcript([{'start': 0, 'end': 3599, 'text': 'Bonjour.'}], 3600)

    def test_fathom_export_retains_all_paragraphs_and_speakers(self):
        text = 'Titre\n---\n\n0:00 - Alice\n  Bonjour.\n  Suite.\n\n1:00:03 - Bob\n  Fin.'
        cues = parse_fathom_text(text)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]['text'], 'Bonjour.\nSuite.')
        self.assertEqual(cues[1]['speaker'], 'Bob')
        self.assertEqual(cues[1]['start'], 3603)

    def test_grouping_does_not_drop_any_spoken_text(self):
        cues = [{'start': i, 'end': i+1, 'text': str(i)} for i in range(100)]
        grouped = group_cues(cues)
        self.assertEqual(' '.join(c['text'] for c in grouped), ' '.join(c['text'] for c in cues))
        self.assertEqual(grouped[-1]['end'], 100)

    def test_link_description_is_clickable_idempotent_and_preserves_original(self):
        result = merge_description(None, [], 'Fathom', 'https://github.com/a/b/blob/main/file.md')
        self.assertIn('transcription complète', result)
        doc = json.loads(result)
        links = [mark['attrs']['href'] for n in doc['content'] for t in n.get('content', []) for mark in t.get('marks', []) if mark['type'] == 'link']
        self.assertEqual(links, ['https://github.com/a/b/blob/main/file.md'])
        self.assertEqual(result, merge_description(result, [], 'Fathom', links[0]))


if __name__ == '__main__':
    unittest.main()
