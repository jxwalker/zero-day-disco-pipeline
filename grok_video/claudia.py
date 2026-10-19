"""Claudia-style headline mode (19 Oct 2026, the owner-approved; see README "Claudia mode").

Replaces, in headline mode only, the per-line micro-shot plan + chyron type with:
 1. pacing: ~25-40 shots per 2:30 song; one coherent scene per lyric couplet (4-8 s), quicker (~2-3 s) shots only in
    choruses and the bridge; almost every shot is a moving clip.
 2. one lead (cast A) with a fixed reference sheet, approved by Opus before any batch; stills are image_edit from the
    sheet and every clip with the lead passes the sheet to reference_to_video; the realism gate checks likeness.
 3. a prompt book (prompt_book.md/.json): one Opus context writes every paid prompt with timestamped motion/blocking,
    camera, lens, light; an Opus review pass corrects it before any render; after render Opus picks each clip's usable
    in/out window from frames (windows.json) and the edit plays only that window, at 1x.
 4. typography designed into each scene (ASS rendered by libass, i.e. code; nothing paid): lyric lines placed in the
    scene's negative-space zone, Inter Tight + Instrument Serif accents, words revealed on their sung onsets; a slim
    synced "via @handle" source tag instead of the scrolling ticker; headline card and end card kept.
 5. art direction: 'clean-film' look (soft motivated light, no flash, no VHS/datestamp) + a film LUT grade pass.
Switch off with GV_CLAUDIA=0 (falls back to the 14-18 Oct headline pipeline)."""
import json, math, os, re, subprocess, time
import common_gv as G
import real_plan as RP
import slop_plan as SP

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 'claudia-1'
MIN_SHOTS, MAX_SHOTS = 25, 40
LEAD_MIN_SHARE = 0.7

CLEAN_FILM = {
    'label': 'clean cinematic 35mm film, soft motivated light',
    'prompt': ("Photoreal film still from a real live-action music video, vertical 9:16, shot on 35mm Kodak Vision3 "
               "with a real spherical prime lens, soft motivated natural light from a visible source, gentle contrast, "
               "true-to-life muted colour with a restrained palette, fine film grain, composed uncluttered frame with "
               "clean negative space, shallow depth of field, real skin texture. No on-camera flash, no HDR, no bloom."),
    'accent': (236, 196, 120), 'accent_hue': None, 'accent_name': 'warm gold', 'sat': 0.92, 'tint': (3, 1, -2),
    'contrast': 1.03, 'crush': 0.0, 'vignette': 0.14, 'leak': (255, 190, 140), 'grain': 5, 'genres': (),
    'energy': 'composed, observational, deadpan: real people in real places, lingering frames'}
SP.SLOP_LOOKS.setdefault('clean-film', CLEAN_FILM)


def enabled(day):
    return os.environ.get('GV_CLAUDIA', '1') != '0' and os.path.exists(os.path.join(day, 'headline.json'))


# ------------------------------------------------------------------------------------------------ scenes (pacing)
def _known_timings(day, work):
    import glob
    au = os.path.join(day, 'audio.mp3')
    for f in [os.path.join(work, 'align', 'timings.json')] + sorted(glob.glob(os.path.join(day, 'work*', 'align', 'timings.json')),
                                                                     key=os.path.getmtime, reverse=True):
        try:
            if os.path.exists(f) and os.path.getmtime(f) >= os.path.getmtime(au):
                d = json.load(open(f))
                if isinstance(d, list) and d and d[0].get('words'):
                    return d
        except Exception:
            continue
    return None


def _quick(kind, section):
    s = section.lower()
    return kind in ('chorus', 'postchorus') or 'bridge' in s or 'final' in s


def scenes(plines, dur, timed=None):
    """Scene slots in song order. Each slot: seg 'scNN', lines [line ids], kind, est seconds, images=clips=shots."""
    tmap = {}
    if timed:
        sung = [l for l in timed if l.get('words')]
        for i, l in enumerate(sung):
            nxt = sung[i + 1]['words'][0][1] if i + 1 < len(sung) else min(dur - 4.3, l['words'][-1][2] + 2.5)
            tmap[RP.line_id(l)] = (l['words'][0][1], nxt)
    lines = [l for l in plines if (l.get('text') or '').strip()]
    first = min((v[0] for v in tmap.values()), default=min(12.0, dur * 0.07))
    per_line = (dur - first - 6.5) / max(1, len(lines))

    def est(ids):
        if all(i in tmap for i in ids):
            return max(0.8, tmap[ids[-1]][1] - tmap[ids[0]][0])
        return per_line * len(ids)
    groups, cur = [], []
    for i, l in enumerate(lines):                       # blocks of one section occurrence
        if cur and (cur[-1]['section'], cur[-1]['section_occ']) != (l['section'], l['section_occ']):
            groups.append(cur); cur = []
        cur.append(l)
    if cur:
        groups.append(cur)
    out = [{'seg': 'hook', 'kind': 'hook', 'section': 'hook', 'lines': [], 'text': '', 'est': round(first, 1)}]
    for g in groups:
        k, sec = g[0]['kind'], g[0]['section']
        step = 1 if _quick(k, sec) else 2               # couplets in verses; one scene per line in choruses/bridge
        if not _quick(k, sec) and len(g) == 3:
            step = 3
        for j in range(0, len(g), step):
            part = g[j:j + step]
            ids = [RP.line_id(x) for x in part]
            out.append({'seg': '', 'kind': k, 'section': sec, 'occ': g[0]['section_occ'], 'lines': ids,
                        'text': ' / '.join(x['text'] for x in part), 'est': round(est(ids), 1)})
    out.append({'seg': 'outro_tail', 'kind': 'outro_tail', 'section': 'outro', 'lines': [], 'text': '', 'est': 4.0})
    for s in out:                                        # shots per scene
        if s['kind'] == 'hook':
            s['images'] = 1 if s['est'] < 7 else 2
        elif s['kind'] == 'outro_tail':
            s['images'] = 1
        elif _quick(s['kind'], s['section']):
            s['images'] = max(1, min(2, round(s['est'] / 2.8)) if s['est'] <= 8 else min(4, math.ceil(s['est'] / 5.5)))
        else:
            s['images'] = max(1, math.ceil(s['est'] / 6.5))
    n = sum(s['images'] for s in out)
    while n > MAX_SHOTS:                                 # trim: quick scenes first (keep one shot each)
        c = max([s for s in out if s['images'] > 1], key=lambda s: (_quick(s['kind'], s['section']), s['images'], -s['est']))
        c['images'] -= 1; n -= 1
    while n < MIN_SHOTS:                                 # add coverage to the longest-per-shot scenes
        c = max([s for s in out if s['kind'] not in ('outro_tail',)], key=lambda s: s['est'] / s['images'])
        if c['est'] / (c['images'] + 1) < 1.8:
            break
        c['images'] += 1; n += 1
    for i, s in enumerate(out):
        if not s['seg']:
            s['seg'] = f'sc{i:02d}'
        s['clips'] = s['images']
        s['hero'] = False
    return out


# ------------------------------------------------------------------------------------------------ prompt book
S, I = {"type": "string"}, {"type": "integer"}
SHOT = {"type": "object", "properties": {
    "cast": {"type": "array", "items": S}, "image_prompt": S, "duration": I,
    "motion": {"type": "array", "items": S}, "camera": S, "lens": S, "light": S},
    "required": ["cast", "image_prompt", "duration", "motion", "camera", "lens", "light"]}
BOOK_SCHEMA = {"type": "object", "properties": {
    "lead": {"type": "object", "properties": {"name": S, "age": I, "face": S, "hair": S, "build": S, "wardrobe": S,
                                              "palette": S, "description": S},
             "required": ["name", "age", "face", "hair", "build", "wardrobe", "palette", "description"]},
    "support": {"type": "array", "items": {"type": "object", "properties": {"id": S, "role": S, "description": S},
                                           "required": ["id", "role", "description"]}},
    "sections": {"type": "array", "items": {"type": "object", "properties": {"section": S, "palette": S, "light": S},
                                            "required": ["section", "palette", "light"]}},
    "scenes": {"type": "array", "items": {"type": "object", "properties": {
        "seg": S, "location": S, "idea": S, "type_zone": {"type": "string", "enum": ["top", "upper", "lower", "left", "right"]},
        "shots": {"type": "array", "items": SHOT}}, "required": ["seg", "location", "idea", "type_zone", "shots"]}},
    "cameo": S},
    "required": ["lead", "support", "sections", "scenes", "cameo"]}
FIX = {"type": "object", "properties": {"seg": S, "shot": I, "image_prompt": S, "duration": I,
                                        "motion": {"type": "array", "items": S}, "camera": S, "lens": S, "light": S},
       "required": ["seg", "shot"]}
REVIEW_SCHEMA = {"type": "object", "properties": {"verdict": S, "issues": {"type": "array", "items": S},
                                                  "fixes": {"type": "array", "items": FIX}},
                 "required": ["verdict", "issues", "fixes"]}
BOT = re.compile(r'\b(robot|robotic|android|cyborg|mascot|toy|pip|hologram)s?\b', re.I)


def _book_prompt(day, slots, h):
    st = G.read(os.path.join(day, 'stories.md')).strip()[:6000]
    seed = '\n'.join(f"- {c['id']} {c.get('role', '')}: {c.get('description', '')}" for c in (h.get('cast') or [])[:3]) or '-'
    hl = (f"Main story #{h.get('main_story')}; secondary {h.get('secondary')}. Bridge surprise: {h.get('bridge_surprise', '')}. "
          f"Outro punchline shot: {h.get('outro_punchline_shot', '')}. Hook gag: "
          + next((x['visual_gag'] for x in h.get('hook_options') or [] if x['title'].strip().lower() == h.get('title', '').strip().lower()), ''))
    rows = []
    for s in slots:
        what = {'hook': 'HOOK (instrumental intro before the first sung word): establish the lead and the main story',
                'outro_tail': 'OUTRO TAIL (instrumental ending): the deadpan payoff, quiet'}.get(s['kind'])
        rows.append(f"{s['seg']} | {s['section']} | est {s['est']}s | shots {s['images']} | "
                    + (what or f"\"{s['text']}\""))
    tpl = open(os.path.join(HERE, 'prompts', 'claudia_book.txt')).read()
    for k, v in {'TITLE': h.get('title', ''), 'STYLE': G.read(os.path.join(day, 'style.txt')).strip(), 'HEADLINE': hl,
                 'STORIES': st, 'LYRICS': G.read(os.path.join(day, 'lyrics.txt')).strip(), 'SEED_CAST': seed,
                 'SCENES': '\n'.join(rows)}.items():
        tpl = tpl.replace('{{' + k + '}}', str(v))
    return tpl


def _fit(book, slots):
    """enforce the slot shape: every slot has a scene with exactly its shot count; durations 3-6; no robots."""
    by = {s['seg']: s for s in book.get('scenes') or []}
    probs = []
    for sl in slots:
        sc = by.get(sl['seg'])
        if not sc or not sc.get('shots'):
            probs.append(f"{sl['seg']} missing"); continue
        sc['shots'] = sc['shots'][:sl['images']]
        while len(sc['shots']) < sl['images']:
            sc['shots'].append(dict(sc['shots'][-1]))
        for sh in sc['shots']:
            sh['duration'] = max(3, min(6, int(sh.get('duration') or 5)))
            sh['cast'] = [str(c).strip().upper()[:1] for c in sh.get('cast') or [] if str(c).strip()]
            for f in ('image_prompt',):
                if BOT.search(sh.get(f) or ''):
                    sh[f] = BOT.sub('person', sh[f]); probs.append(f"{sl['seg']}: robot word removed")
    book['scenes'] = [by[s['seg']] for s in slots if s['seg'] in by]
    return probs


def lead_share(book):
    sh = [x for s in book['scenes'] for x in s['shots']]
    return sum(1 for x in sh if 'A' in x['cast']) / max(1, len(sh))


def write_book_md(book, slots, path, review=None):
    L = book['lead']
    o = [f"# Prompt book ({VERSION})", '', "## Lead (cast A) reference sheet",
         f"- **{L['name']}**, {L['age']}", f"- face: {L['face']}", f"- hair: {L['hair']}", f"- build: {L['build']}",
         f"- wardrobe: {L['wardrobe']}", f"- palette: {L['palette']}", f"- prompt text: {L['description']}", '']
    if book.get('support'):
        o += ['## Supporting cast'] + [f"- {c['id']} ({c['role']}): {c['description']}" for c in book['support']] + ['']
    o += ['## Section palettes'] + [f"- {x['section']}: {x['palette']} | light: {x['light']}" for x in book.get('sections') or []] + ['']
    o += [f"## Scenes ({len(slots)} scenes, {sum(len(s['shots']) for s in book['scenes'])} shots, lead in "
          f"{lead_share(book):.0%})"]
    sl = {s['seg']: s for s in slots}
    for sc in book['scenes']:
        s = sl.get(sc['seg'], {})
        o += ['', f"### {sc['seg']} · {s.get('section', '')} · est {s.get('est', '?')}s · type: {sc['type_zone']}",
              f"*{s.get('text') or s.get('kind')}*", f"Location: {sc['location']}. Idea: {sc['idea']}"]
        for k, sh in enumerate(sc['shots']):
            o += [f"{k + 1}. [{''.join(sh['cast']) or '-'}] {sh['duration']}s | {sh['camera']} | {sh['lens']} | {sh['light']}",
                  f"   first frame: {sh['image_prompt']}"] + [f"   - {m}" for m in sh['motion']]
    o += ['', f"**Cameo / sign-off:** {book.get('cameo', '')}"]
    if review:
        o += ['', '## Producer review (Opus)', f"Verdict: {review.get('verdict', '')}"] + [f"- {x}" for x in review.get('issues') or []]
        o.append(f"Fixes applied: {len(review.get('fixes') or [])}")
    open(path, 'w').write('\n'.join(o) + '\n')


def plan(day, work, plines, dur, deadline=None, reuse=False):
    """-> (pslots, plan dict in the slop_real build_jobs format, book)."""
    import slop_opus as SO
    od = os.path.join(work, 'opus'); os.makedirs(od, exist_ok=True)
    h = SO.headline(day) or {}
    timed = _known_timings(day, work)
    slots = scenes(plines, dur, timed)
    G.log(f"claudia: {len(slots)} scenes, {sum(s['images'] for s in slots)} shots planned "
          f"({'real timings' if timed else 'estimated timings'})")
    bp = os.path.join(work, 'prompt_book.json')
    key = [(s['seg'], s['images']) for s in slots]
    book = G.load_json(bp) if reuse and os.path.exists(bp) else None
    if not book or book.get('_key') != key:
        pf = os.path.join(od, 'book_prompt.txt'); open(pf, 'w').write(_book_prompt(day, slots, h))
        t0 = time.time()
        book, meta = SO.run_claude(pf, od, BOOK_SCHEMA, 900, tools='', effort='high')
        G.log(f"claudia: prompt book written by one Opus context in {meta['secs']}s (${meta.get('cost_usd')})")
        probs = _fit(book, slots)
        if probs:
            G.log(f"claudia: book fit notes {probs[:6]}")
        review = {}
        try:                                             # producer review before any spend
            rf = os.path.join(od, 'book_review.txt')
            open(rf, 'w').write(open(os.path.join(HERE, 'prompts', 'claudia_review.txt')).read()
                                .replace('{{BOOK}}', json.dumps(book, ensure_ascii=False)))
            review, rm = SO.run_claude(rf, od, REVIEW_SCHEMA, 420, tools='', effort='medium')
            by = {s['seg']: s for s in book['scenes']}
            n = 0
            for f in review.get('fixes') or []:
                sc = by.get(f.get('seg'))
                if sc and 0 <= int(f.get('shot', -1)) < len(sc['shots']):
                    sc['shots'][f['shot']].update({k: v for k, v in f.items() if k not in ('seg', 'shot') and v})
                    n += 1
            _fit(book, slots)
            G.log(f"claudia: Opus review {rm['secs']}s: {len(review.get('issues') or [])} issues, {n} fixes applied")
        except Exception as e:
            G.log(f"WARNING: claudia review skipped: {e!r}"[:300])
        book['_key'] = key
        book['_review'] = review
        G.save_json(book, bp)
    write_book_md(book, slots, os.path.join(work, 'prompt_book.md'), book.get('_review'))
    sec_pal = {x['section'].lower(): x for x in book.get('sections') or []}
    cast = [{'id': 'A', 'role': f"lead: {book['lead']['name']}", 'description': book['lead']['description']}]
    cast += [c for c in (book.get('support') or [])[:2] if c['id'] in ('B', 'C')]
    segs = []
    by = {s['seg']: s for s in book['scenes']}
    for sl in slots:
        sc = by[sl['seg']]
        sl['type_zone'] = sc['type_zone']
        pal = sec_pal.get(sl['section'].lower()) or {}
        ims = []
        for k, sh in enumerate(sc['shots']):
            body = (f"{sh['image_prompt']} Location: {sc['location']}. Light: {sh['light']}. Lens: {sh['lens']}. "
                    + (f"Palette: {pal['palette']}. " if pal.get('palette') else ''))
            mot = ' '.join(sh['motion'])
            ims.append({'prompt': body, 'image_prompt': body, 'cast': sh['cast'], '_clip': True, 'duration': sh['duration'],
                        'motion': f"{mot} Camera: {sh['camera']}, {sh['lens']}. Light stays: {sh['light']}.", 'word': 0})
        segs.append({'seg': sl['seg'], 'images': ims})
    return slots, {'planner': VERSION, 'cast': cast, 'segments': segs, 'display': [], 'pip': [],
                   'cameo': book.get('cameo') or ''}, book


def patch_jobs(cast_jobs, stills, heroes, pslots, plan_, work, LK, lead):
    """per-shot clip durations; the lead's sheet as a reference image for every clip with A; a reference-sheet portrait."""
    segs = {s['seg']: s for s in plan_['segments']}
    a_ref = os.path.join(work, 'cast', 'A.jpg')
    for j in cast_jobs:
        if j['id'] == 'castA':
            j['prompt'] = (f"Photoreal casting reference sheet photo, vertical 9:16, one person: {lead['description']} "
                           f"Waist-up, facing the camera, neutral relaxed expression, plain warm-grey studio wall, soft "
                           f"window light from the left, sharp eyes, real skin texture with pores. {LK['prompt']} No text.")
    for h in heroes:
        m = re.match(r'h(\d+)_(\d+)$', h['id'])
        if not m:
            continue
        si, k = int(m.group(1)), int(m.group(2))
        im = segs[pslots[si]['seg']]['images'][k]
        d = int(im.get('duration') or 5)
        h['duration'] = d
        h['prompt'] = re.sub(r'for \d+ seconds', f'for {d} seconds', h['prompt'], count=1)
        h['prompt'] = h['prompt'].replace('handheld camera, ', '')
        if 'A' in (im.get('cast') or []):
            h['images'] = [a_ref]                        # reference-image mode: the lead's sheet rides with every clip
            h['prompt'] += " The person from the reference image keeps exactly the same face, hair and clothes."
    return heroes


# ------------------------------------------------------------------------------------------------ lead approval
LEAD_SCHEMA = {"type": "object", "properties": {"approved": {"type": "boolean"}, "reason": S, "fix": S},
               "required": ["approved", "reason", "fix"]}


def approve_lead(P, args):
    """Opus looks at the lead's reference sheet before any batch; one reroll with its fix if rejected. Fail-open."""
    import slop_opus as SO, real_gen
    work = P['work']
    a = os.path.join(work, 'cast', 'A.jpg')
    book = P.get('book') or {}
    rep = {'tries': []}
    for attempt in range(2):
        if not os.path.exists(a):
            break
        jd = os.path.join(work, 'judge'); os.makedirs(jd, exist_ok=True)
        pf = os.path.join(jd, f'lead_prompt{attempt}.txt')
        open(pf, 'w').write(f"Use the Read tool to look at {a}. It is the reference sheet for the lead of a photoreal music "
                            f"video; every shot will be made from it. Intended person: {book.get('lead', {}).get('description', '')}\n"
                            "APPROVE only if it reads as a real photograph of an ordinary real person (pores, natural "
                            "asymmetry, no waxy/airbrushed skin, no uncanny eyes, no glamour retouch, correct hands), matches "
                            "the intended age, hair and wardrobe, and has no text or logos. If not, 'fix' is a rewritten "
                            "40-70 word portrait prompt. JSON only.")
        try:
            res, meta = SO.run_claude(pf, jd, LEAD_SCHEMA, 240, tools='Read', effort='medium')
        except Exception as e:
            rep['error'] = repr(e)[:200]; break
        rep['tries'].append(res)
        G.log(f"claudia: lead sheet {'APPROVED' if res.get('approved') else 'rejected'} ({res.get('reason', '')[:90]})")
        if res.get('approved') or attempt == 1 or args.skip_gen:
            break
        j = next((x for x in P['cast_jobs'] if x['id'] == 'castA'), None)
        if not j:
            break
        os.replace(a, a.replace('.jpg', f'_rej{attempt}.jpg'))
        j['prompt'] = f"Photoreal casting reference sheet photo, vertical 9:16, one person: {res.get('fix', '')} {P['LK']['prompt']} No text."
        real_gen.Batcher(work, {'gen': 2, 'edit': 0, 'i2v': 0}, batch_size=1, max_parallel=1, tag='cast_retry', timeout=300).run([j])
    rep['approved'] = bool(rep['tries'] and rep['tries'][-1].get('approved'))
    G.save_json(rep, os.path.join(work, 'lead_approval.json'))
    return rep


# ------------------------------------------------------------------------------------------------ usable windows
WIN_SCHEMA = {"type": "object", "properties": {"windows": {"type": "array", "items": {"type": "object", "properties": {
    "id": S, "in": {"type": "number"}, "out": {"type": "number"}, "note": S}, "required": ["id", "in", "out"]}}},
    "required": ["windows"]}


def pick_windows(P, clips):
    """frames every 0.5 s per clip -> one sheet per clip row -> one Opus call -> windows.json {basename: [in, out]}."""
    import judge as J, slop_opus as SO
    import cine_real as CR
    work = P['work']
    wd = os.path.join(work, 'windows'); os.makedirs(wd, exist_ok=True)
    out = {}
    rows, sheets = [], []
    for c in clips:
        d = CR._DUR.get(c) or G.duration(c)
        out[os.path.basename(c)] = [0.15, max(0.5, d - 0.1)]
        ts = [round(x * 0.5, 1) for x in range(int(d / 0.5) + 1) if x * 0.5 <= d - 0.05]
        items = []
        for t in ts:
            f = os.path.join(wd, f"{os.path.basename(c)[:-4]}_{t:04.1f}.jpg")
            if not os.path.exists(f):
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', c, '-frames:v', '1', '-vf', 'scale=216:-2', f])
            if os.path.exists(f):
                items.append((f, f"{os.path.basename(c)[:-4]} {t}s"))
        if items:
            sheets.append(J.tile(items, os.path.join(wd, f"sheet_{os.path.basename(c)[:-4]}.jpg"), cols=len(items), w=144, h=256))
            rows.append(f"{os.path.basename(c)} | {d:.1f}s")
    G.save_json(out, os.path.join(work, 'windows.json'))
    if not sheets:
        return out
    try:
        for n in range(0, len(sheets), 12):
            part, prow = sheets[n:n + 12], rows[n:n + 12]
            pf = os.path.join(wd, f'prompt{n // 12}.txt')
            open(pf, 'w').write(
                "You are the film editor. Use the Read tool on each contact sheet: " + ', '.join(os.path.basename(x) for x in part)
                + ". Each sheet is ONE generated clip, frames every 0.5 s (labelled with the time). Pick the clip's USABLE "
                "window: the longest continuous stretch with no morphing faces or hands, no melting objects, no sudden "
                "new objects, no frozen start frames, no warping at the end. 'in'/'out' in seconds (out > in + 1.0 when "
                "at all possible). JSON only; 'id' = the clip file name.\nCLIPS:\n" + '\n'.join(prow))
            res, meta = SO.run_claude(pf, wd, WIN_SCHEMA, 300, tools='Read', effort='low')
            for w in res.get('windows') or []:
                k = os.path.basename(str(w.get('id', '')).strip())
                k = k if k.endswith('.mp4') else k + '.mp4'
                if k in out and float(w['out']) - float(w['in']) >= 0.6:
                    lo, hi = out[k]
                    out[k] = [round(max(0.0, float(w['in'])), 2), round(min(hi + 0.1, float(w['out'])), 2)]
        G.log(f"claudia: usable windows picked for {len(out)} clips")
    except Exception as e:
        G.log(f"WARNING: claudia window pick fell back to defaults: {e!r}"[:300])
    G.save_json(out, os.path.join(work, 'windows.json'))
    return out


# ------------------------------------------------------------------------------------------------ edit
def make_edit(L, pslots, work, ok, ex, segs_tl, dur):
    """one scene per slot: from its first sung word to the next scene; its shots split it at word onsets; each shot plays
    its clip's usable window at 1x; if the window is shorter, the next shot of the same scene (or its still) covers."""
    import cine_real as CR
    win = G.load_json(os.path.join(work, 'windows.json'), {}) or {}
    onset = {RP.line_id(l): l['words'][0][1] for l in L if l.get('words')}
    words = {RP.line_id(l): [w[1] for w in l['words'] if w[1] is not None] for l in L if l.get('words')}
    cam0 = min([s['t0'] for s in segs_tl if s['kind'] in ('cameo', 'credits')] or [dur - 4.3])
    sung = [s for s in pslots if s.get('lines')]
    starts = {}
    for s in sung:
        t = [onset[i] for i in s['lines'] if i in onset]
        if t:
            starts[s['seg']] = max(0.0, min(t) - 0.12)
    last_word = max([w[-1] for w in words.values() if w] or [cam0 - 3])
    edit = []
    order = [s for s in pslots if s['kind'] == 'hook' or s['seg'] in starts or s['kind'] == 'outro_tail']
    for n, s in enumerate(order):
        if s['kind'] == 'hook':
            a, b = 0.0, min(starts.values()) if starts else 3.0
        elif s['kind'] == 'outro_tail':
            a, b = min(cam0 - 0.8, last_word + 1.2), cam0
        else:
            a = starts[s['seg']]
            nxt = [starts[x['seg']] for x in order[n + 1:] if x['seg'] in starts]
            b = nxt[0] if nxt else min(cam0 - 0.8, last_word + 1.2)
        if b - a < 0.3:
            continue
        si = pslots.index(s)
        shots = []
        for k in range(s['images']):
            st = os.path.join(work, 'stills', f's{si:02d}_{k}.jpg')
            cl = os.path.join(work, 'heroes', f'h{si:02d}_{k}.mp4')
            st = st if os.path.exists(st) and os.path.basename(st) not in ex and CR.valid_image(st) else None
            cl = cl if cl in ok else None
            if st or cl:
                shots.append((st, cl))
        if not shots:
            continue
        ons = sorted(w for i in s['lines'] for w in words.get(i, []) if a < w < b)
        span = b - a
        info = []                                         # (still, clip, w0, w1, clip_len)
        for st, cl in shots:
            if cl:
                d = CR._DUR.get(cl) or G.duration(cl)
                w0, w1 = win.get(os.path.basename(cl), [0.15, d - 0.1])
                info.append((st, cl, w0, w1, d))
            else:
                info.append((st, None, 0, 3.0, 3.0))
        tot = sum(x[3] - x[2] for x in info)
        if tot >= span:                                   # windows cover the scene: shorten each proportionally
            lens = [(x[3] - x[2]) * span / tot for x in info]
            extra = 0.0
        else:                                             # short: borrow margins outside the picked windows first
            lens = [x[3] - x[2] for x in info]
            extra = span - tot
            for i, x in enumerate(info):
                if extra <= 0 or not x[1]:
                    continue
                room = max(0.0, x[2] - 0.04) + max(0.0, x[4] - 0.04 - x[3])
                add = min(room, extra)
                lens[i] += add; extra -= add
        cuts = [a]
        for L_ in lens[:-1]:                              # cut points snap to a sung-word onset within 0.4 s
            c = cuts[-1] + L_
            near = [w for w in ons if abs(w - c) <= 0.4]
            cuts.append(min(near, key=lambda w: abs(w - c)) - 0.04 if near else c)
        cuts.append(a + sum(lens))
        for i, x in enumerate(info):
            t0, t1 = cuts[i], cuts[i + 1]
            if t1 - t0 < 0.3:
                continue
            st, cl, w0, w1, d = x
            if cl:
                L_ = t1 - t0
                s0 = w0 if L_ <= w1 - w0 else max(0.04, min(w0, d - 0.04 - L_))   # start earlier when it needs margin
                edit.append({'t0': round(t0, 3), 't1': round(t1, 3), 'src': cl, 'kind': 'video', 'win0': round(s0, 2),
                             'seg': s['seg'], 'seg_kind': s['kind'], 'on_beat': True, 'anchor': (0.5, 0.5),
                             'cut_in': False, 'move': 'drift', 'flash': False, 'whip': False, 'leak': False})
            elif st:
                edit.append({'t0': round(t0, 3), 't1': round(t1, 3), 'src': st, 'kind': 'still', 'seg': s['seg'],
                             'seg_kind': s['kind'], 'on_beat': True, 'anchor': (0.5, 0.5), 'cut_in': False,
                             'move': 'push_in', 'flash': False, 'whip': False, 'leak': False})
        if extra > 0.05:                                  # still short: the scene's first still holds with a slow push
            st = next((x[0] for x in info if x[0]), None)
            if st and extra >= 1.0:                       # instrumental gap: alternate the scene's stills and a second
                t, n_ = cuts[-1], 0                       # look at its clips, each <= 3.5 s (never one long freeze)
                cyc = [x for x in info if x[1]][::-1] + [x for x in info if x[0]]
                while b - t > 0.3 and cyc:
                    x = cyc[n_ % len(cyc)]
                    use_clip = n_ < len([y for y in info if y[1]]) and x[1]
                    L_ = min(b - t, 3.5 if not use_clip else min(3.5, x[4] - 0.2))
                    if b - t - L_ < 1.0:
                        L_ = b - t
                    if use_clip:
                        edit.append({'t0': round(t, 3), 't1': round(t + L_, 3), 'src': x[1], 'kind': 'video',
                                     'win0': round(max(0.04, x[4] - 0.1 - L_), 2), 'seg': s['seg'], 'seg_kind': s['kind'],
                                     'on_beat': True, 'anchor': (0.5, 0.5), 'cut_in': True, 'move': 'drift',
                                     'flash': False, 'whip': False, 'leak': False})
                    else:
                        edit.append({'t0': round(t, 3), 't1': round(t + L_, 3), 'src': x[0], 'kind': 'still',
                                     'seg': s['seg'], 'seg_kind': s['kind'], 'on_beat': True, 'anchor': (0.5, 0.5),
                                     'cut_in': False, 'move': ('push_in', 'pull_out')[n_ % 2], 'flash': False,
                                     'whip': False, 'leak': False})
                    t += L_; n_ += 1
            elif edit and edit[-1]['kind'] == 'still':
                edit[-1]['t1'] = round(b, 3)
            elif edit:                                    # < 1 s left after a clip: the next scene starts early
                edit[-1]['_short'] = round(extra, 2)
    edit.sort(key=lambda e: e['t0'])
    for i in range(1, len(edit)):                        # no overlaps; close small gaps (stills only stretch)
        gap = edit[i]['t0'] - edit[i - 1]['t1']
        if gap < 0 or (gap < 0.6 and edit[i - 1]['kind'] == 'still'):
            edit[i - 1]['t1'] = edit[i]['t0']
        elif 0 < gap:
            edit[i]['t0'] = edit[i - 1]['t1']
            if edit[i]['kind'] == 'video':
                edit[i]['win0'] = round(max(0.04, edit[i].get('win0', 0.15) - gap), 2)
    return edit


# ------------------------------------------------------------------------------------------------ typography (ASS)
W, H = 1080, 1920
ZONE = {'top': (8, 540, 300), 'upper': (8, 540, 560), 'lower': (2, 540, 1380), 'left': (7, 90, 420), 'right': (9, 990, 420)}


def _ts(t):
    t = max(0.0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(t):
    return t.replace('{', '(').replace('}', ')').replace('\\', '/')


def _wrap(words, maxc):
    lines, cur = [], []
    for w in words:
        if cur and len(' '.join(cur + [w])) > maxc:
            lines.append(cur); cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def build_ass(path, L, pslots, hl, credits_ass, dur, cam0, accent_words=()):
    """lyrics placed in each scene's type zone, word reveal on sung onsets; slim synced source tag; headline card;
    credits events copied from the existing end-card builder (credits_ass)."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyr,Inter Tight,84,&H00F4F4F4,&H00FFFFFF,&H70000000,&HA0000000,1,0,0,0,100,100,0,0,1,3,2,5,80,80,80,1
Style: LyrQ,Inter Tight,104,&H00F4F4F4,&H00FFFFFF,&H70000000,&HA0000000,1,0,0,0,100,100,-1,0,1,3,2,5,70,70,80,1
Style: Acc,Instrument Serif,96,&H0078C4EC,&H00FFFFFF,&H00000000,&HA0000000,0,1,0,0,100,100,0,0,1,0,3,5,80,80,80,1
Style: Src,Inter,38,&H00EDEDED,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,1,0,1,2,1,1,64,64,110,1
Style: Head,Instrument Serif,124,&H00FFFFFF,&H00FFFFFF,&H70000000,&H90000000,0,0,0,0,100,100,0,0,1,3,2,5,80,80,80,1
Style: HeadK,Inter,34,&H0078C4EC,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,6,0,1,0,2,5,80,80,80,1
""" + credits_ass['styles'] + """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    zone_of = {}
    for s in pslots:
        for i in s.get('lines') or []:
            zone_of[i] = (s.get('type_zone') or 'lower', s['kind'], s['section'])
    acc = {re.sub(r'[^a-z0-9%]', '', w.lower()) for w in accent_words if w}
    sung = [l for l in L if l.get('words')]
    import slop_real as SR
    for li, l in enumerate(sung):
        lid = RP.line_id(l)
        z, kind, sec = zone_of.get(lid, ('lower', l['kind'], l['section']))
        al, x, y = ZONE[z]
        quick = _quick(kind, sec)
        ws = [w for w in l['words'] if w[1] is not None]
        if not ws:
            continue
        t0 = ws[0][1] - 0.15
        nxt = sung[li + 1]['words'][0][1] - 0.08 if li + 1 < len(sung) else ws[-1][2] + 1.0
        t1 = min(max(ws[-1][2] + 0.6, t0 + 0.8), nxt, cam0 - 0.1)
        if t1 <= t0:
            continue
        maxc = 14 if z in ('left', 'right') else (16 if quick else 20)
        rows = _wrap([w[0] for w in ws], maxc)
        parts, k = [], 0
        for r in rows:
            seg = []
            for w in r:
                ms = int(max(0, (ws[k][1] - t0)) * 1000)
                is_acc = re.sub(r'[^a-z0-9%]', '', w.lower()) in acc or bool(re.search(r'\d', w))
                fn = "\\fnInstrument Serif\\i1\\c&H0078C4EC&" if is_acc else ''
                seg.append(f"{{\\alpha&HFF&{fn}\\t({ms},{ms + 90},\\alpha&H00&)}}{_esc(w)}{{\\fnInter Tight\\i0\\c&H00F4F4F4&}}")
                k += 1
            parts.append(' '.join(seg))
        st = 'LyrQ' if quick else 'Lyr'
        ev.append(f"Dialogue: 5,{_ts(t0)},{_ts(t1)},{st},,0,0,0,,{{\\an{al}\\pos({x},{y})\\blur2.5\\fad(0,160)}}" + '\\N'.join(parts))
    # slim synced source tag (story of the line being sung)
    if hl:
        cur, a = None, None
        spans = []
        for l in sung:
            n = hl['line_story'].get(SR._norm(l['text']))
            n = n if n in hl['ticker'] else None
            if n != cur:
                if cur is not None:
                    spans.append((cur, a, l['words'][0][1] - 0.1))
                cur, a = n, l['words'][0][1] - 0.2
        if cur is not None:
            spans.append((cur, a, min(sung[-1]['words'][-1][2] + 1.0, cam0 - 0.1)))
        for n, a, b in spans:
            hs = re.findall(r'@[A-Za-z0-9_]+', hl['ticker'][n])
            if not hs or b - a < 0.6:
                continue
            ev.append(f"Dialogue: 4,{_ts(a)},{_ts(b)},Src,,0,0,0,,{{\\fad(200,200)}}via  {{\\b1}}{_esc(hs[0])}"
                      + (f"{{\\b0\\alpha&H60&}}  ·  story {n}" if False else ''))
        if hl.get('card') and sung:
            c0 = max(0.4, sung[0]['words'][0][1] - 3.6)
            c1 = sung[0]['words'][0][1] - 0.3
            if c1 - c0 > 1.0:
                rows = _wrap(hl['card'].split(), 16)
                ev.append(f"Dialogue: 6,{_ts(c0 - 0.2)},{_ts(c1)},HeadK,,0,0,0,,{{\\an5\\pos(540,700)\\fad(250,200)}}TODAY")
                ev.append(f"Dialogue: 6,{_ts(c0)},{_ts(c1)},Head,,0,0,0,,{{\\an5\\pos(540,880)\\fad(350,200)}}"
                          + '\\N'.join(_esc(' '.join(r)) for r in rows))
    ev += credits_ass['events']
    open(path, 'w').write(head + '\n'.join(ev) + '\n')
    return len(ev)


def credits_from(ass_path, c0):
    """keep the end card: the style lines + every event starting at the credits from an existing build_ass output."""
    txt = open(ass_path).read()
    styles = '\n'.join(l for l in txt.splitlines() if l.startswith('Style:'))
    evs = []
    for l in txt.splitlines():
        if l.startswith('Dialogue:'):
            p = l.split(',', 9)
            h, m, s = p[1].split(':')
            if int(h) * 3600 + int(m) * 60 + float(s) >= c0 - 0.05:
                evs.append(l)
    return {'styles': styles, 'events': evs}


# ------------------------------------------------------------------------------------------------ grade
def write_lut(path, n=33):
    """soft film LUT: lifted blacks, gentle S, warm highlights / slightly cool shadows, 8% desaturation."""
    with open(path, 'w') as f:
        f.write(f'TITLE "claudia soft film"\nLUT_3D_SIZE {n}\n')
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    rgb = [r / (n - 1), g / (n - 1), b / (n - 1)]
                    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                    o = []
                    for i, v in enumerate(rgb):
                        v = y + (v - y) * 0.92
                        v = v + 0.06 * math.sin(math.pi * (v - 0.5)) * (1 - abs(2 * v - 1))   # gentle S
                        v = 0.035 + v * 0.95                                                    # lifted blacks, soft white
                        v += (0.018 * y if i == 0 else -0.012 * y if i == 2 else 0)             # warm highs
                        v += (0.012 * (1 - y) if i == 2 else 0)                                 # cool shadows
                        o.append(min(1.0, max(0.0, v)))
                    f.write(f"{o[0]:.5f} {o[1]:.5f} {o[2]:.5f}\n")
    return path


def grade(video, work):
    lut = write_lut(os.path.join(work, 'claudia_soft_film.cube'))
    tmp = video[:-4] + '.grade.mp4'
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-vf', f"lut3d={lut}", '-c:v', 'libx264', '-preset',
                        'medium', '-crf', '18', '-maxrate', '12M', '-bufsize', '24M', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
                        '-movflags', '+faststart', tmp], capture_output=True, text=True)
    if r.returncode == 0 and os.path.getsize(tmp) > 100000:
        os.replace(tmp, video)
        G.log("claudia: LUT grade pass applied (soft film)")
        return True
    G.log(f"WARNING: claudia grade pass failed: {r.stderr[-200:]}")
    return False
