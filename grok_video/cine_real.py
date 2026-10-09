"""cine-real style: photoreal, lyric-literal, fast-cut music video (see README "cine-real (photoreal) style").

plan (one text call) -> image_gen stills in batched sessions, with hero reference_to_video clips (the still pinned as
first_frame) starting as soon as their stills exist -> Pip cameo (image_edit of the reference) -> local edit and a
parallel render. Usage-capped, time-limited, and every missing piece falls back to stills."""
import json, math, os, random, re, time
import common_gv as G
import real_plan as RP
import real_gen
import real_render as RR
from real_gen_usage import usage_pct

STILL_COST = 0.012           # % of the weekly pool per image_gen still (measured 8 Oct: about 0.01 %)
CLIP_COST = 0.14             # % per 4 s 720p reference_to_video clip (9 Oct: 25 clips + 107 stills = 20->24 %, i.e. 0.07-0.15 each; scaled by length)
HERO_SECONDS = 4             # default hero length (--real-clip-sec 3-5); the still is pinned as first_frame
RENDER_RESERVE_S = 9 * 60    # generation stops this long before the hard time limit (render ~5 min + chat copy + margin)
PLAN_RESERVE_S = 17 * 60     # the planner may only use time that leaves this much before the limit


def cameo_prompt(scene, LK):
    return ("Turn this exact character into a small physical collectible vinyl toy figure, exactly the same design, "
            "proportions and colours: white egg-shaped body, two tall white bunny ears with pink insides, a thin antenna "
            "with a small yellow ball, a dark-navy face screen with glowing cyan closed happy arc eyes (^ ^) and pink blush, "
            "a pink heart on the chest, short stubby legs with round feet. Nothing on its head or face. Place the toy in a "
            f"real photographed scene: {scene} The toy is small in the frame, standing upright, in sharp focus, shallow "
            "depth of field, real light falling on its glossy vinyl. " + LK['prompt'] + " No text, no logos.")


def build_jobs(plan, slots, work, LK, sec=HERO_SECONDS):
    segs = {s['seg']: s for s in plan['segments']}
    stills, heroes = [], []
    for si, sl in enumerate(slots):
        imgs = (segs.get(sl['seg']) or {}).get('images') or []
        imgs = imgs[:sl['images']]
        sl['plan_images'] = imgs
        for k, im in enumerate(imgs):
            out = os.path.join(work, 'stills', f"s{si:02d}_{k}.jpg")
            body = im['prompt'].strip()
            for k0, v0 in (LK.get('recolour') or {}).items():     # keep the one accent colour consistent
                body = re.sub(rf'\b{k0}\b', v0, body, flags=re.I)
            prompt = (f"{body} {LK['prompt']} Absolutely no text anywhere: no letters, numbers, writing, signatures, "
                      "receipts, documents, signs, labels or logos. Original designs only, no lookalikes of famous "
                      "characters, robots or real people.")
            stills.append({'id': f's{si:02d}_{k}', 'kind': 'gen', 'prompt': prompt, 'out': out, 'aspect': '9:16'})
            if k == 0 and sl['hero']:
                mo = re.sub(r'\bamber\b', LK.get('accent_name', 'amber'), im.get('motion') or 'slow handheld push-in, real physical motion')
                heroes.append({'id': f'h{si:02d}', 'kind': 'r2v', 'first_frame': out, 'image': out,
                               'duration': sec, 'resolution': '720p', 'aspect': '9:16',
                               'prompt': f"Continue this exact photoreal shot for {sec} seconds: {mo} Keep the same "
                                         f"people, place, palette and film look ({LK['label']}, film grain, halation). "
                                         "Real physical motion, handheld wobble, no cuts, no text, no logos, no lookalikes of famous "
                                         "characters or real people.",
                               'out': os.path.join(work, 'heroes', f'h{si:02d}.mp4'), 'seg': sl['seg'],
                               'pri': si})
    return stills, heroes


def hero_order(heroes, slots):
    rank = {'hook': 0, 'drop': 1, 'chorus': 2}
    kinds = {sl['seg']: sl['kind'] for sl in slots}
    return sorted(heroes, key=lambda h: (rank.get(kinds.get(h['seg']), 3), h['pri']))


_VALID = {}
_DUR = {}


def valid_video(path, min_frames=24):
    """A hero clip counts only if it really decodes (a truncated or mislabelled download must not crash the render)."""
    if path not in _VALID:
        ok = False
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            _DUR[path] = n / (cap.get(cv2.CAP_PROP_FPS) or 24)
            ok = cap.isOpened() and n >= min_frames and cap.read()[0]
            cap.release()
        except Exception:
            ok = False
        _VALID[path] = bool(ok)
    return _VALID[path]


def valid_image(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def make_edit(entries, extra, seed):
    """entries: real segments in time order, each {'seg', 'kind', 'cs' (its cuts), 'files' [(path, plan image)],
    'hero' (clip path or None)}; extra: [(position, path, plan image)] pictures nobody owns (e.g. lines that were not
    sung). Every cut gets a picture: hero clip windows, each segment's own stills (at most twice: the second time as a
    tighter cut-in), then the nearest borrowed pictures (still at most twice, more only if nothing else is left)."""
    rnd = random.Random(seed)
    uses = {}
    for d in entries:
        n_st = len(d['cs']) - (2 if d['hero'] else 0)
        d['own'] = d['files'][:max(0, n_st)]
        d['n_st'] = n_st
        for f, _ in d['own']:
            uses[f] = uses.get(f, 0) + 1
    pool = [(i, f, im) for i, d in enumerate(entries) for f, im in d['files']] + list(extra)
    edit = []
    for i, d in enumerate(entries):
        cs, need = d['cs'], d['n_st'] - len(d['own'])
        seq_st = [('still', f, 0, False, im) for f, im in d['own']]
        # more cuts than own pictures: first unused pictures from neighbouring segments (fresh beats repeated),
        # then punched-in cut-ins of the segment's own stills
        for x in sorted([x for x in pool if uses.get(x[1], 0) == 0 and abs(x[0] - i) <= 2], key=lambda x: abs(x[0] - i)):
            if need <= 0:
                break
            seq_st.append(('still', x[1], 0, False, x[2])); uses[x[1]] = 1; need -= 1
        ins = []
        for f, im in d['own']:
            if need <= 0:
                break
            if uses[f] < 2:
                ins.append((f, im)); uses[f] += 1; need -= 1
        for f, im in ins:                              # each cut-in right after its wide
            k = next(j for j, e in enumerate(seq_st) if e[1] == f) + 1
            seq_st.insert(k, ('still', f, 0, True, im))
        while need > 0:                               # failed generations: borrow the nearest pictures
            last = seq_st[-1][1] if seq_st else None
            cand = sorted([x for x in pool if uses.get(x[1], 0) < 2 and x[1] != last],
                          key=lambda x: (uses.get(x[1], 0) > 0, abs(x[0] - i)))
            if not cand:                              # nothing left under 2 uses: least-used anywhere
                cand = sorted([x for x in pool if x[1] != last] or pool, key=lambda x: (uses.get(x[1], 0), abs(x[0] - i)))
            if not cand:
                break
            _, f, im = cand[0]
            seq_st.append(('still', f, 0, uses.get(f, 0) >= 1, im))
            uses[f] = uses.get(f, 0) + 1
            need -= 1
        if d['hero']:
            hero = d['hero']
            seq = [('video', hero, 0.25, False, None)]
            k = max(1, len(seq_st) - 1) if len(seq_st) > 1 else len(seq_st)
            w2 = max(0.5, min(2.0, _DUR.get(hero, 4.0) - 1.6))     # 2nd window must not run off the clip end
            seq += seq_st[:k] + [('video', hero, w2, True, None)] + seq_st[k:]
            uses[hero] = 2
        else:
            seq = seq_st
        for c, (kind, f, win0, cut_in, im) in zip(cs, seq):
            mv = (im or {}).get('move') or rnd.choice(['push_in', 'pull_out', 'parallax', 'pan_left', 'pan_right', 'drift'])
            if cut_in and kind == 'still':
                mv = {'push_in': 'drift', 'pull_out': 'push_in'}.get(mv, 'push_in')
            edit.append({'t0': c['t0'], 't1': c['t1'], 'src': f, 'kind': kind, 'win0': win0, 'cut_in': cut_in,
                         'move': mv, 'seg': d['seg'], 'seg_kind': d['kind'], 'on_beat': c.get('on_beat'),
                         'anchor': (rnd.uniform(0.42, 0.58), rnd.uniform(0.36, 0.56)) if cut_in else (0.5, 0.5)})
    edit.sort(key=lambda e: e['t0'])
    # fx: white flash on chorus / drop entries, whips on some drop cuts and on story changes, light leaks
    prev_seg = None
    for e in edit:
        new_seg = e['seg'] != prev_seg
        e['flash'] = new_seg and (e['seg'].endswith(':1') and e['seg_kind'] == 'chorus' or (e['seg_kind'] == 'drop' and e['t1'] - e['t0'] > 0))
        e['whip'] = (e['seg_kind'] == 'drop' and rnd.random() < 0.22) or (new_seg and e['seg_kind'] == 'verse' and e['seg'].endswith((':1', ':5')))
        e['leak'] = rnd.random() < (0.28 if e['seg_kind'] in ('chorus', 'drop', 'hook') else 0.12)
        prev_seg = e['seg']
    if edit:
        edit[0]['flash'] = False; edit[0]['whip'] = False
    return edit, uses



def generate(stills, heroes, cameo, slots, work, args, status):
    """Stills and hero clips at the same time: stills (cameo and hero first frames first) in up to 4 sessions; each hero
    starts as soon as its first-frame still exists, up to 4 sessions. The usage meter is watched the whole time and
    spending stops at --real-max-pct. Nothing new starts after the time-limit stop; what exists is edited."""
    import threading
    cap = args.real_max_pct
    dl = getattr(args, 'deadline', None)
    stop = dl - RENDER_RESERVE_S if dl else None
    sec = getattr(args, 'real_clip_sec', HERO_SECONDS) or HERO_SECONDS
    clip_cost = CLIP_COST * sec / 4
    u0 = usage_pct()
    G.log(f"usage meter at start: {u0}% (this run may spend up to about {cap}%)")
    hs = hero_order(heroes, slots)
    room = cap - 0.8 - (len(stills) + 1) * STILL_COST           # 0.8 % margin for the whole-percent meter
    n_fit = max(0, int(room / clip_cost))
    if len(hs) > n_fit:
        G.log(f"budget: {n_fit} of {len(hs)} hero clips fit under {cap}%")
        hs = hs[:n_fit]
    first = [h['first_frame'] for h in hs]
    by_out = {j['out']: j for j in stills}
    order = ([cameo] if cameo else []) + [by_out[f] for f in first if f in by_out] + [j for j in stills if j['out'] not in set(first)]
    todo = [j for j in order if not (os.path.exists(j['out']) and os.path.getsize(j['out']) > 1000)]
    n_edit = sum(1 for j in todo if j['kind'] == 'edit')
    B = real_gen.Batcher(work, {'gen': len(todo) - n_edit + 8, 'edit': n_edit + 4, 'i2v': 0}, batch_size=6, max_parallel=4,
                         start_gap=6.0, tag='stills', deadline=stop)
    HB = real_gen.Batcher(work, {'gen': 0, 'edit': 0, 'i2v': 0, 'r2v': len(hs) + 4}, batch_size=2,
                          max_parallel=getattr(args, 'hero_parallel', 4),
                          start_gap=8.0, tag='heroes', timeout=600, deadline=stop)
    st = {'stills_done': False, 'heroes_done': False, 'cap': None, 'r_st': None, 'readings': []}

    def run_stills():
        try:
            st['r_st'] = B.run(todo)
        except Exception as e:                  # never let a thread error kill the run: edit what exists
            G.log(f"WARNING: stills thread error: {e!r}"[:300])
            st['r_st'] = {'abort': None, 'error': repr(e)[:200]}
        st['stills_done'] = True

    # the cap is RELATIVE: spent = meter now - meter at the start of this run (never an absolute meter value).
    # A weekly reset during the run (meter drops) is handled by adding what was spent before the drop.
    mt = {'base': u0, 'prev': u0, 'carried': 0.0}

    def spent_now(u):
        if u is None:
            return None
        if mt['base'] is None:                  # start reading failed: the first good reading is the baseline
            mt['base'] = mt['prev'] = u
            return 0.0
        if mt['prev'] is not None and u < mt['prev'] - 2:   # pool reset mid-run
            mt['carried'] += mt['prev'] - mt['base']
            mt['base'] = 0
            G.log(f"usage meter dropped {mt['prev']}% -> {u}% (weekly reset); counting {mt['carried']:.0f}% spent so far")
        mt['prev'] = u
        return mt['carried'] + u - mt['base']

    def meter():
        last = time.time()
        while not (st['stills_done'] and st['heroes_done']):
            time.sleep(2)
            if time.time() - last < 90:
                continue
            last = time.time()
            u = usage_pct()
            st['readings'].append(u)
            sp = spent_now(u)
            if sp is not None and sp >= cap - 0.5:
                msg = f'usage cap reached: this run spent about {sp:.0f}% (meter {u0}% at start, {u}% now)'
                st['cap'] = msg
                with B.lock:
                    B.abort = B.abort or msg
                with HB.lock:
                    HB.abort = HB.abort or msg
                G.log(f"WARNING: {msg}; no more generation")

    t_st = threading.Thread(target=run_stills, daemon=True); t_st.start()
    t_m = threading.Thread(target=meter, daemon=True); t_m.start()
    hres, tried = [], set()
    try:
        while True:
            if B.abort or HB.abort or (stop and time.time() > stop - 60):
                break
            left = [h for h in hs if h['id'] not in tried and not os.path.exists(h['out'])]
            ready = [h for h in left if os.path.exists(h['first_frame'])]
            if not left or (st['stills_done'] and not ready):
                break
            cap_n = HB.batch_size * HB.max_parallel
            if ready and (len(ready) >= cap_n or st['stills_done'] or len(ready) == len(left)):
                take = ready[:cap_n]
                tried.update(h['id'] for h in take)
                hres.append(HB.run(take))
                continue
            time.sleep(3)
    except Exception as e:
        G.log(f"WARNING: hero loop error: {e!r}"[:300])
    st['heroes_done'] = True
    t_st.join(timeout=max(30, (stop - time.time() + 120) if stop else 3600))
    st['stills_done'] = True
    quota = B.abort or HB.abort
    if quota:
        G.log(f"WARNING: generation stopped early: {quota[:200]}")
        status['warnings'].append(f'generation stopped early ({"usage cap" if st["cap"] else "allowance reply"}): '
                                  'the edit uses the pictures made so far')
    if stop and time.time() > stop - 60:
        G.log("time limit: generation window closed; editing what exists")
    u3 = usage_pct()
    n_st = sum(1 for j in stills if os.path.exists(j['out']))
    n_h = sum(1 for h in heroes if os.path.exists(h['out']))
    G.log(f"generation done: {n_st}/{len(stills)} stills, cameo {'ok' if cameo and os.path.exists(cameo['out']) else 'MISSING'}, "
          f"{n_h}/{len(hs)} hero clips; meter {u0}% -> {u3}%")
    sp3 = spent_now(u3)
    return {'usage_start': u0, 'usage_end': u3, 'spent_pct': sp3,
            'stills_made': n_st, 'heroes_made': n_h, 'heroes_planned': len(hs), 'meter_readings': st['readings'],
            'abort': quota, 'throttle_events': B.throttle_events + HB.throttle_events}

def prepare(day, work, look_genre, args, status):
    """Everything that needs only lyrics.txt: the look, the beat grid, provisional slots, the plan and the job list.
    Runs while the word timings are still being made."""
    if getattr(args, 'style', '') == 'slopcore':
        import slop_real
        return slop_real.prepare(day, work, look_genre, args, status)
    look, why = RP.pick_real_look(look_genre, getattr(args, 'real_look', 'auto'))
    LK = RP.REAL_LOOKS[look]
    status['real_look'] = look
    G.log(f"cine-real look: {look} ({why})")
    audio = G.audio_path(day)
    dur = G.duration(audio)
    import assemble
    beats = assemble.beat_grid(audio, G.read(os.path.join(day, 'style.txt')), work)
    bn = os.path.basename(os.path.normpath(day)).replace('-', '')[:8]
    seed = args.seed if getattr(args, 'seed', None) is not None else (int(bn) if bn.isdigit() else 7)
    plines = RP.provisional_lines(day)
    pslots = RP.provisional_slots(plines, n_heroes=args.real_heroes, max_images=args.real_images)
    G.save_json(pslots, os.path.join(work, 'slots.json'))
    G.log(f"slots (from lyrics.txt): {len(pslots)} segments, {sum(s['images'] for s in pslots)} images, "
          f"{sum(s['hero'] for s in pslots)} hero clips")
    sec = getattr(args, 'real_clip_sec', HERO_SECONDS) or HERO_SECONDS
    t0 = time.time()
    plan = RP.plan(day, work, look, pslots, plines, deadline=getattr(args, 'deadline', None), clip_sec=sec,
                   reserve_s=PLAN_RESERVE_S)
    status['plan'] = {'secs': round(time.time() - t0), 'segments': len(plan['segments']), 'fallback': bool(plan.get('fallback')),
                      'images': sum(len(s.get('images') or []) for s in plan['segments'])}
    stills, heroes = build_jobs(plan, pslots, work, LK, sec)
    cameo = {'id': 'cameo', 'kind': 'edit', 'images': [G.PIP_REF], 'prompt': cameo_prompt(plan.get('cameo') or
             LK.get('cameo') or 'on the edge of a DJ mixer after the show.', LK),
             'out': os.path.join(work, 'stills', 'cameo.jpg')}
    return {'day': day, 'work': work, 'look': look, 'LK': LK, 'audio': audio, 'dur': dur, 'beats': beats, 'seed': seed,
            'pslots': pslots, 'plan': plan, 'stills': stills, 'heroes': heroes, 'cameo': cameo}


def generate_media(P, args, status):
    if P.get('v2'):
        import slop_real
        return slop_real.generate_media(P, args, status)
    gen = {'skipped': bool(args.skip_gen)}
    if os.environ.get('CINE_REAL_FAIL') == 'gen':
        G.log("TEST: CINE_REAL_FAIL=gen, skipping generation")
    elif not args.skip_gen:
        gen.update(generate(P['stills'], P['heroes'], P['cameo'], P['pslots'], P['work'], args, status))
    status['generation'] = gen
    return gen


def edit_and_render(P, L, out, args, status):
    """The real cut timeline from the word timings, mapped onto the generated pictures, then the type and the render."""
    if P.get('v2'):
        import slop_real
        return slop_real.edit_and_render(P, L, out, args, status)
    day, work, LK, audio, dur, seed = P['day'], P['work'], P['LK'], P['audio'], P['dur'], P['seed']
    stills, plan, pslots, cameo = P['stills'], P['plan'], P['pslots'], P['cameo']
    segs, cuts = RP.build_timeline(L, P['beats'], dur, seed)
    G.save_json({'segments': [{k: v for k, v in s.items() if k != 'line'} for s in segs], 'cuts': cuts},
                os.path.join(work, 'timeline.json'))
    n_st = sum(1 for j in stills if os.path.exists(j['out']))
    G.log(f"timeline: {len(cuts)} cuts; {n_st}/{len(stills)} stills and "
          f"{sum(1 for h in P['heroes'] if os.path.exists(h['out']))}/{len(P['heroes'])} hero clips available")
    if n_st < max(12, len(stills) // 3):
        raise RuntimeError(f'too few stills: {n_st}/{len(stills)}')
    # ---- map the real segments onto the planned pictures
    hide = float(os.environ.get('CINE_REAL_HIDE', '0') or 0)     # TEST: pretend this share of stills (and all heroes) failed
    mapping = RP.map_segments(segs, pslots)
    files_of = {}
    for si, sl in enumerate(pslots):
        hr = random.Random(si)
        fs = [(os.path.join(work, 'stills', f's{si:02d}_{k}.jpg'), im) for k, im in enumerate(sl.get('plan_images') or [])]
        files_of[si] = [(f, im) for f, im in fs if os.path.exists(f) and not (hide and hr.random() < hide) and valid_image(f)]
    by = {}
    for c in cuts:
        by.setdefault(c['seg'], []).append(c)
    claimed, entries = set(), []
    for s in segs:
        if s['kind'] in ('cameo', 'credits'):
            continue
        si = mapping.get(s['id'])
        cs = by.get(s['id'], [])
        files, hero = [], None
        if si is not None and si not in claimed:
            claimed.add(si)
            files = files_of[si]
            h = os.path.join(work, 'heroes', f'h{si:02d}.mp4')
            if pslots[si]['hero'] and len(cs) >= 2 and not hide and files and os.path.exists(h) and valid_video(h):
                hero = h
                files = files[1:]                       # its first still is already the clip's first frame
        entries.append({'seg': s['id'], 'kind': s['kind'], 'cs': cs, 'files': files, 'hero': hero, 'si': si})
    # pictures of planned segments that never came up (e.g. lines that were not sung): extra pool for borrowing,
    # placed next to the real segment whose slot is nearest in the plan
    pos_of = {e['si']: i for i, e in enumerate(entries) if e['si'] is not None}
    extra = []
    for si, fs in files_of.items():
        if si in claimed or not fs:
            continue
        near = min(pos_of, key=lambda p: abs(p - si)) if pos_of else 0
        extra += [(pos_of.get(near, 0), f, im) for f, im in fs]
    edit, uses = make_edit(entries, extra, seed)
    over = sum(1 for f, n in uses.items() if n > 2)
    if over:
        status['warnings'].append(f'too few pictures: {over} stills had to be used 3+ times')
    cam = cameo['out'] if os.path.exists(cameo['out']) and valid_image(cameo['out']) and not hide else None
    last_still = next((e['src'] for e in reversed(edit) if e['kind'] == 'still'), edit[0]['src'] if edit else None)
    for c in cuts:
        if c['seg'] in ('cameo', 'credits'):
            edit.append({'t0': c['t0'], 't1': c['t1'], 'src': cam or last_still, 'kind': 'still',
                         'move': 'push_in' if c['seg'] == 'cameo' else 'drift', 'cut_in': False, 'seg': c['seg'],
                         'seg_kind': c['seg'], 'on_beat': c.get('on_beat'), 'flash': False, 'whip': False,
                         'leak': False, 'anchor': (0.5, 0.5)})
    edit.sort(key=lambda e: e['t0'])
    if not cam:
        status['warnings'].append('Pip cameo image missing: the sign-off shot reuses the last still')
    disp = {d['seg']: d.get('tokens') for d in plan.get('display', [])}
    acc = {d['seg']: d.get('accent') or [] for d in plan.get('display', [])}
    ass = os.path.join(work, 'type.ass')
    rows = []
    for h, _ in G.credit_rows(day):
        rows.append(h)
    rows, footer = G.credit_card(day)
    credits = {'t0': [s for s in segs if s['kind'] == 'credits'][0]['t0'], 'rows': rows[:6], 'footer': footer}
    first = [ln for ln in L if ln.get('words')][0]
    hook_toks = [t[0] for t in RR.line_tokens(first, disp.get(RP.line_id(first)))][:2]
    RR.build_ass(ass, L, disp, acc, None, LK, credits, dur, hook_toks)
    G.save_json(edit, os.path.join(work, 'edit.json'))
    lens = [e['t1'] - e['t0'] for e in edit if e['seg_kind'] not in ('cameo', 'credits')]
    metrics = {'shots': len(edit), 'avg_shot_s': round(sum(lens) / len(lens), 2),
               'distinct_pictures': len({e['src'] for e in edit if e['kind'] == 'still'}),
               'hero_clips_used': len({e['src'] for e in edit if e['kind'] == 'video'}),
               'video_share': round(sum(e['t1'] - e['t0'] for e in edit if e['kind'] == 'video') / dur, 2),
               'max_uses': max([n for f, n in uses.items() if not f.endswith('.mp4')] or [0]),
               'on_beat_frac': round(sum(1 for e in edit if e.get('on_beat')) / len(edit), 2)}
    status['real_metrics'] = metrics
    G.log(f"edit: {metrics}")
    t0 = time.time()
    if os.environ.get('CINE_REAL_FAIL') == 'render':
        raise RuntimeError('TEST: CINE_REAL_FAIL=render')
    RR.render(edit, LK, audio, ass, out, dur, seed=seed, hard_deadline=getattr(args, 'deadline', None))
    G.log(f"render: {time.time()-t0:.0f}s")
    return True, {'metrics': metrics, 'look': P['look']}


def run(day, work, out, L, look_genre, args, status):
    """All steps in a row (the routine path in grok_video.run_real overlaps planning and generation with the timings)."""
    P = prepare(day, work, look_genre, args, status)
    if args.plan_only:
        return True, {'plan_only': True}
    generate_media(P, args, status)
    return edit_and_render(P, L, out, args, status)
