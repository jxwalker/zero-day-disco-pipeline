"""slopcore style (cine-real v2) pipeline pieces: jobs (cast portraits -> scene stills as image_edit from the cast ->
short reference_to_video clips), Pip toy cameos from the locked reference, the motion-first edit and the render.
Dispatched from cine_real.prepare / generate_media / edit_and_render when --style slopcore."""
import json
import subprocess
import math, os, random, re, time
import common_gv as G
import real_plan as RP
import slop_plan as SP
import real_gen
import real_render as RR
import cine_real as CR

NO_TEXT = ("Absolutely no text anywhere: no letters, numbers, writing, signs, labels, captions, logos, documents, receipts "
           "or readable screens. Original people and designs only, no lookalikes of celebrities, real people or famous "
           "characters. No robots, androids, humanoid machines, robot animals, mascots or toys. Natural, correct faces and "
           "hands. Shot as REAL live-action cinema on a real 35mm/50mm lens, never CGI: practical props and real "
           "materials with wear, believable real locations, "
           "imperfect real skin with pores, motivated light from a real source, real lens optics; no plastic sheen, "
           "no airbrushed faces, no toy-like or video-game look, no bloom, no HDR, no over-saturation, "
           "muted true-to-life colour, visible film grain, off-centre natural composition, not symmetrical.")
NO_PIP = os.environ.get('GV_PIP', '0') != '1'          # 14 Oct (the owner): Pip and all robots retired
PIP_DESC = ("this exact character as a small physical collectible vinyl toy figure, exactly the same design, proportions "
            "and colours: white egg-shaped body, two tall white bunny ears with pink insides, a thin antenna with a small "
            "yellow ball, a dark-navy face screen with glowing cyan closed happy arc eyes (^ ^) and pink blush, a pink "
            "heart on the chest, short stubby legs with round feet. Nothing on its head or face, nothing added to it.")


TOY = re.compile(r"(small |little )?(white )?(vinyl )?(toy robot|vinyl toy|mascot toy|robot toy)( with bunny ears)?", re.I)


def cast_map(plan):
    return {c['id'].strip().upper()[:1]: c for c in (plan.get('cast') or [])[:4] if c.get('id') and c.get('description')}


def pip_prompt(scene, LK):
    return (f"Turn {PIP_DESC} Place the toy in a real photographed scene: {scene} The toy is small in the frame, upright, "
            "in sharp focus, real light falling on its glossy vinyl; the people and place around it are real and "
            f"unposed. {LK['prompt']} {NO_TEXT}")


def pip_clip(cid, first, out, seg, sec):
    return {'id': cid, 'kind': 'r2v', 'first_frame': first, 'image': first, 'duration': sec, 'resolution': '720p',
            'aspect': '9:16', 'out': out, 'seg': seg, 'pri': -1,
            'prompt': (f"Continue this exact photoreal shot for {sec} seconds: the small vinyl toy stays completely still "
                       "and unchanged in shape, face and colour (it is a static toy, it never moves or morphs); only the "
                       "camera drifts in slowly by hand and the people and background around it move naturally. Same "
                       "look, no text.")}


def no_text(body):
    """NO_TEXT, except the key numbers a shot shows as big physical painted figures (13 Oct: 41 vs 61 never appeared)."""
    nums = re.findall(r'painted (?:wooden |metal |tin )?(?:numerals?|figures?|numbers?)\s+"?(\d{1,3}%?)"?(?:\s+(?:and|vs\.?)\s+"?(\d{1,3}%?)"?)?', body, re.I)
    keep = [n for t in nums for n in t if n][:2]
    if not keep:
        return NO_TEXT
    return (f"The ONLY marks allowed are the big hand-painted figures {' and '.join(keep)} exactly as written, crisp and "
            "physically painted on the object; otherwise " + NO_TEXT[0].lower() + NO_TEXT[1:])


def robot_refs(body, who, cast):
    """13 Oct: robot design drifted when a prompt said 'the robot horse' without its letter: pin the lettered robot."""
    if not re.search(r'\brobot', body, re.I):
        return []
    bots = [k for k, c in cast.items() if re.search(r'\brobot', (c.get('role', '') + ' ' + c.get('description', '')), re.I)]
    if any(k in who for k in bots):
        return []
    return [k for k in bots if re.search(rf'\b{k}\b', body)][:1] or bots[:1]


def scene_prompt(body, who, cast, LK, force_gen=False):
    """who: cast ids in this image. Returns (prompt, kind, refs)."""
    who = list(who) + [k for k in cast if k != 'A' and k not in who and re.search(rf'\b{k}\b', body)]  # letter used but not listed
    who += robot_refs(body, who, cast)
    refs = [k for k in who if k in cast][:2]
    if refs and not force_gen:
        names = '; '.join(f"{k} = the person in reference image {i + 1} ({cast[k]['role']})" for i, k in enumerate(refs))
        head = (f"Photoreal new scene with the SAME person(s) from the reference image(s): keep each face, hair, age, build "
                f"and clothes exactly. {names}. Scene: ")
        return head + body + f" {LK['prompt']} {no_text(body)}", 'edit', refs
    desc = ' '.join(f"{k} = {c['description']}." for k, c in cast.items() if k in who)   # no regex for A: "A concrete..." is an article
    return (desc + ' ' if desc else '') + body + f" {LK['prompt']} {no_text(body)}", 'gen', []


def load_cast_refs(day):
    """Per-folder real-likeness cast (`cast_refs.json`, consented private videos only). NEVER used for daily folders:
    the daily runs keep the no-real-people rule. Returns {letter: {name, role, description, images[abs paths]}} or {}."""
    import tone as T
    f = os.path.join(day, 'cast_refs.json')
    if not os.path.exists(f) or T.is_daily(day):
        return {}
    d = G.load_json(f, {}) or {}
    out = {}
    for k, c in (d.get('cast') or {}).items():
        imgs = [x if os.path.isabs(x) else os.path.join(day, x) for x in c.get('images') or []]
        imgs = [x for x in imgs if os.path.exists(x)]
        if imgs and c.get('description'):
            out[k.strip().upper()[:1]] = dict(c, images=imgs)
    return out


CAST_REFS = {}


def cast_block():
    """Planner text for the real-likeness cast ('' when none)."""
    if not CAST_REFS:
        return ''
    rows = '\n'.join(f"- {k} = {c.get('name') or k}: {c.get('role') or ''}. Use exactly this description in the cast JSON: "
                     f"{c['description']}" + (f" Appears in at most {c['max_lines']} lines (a cameo)." if c.get('max_lines') else '')
                     for k, c in CAST_REFS.items())
    return ("\n\nREAL CAST (a consented exception for this private gift video only; their faces come from real photos): "
            "these letters are real people, shown flattering, natural and happy (mixed natural expressions when the tone is playful). The no-real-people rule still "
            "applies to everyone else (all other people are original). This overrides the original-people rule for these letters only.\n" + rows + "\n")


def build_jobs(plan, slots, work, LK, sec):
    import tone as T
    cast = cast_map(plan)
    for k, c in CAST_REFS.items():                 # real-likeness cast: the folder's description wins over the planner's
        if k in cast:
            cast[k] = dict(cast[k], description=c['description'], role=c.get('role') or cast[k].get('role'))
    cast_jobs = []
    for k, c in cast.items():
        out = os.path.join(work, 'cast', f'{k}.jpg')
        if k in CAST_REFS:
            cast_jobs.append({'id': f'cast{k}', 'kind': 'edit', 'aspect': '9:16', 'out': out,
                              'images': CAST_REFS[k]['images'][:2],
                              'prompt': ("Photoreal casting reference photo, vertical 9:16, of the SAME real person as in the "
                                         "reference photo(s): keep her/his face, eyes, nose, smile, hair colour and length "
                                         f"exactly, a faithful and flattering likeness. {c['description']} Waist-up, facing "
                                         + ("the camera, a relaxed, confident, warm half-smile, standing in a real place in natural daylight. " if T.CURRENT.get('tone') == 'playful' else "the camera, a big natural warm happy smile, relaxed, standing in a bright sunny place, soft daylight. ")
                                         + f"{LK['prompt']} {NO_TEXT}")})
        else:
            cast_jobs.append({'id': f'cast{k}', 'kind': 'gen', 'aspect': '9:16', 'out': out,
                              'prompt': (f"Photoreal casting reference photo, vertical 9:16: {c['description']} Waist-up, "
                                         f"facing the camera, natural expression, standing in an ordinary real corridor, "
                                         f"soft daylight. {LK['prompt']} {NO_TEXT}")})
    segs = {s['seg']: s for s in plan['segments']}
    stills, heroes = [], []
    toy_segs = set()
    for si, sl in enumerate(slots):
        imgs = ((segs.get(sl['seg']) or {}).get('images') or [])[:sl['images']]
        sl['plan_images'] = imgs
        sl['clip_files'] = []
        for k, im in enumerate(imgs):
            is_clip = im['_clip'] if '_clip' in im else k < sl.get('clips', 0)
            out = os.path.join(work, 'stills', f"s{si:02d}_{k}.jpg")
            who = [str(x).strip().upper()[:1] for x in (im.get('cast') or [])]
            if NO_PIP and TOY.search(im['prompt']):
                im = dict(im, prompt=TOY.sub('a desk lamp', im['prompt']))
            if not NO_PIP and TOY.search(im['prompt']):
                # the planner put the mascot toy into a scene: make it from the locked reference so it stays on-model
                j = {'id': f's{si:02d}_{k}', 'kind': 'edit', 'images': [G.PIP_REF], 'out': out, 'aspect': '9:16',
                     'prompt': pip_prompt(TOY.sub('the toy', im['prompt'].strip()), LK), 'cast': [], 'pip': True}
                toy_segs.add(sl['seg'])
                if not is_clip:                             # its own clip (static toy, camera and people move)
                    hp = os.path.join(work, 'heroes', f'pip_s{si:02d}_{k}.mp4')
                    heroes.append(pip_clip(f'hpip_s{si:02d}_{k}', out, hp, sl['seg'], sec))
                    sl['pip'] = (out, hp)
                    stills.append(j)
                    continue
            else:
                body = (im.get('image_prompt') or im['prompt']).strip()
                prompt, kind, refs = scene_prompt(body, who, cast, LK)
                j = {'id': f's{si:02d}_{k}', 'kind': kind, 'prompt': prompt, 'out': out, 'aspect': '9:16', 'cast': refs,
                     'gen_prompt': scene_prompt(body, who, cast, LK, force_gen=True)[0]}
                if kind == 'edit':
                    j['images'] = [os.path.join(work, 'cast', f'{r}.jpg') for r in refs]
                    if len(refs) == 1 and refs[0] in CAST_REFS:      # real person alone: also show the real photo
                        j['images'].append(CAST_REFS[refs[0]]['images'][0])
                        j['prompt'] = j['prompt'].replace('Scene: ', 'Reference image 2 is a real photo of the same person: '
                                                          'match that face exactly, smiling naturally. Scene: ', 1)
            stills.append(j)
            if is_clip:
                mo = im.get('motion') or 'the people keep doing the action; handheld camera pushes in slowly'
                robot = any('robot' in (cast.get(w) or {}).get('description', '').lower() for w in who)
                hp = os.path.join(work, 'heroes', f'h{si:02d}_{k}.mp4')
                sl['clip_files'].append(hp)
                heroes.append({'id': f'h{si:02d}_{k}', 'kind': 'r2v', 'first_frame': out, 'image': out, 'duration': sec,
                               'resolution': '720p', 'aspect': '9:16', 'out': hp, 'seg': sl['seg'], 'pri': si,
                               'prompt': (f"Continue this exact photoreal shot for {sec} seconds as real live-action "
                                          f"footage: {mo} Keep the same people, faces, clothes, place, light and look "
                                          f"({LK['label']}, grain). "
                                          + ("The robot stays a hard-shelled machine with the same blank visor head, it "
                                             "never becomes a person; " if robot else "Natural human movement and expressions, ")
                                          + "handheld camera, no cuts, no text, no logos"
                                          + (", keep the real cast's faces exactly." if CAST_REFS else ", no lookalikes of real people.")
                                          + (f" {LK['clip_extra']}" if LK.get('clip_extra') else ''))})
    # Pip: two in-story toy shots (each a still + a clip) and the end cameo
    pips = []
    seg_index = {sl['seg']: si for si, sl in enumerate(slots)}
    for n, p in enumerate([] if NO_PIP else (plan.get('pip') or [])[:2], 1):
        si = seg_index.get(p.get('seg'))
        if si is None or p.get('seg') in toy_segs:      # that segment already has an on-model toy shot
            continue
        st = {'id': f'pip{n}', 'kind': 'edit', 'images': [G.PIP_REF], 'prompt': pip_prompt(p['scene'], LK),
              'out': os.path.join(work, 'stills', f'pip{n}.jpg'), 'aspect': '9:16'}
        cl = pip_clip(f'hpip{n}', st['out'], os.path.join(work, 'heroes', f'pip{n}.mp4'), slots[si]['seg'], sec)
        stills.append(st); heroes.append(cl)
        slots[si]['pip'] = (st['out'], cl['out'])
        pips.append(n)
    cameo = {'id': 'cameo', 'kind': 'edit', 'images': [G.PIP_REF], 'aspect': '9:16',
             'prompt': pip_prompt(plan.get('cameo') or 'alone on an empty office desk at night, a desk lamp still on.', LK),
             'out': os.path.join(work, 'stills', 'cameo.jpg')}
    if NO_PIP:                                         # 14 Oct: the sign-off is the real, empty payoff location
        cameo = {'id': 'cameo', 'kind': 'gen', 'aspect': '9:16', 'out': cameo['out'],
                 'prompt': ("A real photographed film still: " + (plan.get('cameo') or 'an empty office at night, one desk '
                            'lamp still on, chairs pushed back') + " No people, no toys, no robots. " + LK['prompt'] + ' ' + NO_TEXT)}
    heroes.append({'id': 'hcameo', 'kind': 'r2v', 'first_frame': cameo['out'], 'image': cameo['out'], 'duration': sec,
                   'resolution': '720p', 'aspect': '9:16', 'out': os.path.join(work, 'heroes', 'cameo.mp4'),
                   'seg': 'hook', 'pri': -2,
                   'prompt': (f"Continue this exact photoreal shot for {sec} seconds: " + ("nothing in the room moves; " if NO_PIP else
                              "the small vinyl toy stays completely still and unchanged (a static toy, it never moves or morphs); ")
                              + "the camera slowly pushes in by hand, dust in the light. Same look, no text.")})
    return cast_jobs, stills, heroes, cameo


def _norm(t):
    import re
    return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


def headline_overlay(day, h):
    """render data for headline mode: per sung line (normalised text) -> story, the ticker text per story (verified
    against stories.md, else '@handle  <story heading>'), the headline card, the chorus hook words."""
    import headline as H
    st = {x['n']: x for x in H.stories(day)}
    voc = H.vocab(day)
    tick, bad = {}, []
    for t in h.get('ticker') or []:
        ok, b = H.ticker_ok(t['text'], voc, st.get(t['story'], {}).get('handles', []))
        if ok:                                         # several lines for one story scroll one after another
            tick[t['story']] = (tick[t['story']] + '      •      ' + t['text']) if t['story'] in tick else t['text']
        else:
            bad.append((t['story'], b))
    for n in [h['main_story']] + list(h.get('secondary') or []):
        if n not in tick and n in st:
            tick[n] = ' · '.join('@' + x for x in st[n]['handles'][:2]) + '  ' + st[n]['title']
    line_story = {}
    for sec in h['sections']:
        for l in sec['lines']:
            line_story.setdefault(_norm(l['text']), l['story'])
    card = (h.get('headline_card') or '').strip()
    cok = all(w.lower().strip(".,':;!?") in voc or w.lower() in H.STOP for w in card.split())
    return {'title': h['title'], 'line_story': line_story, 'ticker': tick, 'ticker_rejected': bad,
            'card': card if cok else st.get(h['main_story'], {}).get('title', ''), 'main': h['main_story'],
            'hook_words': (h.get('hook_words') or '').strip(), 'vocab': sorted(voc)}


def narrative_vocab(day):
    """words allowed in diegetic text (spell check): everything in stories.md, lyrics.txt, title.txt, treatment.json."""
    import re
    txt = ' '.join(G.read(os.path.join(day, f)) for f in ('stories.md', 'lyrics.txt', 'title.txt', 'treatment.json'))
    return sorted({w.lower() for w in re.findall(r"[A-Za-z0-9@%$.'+-]+", txt)} | {w.lower().strip(".'") for w in re.findall(r"[A-Za-z0-9@%$.'+-]+", txt)})


def prepare(day, work, look_genre, args, status):
    import tone as T
    tn = T.pick(day, work)
    status['tone'] = tn['tone']
    CAST_REFS.clear()
    CAST_REFS.update(load_cast_refs(day))
    if CAST_REFS:
        status['cast_refs'] = {k: v.get('name') for k, v in CAST_REFS.items()}
        G.log(f"cast_refs: real-likeness cast {status['cast_refs']} (cast_refs.json, private folder)")
    status['tone_why'] = tn.get('why')
    look, why = SP.pick_look(look_genre, getattr(args, 'real_look', 'auto'))
    if T.LOOK.get(tn['tone']) and getattr(args, 'real_look', 'auto') in (None, 'auto'):
        look, why = T.LOOK[tn['tone']], f"tone {tn['tone']} -> {T.LOOK[tn['tone']]}"
    import claudia as C
    claud = C.enabled(day) and getattr(args, 'real_planner', 'opus') == 'opus'
    if claud and getattr(args, 'real_look', 'auto') in (None, 'auto'):   # 19 Oct: clean film grade, no VHS/flash default
        look, why = 'clean-film', 'claudia mode (headline): clean cinematic film look'
    LK = dict(SP.SLOP_LOOKS[look], type='sparse', handheld=not claud)
    try:
        import datetime
        d = datetime.date.fromisoformat(os.path.basename(os.path.normpath(day))[:10])
        LK['day_label'] = (d.strftime('%b %d %a').upper(), '06:37')
    except ValueError:
        pass
    status['real_look'] = look
    G.log(f"slopcore look: {look} ({why})")
    audio = G.audio_path(day)
    dur = G.duration(audio)
    import assemble
    beats = assemble.beat_grid(audio, G.read(os.path.join(day, 'style.txt')), work)
    bn = os.path.basename(os.path.normpath(day)).replace('-', '')[:8]
    seed = args.seed if getattr(args, 'seed', None) is not None else (int(bn) if bn.isdigit() else 7)
    plines = RP.provisional_lines(day)
    sec = args.real_clip_sec or 3
    planner = getattr(args, 'real_planner', 'opus')
    script = planner in ('script', 'opus')
    if claud:                                          # 19 Oct Claudia mode: scenes + prompt book + one lead
        return prepare_claudia(day, work, look, LK, args, status, audio, dur, beats, seed, plines)
    if script:
        import slop_script as SS
        mx = args.real_images
        if planner == 'opus' and os.path.exists(os.path.join(day, 'treatment.json')) and not os.environ.get('NARRATIVE_OFF'):
            mx = min(mx or 999, int(os.environ.get('NARRATIVE_MAX_SHOTS', 66)))     # narrative: fewer, crafted shots
        pslots = SS.script_slots(plines, n_clips=args.real_heroes, max_images=mx)
        if mx != args.real_images:                     # narrative: the hook is a cold open that may cover a long
            for sl in pslots:                          # instrumental intro (13 Oct: 19 s on 1 still, used 19x)
                if sl['kind'] == 'hook':
                    sl['images'] = 7
        intro = intro_seconds(day) if planner == 'opus' else None
        if planner == 'opus' and intro is None and os.path.exists(os.path.join(day, 'headline.json')):
            for sl in pslots:                          # intro length unknown at plan time: plan 7 distinct hook shots,
                if sl['kind'] == 'hook':               # the edit uses as many as the real intro needs (no recycling)
                    sl['images'] = 7
                    sl['dur_hint'] = 'unknown (3-20)'
            G.log("intro: length unknown at plan time -> hook planned with 7 distinct shots; the edit trims to the real intro")
        if intro:                                      # 13 Oct: time the hook to the REAL intro (plan assumed 3.75 s, was 12 s)
            for sl in pslots:
                if sl['kind'] == 'hook':
                    sl['images'] = max(2, min(8, math.ceil(intro / 1.6)))
                    sl['dur_hint'] = round(intro, 1)
            G.log(f"intro: first vocal at ~{intro:.1f}s -> hook planned with {[x['images'] for x in pslots if x['kind'] == 'hook'][0]} shots")
    else:
        pslots = SP.provisional_slots(plines, n_clips=args.real_heroes, max_images=args.real_images)
    G.save_json(pslots, os.path.join(work, 'slots.json'))
    G.log(f"slots (from lyrics.txt): {len(pslots)} segments, {sum(s['images'] for s in pslots)} scenes"
          + (' (max; the script picks 1-3 per line)' if script else f", {sum(s['clips'] for s in pslots)} video clips") + f" of {sec} s (+ Pip)")
    t0 = time.time()
    cards = {}
    if script:
        if planner == 'opus':
            import slop_opus as SO
            import story_cards as SC
            SO.NARRATIVE.clear()
            SO.HEADLINE.clear()
            SO.HEADLINE.update(SO.headline(day) or {})
            if SO.HEADLINE:
                status['headline'] = SO.HEADLINE.get('title')
                G.log(f"headline mode: headline.json ({SO.HEADLINE.get('title')!r}); ticker + headline card + hook words only")
            else:
                SO.NARRATIVE.update(SO.narrative(day) or {})
            if SO.NARRATIVE:
                status['narrative'] = SO.NARRATIVE.get('title')
                G.log(f"narrative mode: treatment.json ({SO.NARRATIVE.get('title')!r}); no story cards or word slams")
            if T.is_daily(day) and tn['tone'] == 'edgy' and not SO.NARRATIVE and not SO.HEADLINE:          # news songs only (not the family songs)
                cards = SC.make(day, work, plines, deadline=getattr(args, 'deadline', None))
            SO.STORY_NOTE = SC.director_note(cards)
            status['story_cards'] = len(cards)
            tp = os.path.join(work, 'align', 'timings.json')
            timed = G.load_json(tp) if os.path.exists(tp) else None      # word onsets when already known (re-runs)
            plan = SO.plan(day, work, look, pslots, plines, deadline=getattr(args, 'deadline', None),
                           reserve_s=CR.PLAN_RESERVE_S, reuse=getattr(args, 'real_reuse_plan', False),
                           timed=timed if isinstance(timed, list) else None)
        else:
            plan = SS.plan(day, work, look, pslots, plines, deadline=getattr(args, 'deadline', None),
                           reserve_s=CR.PLAN_RESERVE_S, reuse=getattr(args, 'real_reuse_plan', False))
        n_cl = SS.apply(plan, pslots, args.real_heroes)
        G.save_json(pslots, os.path.join(work, 'slots.json'))
        SS.write_script_md(plan, pslots, os.path.join(work, 'script.md'))
        G.log(f"script: {sum(s['images'] for s in pslots)} shots, {n_cl} clips; script.md written")
    else:
        plan = SP.plan(day, work, look, pslots, plines, deadline=getattr(args, 'deadline', None), clip_sec=sec,
                       reserve_s=CR.PLAN_RESERVE_S, reuse=getattr(args, 'real_reuse_plan', False))
    status['plan'] = {'secs': round(time.time() - t0), 'segments': len(plan['segments']), 'fallback': bool(plan.get('fallback')),
                      'cast': [c.get('role') for c in plan.get('cast') or []], 'planner': plan.get('planner', SP.PLANNER_VERSION),
                      'review': plan.get('review')}
    LK['story_cards'] = cards
    if script and planner == 'opus' and SO.HEADLINE:
        LK['headline'] = headline_overlay(day, SO.HEADLINE)
    elif script and planner == 'opus' and SO.NARRATIVE:
        LK['narrative'] = {'title': G.read(os.path.join(day, 'title.txt')).strip(),
                           'onscreen': {b['seg']: b.get('onscreen') for b in plan.get('beats') or [] if (b.get('onscreen') or '').strip()},
                           'vocab': narrative_vocab(day)}
    cast_jobs, stills, heroes, cameo = build_jobs(plan, pslots, work, LK, sec)
    G.log(f"jobs: {len(cast_jobs)} cast portraits, {len(stills)} stills ({sum(1 for j in stills if j['kind']=='edit')} "
          f"from cast/Pip references), {len(heroes)} clips")
    return {'v2': True, 'day': day, 'work': work, 'look': look, 'LK': LK, 'audio': audio, 'dur': dur, 'beats': beats,
            'seed': seed, 'pslots': pslots, 'plan': plan, 'cast_jobs': cast_jobs, 'stills': stills, 'heroes': heroes,
            'cameo': cameo, 'sec': sec, 'script': script}


def prepare_claudia(day, work, look, LK, args, status, audio, dur, beats, seed, plines):
    import claudia as C
    import slop_opus as SO
    t0 = time.time()
    SO.HEADLINE.clear(); SO.NARRATIVE.clear()
    SO.HEADLINE.update(SO.headline(day) or {})
    status['headline'] = SO.HEADLINE.get('title')
    pslots, plan, book = C.plan(day, work, plines, dur, deadline=getattr(args, 'deadline', None),
                                reuse=getattr(args, 'real_reuse_plan', False))
    G.save_json(pslots, os.path.join(work, 'slots.json'))
    LK['story_cards'] = {}
    LK['headline'] = headline_overlay(day, SO.HEADLINE)
    cast_jobs, stills, heroes, cameo = build_jobs(plan, pslots, work, LK, 5)
    ds = [im.get('duration') or 5 for sg in plan['segments'] for im in sg['images']]
    args.real_clip_sec = max(2, min(5, math.ceil(sum(ds) / max(1, len(ds)))))   # budget estimate: the mean clip length
    heroes = C.patch_jobs(cast_jobs, stills, heroes, pslots, plan, work, LK, book['lead'])
    n_sh = sum(s['images'] for s in pslots)
    status['plan'] = {'secs': round(time.time() - t0), 'segments': len(pslots), 'planner': C.VERSION, 'shots': n_sh,
                      'clips': len(heroes) - 1, 'lead': book['lead'].get('name'), 'lead_share': round(C.lead_share(book), 2),
                      'cast': [c.get('role') for c in plan['cast']], 'review_issues': len((book.get('_review') or {}).get('issues') or [])}
    status['claudia'] = True
    G.log(f"claudia: {n_sh} shots in {len(pslots)} scenes, {len(heroes) - 1} clips (+ sign-off), lead "
          f"{book['lead'].get('name')} in {C.lead_share(book):.0%}; prompt_book.md written")
    G.log(f"jobs: {len(cast_jobs)} cast portraits, {len(stills)} stills ({sum(1 for j in stills if j['kind']=='edit')} "
          f"from cast references), {len(heroes)} clips")
    return {'v2': True, 'day': day, 'work': work, 'look': look, 'LK': LK, 'audio': audio, 'dur': dur, 'beats': beats,
            'seed': seed, 'pslots': pslots, 'plan': plan, 'cast_jobs': cast_jobs, 'stills': stills, 'heroes': heroes,
            'cameo': cameo, 'sec': 5, 'script': True, 'claudia': True, 'book': book}


def generate_media(P, args, status):
    gen = {'skipped': bool(args.skip_gen)}
    if os.environ.get('CINE_REAL_FAIL') == 'gen':
        G.log("TEST: CINE_REAL_FAIL=gen, skipping generation")
    elif not args.skip_gen:
        work = P['work']
        cj = [j for j in P['cast_jobs'] if not (os.path.exists(j['out']) and os.path.getsize(j['out']) > 1000)]
        if cj:
            dl = getattr(args, 'deadline', None)
            B = real_gen.Batcher(work, {'gen': len(cj) * 2, 'edit': len(cj) * 2, 'i2v': 0}, batch_size=1, max_parallel=3,
                                 start_gap=4.0, tag='cast', timeout=300, deadline=(dl - CR.RENDER_RESERVE_S) if dl else None)
            r = B.run(cj)
            G.log(f"cast portraits: {sum(1 for j in P['cast_jobs'] if os.path.exists(j['out']))}/{len(P['cast_jobs'])}")
        if P.get('claudia'):                           # 19 Oct: the lead's sheet is Opus-approved before any batch
            import claudia as C
            status['lead_approval'] = C.approve_lead(P, args)
        for j in P['stills']:                         # a cast portrait failed: describe the person in words instead
            if j['kind'] == 'edit' and j.get('cast') and not all(os.path.exists(x) for x in j['images']):
                j.update(kind='gen', prompt=j['gen_prompt']); j.pop('images', None)
        args.hero_parallel = 5
        import judge as J
        gated = os.environ.get('GV_REALISM') != '0'
        if gated:                                      # 13 Oct realism gate: stills -> Opus review/reroll -> clips
            g1 = CR.generate(P['stills'], [], P['cameo'], P['pslots'], work, args, status)
            rg = J.realism_gate(P, args, status, g1.get('spent_pct'))
            blocked = set(rg.get('blocked_clips') or [])
            u_mid = CR.usage_pct()
            spent1 = (u_mid - g1['usage_start']) if (u_mid is not None and g1.get('usage_start') is not None) else (g1.get('spent_pct') or 0)
            import copy
            a2 = copy.copy(args)
            a2.real_max_pct = max(0.0, args.real_max_pct - spent1)
            G.log(f"clips after the gate: {len(P['heroes']) - len(blocked)} of {len(P['heroes'])}, budget {a2.real_max_pct:.1f}%")
            g2 = CR.generate([], [h for h in P['heroes'] if h['id'] not in blocked], None, P['pslots'], work, a2, status)
            gen.update(g2)
            gen.update(usage_start=g1.get('usage_start'), stills_made=g1.get('stills_made'),
                       spent_pct=(spent1 + (g2.get('spent_pct') or 0)), realism=rg)
        else:
            gen.update(CR.generate(P['stills'], P['heroes'], P['cameo'], P['pslots'], work, args, status))
        try:                                           # P2 judge-and-reroll loop (fail-open, budget/time aware)
            gen['judge'] = J.loop(P, args, status, gen, stills_done=gated)
        except Exception as e:
            G.log(f"WARNING: judge loop not run: {e!r}"[:300])
        if P.get('claudia'):                           # 19 Oct: Opus picks each clip's usable in/out window
            try:
                import claudia as C
                ex = qa_exclude(work)
                cl = [h['out'] for h in P['heroes'] if os.path.exists(h['out']) and CR.valid_video(h['out'], 12)
                      and os.path.basename(h['out']) not in ex]
                C.pick_windows(P, cl)
            except Exception as e:
                G.log(f"WARNING: window pick not run: {e!r}"[:300])
    status['generation'] = gen
    return gen


MAX_STILL_USES = 2
HOLD_STILL_S = 1.2       # P6: longest single still on screen (s)
HOLD_CLIP_S = 2.0        # P6: longest single clip window on screen (s)
TOP = (0.5, 0.32)          # punched-in framing keeps heads in frame (people are the subject)


def make_edit(entries, extra, seed, max_still=MAX_STILL_USES):
    """Motion first: each segment's cuts take its clips (first window, then a punched-in second window), then its own
    stills, then unused neighbours. A still is used at most `max_still` times; when the stills run out the cut borrows
    another window of a nearby clip instead. Stills get handheld shake + push."""
    rnd = random.Random(seed)
    uses, wins = {}, {}                            # still -> uses; clip -> windows used
    edit = []
    pool = list(extra)
    for i, d in enumerate(entries):
        pool += [(i, f, im) for f, im in d['files']]
    all_clips = [(i, c) for i, d in enumerate(entries) for c in list(d['clips']) + ([d['pip']] if d.get('pip') else [])]
    pip_set = {d['pip'] for d in entries if d.get('pip')}
    for i, d in enumerate(entries):
        cs = d['cs']
        n = len(cs)
        if not n:
            continue
        clips = list(d['clips'])
        if d.get('pip') and d['pip'] not in clips:
            clips.insert(min(1, len(clips)), d['pip'])
        seq = [('video', c, 'a') for c in clips]
        own = [(f, im) for f, im in d['files'] if uses.get(f, 0) == 0]
        seq += [('still', f, im) for f, im in own]
        if len(seq) > n:                               # too many: keep the clips (and the Pip shot), drop stills
            keep = [x for x in seq if x[0] == 'video'][:n]
            seq = keep + [x for x in seq if x[0] == 'still'][:n - len(keep)]
        k = 0
        while len(seq) < n and k < len(clips):        # second windows of the clips, right after their first
            if ('video', clips[k], 'a') in seq:
                seq.insert(seq.index(('video', clips[k], 'a')) + 1, ('video', clips[k], 'b'))
            k += 1
        if len(seq) < n:                               # unused pictures nearby
            for x in sorted([x for x in pool if uses.get(x[1], 0) == 0 and abs(x[0] - i) <= 2 and
                             x[1] not in [y[1] for y in seq]], key=lambda x: abs(x[0] - i)):
                if len(seq) >= n:
                    break
                seq.append(('still', x[1], x[2]))
        pend = {}
        for x in seq:
            if x[0] == 'still':
                pend[x[1]] = pend.get(x[1], 0) + 1
            else:
                pend[x[1]] = pend.get(x[1], 0) + 1
        while len(seq) < n:                            # borrow: least-used still under the cap, else another clip window
            last = seq[-1][1] if seq else None
            cand = sorted([x for x in pool if uses.get(x[1], 0) + pend.get(x[1], 0) < max_still and x[1] != last],
                          key=lambda x: (uses.get(x[1], 0) + pend.get(x[1], 0), abs(x[0] - i)))
            if cand and abs(cand[0][0] - i) <= 6:
                seq.append(('still', cand[0][1], cand[0][2])); pend[cand[0][1]] = pend.get(cand[0][1], 0) + 1
                continue
            cc = sorted([x for x in all_clips if x[1] not in pip_set and x[1] != last and
                         wins.get(x[1], 0) + pend.get(x[1], 0) < 3],
                        key=lambda x: (wins.get(x[1], 0) + pend.get(x[1], 0), abs(x[0] - i)))
            if cc:
                w = 'abc'[wins.get(cc[0][1], 0) + pend.get(cc[0][1], 0)]
                seq.append(('video', cc[0][1], w)); pend[cc[0][1]] = pend.get(cc[0][1], 0) + 1
                continue
            if cand:
                seq.append(('still', cand[0][1], cand[0][2])); pend[cand[0][1]] = pend.get(cand[0][1], 0) + 1
                continue
            break
        for c, item in zip(cs, seq):
            kind, f = item[0], item[1]
            L = c['t1'] - c['t0']
            e = {'t0': c['t0'], 't1': c['t1'], 'src': f, 'kind': kind, 'seg': d['seg'], 'seg_kind': d['kind'],
                 'on_beat': c.get('on_beat'), 'anchor': (0.5, 0.5), 'cut_in': False, 'move': 'push_in'}
            if kind == 'video':
                cd = CR._DUR.get(f, 3.0)
                if item[2] == 'a':
                    e['win0'] = 0.12
                elif item[2] == 'b':
                    e['win0'] = round(max(0.3, min(cd - L - 0.05, cd * 0.55)), 2)
                    e['cut_in'] = True
                else:                                  # 'c': the middle of the clip, punched in
                    e['win0'] = round(max(0.2, min(cd - L - 0.05, cd * 0.3)), 2)
                    e['cut_in'] = True
                if e['cut_in']:
                    e['anchor'] = TOP
                wins[f] = wins.get(f, 0) + 1
            else:
                im = item[2] or {}
                e['move'] = rnd.choice(['push_in', 'shake', 'push_in', 'pull_out', 'shake'])
                e['cut_in'] = uses.get(f, 0) >= 1
                if e['cut_in']:
                    e['anchor'] = TOP
                uses[f] = uses.get(f, 0) + 1
            edit.append(e)
    edit.sort(key=lambda e: e['t0'])
    prev = None
    for e in edit:
        new = e['seg'] != prev
        e['flash'] = new and ((e['seg_kind'] == 'chorus' and e['seg'].endswith(':1')) or e['seg_kind'] == 'drop')
        e['whip'] = new and e['seg_kind'] == 'drop' and rnd.random() < 0.5
        e['leak'] = False
        prev = e['seg']
    if edit:
        edit[0]['flash'] = edit[0]['whip'] = False
    return edit, uses


def make_edit_script(segs, cuts, pslots, mapping, ok, ex, work, seed):
    """v3 edit: every timeline segment uses ONLY its own line's shots. Shot k starts on its sung word (the word's onset
    from the timings; estimated from the line's position if missing); the beat cuts inside a shot are alternate takes
    of that same shot (the clip continuing, punched in, then its still), then other shots of the same line."""
    rnd = random.Random(seed)
    by_seg = {}
    for c in cuts:
        by_seg.setdefault(c['seg'], []).append(c)
    shots_of = {}
    for si, sl in enumerate(pslots):
        lst = []
        for k, im in enumerate(sl.get('plan_images') or []):
            st = os.path.join(work, 'stills', f's{si:02d}_{k}.jpg')
            cl = os.path.join(work, 'heroes', f'h{si:02d}_{k}.mp4')
            st = st if os.path.exists(st) and CR.valid_image(st) and os.path.basename(st) not in ex else None
            cl = cl if cl in ok else None
            if sl.get('pip') and st and st == sl['pip'][0]:
                continue                               # a toy shot: added once below as this line's Pip shot
            if st or cl:
                lst.append({'k': k, 'still': st, 'clip': cl, 'word': int(im.get('word') or 0)})
        if sl.get('pip'):
            pst, pcl = sl['pip']
            pst = pst if os.path.exists(pst) and CR.valid_image(pst) else None
            pcl = pcl if pcl in ok else None
            if pst or pcl:
                lst.append({'k': 'pip', 'still': pst, 'clip': pcl, 'word': None, 'pip': True})
        shots_of[si] = lst
    edit, uses = [], {}
    sm = {'borrowed_segments': [], 'lines': 0, 'cuts_on_own_line': 0, 'cuts': 0, 'pip_placed': 0}
    order = [s for s in segs if s['kind'] not in ('cameo', 'credits')]
    for idx, s in enumerate(order):
        a, b = s['t0'], s['t1']
        si = mapping.get(s['id'])
        own = shots_of.get(si) or []
        borrowed = False
        if not own:                                    # nothing usable for this line (generation failed): nearest
            for d in range(1, len(order)):
                for j in (idx - d, idx + d):
                    if 0 <= j < len(order) and shots_of.get(mapping.get(order[j]['id'])):
                        own = shots_of[mapping.get(order[j]['id'])]; break
                if own:
                    break
            borrowed = True
            sm['borrowed_segments'].append(s['id'])
        if not own:
            continue
        main = [x for x in own if not x.get('pip')]
        pip = [x for x in own if x.get('pip')]
        words = (s.get('line') or {}).get('words') or []
        timed = [w for w in words if w[1] is not None]
        # shot start times
        starts = []
        for n, x in enumerate(main):
            if n == 0 or x['word'] is None:
                t = a if n == 0 else None
            elif timed and x['word'] < len(words) and words[x['word']][1] is not None:
                t = words[x['word']][1] - 0.06
            elif words:
                t = a + (b - a) * x['word'] / max(len(words), 1)
            else:
                t = a + (b - a) * n / max(len(main), 1)      # instrumental: spread evenly
            if t is None:
                continue
            if starts and (t < starts[-1][0] + 0.45 or t > b - 0.45):
                t = min(max(t, starts[-1][0] + 0.45), b - 0.45)   # nudge a crowded/late planned shot instead of losing it
                if t < starts[-1][0] + 0.45:
                    continue                                 # too tight to show: it stays as an alternate take
            starts.append((max(a, t), x))
        if not starts:
            starts = [(a, main[0] if main else own[0])]
        if pip and not borrowed:                       # the Pip shot: split the longest span of this line
            spans = [(starts[n + 1][0] if n + 1 < len(starts) else b) - starts[n][0] for n in range(len(starts))]
            n = max(range(len(spans)), key=lambda q: spans[q])
            if spans[n] >= 0.9:
                starts.insert(n + 1, (starts[n][0] + spans[n] / 2, pip[0]))
                sm['pip_placed'] += 1
        # cut points: shot starts + the beat cuts that are not too close to a shot start
        pts = sorted({round(t, 3) for t, _ in starts})
        for c in by_seg.get(s['id'], []):
            if a + 0.4 < c['t0'] < b - 0.4 and all(abs(c['t0'] - t) >= 0.4 for t in pts):
                pts.append(round(c['t0'], 3))
        pts = sorted(pts) + [b]
        # P6 hold caps: no single picture stays on screen longer than HOLD_STILL_S (still) / HOLD_CLIP_S (clip);
        # a long span is split and the extra pieces rotate in unused shots of the same line (or the next take)
        split_pts, capped = set(), []
        for q in range(len(pts) - 1):
            t0, t1 = pts[q], pts[q + 1]
            capped.append(t0)
            cur0 = [x for t, x in starts if t <= t0 + 1e-6]
            cur0 = cur0[-1] if cur0 else None
            cap_s = HOLD_CLIP_S if (cur0 and cur0.get('clip')) else HOLD_STILL_S
            n = int(math.ceil((t1 - t0) / cap_s - 1e-6))
            for m in range(1, n):
                tp = round(t0 + (t1 - t0) * m / n, 3)
                capped.append(tp); split_pts.add(tp)
        if split_pts:
            sm['hold_splits'] = sm.get('hold_splits', 0) + len(split_pts)
        pts = capped + [b]
        used_take = {}
        alt = [x for x in main if x not in [y for _, y in starts]] + [y for _, y in starts]
        for j in (idx + 1, idx - 1, idx + 2, idx - 2):        # one-shot lines: borrow the neighbours' shots, not a
            if 0 <= j < len(order):                           # 4-7 s hold of the same picture
                alt += [y for y in shots_of.get(mapping.get(order[j]['id'])) or [] if not y.get('pip') and y not in alt]
        for q in range(len(pts) - 1):
            t0, t1 = pts[q], pts[q + 1]
            if t1 - t0 < 0.08:
                continue
            cur = [x for t, x in starts if t <= t0 + 1e-6][-1]
            n_take = used_take.get(id(cur), 0)
            x = cur
            if t0 in split_pts:                        # a hold-cap split: prefer a shot of this line not seen yet
                fresh = [y for y in alt if y is not cur and not used_take.get(id(y))]
                if fresh:
                    x = fresh[0]; n_take = 0
            if x is cur and n_take >= 3:                            # this shot is used up: an alternate shot of the same line
                x = min(alt, key=lambda y: used_take.get(id(y), 0))
                n_take = used_take.get(id(x), 0)
            used_take[id(x)] = n_take + 1
            L = t1 - t0
            e = {'t0': t0, 't1': t1, 'seg': s['id'], 'seg_kind': s['kind'], 'on_beat': None, 'anchor': (0.5, 0.5),
                 'cut_in': False, 'move': 'push_in', 'shot': f"{s['id']}|{x['k']}", 'borrowed': borrowed}
            if x['clip'] and n_take < 2:
                cd = CR._DUR.get(x['clip'], 3.0)
                e.update(kind='video', src=x['clip'])
                if n_take == 0:
                    e['win0'] = 0.12
                else:                                  # the action continues, punched in (a jump cut)
                    e['win0'] = round(max(0.2, min(cd - L - 0.05, x.get('_end', 0.12))), 2)
                    e['cut_in'] = True; e['anchor'] = TOP
                x['_end'] = e['win0'] + L
            else:
                src = x['still'] or x['clip']
                e.update(kind='still' if x['still'] else 'video', src=src)
                if e['kind'] == 'video':
                    e['win0'] = 0.3
                e['move'] = rnd.choice(['push_in', 'shake', 'push_in', 'pull_out'])
                e['cut_in'] = n_take > 0
                if e['cut_in']:
                    e['anchor'] = TOP
                uses[src] = uses.get(src, 0) + 1
            edit.append(e)
            sm['cuts'] += 1
            sm['cuts_on_own_line'] += 0 if borrowed else 1
        sm['lines'] += 1 if s['kind'] not in ('hook', 'drop', 'outro_tail') else 0
    edit.sort(key=lambda e: e['t0'])
    prev = None
    for e in edit:
        new = e['seg'] != prev
        e['flash'] = new and ((e['seg_kind'] == 'chorus' and e['seg'].endswith(':1')) or e['seg_kind'] == 'drop')
        e['whip'] = new and e['seg_kind'] == 'drop' and rnd.random() < 0.5
        e['leak'] = False
        prev = e['seg']
    if edit:
        edit[0]['flash'] = edit[0]['whip'] = False
    cutset = sorted(c['t0'] for c in cuts)
    for e in edit:
        e['on_beat'] = any(abs(e['t0'] - t) < 0.05 for t in cutset)
    sm['own_line_share'] = round(sm['cuts_on_own_line'] / max(sm['cuts'], 1), 3)
    return edit, uses, sm


def qa_exclude(work):
    """Optional per-day QA blocklist: work/qa_exclude.json = ["s23_1.jpg", "h03_1.mp4", ...]. Listed stills/clips are
    left out of the edit (a clip whose first-frame still is listed goes too) and the cuts borrow other footage."""
    ex = G.load_json(os.path.join(work, 'qa_exclude.json')) or []
    ex = {os.path.basename(x) for x in ex}
    ex |= {x.replace('s', 'h', 1).replace('.jpg', '.mp4') for x in ex if x.startswith('s') and x.endswith('.jpg')}
    return ex


def place_orphan_drops(segs, pslots, min_gap=1.2):
    """The planner's instrumental DROP scenes (e.g. a rowing beat) are only used when the timeline has a separate
    instrumental segment. When the song's breaks are folded into the sung lines instead, give each planned drop the
    instrumental tail of the line it follows (or the longest unused tail) so its pictures still reach the video."""
    if any(s['kind'] == 'drop' for s in segs):
        return segs
    drops = [i for i, sl in enumerate(pslots) if sl['kind'] == 'drop']
    if not drops:
        return segs

    def tail(s):
        ws = [w for w in ((s.get('line') or {}).get('words') or []) if len(w) > 2 and w[2] is not None]
        if not ws or s['kind'] in ('hook', 'cameo', 'credits', 'drop'):
            return None
        end = max(w[2] for w in ws) + 0.1
        return end if s['t1'] - end >= min_gap else None
    segs = list(segs)
    placed = []
    for i in drops:
        prev = pslots[i - 1]['seg'] if i > 0 else None
        cand = [n for n, s in enumerate(segs) if s['id'] == prev and tail(s)]
        if not cand:
            cand = sorted((n for n, s in enumerate(segs) if tail(s)), key=lambda n: segs[n]['t1'] - tail(segs[n]))[-1:]
        if not cand:
            continue
        n = cand[0]; s = dict(segs[n]); e = tail(s)
        d = {'id': pslots[i]['seg'], 'kind': 'drop', 't0': e, 't1': s['t1'], 'line': None}
        s['t1'] = e
        segs[n:n + 1] = [s, d]
        placed.append(f"{d['id']}@{e:.1f}-{d['t1']:.1f}s")
    if placed:
        G.log(f"drops: placed in instrumental tails: {', '.join(placed)}")
    return segs


def edit_and_render(P, L, out, args, status):
    day, work, LK, audio, dur, seed = P['day'], P['work'], P['LK'], P['audio'], P['dur'], P['seed']
    stills, plan, pslots, cameo = P['stills'], P['plan'], P['pslots'], P['cameo']
    segs, cuts = RP.build_timeline(L, P['beats'], dur, seed, credits_len=2.5, cameo_len=1.8)
    G.save_json({'segments': [{k: v for k, v in s.items() if k != 'line'} for s in segs], 'cuts': cuts},
                os.path.join(work, 'timeline.json'))
    clips_ok = [h['out'] for h in P['heroes'] if os.path.exists(h['out']) and CR.valid_video(h['out'], 12)]
    n_st = sum(1 for j in stills if os.path.exists(j['out']))
    G.log(f"timeline: {len(cuts)} cuts; {n_st}/{len(stills)} stills and {len(clips_ok)}/{len(P['heroes'])} clips available")
    if n_st + len(clips_ok) < max(12, (len(stills) + len(P['heroes'])) // 4):
        raise RuntimeError(f'too few pictures: {n_st} stills, {len(clips_ok)} clips')
    import tone as T
    if not T.is_daily(day):                            # special folders only (daily edit untouched)
        segs = place_orphan_drops(segs, pslots)
    mapping = RP.map_segments(segs, pslots)
    ex = qa_exclude(work)
    if ex:
        G.log(f"QA exclude: {sorted(ex)}")
        status['qa_exclude'] = sorted(ex)
    ok = {c for c in clips_ok if os.path.basename(c) not in ex}
    if P.get('claudia'):
        return edit_and_render_claudia(P, L, out, args, status, segs, cuts, ok, ex)
    if P.get('script'):
        edit, uses, sm = make_edit_script(segs, cuts, pslots, mapping, ok, ex, work, seed)
        status['script_edit'] = sm
    else:
        files_of, clips_of, pip_of = {}, {}, {}
        for si, sl in enumerate(pslots):
            fs = [(os.path.join(work, 'stills', f's{si:02d}_{k}.jpg'), im) for k, im in enumerate(sl.get('plan_images') or [])]
            cl = [c for c in sl.get('clip_files') or [] if c in ok]
            firsts = {c.replace('/heroes/h', '/stills/s').replace('.mp4', '.jpg') for c in cl}
            clips_of[si] = cl
            files_of[si] = [(f, im) for f, im in fs if os.path.exists(f) and f not in firsts and CR.valid_image(f)
                            and os.path.basename(f) not in ex]
            # a clip that failed leaves its first-frame still for the edit
            if sl.get('pip') and sl['pip'][1] in ok:
                pip_of[si] = sl['pip'][1]
                files_of[si] = [(f, im) for f, im in files_of[si] if f != sl['pip'][0]]
            elif sl.get('pip') and os.path.exists(sl['pip'][0]):
                files_of[si].insert(0, (sl['pip'][0], {'move': 'push_in'}))
        by = {}
        for c in cuts:
            by.setdefault(c['seg'], []).append(c)
        claimed, entries = set(), []
        for s in segs:
            if s['kind'] in ('cameo', 'credits'):
                continue
            si = mapping.get(s['id'])
            files, clips, pip = [], [], None
            if si is not None and si not in claimed:
                claimed.add(si)
                files, clips, pip = files_of[si], clips_of[si], pip_of.get(si)
            entries.append({'seg': s['id'], 'kind': s['kind'], 'cs': by.get(s['id'], []), 'files': files, 'clips': clips,
                            'pip': pip, 'si': si})
        pos_of = {e['si']: i for i, e in enumerate(entries) if e['si'] is not None}
        extra = []
        for si in files_of:
            if si in claimed:
                continue
            near = min(pos_of, key=lambda p: abs(p - si)) if pos_of else 0
            # unclaimed segments' clips are still worth showing: offer them as pictures too (first window only)
            extra += [(pos_of.get(near, 0), f, im) for f, im in files_of[si]]
        edit, uses = make_edit(entries, extra, seed)
    cam_clip = os.path.join(work, 'heroes', 'cameo.mp4')
    cam_clip = cam_clip if cam_clip in ok else None
    cam = cameo['out'] if os.path.exists(cameo['out']) and CR.valid_image(cameo['out']) else None
    last = next((e['src'] for e in reversed(edit) if e['kind'] == 'still'), edit[0]['src'] if edit else None)
    for c in cuts:
        if c['seg'] in ('cameo', 'credits'):
            src, kind = (cam_clip, 'video') if cam_clip else (cam or last, 'still')
            edit.append({'t0': c['t0'], 't1': c['t1'], 'src': src, 'kind': kind, 'win0': 0.1,
                         'move': 'push_in' if c['seg'] == 'cameo' else 'drift', 'cut_in': False, 'seg': c['seg'],
                         'seg_kind': c['seg'], 'on_beat': c.get('on_beat'), 'flash': False, 'whip': False,
                         'leak': False, 'anchor': (0.5, 0.5)})
    edit.sort(key=lambda e: e['t0'])
    if not (cam_clip or cam):
        status['warnings'].append('Pip end cameo missing: the sign-off shot reuses the last still')
    disp = {d['seg']: d.get('tokens') for d in plan.get('display', [])}
    acc = {d['seg']: d.get('accent') or [] for d in plan.get('display', [])}
    ass = os.path.join(work, 'type.ass')
    rows, footer = G.credit_card(day)
    credits = {'t0': [s for s in segs if s['kind'] == 'credits'][0]['t0'], 'rows': rows[:6], 'footer': footer}
    first = [ln for ln in L if ln.get('words')][0]
    hook_toks = [t[0] for t in RR.line_tokens(first, disp.get(RP.line_id(first)))][:1]
    RR.build_ass(ass, L, disp, acc, None, LK, credits, dur, hook_toks)
    G.save_json(edit, os.path.join(work, 'edit.json'))
    body = [e for e in edit if e['seg_kind'] not in ('credits',)]
    lens = [e['t1'] - e['t0'] for e in body]
    pip_srcs = {p for sl in pslots if sl.get('pip') for p in sl['pip']} | {cameo['out'], os.path.join(work, 'heroes', 'cameo.mp4')}
    metrics = {'shots': len(edit), 'avg_shot_s': round(sum(lens) / len(lens), 2),
               'motion_share': round(sum(e['t1'] - e['t0'] for e in body if e['kind'] == 'video') / sum(lens), 2),
               'clips_used': len({e['src'] for e in edit if e['kind'] == 'video'}),
               'distinct_stills': len({e['src'] for e in edit if e['kind'] == 'still'}),
               'pip_shots': sum(1 for e in edit if e['src'] in pip_srcs),
               'max_uses': max([n for f, n in uses.items()] or [0]),
               'max_still_uses': max([sum(1 for e in body if e['kind'] == 'still' and e['src'] == f)
                                      for f in {e['src'] for e in body if e['kind'] == 'still'}] or [0]),
               'on_beat_frac': round(sum(1 for e in edit if e.get('on_beat')) / len(edit), 2)}
    status['real_metrics'] = metrics
    G.log(f"edit: {metrics}")
    if os.environ.get('CINE_REAL_FAIL') == 'render':
        raise RuntimeError('TEST: CINE_REAL_FAIL=render')
    t0 = time.time()
    RR.render(edit, LK, audio, ass, out, dur, seed=seed, hard_deadline=getattr(args, 'deadline', None))
    G.log(f"render: {time.time()-t0:.0f}s")
    return True, {'metrics': metrics, 'look': P['look']}


def edit_and_render_claudia(P, L, out, args, status, segs, cuts, ok, ex):
    import claudia as C
    day, work, LK, audio, dur, seed, cameo = P['day'], P['work'], P['LK'], P['audio'], P['dur'], P['seed'], P['cameo']
    edit = C.make_edit(L, P['pslots'], work, ok, ex, segs, dur)
    cam_clip = os.path.join(work, 'heroes', 'cameo.mp4')
    cam_clip = cam_clip if cam_clip in ok else None
    cam = cameo['out'] if os.path.exists(cameo['out']) and CR.valid_image(cameo['out']) else None
    last = next((e['src'] for e in reversed(edit) if e['kind'] == 'still'), edit[0]['src'] if edit else None)
    cam0 = min(s['t0'] for s in segs if s['kind'] in ('cameo', 'credits'))
    if edit:
        edit[-1]['t1'] = max(edit[-1]['t1'], cam0) if cam0 - edit[-1]['t1'] < 3 else edit[-1]['t1']
    for s in segs:                                     # sign-off + credits: one shot each, no beat cuts
        if s['kind'] in ('cameo', 'credits'):
            src, kind = (cam_clip, 'video') if cam_clip else (cam or last, 'still')
            edit.append({'t0': s['t0'], 't1': s['t1'], 'src': src, 'kind': kind, 'win0': 0.1, 'move': 'push_in',
                         'cut_in': False, 'seg': s['kind'], 'seg_kind': s['kind'], 'on_beat': True, 'flash': False,
                         'whip': False, 'leak': False, 'anchor': (0.5, 0.5)})
    edit.sort(key=lambda e: e['t0'])
    rows, footer = G.credit_card(day)
    credits = {'t0': [s for s in segs if s['kind'] == 'credits'][0]['t0'], 'rows': rows[:6], 'footer': footer}
    base = os.path.join(work, 'type_base.ass')
    first = [ln for ln in L if ln.get('words')][0]
    RR.build_ass(base, L, {}, {}, None, dict(LK, vhs=False), credits, dur, [first['words'][0][0]])
    ass = os.path.join(work, 'type.ass')
    hl = LK.get('headline')
    accw = (hl or {}).get('hook_words', '').split()
    C.build_ass(ass, L, P['pslots'], hl, C.credits_from(base, credits['t0']), dur, cam0, accw)
    G.save_json(edit, os.path.join(work, 'edit.json'))
    body = [e for e in edit if e['seg_kind'] not in ('credits', 'cameo')]
    lens = [e['t1'] - e['t0'] for e in body]
    metrics = {'shots': len(body), 'avg_shot_s': round(sum(lens) / max(1, len(lens)), 2),
               'motion_share': round(sum(l for e, l in zip(body, lens) if e['kind'] == 'video') / max(0.1, sum(lens)), 2),
               'clips_used': len({e['src'] for e in body if e['kind'] == 'video'}),
               'distinct_stills': len({e['src'] for e in body if e['kind'] == 'still'}),
               'longest_s': round(max(lens or [0]), 2), 'shorter_than_1_5s': sum(1 for l in lens if l < 1.5)}
    status['real_metrics'] = metrics
    G.log(f"edit (claudia): {metrics}")
    t0 = time.time()
    RR.render(edit, LK, audio, ass, out, dur, seed=seed, hard_deadline=getattr(args, 'deadline', None))
    G.log(f"render: {time.time()-t0:.0f}s")
    C.grade(out, work)
    return True, {'metrics': metrics, 'look': P['look']}


def intro_seconds(day):
    """Seconds before the first sung word, from an earlier alignment of this same audio (exact) if one exists, else None.
    (13 Oct: whisper on the full mix gave 13-28 s for a 12.2 s intro, so the plan does not guess.)"""
    import glob
    au = os.path.join(day, 'audio.mp3')
    for f in sorted(glob.glob(os.path.join(day, 'work*', 'align', 'timings.json')), key=os.path.getmtime, reverse=True):
        try:
            if os.path.getmtime(f) < os.path.getmtime(au):
                continue
            w = json.load(open(f))[0]['words'][0]
            return float(w[1])
        except Exception:
            continue
    return None
