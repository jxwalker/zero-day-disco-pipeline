"""slopcore style (cine-real v2): people-driven, deadpan, lyric-literal scenes with a recurring cast, one gritty look,
mostly short reference_to_video clips, sparse giant type, 2-3 Pip toy cameos. See /workspace/slopcore/vibe.md and the
README "slopcore". Reuses the cine-real timeline, slot mapping, generation and renderer."""
import json, os, re, time
import common_gv as G
import real_plan as RP
from plan_gen import run_grok_text, _extract_json

PLANNER_VERSION = 'slop-2'
PLAN_FIRST_S, PLAN_MAX_S = 420, 540

# One gritty, committed look per song. The genre changes the energy (cast, situations, cut pace), never the gloss.
SLOP_LOOKS = {
    'vhs-camcorder': {
        'label': 'found-footage 1990s VHS camcorder tape',
        'prompt': ("Photoreal frame from a 1990s consumer VHS camcorder tape, vertical 9:16, real people in a real place, "
                   "faded desaturated tape colours with real deep shadows, whatever light the scene really has (hard daylight, "
                   "fluorescent, dusk, night streetlight, on-camera light), soft focus, slight chroma bleed and tape noise, "
                   "imperfect handheld amateur framing, natural unflattering light."),
        'accent': (255, 64, 48), 'accent_hue': None, 'accent_name': 'red', 'sat': 0.62, 'tint': (12, 5, -10),
        'contrast': 1.02, 'crush': -0.01, 'vignette': 0.30, 'leak': (255, 150, 60), 'grain': 9, 'vhs': True,
        'overlay': 'vhs', 'genres': ('pop-video', 'standard'),
        'energy': 'euphoric and ominous: mass rituals in mundane places, crowds in formation on car parks and lawns, '
                  'offices that turn into ceremonies, night suburbs under a huge sky, conference halls, launch sites, '
                  'stadiums at night',
    },
    'cold-accent': {
        'label': 'cold grey-blue cinema with one red accent',
        'prompt': ("Photoreal cinematic film frame, vertical 9:16, real people in a real place, cold desaturated grey-blue "
                   "palette with ONE red accent (a tie, a light, a prop), hard overhead fluorescent or window light, haze, "
                   "crushed blacks, 35mm grain, slightly off-level handheld framing."),
        'accent': (230, 30, 40), 'accent_hue': 355, 'accent_name': 'red', 'sat': 0.30, 'tint': (-6, 0, 10),
        'contrast': 1.12, 'leak': (255, 40, 60), 'grain': 7, 'genres': ('edm',),
        'energy': 'cold, rhythmic, uniform: rows of identical workers or students moving in unison, corridors, '
                  'exam halls, server floors, stadiums of robots, night cities',
    },
    '16mm-doc': {
        'label': 'gritty 16mm documentary footage',
        'prompt': ("Photoreal 16mm documentary film frame, vertical 9:16, real people in a real place, tungsten and "
                   "fluorescent practical light, heavy grain, muted earthy colours, slight gate weave, handheld "
                   "observational camera, imperfect focus."),
        'accent': (255, 170, 40), 'accent_hue': None, 'accent_name': 'amber', 'sat': 0.7, 'tint': (8, 4, -6),
        'contrast': 1.08, 'leak': (255, 140, 50), 'grain': 12, 'genres': ('rock',),
        'energy': 'sweaty and loud: garages, pubs, vans, backstage corridors, protest marches, kitchens at 3am',
    },
    'sunny-pastel': {                                   # tone=joyful (never picked by genre)
        'label': 'sunny glossy 35mm pop video, pastel pinks and sunshine',
        'prompt': ("Photoreal glossy pop music-video frame shot on 35mm, vertical 9:16, real people in a real place, bright "
                   "warm sunshine, pastel pink, peach, lilac and baby-blue palette, soft bloom and a little sparkle in the "
                   "light, clean natural skin texture, genuine warm smiles, crisp focus, cheerful candy-coloured styling, "
                   "airy and happy. Wholesome: no blood, no red liquid, no gore, nothing anatomical or medical."),
        'clip_extra': 'Wholesome and happy throughout: no blood, no red liquid, no dripping, no gore, nothing anatomical or medical.',
        'accent': (255, 84, 170), 'accent_hue': None, 'accent_name': 'pink', 'sat': 1.04, 'tint': (8, 0, 5),
        'contrast': 1.0, 'crush': 0.0, 'vignette': 0.10, 'leak': (255, 180, 210), 'grain': 3, 'genres': (),
        'energy': 'sunny, giddy and sweet: sing-along joy, dancing in the street, picnics, college lawns in sun, '
                  'parties with confetti and fairy lights, friends cheering, proud families',
    },
    'sunlit-portra': {                                  # tone=playful (never picked by genre)
        'label': 'sunlit 35mm, warm Kodak Portra grade, real-world colour',
        'prompt': ("Photoreal music-video frame shot on 35mm film, vertical 9:16, real people in a real place, warm Kodak "
                   "Portra colour with real-world palettes (stone, brick, denim, grass, wood, skin), natural light, gentle "
                   "film grain, natural skin texture, confident relaxed expressions, crisp focus, cool and warm. No pastel "
                   "wash, no glitter. Wholesome: no blood, no red liquid, no gore, nothing anatomical or medical."),
        'clip_extra': 'Warm and fun throughout: no blood, no red liquid, no dripping, no gore, nothing anatomical or medical.',
        'accent': (230, 40, 70), 'accent_hue': None, 'accent_name': 'red', 'sat': 1.0, 'tint': (6, 2, -4),
        'contrast': 1.04, 'crush': 0.02, 'vignette': 0.16, 'leak': (255, 170, 110), 'grain': 6, 'genres': (),
        'energy': 'cool and warm: deadpan cheek, strutting down real streets, college lawns, river banks, kitchen '
                  'parties, golden hour, a neon night out, friends and family cheering, the mundane taken absurdly far',
    },
    'digicam-2003': {
        'label': 'early-2000s compact digicam with on-camera flash',
        'prompt': ("Photoreal snapshot from an early-2000s compact digital camera, vertical 9:16, real people, harsh "
                   "on-camera flash, blown highlights, dark background falling off, slight motion blur, JPEG noise, "
                   "candid party or street moment, imperfect tilted framing."),
        'accent': (255, 140, 0), 'accent_hue': None, 'accent_name': 'orange', 'sat': 0.95, 'tint': (4, 2, 0),
        'contrast': 1.10, 'leak': (255, 120, 40), 'grain': 6, 'overlay': 'datestamp', 'genres': ('punk',),
        'energy': 'chaotic: house parties, skate parks, bedroom offices, mosh pits, night buses',
    },
}


def pick_look(genre_look, override='auto'):
    if override and override != 'auto' and override in SLOP_LOOKS:
        return override, 'set on the command line'
    for k, v in SLOP_LOOKS.items():
        if genre_look in v['genres']:
            return k, f'genre look {genre_look} -> {k}'
    return 'vhs-camcorder', f'default for {genre_look}'


# ------------------------------------------------------------------------------------------------ slots
N_DROPS = 2


def provisional_slots(lines, n_clips=55, max_images=95):
    """Segments in song order with 'images' (scenes) and 'clips' (how many of the first images become video)."""
    segs = [{'seg': 'hook', 'kind': 'hook', 'text': '', 'section': 'hook', 'images': 2, 'clips': 2}]
    nd = 0
    for i, ln in enumerate(lines):
        k, occ = ln['kind'], ln['section_occ']
        if k == 'chorus':
            im, cl = (2, 2) if occ <= 2 else (2, 1)
        else:
            im, cl = 2, 1
        segs.append({'seg': RP.line_id(ln), 'kind': k, 'text': ln['text'], 'section': ln['section'],
                     'line_no': ln['line_no'], 'occ': occ, 'images': im, 'clips': cl})
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        end_sec = not nxt or (nxt['section'], nxt['section_occ']) != (ln['section'], ln['section_occ'])
        if end_sec and nxt and k in ('intro', 'chorus') and nd < N_DROPS:
            nd += 1
            segs.append({'seg': f'drop{nd}', 'kind': 'drop', 'text': '', 'section': 'drop', 'images': 3, 'clips': 2})
    while nd < N_DROPS:
        nd += 1
        segs.append({'seg': f'drop{nd}', 'kind': 'drop', 'text': '', 'section': 'drop', 'images': 3, 'clips': 2})
    segs.append({'seg': 'outro_tail', 'kind': 'outro_tail', 'text': '', 'section': 'outro', 'images': 2, 'clips': 1})
    # over the clip budget: drop clips from late repeats first (last chorus, outro, bridge), then verse lines
    def low(s):
        return (s['kind'] == 'chorus' and s.get('occ', 1) >= 3, s['kind'] in ('outro', 'outro_tail'), s['kind'] == 'bridge',
                s['kind'] == 'verse' and s.get('line_no', 0) % 2 == 1, s['clips'])
    while sum(s['clips'] for s in segs) > n_clips:
        c = max([s for s in segs if s['clips'] > 0], key=low)
        c['clips'] -= 1
    while sum(s['images'] for s in segs) > max_images:
        c = max([s for s in segs if s['images'] > max(1, s['clips'])], key=lambda s: (s['images'] - s['clips'], -segs.index(s)))
        c['images'] -= 1
    for s in segs:
        s['hero'] = s['clips'] > 0
    return segs


# ------------------------------------------------------------------------------------------------ planner
SCHEMA = {
    "type": "object",
    "properties": {
        "cast": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string", "description": "A, B or C"},
            "role": {"type": "string"},
            "description": {"type": "string", "description": "age, build, face, hair, exact wardrobe (25-45 words)"}},
            "required": ["id", "role", "description"]}},
        "segments": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"},
            "location": {"type": "string"},
            "images": {"type": "array", "items": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "who does what, where, shot size/lens, light (35-70 words)"},
                "cast": {"type": "array", "items": {"type": "string"}},
                "shot": {"type": "string"},
                "move": {"type": "string", "enum": ["push_in", "pull_out", "pan_left", "pan_right", "shake", "drift"]},
                "motion": {"type": "string", "description": "video shots: the physical action in the clip"}},
                "required": ["prompt", "shot", "move"]}}},
            "required": ["seg", "images"]}},
        "display": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"},
            "tokens": {"type": "array", "items": {"type": "string"}},
            "accent": {"type": "array", "items": {"type": "string"}}},
            "required": ["seg", "tokens"]}},
        "pip": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"}, "scene": {"type": "string"}}, "required": ["seg", "scene"]}},
        "cameo": {"type": "string"}},
    "required": ["cast", "segments", "display", "pip", "cameo"]}


def plan_prompt(day, look, slots, L, clip_sec=3):
    LK = SLOP_LOOKS[look]
    genre, style = G.genre_of(day)
    title = G.read(os.path.join(day, 'title.txt'))
    stories = G.story_list(day)
    st = '\n'.join(f"{s['idx']}. {s['text']} (lyrics: {s['section']} lines {s['lines']}) :: {s['detail'][:600]}" for s in stories)
    rows, ch = [], 0
    for sl in slots:
        if sl['kind'] == 'chorus' and sl['seg'].endswith(':1'):
            ch += 1
        tag = {'hook': 'HOOK (instrumental intro; frame 0 of the video)', 'drop': 'DROP (instrumental)',
               'outro_tail': 'OUTRO TAIL (instrumental, the ending)'}.get(sl['kind'], sl['section'] + (f" (chorus #{ch})" if sl['kind'] == 'chorus' else ''))
        v = f" | the first {sl['clips']} become {clip_sec} s VIDEO clips (give each a motion)" if sl['clips'] else ''
        rows.append(f"SEG {sl['seg']} | {tag} | lyric: \"{sl['text'] or '-'}\" | images: {sl['images']}{v}")
    sung = [ln for ln in L if ln.get('words')]
    disp = '\n'.join(f"{RP.line_id(ln)}: {json.dumps([w[0] for w in ln['words']], ensure_ascii=False)}" for ln in sung)
    n_total = sum(s['images'] for s in slots)
    verse_segs = [s['seg'] for s in slots if s['kind'] in ('verse', 'chorus', 'bridge')]
    return f"""You are the director of a viral "slopcore" AI-news music video for the song "{title}" ({genre or '?'};
{style}). Vertical 9:16. Every shot is generated by a photoreal image model from your prompt and most become short
video clips. Study this brief carefully; the last attempt failed because it was glossy, empty still-life metaphors
(lips, glass brains, slot machines, popsicles) with no people and no story. Do NOT do that.

WHAT SLOPCORE IS (copy this feel):
- PEOPLE IN REAL PLACES ACTING OUT EACH LYRIC, literally and deadpan. Office workers, founders in hoodies, researchers in
  lab coats, a mum at the kitchen table, students in an exam hall, a whole open-plan office, a wedding party, a school
  marching band, a call centre, a robot-arm factory floor, a suburban street, an astronomer in a backyard observatory.
  Each line is a tiny scene: someone DOING the words ("watch the dashboard grow" = an office crowd gathered round a
  monitor, jaws dropping, as a plant on the desk grows to the ceiling; "rate limits" = a man in a suit physically
  holding back a stampede of interns at a glass door).
- A RECURRING CAST gives a loose story with escalation: one protagonist (the "cast" A) who appears in about half of
  all shots across the whole song, plus up to two supporting characters (B, C). They are ORIGINAL people (never a
  celebrity or real person's likeness), described precisely so every shot shows the same person. The protagonist
  is always MID-ACTION, never just standing centred and posing: running down a corridor, climbing onto a desk, dragging
  a server rack, shoving through a crowd, diving across a table, bursting through a door, dancing alone in a car park,
  slamming a desk, pointing into the lens. Frame them off-centre, in profile, from behind, from low or high angles,
  half out of frame, small in a wide. At most 1 in 6 images may be a straight-to-lens stare. Supporting characters react.
- DEADPAN ABSURDITY + MEME LITERACY: everybody takes the absurd premise totally seriously. Mundane x cosmic (a family
  dinner while a planet fills the window; a cubicle worker calmly typing as the office floods). Crowds act in unison
  (a whole hall raises one arm; fifty interns turn their heads at once).
- DEADPAN ESCALATION: nobody smiles at the absurdity; each segment raises the stakes by one notch, and the same bit
  returns bigger (one intern applauds -> the whole floor -> a stadium; a plant on a desk -> a jungle in the lobby).
  Background people carry on with mundane tasks while the impossible happens behind them.
- SCALE: verse 1 = one office/home; chorus 1 = the whole building joins in; verse 2 = the world outside (streets,
  labs, roads, factories); chorus 2 = the city; bridge = night, one quiet human moment; last chorus = absurd
  planetary scale (stadiums, rooftops of a whole city, crowds on a beach at sunset). End on a callback.
- Locations recur for 2-4 consecutive lines (wide -> close-up -> reaction), then jump.
- Genre energy for this song: {LK['energy']}.

LOOK (the same for every shot; the style suffix is appended automatically, do not repeat it): {LK['label']}.
Real-world, imperfect, unflattering light (sun flare, fluorescent tubes, desk lamps, car headlights), grain, handheld.
NOT glossy, NOT product photography, NOT studio sets, NOT candy colours, NOT surreal sculptures.

STORIES (the news the verses are about; show them through PEOPLE and their reactions):
{st}

RULES:
- At least 3 of every 4 images have people doing something. Objects alone only when a line truly needs an insert.
- Shot grammar: mix close-ups of faces and hands, mediums of people doing the action, wides of crowds/places,
  over-the-shoulder, low angles, a tiny figure against something enormous. Faces look natural and expressive.
- NO TEXT IN ANY IMAGE: no words, letters, numbers, signs, labels, captions, logos, readable screens, documents,
  receipts, signatures, jersey numbers. Screens show only abstract light, colour or a face; charts are shown as glowing
  bars and lines with no labels, or as physical things (a bar chart made of stacked people, a rising line drawn in
  light). The lyric type is added later.
- ORIGINAL DESIGNS ONLY: no lookalike of any real person, celebrity, politician, CEO, or of a famous film/TV/game
  character, robot or mascot (no Terminator-style robots, no famous droids). Robots: new designs (matte white humanoid
  with a soft light-bar face, boxy service robot, a plain robot arm).
- For the VIDEO images (the first N of a segment), "motion" says the physical action in the {clip_sec} s clip that starts on
  this exact image: one clear action with direction ("she turns from the screen to the lens and points", "the whole
  row of workers stands up at once", "he sprints toward camera through the doors"), plus a simple camera move.
  Video images should be the ones with the most human action.
- "cast": the ids of the cast members visible and recognisable in that image (empty for crowds of extras/inserts).
  Put the protagonist A in at least one image of most segments; B/C less often. Do not put more than 2 cast in one image.
- prompt: 30-55 words: who, doing WHAT ACTION (a verb, mid-movement), where, where, shot size and lens, the light source, one deliberate imperfection.
  Describe extras as archetypes. Do not re-describe a cast member's looks in the prompt; just write "A" or "B" (e.g.
  "A, sweating, slams the laptop shut while B laughs") - the cast description is supplied separately.
- HOOK: the first image is the most scroll-stopping image (A staring into the lens mid-action, or a striking crowd moment).

SEGMENTS (write exactly the stated number of images for each, {n_total} in total, in order):
{chr(10).join(rows)}

DISPLAY TYPE: the sung words, one token per sung word, in order, for each sung line below. Fix brand / product spellings
and use numerals ("GPT-6.1", "Claude Code", "66.1", "8x", "$1,000"); to merge words into one token use "" for the
following word(s). Keep the token count identical to the word count. "accent": the 1-2 PUNCH tokens of the line that will
slam giant on screen (a verb, a number, a brand, the funny word). Usually exactly 1; never more than 2. Only ONE
giant word per line is shown (chorus words and verse punchlines); the rest stays in the small subtitle.
{disp}

PIP: our mascot is a small physical vinyl toy robot (white, bunny ears; do not describe it further). Pick exactly 2
segments from: {', '.join(verse_segs[:40])} where the toy appears for one shot, and describe the scene in one sentence
each, inside that segment's location and story (e.g. the toy standing on A's office desk next to a coffee mug while A
types; the toy held up in a fan's hand above a singing crowd; the toy on the dashboard of a car on the road). CAMEO: one sentence for the final shot of the song with the
toy alone in the last location after everyone has gone.

Answer directly in your reply. Do NOT use any tools. Return JSON only, matching the schema."""


def plan(day, work, look, slots, L, force=False, deadline=None, clip_sec=3, reserve_s=17 * 60, reuse=False):
    path = os.path.join(work, 'real_plan.json')
    key = {'version': PLANNER_VERSION, 'look': look, 'slots': [(s['seg'], s['images'], s['clips']) for s in slots]}
    p = G.load_json(path)
    if p and not force and p.get('key') == json.loads(json.dumps(key)):
        G.log("planner: cached real_plan.json")
        return p
    if p and reuse and p.get('segments') and (p.get('key') or {}).get('slots') == json.loads(json.dumps(key['slots'])):
        G.log(f"planner: reusing real_plan.json from planner {(p.get('key') or {}).get('version')} (--real-reuse-plan)")
        return p
    pf = os.path.join(work, 'real_plan_prompt.txt')
    open(pf, 'w').write(plan_prompt(day, look, slots, L, clip_sec))
    res, t_first = None, time.time()
    for attempt in (1, 2):
        if os.environ.get('CINE_REAL_FAIL') == 'plan':
            break
        t0 = time.time()
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
            res = None
        except Exception as e:
            G.log(f"planner attempt {attempt} failed: {e!r}"[:300])
            res = None
    if not res:
        G.log("WARNING: planner failed twice; using the template plan")
        res = fallback_plan(day, slots, L, look)
    res['key'] = key
    res['look'] = look
    G.save_json(res, path)
    return res


def fallback_plan(day, slots, L, look):
    stories = G.story_list(day)
    places = ['an open-plan office at golden hour', 'a cramped startup office with whiteboards facing away',
              'a school gym full of people', 'a suburban street at sunset', 'a rooftop over the city at dusk',
              'a crowded beach at sunset']
    acts = ['points straight into the lens', 'slams the laptop shut and stands up', 'leads a crowd singing',
            'walks toward camera through the crowd', 'stares at a glowing screen, jaw dropping', 'dances badly but proudly']
    segs, i, nch = [], 0, 0
    for sl in slots:
        if sl['kind'] == 'chorus' and sl['seg'].endswith(':1'):
            nch += 1
        place = places[min(len(places) - 1, nch * 2 + (1 if sl['kind'] == 'verse' and (sl.get('line_no') or 0) > 4 else 0))]
        imgs = []
        for k in range(sl['images']):
            act = acts[i % len(acts)]; i += 1
            what = f'acting out the lyric "{sl["text"]}" literally' if sl['text'] else 'in the middle of the action'
            imgs.append({'prompt': f"A {act}, {what}, in {place}, real people around reacting, medium shot, 28mm, "
                                   f"natural light, deadpan.", 'cast': ['A'] if k == 0 else [], 'shot': 'MS',
                         'move': 'push_in', 'motion': f'A {act}; the people around react; handheld push-in'})
        segs.append({'seg': sl['seg'], 'location': place, 'images': imgs})
    verse = [s['seg'] for s in slots if s['kind'] == 'verse']
    return {'cast': [{'id': 'A', 'role': 'protagonist', 'description': 'a woman in her early thirties with a messy dark '
                      'bob, round glasses, an oversized grey hoodie over a white collared shirt, tired eyes, very expressive'}],
            'segments': segs, 'display': [],
            'pip': [{'seg': verse[1] if len(verse) > 1 else slots[1]['seg'], 'scene': "standing on A's office desk next to a coffee mug while A types"},
                    {'seg': verse[-2] if len(verse) > 2 else slots[2]['seg'], 'scene': 'held up in a fan\'s hand above a singing crowd'}],
            'cameo': 'alone on an empty office desk at night after everyone has gone, a desk lamp still on.',
            'fallback': True}
