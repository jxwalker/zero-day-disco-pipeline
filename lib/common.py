"""Shared helpers for the suno-daily karaoke video pipeline."""
import json, os, re, subprocess, unicodedata, datetime

NON_LYRIC = {'end', 'instrumental', 'break', 'interlude', 'solo', 'drop', 'silence', 'fade out', 'outro instrumental'}


def section_kind(name):
    """Map a Suno section tag to a coarse kind used for styling/tags."""
    n = name.lower().strip()
    n = re.sub(r'[^a-z0-9 \-]', ' ', n)
    if n.split() and n.split()[0] == 'end':
        return 'end'
    if 'pre' in n and 'chorus' in n:
        return 'prechorus'
    if 'post' in n and 'chorus' in n:
        return 'postchorus'
    if 'chorus' in n or 'hook' in n or 'refrain' in n:
        return 'chorus'
    if 'verse' in n or 'rap' in n:
        return 'verse'
    if 'bridge' in n:
        return 'bridge'
    if 'intro' in n:
        return 'intro'
    if 'outro' in n or 'coda' in n:
        return 'outro'
    if any(k in n for k in NON_LYRIC):
        return 'instrumental'
    return 'other'


def tokens(text):
    """Display tokens: whitespace split, punctuation-only tokens glued to a neighbour."""
    raw = text.split()
    out = []
    for t in raw:
        if not norm(t) and out:
            out[-1] += ' ' + t
        elif out and not norm(out[-1]):
            out[-1] += ' ' + t
        else:
            out.append(t)
    return out


def norm(w):
    w = unicodedata.normalize('NFKD', w).lower()
    return re.sub(r'[^a-z0-9]', '', w)


def parse_lyrics(text):
    """Parse Suno-style lyrics with [Section] tags.
    Returns list of dicts: idx, section, section_occ, kind, line_no (1-based within section), text, tokens.
    Everything after an [End] tag is ignored; empty sections are dropped."""
    lines = []
    sec, kind, occ = 'Intro', 'intro', {}
    cur_occ = 1
    line_no = 0
    for raw in text.splitlines():
        l = raw.strip()
        if not l:
            continue
        m = re.match(r'^\[(.+?)\]\s*$', l)
        if m:
            name = m.group(1).split(':')[0].strip()
            k = section_kind(name)
            if k == 'end':
                break
            if k in ('other', 'instrumental') and line_no == 0 and kind not in ('other', 'instrumental'):
                continue        # a Suno meta tag right under a section header ([Bridge] [Spoken Word],
                                # [Final Chorus] [Key Change]) is a performance note, not a new section
            sec, kind = name, k
            occ[name] = occ.get(name, 0) + 1
            cur_occ = occ[name]
            line_no = 0
            continue
        if re.match(r'^\(.*\)$', l) and kind == 'instrumental':
            continue
        line_no += 1
        lines.append({'section': sec, 'section_occ': cur_occ, 'kind': kind, 'line_no': line_no,
                      'text': l, 'tokens': tokens(l)})
    for i, x in enumerate(lines):
        x['idx'] = i
    # section instance id (consecutive block of the same section occurrence)
    sid = -1; prev = None
    for x in lines:
        key = (x['section'], x['section_occ'])
        if key != prev:
            sid += 1; prev = key
        x['sid'] = sid
    return lines


def ffprobe_json(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def audio_duration(path):
    return float(ffprobe_json(path)['format']['duration'])


def mp3_tags(path):
    tags = ffprobe_json(path)['format'].get('tags', {})
    return {k.lower(): v for k, v in tags.items()}


def embedded_lyrics(path):
    t = mp3_tags(path)
    for k, v in t.items():
        if k.startswith('lyrics') or k in ('uslt', 'unsyncedlyrics'):
            return v
    return None


def day_date(day_dir, tags):
    d = tags.get('date')
    if not d:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(os.path.abspath(day_dir)))
        d = m.group(1) if m else datetime.date.today().isoformat()
    return datetime.date.fromisoformat(d)


def source_handles(stories_md):
    """@handles from stories.md: x.com/<handle>/status URLs plus explicit @mentions, first-seen order."""
    if not os.path.exists(stories_md):
        return []
    txt = open(stories_md, encoding='utf-8').read()
    found = []
    for m in re.finditer(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status|(?<![A-Za-z0-9_.])@([A-Za-z0-9_]{1,15})\b', txt):
        h = m.group(1) or m.group(2)
        if h.lower() in ('i', 'home', 'search', 'intent'):
            continue
        if h.lower() not in [f.lower() for f in found]:
            found.append(h)
    return found


def load_json(p, default=None):
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return default


def save_json(obj, p):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def merge_passes(passes, window=1.0):
    """Merge whisper passes into one reference word list without offering conflicting duplicates:
    passes are taken in order of size (most words first); a word from a later pass is only added when no
    word with the same spelling already sits within +-window seconds."""
    order = sorted(passes, key=lambda k: -len(passes[k]))
    merged = []
    for k in order:
        for w in passes[k]:
            n = norm(w['w'])
            if not n:
                continue
            if any(norm(x['w']) == n and abs(x['s'] - w['s']) <= window for x in merged):
                continue
            merged.append(w)
    merged.sort(key=lambda w: w['s'])
    return merged
