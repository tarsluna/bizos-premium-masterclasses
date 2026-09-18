"""Lossless transcript conversion and preservation of existing Whop descriptions."""
import copy
import html
import json
import re

HEADING = 'Transcription intégrale'
END = 'Fin de la transcription intégrale.'


def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))


def stamp(value):
    n = int(value)
    return f'{n // 3600:02}:{n // 60 % 60:02}:{n % 60:02}'


def parse_vtt(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n')):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            match = re.match(r'([\d:.]+)\s+-->\s+([\d:.]+)', line)
            if match:
                value = html.unescape(re.sub(r'<[^>]*>', '', ' '.join(lines[i + 1:]))).strip()
                if value:
                    cues.append({'start': seconds(match[1]), 'end': seconds(match[2]), 'text': value})
                break
    return cues


def merge_cues(groups):
    unique = {}
    for group in groups:
        for cue in group:
            unique[(cue['start'], cue['end'], cue['text'])] = cue
    return sorted(unique.values(), key=lambda c: (c['start'], c['end']))


def group_cues(cues, period=30):
    result = []
    for cue in cues:
        if result and cue.get('speaker') == result[-1].get('speaker') and cue['start'] - result[-1]['start'] < period:
            result[-1]['text'] += ' ' + cue['text']
            result[-1]['end'] = max(result[-1]['end'], cue['end'])
        else:
            result.append(dict(cue))
    return result


def from_fathom(transcript):
    cues = []
    for item in transcript:
        if not item.get('text', '').strip():
            continue
        t = seconds(item['timestamp'])
        cues.append({'start': t, 'end': t, 'text': item['text'].strip(),
                     'speaker': (item.get('speaker') or {}).get('display_name', '')})
    for a, b in zip(cues, cues[1:]):
        a['end'] = b['start']
    return cues


def parse_fathom_text(text):
    matches = list(re.finditer(r'^(\d+:\d{2}(?::\d{2})?) - (.+)\r?$', text, re.M))
    items = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spoken = '\n'.join(line.strip() for line in text[match.end():end].strip().splitlines())
        items.append({'timestamp': match[1], 'speaker': {'display_name': match[2].strip()}, 'text': spoken})
    return from_fathom(items)


def validate_transcript(cues, duration=None):
    if not cues:
        raise ValueError('Transcription absente')
    if any(not c['text'] or c['start'] < 0 or c['end'] < c['start'] for c in cues):
        raise ValueError('Repères de transcription invalides')
    if any(a['start'] > b['start'] for a, b in zip(cues, cues[1:])):
        raise ValueError('Transcription hors ordre')
    if duration and cues[-1]['end'] < duration - max(120, duration * .05):
        raise ValueError('Transcription potentiellement tronquée')


def md_escape(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r'([\\`*\[\]_#])', r'\\\1', value)


def cue_line(cue, markdown=False):
    text = cue['text']
    speaker = cue.get('speaker')
    if speaker:
        text = speaker + ' : ' + text
    if markdown:
        return f'**[{stamp(cue["start"])}]** {md_escape(text)}'
    return f'[{stamp(cue["start"])}] {text}'


def render_markdown(meta, cues):
    lines = ['# ' + md_escape(meta['title']), '', '[Voir la rediffusion sur Whop](' + meta['whop_url'] + ')', '']
    for key, label in [('course', 'Collection'), ('recorded_at', 'Date de la séance'), ('source', 'Source de la transcription')]:
        if meta.get(key):
            lines += [f'- {label} : {md_escape(meta[key])}']
    lines += ['', '> Transcription automatique complète, susceptible de contenir des erreurs de reconnaissance.', '', '## ' + HEADING, '']
    lines += [cue_line(c, True) + '\n' for c in group_cues(cues)]
    return '\n'.join(lines).rstrip() + '\n'


def node_text(node):
    return node.get('text', '') + ''.join(node_text(c) for c in node.get('content', []))


def text_node(text, kind='paragraph'):
    node = {'type': kind, 'content': [{'type': 'text', 'text': text}]}
    if kind == 'heading':
        node['attrs'] = {'level': 2}
    return node


def merge_description(original, cues, source, transcript_url=None):
    """Replace only our delimited section; retain every other node verbatim."""
    note = f'Transcription automatique complète · Source : {source}. Des erreurs de reconnaissance peuvent subsister.'
    if not original:
        doc = {'type': 'doc', 'content': []}
    else:
        try:
            doc = json.loads(original)
        except (ValueError, TypeError):
            doc = None
    if not isinstance(doc, dict) or doc.get('type') != 'doc':
        start, end = '\n\n## ' + HEADING + '\n', '\n\n' + END
        link = f'\n\n[Lire la transcription complète]({transcript_url})\n\nLe fichier Markdown intégral est également joint sous cette vidéo.' if transcript_url else ''
        block = start + '\n' + note + link + '\n\n' + '\n\n'.join(cue_line(c, True) for c in group_cues(cues)) + end
        value = original or ''
        if start in value:
            a = value.index(start)
            if end not in value[a:]:
                raise ValueError('Bloc de transcription incomplet : intervention nécessaire')
            b = value.index(end, a) + len(end)
            return value[:a] + block + value[b:]
        return value + block
    doc = copy.deepcopy(doc)
    nodes = doc.get('content', [])
    starts = [i for i, n in enumerate(nodes) if n.get('type') == 'heading' and node_text(n) == HEADING]
    new = [text_node(HEADING, 'heading'), text_node(note)]
    if transcript_url:
        new += [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Lire la transcription complète', 'marks': [{'type': 'link', 'attrs': {'href': transcript_url, 'target': '_blank', 'rel': 'noopener noreferrer'}}]}]}, text_node('Le fichier Markdown intégral est également joint sous cette vidéo.')]
    new += [text_node(cue_line(c)) for c in group_cues(cues)] + [text_node(END)]
    if starts:
        if len(starts) != 1:
            raise ValueError('Plusieurs blocs de transcription')
        a = starts[0]
        ends = [i for i in range(a + 1, len(nodes)) if node_text(nodes[i]) == END]
        if len(ends) != 1:
            raise ValueError('Bloc de transcription incomplet : intervention nécessaire')
        nodes = nodes[:a] + new + nodes[ends[0] + 1:]
    else:
        nodes = nodes + new
    doc['content'] = nodes
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
