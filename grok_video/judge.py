"""P2 Opus judge-and-reroll loop + the post-run judge (see README "Judge").

In-run (slop_real.generate_media, after generation): tile every still into labelled contact sheets with the cast
portraits, one headless Opus call flags bad stills -> up to MAX_STILL_REROLLS rerolls (new prompt "fix: <reason>"),
then 3 frames per clip -> one call -> up to MAX_CLIP_REROLLS clip rerolls; rerolls are re-judged once and anything
still failing goes into work/qa_exclude.json (the edit leaves it out; a failed clip falls back to its still).
Every step is FAIL-OPEN: an Opus error, timeout, missing time or missing budget just skips the step.
Post-run (grok_video.finish): a detached Opus call scores the finished video and writes <day>/judge_<style>.md. It never
applies anything. Switches: GV_JUDGE=0 (off), GV_JUDGE_FAIL=opus (test fail-open), GV_POST_JUDGE=0."""
import json, os, re, shutil, subprocess, sys, time
import common_gv as G

MAX_STILL_REROLLS = 15
MAX_CLIP_REROLLS = 4
PER_SHEET = 20
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FAILS = ("cast off-model (wrong hair, age, gender or face vs the portrait; ); ANY robot, android, robot animal, mascot or toy character in frame; "
         "a cast member who is not in the shot's cast list (especially A); clones of A in a crowd; mangled hands, gloves "
         "or merged bodies; a person wearing another character's head; mugging / sitcom faces; a chorus crowd shot without "
         "the signature pose; readable or garbled text, logos or captions in the picture; the picture does not show the "
         "intended scene at all")
SCHEMA = {"type": "object", "properties": {"fails": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["id", "reason"]}}}, "required": ["fails"]}


def _font(n):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT, n)
    except OSError:
        return ImageFont.load_default()


def tile(items, path, cols=5, w=216, h=384):
    """items: [(image path, label)] -> one labelled sheet (jpg)."""
    from PIL import Image, ImageDraw
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * (h + 26)), 'black')
    d = ImageDraw.Draw(sheet)
    f = _font(17)
    for i, (p, lab) in enumerate(items):
        x, y = (i % cols) * w, (i // cols) * (h + 26)
        try:
            im = Image.open(p).convert('RGB'); im.thumbnail((w - 4, h - 4))
            sheet.paste(im, (x + 2, y + 26))
        except Exception:
            pass
        d.text((x + 3, y + 3), lab[:24], fill=(255, 230, 0), font=f)
    sheet.save(path, quality=85)
    return path


def clip_frames(clip, outdir, tag):
    """3 frames (start, middle, end) of a clip side by side -> one image."""
    from PIL import Image
    dur = G.duration(clip) or 3.0
    ims = []
    for n, t in enumerate((0.3, dur / 2, max(0.3, dur - 0.25))):
        f = os.path.join(outdir, f'{tag}_{n}.jpg')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', clip, '-frames:v', '1', '-vf', 'scale=216:-2', f],
                       check=False, timeout=60)
        if os.path.exists(f):
            ims.append(Image.open(f).convert('RGB'))
    if not ims:
        return None
    strip = Image.new('RGB', (sum(i.width for i in ims), max(i.height for i in ims)))
    x = 0
    for i in ims:
        strip.paste(i, (x, 0)); x += i.width
    p = os.path.join(outdir, f'{tag}.jpg'); strip.save(p, quality=85)
    return p


def _call(work, name, sheets, rows, extra, timeout):
    if os.environ.get('GV_JUDGE_FAIL') == 'opus':
        raise RuntimeError('forced test failure (GV_JUDGE_FAIL=opus)')
    import slop_opus as SO
    jd = os.path.join(work, 'judge'); os.makedirs(jd, exist_ok=True)
    names = [os.path.basename(s) for s in sheets]
    prompt = (f"You are the QA judge of a photoreal music video. Use the Read tool to look at every image: {', '.join(names)}. "
              f"{extra}\nFAIL a shot ONLY for one of these clear problems: {FAILS}. Grain, flash, film look, blur and odd but "
              "intentional absurd scenes are fine. Be strict on cast identity and text, lenient otherwise; normally 0-25% of "
              "shots fail. 'reason' under 12 words, 'id' exactly as labelled.\n\nSHOTS (id | cast | intended scene):\n"
              + '\n'.join(rows) + '\n\nReply with JSON only: {"fails": [{"id": "...", "reason": "..."}]}')
    pf = os.path.join(jd, f'{name}_prompt.txt'); open(pf, 'w').write(prompt)
    res, meta = SO.run_claude(pf, jd, SCHEMA, timeout, tools='Read', effort='low')
    fails = {str(f['id']).strip(): f.get('reason', '') for f in (res or {}).get('fails') or [] if f.get('id')}
    G.save_json({'fails': fails, 'secs': meta.get('secs')}, os.path.join(jd, f'{name}.json'))
    return fails


def _cast_tiles(work):
    cd = os.path.join(work, 'cast')
    return [(os.path.join(cd, f), f'CAST {f[0]}') for f in sorted(os.listdir(cd)) if f.endswith('.jpg')] if os.path.isdir(cd) else []


def _exclude(work, names):
    p = os.path.join(work, 'qa_exclude.json')
    cur = G.load_json(p) or []
    cur = sorted(set(cur) | set(names))
    G.save_json(cur, p)
    return cur


def judge_stills(P, ids=None, name='stills'):
    work = P['work']
    jd = os.path.join(work, 'judge'); os.makedirs(jd, exist_ok=True)
    js = [j for j in P['stills'] if os.path.exists(j['out']) and (ids is None or j['id'] in ids)]
    if not js:
        return {}
    cast = _cast_tiles(work)
    sheets, rows = [], []
    for n in range(0, len(js), PER_SHEET):
        part = js[n:n + PER_SHEET]
        sheets.append(tile(cast + [(j['out'], j['id'] + ' ' + ''.join(j.get('cast') or [])) for j in part],
                           os.path.join(jd, f'{name}_sheet{n // PER_SHEET + 1:02d}.jpg')))
    for j in js:
        body = re.sub(r'\s+', ' ', j['prompt'].split('Scene: ')[-1])[:170]
        rows.append(f"{j['id']} | {''.join(j.get('cast') or []) or '-'} | {body}")
    return _call(work, name, sheets, rows, "Each sheet starts with the CAST portraits (CAST A..), then the stills labelled "
                 "'<id> <cast letters>'.", 240)


REALISM = ("AI-SLOP TELLS (reject): plastic/waxy sheen on skin, metal or leather; over-smooth airbrushed faces or uncanny "
           "symmetrical faces; impossible anatomy (extra or fused limbs, legs, hooves, fingers); ANY robot, android, humanoid machine, robot animal, mascot or toy figure (always reject); CGI sheen or "
           "video-game props; uncanny or doll-like faces, dead eyes, identical faces; over-saturated colour; symmetrical "
           "centred poster framing; props (glossy, too clean, rounded toy proportions); over-smooth even lighting with no motivated "
           "source; HDR glow, bloom halos, fake bokeh; everything brand new and spotless; floating objects; melted or "
           "mirrored geometry; illustration / 3D-render look; letters or monograms on clothes, saddle cloths or props; wrong or garbled digits where the intent names painted numerals (those exact numerals are allowed)")
CRAFT = ("REAL FILM CRAFT (rewrite toward): practical props and real materials with wear (scuffed real leather harness, "
         "brass buckles with tarnish, dust, mud, sweat, fingerprints, frayed straps); no robots at all: replace any robot with real people at real screens, offices, labs or server rooms; real people with imperfect skin, pores, stubble, crow's feet, sweat; motivated light from "
         "a named source (low sun, sodium lamp, flood light, window); a named lens and stock (35mm spherical at f/2.8, "
         "Kodak Vision3 500T, or the look's camcorder); natural imperfect framing; texture in every surface.")
GSCHEMA = {"type": "object", "properties": {"fails": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "reason": {"type": "string"}, "prompt": {"type": "string"}},
    "required": ["id", "reason", "prompt"]}}}, "required": ["fails"]}
MAX_GATE_REROLLS = 30


def realism_gate(P, args, status, gen_spent):
    """13 Oct (the owner: "the harnesses are quite AI-slop-like ... review reference images before video"): after the stills
    and BEFORE any clip, Opus reviews every still against its shot intent for photorealism and cinematic craft plus the
    usual QA fails, rewrites failing prompts toward real film craft, rerolls them (budget-capped), re-checks once, and
    excludes what still fails; clips are only made from passing stills (slop_real.generate_media). Fail-open."""
    import cine_real as CR
    import slop_opus as SO
    rep = {'on': True}
    work = P['work']
    if os.environ.get('GV_REALISM') == '0' or args.skip_gen:
        return {'on': False}
    try:
        js = [j for j in P['stills'] if os.path.exists(j['out'])]
        jd = os.path.join(work, 'judge'); os.makedirs(jd, exist_ok=True)
        cast = _cast_tiles(work)
        sheets = []
        for n in range(0, len(js), PER_SHEET):
            part = js[n:n + PER_SHEET]
            sheets.append(tile(cast + [(j['out'], j['id'] + ' ' + ''.join(j.get('cast') or [])) for j in part],
                               os.path.join(jd, f'realism_sheet{n // PER_SHEET + 1:02d}.jpg')))
        rows = [f"{j['id']} | {''.join(j.get('cast') or []) or '-'} | {re.sub(chr(10), ' ', j['prompt'].split('Scene: ')[-1])[:260]}" for j in js]
        names = [os.path.basename(x) for x in sheets]
        prompt = (f"You are a feature-film cinematographer and VFX supervisor doing a REALISM GATE on the stills of a photoreal "
                  f"music video before they are animated. Use the Read tool on every image: {', '.join(names)}. Each sheet "
                  "starts with the CAST portraits, then stills labelled '<id> <cast letters>'.\n"
                  f"Reject a still if it shows {REALISM}; or the usual QA fails: {FAILS}. A still that would pass as a frame "
                  "from a real film or real camcorder tape PASSES even if gritty, grainy or absurd. Expect 15-40% rejects "
                  "on a first pass; be honest, not lenient.\nFor every reject give 'reason' (under 14 words) and a REWRITTEN "
                  f"'prompt' (30-60 words) for the same shot intent, same cast letters and location, rewritten toward {CRAFT} "
                  "Never add text or letters (the only exception: big painted numerals the intent names, e.g. \"41\" and \"61\", kept exactly and checked for correct digits). Keep the action that acts out the line.\n\nSHOTS (id | cast | intended scene):\n"
                  + '\n'.join(rows) + '\n\nReply with JSON only.')
        pf = os.path.join(jd, 'realism_prompt.txt'); open(pf, 'w').write(prompt)
        res, meta = SO.run_claude(pf, jd, GSCHEMA, 420, tools='Read', effort='medium')
        fails = {str(f['id']).strip(): f for f in (res or {}).get('fails') or [] if f.get('id')}
        G.save_json({'fails': fails, 'secs': meta.get('secs')}, os.path.join(jd, 'realism.json'))
        rep['rejected'] = len(fails)
        G.log(f"realism gate: {len(fails)} of {len(js)} stills rejected ({meta.get('secs')}s)")
        by_id = {j['id']: j for j in js}
        firsts = {h['first_frame'] for h in P['heroes']}
        cand = [by_id[i] for i in fails if i in by_id]
        cand.sort(key=lambda j: (j['out'] not in firsts, j['id']))      # clip first frames first
        cap = args.real_max_pct
        room = cap - 0.8 - (gen_spent or 0) - 3.0                      # keep ~3 % for the clips
        n = max(0, min(MAX_GATE_REROLLS, len(cand), int(room / CR.STILL_COST)))
        jobs = []
        for j in cand[:n]:
            r = _swap(j)
            body = fails[j['id']]['prompt'].strip()
            pre = j['prompt'].split('Scene: ')[0] if 'Scene: ' in j['prompt'] else ''
            import slop_real as SR
            tail = f" {(P.get('LK') or {}).get('prompt', '')} {SR.NO_TEXT}"
            r['prompt'] = (pre + 'Scene: ' + body + tail) if pre else (body + tail)
            jobs.append(r)
        if jobs:
            ne = sum(1 for r in jobs if r['kind'] == 'edit')
            _reroll(jobs, work, {'gen': len(jobs) - ne + 3, 'edit': ne + 3, 'i2v': 0}, 'realism_stills', None, 300)
            fixed = [r['id'] for r in jobs if _commit(r)]
            for r in jobs:
                if r['id'] in fixed:
                    by_id[r['id']]['prompt'] = r['prompt']
            rep['rerolled'] = fixed
            G.log(f"realism gate: rerolled {len(fixed)}/{len(jobs)}")
            again = judge_stills(P, set(fixed), 'realism_recheck') if fixed else {}
            bad = [i for i in fixed if i in again] + [i for i in fails if i not in fixed]
        else:
            bad = list(fails)
        bad_out = [os.path.basename(by_id[i]['out']) for i in bad if i in by_id]
        if bad_out:
            _exclude(work, bad_out)
        rep['excluded'] = bad_out
        rep['blocked_clips'] = sorted(h['id'] for h in P['heroes'] if os.path.basename(h['first_frame']) in set(bad_out))
        G.log(f"realism gate: {len(bad_out)} stills left out; {len(rep['blocked_clips'])} clips will not be made from them")
    except Exception as e:
        rep['error'] = repr(e)[:300]
        G.log(f"WARNING: realism gate skipped: {e!r}"[:300])
    status['realism_gate'] = rep
    return rep


def judge_clips(P, ids=None, name='clips'):
    work = P['work']
    jd = os.path.join(work, 'judge', 'frames'); os.makedirs(jd, exist_ok=True)
    hs = [h for h in P['heroes'] if os.path.exists(h['out']) and (ids is None or h['id'] in ids)]
    items, rows = [], []
    for h in hs:
        p = clip_frames(h['out'], jd, h['id'])
        if p:
            items.append((p, h['id']))
            st = next((j for j in P['stills'] if j['out'] == h.get('first_frame')), {})
            body = re.sub(r'\s+', ' ', (st.get('prompt') or h['prompt']).split('Scene: ')[-1])[:150]
            rows.append(f"{h['id']} | {''.join(st.get('cast') or []) or '-'} | {body}")
    if not items:
        return {}
    cast = _cast_tiles(work)
    sheets = []
    for n in range(0, len(items), 8):
        sheets.append(tile(cast + items[n:n + 8], os.path.join(work, 'judge', f'{name}_sheet{n // 8 + 1:02d}.jpg'),
                           cols=4, w=648, h=384))
    return _call(work, name, sheets, rows, "Each sheet starts with the CAST portraits, then clips: each clip is 3 frames "
                 "(start, middle, end) side by side, labelled with its id. Also FAIL a clip if a person or robot morphs "
                 "into something else between frames.", 240)


def _reroll(jobs, work, kind_budget, tag, deadline, timeout):
    import real_gen
    B = real_gen.Batcher(work, kind_budget, batch_size=3 if tag.endswith('stills') else 2, max_parallel=4, start_gap=6.0,
                         tag=tag, timeout=timeout, deadline=deadline)
    B.no_salvage = True
    return B.run(jobs)


def _swap(j, tmp_key='out'):
    """Generate to <out>.reroll.<ext>; on success keep the original as <name>.orig.<ext> and put the new one in place."""
    base, ext = os.path.splitext(j[tmp_key])
    return dict(j, out=f"{base}.reroll{ext}", _final=j[tmp_key], _orig=f"{base}.orig{ext}")


def _commit(r):
    if os.path.exists(r['out']) and os.path.getsize(r['out']) > 1000:
        shutil.move(r['_final'], r['_orig']) if os.path.exists(r['_final']) else None
        shutil.move(r['out'], r['_final'])
        return True
    return False


def loop(P, args, status, gen, stills_done=False):
    """The whole in-run judge-and-reroll loop. Never raises."""
    import cine_real as CR
    rep = {'on': True}
    status['judge_loop'] = rep
    if os.environ.get('GV_JUDGE') == '0' or args.skip_gen:
        rep['on'] = False
        return rep
    work, cap = P['work'], args.real_max_pct
    dl = getattr(args, 'deadline', None)
    stop = (dl - CR.RENDER_RESERVE_S) if dl else None
    sec = P.get('sec') or 3

    def left():
        return None if not stop else stop - time.time()

    def spent():
        try:
            from real_gen_usage import usage_pct
            u = usage_pct()
            if u is not None and gen.get('usage_start') is not None and u >= gen['usage_start']:
                return float(u - gen['usage_start'])
        except Exception:
            pass
        return gen.get('spent_pct') if gen.get('spent_pct') is not None else None

    def room(cost):
        sp = spent()
        rep.setdefault('spent_checks', []).append(sp)
        return sp is None or sp + cost <= cap - 0.8 + 1e-9      # same 0.8 % margin as the generator
    t0 = time.time()
    try:
        # ---- stills (already gated by realism_gate when stills_done)
        if stills_done:
            rep['stills'] = 'done by the realism gate'
        elif left() is not None and left() < 7 * 60:
            rep['stills'] = 'skipped: not enough time'
        else:
            fails = judge_stills(P)
            rep['still_fails'] = fails
            G.log(f"judge: {len(fails)} of {sum(1 for j in P['stills'] if os.path.exists(j['out']))} stills flagged")
            firsts = {h['first_frame']: h for h in P['heroes']}
            by_id = {j['id']: j for j in P['stills']}
            cand = [by_id[i] for i in fails if i in by_id]
            # stills shown on screen first (not first frames of a clip that exists), then clip first frames
            cand.sort(key=lambda j: (j['out'] in firsts and os.path.exists(firsts[j['out']]['out']), j['id']))
            n = min(MAX_STILL_REROLLS, len(cand))
            while n and not room(n * CR.STILL_COST):
                n -= 1
            jobs = []
            for j in cand[:n]:
                r = _swap(j)
                r['prompt'] = j['prompt'] + f" (fix: {fails[j['id']][:80]}; the people must match the references exactly)"
                jobs.append(r)
            if jobs and (left() is None or left() > 5 * 60):
                ne = sum(1 for r in jobs if r['kind'] == 'edit')
                _reroll(jobs, work, {'gen': len(jobs) - ne + 2, 'edit': ne + 2, 'i2v': 0}, 'judge_stills',
                        stop, 300)
                fixed = [r['id'] for r in jobs if _commit(r)]
                rep['still_rerolled'] = fixed
                G.log(f"judge: rerolled {len(fixed)}/{len(jobs)} stills")
                again = judge_stills(P, set(fixed), 'stills_recheck') if fixed and (left() is None or left() > 5 * 60) else {}
                bad = [os.path.basename(by_id[i]['out']) for i in again if i in by_id and i in fixed]
                if bad:
                    rep['still_excluded'] = _exclude(work, bad) and bad
                    G.log(f"judge: {len(bad)} rerolled stills still fail -> left out")
        # ---- clips
        if left() is not None and left() < 9 * 60:
            rep['clips'] = 'skipped: not enough time'
        else:
            cf = judge_clips(P)
            rep['clip_fails'] = cf
            G.log(f"judge: {len(cf)} of {sum(1 for h in P['heroes'] if os.path.exists(h['out']))} clips flagged")
            hb = {h['id']: h for h in P['heroes']}
            cand = [hb[i] for i in cf if i in hb and hb[i].get('kind') == 'r2v']
            clip_cost = CR.CLIP_COST * sec / 4
            n = min(MAX_CLIP_REROLLS, len(cand))
            while n and not room(n * clip_cost):
                n -= 1
            jobs = []
            for h in cand[:n]:
                r = _swap(h)
                r['prompt'] = h['prompt'] + f" Fix: {cf[h['id']][:80]}; nobody changes identity or species."
                jobs.append(r)
            fixed = []
            if jobs and (left() is None or left() > 7 * 60):
                _reroll(jobs, work, {'gen': 0, 'edit': 0, 'i2v': 0, 'r2v': len(jobs) + 1}, 'judge_clips', stop, 600)
                fixed = [r['id'] for r in jobs if _commit(r)]
                rep['clip_rerolled'] = fixed
                G.log(f"judge: rerolled {len(fixed)}/{len(jobs)} clips")
            again = judge_clips(P, set(fixed), 'clips_recheck') if fixed and (left() is None or left() > 4 * 60) else {}
            # leave out every clip that still fails: flagged and not rerolled, or rerolled and failing again
            bad = [os.path.basename(hb[i]['out']) for i in cf if i in hb and i not in fixed] + \
                  [os.path.basename(hb[i]['out']) for i in again if i in hb and i in fixed]
            if bad:
                _exclude(work, bad)
                rep['clip_excluded'] = bad
                G.log(f"judge: {len(bad)} clips left out (their stills stand in)")
    except Exception as e:                                       # FAIL-OPEN
        rep['error'] = repr(e)[:300]
        G.log(f"WARNING: judge loop skipped/stopped: {e!r}"[:300])
        status['warnings'].append('judge loop skipped (Opus error/timeout); the edit uses everything made')
    rep['secs'] = round(time.time() - t0)
    rep['spent_after'] = spent()
    return rep


# ------------------------------------------------------------------------------------------------ post-run judge
POST_DIMS = ("hook in the first 2 s, lyric literalness, escalation and arc, cast consistency, cinematography and variety, "
             "cut rhythm on the beat, realism and artifacts, text slams and story cards, humour and absurdity, ending")


def post_run(day, video, tag='slopcore', work=None):
    """Detached: never blocks or breaks the run. Writes <day>/judge_<tag>.md (scores, gaps, proposals; nothing applied)."""
    if os.environ.get('GV_POST_JUDGE') == '0' or not os.path.exists(video):
        return None
    dst = os.path.dirname(os.path.abspath(video))         # report beside the video (the day folder in the routine)
    log = os.path.join(dst, f'judge_{tag}.log')
    cmd = [sys.executable, os.path.abspath(__file__), 'post', day, video, tag, work or '']
    try:
        p = subprocess.Popen(cmd, stdout=open(log, 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        G.log(f"post-run judge started (pid {p.pid}) -> {os.path.join(dst, f'judge_{tag}.md')}")
        return p.pid
    except Exception as e:
        G.log(f"WARNING: post-run judge not started: {e!r}"[:200])
        return None


def _post_main(day, video, tag, work=''):
    import slop_opus as SO
    dst = os.path.dirname(os.path.abspath(video))
    jd = os.path.join(dst, f'judge_{tag}'); os.makedirs(jd, exist_ok=True)
    subprocess.run(['nice', '-n', '15', 'ffmpeg', '-v', 'error', '-y', '-i', video, '-vf',
                    "fps=2,scale=180:-1,drawtext=fontfile=" + FONT + ":text='%{pts\\:hms}':x=4:y=4:fontsize=16:"
                    "fontcolor=yellow:box=1:boxcolor=black,tile=10x5", os.path.join(jd, 'sheet_%02d.jpg')],
                   check=False, timeout=600)
    sheets = sorted(f for f in os.listdir(jd) if f.startswith('sheet_'))
    work = work or next((os.path.join(day, d) for d in sorted(os.listdir(day)) if d.startswith('work_') and os.path.isdir(os.path.join(day, d))), day)
    T = os.path.dirname(os.path.abspath(__file__))
    hl = os.path.exists(os.path.join(day, 'headline.json'))
    nv = (not hl) and os.path.exists(os.path.join(day, 'treatment.json'))
    mode = 'headline' if hl else 'narrative' if nv else 'v5'
    prefs = ("every shot literally acts out the sung line inside the story that line is about; Verse 1 = the main "
             "story told literally, Verse 2 = 2-3 secondary stories each with its own mini scene; the ONLY text is: the "
             "title in the hook, one headline card, a synced caption for EVERY sung line (wanted, not a fault; bigger "
             "style on the chorus hook), a bottom news ticker that names the story being sung (@handle + fact; check it "
             "changes when the story changes and is spelled right) and credits; the main story's key numbers appear "
             "in-world as painted figures; the bridge opens on a cut to black or freeze then the payoff; the outro "
             "punchline is done by the character the lyric names; one consistent robot design; bridge "
             "surprise; deadpan punchline outro; escalating chorus; gritty look per genre; 2-3 on-model Pip cameos; "
             "credits only with the sung stories' handles; no fake text" if hl else
             "one musical story; the only text is the title, the chorus hook line and in-world text; escalating chorus "
             "motif; continuity of cast and locations; gritty look; 2-3 Pip cameos; credits with handles" if nv else
             "every shot literally acts out the sung line; verse news cards that match the story being sung; escalating "
             "chorus callbacks; gritty look per genre; deadpan cast; sparse giant word slams (hook words in the chorus); "
             "2-3 on-model Pip cameos; credits with handles; no fake text")
    extra = ("{day}/headline.md (the song plan)" if hl else "{day}/treatment.md" if nv else
             "{work}/story_cards.json (if present)").format(day=day, work=work)
    sot = ("\n0) SOUND-OFF TEST first: looking only at the contact sheets (ignore the lyrics), name the main story "
           "in one sentence, then compare with the plan: PASS / PARTIAL / FAIL, and list which secondary stories are "
           "identifiable.") if hl else ''
    prompt = f"""You are the LLM judge for our daily slopcore AI-news music video. Use the Read tool; DO NOT edit anything.
Read: contact sheets {', '.join(sheets)} (2 fps, timestamps burned in) in this folder; {day}/lyrics.txt, {day}/style.txt,
{day}/stories.md, {work}/script.md, {extra}, {work}/judge/*.json (in-run QA, if present);
references /workspace/slopcore/analysis.md and /workspace/slopcore/vibe.md and 3 of /workspace/slopcore/sheets/0[1-8]_*_sheet01.jpg;
current prompts {T}/prompts/opus_director_{mode}.txt and {T}/prompts/opus_doctor_{mode}.txt.
the owner's standing preferences: {prefs}.
Write markdown:{sot} 1) scores 1-10 vs the best references with one-line reasons: {POST_DIMS}; overall. 2) top 5 gaps with
timestamps. 3) up to 5 ranked, specific, minimal proposals (exact prompt diff text or precise workflow change) with the
estimated Grok meter % change per run (cap 7.5%). These are proposals only; the owner approves before anything changes.
Output ONLY the report."""
    pf = os.path.join(jd, 'prompt.txt'); open(pf, 'w').write(prompt)
    out = os.path.join(dst, f'judge_{tag}.md')
    try:
        cmd = [SO.CLAUDE, '-p', prompt, '--model', 'opus', '--no-session-persistence', '--tools', 'Read',
               '--add-dir', '/workspace/slopcore', '--add-dir', day, '--add-dir', T, '--add-dir', work]
        r = subprocess.run(cmd, cwd=jd, env=SO._env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1500)
        if r.returncode == 0 and r.stdout.strip():
            open(out, 'w').write(f"<!-- post-run judge {time.strftime('%Y-%m-%d %H:%M')} {os.path.basename(video)}; "
                                 "proposals only, nothing applied -->\n" + r.stdout)
            print(f"judge written: {out}")
        else:
            print(f"judge failed rc={r.returncode}: {(r.stderr or r.stdout)[-400:]}")
    except Exception as e:
        print(f"judge failed: {e!r}")


if __name__ == '__main__':
    if len(sys.argv) >= 5 and sys.argv[1] == 'post':
        _post_main(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else '')
