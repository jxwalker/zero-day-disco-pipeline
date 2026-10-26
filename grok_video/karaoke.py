"""karaoke mode: the daily video in the karaoke v3 format (default). See README.md "karaoke".
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
SCREEN_RULE = (" NO LAPTOPS anywhere in the frame. Screens only as wall-mounted displays, "
               "rack-mounted monitors or holographic HUDs floating in the air, seen straight-on; no handheld tablet or phone "
               "screen turned toward the camera; never an image or glow on the back of any device.")
NO_LAPTOP = [(re.compile(r'\b((a|an|the|his|her|their|open|gaming|silver) )*laptops?\b', re.I), 'a wall-mounted display'),
             (re.compile(r'\b((a|an|the|his|her|their) )*(tablet|ipad|clipboard tablet)s?\b', re.I), 'a floating holographic HUD panel'),
             (re.compile(r'\b((a|an|the|his|her|their) )*(smart)?phones?\b', re.I), 'a small holographic readout')]


def no_laptops(prompt):
    """swap laptops/tablets/phones for wall displays and holographic HUDs (Grok keeps putting screens on lids)."""
    for rx, rep in NO_LAPTOP: prompt = rx.sub(rep, prompt)
    return prompt


def direction(day):
    """optional <day>/direction.txt (or GV_DIRECTION=path). Free text for the planner, plus optional
    'LEAD: ...' (one consistent lead character, made from a reference still) and 'PALETTE: <name>' lines."""
    pth = os.environ.get('GV_DIRECTION') or os.path.join(day, 'direction.txt')
    txt = G.read(pth).strip() if os.path.exists(pth) else ''
    lead = re.search(r'^LEAD:\s*(.+?)(?=^\w+:|\Z)', txt, re.M | re.S)
    pal = re.search(r'^PALETTE:\s*([\w-]+)', txt, re.M)
    return {'text': txt, 'lead': ' '.join(lead.group(1).split()) if lead else '', 'palette': pal.group(1) if pal else ''}
LOOK = (" Zero Day Disco house style 'Acid Deadpan': live-action music-video frame on 35mm film, fine grain, "
        "flat saturated colour blocking in Klein blue, acid green and safety orange (one bold accent, never rainbow), "
        "symmetrical centred composition, 24mm wide lens, hard clean top light, Wes-Anderson-meets-Kubrick framing, "
        "recurring props: orange-and-black warning tape, an orange rotary phone; clean negative space in the lower third, vertical 9:16. "
        "Cast are young adults aged 21-28 with invented faces, quirky distinctive styling, deadpan / unimpressed / dry expressive "
        "attitude (side-eye, raised brow, bored stare, sudden laugh), never generic smiling at camera; no tongue out, no pulled or "
        "silly faces, no gurning, no pouting or duck faces. No robots, no text, no logos, no readable writing, no famous people." + SCREEN_RULE)
LOOK_CHORUS = (" Zero Day Disco chorus-drop look 'Glitch Pop': clean modern digital cinema camera at night, crisp sharp image, harsh on-camera flash, magenta and cyan "
        "neon rim light, motion smear; no VHS, no tape, no camcorder look, no scan lines, no CRT, no horizontal lines or bars, no video noise; low fisheye or dutch angle, whip-pan energy, neon magenta/cyan haze; "
        "the same cast, wild and cheeky (laughing, crowd-surfing, winking), vertical 9:16. Cast young adults 21-28, invented faces; "
        "no tongue out, no pulled faces. No robots, no text, no logos, no readable writing, no famous people." + SCREEN_RULE)
if os.environ.get('GV_HOUSESTYLE', '1') == '0':
    LOOK = (" Live-action music-video frame shot on 35mm Kodak Vision3 500T film, fine visible grain, real lens depth of field, "
            "off-centre composition with clean negative space in the lower third, vertical 9:16. Cast are young adults aged 21-28; "
            "no tongue out, no pulled faces. No robots, no text, no logos, no readable writing, no famous people." + SCREEN_RULE)
    LOOK_CHORUS = LOOK


def norm(s): return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def lyric_lines(day):
    out = []
    for l in G.read(os.path.join(day, 'lyrics.txt')).splitlines():
        l = l.strip()
        if l and not (l.startswith('[') and l.endswith(']')):
            out.append(l)
    return out


# ---------------------------------------------------------------- alignment (demucs + stable-ts)
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
    """demucs vocals -> stable-ts forced alignment of lyrics.txt (~1-5 min on the box CPU) ->
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
    DIR = direction(day)
    if DIR['text']:
        txt += ("\n\nTODAY'S DIRECTION OVERRIDE (from the owner; follows and overrides the defaults above):\n" + DIR['text'] +
                ("\n- Start the prompt of EVERY scene that shows the lead with the token [LEAD] and describe only the setting, her "
                 "action, pose, expression and lighting (her look comes from a reference image). Most scenes show her." if DIR['lead'] else '')
                + (f"\n- Use palette '{DIR['palette']}'." if DIR['palette'] else ''))
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
                pool.append({'kind': 'gfx', 'g': 'bignum', 'p': {'top': f"STORY {s['idx']}", 'value': n, 'sub': wcut(s['text'], 60)}})
    P = {'planner': 'template', 'scenes': [], 'lines': [{'i': i, 'v': [pool[i % len(pool)]]} for i in range(len(lines))],
         'intro': pool[:2], 'breaks': pool[2:6] or pool, 'outro': pool[:1],
         'story_text': [{'from_line': 0, 'to_line': len(lines) - 1, 'kicker': 'MAIN STORY', 'text': wcut(stories[0]['text'], 70)}] if stories else [],
         'credit': wcut(stories[0]['text'], 70) if stories else ''}
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
    """Grok sometimes returns a 9:16 picture that is two copies of the same frame stacked (seen)."""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(png).convert('L').resize((90, 160)), dtype=float)
        return float(np.corrcoef(a[:80].ravel(), a[80:].ravel())[0, 1]) > 0.6
    except Exception:
        return False


SCREEN_SCHEMA = {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {
    "type": "object", "required": ["id", "device_present", "laptop_present", "screen_on_outer_lid", "screen_not_facing_camera",
                                   "user_faces_camera_behind_device", "display_visible_to_camera", "other_problem", "issue"],
    "properties": {"id": {"type": "string"}, "device_present": {"type": "boolean"}, "laptop_present": {"type": "boolean"},
                   "screen_on_outer_lid": {"type": "boolean"}, "screen_not_facing_camera": {"type": "boolean"},
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
        "- laptop_present: ANY laptop or laptop-like folding device anywhere in the frame, even in the background (true = reject).\n"
        "- screen_on_outer_lid: any image, UI or glow on the OUTSIDE/back of a lid, tablet back or monitor back.\n"
        "- screen_not_facing_camera: any handheld tablet/phone/laptop whose lit screen we can see while the person holding "
        "or using it faces the camera (physically the screen would face them, not us), or any screen facing away.\n"
        "- user_faces_camera_behind_device: the person using that device faces the camera with the device between them "
        "and the camera (we see their face over/behind the device).\n"
        "- display_visible_to_camera: we can see that device's lit screen content (UI, code, image).\n"
        "  If BOTH of the last two are true the screen is physically on the wrong side: that is the main failure.\n"
        "- other_problem: anything in the list below.\n"
        "Reject (ok=false) if ANY of these: a laptop shows an image/screen content on the BACK of its lid; a laptop/monitor/"
        "phone that the person is using has its screen facing away from the camera while the shot is about what is on it "
        "(we only see the back of the lid/monitor, which looks like a screen); a screen glows on the wrong side; a device "
        "is physically impossible; the frame is two stacked copies of the same picture; a robot or android; garbled "
        "readable text that is prominent; ANY print, patch, logo or tool/prop-shaped graphic on clothing; a rigid prop that bends, melts or changes size; badly malformed hands or faces; anyone sticking their tongue out, pulling a silly/bratty face, gurning, pouting or making a duck face; any on-screen text (watch, sign, bubble) that is upside down, mirrored or garbled.; any glasses or eyewear on the lead, or eyewear rendering artefacts (warped, melted, doubled, floating or half-missing frames or lenses, frames fused into skin or hair). A laptop seen from behind is ONLY acceptable if "
        "its lid back is plain (no picture) and we are clearly looking at the person's face, not the screen; when unsure, "
        "reject.: ANY laptop at all is a reject. Wall displays, rack monitors and holographic HUDs are fine.\nGive a short issue for each problem image, '' otherwise. id = the file name without .png (for _f.png frames use the name without _f.png).\n\nFILES:\n"
        + '\n'.join(names))
    try:
        res, meta = SO.run_claude(pf, gdir, SCREEN_SCHEMA, 420, tools='Read', effort='medium')
    except Exception as e:
        G.log(f"karaoke: screen check unavailable ({str(e)[:150]}); continuing without it")
        status.setdefault('warnings', []).append('screen check unavailable'); return set()
    rs = {r['id'].replace('_f.png', '').replace('.png', '').replace('_f', ''): r for r in (res or {}).get('results', [])}
    G.save_json(rs, os.path.join(gdir, f'screen_check_{tag}.json'))
    for r in rs.values():
        r['ok'] = not ((r.get('user_faces_camera_behind_device') and r.get('display_visible_to_camera')) or r.get('other_problem')
                       or r.get('laptop_present') or r.get('screen_on_outer_lid') or r.get('screen_not_facing_camera'))  # stricter
    bad = {k for k, r in rs.items() if not r.get('ok')}
    G.log(f"karaoke: screen check {tag}: {len(rs)} checked, rejected {sorted(bad)}")
    status.setdefault('screen_checks', {})[tag] = {k: r.get('issue') for k, r in rs.items() if not r.get('ok')}
    return bad


SPARK_SSH = ['ssh', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', '-i', os.path.expanduser(os.environ.get('SPARK_SSH_KEY', '~/.ssh/id_ed25519')), os.environ.get('SPARK_SSH', 'user@spark-host')]

def local_clips(cj, mv, status, gdir, deadline):
    """tiers per clip.
    premium = Runway hero_jobs (left to the Grok batch here; the agent replaces them via the Runway runbook);
    hero = the GV_WAN_HEROES (2) most-used other scenes -> Wan 2.2 on the Spark;
    b-roll = everything else -> LTX draft + strict QC -> one LTX re-roll -> Wan 2.2 -> Grok/Runway.
    Starts ComfyUI on the Spark and always stops it. Returns the jobs that still need Grok."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'local_gen'))
    import clip_qc as Q
    premium = set(status.get('hero_jobs') or [])
    order = [s['id'] for s in mv if s['id'] not in premium]
    heroes = set(order[:int(os.environ.get('GV_WAN_HEROES', 2))])
    log = os.path.join(gdir, 'local_qc_log.jsonl'); left = []
    if subprocess.run(SPARK_SSH + ['/opt/comfyui/comfy_spark.sh start'], capture_output=True, timeout=120).returncode != 0:
        status.setdefault('warnings', []).append('Spark ComfyUI unreachable; all clips via Grok'); return cj
    try:
        time.sleep(30)
        for j in cj:
            sid = j['id'][2:]
            if sid in premium or time.time() > deadline - 20 * 60:
                left.append(j); continue
            if sid in heroes:      # hero: Wan only, then QC; failure -> Grok
                r = Q.broll(j['image'], j['prompt'], j['out'], log=log, wan=True, ltx=False)
            else:
                r = Q.broll(j['image'], j['prompt'], j['out'], log=log)
            status.setdefault('local_clips', {})[sid] = {'tier': 'hero' if sid in heroes else 'broll', 'backend': r['backend'], 'ok': r['ok'],
                                                         'fails': [h.get('reasons') for h in r['history'] if h.get('ok') is False]}
            if not r['ok']: left.append(j)
    finally:
        subprocess.run(SPARK_SSH + ['/opt/comfyui/comfy_spark.sh stop'], capture_output=True, timeout=120)
    G.log(f"karaoke: local clips {status.get('local_clips')}; {len(left)} left for Grok")
    return left


def generate(P, work, a, deadline, status):
    import real_gen as R
    gdir = os.path.join(work, 'grok'); os.makedirs(gdir, exist_ok=True)
    scenes = P.get('scenes', [])[:a.stills]
    if not scenes or a.skip_gen:
        return
    used = {}
    for v in [v for ln in P['lines'] for v in ln['v']] + P['intro'] + P['breaks'] + P['outro']:
        if v.get('kind') == 'scene': used[v.get('id')] = used.get(v.get('id'), 0) + 1
    DIR = direction(os.path.dirname(os.path.abspath(work)) if not getattr(a, 'day', None) else a.day)
    LN = G.lead_noun(os.path.dirname(os.path.abspath(work)) if not getattr(a, 'day', None) else a.day)   # male lead
    ref = f"{gdir}/lead_ref.png"
    if DIR['lead'] and not os.path.exists(ref):     # one consistent lead from a reference still
        rb = R.Batcher(gdir, {'gen': 2}, batch_size=1, max_parallel=1, deadline=deadline - 12 * 60, tag='leadref')
        rb.run([{'id': 'lead_ref', 'kind': 'gen', 'aspect': '9:16', 'out': ref, 'prompt':
                 "Full-body character reference portrait, plain dark studio background, even soft light, facing camera: "
                 + DIR['lead'] + f" Clearly an adult {LN}, no glasses. An original person, not any real person or celebrity. No text, no logos."}])
    lead_ok = DIR['lead'] and os.path.exists(ref)
    if not any('[PIP]' in s['prompt'] for s in scenes) and len(scenes) > 4:   # Pip cameo is mandatory
        k = next((i for i, s in enumerate(scenes) if '[CHORUS]' in s['prompt']), len(scenes) // 2)
        scenes[k] = dict(scenes[k], prompt='[PIP] ' + scenes[k]['prompt'] + ' Our small mascot toy is in the background, reacting with a quick hop.')
        G.log(f"karaoke: no [PIP] cameo planned; added one to {scenes[k]['id']}")
    # plain solid wardrobe, no prop-pocketing
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'local_gen'))
    import strict_qc as SQ
    if DIR['lead']: DIR['lead'] = SQ.strip_graphics(DIR['lead']) + SQ.PLAIN_RULE
    _w = re.search(r'Wardrobe:\s*(.+?)(?:\.\s*Colour:|\n|$)', DIR['text'])
    os.environ['GV_WARDROBE'] = SQ.plain_wardrobe(_w.group(1) if _w else DIR['lead'])   # spec the QC checks against
    keep = []
    for s in scenes:
        s['prompt'] = SQ.strip_graphics(s['prompt']); s['motion'] = SQ.strip_graphics(s.get('motion') or '')
        if SQ.POCKET_RE.search(s['prompt'] + ' ' + s['motion']):     # prop-in-pocket / clip-on / holster -> graphic card
            status.setdefault('qc_swapped_to_card', []).append(s['id']); G.log(f"karaoke: {s['id']} has a prop-pocket action; swapped for a graphic card")
            continue
        keep.append(s)
    scenes[:] = keep
    jobs = []
    for s in scenes:
        pr = no_laptops(s['prompt'].strip())
        if '[PIP]' in pr:     # Pip cameo: edit from the locked Pip reference, house look, mascot allowed
            lk = (LOOK_CHORUS if '[CHORUS]' in pr else LOOK).replace('No robots, ', '')
            pr = re.sub(r'\[(PIP|CHORUS|LEAD)\]', '', pr).strip()
            jobs.append({'id': s['id'], 'kind': 'edit', 'images': [G.PIP_REF], 'out': f"{gdir}/{s['id']}.png", 'prompt':
                         "Keep this exact mascot character from the reference image exactly on-model, as a small physical vinyl toy "
                         "in a real photographed scene, vertical 9:16, the toy small in frame: " + pr + lk})
            continue
        is_lead = bool(re.search(r'\[LEAD\]', pr)); pr = pr.replace('[LEAD]', '').strip()
        lk = LOOK_CHORUS if '[CHORUS]' in pr else LOOK; pr = pr.replace('[CHORUS]', '').strip()   # house style
        if is_lead and lead_ok:
            jobs.append({'id': s['id'], 'kind': 'edit', 'images': [ref], 'out': f"{gdir}/{s['id']}.png", 'prompt':
                         f"Keep the exact same {LN} from the reference image: same face, hair, body and outfit. New scene, vertical 9:16: "
                         + pr + lk})
        else:
            jobs.append({'id': s['id'], 'kind': 'gen', 'prompt': ((DIR['lead'] + ' ') if is_lead else '') + pr + lk, 'aspect': '9:16', 'out': f"{gdir}/{s['id']}.png"})
    b = R.Batcher(gdir, {'gen': len(jobs) + 3, 'edit': len(jobs) + 3}, batch_size=5, max_parallel=3, deadline=deadline - 9 * 60, tag='stills')
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
                rj.append(dict(j, prompt=("STRICT: no laptop, no tablet, no phone anywhere. Any screen is a wall-mounted display or a "
                                          "holographic HUD seen straight-on. " + j['prompt'].replace(DEVICE_PREFIX, ''))))
        b4 = R.Batcher(gdir, {'gen': len(rj), 'edit': len(rj)}, batch_size=5, max_parallel=3, deadline=deadline - 8 * 60, tag='screenfix')
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
    try:                                           # vision check each still vs its sung line
        import storyboard as SB
        SB.line_check(P, scenes, jobs, gdir, lyric_lines(getattr(a, 'day', None) or os.path.dirname(os.path.abspath(work))), status, LOOK, deadline)
    except Exception as e:
        status.setdefault('warnings', []).append(f'line check failed ({str(e)[:120]})')
    status['stills_made'] = sum(1 for j in jobs if os.path.exists(j['out']))
    if os.environ.get('GV_HERO', '1') != '0':     # Runway hero-shot jobs (agent runs them via MCP; Grok clip is the fallback)
        try:
            import storyboard as SB
            status['hero_jobs'] = [j['id'] for j in SB.hero_plan(P, getattr(a, 'day', None) or os.path.dirname(os.path.abspath(work)), gdir)]
            if status['hero_jobs'] and os.environ.get('GV_SHEETS', '1') != '0':   # director's shot sheet, score >= 8 before credits
                status['hero_sheets'] = {j['id']: j.get('spec_score') for j in SB.hero_sheets(P, gdir)}
        except Exception as e:
            status.setdefault('warnings', []).append(f'hero plan failed ({str(e)[:120]})')
    for s in scenes:                               # every scene is animated
        if not (s.get('motion') or '').strip():
            s['motion'] = "Energetic natural movement of the person with a smooth handheld camera push-in."
    mv = sorted([s for s in scenes if s.get('motion') and os.path.exists(f"{gdir}/{s['id']}.png") and not dup_halves(f"{gdir}/{s['id']}.png")],
                key=lambda s: -used.get(s['id'], 0))[:a.clips]
    cj = [{'id': 'v_' + s['id'], 'kind': 'i2v', 'image': f"{gdir}/{s['id']}.png", 'duration': 6,
           'prompt': no_laptops(s['motion'].replace('[LEAD]', '')) + " Realistic natural motion, cinematic, no text, no laptops, keep the same people and outfits.", 'out': f"{gdir}/{s['id']}.mp4"} for s in mv]
    if cj and os.environ.get('GV_LOCAL', '1') != '0' and time.time() < deadline - 20 * 60:
        cj = local_clips(cj, mv, status, gdir, deadline)   # LTX b-roll / Wan hero on the Spark; leftovers go to Grok
    if cj and time.time() < deadline - 6 * 60:
        b2 = R.Batcher(gdir, {'i2v': len(cj) + 2}, batch_size=3, max_parallel=3, timeout=900, deadline=deadline, tag='clips')
        b2.run(cj)
        # strict dense-frame QC (0.25 s contact sheets, prop rigidity, wardrobe, hand-prop, 2 reviewers on
        # hero/prop shots, fail closed) on EVERY Grok clip; then the old late-frame screen check as well
        from concurrent.futures import ThreadPoolExecutor
        wd = os.environ.get('GV_WARDROBE', '')
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'local_gen'))
        import strict_qc as SQ
        todo = [j for j in cj if os.path.exists(j['out'])]
        with ThreadPoolExecutor(int(os.environ.get('QC_PAR', 4))) as ex:
            qres = list(ex.map(lambda j: (j, SQ.qc_clip(j['out'], j['prompt'], wd, j.get('image'), 'hero')), todo))
        for j, r in qres:
            status.setdefault('strict_qc', {})[j['id']] = {'ok': r['ok'], 'reasons': r['reasons'][:8], 'warnings': r.get('warnings', [])[:8]}
            if not r['ok']:
                os.replace(j['out'], j['out'] + '.qcfail.mp4'); status.setdefault('clip_rejected', []).append(j['out'])
                G.log(f"karaoke: strict QC rejected {j['id']}: {'; '.join(r['reasons'])[:300]}")
            elif r.get('warnings'): G.log(f"karaoke: strict QC WARN (not blocking) {j['id']}: {'; '.join(r['warnings'])[:300]}")
        fj = []
        for j in cj:
            if os.path.exists(j['out']):
                fp = j['out'][:-4] + '_f.png'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-sseof', '-1.2', '-i', j['out'], '-frames:v', '1', fp])
                if os.path.exists(fp) and os.path.exists(j['out']): fj.append({'id': j['id'], 'out': fp, 'clip': j['out']})
        badc = screen_check(gdir, fj, status, 'clips') if fj else set()
        for j in fj:
            if os.path.basename(j['out']).replace('_f.png', '') in badc:
                os.replace(j['clip'], j['clip'] + '.screen.mp4'); status.setdefault('clip_rejected', []).append(j['clip'])


# ---------------------------------------------------------------- timeline
def map_lines(P, L, day):
    """plan line index (lyrics.txt order) -> timings entry (sequential text match)."""
    lines = lyric_lines(day); out = {}; j = 0
    for i, t in enumerate(lines):
        for k in range(j, min(len(L), j + 4)):
            if norm(L[k]['text']) == norm(t) or (norm(t)[:20] and norm(L[k]['text']).startswith(norm(t)[:20])):
                out[i] = k; j = k + 1; break
    return out


def wcut(s, n):
    """shorten on a word boundary (never leave a cut-off word like 'Vir' on screen)."""
    s = str(s or '').strip()
    if len(s) <= n: return s
    return (s[:n].rsplit(' ', 1)[0] if ' ' in s[:n] else s[:n]).rstrip(' ,;:-')


def line_card(text, fact, used, handle=''):
    """A code-rendered graphic that illustrates THIS line (its words + the story fact behind it); used when the planned
    visual is missing/rejected/over the template cap. Picks the first template variant still under the cap."""
    key = max(re.findall(r"[A-Za-z0-9'-]+", text) or ['FIX'], key=len).upper()[:14]
    opts = [('headline', {'kicker': key, 'text': text, 'sub': wcut(fact, 80)}),
            ('quote', {'text': text, 'by': ('@' + handle) if handle else wcut(fact, 60)}),
            ('browser', {'url': 'news', 'site': 'TODAY', 'headline': text, 'lede': wcut(fact or text, 120), 'highlight': wcut(fact or text, 30)})]
    # no phone 'screen' fallback
    for g, pp in opts:
        if used.get(g, 0) < MAX_PER_TEMPLATE:
            return {'kind': 'gfx', 'g': g, 'p': pp}
    return {'kind': 'gfx', 'g': 'headline', 'p': opts[0][1]}


def timeline(P, L, dur, day, gdir, bad_scenes=()):
    """LINE-LOCKED: the shot(s) under each sung line are that
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
            if used.get(g, 0) >= (MAX_PER_TEMPLATE * 3 if g == 'terminal' else MAX_PER_TEMPLATE):   # story terminals wanted
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
            if os.path.exists(clip) and os.path.getsize(clip) > 10000:
                s['src'] = ('clip', clip, [0.0, 2.6, 1.2][k % 3])
            else:                                  # NO still images; a scene without a clip becomes its line's graphic
                li = s['line']; spec = pl.get(inv.get(li), {}) if li is not None else {}
                v = line_card(L[li]['text'] if li is not None else title, spec.get('fact', ''), used)
                used[v['g']] = used.get(v['g'], 0) + 1
                s['v'] = v; s['redrawn'] = 'scene has no clip (no stills rule)'; s['src'] = ('gfx', v['g'], dict(v.get('p') or {}))
        else:
            s['src'] = ('gfx', v.get('g'), dict(v.get('p') or {}))
    # stamp/slam effects at most STAMP_MAX per video (stamp template + terminal stamps)
    ns = 0
    for s in shots:
        if s['src'][0] != 'gfx': continue
        g, p_ = s['src'][1], s['src'][2]
        if g == 'stamp' or (g == 'terminal' and p_.get('stamp')):
            ns += 1
            if ns > STAMP_MAX:
                if g == 'terminal': p_.pop('stamp', None)
                else:
                    li = s['line']; spec = pl.get(inv.get(li), {}) if li is not None else {}
                    v = line_card(L[li]['text'] if li is not None else title, spec.get('fact', ''), used)
                    s['v'] = v; s['src'] = ('gfx', v['g'], dict(v['p'])); s['redrawn'] = 'stamp cap'
    return shots


# ---------------------------------------------------------------- pacing
# "cuts need to be quick throughout ... roughly 1-2 s per shot, landing on the beat; about 0.5-1 s in the choruses and
# post-chorus chants; never hold longer than about 2.5 s, even in the breakdown; split long clips into beat-synced sub-cuts"
STAMP_MAX = 2
PACE_BEATS = {'fast': 2, 'mid': 3, 'calm': 4}     # beats per sub-cut (126 BPM: 0.95 / 1.43 / 1.9 s)
PACE_MAX_S = float(os.environ.get('GV_KARAOKE_MAX_HOLD', 2.5))


def beat_grid(audio, dur):
    """Tempo + phase from an onset envelope (numpy only): returns beat times across the song."""
    import numpy as np
    sr = 11025; hop = 128
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', audio, '-ac', '1', '-ar', str(sr), '-f', 's16le', '-'], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // hop; fr = x[:n * hop].reshape(n, hop)
    win = 1024; spec = []
    for i in range(0, len(x) - win, hop): spec.append(np.abs(np.fft.rfft(x[i:i + win] * np.hanning(win)))[:200])
    S = np.log1p(10 * np.array(spec)); fl = np.maximum(0, np.diff(S, axis=0)).sum(1)
    fl = (fl - fl.mean()) / (fl.std() + 1e-9); fps = sr / hop
    best = (0, 120.0)
    for bpm in np.arange(90, 181, 0.25):
        per = 60 * fps / bpm; lag = per
        ac = 0
        for m in (1, 2, 4):
            L_ = int(round(lag * m)); ac += (fl[:-L_] * fl[L_:]).mean() / m
        if ac > best[0]: best = (ac, bpm)
    bpm = best[1]
    while bpm < 100: bpm *= 2
    while bpm > 180: bpm /= 2
    per = 60 / bpm; idx = np.arange(len(fl)) / fps
    ph_best = (-1e9, 0)
    for ph in np.arange(0, per, 0.005):
        k = np.round((np.arange(ph, dur, per)) * fps).astype(int); k = k[k < len(fl)]
        sc = fl[k].sum()
        if sc > ph_best[0]: ph_best = (sc, ph)
    return float(bpm), [float(t) for t in np.arange(ph_best[1], dur, per)]


def section_is_chorus(t, L, day):
    """True inside a chorus/hook/refrain section."""
    secs = lyric_sections(day); timed = [i for i, ln in enumerate(L) if ln.get('start') is not None]
    if not timed or t < L[timed[0]]['start']: return False
    cur = None
    for i in timed:
        if L[i]['start'] - 0.1 <= t: cur = i
    if cur is None or cur >= len(secs): return False
    name = norm(secs[cur][1]) + ' ' + secs[cur][2]
    return any(k in name for k in ('chorus', 'hook', 'refrain')) and 'pre' not in name


def energy_at(t, L, day):
    """fast (chorus/chant/hook/intro chant/final lift), mid (verse/pre), calm (breakdown/bridge/stripped) for time t."""
    secs = lyric_sections(day); timed = [i for i, ln in enumerate(L) if ln.get('start') is not None]
    if not timed or t < L[timed[0]]['start']: return 'fast'
    cur = None
    for i in timed:
        if L[i]['start'] - 0.1 <= t: cur = i
    if cur is None or cur >= len(secs): return 'fast'
    name = norm(secs[cur][1]) + ' ' + secs[cur][2]
    if any(k in name for k in ('breakdown', 'bridge', 'stripped', 'whisper')): return 'calm'
    if 'pre' in name: return 'mid'
    if any(k in name for k in ('chorus', 'chant', 'hook', 'refrain', 'drop', 'outro', 'intro')): return 'fast'
    return 'mid'


def pace(shots, L, day, audio, dur):
    """Split every shot into beat-synced sub-cuts sized to the section energy. Sub-cuts of a clip show other moments of
    the same clip (alternating punch-in); sub-cuts of a graphic alternate with the line's own scene clip (or the
    nearest scene clip) and the graphic resumes where its animation left off."""
    bpm, beats = beat_grid(audio, dur)
    end_shot = shots[-1]; body = shots[:-1]; out = []
    clips_seen = {}
    _gd = os.path.dirname(next((x['src'][1] for x in body if x['src'][0] == 'clip'), '') or '.')
    pool = sorted(f"{_gd}/{f}" for f in os.listdir(_gd) if f.endswith('.mp4') and f.count('.') == 1) if os.path.isdir(_gd) else []
    CAP = int(os.environ.get('GV_CLIP_MAX_USES', '4'))
    _dur = {}
    def cdur(c):
        if c not in _dur:
            try: _dur[c] = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', c], capture_output=True, text=True).stdout.strip())
            except Exception: _dur[c] = 0.0
        return _dur[c]
    _ex = set(filter(None, os.environ.get('GV_CLIP_EXCLUDE', '').split(',')))   # QC-failed clips
    pool = [c for c in pool if os.path.basename(c) not in _ex]
    FORCE_GFX = [tuple(map(float, w.split('-'))) for w in os.environ.get('GV_FORCE_GFX', '').split(',') if w]
    outside = {}; chorus_used = []; use_log = []; ch = {'n': 0, 'prev': False}; ch_last = {}
    def allowed(c, chorus):
        # rule : no repeats outside choruses. A clip >=5 s may give 2 distinct segments outside;
        # inside choruses a clip may come back as a deliberate callback (total cap CAP).
        if os.path.basename(c) in _ex or clips_seen.get(c, 0) >= CAP: return False
        if chorus: return ch_last.get(c) != ch['n']   # once per chorus; may return on a later chorus
        return outside.get(c, 0) < (2 if cdur(c) >= 5.0 else 1)
    def clip_src(path, strict=True, chorus=False, t=None):
        if not allowed(path, chorus):
            free = [c for c in pool if allowed(c, chorus)]
            if chorus:   # callback: prefer a clip already used on an earlier chorus hook, else an unused one
                cb = [c for c in free if c in chorus_used]
                free = cb or sorted(free, key=lambda c: clips_seen.get(c, 0))
            else: free = sorted(free, key=lambda c: clips_seen.get(c, 0))
            if not free: return None
            path = free[0]
        if chorus:
            ch_last[path] = ch['n']
            if path not in chorus_used: chorus_used.append(path)
        else: outside[path] = outside.get(path, 0) + 1
        use_log.append((path.split('/')[-1], round(t or 0, 2), f"chorus{ch['n']}" if chorus else 'other'))
        k = clips_seen.get(path, 0); clips_seen[path] = k + 1
        off = [0.0, 3.0, 1.5, 4.2, 0.6, 2.4, 1.8, 3.6][k % 8]
        try:   # short hero clips (2-3 s) - keep the in-point inside the clip
            cd = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip())
            off = off % max(0.01, cd - 1.6) if cd - 1.6 > 0.05 else 0.0
        except Exception: pass
        return ('clip', path, round(off, 2), {'zoom': [1.0, 1.16][k % 2]})
    def near_clip(i):
        li = body[i]['line']
        for j in list(range(i, -1, -1)) + list(range(i + 1, len(body))):   # same line first, then nearest earlier/later
            if body[j]['src'][0] == 'clip' and (j == i or body[j]['line'] == li): return body[j]['src'][1]
        for d_ in range(1, len(body)):
            for j in (i - d_, i + d_):
                if 0 <= j < len(body) and body[j]['src'][0] == 'clip': return body[j]['src'][1]
        return None
    for i, s in enumerate(body):
        t0, t1 = s['t0'], s['t1']
        e = energy_at((t0 + t1) / 2, L, day); nb = PACE_BEATS[e]
        e_ch = section_is_chorus((t0 + t1) / 2, L, day)
        if e_ch and not ch['prev']: ch['n'] += 1
        ch['prev'] = e_ch
        bs = [b for b in beats if t0 + 0.3 < b < t1 - 0.3]
        cutsp = [t0]
        k = 0
        for b in bs:
            k += 1
            if k >= nb and b - cutsp[-1] >= 0.4: cutsp.append(b); k = 0
        if t1 - cutsp[-1] < 0.35 and len(cutsp) > 1: cutsp.pop()
        cutsp.append(t1)
        pieces = list(zip(cutsp[:-1], cutsp[1:]))
        fin = []
        for a, b in pieces:                         # hard cap ~2.5 s
            m = max(1, math.ceil((b - a) / PACE_MAX_S))
            fin += [(a + (b - a) * q / m, a + (b - a) * (q + 1) / m) for q in range(m)]
        alt = near_clip(i) if s['src'][0] == 'gfx' else None
        for q, (a, b) in enumerate(fin):
            n_ = dict(s, t0=a, t1=b, energy=e)
            _fg = any(a < y and b > x for x, y in FORCE_GFX)   # QC-flagged windows -> graphic
            if s['src'][0] == 'clip':
                cs = None if _fg else clip_src(s['src'][1], chorus=e_ch, t=a)
                if cs is None:   # every passing clip used CAP times: borrow the nearest graphic instead
                    gj = min((j for j in range(len(body)) if body[j]['src'][0] == 'gfx'), key=lambda j: abs(j - i), default=None)
                    if gj is not None:
                        p_ = dict(body[gj]['src'][2]); p_['_toff'] = 0.0; p_['_dur'] = b - a
                        cs = ('gfx', body[gj]['src'][1], p_)
                    else: cs = ('clip', s['src'][1], 0.0, {'zoom': 1.0})
                n_['src'] = cs
            elif s['src'][0] == 'gfx':
                cs = clip_src(alt, chorus=e_ch, t=a) if (q % 2 == 1 and alt and not _fg) else None
                if cs: n_['src'] = cs; n_['sub_of'] = 'gfx'
                else:
                    p_ = dict(s['src'][2]); p_['_toff'] = a - t0; p_['_dur'] = t1 - t0
                    n_['src'] = ('gfx', s['src'][1], p_)
            if q: n_['sub'] = q
            out.append(n_)
    out.append(end_shot)
    try: G.save_json([{'clip': c, 't': t, 'section': w} for c, t, w in use_log], os.path.join(os.path.dirname(_gd), 'clip_uses.json'))
    except Exception: pass
    return out, bpm


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
            'glitch': "rgbashift=rh=-8:bh=8:enable='lt(t,0.12)'",
            # no VHS/tape lines. Chorus-drop accent = hard cut + brief magenta flash + brief RGB split, no noise/tblend
            'vhs': "fade=in:st=0:d=0.06:color=0xFF28C8,rgbashift=rh=-10:bh=10:enable='lt(t,0.12)'"}.get(t, '')


def seg_design(des, s, L, day):
    """house style: chorus-drop shots switch to the Glitch Tape transition/grade; others keep Acid Deadpan."""
    if not des.get('house') or s.get('src', [''])[1] == 'endcard': return des
    try:
        if energy_at((s['t0'] + s['t1']) / 2, L, day) == 'fast' and s['t0'] > 1.0:
            return dict(des, transition='vhs', grade='punchy')
    except Exception:
        pass
    return des


def render_seg(job):
    s, W, H, out, endp, design, i = job
    import kgfx2 as kgfx, design as DZ
    from PIL import Image
    kgfx.set_theme(DZ.theme(design))
    tv = trans_vf(design, i, 0).replace('s=WxH', f's={W}x{H}')
    grade = DZ.GRADE.get(design.get('grade'), '')
    ENC = ENC0
    nfr = max(1, round(s['t1'] * FPS) - round(s['t0'] * FPS)); dur = nfr / FPS
    kind, src, x = s['src'][:3]; opt = s['src'][3] if len(s['src']) > 3 else {}
    if kind == 'clip':
        spd = min(1.0, max(0.4, (6.0 - x) / dur))
        z = opt.get('zoom', 1.0)
        zf = f",scale=iw*{z}:ih*{z},crop={W}:{H}" if z != 1.0 else ''
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(x), '-i', src, '-filter_complex',
                        f"setpts=PTS/{spd},{_vf_fill(W, H)}{zf},fps={FPS}" + (',' + grade if grade else '') + (',' + tv if tv else ''), '-frames:v', str(nfr), '-an'] + ENC + [out], check=True)
        return out
    if kind == 'still':
        zin = x % 2 == 0
        z = (f"zoompan=z='{'1+0.0016*on' if zin else '1.12-0.0016*on'}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={nfr}:s={W}x{H}:fps={FPS}")
        pre = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2}," if H > W else
               f"split[a][b];[a]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},boxblur=40:3,eq=brightness=-0.15[bg];[b]scale=-2:{H*2}[fg];[bg][fg]overlay=(W-w)/2:0,")
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', src, '-filter_complex', pre + z + (',' + grade if grade else '') + (',' + tv if tv else ''), '-frames:v', str(nfr)] + ENC + [out], check=True)
        return out
    p = dict(x); toff = p.pop('_toff', 0.0); tdur = p.pop('_dur', None) or dur
    bgframes = None
    if src == 'endcard':
        p.update(endp)
        bc = p.pop('bg_clip', None)
        if bc and os.path.exists(bc):              # moving end-card background (no stills)
            spd = min(1.0, 6.0 / max(dur, 0.1))
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', bc, '-vf', f"setpts=PTS/{spd},{_vf_fill(W, H)},fps={FPS}",
                                  '-frames:v', str(nfr), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
            fsz = W * H * 3; bgframes = [Image.frombytes('RGB', (W, H), raw[i:i + fsz]) for i in range(0, len(raw) - fsz + 1, fsz)]
            p['bg'] = bgframes[0] if bgframes else None
        elif p.get('bg'): p['bg'] = _fill(Image.open(p['bg']).convert('RGB'), W, H)
    f = kgfx.R.get(src, kgfx.R['headline'])
    pr = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
                           '-i', '-'] + (['-vf', tv] if tv else []) + ENC + [out], stdin=subprocess.PIPE)
    for k in range(nfr):
        try:
            if bgframes: p['bg'] = bgframes[min(k, len(bgframes) - 1)]
            im = kgfx.render(src if src in kgfx.R else 'headline', W, H, toff + k / FPS, tdur, p)
            if src != 'endcard':                   # constant gentle push so no graphic ever sits still
                zz = 1.0 + 0.022 * ((toff + k / FPS) / max(tdur, 0.5))
                cw, ch = int(W / zz), int(H / zz)
                im = im.crop(((W - cw) // 2, (H - ch) // 2, (W - cw) // 2 + cw, (H - ch) // 2 + ch)).resize((W, H), Image.BILINEAR)
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
        a = int(min(1, (y - y0) / (H * 0.10)) * 205)   # was 175, darker band for dark photos
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
    """kgfx2 logs text that could not be shrunk to fit, and every string on each shot's final frame. A final-frame
    word that is not in the source text but is a strict prefix of a source word is a truncated fragment = failure."""
    srcw = set(norm(G.read(os.path.join(day, 'title.txt')) + ' ' + G.read(os.path.join(day, 'stories.md')) + ' ' + G.read(os.path.join(day, 'lyrics.txt'))).split())
    fails, trunc = [], set()
    try:
        from spellchecker import SpellChecker; _sp = SpellChecker()
        real = lambda w: not _sp.unknown([w])
    except ImportError:
        real = lambda w: False
    recs = []
    if os.path.exists(fitlog):
        for ln in open(fitlog):
            try: recs.append(json.loads(ln))
            except Exception: pass
    for r in recs:
        if r.get('fail'): fails.append(f"{r.get('shot')}: {r.get('text')!r}"[:120])
        elif 'final' in r:
            fw = norm(r['final']).split()
            for i, w in enumerate(fw):
                # 'NBC News' vs source handle '@NBCNews' is not truncation; skip if w+next word is a source word
                if i + 1 < len(fw) and (w + fw[i + 1]) in srcw: continue
                if (w + '-') in r['final'].lower(): continue  # hyphenated prefix like 'ex-editors'
                if len(w) >= 2 and not w.isdigit() and w not in srcw and not real(w) and any(sw.startswith(w) and sw != w for sw in srcw):
                    trunc.add(w)
    return sorted(set(fails)), sorted(trunc)


def end_tags(day):
    """Tagged accounts for the end card: source handles from sources.txt then post.txt (in order), then @grok, @suno."""
    seen, out = set(), []
    for fn in ('sources.txt', 'post.txt'):
        pth = os.path.join(day, fn)
        if not os.path.exists(pth): continue
        for h in re.findall(r'(?<![\w/])@(\w{1,15})', G.read(pth)):
            k = h.lower()
            if k in seen or k in ('jxwalker', 'grok', 'suno'): continue
            seen.add(k); out.append(h)
    return out + ['grok', 'suno']


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
    ap.add_argument('--clips', type=int, default=int(os.environ.get('GV_KARAOKE_CLIPS', 14)))   # no stills -> every scene is a clip
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
                import storyboard as SB                    # treatment + lead bible + shot list
                try: SB.ensure_direction(day, lyric_lines(day))
                except Exception as e: status['warnings'].append(f'storyboard direction failed ({str(e)[:120]})')
                P = plan_opus(day, work, a.stills, a.clips)
                try: SB.review(P, day, work, lyric_lines(day))  # Opus storyboard review before any Grok spend
                except Exception as e: status['warnings'].append(f'storyboard review failed ({str(e)[:120]})')
            except Exception as e:
                status['warnings'].append(f'opus planner failed ({str(e)[:120]}); template plan, no Grok scenes')
                P = plan_template(day)
            P['ver'] = PLAN_VER; P['plan_s'] = round(time.time() - t0)
            G.save_json(P, os.path.join(work, 'plan_raw.json'))
            status['warnings'] += fact_lint(P, day)
            G.save_json(P, pp)
        import design as DZ
        DES = DZ.resolve(day, P.get('design'), force_palette=direction(day)['palette']); status['design'] = DES
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
            _keep = set(filter(None, os.environ.get('GV_MATCH_KEEP', '').split(',')))   # hand-verified clips are never redrawn
            bad_n = [n_ for n_ in bad_n if not ((shots[n_]['src'][0] == 'clip' and os.path.splitext(os.path.basename(str(shots[n_]['src'][1])))[0] in _keep) or (shots[n_]['src'][0] == 'gfx' and shots[n_]['src'][1] in _keep))]
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
        shots, bpm_ = pace(shots, L, day, audio, dur); status['bpm'] = round(bpm_, 1)
        G.log(f'karaoke: paced {len(shots)} shots at {bpm_:.1f} BPM')
        end_t = shots[-1]['t0']
        story = []   # no story banner/chip over the video (standing rule)
        stills = sorted(f for f in os.listdir(gdir) if f.endswith('.png'))
        endp = {'title': G.read(os.path.join(day, 'title.txt')).strip(), 'credit': (P.get('credit') or '')[:80],
                'sub': 'Grok Bot · ' + time.strftime('%-d %b %Y', time.strptime(os.path.basename(day)[:10], '%Y-%m-%d')) if re.match(r'\d{4}-\d\d-\d\d', os.path.basename(day)) else '',
                'bg': os.path.join(gdir, stills[-1]) if stills else None}
        endp['tags'] = end_tags(day)   # end card lists the post's tagged accounts
        if os.environ.get('GV_ENDCARD_PHOTO') != '1':  # un-QC'd lead still behind the end card failed strict QC (plaid shirt) -> plain theme bg
            endp['bg'] = None
        if P.get('scenes') and stills:                # prefer the outro scene as the end-card background
            for v in P.get('outro', [])[::-1]:
                if v.get('kind') == 'scene' and os.path.exists(os.path.join(gdir, f"{v['id']}.png")):
                    endp['bg'] = os.path.join(gdir, f"{v['id']}.png")
                    if os.environ.get('GV_ENDCARD_PHOTO') != '1': endp['bg'] = None; break
                    if os.path.exists(os.path.join(gdir, f"{v['id']}.mp4")): endp['bg_clip'] = os.path.join(gdir, f"{v['id']}.mp4")
                    break
        G.save_json({'shots': [{'t0': round(s['t0'], 2), 't1': round(s['t1'], 2), 'src': [s['src'][0], s['src'][1]], 'line': s.get('line'), 'redrawn': s.get('redrawn')} for s in shots],
                     'story': story}, os.path.join(work, 'timeline.json'))
        sizes = [(1080, 1920)] + ([] if a.no_16x9 else [(1920, 1080)])
        jobs = []
        for W, H in sizes:
            sd = os.path.join(work, f'seg_{W}x{H}'); os.makedirs(sd, exist_ok=True)
            jobs += [(s, W, H, os.path.join(sd, f'{i:03d}.mp4'), endp, seg_design(DES, s, L, day), i) for i, s in enumerate(shots)]
        rt = time.time()
        fitlog = os.path.join(work, 'fit_log.jsonl'); open(fitlog, 'w').close(); os.environ['KGFX_FITLOG'] = fitlog  
        with Pool(min(8, os.cpu_count() or 4)) as pool:
            segs = pool.map(render_seg, jobs, chunksize=1)
        os.environ.pop('KGFX_FITLOG', None)   # margin_check's synthetic truncation cases must not count
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
                            f"[0:v][1:v]overlay=0:0,ass='{assf}',scale=in_range=auto:out_range=tv,format=yuv420p[v]",  # jpeg-range sources gave yuvj420p
                            '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
                            '-profile:v', 'high', '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-t', f'{dur:.3f}', '-movflags', '+faststart', tmp], check=True)
            os.replace(tmp, dst); results[tag] = dst
        # chat copy < 25 MB: two-pass at a bitrate derived from the duration, 22 MB target, retry lower if over
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
        # fit failures and truncated words fail the build
        fit_fail, trunc = fit_check(fitlog, texts, day)
        status.update(fit_fail=fit_fail, truncated_words=trunc, fit_ok=not fit_fail and not trunc)
        if fit_fail or trunc:
            status['warnings'].append(f"text fit check failed: {fit_fail[:5]} truncated {trunc}")
            vr['ok'] = False; vr['checks']['text_fits'] = False
        else: vr['checks']['text_fits'] = True
        status.update(ok=vr['ok'], verify=vr['checks'], sync=sync, sync_ok=sync_ok, spelling_unknown=bad, contact_sheet=cs,
                      shots=len(shots), avg_shot=round(end_t / max(1, len(shots) - 1), 2),
                      scenes=sum(1 for s in shots if s['src'][0] in ('clip', 'still')), clips_used=sum(1 for s in shots if s['src'][0] == 'clip'),
                      stills_used=sum(1 for s in shots if s['src'][0] == 'still'), max_hold=round(max(s['t1'] - s['t0'] for s in shots[:-1]), 2),
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
        # a verification-only failure means all paid media already exists in work_karaoke. Falling back to the
        # Claudia/cine-real chain then burns 50+ min, hits the routine's time limit and loses post/sources. Stop here instead;
        # fix the check and re-render with: karaoke.py DAY --skip-gen --no-fallback  (no Grok spend).
        if why.startswith('RuntimeError: verification failed'):
            G.save_json(dict(stage='media_done_verify_failed', error=why[:500], resume=f'karaoke.py {day} --skip-gen --no-fallback'),
                        os.path.join(day, 'VIDEO_CHECKPOINT.json'))
            print(f"GROK_VIDEO_STATUS=failed code=4 style=karaoke resumable=1 reason={why[:300]!r}", flush=True); sys.exit(4)
        if a.no_fallback or a.skip_gen:
            print(f"GROK_VIDEO_STATUS=failed code=3 style=karaoke reason={why[:300]!r}", flush=True); sys.exit(3)
        G.log(f"karaoke FAILED ({why[:200]}); falling back to grok_video.py (Claudia/slopcore chain)")
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, 'grok_video.py'), day] + passthru)


if __name__ == '__main__':
    main()
