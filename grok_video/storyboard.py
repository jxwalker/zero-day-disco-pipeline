#!/usr/bin/env python3
"""Storyboard (24 Oct 2026, the owner: "the videos should be much more relevant to the lyrics and sync with the words so
the production design and story boarding needs to be much better"; "claudia is much better quality").
Research: /home/box/suno-daily/research/2026-10-24_songcraft.md

ensure_direction(day): when there is no <day>/direction.txt, Opus writes one in the 21 Oct "Turn Me On" format
  (LEAD character bible pasted into every prompt, PALETTE, one-line STORY arc, BEATS, SETTING, PRODUCTION DESIGN and a
  per-line SHOT LIST in Claudia DP grammar). karaoke.py's existing LEAD machinery then makes one reference still and
  edits every [LEAD] scene from it, so she is the same woman in every shot.
review(P, day, work, lines): an independent Opus storyboard review of the karaoke plan: every sung line must show a shot
  that acts out THAT line inside the one mini-story; prompts get lens/light/one-move grammar and timestamped motion.
line_check(...): frame-level vision check. Opus Reads every still against the lines it sits under and the shot it was
  meant to be; failures are re-shot once with the reviewer's corrected prompt (then karaoke's match_check still
  guards the final cut)."""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import common_gv as G

S = {"type": "string"}; I = {"type": "integer"}
PALETTES = ['risograph', 'newsprint', 'sunset-pop', 'candy', 'teal-coral', 'noir-yellow', 'cobalt-cream', 'y2k-chrome',
            'neon-chrome', 'forest-mustard']
BANNED = r'\b(cinematic|4k|8k|ultra[- ]detailed|highly detailed|masterpiece|stunning|epic|hyperreal\w*|award[- ]winning|breathtaking)\b'

DIR_SCHEMA = {"type": "object", "properties": {
    "lead": S, "palette": {"type": "string", "enum": PALETTES}, "arc": S,
    "beats": {"type": "array", "items": {"type": "object", "properties": {"beat": S, "sections": S, "action": S}, "required": ["beat", "sections", "action"]}},
    "setting": S, "locations": {"type": "array", "items": S}, "props": {"type": "array", "items": S}, "wardrobe": S, "colour": S,
    "shots": {"type": "array", "items": {"type": "object", "properties": {
        "i": I, "line": S, "shot": S, "literal_or_pun": S, "size_lens": S, "light": S, "move": S, "motion": S},
        "required": ["i", "line", "shot", "literal_or_pun", "size_lens", "light", "move", "motion"]}}},
    "required": ["lead", "palette", "arc", "beats", "setting", "locations", "props", "wardrobe", "colour", "shots"]}

GRAMMAR = """CINE GRAMMAR (from the Claudia prompt book, which the owner rates much higher):
- Live-action music video shot on film: real lens with focal length and stop (35mm f/2, 50mm f/1.8, 85mm f/2), Kodak
  Vision3 250D/500T grain, ONE named motivated light source (window, practical lamp, rack LEDs, sodium street light,
  low sun, fluorescent tube), composed off-centre with clean negative space in the lower third for the karaoke words.
- Every shot moves: exactly ONE camera move (STATIC, PUSH, PULL, TRUCK, SLIDER, ARC, TRACK, HANDHELD, CRANEUP,
  RACK, WHIP, CRASH) plus one simple human action, written as timestamped blocking "0-2s: ... 2-4s: ... 4-6s: ...".
- One lead in most shots; one fixed wardrobe; max 3 locations; one continuous mini-story in song order.
- Each sung line gets a shot that acts out THAT line's words literally or with a clever visual pun inside the story
  (sound off, a stranger still gets the line). Choruses replay the central gag from new angles and escalate; the
  final-chorus word swap gets its own payoff image. Pure literal word-by-word clip art is banned: the lead DOES it.
- Banned filler words: cinematic, 4k, 8k, ultra-detailed, masterpiece, stunning, epic, hyperreal, award-winning.
- No robots/androids/mascots; no laptops, tablets or phones anywhere (any screen is a wall display or terminal seen
  straight-on, with real commands); no real or famous people; everyone 21-28; no logos."""


def _lines(day):
    return [l.strip() for l in G.read(os.path.join(day, 'lyrics.txt')).splitlines() if l.strip() and not l.strip().startswith('[')]


def ensure_direction(day, lines=None):
    pth = os.path.join(day, 'direction.txt')
    if os.path.exists(pth) or os.environ.get('GV_STORYBOARD', '1') == '0' or os.environ.get('GV_DIRECTION'):
        return False
    import slop_opus as SO
    hj = G.load_json(os.path.join(day, 'headline.json'), {}) or {}
    cj = G.load_json(os.path.join(day, 'work_headline', 'concept.json'), {}) or {}
    lines = lines or _lines(day)
    od = os.path.join(day, 'work_storyboard'); os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'direction_prompt.txt')
    open(pf, 'w').write(
        "You are the director, DP and production designer of today's 2:20 vertical music video. Write the treatment and "
        "storyboard. Template: the 21 Oct 'Turn Me On' video (a data centre personified as a girl dressed up and stood "
        "up waiting for grid power; she finally throws the breaker herself) - one lead, one arc, every line acted out.\n\n"
        + GRAMMAR + "\n\nWRITE:\n- lead: the character bible, ONE dense 55-80 word paragraph pasted into every image "
        "prompt: an original quirky manic-pixie indie engineer, clearly an adult woman of about 24 (not any real person), "
        "face, hair (one distinctive colour detail), glasses or other signature, ONE exact wardrobe with colours and "
        "materials that fits the song's pun, footwear, one accessory; 'PG-13, fully clothed'; natural varied "
        "expressions.\n- palette: one of the enum names that suits the song.\n- arc: ONE-LINE ARC that turns the song's "
        "pun into a story with a payoff.\n- beats: SETUP / RISING / CHEEKY CHORUSES / BREAKDOWN / PAYOFF with what she does.\n"
        "- setting, locations (max 3, real and technically accurate), props (the story's real objects + 2-3 cheeky cues "
        "for the pun), wardrobe, colour (section palettes and accent).\n- shots: one per sung line index below "
        "(repeated chorus lines escalate: new angle or bigger version of the same gag); 'shot' = the first frame in 25-45 "
        "words (who, where, exact action that depicts the line's words, framing, negative space); size_lens, light, "
        "move, motion = timestamped 6 s blocking with that one move.\n\nCONCEPT: "
        + json.dumps(cj.get('chosen') or {}, ensure_ascii=False) + "\n\nTITLE: " + (hj.get('title') or G.read(os.path.join(day, 'title.txt')))
        + "\n\nSTORIES:\n" + G.read(os.path.join(day, 'stories.md'))[:6000] + "\n\nSUNG LINES (index: text):\n"
        + '\n'.join(f"{i}: {l}" for i, l in enumerate(lines)) + "\n\nReply with the JSON only.")
    d, meta = SO.run_claude(pf, od, DIR_SCHEMA, 600, tools='', effort='high')
    G.save_json(d, os.path.join(od, 'direction.json'))
    shots = '\n'.join(f"- line {s['i']} \"{s['line']}\": {s['shot']} [{s['size_lens']}; {s['light']}; {s['move']}] "
                      f"motion: {s['motion']}" for s in d['shots'])
    txt = (f"LEAD: {' '.join(d['lead'].split())}\nPALETTE: {d['palette']}\nSTORY: ONE-LINE ARC: {d['arc']}\n"
           "BEATS (map every shot to its beat; every shot must advance the arc and literally match its lyric line):\n"
           + '\n'.join(f"- {b['beat']} ({b['sections']}): {b['action']}" for b in d['beats'])
           + f"\nSETTING: {d['setting']}\nPRODUCTION DESIGN: locations: {'; '.join(d['locations'])}. Props: {'; '.join(d['props'])}. "
           f"Wardrobe: {d['wardrobe']}. Colour: {d['colour']}\nSHOT LIST (storyboard; follow it line by line, start every "
           f"scene prompt with the shot's camera grammar):\n{shots}\nRULES: the same woman in every shot that shows her "
           "(same face, hair, glasses, wardrobe). Real technical kit. No laptops, tablets or phones; no robots. "
           "Everyone is 21-28. Graphics stay exact and code-rendered as usual.\n" + GRAMMAR + "\n")
    open(pth, 'w').write(txt)
    G.log(f"storyboard: wrote {pth} ({len(d['shots'])} shots, palette {d['palette']}, {meta['secs']}s)")
    return True


REV_SCHEMA = {"type": "object", "properties": {
    "score": I, "verdict": S,
    "scene_fixes": {"type": "array", "items": {"type": "object", "properties": {"id": S, "prompt": S, "motion": S, "why": S},
                                                "required": ["id", "prompt", "motion", "why"]}},
    "line_scene": {"type": "array", "items": {"type": "object", "properties": {"i": I, "scene": S, "why": S}, "required": ["i", "scene", "why"]}}},
    "required": ["score", "verdict", "scene_fixes", "line_scene"]}


def review(P, day, work, lines):
    """Opus storyboard review of the plan before any Grok spend. Applies fixes in place; returns the review."""
    if os.environ.get('GV_STORYBOARD', '1') == '0' or not P.get('scenes'):
        return None
    import slop_opus as SO
    od = os.path.join(work, 'opus'); os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'storyboard_review.txt')
    rows = []
    for ln in P.get('lines', []):
        i = ln.get('i'); vs = ', '.join(v.get('id') if v.get('kind') == 'scene' else 'gfx:' + str(v.get('g')) for v in ln.get('v', []))
        rows.append(f"{i}: {lines[i] if isinstance(i, int) and i < len(lines) else '?'}  ->  [{vs}] shows: {ln.get('shows', '')}")
    sc = '\n'.join(f"{s['id']}: {s['prompt']}  || motion: {s.get('motion', '')}" for s in P['scenes'])
    open(pf, 'w').write(
        "You are the producer reviewing a music-video storyboard before money is spent on shots. Be strict.\n" + GRAMMAR +
        "\n\nDIRECTION (treatment, lead bible, shot list):\n" + G.read(os.path.join(day, 'direction.txt'))[:9000] +
        "\n\nSCENES (id: prompt || motion):\n" + sc + "\n\nLINE MAP (index: sung line -> visuals, shows):\n" + '\n'.join(rows) +
        "\n\nCheck: (1) every scene prompt depicts a specific line's words being acted out by the lead inside the one "
        "story, and follows the grammar (shot size, lens+stop, named light source, negative space, starts with [LEAD] "
        "when she is in it); (2) motion is timestamped 0-2s/2-4s/4-6s with ONE camera move and one action; (3) each "
        "sung line's scene really matches THAT line (sound off test) and the story reads in order; (4) no banned "
        "words, no laptops/phones/tablets, no robots, nobody outside 21-28.\nReturn score 1-10, a verdict, "
        "scene_fixes = full corrected prompt+motion for every scene that is not already excellent (keep the same id; "
        "35-80 words; keep [LEAD] tokens), and line_scene = reassignments where a different EXISTING scene id fits a "
        "sung line far better (only scene ids from the list). Reply with the JSON only.")
    try:
        r, meta = SO.run_claude(pf, od, REV_SCHEMA, 480, tools='', effort='high')
    except Exception as e:
        G.log(f"storyboard: review unavailable ({str(e)[:150]})"); return None
    byid = {s['id']: s for s in P['scenes']}
    nf = 0
    for f in r.get('scene_fixes', []):
        if f['id'] in byid and f['prompt'].strip():
            s = byid[f['id']]; s['prompt_orig'] = s['prompt']
            s['prompt'] = re.sub(BANNED, '', f['prompt'], flags=re.I).strip()
            if f.get('motion', '').strip(): s['motion'] = f['motion'].strip()
            nf += 1
    nl = 0
    lmap = {ln.get('i'): ln for ln in P.get('lines', [])}
    for x in r.get('line_scene', []):
        if x['scene'] in byid and x['i'] in lmap:
            lmap[x['i']]['v'] = [{'kind': 'scene', 'id': x['scene']}]; nl += 1
    for s in P['scenes']:
        s['prompt'] = re.sub(BANNED, '', s['prompt'], flags=re.I)
    G.save_json(r, os.path.join(od, 'storyboard_review.json'))
    P['storyboard_review'] = {'score': r.get('score'), 'verdict': r.get('verdict'), 'scene_fixes': nf, 'line_moves': nl}
    G.log(f"storyboard: review score {r.get('score')} - {nf} scene fixes, {nl} line moves ({meta['secs']}s)")
    return r


LC_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
    "id": S, "matches_line": {"type": "boolean"}, "same_lead": {"type": "boolean"}, "issue": S, "fixed_prompt": S},
    "required": ["id", "matches_line", "same_lead", "issue", "fixed_prompt"]}}}, "required": ["results"]}


def line_check(P, scenes, jobs, gdir, lines, status, look, deadline):
    """Vision check of every still against its sung line(s); re-shoot failures once with the corrected prompt."""
    if os.environ.get('GV_STORYBOARD', '1') == '0':
        return
    import slop_opus as SO, real_gen as R, time
    under = {}
    for ln in P.get('lines', []):
        for v in ln.get('v', []):
            if v.get('kind') == 'scene' and isinstance(ln.get('i'), int) and ln['i'] < len(lines):
                under.setdefault(v['id'], []).append(lines[ln['i']])
    have = [s for s in scenes if os.path.exists(f"{gdir}/{s['id']}.png")]
    if not have:
        return
    pf = os.path.join(gdir, 'line_check.txt')
    ref = os.path.exists(f"{gdir}/lead_ref.png")
    open(pf, 'w').write(
        "You are the script supervisor of a music video. For each still below, use the Read tool to open the file (in "
        "this directory) and judge it literally against the sung line(s) it plays under and the shot it was meant to "
        "be. matches_line = a viewer with the sound off would connect this picture to those words (the action/prop the "
        "words name is clearly visible), and it fits the story. same_lead = " + ("open lead_ref.png first; true if the "
        "woman shown is clearly the same person and outfit (or no woman is meant to be shown)" if ref else "true") +
        ". Reject laptops/phones/tablets, robots, readable gibberish text, malformed hands or faces too. For failures give "
        "the issue and a fixed_prompt (35-80 words, same grammar: shot size, lens, light, action that depicts the line); "
        "'' for passes. id = file name without .png.\n\n" +
        '\n'.join(f"{s['id']}.png  lines: {' / '.join(under.get(s['id'], ['(instrumental)']))}  ||  meant: {s['prompt'][:300]}" for s in have))
    try:
        res, meta = SO.run_claude(pf, gdir, LC_SCHEMA, 600, tools='Read', effort='medium')
    except Exception as e:
        G.log(f"storyboard: line check unavailable ({str(e)[:150]})"); status.setdefault('warnings', []).append('line check unavailable'); return
    rs = {r['id'].replace('.png', ''): r for r in res.get('results', [])}
    G.save_json(rs, os.path.join(gdir, 'line_check.json'))
    bad = [k for k, r in rs.items() if not (r.get('matches_line') and r.get('same_lead')) and r.get('fixed_prompt', '').strip()]
    status['line_check'] = {'checked': len(rs), 'failed': {k: rs[k].get('issue') for k in bad}}
    G.log(f"storyboard: line check {len(rs)} stills, re-shooting {bad}")
    if not bad or time.time() > deadline - 10 * 60:
        return
    jb = {j['id']: j for j in jobs}
    rj = []
    for k in bad:
        if k not in jb: continue
        j = jb[k]; fx = rs[k]['fixed_prompt'].replace('[LEAD]', '').strip()
        if j['kind'] == 'edit':
            pr = "Keep the exact same woman from the reference image: same face, hair, body and outfit. New scene, vertical 9:16: " + fx + look
        else:
            pr = fx + look
        os.replace(j['out'], j['out'] + '.linefail.png')
        rj.append(dict(j, prompt=pr))
        for s in scenes:
            if s['id'] == k: s['prompt_linefix'] = fx
    b = R.Batcher(gdir, {'gen': len(rj), 'edit': len(rj)}, batch_size=5, max_parallel=3, deadline=deadline - 8 * 60, tag='linefix')
    b.run(rj)
    for j in rj:                                   # keep the original if the re-shoot failed
        if not os.path.exists(j['out']) and os.path.exists(j['out'] + '.linefail.png'):
            os.replace(j['out'] + '.linefail.png', j['out'])
    status['line_check']['reshot'] = [j['id'] for j in rj]


# ---------------------------------------------------------------- Runway hero shots (24 Oct, optional)
# Runway is reached only through the user-Runway MCP (agent side), so the pipeline writes the jobs and the routine's
# agent runs them: see prompts/runway_hero_runbook.md. Budget ~300 credits/day; any failure keeps the Grok clip.
HERO_COST = {'kling-4': 15.7, 'wan3': 10.0}       # credits per second at 720p (Runway MCP docs, 24 Oct 2026)
HERO_BUDGET = float(os.environ.get('GV_HERO_BUDGET', 300)); HERO_SECS = 5


def _section_lines(day):
    out, sec = [], ''
    for l in G.read(os.path.join(day, 'lyrics.txt')).splitlines():
        l = l.strip()
        if not l: continue
        if l.startswith('['):
            if not any(w in l.lower() for w in ('gang', 'rising', 'silence', 'spoken', 'key change', 'full band', 'hard stop', 'chant]')) or ' - ' in l:
                sec = l.strip('[]').split(' - ')[0].strip()
            continue
        out.append(sec)
    return out


def hero_plan(P, day, gdir):
    """Pick 2-4 hero moments (first chorus opening, the drop into the final chorus, the final-chorus payoff, the
    scroll-stopper) and write <gdir>/hero_jobs.json. Kling 4 for high-energy performance, WAN 3 for prop/screen shots."""
    secs = _section_lines(day)
    sc_of = {}
    for ln in P.get('lines', []):
        for v in ln.get('v', []):
            if v.get('kind') == 'scene': sc_of.setdefault(ln['i'], v['id'])
    def first(name, last=False):
        idx = [i for i, s in enumerate(secs) if s.lower() == name.lower() and i in sc_of]
        return (idx[-1] if last else idx[0]) if idx else None
    picks = []
    for why, i in (('chorus opening', first('Chorus')), ('final chorus drop', first('Final Chorus')),
                   ('final payoff', first('Final Chorus', last=True))):
        if i is not None and sc_of[i] not in [p['id'] for p in picks]:
            picks.append({'id': sc_of[i], 'line': i, 'why': why})
    intro = next((v['id'] for v in P.get('intro', []) if v.get('kind') == 'scene'), None)
    if intro and intro not in [p['id'] for p in picks]:
        picks.append({'id': intro, 'line': -1, 'why': 'scroll-stopper'})
    byid = {s['id']: s for s in P.get('scenes', [])}
    jobs, spent = [], 0.0
    for p in picks[:4]:
        s = byid.get(p['id'])
        if not s or not os.path.exists(f"{gdir}/{p['id']}.png"): continue
        prop = bool(re.search(r'\b(screen|display|terminal|monitor|dashboard|close-up of|insert|hand[s]? on|prop|log)\b', s['prompt'], re.I)) and 'chorus' not in p['why']
        model = 'wan3' if prop else 'kling-4'
        cost = HERO_COST[model] * HERO_SECS
        if spent + cost > HERO_BUDGET: continue
        spent += cost
        motion = re.sub(r'\[LEAD\]', 'the woman', s.get('motion', ''))
        jobs.append(dict(p, model=model, est_credits=round(cost), image=f"{gdir}/{p['id']}.png", out=f"{gdir}/{p['id']}.mp4",
                         prompt=("Keep the exact same woman, outfit, set and lighting as the image; live-action music video, "
                                 "35mm film look, natural human motion, no morphing, no new people, no text, no laptops or phones. "
                                 + motion)[:2400], ratio='9:16', resolution='720p', duration=HERO_SECS, status='todo'))
    G.save_json({'budget': HERO_BUDGET, 'est_total': round(spent), 'jobs': jobs}, os.path.join(gdir, 'hero_jobs.json'))
    G.log(f"storyboard: hero plan {[(j['id'], j['model'], j['why']) for j in jobs]} est {round(spent)} credits")
    return jobs


def hero_apply(gdir, hid, mp4):
    """Install a downloaded Runway clip as the scene clip (the Grok clip is kept as <id>.grok.mp4 for fallback)."""
    import shutil, subprocess
    out = f"{gdir}/{hid}.mp4"
    if os.path.exists(out) and not os.path.exists(f"{gdir}/{hid}.grok.mp4"):
        shutil.copyfile(out, f"{gdir}/{hid}.grok.mp4")
    # normalise to the Grok clip format (720x1280, 24 fps, no audio) so the renderer treats it the same
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mp4, '-an', '-vf', 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', out + '.tmp.mp4'])
    if r.returncode == 0:
        os.replace(out + '.tmp.mp4', out); return True
    return False


if __name__ == '__main__':        # storyboard.py hero-apply <gdir> <id> <downloaded.mp4>
    if sys.argv[1:2] == ['hero-apply']:
        print(hero_apply(sys.argv[2], sys.argv[3], sys.argv[4]))
