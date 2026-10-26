"""Tone step: pick the video's tone profile from the song (lyrics, style.txt, stories.md, optional tone.txt).

Profiles: 'edgy' (deadpan menace, the v5 prompts; default for the daily AI-news songs), 'playful' (slopcore cool with
warmth; the automatic pick for personal or happy songs) and 'joyful' (bright, pastel, wholesome-cute; tone.txt only).
 Daily folders (<YYYY-MM-DD>) whose stories carry news sources are always 'edgy' with no call,
so the daily path is unchanged. Anything else: `tone.txt` (first word = profile, rest = a note for the director) or a
short Opus call; a daily folder only leaves 'edgy' when Opus says the song is clearly personal (not news).
The chosen tone is kept in CURRENT for the planners and in <work>/tone.json."""
import datetime, json, os, re, time
import common_gv as G

PROFILES = ('edgy', 'playful', 'joyful')       # joyful only via tone.txt
AUTO = ('edgy', 'playful')
LOOK = {'edgy': None, 'playful': 'sunlit-portra', 'joyful': 'sunny-pastel'}          # None = the genre's slopcore look
CURRENT = {'tone': 'edgy', 'note': '', 'why': 'default'}
SCHEMA = {"type": "object", "properties": {
    "tone": {"type": "string", "enum": list(AUTO)},
    "personal": {"type": "boolean", "description": "true if the song is a personal/private song (a gift, a family member, love, a celebration), not AI news"},
    "reason": {"type": "string"}}, "required": ["tone", "personal", "reason"]}


def is_daily(day):
    try:
        datetime.date.fromisoformat(os.path.basename(os.path.normpath(day))[:10])
    except ValueError:
        return False
    tags = G.load_json(os.path.join(day, 'tags.json'), {}) or {}
    return not tags.get('special')


def _override(day):
    f = os.path.join(day, 'tone.txt')
    if not os.path.exists(f):
        return None
    txt = G.read(f).strip()
    m = re.match(r'\s*(?:tone\s*[=:]\s*)?([a-z]+)', txt, re.I)
    if m and m.group(1).lower() in PROFILES:
        return m.group(1).lower(), txt[m.end():].strip(' \n:-=')
    return None


def _heuristic(day):
    txt = (G.read(os.path.join(day, 'style.txt')) + ' ' + G.read(os.path.join(day, 'caption.txt'))).lower()
    happy = sum(w in txt for w in ('happy', 'joy', 'playful', 'cheeky', 'sweet', 'gift', 'love', 'birthday', 'celebrat',
                                   'wedding', 'bright sing-along', 'wholesome'))
    return 'playful' if happy >= 2 else 'edgy'


def pick(day, work):
    """Returns CURRENT (also saved to <work>/tone.json)."""
    daily = is_daily(day)
    res = None
    ov = _override(day)
    if ov:
        res = {'tone': ov[0], 'note': ov[1], 'why': 'tone.txt'}
    elif daily and G.credit_rows(day):
        res = {'tone': 'edgy', 'note': '', 'why': 'daily AI-news song'}
    else:
        cache = G.load_json(os.path.join(work, 'tone.json'))
        if cache and cache.get('why', '').startswith('opus'):
            res = cache
        else:
            res = _ask_opus(day, work, daily)
    CURRENT.clear()
    CURRENT.update(res)
    G.save_json(CURRENT, os.path.join(work, 'tone.json'))
    G.log(f"tone: {CURRENT['tone']} ({CURRENT['why']})")
    return CURRENT


def _ask_opus(day, work, daily):
    import slop_opus as SO
    od = os.path.join(work, 'opus')
    os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'tone_prompt.txt')
    open(pf, 'w').write(f"""Pick the tone profile for a music video of this song. Profiles:
- "edgy": deadpan menace, cool and ominous slopcore (for AI-news, tech, satire, dark or aggressive songs).
- "playful": slopcore cool with warmth: deadpan cheek, fun, affectionate, never menacing (happy, sweet, celebratory,
  personal or gift songs, love songs, family songs).
Also say whether the song is clearly personal (about a specific person, a gift, family, love, a celebration) rather
than news. Do not use any tools.

TITLE: {G.read(os.path.join(day, 'title.txt'))}
STYLE: {G.read(os.path.join(day, 'style.txt'))[:800]}
CAPTION: {G.read(os.path.join(day, 'caption.txt'))[:400]}
LYRICS:
{G.read(os.path.join(day, 'lyrics.txt'))[:4000]}
STORIES:
{G.read(os.path.join(day, 'stories.md'))[:2500]}
""")
    t0 = time.time()
    try:
        if os.environ.get('CINE_REAL_FAIL') == 'opus' or not os.path.exists(SO.CLAUDE):
            raise RuntimeError('opus unavailable')
        out, meta = SO.run_claude(pf, od, SCHEMA, 120, tools='', effort='low')
        tone = out.get('tone') if out.get('tone') in AUTO else 'edgy'
        if daily and tone != 'edgy' and not out.get('personal'):
            return {'tone': 'edgy', 'note': '', 'why': f"opus said {tone} but a daily song that is not personal stays edgy"}
        return {'tone': tone, 'note': '', 'why': f"opus ({round(time.time() - t0)} s): {str(out.get('reason'))[:160]}",
                'personal': out.get('personal'), 'cost_usd': meta.get('cost_usd')}
    except Exception as e:
        tone = 'edgy' if daily else _heuristic(day)
        return {'tone': tone, 'note': '', 'why': f"fallback ({type(e).__name__}): {'daily' if daily else 'style.txt words'}"}
