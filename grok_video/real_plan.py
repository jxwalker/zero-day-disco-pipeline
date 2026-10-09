"""cine-real style: photoreal looks, the lyric/beat cut timeline, and the one-call shot planner.
See README "cine-real (photoreal) style"."""
import json, math, os, random, re
import common_gv as G
from plan_gen import run_grok_text, _extract_json

PLANNER_VERSION = 'real-3'      # real-3: planned from lyrics.txt (before the word timings)      # bump to force a re-plan of cached plans

# One bold look per song. 'prompt' is appended to every image prompt; the rest drives the local grade and the type.
REAL_LOOKS = {
    'neon-accent': {
        'label': 'cold desaturated night with one hot accent colour',
        'prompt': ("Photoreal cinematic film still, vertical 9:16, 35mm anamorphic lens, shot on Kodak Vision3 500T with "
                   "halation and fine grain, cold desaturated steel-blue and graphite palette with ONE hot magenta-red "
                   "accent colour, hard motivated light (strobes, lasers, sodium and fluorescent practicals), haze, crushed "
                   "blacks, slightly off-level handheld framing."),
        'accent': (255, 31, 90), 'accent_hue': 345, 'accent_name': 'magenta-red', 'recolour': {'amber': 'magenta-red'}, 'sat': 0.32, 'tint': (-6, 0, 10), 'contrast': 1.12,
        'leak': (255, 40, 110), 'grain': 7, 'genres': ('edm',),
        'worlds': ['a packed sweaty warehouse rave', 'a massive open-air festival at night over a city skyline',
                   'planetary or cosmic in scale'],
        'cameo': 'on the edge of a DJ mixer after the show, haze and a single magenta-red light behind it.',
    },
    'candy-pop': {
        'label': 'glossy candy-saturated 35mm pop music video',
        'prompt': ("Photoreal glossy pop music-video film still, vertical 9:16, shot on 35mm Kodak Ektachrome with fine "
                   "grain and soft halation, candy-saturated palette of bubblegum pink, aqua cyan and lemon yellow against "
                   "clean whites, hard direct flash and coloured gel light, glossy reflective surfaces, slightly off-level "
                   "handheld framing."),
        'accent': (255, 70, 170), 'accent_hue': None, 'accent_name': 'bubblegum pink (with aqua cyan)', 'sat': 1.18,
        'tint': (6, -2, 6), 'contrast': 1.06, 'crush': -0.02, 'vignette': 0.14, 'leak': (255, 120, 200), 'grain': 6,
        'genres': ('pop-video',),
        'worlds': ['a glossy candy-coloured pop video set: giant inflatable props, a pastel staircase, matching dancers',
                   'a sunlit city street and rooftops turned into a flash-mob dance number at golden hour, balloons and a '
                   'marching band', 'a dreamlike pop finale: a pink sky, a disco-ball moon, floating cars and swimming pools'],
        'cameo': 'on a glossy pink stage riser after the show, confetti on the floor and a soft cyan light behind it.',
    },
    'vhs': {
        'label': '1990s VHS camcorder, golden hour',
        'prompt': ("Photoreal 1990s VHS camcorder home-video frame, vertical 9:16, golden-hour sun, warm faded colours, "
                   "soft focus, slight chroma bleed, hard low sun flare, candid handheld framing."),
        'accent': (255, 196, 64), 'accent_hue': None, 'accent_name': 'golden yellow', 'sat': 0.75, 'tint': (10, 4, -8), 'contrast': 1.04,
        'leak': (255, 150, 60), 'grain': 9, 'vhs': True, 'genres': ('rock',),
        'worlds': ['a sweaty packed club gig', 'a stadium at golden hour with lighters in the air',
                   'an endless desert highway under a burning sunset'],
        'cameo': 'on top of a guitar amp after the show, golden light and dust in the air.',
    },
    '35mm': {
        'label': '35mm film stock with grain and direct flash',
        'prompt': ("Photoreal 35mm film photograph, vertical 9:16, shot on Kodak Portra 400, direct on-camera flash or hard "
                   "window light, deep shadows, visible film grain, slight halation, editorial music-video still."),
        'accent': (255, 214, 0), 'accent_hue': None, 'accent_name': 'sunflower yellow', 'sat': 0.9, 'tint': (6, 2, -4), 'contrast': 1.08,
        'leak': (255, 120, 40), 'grain': 10, 'genres': ('standard',),
        'worlds': ['a packed club', 'a huge open-air concert at sunset', 'a surreal dreamlike landscape'],
        'cameo': 'on a monitor speaker after the show, warm flash light.',
    },
    'xerox': {
        'label': 'high-contrast black-and-white 16mm with one acid accent',
        'prompt': ("Photoreal high-contrast black-and-white 16mm film frame on Kodak Tri-X, vertical 9:16, hard flash light, heavy grain, "
                   "punk zine energy, with ONE acid-yellow accent object."),
        'accent': (230, 255, 0), 'accent_hue': 65, 'accent_name': 'acid yellow', 'recolour': {'amber': 'acid-yellow', 'red': 'acid-yellow'}, 'sat': 0.0, 'tint': (0, 0, 0), 'contrast': 1.25,
        'leak': (230, 255, 60), 'grain': 13, 'genres': ('punk',),
        'worlds': ['a crammed DIY basement show', 'a skatepark at dusk full of kids', 'a rooftop riot of smoke and confetti'],
        'cameo': 'on a beaten-up skateboard after the show, flash light, acid-yellow tape on the board.',
    },
}
REAL_ALIASES = {'auto': None}
REAL_CHOICES = ['auto'] + list(REAL_LOOKS)


def pick_real_look(genre_look, override='auto'):
    if override and override != 'auto':
        return override, 'set on the command line'
    for k, v in REAL_LOOKS.items():
        if genre_look in v['genres']:
            return k, f'genre look {genre_look} -> {k}'
    return 'neon-accent', f'default for {genre_look}'


# ------------------------------------------------------------------------------------------------ timeline
def line_id(ln):
    return f"{ln['section']}#{ln['section_occ']}:{ln['line_no']}"


def build_timeline(L, beats, dur, seed, credits_len=2.5, cameo_len=1.5):
    """Segments (hook / sung line / drop / outro / cameo / credits) and cuts inside them. Cuts land on word onsets and
    on beats (about half each), average about 1.2 s, bursts in choruses and drops, longer holds on punchlines."""
    rnd = random.Random(seed)
    B = sorted(b for b in beats['beats'] if 0 < b < dur)
    bp = beats.get('beat_period') or 0.45
    credits_start = round(dur - credits_len, 3)
    cameo_start = round(credits_start - cameo_len, 3)
    lines = [ln for ln in L if ln.get('words')]
    segs = []
    first = lines[0]['words'][0][1] if lines else cameo_start
    segs.append({'id': 'hook', 'kind': 'hook', 't0': 0.0, 't1': max(0.8, first - 0.04)})
    for i, ln in enumerate(lines):
        a = ln['words'][0][1] - 0.04
        nxt = lines[i + 1]['words'][0][1] - 0.04 if i + 1 < len(lines) else cameo_start
        end = ln['words'][-1][2]
        b = nxt
        if nxt - end > 2.5:                       # instrumental gap after this line: a drop / break segment
            b = min(nxt, end + 0.45)
            bb = [x for x in B if end + 0.15 <= x <= end + 1.2]
            if bb:
                b = bb[0]
        stories_last = ln['line_no'] in (4, 8)
        segs.append({'id': line_id(ln), 'kind': ln['kind'], 't0': round(max(a, segs[-1]['t1']), 3), 't1': round(min(b, cameo_start), 3),
                     'line': ln, 'punch': stories_last or ln['kind'] in ('outro',)})
        if b < nxt - 0.5:
            k = sum(1 for s in segs if s['kind'] == 'drop') + 1
            kind = 'drop' if i + 1 < len(lines) else 'outro_tail'
            segs.append({'id': f'{kind}{k}', 'kind': kind, 't0': round(b, 3), 't1': round(min(nxt, cameo_start), 3)})
    if segs[-1]['t1'] < cameo_start - 0.3:
        segs.append({'id': 'outro_tail', 'kind': 'outro_tail', 't0': segs[-1]['t1'], 't1': cameo_start})
    segs = [s for s in segs if s['t1'] - s['t0'] > 0.2]
    segs.append({'id': 'cameo', 'kind': 'cameo', 't0': cameo_start, 't1': credits_start})
    segs.append({'id': 'credits', 'kind': 'credits', 't0': credits_start, 't1': round(dur, 3)})

    onsets = sorted(w[1] - 0.03 for ln in lines for w in ln['words'])
    cuts = []
    n_beat = n_on = 0
    for s in segs:
        a, b = s['t0'], s['t1']
        if s['kind'] in ('cameo', 'credits'):
            cuts.append({'t0': a, 't1': b, 'seg': s['id'], 'on': 'onset'}); continue
        kind = s['kind']
        if kind in ('chorus', 'drop', 'hook'):
            lo, hi = 0.42, 1.3
        else:
            lo, hi = 0.55, 1.7
        cand_b = [x for x in B if a + 0.3 < x < b - 0.3]
        cand_o = [x for x in onsets if a + 0.3 < x < b - 0.3]
        if kind in ('drop', 'hook'):     # instrumental: syncopated cuts on the off-beat eighths as well
            cand_o = [(x + y) / 2 for x, y in zip(cand_b[:-1], cand_b[1:])]
        t = a
        pts = []
        while b - t > hi * (1.55 if s.get('punch') else 1.0):
            if kind in ('drop', 'hook'):
                # instrumental: beat-locked; 2 beats, with 1-beat bursts in the last bar before vocals / a drop
                burst = (b - t) < 4 * bp + 0.05 or rnd.random() < 0.18
                target = t + bp * (1 if burst else rnd.choice((1.5, 2, 2)))
            elif kind == 'chorus':
                target = t + (bp if rnd.random() < 0.25 else rnd.uniform(0.85, 1.3))
            else:
                target = t + rnd.uniform(1.0, 1.65)
            # sung parts: mostly the vocal onsets (off the grid where possible); choruses mix; drops lock to the beat
            want_beat = (kind in ('drop', 'hook') and rnd.random() < 0.55) or (kind == 'chorus' and n_beat <= n_on)
            pool = [(x, 'beat') for x in cand_b if t + lo - 0.05 <= x] + [(x, 'onset') for x in cand_o if t + lo - 0.05 <= x]
            pool = [p for p in pool if p[0] <= b - lo]
            if not pool:
                break
            def cost(p):
                c = abs(p[0] - target)
                onb = any(abs(p[0] - x) < 0.07 for x in B)
                if want_beat and not onb:
                    c += 0.12
                if not want_beat and onb:
                    c += 0.1
                return c
            x, typ = min(pool, key=cost)
            if x - t > hi * 1.6 and not s.get('punch'):
                x, typ = t + (hi + lo) / 2, 'free'
            pts.append((x, typ)); t = x
            if typ == 'beat':
                n_beat += 1
            elif typ == 'onset':
                n_on += 1
        edges = [(a, 'onset' if kind not in ('drop', 'hook') else 'beat')] + pts
        for k, (x, typ) in enumerate(edges):
            y = edges[k + 1][0] if k + 1 < len(edges) else b
            cuts.append({'t0': round(x, 3), 't1': round(y, 3), 'seg': s['id'], 'on': typ})
    for c in cuts:                                  # measure: is each cut on a beat (within 70 ms)?
        c['on_beat'] = any(abs(c['t0'] - x) < 0.07 for x in B)
    return segs, cuts


def assign_slots(segs, cuts, n_heroes=11, max_images=90):
    """Decide how many distinct images each segment needs and which become hero video clips. Each hero clip covers
    two cuts (two different windows of one clip); every still covers one cut (a still may be used a second time only
    as a tighter cut-in when the budget is short; see reuse_plan)."""
    by = {}
    for c in cuts:
        by.setdefault(c['seg'], []).append(c)
    order = [s for s in segs if s['kind'] not in ('cameo', 'credits')]
    # hero candidates, strongest first: the hook, chorus lines 1 and 3, drops, story punchlines
    pri = []
    for s in order:
        ln = s.get('line') or {}
        if s['kind'] == 'hook':
            pri.append((0, s['id']))
        elif s['kind'] == 'drop' and s['t1'] - s['t0'] > 6:
            pri.append((1, s['id']))
        elif s['kind'] == 'chorus' and ln.get('line_no') in (1, 3):
            pri.append((2, s['id']))
        elif s['kind'] in ('verse', 'bridge') and ln.get('line_no') in (4, 8):
            pri.append((3, s['id']))
        elif s['kind'] in ('verse', 'bridge') and ln.get('line_no') in (2, 6):
            pri.append((4, s['id']))
        elif s['kind'] == 'chorus':
            pri.append((5, s['id']))
        elif s['kind'] in ('drop', 'outro_tail', 'outro', 'intro'):
            pri.append((6, s['id']))
        else:
            pri.append((7, s['id']))
    heroes = [sid for _, sid in sorted(pri, key=lambda x: x[0]) if len(by.get(sid, [])) >= 2][:n_heroes]
    slots = []
    for s in order:
        cs = by.get(s['id'], [])
        n = len(cs)
        hero = s['id'] in heroes
        n_img = n - 1 if hero and n >= 2 else n
        slots.append({'seg': s['id'], 'kind': s['kind'], 'cuts': n, 'images': max(1, n_img), 'hero': hero,
                      't0': s['t0'], 't1': s['t1'], 'text': (s.get('line') or {}).get('text', ''),
                      'section': (s.get('line') or {}).get('section', s['kind'])})
    # over the image budget: let some stills cover two cuts (a tighter cut-in), most of all in drops and long lines,
    # never below half the cuts of a segment (each image is used at most twice)
    while sum(sl['images'] for sl in slots) > max_images:
        cand = [sl for sl in slots if sl['images'] > 1 and sl['images'] - (1 if sl['hero'] else 0) > (sl['cuts'] - (2 if sl['hero'] else 0) + 1) // 2]
        if not cand:
            break
        sl = max(cand, key=lambda x: (x['kind'] in ('drop', 'outro_tail'), x['images'] / max(x['t1'] - x['t0'], 0.1), x['images']))
        sl['images'] -= 1
    return slots


# ------------------------------------------------------------------------------------------------ provisional slots
# The plan (and all generation) is made from lyrics.txt alone, so it runs while demucs/whisper/alignment are still
# working; the real cut timeline is built later from the word timings and mapped onto these slots by segment id.
PLAN_FIRST_S, PLAN_MAX_S = 360, 480    # planner: first attempt, both attempts together (seconds)
PROV_IMAGES = {'chorus': 3, 'hook': 4, 'drop': 4, 'outro_tail': 3}      # every other lyric line: 2
N_DROPS = 4


def provisional_lines(day):
    lyr = G.C.parse_lyrics(G.read(os.path.join(day, 'lyrics.txt')))
    return [dict(x, words=[[t, None, None] for t in (x.get('tokens') or x['text'].split())]) for x in lyr
            if (x.get('text') or '').strip()]


def provisional_slots(lines, n_heroes=25, max_images=110):
    """Segments in song order: the hook, every lyric line, instrumental drops (after the intro and after each chorus,
    up to N_DROPS) and an outro tail. Image counts are estimates; the edit later borrows or leaves pictures unused."""
    segs = [{'seg': 'hook', 'kind': 'hook', 'text': '', 'section': 'hook'}]
    nd = 0

    def drop():
        nonlocal nd
        if nd < N_DROPS:
            nd += 1
            segs.append({'seg': f'drop{nd}', 'kind': 'drop', 'text': '', 'section': 'drop'})
    for i, ln in enumerate(lines):
        segs.append({'seg': line_id(ln), 'kind': ln['kind'], 'text': ln['text'], 'section': ln['section'],
                     'line_no': ln['line_no'], 'occ': ln['section_occ']})
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        end_of_section = not nxt or (nxt['section'], nxt['section_occ']) != (ln['section'], ln['section_occ'])
        if end_of_section and nxt and ln['kind'] in ('intro', 'chorus'):
            drop()
    while nd < 2:
        drop()
    segs.append({'seg': 'outro_tail', 'kind': 'outro_tail', 'text': '', 'section': 'outro'})
    for sl in segs:
        sl['images'] = PROV_IMAGES.get(sl['kind'], 2)
        sl['hero'] = False
    # heroes, strongest first (later chorus repeats last: they may not be sung)
    def pri(sl):
        k, n, occ = sl['kind'], sl.get('line_no'), sl.get('occ', 1)
        if k == 'hook':
            return 0
        if k == 'drop':
            return 1 if sl['seg'] in ('drop1', 'drop2') else 6
        if k == 'chorus':
            return (2 if n in (1, 3) else 5) if occ <= 2 else 8
        if k == 'verse' and n in (4, 8):
            return 3
        if k == 'verse' and n in (2, 6):
            return 4
        if k in ('intro', 'outro', 'outro_tail'):
            return 6
        return 7                                 # bridges are often skipped by Suno: no clips unless spare
    for sl in sorted(segs, key=pri)[:n_heroes]:
        sl['hero'] = True
    # over the image budget: trim the biggest non-essential segments first (repeat choruses, drops, then the rest)
    while sum(sl['images'] for sl in segs) > max_images:
        cand = [sl for sl in segs if sl['images'] > 1]
        if not cand:
            break
        sl = max(cand, key=lambda x: (x['kind'] == 'chorus' and x.get('occ', 1) > 2, x['kind'] in ('drop', 'outro_tail'),
                                      x['images'], -segs.index(x)))
        sl['images'] -= 1
    return segs


def map_segments(rsegs, pslots):
    """real timeline segment id -> provisional slot index (lines by id; drops in order, cycling; outro tails)."""
    pid = {s['seg']: i for i, s in enumerate(pslots)}
    drops = [i for i, s in enumerate(pslots) if s['kind'] == 'drop']
    tails = [i for i, s in enumerate(pslots) if s['kind'] == 'outro_tail'] or drops
    m, dk = {}, 0
    for s in rsegs:
        sid = s['id']
        if s['kind'] in ('cameo', 'credits'):
            continue
        if sid in pid:
            m[sid] = pid[sid]
        elif s['kind'] == 'outro_tail' and tails:
            m[sid] = tails[0]
        elif drops:
            m[sid] = drops[dk % len(drops)]; dk += 1
    return m


# ------------------------------------------------------------------------------------------------ planner
SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"},
            "images": {"type": "array", "items": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "the photoreal image: subject, action, setting, composition, light (35-70 words)"},
                "shot": {"type": "string", "description": "ECU / CU / MCU / MS / WS / aerial / insert / POV / OTS / low-angle"},
                "move": {"type": "string", "enum": ["push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "parallax", "shake", "drift"]},
                "motion": {"type": "string", "description": "hero image only: what moves in the 6 s video"}},
                "required": ["prompt", "shot", "move"]}}},
            "required": ["seg", "images"]}},
        "display": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"},
            "tokens": {"type": "array", "items": {"type": "string"}},
            "accent": {"type": "array", "items": {"type": "string"}}},
            "required": ["seg", "tokens"]}},
        "cameo": {"type": "string", "description": "the Pip cameo scene (one sentence)"}},
    "required": ["segments", "display", "cameo"]}


def plan_prompt(day, look, slots, L, clip_sec=4):
    LK = REAL_LOOKS[look]
    genre, style = G.genre_of(day)
    title = G.read(os.path.join(day, 'title.txt'))
    stories = G.story_list(day)
    st = '\n'.join(f"{s['idx']}. {s['text']} (lyrics: {s['section']} lines {s['lines']}) :: {s['detail'][:700]}" for s in stories)
    rows = []
    ch = 0
    for sl in slots:
        if sl['kind'] == 'chorus' and sl['text'] and sl['seg'].endswith(':1'):
            ch += 1
        tag = {'hook': 'HOOK (instrumental intro, the first frame of the video)', 'drop': 'DROP (instrumental, beat-cut)',
               'outro_tail': 'OUTRO TAIL (instrumental)'}.get(sl['kind'], sl['section'] + (f" (chorus #{ch})" if sl['kind'] == 'chorus' else ''))
        h = f' | image 1 becomes a {clip_sec} s HERO VIDEO (give it a motion)' if sl['hero'] else ''
        tm = f" | {sl['t0']:.1f}-{sl['t1']:.1f} s" if sl.get('t0') is not None else ''
        rows.append(f"SEG {sl['seg']}{tm} | {tag} | lyric: \"{sl['text'] or '-'}\" | images: {sl['images']}{h}")
    sung = [ln for ln in L if ln.get('words')]
    disp = '\n'.join(f"{line_id(ln)}: {json.dumps([w[0] for w in ln['words']], ensure_ascii=False)}" for ln in sung)
    n_total = sum(s['images'] for s in slots)
    worlds = LK.get('worlds') or ['a packed club', 'a huge open-air show at night', 'something cosmic in scale']
    return f"""You are the director of a photoreal, cinematic AI-news music video in the viral "slopcore" style for the song
"{title}" ({genre or '?'}; {style}). Vertical 9:16 for phones. Every image is made by a photoreal image model from your
prompt; most are animated with fast camera moves, the hero images become short videos.

ART DIRECTION for the WHOLE video: {LK['label']}. The ONE accent colour is {LK.get('accent_name', 'red')}: use it for
the key light, prop or detail in every image and never any other strong colour. (The style suffix is appended
automatically; do not repeat it.)
Hard, motivated light in every frame. Real-looking people, places and objects.

THE CORE TRICK: the picture follows the lyric literally, line by line and often word by word. Use LOUD, SPECIFIC,
MEME-LITERATE images a viewer gets in half a second (e.g. "seventy-five percent off the bill": a tower of gold coins
sliced down to a quarter by a guillotine; "benchmaxx": a gym-pumped original robot design flexing on a podium in front of
an eye-test chart drawn only with shapes; "watermark in every frame": a magnifying glass revealing a glowing hidden
pattern of dots on a photo of a sunset). Each image in a segment is a NEW picture that escalates or reacts: wide, then the detail,
then the reaction. Story facts (numbers, who did what) drive the images.

STORIES:
{st}

RULES:
- Photoreal people only as ARCHETYPES (the hoodie engineer, the CEO in a black turtleneck, the lab tech, the detective,
  the raver, the actor in make-up). NEVER a recognisable real person or celebrity face, never a named person's likeness.
  Show famous people through wardrobe, setting and props (a film set, a director's chair, a boardroom), seen from behind,
  in silhouette, or face hidden.
- ABSOLUTELY NO TEXT in any image (the lyric type is added later): no words, letters, numbers, handwriting,
  signatures, receipts, bills, documents, newspapers, books with titles, posters, signs, labels, price tags, jersey
  numbers, no screens or phones showing anything readable, no real logos or brand marks. Show the idea with objects,
  actions, colour and scale instead; suggest companies with colour and objects.
- ORIGINAL DESIGNS ONLY: never a lookalike of a famous film/TV/game character, robot, mascot or superhero (no
  Terminator-style chrome skeleton robots, no Iron Man-style suits, no famous droids, no Wall-E, no cartoon mascots)
  and never a lookalike of a real person. Robots are new designs (e.g. a matte white industrial robot with a soft
  light-bar face, a boxy service robot on wheels).
- Vary shot grammar a lot: extreme close-ups (eyes, mouths, hands), inserts of objects with no people, POV, over-the-
  shoulder, aerials, low-angle hero shots, a tiny figure against something enormous. At most 1 in 5 images is a
  centred medium shot.
- CHORUSES: each chorus happens somewhere NEW and BIGGER: chorus #1 in {worlds[0]}; chorus #2 in {worlds[1]}; the last
  chorus / outro tail: {worlds[2]}.
  VARIETY inside every chorus: at most ONE crowd shot and at most ONE raised-hands shot per chorus, lasers in no more
  than a third of the chorus images. The rest are literal, surprising picturings of the chorus words through objects,
  places, performers' close-ups (feet, mouths, hair whipping), animals, weather, vehicles, macro details (e.g. "lights
  up": a whole city block switching on window by window; "the bass drops": a grand piano falling into a swimming pool).
  Never repeat an image idea from an earlier chorus.
- HOOK: image 1 of the HOOK is the single most striking, scroll-stopping image of the video (it is frame 0).
- DROPS: rapid, escalating spectacle images of the song's world, no story exposition.
- "motion" (hero images only): one sentence for a {clip_sec} s clip that starts on this exact image: a clear physical action with
  an exact direction ("enters left, exits right", "falls toward the lens"), one camera move, handheld wobble.
- "move" for every image: the local camera move used when it is animated (push_in, pull_out, pan_left, pan_right,
  tilt_up, tilt_down, parallax, shake, drift). Vary them.
- prompt: 35-70 words, concrete nouns and verbs, exact lens and scale cues ("24mm low angle", "macro", "the figure is
  tiny against..."), composition, the light source, a little deliberate imperfection. English.

SEGMENTS (write exactly the stated number of images for each, {n_total} in total, in order):
{chr(10).join(rows)}

DISPLAY TYPE: the sung words, one token per sung word, in order, for each sung line below. Fix brand / product spellings
and use numerals for numbers ("GPT-6", "Haiku 5.5", "DeepMind", "75%", "SynthID"); to merge words into one token use ""
for the following word(s) (e.g. ["Seventy-five","percent"] -> ["75%",""]). Keep the token count identical to the word
count. "accent": up to 2 tokens per line to colour (brands, numbers, the punch word).
{disp}

CAMEO: one sentence: where a small physical toy figure of our mascot (a cute white chibi robot) sits in a real scene at
the end of the song, in this video's world (e.g. {LK.get('cameo', 'on a DJ mixer after the show')}). Do not describe
the mascot's design.

Answer directly in your reply. Do NOT use any tools. Return JSON only, matching the schema."""


def plan(day, work, look, slots, L, force=False, deadline=None, clip_sec=4, reserve_s=17 * 60):
    path = os.path.join(work, 'real_plan.json')
    key = {'version': PLANNER_VERSION, 'look': look, 'slots': [(s['seg'], s['images'], s['hero']) for s in slots]}
    p = G.load_json(path)
    if p and not force and p.get('key') == json.loads(json.dumps(key)):
        G.log("planner: cached real_plan.json")
        return p
    pf = os.path.join(work, 'real_plan_prompt.txt')
    open(pf, 'w').write(plan_prompt(day, look, slots, L, clip_sec))
    import time
    res = None
    t_first = time.time()
    for attempt in (1, 2):
        if os.environ.get('CINE_REAL_FAIL') == 'plan':
            break
        t0 = time.time()
        # generation waits for the plan, so the planner gets at most PLAN_MAX_S in total (a normal reply takes 3-4 min;
        # a slower one means a slow API, and the template plan is better than losing the generation window), and it
        # must leave room for generation + render inside the run's time budget
        tmo = int(min(PLAN_FIRST_S if attempt == 1 else PLAN_MAX_S, PLAN_MAX_S - (t0 - t_first)))
        if deadline:
            tmo = int(min(tmo, deadline - t0 - reserve_s))
        if tmo < 120:
            G.log(f"planner: skipped attempt {attempt}, not enough time left in the budget")
            break
        try:
            r = run_grok_text(pf, work, schema=SCHEMA, timeout=tmo)
            res = _extract_json(r.get('text') or '')
            if res and res.get('segments'):
                G.log(f"planner: {time.time()-t0:.0f}s (attempt {attempt})")
                break
            G.log(f"planner attempt {attempt}: no segments in reply")
        except Exception as e:
            G.log(f"planner attempt {attempt} failed: {e!r}"[:300])
            res = None
    if os.environ.get('CINE_REAL_FAIL') == 'plan':
        res = None
        G.log("TEST: CINE_REAL_FAIL=plan, discarding the planner reply")
    if not res:
        G.log("WARNING: planner failed twice; using the lyric-literal template plan")
        res = fallback_plan(day, slots, L, look)
    res['key'] = key
    res['look'] = look
    G.save_json(res, path)
    return res


SHOTS = [('ECU', 'push_in', 'extreme close-up'), ('WS', 'pull_out', 'wide shot, the subject small against a huge setting'),
         ('low-angle', 'tilt_up', 'low-angle hero shot'), ('insert', 'parallax', 'insert shot of the key object, no people'),
         ('POV', 'shake', 'point-of-view shot'), ('OTS', 'pan_left', 'over-the-shoulder shot')]


def fallback_plan(day, slots, L, look='neon-accent'):
    """No planner: literal template prompts built from each lyric line and its story (still photoreal, no text)."""
    stories = G.story_list(day)
    def story_for(sl):
        for s in stories:
            if s.get('section') and sl['section'] == s['section'] and s.get('lines'):
                ln = int(sl['seg'].split(':')[-1]) if ':' in sl['seg'] else 0
                if s['lines'][0] <= ln <= s['lines'][1]:
                    return s['text']
        return ''
    LK = REAL_LOOKS.get(look, REAL_LOOKS['neon-accent'])
    worlds = LK.get('worlds') or ['a packed club', 'a huge open-air show', 'something cosmic']
    segs, i = [], 0
    nch = 0
    for sl in slots:
        st = story_for(sl)
        if sl['kind'] == 'chorus' and sl['seg'].endswith(':1'):
            nch += 1
        world = worlds[min(nch, 3) - 1] if nch else worlds[0]
        imgs = []
        for k in range(sl['images']):
            code, mv, desc = SHOTS[i % len(SHOTS)]; i += 1
            if sl['text']:
                what = f'a literal, specific visual of the lyric "{sl["text"]}"' + (f' about the news "{st}"' if st else '') + \
                    (f', set in {world}' if sl['kind'] == 'chorus' else '')
            elif sl['kind'] == 'hook':
                what = f'a scroll-stopping image set in {worlds[0]}, one blinding light'
            else:
                what = f'huge spectacle in {world}: pyro, confetti in the air, performers in motion'
            imgs.append({'prompt': f"{desc} of {what}. Real people as anonymous archetypes, faces turned away or in "
                                   f"shadow, real objects, hard motivated light.", 'shot': code, 'move': mv,
                         'motion': 'the subject moves toward the lens while the camera pushes in, handheld wobble'})
        segs.append({'seg': sl['seg'], 'images': imgs})
    return {'segments': segs, 'display': [], 'cameo': LK.get('cameo', 'on the edge of a DJ mixer after the show.'),
            'fallback': True}
