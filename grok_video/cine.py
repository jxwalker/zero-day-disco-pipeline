"""Story-driven, cinematic shot planning for the genre looks (pop-video, edm, rock, punk).

The shot list skeleton is built here, deterministically, from tags.json story_tags + lyrics.txt (+ caption timings when
they exist): an intro slot, an establishing and a payoff slot per story (each owning half of that story's sung lines),
chorus performance slots spread over the choruses, and an outro slot if the count allows. The planner (one grok text
call) only fills in the creative fields of each slot, so every story shot is tied to the exact words sung over it and
the editor can put it under those lines."""
import os, re
import common_gv as G
from looks import LOOKS

SCHEMA = {
    "type": "object",
    "properties": {"shots": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer", "description": "the slot id"},
        "setting": {"type": "string", "description": "short location name (identical for every chorus slot)"},
        "props": {"type": "string", "description": "the story objects / set pieces in frame"},
        "scene": {"type": "string", "description": "the opening movie frame: who/what/where, composition, foreground/background"},
        "shot_type": {"type": "string", "description": "wide establishing | medium | medium close-up | close-up | extreme close-up | over-the-shoulder | low-angle wide"},
        "lens": {"type": "string", "description": "lens feel, e.g. anamorphic widescreen feel, shallow depth of field, rack focus from X to Y"},
        "lighting": {"type": "string", "description": "motivated lighting: source and colour"},
        "atmosphere": {"type": "string", "description": "haze, particles, rain, sparks, lens flare..."},
        "camera": {"type": "string", "description": "ONE clear camera move"},
        "motion": {"type": "string", "description": "the 10 s action beat by beat: '0-3 s: ... 3-7 s: ... 7-10 s: ...'"},
        "outfit": {"type": "string", "description": "Pip's styling for this shot (or 'none')"}},
        "required": ["id", "setting", "props", "scene", "shot_type", "lens", "lighting", "atmosphere", "camera", "motion", "outfit"]}}},
    "required": ["shots"]}


def _lyric_lines(day):
    return G.C.parse_lyrics(G.read(os.path.join(day, 'lyrics.txt')))


def _timed(L):
    """(section lower, occ, line_no) -> (start, end) from caption timings."""
    out = {}
    for ln in L or []:
        out[(ln['section'].lower(), ln['section_occ'], ln['line_no'])] = (ln.get('ds', ln.get('start')), ln.get('de', ln.get('end')))
    return out


def story_slots(day, n, L=None):
    lyr = _lyric_lines(day)
    stories = G.story_list(day)
    tm = _timed(L)

    def win(lines):
        ts = [tm.get((x['section'].lower(), x['section_occ'], x['line_no'])) for x in lines]
        ts = [t for t in ts if t and t[0] is not None]
        return [round(min(t[0] for t in ts), 1), round(max(t[1] for t in ts), 1)] if ts else None

    def ref(lines):
        return [[x['section'], x['section_occ'], x['line_no']] for x in lines]

    story_lines = []
    for s in stories:
        if not s.get('section') or not s.get('lines'):
            story_lines.append([]); continue
        a, b = s['lines'][0], s['lines'][-1]
        occ = s.get('occurrence') or 1
        story_lines.append([x for x in lyr if x['section'].lower() == s['section'].lower() and x['section_occ'] == occ
                            and a <= x['line_no'] <= b])
    k = len(stories)
    choruses = []
    for x in lyr:
        if x['kind'] in ('chorus', 'postchorus'):
            key = (x['section'], x['section_occ'])
            if not choruses or choruses[-1][0] != key:
                choruses.append((key, []))
            choruses[-1][1].append(x)
    intro = [x for x in lyr if x['kind'] == 'intro']
    outro = [x for x in lyr if x['kind'] == 'outro']
    min_ch = max(2, min(3, len(choruses) or 3))
    budget = max(n - 1 - min_ch, 0)                     # shots left for stories after intro + choruses
    per = [1 if i < budget else 0 for i in range(k)]
    extra = budget - sum(per)
    for i in sorted(range(k), key=lambda i: -len(story_lines[i])):   # second shot: stories with most lines first
        if extra <= 0:
            break
        if per[i] == 1 and len(story_lines[i]) >= 2:
            per[i] = 2; extra -= 1
    n_ch = n - 1 - sum(per)
    want_outro = n_ch >= 5 or (n_ch >= 4 and outro)
    if want_outro:
        n_ch -= 1
    slots = [{'slot': 'intro', 'story': 0, 'section': 'intro', 'beat': 'opening',
              'lyric': [x['text'] for x in intro], 'line_refs': ref(intro), 'window': win(intro)}]
    for i, s in enumerate(stories):
        lines = story_lines[i]
        sec = 'bridge' if (s.get('section') or '').lower().startswith('bridge') else 'verse'
        if per[i] == 0:
            continue
        halves = [lines] if per[i] == 1 else [lines[:(len(lines) + 1) // 2], lines[(len(lines) + 1) // 2:]]
        for h, part in enumerate(halves):
            slots.append({'slot': f"story{s['idx']}{'ab'[h] if per[i] == 2 else ''}", 'story': s['idx'], 'section': sec,
                          'beat': ('establishing' if h == 0 else 'payoff') if per[i] == 2 else 'establishing+payoff',
                          'story_text': s['text'], 'story_detail': s['detail'], 'lyric': [x['text'] for x in part],
                          'line_refs': ref(part), 'window': win(part)})
    moments = ['the chorus lands: first big hit of the hook', 'hands up: the whole crowd sings the hook back',
               'the final chorus climax: biggest moment of the song', 'a second angle on the hook: intimate close-up energy',
               'a slow-motion beat inside the chorus']
    for j in range(n_ch):
        if choruses:
            ci = min(len(choruses) - 1, round(j * (len(choruses) - 1) / max(n_ch - 1, 1))) if n_ch > 1 else 0
            lines = choruses[ci][1]
        else:
            lines = []
        slots.append({'slot': f'chorus{j+1}', 'story': 0, 'section': 'chorus', 'beat': moments[j % len(moments)] if j < 2 or j != n_ch - 1 else moments[2],
                      'lyric': [x['text'] for x in lines], 'line_refs': ref(lines), 'window': win(lines)})
    if want_outro:
        slots.append({'slot': 'outro', 'story': 0, 'section': 'outro', 'beat': 'the final pose',
                      'lyric': [x['text'] for x in outro], 'line_refs': ref(outro), 'window': win(outro)})
    # song order: by first sung line where known (choruses interleave with the stories)
    order = {(x['section'], x['section_occ'], x['line_no']): x['idx'] for x in lyr}
    def pos(sl):
        if sl['slot'] == 'intro':
            return -1
        if sl['slot'] == 'outro':
            return 1e9
        r = sl['line_refs']
        return order.get(tuple(r[0]), 1e8) + (0.5 if sl['section'] == 'chorus' else 0) if r else 1e8
    slots.sort(key=pos)
    for i, sl in enumerate(slots[:n]):
        sl['id'] = i + 1
    return slots[:n]


EXAMPLES = """Examples of the literal, readable storytelling wanted (the quality bar; if today's story is one of these, use
that image; otherwise invent one in the same spirit):
- "Mistral's 1T-parameter open model 'Le Chonk'" -> Pip next to a colossal chonky trillion-parameter robot in a blue
  cape with a ring of gold stars (Europe), the robot stomping through a city while Pip rides its shoulder.
- "Claude now works inside Google Docs, Sheets and Slides" -> Pip walking through giant floating blank document,
  spreadsheet-grid and slide windows in blue, green, yellow and red, a warm coral sparkle sidebar beside them stamping
  glowing check marks on edits.
- "users voted for a usage reset" -> a sea of raised robot hands, a giant analogue meter spinning back to zero, confetti.
- "722 math papers" -> a vault door swinging open on towering stacks of papers glowing with equations."""


def plan_prompt(day, n, look, slots):
    LK = LOOKS[look]
    genre, style = G.genre_of(day)
    title = G.read(os.path.join(day, 'title.txt')) or (G.load_json(os.path.join(day, 'tags.json'), {}) or {}).get('title', '')
    lyr = G.read(os.path.join(day, 'lyrics.txt'))
    rows = []
    for sl in slots:
        w = f" | sung at {sl['window'][0]}-{sl['window'][1]} s" if sl.get('window') else ''
        lyric = ' / '.join(sl['lyric']) if sl['lyric'] else '(instrumental)'
        if sl['story']:
            rows.append(f"SLOT {sl['id']} [{sl['section']}, story {sl['story']}, {sl['beat'].upper()} shot{w}]\n"
                        f"  story: {sl['story_text']}\n  facts: {sl['story_detail'][:600]}\n  lyrics sung over this shot: {lyric}")
        else:
            rows.append(f"SLOT {sl['id']} [{sl['section']}, performance: {sl['beat']}{w}]\n  lyrics sung over this shot: {lyric}")
    slot_txt = '\n\n'.join(rows)
    return f"""You are the director of a high-budget, CINEMATIC vertical 9:16 AI music video for today's AI-news song
"{title}" (genre: {genre or '?'} / style: {style}). Fill in a shot for each numbered SLOT below.

THE LOOK OF THE PERFORMANCE SHOTS:
{LK['direction']}

THE STAR of every shot is our mascot Pip: {G.PIP_DESC}
Pip's outfit changes per section but the core look stays: white egg body, bunny ears with pink insides, yellow antenna
ball, navy face screen with cyan CLOSED ARC EYES, pink blush, SHORT STUBBY LEGS, PINK HEART ON THE CHEST ALWAYS VISIBLE
(jackets/shirts open; any guitar slung low at the hip or to the side). Styling is body-only (jacket, vest, scarf,
wristbands, cape): nothing on the head or across the face screen (no headbands, bandanas, hats, visors). Other performers or extras: {LK['crew']}.

Each shot = ONE still (an image edit restaging Pip from a reference image), animated for 10 s (image-to-video): one
continuous camera setup, ONE camera move.

STORY SLOTS (verse/bridge): tell THAT story as a literal, readable visual narrative with Pip acting it out. A viewer must
get the WHO, the WHAT and the NUMBER at a glance, matching the lyrics sung over that shot. Not a prop on a stage: put Pip
in the story's own world (a city, a lab, an office, a vault...), tinted by the look's palette and atmosphere.
- ESTABLISHING shot: a wide shot that sets up the story world and its main players. PAYOFF shot: closer, the punchline
  or result of the story (the number revealed, the thing happening, Pip's reaction). ESTABLISHING+PAYOFF: one shot that
  starts wide and lands the result by the end of the 10 s.
- Companies and products: suggest them through colours, shapes and symbols (brand colour palettes, a flag colour, a
  sparkle, a shape), never real logos, wordmarks, real people or readable words.
- Numbers: at most ONE short number (max 4 characters, e.g. 722, 0, 1T) as a big clean physical or LED object, and only
  when the number is the point of the story. Otherwise no text at all; the captions carry the words.
- Software / apps: show them as giant floating glowing SCREENS or app panels (rounded rectangles with a thin blank
  title-bar strip, like a desktop UI), never just "windows" (that renders as building windows). AI assistants and
  models appear as a glowing SYMBOL-SHAPED character in the brand colour (e.g. a small warm coral eight-point
  starburst sparkle with no face, wings or animal features) doing the action with Pip. Software stories happen in a
  stylised modern workspace or desktop-like space, not a fantasy landscape.
- Prefer the most OBVIOUS visual metaphor a viewer instantly recognises (giant product windows, a scoreboard, a vote,
  a vault) over abstract architecture or symbolic buildings. Keep Pip big enough to read (at least a quarter of frame
  height) and interacting with the story object.
{EXAMPLES}

PERFORMANCE SLOTS (intro / chorus / outro): genre performance moments in the look above. Every chorus slot uses the SAME
hero set ({LK['hero']}; identical "setting" text) with matching choreography, varied by shot type, camera move and moment.

CINEMATIC LANGUAGE in every shot:
- shot_type: an explicit shot type. Story slots mostly wide establishing / medium / over-the-shoulder (Pip fully in frame
  head-to-feet in wide and medium shots); payoff and chorus slots may use medium close-up or close-up; extreme close-up
  rarely.
- lens: an anamorphic widescreen feel inside the vertical frame (shallow depth of field, oval bokeh, horizontal flares),
  or a rack focus from one subject to another.
- lighting: motivated (golden hour sun, neon rim light, volumetric god rays through haze, practical lamps, screens).
- atmosphere: haze, dust or light particles, rain, sparks, lens flare.
- camera: ONE clear move (slow push-in, dolly left/right, crane up/down, orbit, tracking, pull-back reveal).
- scene: the opening frame composed like a movie frame: foreground / midground / background, where Pip stands, what the
  story objects are, the light direction.
- motion: the action beat by beat across the 10 s, exactly in the form "0-3 s: ... 3-7 s: ... 7-10 s: ...", including
  what Pip does, what the story objects do, and the camera move.
- Pip's eyes are always closed happy arcs: in motion, show attention with head tilts, pointing and body language,
  never "looks at", "stares", "glances" or "eyes widen".
- Keep scene under 70 words and motion under 70 words. No captions, logos or readable words.

Lyrics (for context):
{lyr}

SLOTS:
{slot_txt}

Answer directly in your reply. Do NOT use any tools (no terminal, no files, no validation scripts).
Return JSON only, matching the schema: exactly {len(slots)} shots, ids 1..{len(slots)} matching the slots."""


def clip_prompt(shot, look):
    LK = LOOKS[look]
    outfit = (shot.get('outfit') or '').strip()
    wear = (f"Pip's styling for this shot: {outfit}. Any jacket or shirt stays OPEN so the pink chest heart shows. "
            f"Nothing on the head or face: no headband, bandana, hat, visor or sunglasses.") if outfit and outfit.lower() != 'none' else "No clothing."
    story = shot.get('story') or 0
    kind = (f"a STORY shot ({shot.get('beat', 'establishing')}): the scene must read at a glance as the story it shows"
            if story else f"a PERFORMANCE shot ({shot.get('beat', '')}) in the {LK['label']} look")
    extras = (f"Any other performers or extras are {LK['crew']}, so Pip stands out." if not story else
              "No band, musicians or stage in this shot: only Pip and the story's own objects and characters.")
    framing = ("Pip fully in frame head-to-feet" if not re.search(r'close', shot.get('shot_type', ''), re.I)
               else "Pip's face screen, closed arc eyes and pink chest heart clearly in frame")
    return f"""You are generating ONE shot of a high-budget, cinematic {LK['label']} music video starring our mascot
"Pip". This is {kind}. Use your media tools directly. Do not use web search, do not spawn subagents, do not run shell
commands, and make NO extra or retry generations: exactly ONE image_edit call followed by exactly ONE image_to_video call.
If a tool call fails, report the error verbatim and stop.

{G.PIP_DESC.replace(' No clothing.', '')} {wear}
{extras}

Step 1: call image_edit with image = ["{G.PIP_REF}"] and a prompt that re-stages this exact character (same design,
proportions, colours, flat 2D cartoon style with thick dark-navy outlines; restate Pip's traits: white egg body, bunny
ears with pink insides, yellow antenna ball, navy face screen with cyan closed arc eyes, pink blush, the visible pink
chest heart, short stubby legs with round feet) inside a cinematic movie frame:
{shot.get('shot_type', 'wide establishing')} shot. {shot['scene']} Setting: {shot.get('setting', '')}. Story objects:
{shot.get('props', '')}. Lens: {shot.get('lens', 'anamorphic widescreen feel, shallow depth of field')}. Lighting:
{shot.get('lighting', '')}. Atmosphere: {shot.get('atmosphere', '')}. Filmic colour grade, rich detailed painterly
background, depth and scale. Vertical 9:16 frame filled edge to edge (no borders, no letterbox or dark bands), {framing}.
No logos, no captions, no readable words (one short clean number only if the scene above asks for it).

Step 2: call image_to_video on the image produced by step 1 with duration=10, resolution_name="720p", and this prompt:
"Cinematic shot, camera: {shot.get('camera', LK['default_camera'])}. {shot['motion']} Keep Pip on-model throughout:
the dark-navy face screen stays visible for all 10 s (never a white or drawn-on face) and the cyan eyes stay CLOSED
happy arcs (^ ^) the whole time, never opening into round eyes,
short stubby legs, pink heart on chest visible, bunny ears, flat 2D cartoon style. Filmic, no text."

Step 3: reply with the two saved file paths. Do nothing else."""
