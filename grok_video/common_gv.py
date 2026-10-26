"""Shared helpers for the Grok-clip video pipeline (grok_video)."""
import json, os, re, subprocess, sys, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(TOOLS), 'lib')          # existing karaoke pipeline (used read-only)
sys.path.insert(0, LIB)
import common as C                                           # noqa: E402  (parse_lyrics, source_handles, ...)

GROK = os.environ.get('GROK_BIN', '/home/box/.grok/bin/grok')
PIP_REF = os.path.join(TOOLS, 'assets', 'pip_ref_9x16.png')

PIP_DESC = (
    "Pip (must stay exactly on-model to the reference image): a small, cute chibi robot in flat 2D vector cartoon style "
    "with thick dark-navy outlines. Round white helmet-shaped head with a large dark-navy rounded-rectangle face screen "
    "showing glowing cyan happy CLOSED ARC EYES (^ ^), pink blush ovals on the cheeks and an open cyan-outlined smile with "
    "a pink tongue. Two tall white bunny ears with pink inner ear, and a thin antenna with a small glowing yellow ball. "
    "Small white egg-shaped body with a clearly visible PINK HEART on the chest (never covered by props; any guitar is "
    "slung low at the hip or off to the side). Stubby white arms with round mitten hands. SHORT STUBBY white legs with "
    "round white feet, both legs and feet fully visible in frame (never long or thin legs). No clothing.")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(obj, p):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def read(p, default=''):
    try:
        return open(p, encoding='utf-8').read().strip()
    except FileNotFoundError:
        return default


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def probe_video(path):
    """(width, height, duration, has_video) of the first real video stream, or None if unreadable."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    j = json.loads(r.stdout)
    vs = [s for s in j.get('streams', []) if s.get('codec_type') == 'video'
          and not s.get('disposition', {}).get('attached_pic')]
    if not vs:
        return None
    return int(vs[0]['width']), int(vs[0]['height']), float(j['format'].get('duration', 0))


def genre_of(day):
    tags = load_json(os.path.join(day, 'tags.json'), {}) or {}
    return (tags.get('genre') or '').strip(), read(os.path.join(day, 'style.txt'))


def genre_family(genre, style):
    g = f"{genre} {style}".lower()
    if any(k in g for k in ('big-room', 'big room', 'edm', 'house', 'techno', 'trance', 'dance-floor', 'dance floor',
                            'electro', 'dubstep', 'drum and bass', 'dnb', 'rave')):
        return 'bigroom'
    if any(k in g for k in ('punk', 'rock', 'metal', 'grunge', 'emo', 'hardcore', 'garage', 'shoegaze')):
        return 'rock'
    if 'pop' in g or 'k-pop' in g or 'disco' in g or 'synth' in g:
        return 'pop'
    return 'other'


GENRE_RULES = {
    'rock': "Rock / pop-punk energy: electric guitars (always slung low or to the side), drum kits, amp stacks, mosh pits, "
            "stage dives, crowd surfing, arenas and stadiums, sweaty clubs, garages, skate parks, pyrotechnics, smoke, "
            "spotlights.",
    'pop': "Bright, glossy pop music video: candy colours, pastel sets, glitter, confetti cannons, neon signs, mirror balls, "
           "choreographed dance moves, glossy studio lighting.",
    'bigroom': "Big-room festival energy: huge festival main stage, lasers, CO2 jets, pyro, LED walls, DJ decks, crowds with "
               "hands up, confetti, night sky, drops.",
    'other': "Energetic music-video staging that fits the song's mood: stages, crowds, dramatic lighting, motion.",
}


def story_list(day):
    """Stories as [{'idx':1.., 'text': short tag text, 'section':..., 'lines':[a,b], 'detail': stories.md paragraph,
    'handles': [...]}] in tags.json story_tags order; detail/handles matched from stories.md sections by order."""
    tags = load_json(os.path.join(day, 'tags.json'), {}) or {}
    st = tags.get('story_tags') or []
    md = read(os.path.join(day, 'stories.md'))
    secs = [s for s in re.split(r'\n(?=## )', md) if s.startswith('## ')]
    out = []
    n = max(len(st), len(secs))
    for i in range(n):
        t = st[i] if i < len(st) else {}
        sec = secs[i] if i < len(secs) else ''
        head = sec.split('\n', 1)[0].lstrip('# ').strip()
        head = re.sub(r'^\d+\.\s*', '', head)
        body = sec.split('\n', 1)[1].strip() if '\n' in sec else ''
        handles = []
        for m in re.finditer(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status|(?<![A-Za-z0-9_.])@([A-Za-z0-9_]{1,15})\b', sec):
            h = m.group(1) or m.group(2)
            if h.lower() not in [x.lower() for x in handles]:
                handles.append(h)
        handles = t.get('handles') or ([t['handle']] if t.get('handle') else handles)
        out.append({'idx': i + 1, 'text': t.get('text') or head, 'section': t.get('section'), 'lines': t.get('lines'),
                    'occurrence': t.get('occurrence'), 'detail': (head + '. ' + body)[:900], 'handles': handles})
    return out


def credit_card(day):
    """(rows, footer) for the end card. `credits.txt` (one row per line, up to 6) replaces the rows and drops the
    "SOURCES ON X" footer; with no source rows at all (non-news songs) the footer is dropped too."""
    f = os.path.join(day, 'credits.txt')
    if os.path.exists(f):
        return [ln.strip() for ln in read(f).splitlines() if ln.strip()][:6], None
    rows = [h for h, _ in credit_rows(day)]
    return rows, ('@jxwalker' if rows else None)


def credit_rows(day):
    """End-card rows [(handle_text, story_text)] (tags.json 'sources'/'credits' override, else stories.md by story)."""
    tags = load_json(os.path.join(day, 'tags.json'), {}) or {}
    explicit = tags.get('sources') or tags.get('credits')
    if explicit:
        return [('@' + h.lstrip('@'), '') for h in explicit]
    rows = []
    for s in story_list(day):
        if s['handles']:
            rows.append((' · '.join('@' + h.lstrip('@') for h in s['handles']), s['text']))
    if not rows:
        rows = [('@' + h, '') for h in C.source_handles(os.path.join(day, 'stories.md'))]
    return rows


# --audio override (e.g. a re-edited song file for a special folder); None = <day>/audio.mp3, the daily default
AUDIO_OVERRIDE = None


def audio_path(day):
    return AUDIO_OVERRIDE or os.path.join(day, 'audio.mp3')


def lead_noun(day):
    """'man' when the lead vocal is male (headline.json lead_gender, else style.txt 'male lead'/'male vocal'), else 'woman'."""
    try:
        g = ((load_json(os.path.join(day, 'headline.json'), {}) or {}).get('lead_gender') or '').lower()
        if g in ('male', 'man'): return 'man'
        if g in ('female', 'woman'): return 'woman'
        st = read(os.path.join(day, 'style.txt')).lower()
        if re.search(r'(?<!fe)male (lead|vocal|singer)', st): return 'man'
    except Exception:
        pass
    return 'woman'
