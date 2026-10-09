"""Beat-cut assembly: beat grid (librosa, ffmpeg/BPM fallback), cut list aligned to bars and section starts,
best-motion windows from each clip, 1080x1920 upscale, ASS burn-in, song audio."""
import os, re, random, subprocess, json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import common_gv as G
from looks import LOOKS

FPS = 24          # native rate of the Grok clips (no 24->30 judder)


def beat_grid(audio, style_txt, work):
    cache = os.path.join(work, 'beats.json')
    j = G.load_json(cache)
    if j and os.path.getmtime(cache) > os.path.getmtime(audio):
        return j
    dur = G.duration(audio)
    try:
        import librosa
        y, sr = librosa.load(audio, sr=22050, mono=True)
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units='frames', tightness=120)
        beats = librosa.frames_to_time(frames, sr=sr).tolist()
        tempo = float(np.atleast_1d(tempo)[0])
        onset = librosa.onset.onset_strength(y=y, sr=sr)
        # downbeat phase: which of the 4 beat phases carries the most onset energy
        ob = [onset[min(f, len(onset) - 1)] for f in frames]
        phase = int(np.argmax([np.mean(ob[p::4]) if ob[p::4] else 0 for p in range(4)])) if len(ob) >= 8 else 0
        src = 'librosa'
    except Exception as e:
        G.log(f"librosa unavailable/failed ({e}); using BPM grid fallback")
        m = re.search(r'(\d{2,3})\s*BPM', style_txt or '', re.I)
        tempo = float(m.group(1)) if m else 120.0
        r = subprocess.run(['ffmpeg', '-i', audio, '-af', 'silencedetect=n=-35dB:d=0.3', '-f', 'null', '-'],
                           capture_output=True, text=True)
        ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', r.stderr)]
        start = ends[0] if ends and ends[0] < 10 else 0.0
        per = 60.0 / tempo
        beats = list(np.arange(start, dur, per)); phase = 0; src = 'bpm-grid'
    m = re.search(r'(\d{2,3})\s*BPM', style_txt or '', re.I)
    if src == 'librosa' and m and len(beats) > 8:
        bpm = float(m.group(1))
        if abs(2 * tempo - bpm) <= 0.08 * bpm:       # librosa locked to half time (fast punk): double the grid
            mids = [(x + y) / 2 for x, y in zip(beats[:-1], beats[1:])]
            beats = sorted(beats + mids); tempo *= 2; phase *= 2; src = 'librosa-x2'
            G.log(f"beat grid: half-time detected (style says {bpm:.0f} BPM), doubled to {tempo:.1f}")
    if len(beats) > 4:
        per = float(np.median(np.diff(beats)))
        # half-time detection for fast songs is fine: we only need a regular grid
    else:
        per = 0.5
    j = {'tempo': tempo, 'beat_period': per, 'beats': beats, 'downbeat_phase': phase, 'source': src, 'duration': dur}
    G.save_json(j, cache)
    return j


def section_spans(L):
    """[(start, kind, section, section_occ, line_no)] at the start of each (section, occ) block."""
    out = []
    prev = None
    for ln in L:
        key = (ln['section'], ln['section_occ'])
        if key != prev:
            out.append((ln['start'], ln['kind'], ln['section'], ln['section_occ']))
            prev = key
    return out


def cut_list(beats, L, dur, end_start, seed, min_len=2.0, max_len=5.0, look='standard'):
    pop = look in LOOKS                     # every genre look uses the punchy music-video rhythm
    E = LOOKS[look]['edit'] if pop else {}
    if pop:
        min_len, max_len = 0.8, 4.0
    bt = beats['beats']; per = beats['beat_period']
    ph = beats.get('downbeat_phase', 0)
    bars = bt[ph::4] if len(bt) > 8 else bt
    rnd = random.Random(seed)

    def snap(t, grid, tol):
        if not grid:
            return t
        g = min(grid, key=lambda b: abs(b - t))
        return g if abs(g - t) <= tol else t
    forced = [0.0]
    for st, kind, sec, occ in section_spans(L):
        # cut slightly before the first sung word, on the nearest bar (or beat)
        t = snap(st - 0.15, bars, per * 2.1)
        t = snap(t, bt, per * 0.6)
        forced.append(t)
    forced.append(snap(end_start, bt, per))
    forced = sorted(set(round(t, 3) for t in forced if 0 <= t < dur - 1.0)) + [dur]
    # merge forced points closer than min_len
    fp = [forced[0]]
    for t in forced[1:]:
        if t - fp[-1] < min_len and t != dur:
            continue
        fp.append(t)
    if dur - fp[-2] < 1.0 and len(fp) > 2:
        fp.pop(-2)

    def kind_at(t):
        k = 'intro'
        for ln in L:
            if ln['ds'] <= t:
                k = ln['kind']
        return k
    cuts = []
    for a, b in zip(fp[:-1], fp[1:]):
        t = a
        while True:
            k = kind_at(t + 0.5)
            chorus = k in ('chorus', 'postchorus')
            lo, hi = (min_len, max_len)
            if pop and not chorus:
                lo, hi = 2.6, 5.2          # story / verse shots hold 3-5 s so they read; cuts land on bars
            if b - t <= hi:
                break
            if pop and chorus:
                # punchy, beat-snapped, mild bar preference; beats per cut depend on the look
                want = per * rnd.choice(E['chorus_beats'])
                bar_pen = 0.12
            elif pop:
                want = rnd.choice([3.0, 3.5, 4.0, 4.5])
                bar_pen = 0.4
            else:
                want = rnd.choice([2.0, 2.4, 2.8, 3.2]) if chorus else rnd.choice([2.6, 3.2, 3.8, 4.4, 4.9])
                bar_pen = 0.35
            target = t + want
            cand = [x for x in bt if t + lo <= x <= t + hi]
            barset = set(round(x, 3) for x in bars)
            nt = min(cand, key=lambda x: abs(x - target) + (0 if round(x, 3) in barset else bar_pen)) if cand else t + want
            if b - nt < lo:
                nt = snap((t + b) / 2, bt, per)
            cuts.append((t, nt)); t = nt
        cuts.append((t, b))
    if pop and E.get('build'):
        cuts = build_ups(cuts, beats, L, end_start)
    # long end-card tail is fine; split anything > 9.5 s
    out = []
    for a, b in cuts:
        while b - a > 9.5:
            out.append((a, a + 5.0)); a += 5.0
        out.append((a, b))
    return out


def chorus_cut_points(points, L, tol=1.6):
    """For each chorus block start, the nearest cut point (section starts are forced cuts snapped to a bar)."""
    out = []
    for st, kind, sec, occ in section_spans(L):
        if kind in ('chorus', 'postchorus') and points:
            c = min(points, key=lambda x: abs(x - st))
            if abs(c - st) <= tol and c not in out:
                out.append(c)
    return out


def build_ups(cuts, beats, L, end_start):
    """EDM build-up: the 2 bars before each drop (chorus) are cut every 2 beats, then every beat in the last bar."""
    bt = beats['beats']; per = beats['beat_period']
    pts = sorted(set([a for a, b in cuts] + [cuts[-1][1]]))
    for c in chorus_cut_points(pts, L):
        if c >= end_start - 0.05:
            continue
        w0 = c - 8 * per
        if w0 < 3.0:
            continue
        inb = [x for x in bt if w0 - per * 0.3 <= x < c - per * 0.5]
        if len(inb) < 6:
            continue
        new = inb[:4:2] + inb[4:]
        pts = [x for x in pts if not (inb[0] - 0.05 < x < c - 0.05)] + new
    pts = sorted(set(round(x, 3) for x in pts))
    return list(zip(pts[:-1], pts[1:]))


def pop_fx(plan, L, beats, seed, end_start, look='pop-video'):
    """Tasteful pop-video edit effects on the cut plan (in place): white flash into every chorus, a speed-up ramp on the
    shot that leads into a chorus, up to 4 half-speed slow-mo hits (bridge start, a verse hit, last chorus, outro),
    whip blurs on some verse downbeats, punch-in zooms on some chorus downbeats."""
    E = LOOKS[look]['edit']
    rnd = random.Random(seed + 7)
    bt = beats['beats']; ph = beats.get('downbeat_phase', 0)
    bars = bt[ph::4] if len(bt) > 8 else bt
    on_bar = lambda t: any(abs(t - x) < 0.06 for x in bars)
    starts = section_spans(L)
    chorus_starts = [st for st, kind, sec, occ in starts if kind in ('chorus', 'postchorus')]
    # first chorus-block start of each run of chorus sections
    near = lambda t, pts, tol=0.9: any(abs(t - p) <= tol for p in pts)
    for p in plan:
        p.setdefault('speed', 1.0); p.setdefault('fx', [])
    slow = 0
    for cs in chorus_starts:
        # the cut nearest to the start of each chorus block (section starts are forced cuts, snapped to a bar)
        i = min(range(len(plan)), key=lambda j: abs(plan[j]['t0'] - cs))
        p = plan[i]
        if abs(p['t0'] - cs) > 1.6 or p['t0'] >= end_start - 0.05 or 'flash' in p['fx']:
            continue
        p['fx'] += [f for f in E['drop_fx'] if f not in p['fx']]       # flash (+ strobe for EDM drops)
        if E['speedup'] and i > 0 and 'flash' not in plan[i - 1]['fx'] and plan[i - 1]['t0'] > 4.0 \
                and 0.8 <= plan[i - 1]['t1'] - plan[i - 1]['t0'] <= 4.2:
            plan[i - 1]['speed'] = 1.5
    # slow-mo hits
    cands = []
    bridge = [st for st, kind, sec, occ in starts if kind == 'bridge']
    if bridge:
        cands += [i for i, p in enumerate(plan) if abs(p['t0'] - (bridge[0] - 0.15)) < 0.9][:1]
    if len(chorus_starts) > 1:
        cands += [i for i, p in enumerate(plan) if abs(p['t0'] - chorus_starts[-1]) < 0.9][:1]
    verse_mid = [i for i, p in enumerate(plan) if p['kind'] == 'verse' and 'flash' not in p['fx'] and p['speed'] == 1.0
                 and 1.6 <= p['t1'] - p['t0'] <= 3.6]
    if verse_mid:
        cands.append(verse_mid[len(verse_mid) // 2])
    last = [i for i, p in enumerate(plan) if p['t1'] <= end_start + 0.05 and p['t0'] > end_start - 6 and p['speed'] == 1.0]
    if last:
        cands.append(last[-1])
    for i in dict.fromkeys(cands):
        p = plan[i]
        if slow < E['slowmo'] and p['speed'] == 1.0 and 0.8 <= p['t1'] - p['t0'] <= 6.0:
            p['speed'] = 0.5; slow += 1
    # whips and punches on downbeats (not on the flash cuts), sparing
    for i, p in enumerate(plan):
        if i == 0 or 'flash' in p['fx'] or p['t0'] >= end_start - 0.05 or p['speed'] != 1.0 or plan[i - 1]['speed'] < 1.0:
            continue
        prev_fx = plan[i - 1]['fx']
        if p['t1'] - p['t0'] < 0.75:          # build-up beats: no extra effects
            continue
        if p['kind'] in ('chorus', 'postchorus'):
            if on_bar(p['t0']) and rnd.random() < E['punch']:
                p['fx'].append('punch')
        elif p.get('story') != plan[i - 1].get('story') and rnd.random() < max(E['whip'][0], 0.5) \
                and 'whip_out' not in prev_fx and 'whip' not in prev_fx:
            # verses: whip only on a motivated cut (the story changes), otherwise clean straight cuts that let shots read
            p['fx'].append('whip'); prev_fx.append('whip_out')
    # camera feel: handheld shake (rock: some chorus shots, light; punk: anywhere) and punk fisheye shots
    for i, p in enumerate(plan):
        if p['t0'] >= end_start - 0.05 or p['speed'] < 1.0:
            continue
        chorus = p['kind'] in ('chorus', 'postchorus')
        # handheld shake: chorus energy (punk also, lightly, in some verses); story shots otherwise stay steady
        if E['shake'] and (chorus or look == 'punk') and rnd.random() < (E['shake'] if chorus else E['shake'] * 0.35):
            p['fx'].append('shake')
        if E['fisheye'] and chorus and 'punch' not in p['fx'] and p['t1'] - p['t0'] >= 1.0 and rnd.random() < E['fisheye']:
            p['fx'].append('fisheye')
    # cinematic letterbox bars on story / verse shots only (captions sit well inside them)
    for p in plan:
        if E.get('bars', True) and p['t0'] < end_start - 0.05 and p['kind'] in ('verse', 'bridge', 'prechorus'):   # incl. build-up cuts, so the bars open on the drop
            p['fx'].append('bars')
    return plan


def motion_profile(clip, cache_dir):
    cp = os.path.join(cache_dir, os.path.basename(clip) + '.motion.json')
    if os.path.exists(cp) and os.path.getmtime(cp) > os.path.getmtime(clip):
        return G.load_json(cp)
    w, h, r = 72, 128, 8
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', clip, '-map', '0:v:0', '-vf', f'fps={r},scale={w}:{h},format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2)) if len(fr) > 1 else np.zeros(1)
    vw, vh, vd = G.probe_video(clip)
    prof = {'rate': r, 'motion': d.tolist(), 'duration': vd, 'crop': band_crop(clip, vw, vh)}
    G.save_json(prof, cp)
    return prof


def band_crop(clip, vw, vh):
    """Detect flat dark letterbox bands (top/bottom) that image_edit sometimes copies from the padded reference.
    Returns 'crop=w:h:x:y' that removes them and keeps 9:16, or None."""
    w, h = 180, 320
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', clip, '-map', '0:v:0', '-vf', f'fps=2,scale={w}:{h},format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)
    if len(fr) < 3:
        return None
    mean_row = fr.mean(axis=(0, 2)); sp = fr.std(axis=2).mean(axis=0); tm = fr.mean(axis=2).std(axis=0)
    flat = (sp < 3.0) & (tm < 2.0) & (mean_row > 12) & (mean_row < 70)
    top = 0
    while top < h and flat[top]:
        top += 1
    bot = 0
    while bot < h and flat[h - 1 - bot]:
        bot += 1
    top = top if 0.025 * h <= top <= 0.2 * h else 0
    bot = bot if 0.025 * h <= bot <= 0.2 * h else 0
    if not top and not bot:
        return None
    y0 = int((top + 1) * vh / h); y1 = vh - int((bot + 1) * vh / h)
    ch = y1 - y0; cw = int(ch * 9 / 16) // 2 * 2; ch = ch // 2 * 2
    return f"crop={cw}:{ch}:{(vw - cw) // 2}:{y0}"


def best_window(prof, d, used):
    """Start time of the d-second window with most motion, penalising overlap with already used windows."""
    r = prof['rate']; m = np.array(prof['motion']); cd = prof['duration']
    best, bs = None, -1e9
    for s in np.arange(0.15, max(cd - d - 0.05, 0.15) + 1e-6, 0.25):
        a, b = int(s * r), max(int((s + d) * r), int(s * r) + 1)
        sc = float(m[a:b].mean()) if b <= len(m) else float(m[a:].mean() if a < len(m) else 0)
        ov = sum(max(0, min(s + d, ue) - max(s, us)) for us, ue in used) / d
        sc = sc * (1 - 0.85 * min(ov, 1.0)) - 0.5 * ov
        if sc > bs:
            best, bs = float(s), sc
    if best is None:
        best = 0.0
    ov = sum(max(0, min(best + d, ue) - max(best, us)) for us, ue in used) / d
    return best, ov


def assign(cuts, shots, L, story_tags, clips_dir, work, seed, look='standard', beats=None, end_start=None):
    rnd = random.Random(seed + 1)
    avail = [s for s in shots if os.path.exists(os.path.join(clips_dir, s['file']))]
    if not avail:
        raise RuntimeError('no clips available')
    prof = {s['file']: motion_profile(os.path.join(clips_dir, s['file']), work) for s in avail}
    used = {s['file']: [] for s in avail}
    usage = {s['file']: 0.0 for s in avail}

    def ctx(t):
        cur = None
        for ln in L:
            if ln['ds'] <= t:
                cur = ln
        if cur is None:
            return 'intro', 0
        for i, st in enumerate(story_tags):
            if st.get('section', '').lower() == cur['section'].lower() and st['lines'][0] <= cur['line_no'] <= st['lines'][-1] \
                    and ('occurrence' not in st or st['occurrence'] == cur['section_occ']):
                return cur['kind'], i + 1
        return cur['kind'], 0
    def line_at(t):
        cur = None
        for ln in L:
            if ln['ds'] <= t:
                cur = ln
        return (cur['section'].lower(), cur['section_occ'], cur['line_no']) if cur else None
    pre = []
    for a, b in cuts:
        kind, story = ctx((a + b) / 2)
        pre.append({'t0': round(a, 3), 't1': round(b, 3), 'kind': kind, 'story': story, 'speed': 1.0, 'fx': [],
                    'line': line_at((a + b) / 2)})
    refs = {s['file']: {(r[0].lower(), r[1], r[2]) for r in s.get('line_refs') or []} for s in avail}
    if look in LOOKS and beats:
        pop_fx(pre, L, beats, seed, end_start if end_start is not None else cuts[-1][0], look)
    plan, prev = [], None
    for (a, b), pp in zip(cuts, pre):
        d = b - a
        kind, story, cur_line = pp['kind'], pp['story'], pp.get('line')
        def mismatch(sh):
            r = refs.get(sh['file'])
            if r and cur_line:
                # cinematic plans: each shot owns the lyric lines sung over it (establishing vs payoff, which chorus)
                if cur_line in r:
                    return 0.0
                if story and sh.get('story') == story:
                    return 0.3
                if not story and kind in ('chorus', 'postchorus') and sh.get('section') == 'chorus':
                    return 0.1
            if story:
                if sh.get('story') == story:
                    return 0.0
                return 0.35 if sh.get('story') == 0 and sh.get('section') != 'intro' else 0.7
            if kind in ('chorus', 'postchorus'):
                return 0.0 if sh.get('section') == 'chorus' else (0.2 if sh.get('story') == 0 else 0.45)
            if kind == 'intro' or a < 0.5:
                return 0.0 if sh.get('section') == 'intro' else (0.25 if sh.get('story') == 0 else 0.5)
            return 0.0 if sh.get('section') == kind else (0.2 if sh.get('story') == 0 else 0.4)
        # no back-to-back repeats, except the shot that owns the lines being sung (a cut-in to a later moment of it)
        # (only on real holds; fast build-up cuts always change shot)
        pool = [sh for sh in avail if sh['file'] != prev
                or (d >= 2.0 and cur_line and cur_line in refs.get(sh['file'], ()))] or avail
        # best match first, but spread the footage: every pass through a clip's 10 s costs as much as a mismatch
        pool = sorted(pool, key=lambda sh: mismatch(sh) + 0.45 * usage[sh['file']] / max(prof[sh['file']]['duration'], 1)
                      + rnd.random() * 0.04)
        s = pool[0]
        cut_in = s['file'] == prev      # same shot again: a motivated cut-in / cut-out (alternating scale)
        sp = pp['speed']
        if d * sp > prof[s['file']]['duration'] - 0.2:      # not enough footage for a speed-up: play it normal
            sp = 1.0 if sp > 1 else sp
        dd = min(d * sp, prof[s['file']]['duration'] - 0.2)
        st, ov = best_window(prof[s['file']], dd, used[s['file']])
        used[s['file']].append((st, st + dd)); usage[s['file']] += dd
        plan.append({'t0': round(a, 3), 't1': round(b, 3), 'clip': s['file'], 'shot': s['id'], 'kind': kind, 'story': story,
                     'src_start': round(st, 2), 'src_dur': round(dd, 3), 'reuse_overlap': round(ov, 2),
                     'crop': prof[s['file']].get('crop'), 'flip': ov > 0.35 and rnd.random() < 0.6 and not cut_in,
                     'zoom': (1.0 if plan and plan[-1]['zoom'] >= 1.1 else 1.14) if cut_in else round(1.0 + (0.12 if ov > 0.35 else 0.0) * rnd.random(), 3),
                     'speed': sp, 'fx': pp['fx'], 'grade': look if look in LOOKS else None})
        prev = s['file']
    return plan


def render_segments(plan, clips_dir, segdir, threads=4):
    os.makedirs(segdir, exist_ok=True)
    # frame-exact boundaries on the output grid
    jobs = []
    for i, p in enumerate(plan):
        f0, f1 = int(round(p['t0'] * FPS)), int(round(p['t1'] * FPS))
        n = max(f1 - f0, 1)
        out = os.path.join(segdir, f"seg{i:03d}.mp4")
        vf = ['setpts=PTS-STARTPTS'] + ([p['crop']] if p.get('crop') else [])
        z = p['zoom']
        if z > 1.001:
            vf.append(f"crop=iw/{z}:ih/{z}")
        sp = p.get('speed', 1.0); fx = p.get('fx', [])
        if sp < 0.99:      # slow-mo: stretch time, then motion-interpolate back to 24 fps (at source res, cheaper)
            vf += [f'setpts={1/sp:.4f}*PTS', f'minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1']
        elif sp > 1.01:    # speed-up ramp into a chorus
            vf += [f'setpts=PTS/{sp:.4f}']
        vf += ['scale=1080:1920:flags=lanczos', 'unsharp=5:5:0.5:5:5:0', 'setsar=1']
        if p['flip']:
            vf.append('hflip')
        vf += [f'fps={FPS}']
        dsec = n / FPS
        if 'fisheye' in fx:  # barrel distortion, then crop the bent edges away
            vf += ['lenscorrection=k1=0.22:k2=0.06:i=bilinear', 'crop=iw*0.8:ih*0.8', 'scale=1080:1920:flags=bicubic']
        if 'shake' in fx:    # handheld feel: smooth drift on a slightly enlarged frame
            amp = 1.0 if p.get('grade') == 'punk' else 0.5
            vf += ['scale=1144:2034:flags=bicubic',
                   f"crop=1080:1920:x='32+{22*amp:.0f}*sin(t*6.1+{i})+{10*amp:.0f}*sin(t*13.7)':"
                   f"y='57+{28*amp:.0f}*sin(t*4.3+{i*2})+{12*amp:.0f}*sin(t*11.9)'"]
        if 'punch' in fx:  # punch-in: start 10% tighter and settle back over ~0.3 s
            vf += [f"zoompan=z='if(lt(in,8),1.10-0.0125*in,1)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS}"]
        if 'whip' in fx:   # incoming whip: heavy horizontal smear for the first 3 frames
            vf += ["avgblur=sizeX=90:sizeY=1:enable='lt(t,0.125)'", "avgblur=sizeX=40:sizeY=1:enable='between(t,0.125,0.17)'"]
        if 'whip_out' in fx:
            vf += [f"avgblur=sizeX=60:sizeY=1:enable='gte(t,{dsec - 0.09:.3f})'"]
        if p.get('grade') in LOOKS:  # per-look colour grade
            vf += LOOKS[p['grade']]['grade']
        if 'strobe' in fx:   # drop strobe: one bright frame in every three for the first half second
            vf += ["eq=brightness=0.5:saturation=0.5:enable='lt(t,0.5)*lt(mod(t,0.125),0.042)'"]
        if 'bars' in fx:     # subtle cinematic letterbox (5 % top and bottom), above the flash so the flash covers it
            vf += ['drawbox=x=0:y=0:w=iw:h=96:color=black:t=fill', 'drawbox=x=0:y=ih-96:w=iw:h=96:color=black:t=fill']
        if 'flash' in fx:
            vf += ['fade=t=in:st=0:d=0.17:color=white']
        vf += ['tpad=stop_mode=clone:stop_duration=10', 'format=yuv420p']
        cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', f"{p['src_start']:.3f}", '-i', os.path.join(clips_dir, p['clip']),
               '-map', '0:v:0', '-an', '-vf', ','.join(vf), '-frames:v', str(n), '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '15', '-r', str(FPS), out]
        jobs.append((cmd, out, n))

    def run(job):
        cmd, out, n = job
        subprocess.run(cmd, check=True)
        return out
    with ThreadPoolExecutor(threads) as ex:
        outs = list(ex.map(run, jobs))
    lst = os.path.join(segdir, 'list.txt')
    open(lst, 'w').write(''.join(f"file '{o}'\n" for o in outs))
    return lst, sum(j[2] for j in jobs)


def final_render(seg_list, audio, ass, out, dur):
    part = out + '.part.mp4'
    cmd = ['ffmpeg', '-v', 'error', '-stats', '-y', '-f', 'concat', '-safe', '0', '-i', seg_list, '-i', audio,
           '-filter_complex', f"[0:v]tpad=stop_mode=clone:stop_duration=2,ass={ass},format=yuv420p[v]",
           '-map', '[v]', '-map', '1:a:0', '-t', f"{dur:.3f}",
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-maxrate', '6M', '-bufsize', '12M',
           '-profile:v', 'high', '-level', '4.1', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', str(FPS * 2),
           '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
           '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-f', 'mp4', part]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    os.replace(part, out)
