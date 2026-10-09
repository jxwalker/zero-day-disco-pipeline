#!/usr/bin/env python3
"""strict_qc.py (25 Oct 2026, the owner: "Why does she have wrenches on her shirt. Why does she put a floppy wrench in her
pocket. We need better quality control.")  Shared, fail-closed artefact QC for EVERY clip route (LTX, Wan, Runway, Grok)
and for the final cut before READY_TO_POST.

Root cause it fixes: clips were judged on 1-2 frames (Grok route: one frame 1.2 s from the end; v3 regen: 1.5 s and
4.5 s; clip_qc: 6 frames), by a single Opus reviewer whose rubric was about laptops/screens/faces, with no rule for
rigid props bending, wardrobe graphics, or hand-prop actions, and the checker failed OPEN when unavailable.

  strict_qc.py clip <clip.mp4> --prompt "..." [--wardrobe "..."] [--still s.png] [--tier hero|broll|prop]
  strict_qc.py cut  <video.mp4> [--wardrobe "..."] [--out qc_cut.json]        # whole-video 2 fps review
  strict_qc.py lint-prompt "<prompt>"                                          # pocket/prop-action + wardrobe-graphic lint
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'grok_video'))

STEP = float(os.environ.get('QC_STEP', 0.25))        # clip sampling interval (s)
CUT_FPS = float(os.environ.get('QC_CUT_FPS', 2))     # final-cut sampling rate
TILE_COLS, TILE_ROWS, TILE_W = 4, 3, 360
GROK = os.environ.get('GROK_BIN', '/home/box/.grok/bin/grok')
GROK_OFF = ('web_search,web_fetch,Agent,image_gen,image_edit,image_to_video,reference_to_video,run_terminal_command,'
            'write,search_replace,todo_write,monitor,workflow,use_tool,search_tool')

PROP_WORDS = r"spanner|wrench|hammer|plier|screwdriver|tool|knife|key|watch|strap|phone|cup|mug|bag|grapes|card|bottle|pen|iron|board|guitar|mic"
POCKET_RE = re.compile(r"\bpocket(s|ed|ing)?\b|\btuck(s|ed|ing)?\b|\bholster|\bsheath|\bslips? \w+ (in|into)\b|"
                       r"\bclip(s|ped|ping)?\b[^.;]{0,80}\b(tool ?loop|belt|pocket|waistband|lanyard)|"
                       r"\bhang(s|ing)?\b[^.;]{0,60}\b(peg ?board|hook|belt|outline)|\bwith (her|his) teeth\b", re.I)
GRAPHIC_WARDROBE_RE = re.compile(r"(\w+[- ]?(shaped|print|printed|pattern|patterned|motif|patch(es)?|logo|graphic|embroider\w*|appliqu\w*|badge|decal))|"
                                 r"(stitched|embroidered|printed|painted) \w+ (patch(es)?|motif|print|graphic)", re.I)

CHECKS = {
  "prop_rigidity": "Any rigid object (spanner, wrench, tool, watch body, phone, cup, card, board, instrument) bends, flexes, "
                   "goes rubbery/floppy, melts, stretches, changes size, shape, colour or count between frames, splits, "
                   "merges, appears from nowhere, vanishes, or passes through a hand, body, cloth or surface. Rigid tools "
                   "MUST stay rigid and the same size in every frame. FAIL on any frame-to-frame change.",
  "wardrobe_spec": "Clothing differs from the WARDROBE SPEC (garment, colour, fit) or changes between frames; ANY print, "
                   "patch, embroidery, logo, badge, pattern or graphic on clothing that is not literally in the spec - "
                   "especially tool, wrench, spanner or prop-shaped graphics, which ALWAYS fail even if the spec mentions them; "
                   "garments merging, extra pockets/straps/belts appearing.",
  "hand_prop_interaction": "Hands gripping, pocketing, clipping, hanging, handing over or putting away an object: the "
                   "object must keep its shape and be physically held (fingers around it, not fused), go into a real "
                   "opening, and not deform, sink into fabric, morph into a strap/cloth, or swap hands. Any pocketing/"
                   "clipping/holstering action that is not perfectly clean fails.",
  "hands_objects": "Malformed, melted, extra or missing fingers; extra limbs or extra hands; duplicated accessories (two watches).",
  "framing": "Camera overshoot, crop on chin/forehead, landing on an awkward body part, subject leaving frame, or shot size "
             "clearly different from the prompt (e.g. prompt says hip close-up, clip is a full figure).",
  "face_drift": "Face, hair, age or identity changes between frames or vs the start still; extra or vanishing people.",
  "tongue_or_pulled_face": "Tongue out, gurning, pouting, duck face, bratty or pulled expression.",
  "eyewear": "Any glasses or eyewear on the lead, or eyewear artefacts.",
  "text_flipped": "Visible text upside down or mirrored anywhere; large or in-focus text garbled.",
  "physics_continuity": "Background objects or furniture morphing, popping, sliding; liquids, cloth or hair behaving impossibly; "
                        "a scene cut or jump inside the clip.",
  "prompt_fidelity": "The action and camera move in the prompt is clearly what happens; no invented props or actions.",
}
SCHEMA = {"type": "object", "required": ["checks", "ok", "worst_frames"], "properties": {
    "checks": {"type": "object", "required": list(CHECKS), "properties": {k: {"type": "object", "required": ["pass", "note", "times"],
        "properties": {"pass": {"type": "boolean"}, "note": {"type": "string"}, "times": {"type": "array", "items": {"type": "string"}}}} for k in CHECKS}},
    "ok": {"type": "boolean"}, "worst_frames": {"type": "array", "items": {"type": "string"}}}}
CUT_SCHEMA = {"type": "object", "required": ["flags", "ok"], "properties": {
    "ok": {"type": "boolean"}, "flags": {"type": "array", "items": {"type": "object", "required": ["time", "check", "issue"],
        "properties": {"time": {"type": "string"}, "check": {"type": "string"}, "issue": {"type": "string"}}}}}}


# ------------------------------------------------------------------ frames + contact sheets
def probe_dur(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p], capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except ValueError: return 0.0

def sheets(video, outdir, step=None, fps=None, t0=0.0, t1=None, w=TILE_W, prefix='sheet'):
    """Dense frames (every `step` s or at `fps`) stamped with their timestamp, tiled 4x3 per sheet. Returns sheet paths."""
    from PIL import Image, ImageDraw
    os.makedirs(outdir, exist_ok=True)
    dt = 1.0 / fps if fps else (step or STEP)
    t1 = t1 if t1 is not None else probe_dur(video)
    fd = os.path.join(outdir, prefix + '_frames'); os.makedirs(fd, exist_ok=True)
    for f in glob.glob(os.path.join(outdir, f'{prefix}_*.jpg')) + glob.glob(os.path.join(fd, '*.jpg')): os.remove(f)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t0:.3f}', '-t', f'{max(0.05, t1 - t0 - 0.01):.3f}', '-i', video,
                    '-vf', f'fps=1/{dt},scale={w}:-2', '-q:v', '3', os.path.join(fd, 'f%04d.jpg')], check=True)
    fr = sorted(glob.glob(os.path.join(fd, 'f*.jpg'))); out = []; n = TILE_COLS * TILE_ROWS
    for si in range(0, len(fr), n):
        ims = [Image.open(p).convert('RGB') for p in fr[si:si + n]]
        tw, th = ims[0].size; S = Image.new('RGB', (TILE_COLS * (tw + 4), TILE_ROWS * (th + 4)), 'white')
        for k, im in enumerate(ims):
            ts = t0 + (si + k) * dt; dr = ImageDraw.Draw(im); lab = f"{int(ts // 60)}:{ts % 60:05.2f}"
            dr.rectangle([0, 0, 92, 22], fill='black'); dr.text((5, 4), lab, fill='yellow')
            S.paste(im, ((k % TILE_COLS) * (tw + 4), (k // TILE_COLS) * (th + 4)))
        p = os.path.join(outdir, f'{prefix}_{si // n + 1:03d}.jpg'); S.save(p, quality=85); out.append(p)
    return out


# ------------------------------------------------------------------ reviewers
def _prompt(files, shot_prompt, wardrobe, tier, role):
    lens = ("You are reviewer A, a strict VFX artefact QC supervisor." if role == 'A' else
            "You are reviewer B, an independent adversarial checker. Assume there IS at least one artefact and hunt for "
            "it frame by frame; compare every frame with the previous one, focusing on props, hands and clothing.")
    broll = ("B-ROLL EXCEPTION: fuzzy/garbled text on a small or out-of-focus screen (<5% of frame) is allowed; "
             "upside-down or mirrored text still fails.\n" if tier == 'broll' else "")
    return (lens + " These contact sheets are consecutive frames of ONE AI-generated music-video clip, sampled every "
            f"{STEP} s, in reading order, each stamped with its timestamp. Read EVERY sheet (and start_still if listed). "
            "Fail a check on ANY doubt; when unsure, fail. For each failed check give the timestamps.\n\nCHECKS:\n"
            + "\n".join(f"- {k}: {v}" for k, v in CHECKS.items()) + "\n" + broll
            + f"\nWARDROBE SPEC (plain solid garments; anything else on clothing fails): {wardrobe or 'not given - flag any clothing graphic at all'}"
            + f"\nSHOT PROMPT: {shot_prompt}\nok = every check passes. worst_frames = timestamps of the worst frames.\n\nFILES (absolute paths):\n"
            + "\n".join(files))

def review_claude(files, text, cwd, schema=SCHEMA, timeout=600):
    import slop_opus as SO
    pf = os.path.join(cwd, f'qcA_{os.getpid()}_{time.time_ns()}.txt'); open(pf, 'w').write(text)
    res, _ = SO.run_claude(pf, cwd, schema, timeout, tools='Read', effort='high')
    return res

def review_grok(files, text, cwd, schema=SCHEMA, timeout=600):
    pf = os.path.join(cwd, f'qcB_{os.getpid()}_{time.time_ns()}.txt')
    open(pf, 'w').write(text + "\n\nUse read_file on every file. Reply with ONE JSON object only, matching this schema:\n" + json.dumps(schema))
    r = subprocess.run([GROK, '--prompt-file', pf, '--output-format', 'json', '-m', os.environ.get('QC_GROK_MODEL', 'grok-4.7'),
                        '--effort', 'high', '--max-turns', str(3 * len(files) + 10), '--always-approve', '--disallowed-tools', GROK_OFF,
                        '--cwd', cwd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(f'grok rc {r.returncode}: {(r.stderr or r.stdout)[-300:]}')
    t = json.loads(r.stdout).get('text', '')
    m = re.search(r'\{.*\}', t, re.S)
    return json.loads(m.group(0)) if m else None

def _norm(res):
    """Fail closed: missing/empty reply or any failing check = not ok."""
    if not res or 'checks' not in res: return {'ok': False, 'reasons': ['reviewer gave no usable reply'], 'checks': {}}
    ch = res.get('checks', {})
    missing = [k for k in CHECKS if k not in ch]
    fails = {k: v for k, v in ch.items() if not v.get('pass')}
    res['ok'] = bool(res.get('ok')) and not fails and not missing
    res['reasons'] = [f"{k} @{','.join(v.get('times', []))}: {v.get('note', '')}" for k, v in fails.items()] + [f'{k}: not answered' for k in missing]
    return res

def needs_two(prompt, tier):
    return tier in ('hero', 'prop') or bool(re.search(PROP_WORDS, prompt or '', re.I))


# ------------------------------------------------------------------ public API
def qc_clip(clip, prompt, wardrobe='', still=None, tier='hero', workdir=None):
    """Dense-frame, two-reviewer (hero/prop shots), fail-closed QC. Returns {'ok', 'reasons', 'A', 'B', 'sheets'}."""
    d = workdir or tempfile.mkdtemp(prefix='sqc_', dir=os.path.dirname(os.path.abspath(clip)))
    sh = sheets(clip, d, step=STEP)
    files = sh + ([os.path.abspath(still)] if still else [])
    t0 = time.time(); out = {'sheets': sh, 'frames_dir': d}
    jobs = {'A': (review_claude, 'A')} | ({'B': (review_grok, 'B')} if needs_two(prompt, tier) else {})
    with ThreadPoolExecutor(2) as ex:
        fut = {k: ex.submit(fn, files, _prompt(files, prompt, wardrobe, tier, role), d) for k, (fn, role) in jobs.items()}
        for k, f in fut.items():
            try: out[k] = _norm(f.result())
            except Exception as e: out[k] = {'ok': False, 'reasons': [f'reviewer {k} unavailable: {str(e)[:150]}']}
    out['ok'] = all(out[k]['ok'] for k in jobs)        # BOTH must pass
    out['reasons'] = [f"[{k}] {r}" for k in jobs for r in out[k].get('reasons', [])]
    out['reviewers'] = list(jobs); out['qc_s'] = round(time.time() - t0)
    json.dump(out, open(os.path.join(d, 'strict_qc.json'), 'w'), indent=1)
    return out

def qc_cut(video, wardrobe='', out=None, chunk_s=30.0):
    """Whole final cut at CUT_FPS, both reviewers, chunked. Any flag = fail (READY_TO_POST must not be written)."""
    d = os.path.join(os.path.dirname(os.path.abspath(video)), 'qc_cut'); os.makedirs(d, exist_ok=True)
    dur = probe_dur(video); flags = []; ok = True; t = 0.0; i = 0
    while t < dur:
        sh = sheets(video, d, fps=CUT_FPS, t0=t, t1=min(dur, t + chunk_s), prefix=f'cut{i:02d}')
        text = ("Whole-video artefact review of the FINAL CUT of an AI music video, frame by frame at "
                f"{CUT_FPS} fps (timestamps burnt in). Karaoke lyrics, code-rendered graphic cards and the end card are "
                "intentional. Flag EVERY frame with an AI artefact, using these checks:\n" + "\n".join(f"- {k}: {v}" for k, v in CHECKS.items() if k != 'prompt_fidelity')
                + f"\nWARDROBE SPEC: {wardrobe or 'plain solid garments, no prints'}\nok=false if any flag. FILES:\n" + "\n".join(sh))
        for name, fn in (('A', review_claude), ('B', review_grok)):
            try:
                r = fn(sh, text, d, schema=CUT_SCHEMA)
                if not r: raise RuntimeError('empty')
                for f in r.get('flags', []): flags.append(dict(f, reviewer=name))
                ok = ok and bool(r.get('ok')) and not r.get('flags')
            except Exception as e:
                ok = False; flags.append({'time': f'{t:.0f}s', 'check': 'reviewer', 'issue': f'{name} unavailable: {str(e)[:120]}', 'reviewer': name})
        t += chunk_s; i += 1
    res = {'ok': ok, 'flags': flags, 'video': video, 'fps': CUT_FPS, 't': time.strftime('%Y-%m-%d %H:%M:%S')}
    json.dump(res, open(out or os.path.join(d, 'qc_cut.json'), 'w'), indent=1)
    return res

def lint_prompt(prompt):
    """Pre-generation lint. Returns problems; any problem -> rewrite the action or swap the shot for a graphic card."""
    p = []
    if POCKET_RE.search(prompt or ''): p.append('prop-in-pocket/clip/holster action: avoid, or swap this shot for a graphic card')
    if GRAPHIC_WARDROBE_RE.search(prompt or ''): p.append('wardrobe graphic (patch/print/logo/motif): use plain solid garments only')
    return p

PLAIN_RULE = " All garments plain and solid-coloured: no prints, patches, embroidery, logos or graphics on any clothing."
GRAPHIC_STRIP_RE = re.compile(r"\s*[,;]?\s*(with|featuring)?\s*(hand-)?(stitched|embroidered|printed|painted)?\s*[\w-]*\s*[\w-]*\s*(patch(es)?|motifs?|prints?|logos?|graphics?|badges?|decals?)(\s*\(no logos\))?", re.I)

def strip_graphics(text):
    """Remove wardrobe graphics (patches, prints, logos, motifs) from any prompt text."""
    return GRAPHIC_STRIP_RE.sub('', text or '')

def plain_wardrobe(text):
    """Strip prints, patches, logos and prop-shaped graphics from a wardrobe description; add the plain-garment rule."""
    t = re.sub(r"\s*(,|;)?\s*(with|featuring)?\s*(hand-)?(stitched|embroidered|printed|painted)?\s*[\w-]*\s*[\w-]*\s*(patch(es)?|motifs?|prints?|logos?|graphics?|badges?|decals?)(\s*\(no logos\))?", '', text or '', flags=re.I)
    return t.strip(' ,;') + ". All garments plain and solid-coloured: no prints, patches, embroidery, logos or graphics on any clothing."

def write_ready(day, video, wardrobe=''):
    """The ONLY sanctioned way to write READY_TO_POST: runs qc_cut first and refuses on any flag."""
    r = qc_cut(video, wardrobe)
    if not r['ok']:
        open(os.path.join(day, 'QC_FAILED'), 'w').write(json.dumps(r['flags'], indent=1)); return False
    open(os.path.join(day, 'READY_TO_POST'), 'w').write(f"qc_cut ok {r['t']} {video}\n"); return True

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['clip', 'cut', 'lint-prompt', 'ready'])
    ap.add_argument('target'); ap.add_argument('--prompt', default=''); ap.add_argument('--wardrobe', default='')
    ap.add_argument('--still'); ap.add_argument('--tier', default='hero', choices=['hero', 'broll', 'prop']); ap.add_argument('--out'); ap.add_argument('--video')
    a = ap.parse_args()
    if a.cmd == 'clip': print(json.dumps(qc_clip(a.target, a.prompt, a.wardrobe, a.still, a.tier), indent=1))
    elif a.cmd == 'cut': print(json.dumps(qc_cut(a.target, a.wardrobe, a.out), indent=1))
    elif a.cmd == 'ready': print(write_ready(a.target, a.video, a.wardrobe))
    else: print(json.dumps(lint_prompt(a.target)))
