"""slopcore v4 planner: Claude Opus (Claude Code CLI, the owner's Max plan, headless) as writer-director.
Call 1 writes the cast bible, a line-by-line script (meaning + one literal gag readable with the sound off) and a
storyboard of word-anchored shots (image prompt, motion, camera, lens, light, framing, edit note, clip or still).
Call 2 (script doctor) critiques every shot and rewrites weak ones. The JSON is validated and repaired once. Any
failure (auth, limits, timeout, bad JSON) falls back to the Grok script planner (slop_script), then the template.
Output = the slop_script plan format, so jobs / generation / the line-locked edit / render are shared."""
import json, os, re, shutil, subprocess, time
import common_gv as G
import real_plan as RP
import slop_plan as SP
import slop_script as SS

PROMPTS_V5 = os.environ.get('OPUS_PROMPTS', 'v5') != 'v4'
PLANNER_VERSION = 'opus-2' if PROMPTS_V5 else 'opus-1'   # opus-2 = v5 prompts (Opus self-review 9 Oct); OPUS_PROMPTS=v4 -> old prompts
CLAUDE = os.environ.get('CLAUDE_BIN', '/home/box/.local/bin/claude')
TOKEN_FILE = os.path.expanduser('~/.claude_oauth_token')
OPUS_MAIN_S, OPUS_DOCTOR_S, OPUS_TOTAL_S = 450, 150, 600      # v5 prompt measured 316 s (+ doctor ~30-60 s); v4 285 s
REFS = ['04_voldemort2x_saysi_sheet01.jpg', '05_javif4_underclass_sheet01.jpg', '06_dvorahfr_theheir_sheet01.jpg',
        '01_donaldjewkes_sheet01.jpg']
PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts')
PROMPTS = os.environ.get('OPUS_PROMPTS', 'v5')


def _template(name):
    """prompts/opus_<name>_<tone>.txt for a non-edgy tone, else prompts/opus_<name>_<PROMPTS>.txt (edgy = v5), or None
    (-> the built-in v4 prompt)."""
    import tone as T
    if T.CURRENT.get('tone', 'edgy') != 'edgy':
        f = os.path.join(PROMPT_DIR, f"opus_{name}_{T.CURRENT['tone']}.txt")
        if os.path.exists(f):
            return open(f).read()
    f = os.path.join(PROMPT_DIR, f'opus_{name}_{PROMPTS}.txt')
    return open(f).read() if PROMPTS != 'v4' and os.path.exists(f) else None


def _cast_block():
    import slop_real as SR
    return SR.cast_block()


def _fill(tpl, vals):
    for k, v in vals.items():
        tpl = tpl.replace('{{' + k + '}}', str(v))
    return tpl
SHEETS = '/workspace/slopcore/sheets'
VIBE = '/workspace/slopcore/vibe.md'
ANALYSIS = '/workspace/slopcore/analysis.md'

SHOT = {"type": "object", "properties": {
    "word": {"type": "integer", "description": "0-based index of the sung word the shot cuts in on"},
    "kind": {"type": "string", "enum": ["clip", "still"]},
    "prompt": {"type": "string", "description": "image prompt: who does what, where (30-60 words)"},
    "cast": {"type": "array", "items": {"type": "string"}},
    "framing": {"type": "string"}, "lens": {"type": "string"}, "light": {"type": "string"},
    "move": {"type": "string", "enum": ["push_in", "pull_out", "pan_left", "pan_right", "shake", "drift"]},
    "motion": {"type": "string", "description": "the physical action in the 3 s clip"},
    "camera": {"type": "string", "description": "camera move for the clip"},
    "edit": {"type": "string", "description": "edit note (cut on the word, hold, smash cut...)"}},
    "required": ["word", "kind", "prompt", "cast", "framing", "lens", "light", "move", "motion", "camera", "edit"]}
SCHEMA = {"type": "object", "properties": {
    "cast": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "role": {"type": "string"},
        "description": {"type": "string", "description": "age, build, face, hair, exact wardrobe (25-45 words)"}},
        "required": ["id", "role", "description"]}},
    "beats": {"type": "array", "items": {"type": "object", "properties": {
        "seg": {"type": "string"}, "meaning": {"type": "string"}, "visual": {"type": "string"},
        "shots": {"type": "array", "items": SHOT}}, "required": ["seg", "meaning", "visual", "shots"]}},
    "display": SP.SCHEMA['properties']['display'],
    "pip": SP.SCHEMA['properties']['pip'],
    "cameo": {"type": "string"}},
    "required": ["cast", "beats", "display", "pip", "cameo"]}
DOCTOR_SCHEMA = {"type": "object", "properties": {"reviews": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "score": {"type": "integer"}, "problem": {"type": "string"},
    "prompt": {"type": "string"}, "motion": {"type": "string"}, "new_score": {"type": "integer"}},
    "required": ["id", "score"]}}}, "required": ["reviews"]}


def _env():
    env = dict(os.environ)
    try:
        env['CLAUDE_CODE_OAUTH_TOKEN'] = open(TOKEN_FILE).read().strip()      # never logged
    except OSError:
        pass
    return env


def run_claude(prompt_file, cwd, schema, timeout, tools='Read', effort='medium'):
    """Headless Claude Code call. Returns (structured_output or parsed JSON, meta). Raises on failure."""
    cmd = [CLAUDE, '-p', open(prompt_file).read(), '--model', 'opus', '--output-format', 'json',
           '--no-session-persistence', '--restricted', '--tools', tools, '--effort', effort,
           '--json-schema', json.dumps(schema)]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    meta = {'secs': round(time.time() - t0), 'rc': r.returncode}
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"claude rc={r.returncode}: no JSON reply ({(r.stderr or r.stdout)[-300:]!r})")
    meta.update(cost_usd=d.get('total_cost_usd'), turns=d.get('num_turns'), is_error=d.get('is_error'),
                subtype=d.get('subtype'), api_error=d.get('api_error_status'))
    if d.get('is_error') or r.returncode != 0:
        raise RuntimeError(f"claude error: {d.get('subtype')} {d.get('api_error_status')} {str(d.get('result'))[:300]!r}")
    out = d.get('structured_output')
    if not out:
        out = SS._extract_json(d.get('result') or '') if hasattr(SS, '_extract_json') else None
    meta['raw'] = (d.get('result') or '')[:200000]
    return out, meta


def opus_prompt(day, look, slots, L, timed):
    LK = SP.SLOP_LOOKS[look]
    genre, style = G.genre_of(day)
    title = G.read(os.path.join(day, 'title.txt'))
    stories = G.story_list(day)
    st = '\n'.join(f"{s['idx']}. {s['text']} (sung in: {s['section']} lines {s['lines']}) :: {s['detail'][:600]}" for s in stories)
    tl = {RP.line_id(ln): ln for ln in (timed or []) if ln.get('words')}
    rows = []
    for sl in slots:
        if sl['kind'] in ('hook', 'drop', 'outro_tail'):
            import tone as T
            joy = T.CURRENT.get('tone') == 'joyful'
            pl = T.CURRENT.get('tone') == 'playful'
            what = {'hook': ('HOOK: instrumental intro, the first frames (scroll-stopper: the most joyful, eye-popping image of the song, planting the payoff)' if joy else 'HOOK: instrumental intro, the first frames (scroll-stopper: the boldest, coolest image of the song, planting the payoff)' if pl else None) or ('HOOK: instrumental intro, the first frames (scroll-stopper: the most extreme image of the song, planting the payoff)' if _template('director') else 'HOOK: instrumental intro, the first frames (scroll-stopper; set up the song and the first story)'),
                    'drop': 'DROP: instrumental break after a chorus (the chorus gag at its most absurd scale)',
                    'outro_tail': ('OUTRO TAIL: instrumental ending (the happiest payoff of the hook: the biggest smile, sparkle and confetti)' if joy else 'OUTRO TAIL: instrumental ending (payoff of the hook at full scale, warm and triumphant)' if pl else None) or ('OUTRO TAIL: instrumental ending (payoff of the hook at full scale)' if _template('director') else 'OUTRO TAIL: instrumental ending (callback to the hook; lights going out)')}[sl['kind']]
            rows.append(f"SEG {sl['seg']} | {what} | shots: 1-{sl['images']}")
            continue
        ln = tl.get(sl['seg'])
        if ln and all(w[1] is not None for w in ln['words']):
            words = ' '.join(f"{i}:{w[0]}@{w[1]:.2f}s" for i, w in enumerate(ln['words']))
        else:
            words = ' '.join(f"{i}:{w}" for i, w in enumerate(sl['words']))
        tag = sl['section'] + (f" (chorus repeat #{sl['occ']}: escalate)" if sl['kind'] == 'chorus' else '')
        rows.append(f"SEG {sl['seg']} | {tag} | \"{sl['text']}\" | words: {words} | shots: 1-{sl['images']}")
    sung = [ln for ln in L if ln.get('words')]
    disp = '\n'.join(f"{RP.line_id(ln)}: {json.dumps([w[0] for w in ln['words']], ensure_ascii=False)}" for ln in sung)
    lyr = [s['seg'] for s in slots if s['kind'] not in ('hook', 'drop', 'outro_tail')]
    vibe = G.read(VIBE)
    analysis = G.read(ANALYSIS)[:14000]
    import tone as T
    tpl = _template('director')
    if tpl:
        return _fill(tpl, {'TITLE': title, 'GENRE': genre or '?', 'STYLE': style, 'VIBE': vibe, 'ANALYSIS': analysis,
                           'REFS': ', '.join(f'ref{i}.jpg' for i in range(1, len(REFS) + 1)), 'N_CLIPS': 45,
                           'LYRIC_SEGS': ', '.join(lyr), 'LOOK_LABEL': LK['label'], 'LOOK_ENERGY': LK['energy'],
                           'STORIES': st, 'SEGMENTS': chr(10).join(rows), 'DISPLAY': disp,
                           'TONE_NOTE': T.CURRENT.get('note') or '(none)'}) + _cast_block()
    return f"""You are the writer AND director (storyboard, cinematography, edit) of a viral "slopcore" AI-news music video
for the song "{title}" ({genre or '?'}; {style}). Vertical 9:16, about 1 s cuts, 2.5 minutes.

First use the Read tool to look at the three reference contact sheets in the current folder (ref1.jpg, ref2.jpg,
ref3.jpg: SAY. SI., javif4_ "underclass", dvorahfr "The Heir") - they are what great slopcore looks like. Then write.

WHAT MAKES SLOPCORE WORK (our notes):
{vibe}

DETAILED ANALYSIS OF THE REFERENCES:
{analysis}

THE BRIEF FROM THE OWNER: the last two versions looked good but "the video doesn't seem related to the music lyrics" and
"the script is bad". The script is the product. EVERY SHOT MUST ACT OUT THE WORDS BEING SUNG AT THAT MOMENT, as a
funny, deadpan, literal gag a viewer gets instantly with the sound off while reading the subtitle. Show the nouns and
verbs. Generic shots (people standing, staring, walking through an office, looking at screens) are failures.
Example: "Ultrafast hits Sol, eight times the pace" -> A's laptop literally on fire while B's printer fires pages out
eight at a time. Product names are AI products (Sol is a model, not the sun); act out the news, not puns on names.

DELIVER (strict JSON, schema enforced):
- "cast": a cast bible: protagonist A and up to three supporting B, C, D: ORIGINAL people (never a celebrity, never the
  real people named in the news), precise looks + one fixed outfit each, so every shot shows the same person.
  IDENTITY RULE: anyone who appears in more than one shot (e.g. "the man yelling at his laptop" across two lines) MUST
  be a cast member: give him a letter (D if A-C are taken), write the letter in the prompt and list it in that shot's
  "cast" every time. Unlettered extras appear in ONE shot only (the generator invents a new face each time).
- "beats": one per SEG below, same seg ids, in order: "meaning" (the news behind the line, from STORIES), "visual"
  (the ONE gag for the line), "shots" (1 to the SEG's max): each shot cuts in on a sung word ("word" = its index; shot 1
  on word 0 with the main gag; later shots on the key noun/verb/number as it is sung - a payoff, an insert, a reaction).
  Shots of a line share its location. Chorus lines: one simple idea per chorus line that returns on every repeat and
  ESCALATES (repeat 1: A and a few people; 2: a whole office/street; 3: a stadium/city crowd doing the same thing).
  PAYOFF: the final sung line and the outro tail pay off the HOOK's opening gag: same location, same prop/action,
  completed or reversed with a twist that shows how far the day escalated (e.g. hook: A slams the breaker and the
  lights bang on -> last line: A pulls the same breaker and the whole stadium crowd / city goes dark behind her).
  Story arc across the song: escalating absurdity, deadpan throughout.
- Per shot: "prompt" (30-60 words: who does what mid-action, where; write A/B/C for cast, never re-describe them;
  extras as archetypes), "framing", "lens", "light", "move" (for stills), "motion" (the physical action in the 3 s
  clip), "camera" (clip camera move), "edit" (note), "kind": "clip" for the shot that carries the line's action
  (normally the first shot of each line; about {45} clips in the whole video; at most 2 per line), "still" otherwise.
- "display": tokens per sung word for the subtitle, fixing brand spellings and using numerals ("GPT-6.1", "Claude
  Code", "66.1", "8x", "$1,000"; give "" to merge following words; keep the count), "accent": the 1 punch token.
- "pip": our mascot Pip is a small physical vinyl toy robot (white egg body, bunny ears, a dark face screen with happy
  cyan eyes - do NOT describe him further and NEVER put anything on his head or face, no hats, glasses, props). Pick
  exactly 2 lyric segments from: {', '.join(lyr)} where the toy fits that line's gag naturally, one sentence each
  (the toy sits/stands as a static object in the scene). "cameo": one sentence for the final shot: the toy alone in
  the last location after everyone has gone.

GENERATOR LIMITS (Grok Imagine): photoreal stills from text (cast shots are edited from the cast portraits), video =
the still continued for 3 s at 720p (one clear action, simple camera). NO readable text in any image (no words,
letters, numbers, signs, logos, labels, readable screens, jersey numbers, switch labels) - show numbers as objects
(eight pages, a podium, a counter needle). No real people, no celebrity lookalikes, no famous characters, robots,
brands or logos. Look for every shot (appended automatically, don't repeat): {LK['label']}. Genre energy: {LK['energy']}.

STORIES:
{st}

SEGMENTS (song order; word onsets in seconds where known):
{chr(10).join(rows)}

DISPLAY LINES:
{disp}

Reply with the JSON object only."""


def doctor_prompt(plan_, slots):
    text = {s['seg']: s for s in slots}
    rows = []
    for b in plan_['beats']:
        sl = text.get(b['seg'])
        if not sl:
            continue
        line = sl['text'] or f"({sl['kind']}, instrumental)"
        w = sl.get('words') or []
        for k, sh in enumerate(b['shots']):
            on = w[min(sh.get('word', 0), len(w) - 1)] if w else '-'
            rows.append(f"{b['seg']}|{k} | sung: \"{line}\" (cuts in on \"{on}\") | news: {b.get('meaning', '')} | "
                        f"gag: {b.get('visual', '')} | shot: {sh['prompt']} | kind: {sh.get('kind', '')} | "
                        f"framing: {sh.get('framing', '')} | motion: {sh.get('motion', '')}")
    tpl = _template('doctor')
    if tpl:
        return _fill(tpl, {'ROWS': chr(10).join(rows)})
    return f"""You are the script doctor on a slopcore AI-news music video. Each row is one shot: the lyric being sung (shown
as a subtitle), the news behind it, the line's gag and the shot. Score every shot 1-5: "would a viewer with the sound
off, reading the subtitle, instantly connect this picture to the words being sung - and is it funny/deadpan?"
5 = the words are literally and funnily acted out; 4 = clear; 3 = vague or mood; 2 = generic (standing, staring,
walking, screens); 1 = unrelated. Product names are AI products (not puns). For every shot under 4 write a better
"prompt" (30-60 words, same cast letters and location, a literal gag on the sung words, no text/numbers/logos in the
image, original people) and "motion" (one physical action for 3 s), plus "new_score". "problem" under 12 words.
One review per row, "id" exactly as given. Do not use any tools.

{chr(10).join(rows)}"""


def _valid(res, slots):
    if not isinstance(res, dict) or not isinstance(res.get('beats'), list):
        return 'no beats list'
    segs = {s['seg'] for s in slots if s['kind'] not in ('hook', 'drop', 'outro_tail')}
    have = {b.get('seg') for b in res['beats'] if isinstance(b, dict) and b.get('shots')}
    miss = segs - have
    if len(miss) > max(2, len(segs) // 10):
        return f'{len(miss)} lyric lines without shots'
    if not (res.get('cast') or []):
        return 'no cast'
    return None


def plan(day, work, look, slots, L, deadline=None, reserve_s=17 * 60, force=False, reuse=False, timed=None):
    path = os.path.join(work, 'real_plan.json')
    import tone as T
    key = {'version': PLANNER_VERSION, 'look': look, 'slots': [(s['seg'], s['images']) for s in slots]}
    if T.CURRENT.get('tone', 'edgy') != 'edgy':
        key.update(tone=T.CURRENT['tone'], note=T.CURRENT.get('note', ''))
    if _cast_block():
        key['cast_refs'] = _cast_block()
    p = G.load_json(path)
    if p and not force and (p.get('key') == json.loads(json.dumps(key)) or (reuse and p.get('beats'))):
        G.log(f"planner: cached real_plan.json ({p.get('planner')})")
        return p
    od = os.path.join(work, 'opus')
    os.makedirs(od, exist_ok=True)
    for i, f in enumerate(REFS, 1):
        if os.path.exists(os.path.join(SHEETS, f)):
            shutil.copyfile(os.path.join(SHEETS, f), os.path.join(od, f'ref{i}.jpg'))
    t_first = time.time()

    def budget(cap):
        t = int(min(cap, OPUS_TOTAL_S - (time.time() - t_first)))
        if deadline:
            t = int(min(t, deadline - time.time() - reserve_s))
        return t
    res, why, meta_all = None, None, {}
    if os.environ.get('CINE_REAL_FAIL') == 'opus' or not os.path.exists(CLAUDE):
        why = 'forced test failure' if os.path.exists(CLAUDE) else 'claude CLI missing'
    else:
        pf = os.path.join(od, 'prompt.txt')
        open(pf, 'w').write(opus_prompt(day, look, slots, L, timed))
        try:
            tmo = budget(OPUS_MAIN_S)
            if tmo < 120:
                raise RuntimeError('not enough time for the Opus planner')
            res, meta = run_claude(pf, od, SCHEMA, tmo, tools='Read', effort='medium')
            meta_all['main'] = {k: v for k, v in meta.items() if k != 'raw'}
            open(os.path.join(od, 'reply_main.txt'), 'w').write(meta.get('raw') or '')
            G.log(f"opus: {meta['secs']}s, {len((res or {}).get('beats') or [])} beats, "
                  f"{sum(len(b.get('shots') or []) for b in (res or {}).get('beats') or [])} shots, ${meta.get('cost_usd')}")
            bad = _valid(res, slots)
            if bad:                                       # one repair call
                G.log(f"opus: invalid plan ({bad}); one repair call")
                rf = os.path.join(od, 'repair.txt')
                open(rf, 'w').write(f"This JSON plan is invalid: {bad}. Fix it so that it matches the schema and has a "
                                    f"beat with shots for every SEG listed in the original brief below. Reply with the "
                                    f"fixed JSON only.\n\nPLAN:\n{json.dumps(res)[:150000] if res else (meta.get('raw') or '')[:150000]}"
                                    f"\n\nORIGINAL BRIEF:\n{open(pf).read()}")
                tmo = budget(OPUS_MAIN_S)
                if tmo < 90:
                    raise RuntimeError(f'invalid plan ({bad}) and no time to repair')
                res, meta = run_claude(rf, od, SCHEMA, tmo, tools='', effort='low')
                meta_all['repair'] = {k: v for k, v in meta.items() if k != 'raw'}
                bad = _valid(res, slots)
                if bad:
                    raise RuntimeError(f'invalid plan after repair: {bad}')
        except Exception as e:
            why = f'{type(e).__name__}: {e}'[:300]
            res = None
    if res:
        res['planner'] = PLANNER_VERSION
        SS._clean(res, slots)
        # keep Opus's own clip/still choice per shot (apply() honours it), and fold the cinematography into the prompt
        for b in res['beats']:
            for s in b['shots']:
                extra = ', '.join(x for x in (s.get('framing'), s.get('lens'), s.get('light')) if x)
                if extra and extra.lower()[:20] not in s['prompt'].lower():
                    s['image_prompt'] = s['prompt'] + f" ({extra})."
                if s.get('camera') and s.get('motion') and s['camera'].lower()[:15] not in s['motion'].lower():
                    s['motion'] = s['motion'].rstrip('. ') + '; camera: ' + s['camera']
        tmo = budget(OPUS_DOCTOR_S)
        if tmo >= 60 and os.environ.get('CINE_REAL_FAIL') != 'opus-doctor':
            df = os.path.join(od, 'doctor.txt')
            open(df, 'w').write(doctor_prompt(res, slots))
            try:
                rv, meta = run_claude(df, od, DOCTOR_SCHEMA, tmo, tools='', effort='low')
                meta_all['doctor'] = {k: v for k, v in meta.items() if k != 'raw'}
                n = SS.apply_reviews(res, (rv or {}).get('reviews') or [])
                for b in res['beats']:                    # a rewritten shot drops the old cinematography suffix
                    for s in b['shots']:
                        if s.get('rewritten'):
                            s.pop('image_prompt', None)
                res['review'] = {'secs': meta['secs'], 'n': len((rv or {}).get('reviews') or []), 'rewritten': n, 'by': 'opus'}
                G.log(f"opus script doctor: {meta['secs']}s, {res['review']['n']} shots scored, {n} rewritten")
            except Exception as e:
                res['review'] = {'error': repr(e)[:200]}
                G.log(f"opus script doctor failed (kept the script): {e!r}"[:300])
        else:
            res['review'] = {'skipped': True}
            G.log(f"opus script doctor skipped ({tmo}s left)")
    else:
        G.log(f"WARNING: Opus planner failed ({why}); falling back to the Grok script planner")
        res = SS.plan(day, work, look, slots, L, deadline=deadline, reserve_s=reserve_s, force=True)
        res['planner'] = 'template' if res.get('fallback') else SS.PLANNER_VERSION
        res['opus_error'] = why
    res['opus_meta'] = meta_all
    res['key'] = key
    res['look'] = look
    res['secs'] = round(time.time() - t_first)
    G.save_json(res, path)
    return res
