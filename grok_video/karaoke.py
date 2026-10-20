"""karaoke mode: the daily video in the ONUG "No Window" format (default since 20 Oct 2026). See README.md "karaoke".
usage: karaoke.py DAY_DIR [--out FILE] [--work DIR] [--skip-gen] [--replan] [--no-fallback] [--stills N] [--clips N]
                  [--time-limit MIN] [--max-pct P] [--no-16x9]  (+ any grok_video.py args, passed to the fallback)
Writes <day>/video_karaoke.mp4 (1080x1920, posted), video_karaoke_chat.mp4 (<25 MB), video_karaoke_16x9.mp4.
On any failure (not exit 6 instrumental / 7 auth) it runs grok_video.py (the Claudia/slopcore chain) with the same args.
Last stdout line: GROK_VIDEO_STATUS=... out=<mp4> chat=<mp4> (same contract as grok_video.py)."""
import argparse, json, math, os, re, shutil, subprocess, sys, threading, time, traceback
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import common_gv as G

FPS = 30
TEMPLATES = ['headline', 'bignum', 'bars', 'post', 'feed', 'inbox', 'chat', 'code', 'terminal', 'rows', 'stamp', 'quote', 'browser', 'gauge', 'compare', 'countdown', 'screen']
MAX_PER_TEMPLATE = 2
MAX_SHOT = float(os.environ.get('GV_KARAOKE_MAX_SHOT', 3.6))
PLAN_VER = 'karaoke-3'
SCHEMA = {"type": "object", "required": ["scenes", "lines", "intro", "breaks", "outro", "story_text", "credit", "design"],
          "properties": {
              "scenes": {"type": "array", "items": {"type": "object", "required": ["id", "prompt", "motion"],
                         "properties": {"id": {"type": "string"}, "prompt": {"type": "string"}, "motion": {"type": "string"}}}},
              "lines": {"type": "array", "items": {"type": "object", "required": ["i", "shows", "fact", "v"],
                        "properties": {"i": {"type": "integer"}, "shows": {"type": "string"}, "fact": {"type": "string"}, "v": {"type": "array", "items": {"type": "object"}}}}},
              "intro": {"type": "array", "items": {"type": "object"}},
              "breaks": {"type": "array", "items": {"type": "object"}},
              "outro": {"type": "array", "items": {"type": "object"}},
              "story_text": {"type": "array", "items": {"type": "object", "required": ["from_line", "to_line", "kicker", "text"],
                             "properties": {"from_line": {"type": "integer"}, "to_line": {"type": "integer"},
                                            "kicker": {"type": "string"}, "text": {"type": "string"}}}},
              "credit": {"type": "string"},
              "design": {"type": "object", "required": ["palette", "type", "lyric_style", "lyric_pos", "transition", "grade", "texture", "why"],
                         "properties": {k: {"type": "string"} for k in ("palette", "type", "lyric_style", "lyric_pos", "transition", "grade", "texture", "why")}}}}
SCREEN_RULE = (" Any laptop, monitor or phone: its SCREEN faces the camera (we see the display, shot over the user's shoulder "
               "from behind them, or a straight-on screen view); never show the back of a laptop lid, never put an image or "
               "glow on the back of a lid, no screens facing away from camera.")
LOOK = (" Photorealistic cinematic film still, natural skin texture, motivated practical lighting, vertical 9:16 composition. "
        "Cast are young adults aged 21-28, attractive, natural balanced expressions. No robots, no text, no logos, no "
        "readable writing, no famous people." + SCREEN_RULE)


def norm(s): return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def lyric_lines(day):
    out = []
    for l in G.read(os.path.join(day, 'lyrics.txt')).splitlines():
        l = l.strip()
        if l and not (l.startswith('[') and l.endswith(']')):
            out.append(l)
    return out


# ---------------------------------------------------------------- alignment (ONUG method)
DEMUCS = os.environ.get('DEMUCS', '/home/box/venvs/align/bin/demucs')
ALIGN_PY = os.environ.get('PY', '/home/box/venvs/align/bin/python')
_ALIGN_SRC = r"""
import stable_whisper, sys
m = stable_whisper.load_model(sys.argv[4] if len(sys.argv) > 4 else 'medium.en')
r = m.align(sys.argv[1], open(sys.argv[2]).read(), language='en', original_split=True)
r.save_as_json(sys.argv[3])
"""


def lyric_sections(day):
    """[(text, section, kind, section_occ, line_no)] for the sung lines of lyrics.txt."""
    out, sec, occ, cnt, ln = [], 'Verse', {}, {}, 0
    for l in G.read(os.path.join(day, 'lyrics.txt')).splitlines():
        l = l.strip()
        if not l: continue
        if l.startswith('[') and l.endswith(']'):
            name = l[1:-1].strip()
            k = norm(name)
            if any(x in k for x in ('verse', 'chorus', 'bridge', 'intro', 'outro', 'hook', 'pre', 'refrain', 'break')):
                sec = name; occ[sec] = occ.get(sec, 0) + 1; ln = 0
            continue
        ln += 1; k = norm(sec)
        kind = ('chorus' if 'chorus' in k or 'hook' in k or 'refrain' in k else 'bridge' if 'bridge' in k else
                'outro' if 'outro' in k else 'intro' if 'intro' in k else 'verse')
        out.append((l, sec, kind, occ.get(sec, 1), ln))
    return out


def vocal_activity(stem):
    import numpy as np, soundfile as sf
    y, sr = sf.read(stem, dtype='float32'); y = y.mean(1) if y.ndim > 1 else y
    hop = int(sr * 0.05); n = len(y) // hop
    db = 20 * np.log10(np.sqrt(np.mean(np.square(y[:n * hop].reshape(n, hop)), axis=1)) + 1e-9)
    return db > (np.percentile(db, 95) - 28), 0.05


def line_score(ln, act, hop):
    """1 = the line's words sit on audible vocals and look plausible; 0 = suspect."""
    w = ln.get('words') or []
    if not w: return 0.0
    if any(b[2] < b[1] - 0.01 or b[2] - b[1] > 4.0 for b in w): return 0.0
    if len(w) >= 4 and (w[-1][2] - w[0][1]) < 0.18 * len(w): return 0.0          # squeezed
    tot = on = 0
    for b in w:
        i0, i1 = int(b[1] / hop), max(int(b[1] / hop) + 1, int(b[2] / hop))
        seg = act[i0:i1]; tot += len(seg); on += int(seg.sum())
    return on / tot if tot else 0.0


def align_karaoke(day, work, status):
    """demucs vocals -> stable-ts forced alignment of lyrics.txt (the ONUG method, ~1-5 min on the box CPU) ->
    per-line sanity score. Returns (L, report)."""
    aw = os.path.join(work, 'kalign'); os.makedirs(aw, exist_ok=True)
    audio = G.audio_path(day); t0 = time.time()
    secs = lyric_sections(day)
    open(os.path.join(aw, 'lines.txt'), 'w').write('\n'.join(x[0] for x in secs) + '\n')
    stem = os.path.join(aw, 'sep', 'htdemucs', os.path.splitext(os.path.basename(audio))[0], 'vocals.wav')
    logf = open(os.path.join(aw, 'align.log'), 'a')
    if not (os.path.exists(stem) and os.path.getmtime(stem) >= os.path.getmtime(audio)):
        subprocess.run([DEMUCS, '-n', 'htdemucs', '--two-stems', 'vocals', '-o', os.path.join(aw, 'sep'), audio],
                       check=True, stdout=logf, stderr=subprocess.STDOUT, timeout=900)
    G.log(f"karaoke align: demucs done ({time.time() - t0:.0f}s)")
    import grok_video as GV
    vm = GV.vocal_metrics(stem, stem.replace('vocals.wav', 'no_vocals.wav')); G.save_json(vm, os.path.join(aw, 'vocal_check.json'))
    aj = os.path.join(aw, 'align.json')
    if not (os.path.exists(aj) and os.path.getmtime(aj) >= os.path.getmtime(stem)):
        sp_ = os.path.join(aw, 'align_run.py'); open(sp_, 'w').write(_ALIGN_SRC)
        subprocess.run([ALIGN_PY, sp_, stem, os.path.join(aw, 'lines.txt'), aj, os.environ.get('GV_KARAOKE_ALIGN_MODEL', 'medium.en')],
                       check=True, stdout=logf, stderr=subprocess.STDOUT, timeout=1200)
    G.log(f"karaoke align: stable-ts done ({time.time() - t0:.0f}s)")
    segs = G.load_json(aj)['segments']
    L = []
    for i, sg in enumerate(segs):
        words = [[w['word'].strip(), round(w['start'], 3), round(w['end'], 3)] for w in sg.get('words', []) if w['word'].strip()]
        meta = secs[i] if i < len(secs) else (sg['text'].strip(), 'Verse', 'verse', 1, 1)
        L.append({'n': i, 'text': meta[0] if norm(meta[0]) == norm(sg['text']) else sg['text'].strip(), 'section': meta[1],
                  'kind': meta[2], 'section_occ': meta[3], 'line_no': meta[4], 'words': words,
                  'start': words[0][1] if words else sg['start'], 'end': words[-1][2] if words else sg['end'], 'src_timing': 'stable-ts-direct'})
    act, hop = vocal_activity(stem)
    sc = [round(line_score(ln, act, hop), 2) for ln in L]
    for ln, x in zip(L, sc): ln['sync_score'] = x
    bad = [i for i, x in enumerate(sc) if x < 0.45]
    rep = {'method': 'stable-ts-direct', 'lines': len(L), 'expected_lines': len(secs), 'suspect_lines': bad, 'scores': sc,
           'mean_score': round(sum(sc) / max(1, len(sc)), 3), 'secs': round(time.time() - t0)}
    G.save_json(rep, os.path.join(aw, 'sync_check.json')); G.save_json(L, os.path.join(aw, 'timings.json'))
    return L, rep, vm


# ---------------------------------------------------------------- planning
def plan_opus(day, work, nscenes, nclips):
    import slop_opus as SO
    lines = lyric_lines(day)
    st = G.read(os.path.join(day, 'stories.md'))
    txt = open(os.path.join(HERE, 'prompts', 'karaoke_plan.txt')).read()
    import design as DZ
    hist = '\n'.join(json.dumps({k: h.get(k) for k in ('day', 'palette', 'type', 'lyric_style', 'lyric_pos', 'transition', 'grade', 'texture')}) for h in DZ.history()) or '(none yet)'
    for k, v in dict(DESIGN_MENU=DZ.menu_text(), DESIGN_HISTORY=hist, TEMPLATES=', '.join(TEMPLATES), SCENES_MAX=nscenes, CLIPS_MAX=nclips, INTRO_S='8-15', TITLE=G.read(os.path.join(day, 'title.txt')).strip(), GENRE=G.genre_of(day)[0] or 'pop',
                     STYLE=G.read(os.path.join(day, 'style.txt')).strip()[:300], STORIES=st[:9000],
                     LINES='\n'.join(f"{i}: {l}" for i, l in enumerate(lines))).items():
        txt = txt.replace('{' + k + '}', str(v))
    od = os.path.join(work, 'opus'); os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'plan_prompt.txt'); open(pf, 'w').write(txt)
    last = None
    for attempt in (1, 2):
        try:
            plan, meta = SO.run_claude(pf, od, SCHEMA, int(os.environ.get('GV_KARAOKE_OPUS_S', 480)), tools='', effort='medium')
            G.save_json({k: v for k, v in meta.items() if k != 'raw'}, os.path.join(od, f'meta{attempt}.json'))
            if plan and plan.get('lines'):
                plan['planner'] = 'opus'; return plan
            last = 'empty plan'
        except Exception as e:
            last = repr(e)[:300]
        G.log(f"karaoke: opus plan attempt {attempt} failed: {last}")
    raise RuntimeError('opus plan failed: ' + str(last))


def plan_template(day):
    """No-LLM fallback plan: story headlines, post cards and figures straight from stories.md, no Grok scenes."""
    stories = G.story_list(day); lines = lyric_lines(day)
    pool = []
    for s in stories:
        h = (s.get('handles') or [''])[0]
        pool.append({'kind': 'gfx', 'g': 'headline', 'p': {'kicker': f"STORY {s['idx']}" + (f" · @{h}" if h else ''), 'text': s['text']}})
        if h:
            body = re.sub(r'https?://\S+', '', s['detail'].split('. ', 1)[-1]).strip()
            pool.append({'kind': 'gfx', 'g': 'post', 'p': {'handle': h, 'name': h, 'text': body[:140]}})
        for n in re.findall(r'\b\d[\d,]*\b', s['detail'].split('http')[0])[:2]:
            if n not in ('2026',):
                pool.append({'kind': 'gfx', 'g': 'bignum', 'p': {'top': f"STORY {s['idx']}", 'value': n, 'sub': s['text'][:60]}})
    P = {'planner': 'template', 'scenes': [], 'lines': [{'i': i, 'v': [pool[i % len(pool)]]} for i in range(len(lines))],
         'intro': pool[:2], 'breaks': pool[2:6] or pool, 'outro': pool[:1],
         'story_text': [{'from_line': 0, 'to_line': len(lines) - 1, 'kicker': 'MAIN STORY', 'text': stories[0]['text'][:70]}] if stories else [],
         'credit': stories[0]['text'][:70] if stories else ''}
    return P


def fact_lint(P, day):
    """Every token with a digit and every @handle shown in a GFX must exist in stories/lyrics/title. Bad visuals are
    replaced by a story headline card. Returns warnings."""
    src = norm(G.read(os.path.join(day, 'stories.md')) + ' ' + G.read(os.path.join(day, 'lyrics.txt')) + ' ' +
               G.read(os.path.join(day, 'title.txt'))).replace(' ', '')
    raw = G.read(os.path.join(day, 'stories.md')).lower()
    stories = G.story_list(day); warns = []
    safe = {'0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0s', '200', '404', '100', '0.0', '1.0'}

    def strings(o):
        if isinstance(o, str): yield o
        elif isinstance(o, dict):
            for v in o.values(): yield from strings(v)
        elif isinstance(o, list):
            for v in o: yield from strings(v)

    def bad(v):
        if v.get('kind') != 'gfx': return None
        for s in strings(v.get('p', {})):
            # figures (numbers with 2+ digits) and CVE ids; identifiers like mx1 / noc-01 / v4.2 are fine
            for tok in re.findall(r'CVE-\d{4}-\d+|(?<![A-Za-z\-.])\d[\d,.]*\d(?![A-Za-z\d])', s):
                t = norm(tok).replace(' ', '')
                if t and t not in safe and t not in src and not re.fullmatch(r'\d{1,2}(:\d\d)+', tok) \
                        and v.get('g') not in ('code', 'countdown'):
                    return f"figure {tok!r} not in sources"
            for h in re.findall(r'(?<![\w.])@(\w+)', s):
                if h.lower() not in raw: return f"handle @{h} not in sources"
        if v.get('g') == 'post' and v['p'].get('handle', '').lower().lstrip('@') not in raw:
            return f"post handle {v['p'].get('handle')!r} not in sources"
        return None

    def fix(v, where):
        b = bad(v)
        if not b: return v
        warns.append(f"{where}: {v.get('g')} replaced ({b})")
        s = stories[0] if stories else {'idx': 1, 'text': G.read(os.path.join(day, 'title.txt'))}
        return {'kind': 'gfx', 'g': 'headline', 'p': {'kicker': f"STORY {s['idx']}", 'text': s['text']}}
    for ln in P.get('lines', []):
        ln['v'] = [fix(v, f"line {ln['i']}") for v in ln.get('v', [])][:2]
    for k in ('intro', 'breaks', 'outro'):
        P[k] = [fix(v, k) for v in P.get(k, [])]
    import kgfx2 as kgfx
    for v in [v for ln in P['lines'] for v in ln['v']] + P['intro'] + P['breaks'] + P['outro']:
        if v.get('kind') == 'gfx' and v.get('g') not in kgfx.R:
            warns.append(f"unknown gfx {v.get('g')!r} -> headline"); v['g'] = 'headline'; v['p'] = {'text': str(v.get('p', {}).get('text') or G.read(os.path.join(day, 'title.txt')))}
    return warns


# ---------------------------------------------------------------- media
def dup_halves(png):
    """Grok sometimes returns a 9:16 picture that is two copies of the same frame stacked (seen 20 Oct)."""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(png).convert('L').resize((90, 160)), dtype=float)
        return float(np.corrcoef(a[:80].ravel(), a[80:].ravel())[0, 1]) > 0.6
    except Exception:
        return False


SCREEN_SCHEMA = {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {
    "type": "object", "required": ["id", "device_present", "user_faces_camera_behind_device", "display_visible_to_camera",
                                   "other_problem", "issue"],
    "properties": {"id": {"type": "string"}, "device_present": {"type": "boolean"},
                   "user_faces_camera_behind_device": {"type": "boolean"}, "display_visible_to_camera": {"type": "boolean"},
                   "other_problem": {"type": "boolean"}, "issue": {"type": "string"}}}}}}
DEVICE_RE = re.compile(r'laptop|phone|screen|monitor|tablet|computer|keyboard|display|terminal|inbox|email', re.I)
DEVICE_PREFIX = ("CAMERA POSITION: behind the person, over their shoulder, so we see the back of their head and the FRONT "
                 "of the device's screen (screen content faces the camera, the person faces away from camera). ")


def screen_check(gdir, jobs, status, tag):
    """Claude looks at every still: reject reversed/impossible screens (content on a laptop lid, screen facing away
    while we are meant to see it, glowing backs), robots, readable gibberish text, duplicated/stacked frames, bad hands
    or faces. Returns the set of rejected ids. Fails open (logs) if the checker is unavailable."""
    if not jobs: return set()
    import slop_opus as SO
    names = [os.path.basename(j['out']) for j in jobs]
    pf = os.path.join(gdir, f'screen_check_{tag}.txt')
    open(pf, 'w').write(
        "You are a strict continuity checker for photoreal stills in a music video. Read each image file listed below "
        "(use the Read tool on each, in this directory) and answer the fields for each image literally:\n"
        "- device_present: any laptop/phone/monitor/tablet that someone is using.\n"
        "- user_faces_camera_behind_device: the person using that device faces the camera with the device between them "
        "and the camera (we see their face over/behind the device).\n"
        "- display_visible_to_camera: we can see that device's lit screen content (UI, code, image).\n"
        "  If BOTH of the last two are true the screen is physically on the wrong side: that is the main failure.\n"
        "- other_problem: anything in the list below.\n"
        "Reject (ok=false) if ANY of these: a laptop shows an image/screen content on the BACK of its lid; a laptop/monitor/"
        "phone that the person is using has its screen facing away from the camera while the shot is about what is on it "
        "(we only see the back of the lid/monitor, which looks like a screen); a screen glows on the wrong side; a device "
        "is physically impossible; the frame is two stacked copies of the same picture; a robot or android; garbled "
        "readable text that is prominent; badly malformed hands or faces. A laptop seen from behind is ONLY acceptable if "
        "its lid back is plain (no picture) and we are clearly looking at the person's face, not the screen; when unsure, "
        "reject.\nGive a short issue for each problem image, '' otherwise. id = the file name without .png.\n\nFILES:\n"
        + '\n'.join(names))
    try:
        res, meta = SO.run_claude(pf, gdir, SCREEN_SCHEMA, 420, tools='Read', effort='medium')
    except Exception as e:
        G.log(f"karaoke: screen check unavailable ({str(e)[:150]}); continuing without it")
        status.setdefault('warnings', []).append('screen check unavailable'); return set()
    rs = {r['id'].replace('.png', ''): r for r in (res or {}).get('results', [])}
    G.save_json(rs, os.path.join(gdir, f'screen_check_{tag}.json'))
    for r in rs.values():
        r['ok'] = not ((r.get('user_faces_camera_behind_device') and r.get('display_visible_to_camera')) or r.get('other_problem'))
    bad = {k for k, r in rs.items() if not r.get('ok')}
    G.log(f"karaoke: screen check {tag}: {len(rs)} checked, rejected {sorted(bad)}")
    status.setdefault('screen_checks', {})[tag] = {k: r.get('issue') for k, r in rs.items() if not r.get('ok')}
    return bad


def generate(P, work, a, deadline, status):
    import real_gen as R
    gdir = os.path.join(work, 'grok'); os.makedirs(gdir, exist_ok=True)
    scenes = P.get('scenes', [])[:a.stills]
    if not scenes or a.skip_gen:
        return
    used = {}
    for v in [v for ln in P['lines'] for v in ln['v']] + P['intro'] + P['breaks'] + P['outro']:
        if v.get('kind') == 'scene': used[v.get('id')] = used.get(v.get('id'), 0) + 1
    jobs = [{'id': s['id'], 'kind': 'gen', 'prompt': (DEVICE_PREFIX if DEVICE_RE.search(s['prompt']) else '') + s['prompt'].strip() + LOOK, 'aspect': '9:16', 'out': f"{gdir}/{s['id']}.png"}
            for s in scenes]
    b = R.Batcher(gdir, {'gen': len(jobs) + 3}, batch_size=5, max_parallel=3, deadline=deadline - 9 * 60, tag='stills')
    b.run(jobs)
    dups = [j for j in jobs if os.path.exists(j['out']) and dup_halves(j['out'])]
    if dups and time.time() < deadline - 10 * 60:          # one reroll for stacked-duplicate pictures
        G.log(f"karaoke: rerolling {len(dups)} stacked-duplicate stills: {[j['id'] for j in dups]}")
        for j in dups: os.replace(j['out'], j['out'] + '.dup.png')
        b3 = R.Batcher(gdir, {'gen': len(dups)}, batch_size=5, max_parallel=2, deadline=deadline - 9 * 60, tag='reroll')
        b3.no_salvage = True; b3.run(dups)
    bad = screen_check(gdir, [j for j in jobs if os.path.exists(j['out'])], status, 'stills')
    if bad and time.time() < deadline - 9 * 60:
        G.log(f"karaoke: rerolling {len(bad)} stills with screen problems: {sorted(bad)}")
        rj = []
        for j in jobs:
            if j['id'] in bad:
                os.replace(j['out'], j['out'] + '.screen.png')
                mp = os.path.splitext(j['out'])[0] + '.mp4'
                if os.path.exists(mp): os.replace(mp, mp + '.screen.mp4')   # clip made from the rejected still
                rj.append(dict(j, prompt=("Framing: over-the-shoulder from BEHIND the person: we see the back of their head and the "
                                          "front of their screen; the person does NOT face the camera. " + j['prompt'].replace(DEVICE_PREFIX, ''))))
        b4 = R.Batcher(gdir, {'gen': len(rj)}, batch_size=5, max_parallel=3, deadline=deadline - 8 * 60, tag='screenfix')
        b4.no_salvage = True; b4.run(rj)
        bad2 = screen_check(gdir, [j for j in rj if os.path.exists(j['out'])], status, 'reroll')
        for j in rj:
            if j['id'] in bad2 or not os.path.exists(j['out']):
                if os.path.exists(j['out']): os.replace(j['out'], j['out'] + '.screen2.png')
                status.setdefault('screen_rejected', []).append(j['id'])
    elif bad:
        for j in jobs:
            if j['id'] in bad and os.path.exists(j['out']):
                os.replace(j['out'], j['out'] + '.screen.png'); status.setdefault('screen_rejected', []).append(j['id'])
    status['stills_made'] = sum(1 for j in jobs if os.path.exists(j['out']))
    mv = sorted([s for s in scenes if s.get('motion') and os.path.exists(f"{gdir}/{s['id']}.png") and not dup_halves(f"{gdir}/{s['id']}.png")],
                key=lambda s: -used.get(s['id'], 0))[:a.clips]
    cj = [{'id': 'v_' + s['id'], 'kind': 'i2v', 'image': f"{gdir}/{s['id']}.png", 'duration': 6,
           'prompt': s['motion'] + " Realistic natural motion, cinematic, no text.", 'out': f"{gdir}/{s['id']}.mp4"} for s in mv]
    if cj and time.time() < deadline - 6 * 60:
        b2 = R.Batcher(gdir, {'i2v': len(cj) + 2}, batch_size=3, max_parallel=3, timeout=900, deadline=deadline, tag='clips')
        b2.run(cj)


# ---------------------------------------------------------------- timeline
def map_lines(P, L, day):
    """plan line index (lyrics.txt order) -> timings entry (sequential text match)."""
    lines = lyric_lines(day); out = {}; j = 0
    for i, t in enumerate(lines):
        for k in range(j, min(len(L), j + 4)):
            if norm(L[k]['text']) == norm(t) or (norm(t)[:20] and norm(L[k]['text']).startswith(norm(t)[:20])):
                out[i] = k; j = k + 1; break
    return out


def line_card(text, fact, used, handle=''):
    """A code-rendered graphic that illustrates THIS line (its words + the story fact behind it); used when the planned
    visual is missing/rejected/over the template cap. Picks the first template variant still under the cap."""
    key = max(re.findall(r"[A-Za-z0-9'-]+", text) or ['FIX'], key=len).upper()[:14]
    opts = [('headline', {'kicker': key, 'text': text, 'sub': (fact or '')[:80]}),
            ('quote', {'text': text, 'by': ('@' + handle) if handle else (fact or '')[:40]}),
            ('stamp', {'above': text[:70], 'text': key}),
            ('browser', {'url': 'news', 'site': 'TODAY', 'headline': text, 'lede': (fact or text)[:120], 'highlight': (fact or text)[:30]}),
            ('screen', {'device': 'laptop', 'app': 'news', 'text': (fact or text)[:90]})]
    for g, pp in opts:
        if used.get(g, 0) < MAX_PER_TEMPLATE:
            return {'kind': 'gfx', 'g': g, 'p': pp}
    return {'kind': 'gfx', 'g': 'headline', 'p': opts[0][1]}


def timeline(P, L, dur, day, gdir, bad_scenes=()):
    """LINE-LOCKED (20 Oct, the owner: scenes must match the line being sung): the shot(s) under each sung line are that
    line's own planned visuals, nothing else; substitutes are redrawn for the same line (line_card). Pools (intro,
    breaks, outro) are only used where nothing is sung."""
    m = map_lines(P, L, day); inv = {v: k for k, v in m.items()}
    pl = {ln['i']: ln for ln in P['lines']}
    timed = [ln for ln in L if ln.get('words')]
    pools = {k: list(P.get(k) or []) or list(P.get('breaks') or []) for k in ('intro', 'breaks', 'outro')}
    title = G.read(os.path.join(day, 'title.txt')).strip()
    fallback = [{'kind': 'gfx', 'g': 'headline', 'p': {'kicker': 'TODAY', 'text': title}}]
    ctr = {'intro': 0, 'breaks': 0, 'outro': 0}
    def take(k):
        p = pools[k] or fallback; v = p[ctr[k] % len(p)]; ctr[k] += 1; return v
    end_t = max(dur - 5.5, (timed[-1]['end'] + 0.6) if timed else dur - 5.5); end_t = min(end_t, dur - 3.5)
    cuts = []                                     # (t, visual, line_index or None)
    first = timed[0]['start'] - 0.08 if timed else end_t
    n_in = max(1, min(len(pools['intro']) or 2, int(first / 2.6)))
    for k in range(n_in):
        cuts.append((first * k / n_in, take('intro'), None))
    for idx, ln in enumerate(timed):
        n = L.index(ln); pi = inv.get(n); spec = pl.get(pi, {})
        vis = spec.get('v') or [line_card(ln['text'], spec.get('fact', ''), {})]
        t0 = max(0.0, ln['start'] - 0.08)
        cuts.append((t0, vis[0], n))
        if len(vis) > 1 and len(ln['words']) >= 4:
            mid = ln['words'][len(ln['words']) // 2][1] - 0.05
            if mid - t0 > 1.0 and ln['end'] - mid > 0.8: cuts.append((mid, vis[1], n))
        nxt = timed[idx + 1]['start'] - 0.08 if idx + 1 < len(timed) else end_t
        gs = ln['end'] + 0.35
        if nxt - gs > 2.6:                        # instrumental gap (nothing sung): break visuals every ~2.4 s
            k = int((nxt - gs) / 2.4)
            for q in range(k):
                cuts.append((gs + (nxt - gs) * q / k, take('breaks' if idx + 1 < len(timed) else 'outro'), None))
    cuts = sorted([c for c in cuts if c[0] < end_t - 0.4], key=lambda c: c[0])
    out = []
    for c in cuts:
        if out and c[0] - out[-1][0] < 0.7:
            if out[-1][2] is None: out[-1] = (out[-1][0], c[1], c[2])     # a sung line beats a filler
            continue
        out.append(c)
    shots = [{'t0': t, 't1': (out[i + 1][0] if i + 1 < len(out) else end_t), 'v': v, 'line': li} for i, (t, v, li) in enumerate(out)]
    # long holds: tail after the line ends -> an instrumental visual; still too long -> a 2nd, redrawn card for the SAME line
    sp_ = []
    for s_ in shots:
        li = s_['line']
        if li is not None and s_['t1'] - s_['t0'] > MAX_SHOT + 1.2:
            le = L[li]['end'] + 0.35
            if s_['t1'] - le > 1.6 and le - s_['t0'] > 1.0:
                sp_ += [dict(s_, t1=le), {'t0': le, 't1': s_['t1'], 'v': take('breaks'), 'line': None}]; continue
            if s_['t1'] - s_['t0'] > MAX_SHOT + 1.2:
                m_ = (s_['t0'] + s_['t1']) / 2; spec = pl.get(inv.get(li), {})
                sp_ += [dict(s_, t1=m_), {'t0': m_, 't1': s_['t1'], 'v': line_card(L[li]['text'], spec.get('fact', ''), {}), 'line': li}]; continue
        sp_.append(s_)
    shots = sp_
    # template cap and missing/rejected scenes -> redraw for the SAME line
    used = {}
    have = {x['id'] for x in P.get('scenes', []) if os.path.exists(f"{gdir}/{x['id']}.png") and x['id'] not in bad_scenes
            and not dup_halves(f"{gdir}/{x['id']}.png")}
    for s_ in shots:
        v = s_['v']; li = s_['line']
        spec = pl.get(inv.get(li), {}) if li is not None else {}
        txt = L[li]['text'] if li is not None else title
        if v.get('kind') == 'scene' and v.get('id') not in have:
            s_['v'] = v = line_card(txt, spec.get('fact', ''), used); s_['redrawn'] = 'scene missing/rejected'
        if v.get('kind') == 'gfx':
            g = 'terminal' if v.get('g') == 'term' else v.get('g')
            if used.get(g, 0) >= MAX_PER_TEMPLATE:
                s_['v'] = v = line_card(txt, spec.get('fact', ''), used); s_['redrawn'] = f'template {g} over cap'
                g = v['g']
            used[g] = used.get(g, 0) + 1
    shots.append({'t0': end_t, 't1': dur, 'v': {'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'line': None})
    seen = {}
    for s in shots:
        v = s['v']
        if v.get('kind') == 'scene':
            sid = v.get('id'); clip, png = f"{gdir}/{sid}.mp4", f"{gdir}/{sid}.png"
            k = seen.get(sid, 0); seen[sid] = k + 1
            s['src'] = ('clip', clip, [0.0, 2.6, 1.2][k % 3]) if os.path.exists(clip) and os.path.getsize(clip) > 10000 else ('still', png, k)
        else:
            s['src'] = ('gfx', v.get('g'), dict(v.get('p') or {}))
    return shots


MATCH_SCHEMA = {"type": "object", "required": ["rows"], "properties": {"rows": {"type": "array", "items": {
    "type": "object", "required": ["n", "match", "why"], "properties": {"n": {"type": "integer"}, "match": {"type": "boolean"},
                                                                       "why": {"type": "string"}}}}}}


def describe(s, P):
    v = s['v']
    if v.get('kind') == 'scene':
        sc = next((x for x in P.get('scenes', []) if x['id'] == v.get('id')), {})
        return f"photo scene {v.get('id')}: {sc.get('prompt', '')[:300]}", sc
    return f"graphic {v.get('g')}: " + json.dumps(v.get('p') or {}, ensure_ascii=False)[:300], None


def match_check(shots, L, P, work, gdir, status):
    """Claude reads every (sung line, shot) pair (scene stills are opened with Read) and says whether the shot
    literally illustrates the words being sung. Mismatched shots are redrawn for their line (line_card)."""
    import slop_opus as SO
    rows = []
    for k, s in enumerate(shots):
        if s.get('line') is None: continue
        d, sc = describe(s, P)
        img = f"{s['v']['id']}.png" if sc else ''
        rows.append({'n': k, 'line': L[s['line']]['text'], 'shot': d, 'image': img})
    pf = os.path.join(gdir, 'match_check.txt')
    open(pf, 'w').write(
        "Music-video edit check. For each row, a lyric line is sung while the shot plays. Decide `match`: does the shot "
        "LITERALLY illustrate what the line says (its people/objects/actions/numbers/story), so a viewer instantly sees the "
        "connection? A generic or merely mood-related shot is NOT a match. For photo scenes, open the image file with Read "
        "(in this directory) and judge the picture itself, not only the description. Reply for every n.\n\n"
        + '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
    try:
        res, meta = SO.run_claude(pf, gdir, MATCH_SCHEMA, 600, tools='Read', effort='medium')
        got = {r['n']: r for r in (res or {}).get('rows', [])}
    except Exception as e:
        G.log(f"karaoke: match check unavailable ({str(e)[:150]})"); status['warnings'].append('match check unavailable'); return None
    table = []
    for r in rows:
        g = got.get(r['n'], {'match': False, 'why': 'no verdict'})
        table.append(dict(r, match=bool(g.get('match')), why=g.get('why', '')))
    G.save_json(table, os.path.join(work, 'match_table_pre.json'))
    return table


# ---------------------------------------------------------------- rendering
def _fill(img, W, H):
    from PIL import Image
    sw, sh = img.size; sc = max(W / sw, H / sh); img = img.resize((int(sw * sc) + 1, int(sh * sc) + 1), Image.LANCZOS)
    x = (img.width - W) // 2; y = (img.height - H) // 2; return img.crop((x, y, x + W, y + H))


def _vf_fill(W, H):
    if H > W: return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    return (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.15[bg];"
            f"[b]scale=-2:{H}[fg];[bg][fg]overlay=(W-w)/2:0")


ENC0 = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS)]


def trans_vf(design, i, nfr):
    t = design.get('transition', 'cut')
    if i == 0 or t == 'cut': return ''
    return {'flash': 'fade=in:st=0:d=0.1:color=white', 'dip': 'fade=in:st=0:d=0.12:color=black',
            'punch': "scale=iw*1.08:ih*1.08,crop=iw/1.08:ih/1.08" if False else "zoompan=z='if(lt(on,5),1.10-0.02*on,1)':d=1:s=WxH:fps=30",
            'slide': "fade=in:st=0:d=0.08",
            'glitch': "rgbashift=rh=-8:bh=8:enable='lt(t,0.12)'"}.get(t, '')


def render_seg(job):
    s, W, H, out, endp, design, i = job
    import kgfx2 as kgfx, design as DZ
    from PIL import Image
    kgfx.set_theme(DZ.theme(design))
    tv = trans_vf(design, i, 0).replace('s=WxH', f's={W}x{H}')
    grade = DZ.GRADE.get(design.get('grade'), '')
    ENC = ENC0
    nfr = max(1, round(s['t1'] * FPS) - round(s['t0'] * FPS)); dur = nfr / FPS
    kind, src, x = s['src']
    if kind == 'clip':
        spd = min(1.0, max(0.4, (6.0 - x) / dur))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(x), '-i', src, '-filter_complex',
                        f"setpts=PTS/{spd},{_vf_fill(W, H)},fps={FPS}" + (',' + grade if grade else '') + (',' + tv if tv else ''), '-frames:v', str(nfr), '-an'] + ENC + [out], check=True)
        return out
    if kind == 'still':
        zin = x % 2 == 0
        z = (f"zoompan=z='{'1+0.0016*on' if zin else '1.12-0.0016*on'}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={nfr}:s={W}x{H}:fps={FPS}")
        pre = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2}," if H > W else
               f"split[a][b];[a]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},boxblur=40:3,eq=brightness=-0.15[bg];[b]scale=-2:{H*2}[fg];[bg][fg]overlay=(W-w)/2:0,")
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', src, '-filter_complex', pre + z + (',' + grade if grade else '') + (',' + tv if tv else ''), '-frames:v', str(nfr)] + ENC + [out], check=True)
        return out
    p = dict(x)
    if src == 'endcard':
        p.update(endp)
        if p.get('bg'): p['bg'] = _fill(Image.open(p['bg']).convert('RGB'), W, H)
    f = kgfx.R.get(src, kgfx.R['headline'])
    pr = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
                           '-i', '-'] + (['-vf', tv] if tv else []) + ENC + [out], stdin=subprocess.PIPE)
    for k in range(nfr):
        try:
            im = kgfx.render(src if src in kgfx.R else 'headline', W, H, k / FPS, dur, p)
        except Exception:
            im = kgfx.R['headline'](W, H, k / FPS, dur, {'text': str(p.get('text') or p.get('title') or '')})
        if im.size != (W, H): im = im.resize((W, H))
        pr.stdin.write(im.convert('RGB').tobytes())
    pr.stdin.close(); pr.wait()
    if pr.returncode: raise RuntimeError(f'gfx encode failed {out}')
    return out


def band_png(W, H, path, design=None):
    from PIL import Image
    import design as DZ
    th = DZ.theme(design) if design else {'bg': (0, 0, 0), 'light': False}
    bc = th['bg'] if not th['light'] else th['panel']
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); px = im.load()
    if design and design.get('lyric_pos') == 'bottom-band':
        im.save(path); return
    y0 = int(H * (0.60 if H > W else 0.62))
    for y in range(y0, H):
        a = int(min(1, (y - y0) / (H * 0.10)) * 175)
        for xx in range(W): px[xx, y] = bc + (a,)
    im.save(path)


# ---------------------------------------------------------------- lyrics (ASS)
def _ts(x):
    x = max(0, x); return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


def _esc(s): return s.replace('{', '(').replace('}', ')').replace('\\', '/')


def line_ok(ln):
    w = ln.get('words') or []
    if not w: return False
    if any(b[2] < b[1] - 0.01 or b[2] - b[1] > 4.0 for b in w): return False
    if any(w[i + 1][1] < w[i][1] - 0.05 for i in range(len(w) - 1)): return False
    return ln['end'] - ln['start'] < 14


def sanitize(L):
    """Sanity repairs on the aligner output: a word run after a > 4 s gap inside a line, or words past the next line's
    start, are re-spread right after the last good word (the aligner sometimes parks the tail of a line on a later
    line). Returns the list of repaired line texts."""
    fixed = []
    T = [ln for ln in L if ln.get('words')]
    for i, ln in enumerate(T):
        w = ln['words']; nxt = T[i + 1]['start'] if i + 1 < len(T) else 1e9
        for j in range(1, len(w)):
            if w[j][1] - w[j - 1][2] > 4.0 or w[j][2] > nxt + 0.05:
                t0 = w[j - 1][2] + 0.08; n = len(w) - j; t1 = min(nxt - 0.1, t0 + 0.38 * n)
                step = max(0.08, (t1 - t0) / n)
                for q in range(n):
                    w[j + q] = [w[j + q][0], round(t0 + q * step, 2), round(t0 + (q + 1) * step - 0.02, 2)]
                ln['end'] = w[-1][2]; fixed.append(ln['text']); break
    return fixed


def build_ass(path, L, W, H, dur, story, sync_ok):
    v = H > W; fs = 92 if v else 80; cx = W // 2; ycur = int(H * (0.745 if v else 0.80)); ynext = ycur + int(fs * 0.35)
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cur,Poppins Black,{fs},&H0040FFB0,&H00FFFFFF,&H00100A05,&H96000000,0,0,0,0,100,100,1,0,1,7,4,2,60,60,0,1
Style: Next,Poppins Black,{int(fs * 0.68)},&H70FFFFFF,&H70FFFFFF,&H70100A05,&HB4000000,0,0,0,0,100,100,1,0,1,5,0,8,60,60,0,1
Style: Chip,Poppins Bold,{46 if v else 36},&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,3,10,0,7,40,40,40,1
Style: Kick,IBM Plex Mono,{34 if v else 28},&H0028BEFF,&H0028BEFF,&H00000000,&H50000000,1,0,0,0,100,100,1,0,3,8,0,7,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []; pend = 0.0; T = [ln for ln in L if ln.get('words') or ln.get('start') is not None]
    nline_level = 0
    for i, s in enumerate(T):
        st = s['start']; nx = T[i + 1]['start'] if i + 1 < len(T) else dur
        end = min(s['end'] + 0.8, nx - 0.05) if nx - s['end'] < 2.5 else s['end'] + 0.8
        end = min(end, nx - 0.02, dur); a = min(st, max(st - 0.35, pend + 0.01)); pend = end
        parts = [f"{{\\an2\\pos({cx},{ycur})\\fad(60,0)"]
        words = s.get('words') or []
        if sync_ok and line_ok(s) and s.get('sync_score', 1) >= 0.45:
            parts[0] += f"\\k{round((words[0][1] - a) * 100)}}}"
            inpar = False
            for j, w in enumerate(words):
                nxt = words[j + 1][1] if j + 1 < len(words) else w[2]
                d = min(nxt, max(w[2], w[1] + 0.12)) - w[1]          # wipe over the word itself...
                gap = nxt - w[1] - d                                  # ...then hold (no 10 s crawl across a gap)
                tok = _esc(w[0])
                if '(' in tok: inpar = True
                parts.append(f"{{\\kf{max(1, round(d * 100))}" + ("\\i1\\c&H0028BEFF&\\2c&H0060D0FF&\\fscx85\\fscy85" if inpar else "") + "}" + tok + " ")
                if gap > 0.25: parts.append(f"{{\\k{round(gap * 100)}}}")
                if ')' in tok: inpar = False; parts.append("{\\r}")
        else:                                      # line-level fallback: one smooth wipe over the sung line
            nline_level += 1
            parts[0] += f"\\k{round((st - a) * 100)}}}"
            parts.append(f"{{\\kf{max(1, round((s['end'] - st) * 100))}}}" + _esc(s['text']))
        ev.append(f"Dialogue: 1,{_ts(a)},{_ts(end)},Cur,,0,0,0,,{''.join(parts).strip()}")
        if i + 1 < len(T) and T[i + 1]['start'] - end < 1.5:
            ev.append(f"Dialogue: 0,{_ts(a)},{_ts(end)},Next,,0,0,0,,{{\\an8\\pos({cx},{ynext})\\fad(80,0)}}{_esc(T[i + 1]['text'])}")
    # story text layer (main + secondary stories), top-left chip
    for c in story:
        y = 40 if v else 24
        ev.append(f"Dialogue: 2,{_ts(c['t0'])},{_ts(c['t1'])},Kick,,0,0,0,,{{\\an7\\pos(40,{y})\\fad(150,150)}}{_esc(c['kicker'].upper())}")
        ev.append(f"Dialogue: 2,{_ts(c['t0'])},{_ts(c['t1'])},Chip,,0,0,0,,{{\\an7\\pos(40,{y + (60 if v else 50)})\\fad(150,150)}}{_esc(c['text'])}")
    open(path, 'w').write(hdr + '\n'.join(ev) + '\n')
    return nline_level


def story_events(P, L, day, dur, end_t):
    m = map_lines(P, L, day); out = []
    for c in P.get('story_text', [])[:5]:
        a, b = m.get(c.get('from_line')), m.get(c.get('to_line'))
        if a is None or b is None or not L[a].get('start') or not L[b].get('end'): continue
        out.append({'t0': max(0.5, L[a]['start'] - 0.3), 't1': min(end_t, L[b]['end'] + 0.6), 'kicker': c.get('kicker', ''), 'text': c.get('text', '')[:80]})
    out.sort(key=lambda c: c['t0'])
    for i in range(len(out) - 1):                  # never two chips at once
        out[i]['t1'] = min(out[i]['t1'], out[i + 1]['t0'] - 0.05)
    return [c for c in out if c['t1'] - c['t0'] > 1.0]


# ---------------------------------------------------------------- checks
TECH_WORDS = ('grok bot poc cve cves dev devs grep oneline sudo kubectl kpatch livepatch ssh cbl cob cobol fortran repo '
              'diff stdout stderr cron nginx localhost api apis gpu gpus cpu llm llms sdk cli tcp dns http https json yaml '
              'oss url urls src lib bin usr etc var tmp tls mx admin npm pip infosec sysadmin devops noc soc init')


def spelling(texts, day):
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return ['pyspellchecker not installed']
    sp = SpellChecker(); srcw = set(norm(G.read(os.path.join(day, 'stories.md')) + ' ' + G.read(os.path.join(day, 'lyrics.txt'))).split())
    allow = set(TECH_WORDS.split())
    bad = set()
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z']+", t):
            lw = w.lower().strip("'")
            if len(lw) < 3 or lw in allow or lw in srcw or lw.replace("'s", '') in srcw or not sp.unknown([lw]): continue
            bad.add(w)
    return sorted(bad)


def fit_check(fitlog, texts, day):
    """21 Oct: kgfx2 logs text that could not be shrunk to fit, and every string on each shot's final frame. A final-frame
    word that is not in the source text but is a strict prefix of a source word is a truncated fragment = failure."""
    srcw = set(norm(' '.join(texts) + ' ' + G.read(os.path.join(day, 'stories.md')) + ' ' + G.read(os.path.join(day, 'lyrics.txt'))).split())
    fails, trunc = [], set()
    recs = []
    if os.path.exists(fitlog):
        for ln in open(fitlog):
            try: recs.append(json.loads(ln))
            except Exception: pass
    for r in recs:
        if r.get('fail'): fails.append(f"{r.get('shot')}: {r.get('text')!r}"[:120])
        elif 'final' in r:
            for w in norm(r['final']).split():
                if len(w) >= 2 and w not in srcw and any(sw.startswith(w) and sw != w for sw in srcw):
                    trunc.add(w)
    return sorted(set(fails)), sorted(trunc)


def all_texts(shots, story, endp):
    out = []
    def walk(o):
        if isinstance(o, str): out.append(o)
        elif isinstance(o, dict): [walk(v) for k, v in o.items() if k not in ('bg', 'color', 'mode', 'kind')]
        elif isinstance(o, (list, tuple)): [walk(v) for v in o if v not in ('cmd', 'out', 'err', 'warn', 'dim')]
    for s in shots:
        if s['src'][0] == 'gfx': walk(s['src'][2])
    walk([c['text'] for c in story] + [c['kicker'] for c in story]); walk({k: v for k, v in endp.items() if k != 'bg'})
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day'); ap.add_argument('--out'); ap.add_argument('--work')
    ap.add_argument('--skip-gen', action='store_true'); ap.add_argument('--replan', action='store_true')
    ap.add_argument('--no-fallback', action='store_true'); ap.add_argument('--no-16x9', action='store_true')
    ap.add_argument('--stills', type=int, default=int(os.environ.get('GV_KARAOKE_STILLS', 14)))
    ap.add_argument('--clips', type=int, default=int(os.environ.get('GV_KARAOKE_CLIPS', 8)))
    ap.add_argument('--time-limit', type=float, default=float(os.environ.get('GV_KARAOKE_LIMIT_MIN', 40)))
    ap.add_argument('--whisper-model', default='medium')
    a, passthru = ap.parse_known_args()
    t_start = time.time(); day = os.path.abspath(a.day)
    out = os.path.abspath(a.out or os.path.join(day, 'video_karaoke.mp4'))
    base_ = os.path.splitext(out)[0]; chat, wide = base_ + '_chat.mp4', base_ + '_16x9.mp4'
    work = os.path.abspath(a.work or os.path.join(day, 'work_' + os.path.splitext(os.path.basename(out))[0].replace('video_', ''))); os.makedirs(work, exist_ok=True)
    gdir = os.path.join(work, 'grok'); os.makedirs(gdir, exist_ok=True)
    deadline = t_start + a.time_limit * 60
    status = {'style': 'karaoke', 'day': day, 'out': out, 'started': time.strftime('%Y-%m-%d %H:%M:%S %Z'), 'warnings': []}
    sp = os.path.join(work, 'status.json')
    import grok_video as GV
    try:
        audio = G.audio_path(day); dur = G.duration(audio)
        for f in ('lyrics.txt', 'stories.md'):
            if not os.path.exists(os.path.join(day, f)): raise RuntimeError(f'missing {f}')
        if not a.skip_gen:
            ok, how, msg = GV.grok_auth_ok()
            if not ok:
                print(f"GROK_VIDEO_STATUS=failed code=7 style=karaoke reason='grok CLI not signed in - run grok login --device-auth'", flush=True)
                sys.exit(7)
        try:
            from real_gen_usage import usage_pct
            status['usage_before'] = usage_pct()
        except Exception as e:
            status['usage_before'] = None
        tres = {}
        def tj():
            try:
                L, rep, vm = align_karaoke(day, work, status)
                tres.update(L=L, rep=rep, vm=vm)
                if len(L) != rep['expected_lines'] or len(rep['suspect_lines']) > 0.3 * max(1, len(L)):
                    raise RuntimeError(f"direct alignment suspect ({len(rep['suspect_lines'])}/{len(L)} lines)")
            except Exception as e:
                G.log(f"karaoke align: {e!r}; trying the old alignment pipeline (lyric_timings)")
                tres['direct_err'] = repr(e)[:200]
                try:
                    path = GV.lyric_timings(day, work, a.whisper_model)
                    L2 = G.load_json(path)
                    stem = os.path.join(work, 'kalign', 'sep', 'htdemucs', os.path.splitext(os.path.basename(G.audio_path(day)))[0], 'vocals.wav')
                    if os.path.exists(stem):
                        act, hop = vocal_activity(stem)
                        for ln in L2: ln['sync_score'] = round(line_score(ln, act, hop), 2)
                        m2 = sum(ln['sync_score'] for ln in L2) / max(1, len(L2))
                    else:
                        m2 = 1.0
                    if 'L' not in tres or m2 > tres['rep']['mean_score']:
                        tres['L'] = L2; tres['rep'] = {'method': 'lyric_timings', 'mean_score': round(m2, 3),
                                                       'suspect_lines': [i for i, ln in enumerate(L2) if ln.get('sync_score', 1) < 0.45]}
                        tres['vm'] = G.load_json(os.path.join(work, 'align', 'vocal_check.json'), {}) or tres.get('vm') or {}
                except Exception as e2:
                    if 'L' not in tres: tres['err'] = repr(e2)
        th = threading.Thread(target=tj, daemon=True); th.start()
        pp = os.path.join(work, 'plan.json')
        P = G.load_json(pp) if os.path.exists(pp) and not a.replan else None
        if not P or P.get('ver') != PLAN_VER:
            t0 = time.time()
            try:
                P = plan_opus(day, work, a.stills, a.clips)
            except Exception as e:
                status['warnings'].append(f'opus planner failed ({str(e)[:120]}); template plan, no Grok scenes')
                P = plan_template(day)
            P['ver'] = PLAN_VER; P['plan_s'] = round(time.time() - t0)
            G.save_json(P, os.path.join(work, 'plan_raw.json'))
            status['warnings'] += fact_lint(P, day)
            G.save_json(P, pp)
        import design as DZ
        DES = DZ.resolve(day, P.get('design')); status['design'] = DES
        G.log(f"karaoke: design {DES}")
        G.log(f"karaoke: plan ready ({P.get('planner')}, {len(P.get('scenes', []))} scenes) at {time.time() - t_start:.0f}s")
        gt = time.time(); generate(P, work, a, t_start + 26 * 60, status); status['gen_s'] = round(time.time() - gt)
        G.log(f"karaoke: media done at {time.time() - t_start:.0f}s")
        th.join(timeout=max(60, deadline - time.time() - 8 * 60))
        if 'L' not in tres: raise RuntimeError('lyric timing failed: ' + tres.get('err', 'timeout'))
        L, sync, vc = tres['L'], tres['rep'], tres.get('vm') or {}
        if vc and GV.stem_is_low(vc) and sync.get('mean_score', 1) < 0.5:
            print("GROK_VIDEO_STATUS=failed code=6 style=karaoke reason='song looks instrumental (vocal stem low)'", flush=True); sys.exit(6)
        sync_ok = len(sync.get('suspect_lines', [])) <= 0.3 * max(1, len(L)) and sum(1 for ln in L if ln.get('words')) >= len(L) * 0.7
        G.log(f"karaoke: timings via {sync.get('method')} mean sync score {sync.get('mean_score')} suspect lines {sync.get('suspect_lines')}")
        if not sync_ok: status['warnings'].append(f'word sync weak {sync} -> line-level karaoke')
        rep = sanitize(L)
        if rep: status['warnings'].append(f"timing sanity: re-spread the tail of {len(rep)} line(s): {rep}")
        shots = timeline(P, L, dur, day, gdir)
        pl_ = {ln['i']: ln for ln in P['lines']}; inv_ = {v: k for k, v in map_lines(P, L, day).items()}
        tab = match_check(shots, L, P, work, gdir, status)
        if tab:
            used = {}
            for s_ in shots:
                if s_['src'][0] == 'gfx': used[s_['src'][1]] = used.get(s_['src'][1], 0) + 1
            bad_n = [r['n'] for r in tab if not r['match']]
            for n_ in bad_n:
                s_ = shots[n_]; li = s_['line']; spec = pl_.get(inv_.get(li), {})
                if s_['src'][0] == 'gfx': used[s_['src'][1]] -= 1
                v = line_card(L[li]['text'], spec.get('fact', ''), used); used[v['g']] = used.get(v['g'], 0) + 1
                s_['v'] = v; s_['src'] = ('gfx', v['g'], dict(v['p'])); s_['redrawn'] = 'match check: ' + next(r['why'] for r in tab if r['n'] == n_)[:120]
            G.log(f"karaoke: match check: {len(tab) - len(bad_n)}/{len(tab)} matched; redrew {len(bad_n)} for their own line")
            if bad_n:
                tab2 = match_check(shots, L, P, work, gdir, status) or tab
            else:
                tab2 = tab
            G.save_json(tab2, os.path.join(work, 'match_table.json'))
            status['match'] = {'first_pass': f"{len(tab) - len(bad_n)}/{len(tab)}", 'final': f"{sum(r['match'] for r in tab2)}/{len(tab2)}"}
            with open(os.path.join(work, 'match_table.md'), 'w') as f_:
                f_.write('| shot | line | shot shown | match | note |\n|---|---|---|---|---|\n')
                for r in tab2:
                    f_.write(f"| {r['n']} | {r['line']} | {r['shot'][:90].replace('|', '/')} | {'yes' if r['match'] else 'NO'} | {r['why'][:80].replace('|', '/')} |\n")
        end_t = shots[-1]['t0']
        story = story_events(P, L, day, dur, end_t)
        stills = sorted(f for f in os.listdir(gdir) if f.endswith('.png'))
        endp = {'title': G.read(os.path.join(day, 'title.txt')).strip(), 'credit': (P.get('credit') or '')[:80],
                'sub': 'Grok Bot · ' + time.strftime('%-d %b %Y', time.strptime(os.path.basename(day)[:10], '%Y-%m-%d')) if re.match(r'\d{4}-\d\d-\d\d', os.path.basename(day)) else '',
                'bg': os.path.join(gdir, stills[-1]) if stills else None}
        if P.get('scenes') and stills:                # prefer the outro scene as the end-card background
            for v in P.get('outro', [])[::-1]:
                if v.get('kind') == 'scene' and os.path.exists(os.path.join(gdir, f"{v['id']}.png")):
                    endp['bg'] = os.path.join(gdir, f"{v['id']}.png"); break
        G.save_json({'shots': [{'t0': round(s['t0'], 2), 't1': round(s['t1'], 2), 'src': [s['src'][0], s['src'][1]], 'line': s.get('line'), 'redrawn': s.get('redrawn')} for s in shots],
                     'story': story}, os.path.join(work, 'timeline.json'))
        sizes = [(1080, 1920)] + ([] if a.no_16x9 else [(1920, 1080)])
        jobs = []
        for W, H in sizes:
            sd = os.path.join(work, f'seg_{W}x{H}'); os.makedirs(sd, exist_ok=True)
            jobs += [(s, W, H, os.path.join(sd, f'{i:03d}.mp4'), endp, DES, i) for i, s in enumerate(shots)]
        rt = time.time()
        fitlog = os.path.join(work, 'fit_log.jsonl'); open(fitlog, 'w').close(); os.environ['KGFX_FITLOG'] = fitlog  # 21 Oct
        with Pool(min(8, os.cpu_count() or 4)) as pool:
            segs = pool.map(render_seg, jobs, chunksize=1)
        results = {}
        texts = all_texts(shots, story, endp) + [ln['text'] for ln in L]
        for W, H in sizes:
            tag = f'{W}x{H}'; sd = os.path.join(work, f'seg_{tag}')
            lst = os.path.join(sd, 'list.txt')
            open(lst, 'w').write(''.join(f"file '{s}'\n" for s in segs if f'/seg_{tag}/' in s))
            bg = os.path.join(work, f'bg_{tag}.mp4')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', bg], check=True)
            assf = os.path.join(work, f'lyrics_{tag}.ass'); bandf = os.path.join(work, f'band_{tag}.png')
            import klyrics
            ll = klyrics.build(assf, L, W, H, dur, story, sync_ok, DES, DZ.theme(DES), line_ok); band_png(W, H, bandf, DES)
            status['line_level_lines'] = ll
            dst = out if H > W else wide
            tmp = dst + '.part.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', bg, '-i', bandf, '-i', audio, '-filter_complex',
                            f"[0:v][1:v]overlay=0:0,ass='{assf}',scale=in_range=auto:out_range=tv,format=yuv420p[v]",  # 21 Oct: jpeg-range sources gave yuvj420p
                            '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
                            '-profile:v', 'high', '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-t', f'{dur:.3f}', '-movflags', '+faststart', tmp], check=True)
            os.replace(tmp, dst); results[tag] = dst
        # chat copy < 25 MB (21 Oct): two-pass at a bitrate derived from the duration, 22 MB target, retry lower if over
        for tgt in (22, 19, 16):
            kbps = max(300, int((tgt * 8 * 1024) / dur) - 128)
            pl = os.path.join(work, 'chat2pass')
            common = ['-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'high', '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.3)}k',
                      '-bufsize', f'{kbps * 2}k', '-vf', 'scale=in_range=auto:out_range=tv,format=yuv420p', '-pix_fmt', 'yuv420p',
                      '-color_range', 'tv', '-passlogfile', pl]
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out] + common + ['-pass', '1', '-an', '-f', 'mp4', os.devnull], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out] + common + ['-pass', '2', '-c:a', 'aac', '-b:a', '128k',
                            '-movflags', '+faststart', chat + '.part.mp4'], check=True)
            if os.path.getsize(chat + '.part.mp4') < 25 * 1048576: break
        os.replace(chat + '.part.mp4', chat)
        status['render_s'] = round(time.time() - rt)
        vr = GV.verify(out, audio, L, {}, os.path.join(work, 'verify_frames'))
        cs = os.path.join(work, 'contact_sheet.jpg')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-vf', f"fps=16/{dur:.1f},scale=270:-2,tile=8x2", '-frames:v', '1', cs])
        bad = spelling(texts, day)
        try:
            import margin_check as MC
            P['_title'] = endp['title']
            mc = MC.run(work, P, [x['text'] for x in (G.story_list(day) or [])] + [c['text'] for c in story], [ln['text'] for ln in L], DZ.theme(DES), dur)
            status['margin_ok'] = mc['ok']
            status['margin_fail'] = [f"{r['g']}/{r['case']}/{r['size']}" for r in mc['gfx'] if not r['ok']] + [f"lyrics {k}: {a['n_fail']} frames" for k, a in mc['ass'].items() if a['n_fail']]
            if not mc['ok']: status['warnings'].append(f"margin check failed: {status['margin_fail']}")
        except Exception as e:
            status['warnings'].append(f'margin check error: {e!r}')
        # 21 Oct 2026 (the owner: no on-screen text is ever cut off): fit failures and truncated words fail the build
        fit_fail, trunc = fit_check(fitlog, texts, day)
        status.update(fit_fail=fit_fail, truncated_words=trunc, fit_ok=not fit_fail and not trunc)
        if fit_fail or trunc:
            status['warnings'].append(f"text fit check failed: {fit_fail[:5]} truncated {trunc}")
            vr['ok'] = False; vr['checks']['text_fits'] = False
        else: vr['checks']['text_fits'] = True
        status.update(ok=vr['ok'], verify=vr['checks'], sync=sync, sync_ok=sync_ok, spelling_unknown=bad, contact_sheet=cs,
                      shots=len(shots), avg_shot=round(end_t / max(1, len(shots) - 1), 2),
                      scenes=sum(1 for s in shots if s['src'][0] in ('clip', 'still')), clips_used=sum(1 for s in shots if s['src'][0] == 'clip'),
                      planner=P.get('planner'), wide=results.get('1920x1080'), chat=chat,
                      chat_mb=round(os.path.getsize(chat) / 1048576, 1), elapsed_s=round(time.time() - t_start))
        try:
            from real_gen_usage import usage_pct
            status['usage_after'] = usage_pct()
        except Exception:
            pass
        if bad: status['warnings'].append(f"spelling check: unknown words {bad}")
        tl = {}
        for s_ in shots:
            if s_['src'][0] == 'gfx': tl[s_['src'][1]] = tl.get(s_['src'][1], 0) + 1
        status['templates'] = tl
        try: DZ.record(day, DES, tl)
        except Exception as e: status['warnings'].append(f'design history not saved: {e!r}')
        G.save_json(status, sp)
        if not vr['ok']: raise RuntimeError(f"verification failed {vr['checks']}")
        print(f"GROK_VIDEO_STATUS=ok code=0 style=karaoke planner={P.get('planner')} out={out} chat={chat} wide={status['wide']} "
              f"elapsed={status['elapsed_s']}s shots={len(shots)} avg_shot={status['avg_shot']}s scenes={status['scenes']} "
              f"clips={status['clips_used']} sync_ok={int(sync_ok)} line_level={status.get('line_level_lines')}"
              + (f" warnings={len(status['warnings'])}: {' | '.join(status['warnings'])[:600]}" if status['warnings'] else ''), flush=True)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        why = f'{type(e).__name__}: {e}'
        G.log('karaoke error:\n' + traceback.format_exc()[-2000:])
        status.update(ok=False, error=why, elapsed_s=round(time.time() - t_start)); G.save_json(status, sp)
        for f in (out, chat, wide):
            if os.path.exists(f) and os.path.getmtime(f) >= t_start:
                os.replace(f, os.path.splitext(f)[0] + '.failed.mp4')
        if a.no_fallback or a.skip_gen:
            print(f"GROK_VIDEO_STATUS=failed code=3 style=karaoke reason={why[:300]!r}", flush=True); sys.exit(3)
        G.log(f"karaoke FAILED ({why[:200]}); falling back to grok_video.py (Claudia/slopcore chain)")
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, 'grok_video.py'), day] + passthru)


if __name__ == '__main__':
    main()
