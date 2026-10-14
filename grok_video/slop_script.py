"""slopcore v3 planner: a line-by-line SCRIPT. Every sung line gets a beat (the exact line, what it means from stories.md,
one literal, instantly readable visual acted out by the recurring cast) split into 1-3 shots that each start on a sung
word; chorus lines keep one idea that escalates on every repeat. A second cheap call scores every shot 1-5 on "would a
viewer connect this picture to the line being sung?" and rewrites anything under 4. The result is converted into the
slopcore segments format (so jobs / generation / render are shared) and written to work/script.md."""
import json, os, re, time
import common_gv as G
import real_plan as RP
import slop_plan as SP
from plan_gen import run_grok_text, _extract_json

PLANNER_VERSION = 'script-1'
SCRIPT_FIRST_S, SCRIPT_MAX_S = 570, 780   # call 1 attempt-1 cap; total planner cap (attempt 2 + the review). Measured 9 Oct: 477 s + 181 s
REVIEW_MAX_S = 200
N_DROPS = 2


# ------------------------------------------------------------------------------------------------ slots
def _end_slots(segs):
    """P6: the outro tail, every outro line and every line of the LAST chorus occurrence."""
    ch = [s for s in segs if s.get('kind') == 'chorus']
    last = max((s.get('occ') or 1) for s in ch) if ch else None
    return [s for s in segs if s.get('kind') in ('outro', 'outro_tail')
            or (s.get('kind') == 'chorus' and (s.get('occ') or 1) == last)]


def _force_end_clips(slots, by):
    """P6: at least one clip on each end slot (outro tail, outro lines, last chorus). Returns clips added; these may go
    a few over n_clips (the meter budget in cine_real.generate still trims the lowest-priority clips)."""
    n = 0
    for sl in _end_slots(slots):
        shots = (by.get(sl['seg']) or {}).get('shots') or []
        if shots and not any(sh.get('_clip') for sh in shots):
            shots[0]['_clip'] = True
            sl['clips'] = sl.get('clips', 0) + 1
            n += 1
    return n


LONG_SHOTS = __import__('os').environ.get('GV_LONG_SHOTS', '1') == '1'   # 14 Oct: fewer, longer shots


def script_slots(lines, n_clips=45, max_images=95):
    """Song order: hook, every sung line (max shots 2-3 by length), drops after the intro / choruses, outro tail.
    'images' here is the MAX; the planner returns 1..max and apply() sets the real counts and the clips."""
    segs = [{'seg': 'hook', 'kind': 'hook', 'text': '', 'section': 'hook', 'images': 2, 'clips': 0}]
    nd = 0
    for i, ln in enumerate(lines):
        k = ln['kind']
        nw = len(ln.get('words') or ln['text'].split())
        mx = (1 if k == 'chorus' or nw <= 6 else 2) if LONG_SHOTS else (2 if k == 'chorus' or nw <= 4 else 3)
        segs.append({'seg': RP.line_id(ln), 'kind': k, 'text': ln['text'], 'section': ln['section'],
                     'line_no': ln['line_no'], 'occ': ln['section_occ'], 'images': mx, 'clips': 0,
                     'words': [w[0] for w in (ln.get('words') or [[t] for t in ln['text'].split()])]})
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        end_sec = not nxt or (nxt['section'], nxt['section_occ']) != (ln['section'], ln['section_occ'])
        if end_sec and nxt and k in ('intro', 'chorus') and nd < N_DROPS:
            nd += 1
            segs.append({'seg': f'drop{nd}', 'kind': 'drop', 'text': '', 'section': 'drop', 'images': 2, 'clips': 0})
    while nd < N_DROPS:
        nd += 1
        segs.append({'seg': f'drop{nd}', 'kind': 'drop', 'text': '', 'section': 'drop', 'images': 2, 'clips': 0})
    segs.append({'seg': 'outro_tail', 'kind': 'outro_tail', 'text': '', 'section': 'outro', 'images': 3, 'clips': 0})
    for s in _end_slots(segs):                         # P6: the last chorus and the outro get up to 3 shots each
        s['images'] = max(s['images'], 2 if LONG_SHOTS else 3)
    # keep the planner's maximum under the image budget: trim third shots from late lines first
    while sum(s['images'] for s in segs) > max_images:
        end = {id(s) for s in _end_slots(segs)}
        c = max([s for s in segs if s['images'] > 1 and id(s) not in end] or [s for s in segs if s['images'] > 1],
                key=lambda s: (s['images'], segs.index(s)))
        c['images'] -= 1
    for s in segs:
        s['hero'] = False
    return segs


# ------------------------------------------------------------------------------------------------ call 1: the script
SHOT = {"type": "object", "properties": {
    "word": {"type": "integer", "description": "index (0-based) of the sung word this shot starts on"},
    "prompt": {"type": "string", "description": "who does what, where, shot size, light (25-50 words)"},
    "cast": {"type": "array", "items": {"type": "string"}},
    "shot": {"type": "string"},
    "move": {"type": "string", "enum": ["push_in", "pull_out", "pan_left", "pan_right", "shake", "drift"]},
    "motion": {"type": "string", "description": "the physical action during the 3 s clip"},
    "score": {"type": "integer", "description": "self-check 1-5: would a viewer connect this picture to the line?"}},
    "required": ["word", "prompt", "cast", "move", "motion", "score"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "cast": SP.SCHEMA['properties']['cast'],
        "beats": {"type": "array", "items": {"type": "object", "properties": {
            "seg": {"type": "string"},
            "meaning": {"type": "string", "description": "what the line means: the AI story behind it (max 25 words)"},
            "visual": {"type": "string", "description": "the ONE literal visual gag that acts the line out (max 30 words)"},
            "shots": {"type": "array", "items": SHOT}},
            "required": ["seg", "meaning", "visual", "shots"]}},
        "display": SP.SCHEMA['properties']['display'],
        "pip": SP.SCHEMA['properties']['pip'],
        "cameo": {"type": "string"}},
    "required": ["cast", "beats", "display", "pip", "cameo"]}


def script_prompt(day, look, slots, L):
    LK = SP.SLOP_LOOKS[look]
    genre, style = G.genre_of(day)
    title = G.read(os.path.join(day, 'title.txt'))
    stories = G.story_list(day)
    st = '\n'.join(f"{s['idx']}. {s['text']} (sung in: {s['section']} lines {s['lines']}) :: {s['detail'][:500]}" for s in stories)
    rows = []
    for sl in slots:
        if sl['kind'] in ('hook', 'drop', 'outro_tail'):
            what = {'hook': 'HOOK: instrumental intro, frame 0 of the video: set up the song title and the first story',
                    'drop': 'DROP: instrumental break: the previous chorus idea at its most absurd scale',
                    'outro_tail': 'OUTRO TAIL: instrumental ending: a callback to the hook, lights going out'}[sl['kind']]
            rows.append(f"SEG {sl['seg']} | {what} | shots: 1-{sl['images']}")
            continue
        tag = sl['section'] + (f" (chorus repeat #{sl['occ']}: escalate)" if sl['kind'] == 'chorus' else '')
        words = ' '.join(f"{i}:{w}" for i, w in enumerate(sl['words']))
        rows.append(f"SEG {sl['seg']} | {tag} | line: \"{sl['text']}\" | words: {words} | shots: 1-{sl['images']}")
    sung = [ln for ln in L if ln.get('words')]
    disp = '\n'.join(f"{RP.line_id(ln)}: {json.dumps([w[0] for w in ln['words']], ensure_ascii=False)}" for ln in sung)
    lyr = [s['seg'] for s in slots if s['kind'] not in ('hook', 'drop', 'outro_tail')]
    return f"""You are the writer-director of a viral "slopcore" AI-news music video for the song "{title}" ({genre or '?'};
{style}). Vertical 9:16, about 1 s cuts. Every shot is generated by a photoreal image model from your prompt; the first
shot of each line also becomes a 3 s video clip. The lyric line is shown as a subtitle while it is sung.

THE ONE RULE: the last cut looked great but "didn't seem related to the lyrics". This time EVERY SHOT MUST VISIBLY ACT
OUT THE WORDS BEING SUNG AT THAT MOMENT. A viewer with the sound off, reading the subtitle, must instantly get the link.

WRITE A LINE-BY-LINE SCRIPT. For every lyric segment below:
1. "meaning": what the line is about (the AI news behind it, from STORIES).
2. "visual": ONE concrete, literal, funny visual gag that acts out the line's key words with the recurring cast.
   Literal beats metaphorical: show the nouns and verbs. Examples:
   - "Ultrafast hits Sol, eight times the pace": A's laptop literally on fire while B's printer fires pages out eight at
     a time into the air.
   - "Rate limits laugh at the Pro five-hundred case": a velvet-rope bouncer laughing in A's face as she holds out a
     gold card, a queue of interns behind her.
   - "Lights on, charts light up": A flips a giant wall switch and every chart on the office wall lights up like a
     stadium scoreboard.
   - "Robots learn the pour": a boxy robot carefully pouring tea into a cup held by a terrified B.
   NEVER generic shots: people standing, staring, smiling, nodding, walking through an office, looking at a screen.
   Something must HAPPEN that matches the words.
3. "shots": 1 to the stated max. Each shot starts on a sung word ("word" = its index in that line's word list) and
   shows THAT word's noun or verb: shot 1 starts on word 0 and shows the line's main gag; a 2nd/3rd shot starts on a
   later key word (a number, a brand, a verb) and shows that word (a close-up insert or the payoff/reaction).
   Lines of 6+ words usually get 2 shots, so the second key word is also seen when it is sung.
   Shots of the same line share one location and situation (they are cuts within one gag).
4. "score": rate each shot 1-5 honestly: "would a viewer connect this picture to the line being sung?" Rewrite any
   shot you would rate under 4 before answering.

CHORUS: every chorus line has ONE simple visual idea that comes back on every repeat and ESCALATES: repeat #1 = A and
a few people, #2 = the whole office/street, #3 = a stadium/city-scale crowd doing the same thing (same gag, bigger).
The outro lines call back to the hook. HOOK / DROP / OUTRO TAIL are instrumental: follow their notes.

CAST: one protagonist A (in about half of all shots, always DOING the gag, never just posing), up to two supporting
characters B and C who react or take part. ORIGINAL people (never a celebrity, a named real person from the news, or
anyone's likeness), described precisely. Write "A"/"B"/"C" in prompts; never re-describe their looks. Max 2 cast per shot.
Anyone who appears in more than one shot must be a cast member (use D if needed) and listed in "cast" each time;
unlettered extras appear in one shot only. The final sung line and outro pay off the hook's opening gag (same place and
prop, completed or reversed).
Deadpan: everyone treats the absurd gag as completely normal.

PROMPTS: 25-50 words: who, doing what (mid-action), where, shot size, light, one imperfection. Look (appended
automatically, do not repeat): {LK['label']}; real places, imperfect light, NOT glossy, NOT studio, NOT surreal sculpture.
Genre energy: {LK['energy']}.
NO TEXT IN ANY IMAGE: no words, letters, numbers, signs, logos, readable screens or documents; show numbers physically
(eight pages, a "66" made of people is NOT allowed - use eight objects, a counter needle, a podium). The subtitle does it.
ORIGINAL DESIGNS ONLY: no famous robots/characters/mascots; robots are new designs (boxy service robot, white humanoid
with a light-bar face, plain robot arm). "motion": one clear physical action for the 3 s clip plus a simple camera move.

STORIES:
{st}

SEGMENTS (in song order; answer one beat per segment, same seg ids):
{chr(10).join(rows)}

DISPLAY TYPE: one token per sung word, in order, for each line below. Fix brand/product spellings and use numerals
("GPT-6.1", "Claude Code", "66.1", "8x", "$1,000"); merge words by giving "" to the following word(s); keep the token
count identical. "accent": usually exactly 1 punch token (the key noun/verb/number), never more than 2.
{disp}

PIP: our mascot is a small physical vinyl toy robot (white, bunny ears; do not describe it further). Pick exactly 2
lyric segments from: {', '.join(lyr)} where the toy fits the line's gag (e.g. the toy on the dashboard for "cars learn
the road", the toy on the desk next to the burning laptop) and describe that scene in one sentence. CAMEO: one sentence
for the final shot: the toy alone in the last location after everyone has gone.

{_tone_block()}{_cast_block()}Answer directly. Do NOT use any tools. Return JSON only, matching the schema."""


def _cast_block():
    import slop_real as SR
    return SR.cast_block()


def _tone_block():
    import tone as T
    if T.CURRENT.get('tone', 'edgy') == 'playful':
        return ("TONE OVERRIDE (this song is PLAYFUL: slopcore cool with warmth; this beats anything above about AI news or "
                "menace): photoreal, a natural film look with real-world colour (no pastel wash, at most one accent "
                "colour), deadpan-cool cheek, mundane-meets-absurd literal gags, the lead owns the lens with mixed "
                "expressions (cool, smirking, deadpan, laughing in at most ~30% of her shots), varied light (daylight, "
                "golden hour, evening party, neon). Warm and affectionate: never menace, cults, judges, hospitals, robot "
                "formations or anything creepy; no glitter overload, candy sets or constant grinning. ABSOLUTELY NO blood, "
                "red liquid, wounds, organs, organ-like tissue or medical gore; an organ in the lyrics (e.g. a placenta) is "
                "only ever a cute plush heart / VIP-badge character or an abstract glowing heart. "
                f"Note from the owner: {T.CURRENT.get('note') or '(none)'}\n\n")
    if T.CURRENT.get('tone', 'edgy') != 'joyful':
        return ''
    return ("TONE OVERRIDE (this song is JOYFUL; this beats anything above about AI news, deadpan or 'NOT glossy'): bright, "
            "warm, funny, wholesome-cute; sunshine and pastel colours, real warm smiles, sparkle, playful slapstick, "
            "sing-along joy; the lead sings and dances to the camera. Never menace, cults, judges, hospitals, night or "
            "rain as the default, dark interrogation light, robot formations, anything creepy. ABSOLUTELY NO blood, red "
            "liquid, wounds, organs, organ-like tissue or medical gore; an organ in the lyrics (e.g. a placenta) is only "
            "ever a cute sparkly plush heart / VIP-badge character or an abstract glowing heart. "
            f"Note from the owner: {T.CURRENT.get('note') or '(none)'}\n\n")


# ------------------------------------------------------------------------------------------------ call 2: the critic
REVIEW_SCHEMA = {"type": "object", "properties": {"reviews": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "score": {"type": "integer"}, "problem": {"type": "string"},
    "prompt": {"type": "string", "description": "rewrite (only when score < 4)"},
    "motion": {"type": "string"}, "new_score": {"type": "integer"}},
    "required": ["id", "score"]}}}, "required": ["reviews"]}


def review_prompt(plan, slots):
    text = {s['seg']: s for s in slots}
    rows = []
    for b in plan['beats']:
        sl = text.get(b['seg'])
        if not sl:
            continue
        line = sl['text'] or {'hook': '(instrumental intro)', 'drop': '(instrumental break)', 'outro_tail': '(instrumental ending)'}.get(sl['kind'], '')
        for k, sh in enumerate(b['shots']):
            w = sl.get('words') or []
            on = w[min(max(int(sh.get('word') or 0), 0), len(w) - 1)] if w else '-'
            rows.append(f"{b['seg']}|{k} | sung: \"{line}\" (shot starts on \"{on}\") | news: {b.get('meaning', '')} | "
                        f"picture: {sh['prompt']}")
    return f"""You are a harsh music-video script editor. Each row is one shot of a lyric video: the line being sung while the
shot is on screen (shown as a subtitle) and the picture. Score each shot 1-5: "would a viewer with the sound off,
reading the subtitle, instantly connect this picture to the words being sung?"
The "news" column says what the line is about (product names in the lyric are AI products, e.g. "Sol" is a model,
not the sun): a picture that acts out the news meaning is a valid link - do NOT replace a clear gag with a pun on a
product name. 5 = the words are literally acted out; 4 = clear link; 3 = vague/mood only; 2 = generic (people standing, staring,
walking, smiling, looking at screens); 1 = unrelated. Instrumental rows (no lyric): score on whether they continue the
song's story; 4 is fine for a good callback.
For every shot under 4, write a replacement "prompt" (25-50 words, same cast letters A/B/C and the same location as
its line, a literal funny gag that acts out the sung words, no text/letters/numbers/logos in the image, original
people only) and a "motion" (one physical action for a 3 s clip), plus "new_score" for your rewrite. Keep "problem"
under 12 words. Return JSON only: one review per row, "id" exactly as given.

{chr(10).join(rows)}

Answer directly. Do NOT use any tools."""


def _run(pf, work, schema, tmo):
    r = run_grok_text(pf, work, schema=schema, timeout=tmo)
    return _extract_json(r.get('text') or '')


def plan(day, work, look, slots, L, deadline=None, reserve_s=17 * 60, force=False, reuse=False):
    path = os.path.join(work, 'real_plan.json')
    key = {'version': PLANNER_VERSION, 'look': look, 'slots': [(s['seg'], s['images']) for s in slots]}
    import tone as T
    if T.CURRENT.get('tone', 'edgy') != 'edgy':
        key.update(tone=T.CURRENT['tone'], note=T.CURRENT.get('note', ''))
    p = G.load_json(path)
    if p and not force and (p.get('key') == json.loads(json.dumps(key)) or (reuse and p.get('beats'))):
        G.log("planner: cached real_plan.json (script)")
        return p
    pf = os.path.join(work, 'script_prompt.txt')
    open(pf, 'w').write(script_prompt(day, look, slots, L))
    res, t_first = None, time.time()

    def budget(cap):
        t = int(min(cap, SCRIPT_MAX_S - (time.time() - t_first)))
        if deadline:
            t = int(min(t, deadline - time.time() - reserve_s))
        return t
    for attempt in (1, 2):
        if os.environ.get('CINE_REAL_FAIL') == 'plan':
            break
        tmo = budget(SCRIPT_FIRST_S if attempt == 1 else SCRIPT_MAX_S)
        if tmo < 150:
            G.log(f"script: skipped attempt {attempt}, not enough time left in the budget")
            break
        t0 = time.time()
        try:
            res = _run(pf, work, SCHEMA, tmo)
            if res and res.get('beats'):
                G.log(f"script: {time.time()-t0:.0f}s (attempt {attempt}), {len(res['beats'])} beats, "
                      f"{sum(len(b.get('shots') or []) for b in res['beats'])} shots")
                break
            G.log(f"script attempt {attempt}: no beats in reply"); res = None
        except Exception as e:
            G.log(f"script attempt {attempt} failed: {e!r}"[:300]); res = None
    if not res:
        G.log("WARNING: script planner failed; using the template plan")
        fb = SP.fallback_plan(day, slots, L, look)
        res = {'cast': fb['cast'], 'display': [], 'pip': fb['pip'], 'cameo': fb['cameo'], 'fallback': True,
               'beats': [{'seg': s['seg'], 'meaning': '', 'visual': '(template)',
                          'shots': [dict(im, word=0, score=0) for im in s['images']]} for s in fb['segments']]}
    _clean(res, slots)
    # call 2: the critic (only with time left; the self-scores stand otherwise)
    tmo = budget(REVIEW_MAX_S)
    if not res.get('fallback') and tmo >= 60 and os.environ.get('CINE_REAL_FAIL') != 'plan':
        rf = os.path.join(work, 'review_prompt.txt')
        open(rf, 'w').write(review_prompt(res, slots))
        t0 = time.time()
        try:
            rv = _run(rf, work, REVIEW_SCHEMA, tmo) or {}
            n = apply_reviews(res, rv.get('reviews') or [])
            G.log(f"script review: {time.time()-t0:.0f}s, {len(rv.get('reviews') or [])} shots scored, {n} rewritten")
            res['review'] = {'secs': round(time.time() - t0), 'n': len(rv.get('reviews') or []), 'rewritten': n}
        except Exception as e:
            G.log(f"script review failed (self-scores kept): {e!r}"[:300])
            res['review'] = {'error': repr(e)[:200]}
    else:
        G.log(f"script review skipped ({'template plan' if res.get('fallback') else f'only {tmo}s left'})")
        res['review'] = {'skipped': True}
    res['key'] = key
    res['look'] = look
    res['planner'] = PLANNER_VERSION
    res['secs'] = round(time.time() - t_first)
    G.save_json(res, path)
    return res


def _clean(res, slots):
    """One beat per slot, shots capped at the slot max, word indices sorted/clamped, shot 0 on word 0."""
    by = {}
    for b in res.get('beats') or []:
        if isinstance(b, dict) and b.get('seg') and b['seg'] not in by:
            by[b['seg']] = b
    beats = []
    for sl in slots:
        b = by.get(sl['seg']) or {'seg': sl['seg'], 'meaning': '', 'visual': '', 'shots': []}
        shots = [s for s in (b.get('shots') or []) if isinstance(s, dict) and (s.get('prompt') or '').strip()][:sl['images']]
        nw = len(sl.get('words') or [])
        last = -1
        for k, s in enumerate(shots):
            try:
                w = int(s.get('word') or 0)
            except (TypeError, ValueError):
                w = 0
            w = 0 if k == 0 else max(last + 1, min(w, max(nw - 1, 0)))
            s['word'] = w
            last = w
            s['self_score'] = s.pop('score', None)
            s.setdefault('cast', [])
            s.setdefault('move', 'push_in')
        if nw:
            shots = [s for k, s in enumerate(shots) if k == 0 or s['word'] < nw]
        b['shots'] = shots
        beats.append(b)
    res['beats'] = beats


def apply_reviews(res, reviews):
    by = {b['seg']: b for b in res['beats']}
    n = 0
    for r in reviews:
        try:
            seg, k = r['id'].rsplit('|', 1)
            sh = by[seg.strip()]['shots'][int(k)]
        except (KeyError, ValueError, IndexError, AttributeError):
            continue
        sh['score'] = r.get('score')
        if r.get('problem'):
            sh['problem'] = r['problem']
        if (r.get('score') or 5) < 4 and (r.get('prompt') or '').strip():
            sh['orig_prompt'] = sh['prompt']
            sh['prompt'] = r['prompt'].strip()
            if (r.get('motion') or '').strip():
                sh['motion'] = r['motion'].strip()
            sh['rewritten'] = True
            sh['new_score'] = r.get('new_score')
            n += 1
    return n


# ------------------------------------------------------------------------------------------------ to slopcore segments
def apply(plan_, slots, n_clips):
    """Set each slot's real image count, allocate the clips (the first shot of every line first, then hook/drops,
    then second shots of chorus #1-2 and long verse lines), and build plan['segments'] for slop_real.build_jobs."""
    by = {b['seg']: b for b in plan_['beats']}
    for sl in slots:
        sl['images'] = len((by.get(sl['seg']) or {}).get('shots') or [])
        sl['clips'] = 0
    order = []
    order += [(0, sl) for sl in slots if sl['kind'] not in ('hook', 'drop', 'outro_tail')]          # every line's gag
    order += [(0, sl) for sl in slots if sl['kind'] in ('hook', 'drop')]
    order += [(1, sl) for sl in slots if sl['kind'] == 'hook']
    order += [(1, sl) for sl in slots if sl['kind'] == 'chorus' and (sl.get('occ') or 1) <= 2]
    order += [(1, sl) for sl in slots if sl['kind'] in ('verse', 'bridge')]
    order += [(0, sl) for sl in slots if sl['kind'] == 'outro_tail']
    order += [(1, sl) for sl in slots if sl['kind'] in ('drop', 'chorus', 'intro', 'outro')]
    used = 0
    flagged = any(isinstance(sh, dict) and sh.get('kind') in ('clip', 'still') for b in plan_['beats'] for sh in b['shots'])
    if flagged:                                        # the director (Opus) chose clip/still per shot: honour it
        for sl in slots:
            b = by.get(sl['seg']) or {'shots': []}
            n_line = 0
            for sh in b['shots']:
                want = sh.get('kind') == 'clip' and used < n_clips and n_line < 2
                sh['_clip'] = bool(want)
                used += 1 if want else 0
                n_line += 1 if want else 0
            sl['clips'] = n_line
        # under budget: top up with each line's first shot, then the hook/drops
        for k, sl in order:
            if used >= n_clips:
                break
            b = by.get(sl['seg']) or {'shots': []}
            if k < len(b['shots']) and not b['shots'][k].get('_clip') and sl['clips'] < 2:
                b['shots'][k]['_clip'] = True
                sl['clips'] += 1
                used += 1
        used += _force_end_clips(slots, by)
        for sl in slots:
            sl['hero'] = sl['clips'] > 0
        plan_['segments'] = [{'seg': b['seg'], 'location': b.get('visual', ''), 'images': b['shots']} for b in plan_['beats']]
        return used
    for k, sl in order:
        if used >= n_clips:
            break
        if sl['images'] > k and sl['clips'] == k:
            sl['clips'] = k + 1
            used += 1
    for sl in slots:
        sl['hero'] = sl['clips'] > 0
    plan_['segments'] = [{'seg': b['seg'], 'location': b.get('visual', ''), 'images': b['shots']} for b in plan_['beats']]
    return used


def write_script_md(plan_, slots, path):
    def esc(s):
        return str(s or '').replace('|', '/').replace('\n', ' ')
    by = {b['seg']: b for b in plan_['beats']}
    rv = plan_.get('review') or {}
    sc = [s for b in plan_['beats'] for s in b['shots']]
    crit = [s.get('score') for s in sc if isinstance(s.get('score'), int)]
    final = [(s.get('new_score') if s.get('rewritten') else s.get('score')) for s in sc]
    final = [x for x in final if isinstance(x, int)]
    out = [f"# Script ({plan_.get('planner')}, look {plan_.get('look')})", '',
           f"Planner {plan_.get('secs')} s; review: {json.dumps(rv)}", '',
           f"Shots: {len(sc)}. Critic score >= 4 before rewrites: {sum(1 for x in crit if x >= 4)}/{len(crit)}"
           + (f" ({100 * sum(1 for x in crit if x >= 4) / len(crit):.0f} %)" if crit else '')
           + f"; after rewrites (critic's score for its rewrite): {sum(1 for x in final if x >= 4)}/{len(final)}"
           + (f" ({100 * sum(1 for x in final if x >= 4) / len(final):.0f} %)" if final else ''), '',
           '## Cast', '']
    for c in plan_.get('cast') or []:
        out.append(f"- **{c.get('id')}** ({esc(c.get('role'))}): {esc(c.get('description'))}")
    out += ['', f"Pip: {json.dumps(plan_.get('pip'))}  ", f"Cameo: {esc(plan_.get('cameo'))}", '', '## Beats', '']
    for sl in slots:
        b = by.get(sl['seg'])
        if not b:
            continue
        line = sl['text'] or f"({sl['kind']}, instrumental)"
        out.append(f"### {sl['seg']}: \"{esc(line)}\"")
        out.append(f"- meaning: {esc(b.get('meaning'))}")
        out.append(f"- visual: {esc(b.get('visual'))}")
        out.append('')
        out.append('| # | on word | clip | self | critic | final | shot |')
        out.append('|---|---|---|---|---|---|---|')
        w = sl.get('words') or []
        for k, s in enumerate(b['shots']):
            on = w[s['word']] if w and s['word'] < len(w) else '-'
            fin = s.get('new_score') if s.get('rewritten') else s.get('score')
            txt = esc(s['prompt']) + (f" <br>*(rewritten; was: {esc(s.get('orig_prompt'))[:160]}... problem: {esc(s.get('problem'))})*"
                                      if s.get('rewritten') else (f" <br>*({esc(s.get('problem'))})*" if s.get('problem') else ''))
            isclip = s['_clip'] if '_clip' in s else k < sl.get('clips', 0)
            cine = ', '.join(x for x in (s.get('framing'), s.get('lens'), s.get('light')) if x)
            if s.get('rewritten'):                  # the rewrite replaces the prompt; the old cinematography is not used
                txt += f" <br>*motion: {esc(s.get('motion'))}*"
            elif cine:
                txt += f" <br>*cinematography: {esc(cine)}; motion: {esc(s.get('motion'))}; edit: {esc(s.get('edit'))}*"
            out.append(f"| {k} | {esc(on)} | {'clip' if isclip else 'still'} | {s.get('self_score') or '-'} | "
                       f"{s.get('score', '')} | {fin if fin is not None else ''} | {txt} |")
        out.append('')
    open(path, 'w').write('\n'.join(out))
