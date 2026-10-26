#!/usr/bin/env python3
"""clip_qc.py - strict per-clip vision QC and the
b-roll cascade LTX -> LTX re-roll (new seed) -> Wan 2.2 -> Runway (agent job) / Grok. Every failure reason is logged.

  clip_qc.py qc <clip.mp4> --prompt "..."            # QC one clip, prints JSON
  clip_qc.py broll --image s.png --prompt "..." --out clip.mp4 [--log qc_log.jsonl]
"""
import argparse, json, os, subprocess, sys, tempfile, time, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'grok_video'))
import local_gen as L

QC_SCHEMA = {"type": "object", "required": ["checks", "ok", "reasons"], "properties": {
    "checks": {"type": "object", "required": ["hands_objects", "framing", "face_drift", "tongue_or_pulled_face", "text_flipped", "prompt_fidelity"],
               "properties": {k: {"type": "object", "required": ["pass", "note"], "properties": {"pass": {"type": "boolean"}, "note": {"type": "string"}}}
                              for k in ["hands_objects", "framing", "face_drift", "tongue_or_pulled_face", "text_flipped", "prompt_fidelity"]}},
    "ok": {"type": "boolean"}, "reasons": {"type": "array", "items": {"type": "string"}}}}

def frames(clip, n=6):
    d = tempfile.mkdtemp(prefix='qc_', dir=os.path.dirname(os.path.abspath(clip)))
    dur = L.probe(clip).get('dur') or 5.0
    out = []
    for i in range(n):
        t = dur * (0.02 + 0.96 * i / (n - 1)); p = os.path.join(d, f'f{i}_{t:.1f}s.png')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', clip, '-frames:v', '1', '-vf', 'scale=432:-2', p])
        if os.path.exists(p): out.append(p)
    return d, out

def qc(clip, prompt, still=None, tier='hero', wardrobe=''):
    """delegates to strict_qc - frames every 0.25 s as contact sheets,
    prop-rigidity / wardrobe / hand-prop rules, second independent reviewer (Grok) on hero and prop shots, both must
    pass on FAIL-level checks (serious glitches), WARN-level drift is logged only (strict_qc.log), fail closed. Set QC_LEGACY=1 for the old 6-frame single reviewer."""
    if os.environ.get('QC_LEGACY') != '1':
        import strict_qc as SQ
        wardrobe = wardrobe or os.environ.get('GV_WARDROBE', '')
        return SQ.qc_clip(clip, prompt, wardrobe, still, tier)
    return _qc_legacy(clip, prompt, still, tier)

def _qc_legacy(clip, prompt, still=None, tier='hero'):
    import slop_opus as SO
    d, fs = frames(clip)
    if still: subprocess.run(['cp', still, os.path.join(d, 'start_still.png')]); 
    pf = os.path.join(d, 'qc_prompt.txt')
    open(pf, 'w').write(
        "You are a STRICT QC checker for an AI-generated music-video clip. Use the Read tool on every PNG in this directory "
        "(frames are in time order; start_still.png, if present, is the intended first frame). Fail a check on ANY doubt:\n"
        "- hands_objects: malformed, melted, extra or missing fingers; held objects (watch, spanner, bag, phone) warping, "
        "duplicating, fusing with hands or vanishing.\n- framing: camera overshoot (push-in that ends too tight, cuts off the "
        "chin/forehead, or lands on an awkward body part), lens-in-the-face close-ups, a subject leaving frame.\n"
        "- face_drift: the face, hair or outfit changes identity between frames or versus the start still.\n"
        "- tongue_or_pulled_face: any tongue out, gurning, pouting, duck face, bratty or pulled expression.\n"
        "- text_flipped: any visible text upside down, mirrored or garbled.\n" + (
        "  B-ROLL EXCEPTION: garbled or fuzzy text is ALLOWED when it sits on a small or out-of-focus "
        "screen (watch face, background monitor) covering a small part of the frame (under ~5%). Large or in-focus text "
        "must still be legible and upright; upside-down or mirrored text fails everywhere.\n" if tier == 'broll' else "") + "- prompt_fidelity: the action/camera move in the "
        "prompt is clearly what happens, with no new people, morphing or scene change.\n"
        "ok = every check passes. reasons = one short line per failed check.\n\nSHOT PROMPT: " + prompt
        + "\n\nFILES (Read each one, absolute paths):\n" + "\n".join(fs + ([os.path.join(d, 'start_still.png')] if still else [])))
    t0 = time.time()
    try:
        res, _ = SO.run_claude(pf, d, QC_SCHEMA, 420, tools='Read', effort='medium')
    except Exception as e:
        return {'ok': False, 'reasons': [f'qc unavailable: {str(e)[:150]}'], 'qc_s': round(time.time() - t0), 'frames_dir': d}
    res = res or {'ok': False, 'reasons': ['empty qc reply']}
    res['ok'] = bool(res.get('ok')) and all(c.get('pass') for c in res.get('checks', {}).values())
    res.update(qc_s=round(time.time() - t0), frames_dir=d)
    return res

def broll(image, prompt, out, log=None, seed=42, wan=True, server=L.SERVER, ltx=True):
    """Cascade for one b-roll shot. Returns a result dict; backend 'runway_job' means hand it to the hero runbook."""
    hist = []
    def note(**k):
        hist.append(k)
        if log: open(log, 'a').write(json.dumps(dict(k, out=out, t=time.strftime('%H:%M:%S'))) + '\n')
    steps = ([('ltx', seed), ('ltx', seed + 7919)] if ltx else []) + ([('wan', seed)] if wan else [])
    for be, sd in steps:
        a = types.SimpleNamespace(server=server, image=image, prompt=prompt, out=out, seed=sd, fps=24, timeout=3600,
                                  mode='draft' if be == 'ltx' else 'fast', w=720 if be == 'wan' else 736, h=1280, frames=73 if be == 'ltx' else 81)
        if be == 'wan': a.fps = 16
        t0 = time.time()
        try:
            L.render_local(a)
        except Exception as e:
            note(backend=be, seed=sd, ok=False, render_s=round(time.time() - t0, 1), reasons=[f'render failed: {str(e)[:200]}']); continue
        rs = round(time.time() - t0, 1)
        r = qc(out, a.prompt if be == 'wan' else L.gentle(prompt), still=image, tier='broll' if ltx else 'hero')
        note(backend=be, seed=sd, ok=r['ok'], render_s=rs, qc_s=r.get('qc_s'), reasons=r.get('reasons', []))
        if r['ok']:
            return {'ok': True, 'backend': be, 'seed': sd, 'history': hist}
        os.replace(out, f"{out[:-4]}.{be}{sd}.qcfail.mp4")
    note(backend='runway_job', ok=None, reasons=['local cascade exhausted; queue as Runway premium job, Grok clip is the final fallback'])
    return {'ok': False, 'backend': 'runway_job', 'history': hist}

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('cmd', choices=['qc', 'broll']); p.add_argument('clip', nargs='?')
    p.add_argument('--image'); p.add_argument('--prompt', required=True); p.add_argument('--out'); p.add_argument('--log')
    p.add_argument('--seed', type=int, default=42); p.add_argument('--tier', default='hero', choices=['hero', 'broll']); p.add_argument('--no-wan', action='store_true')
    a = p.parse_args()
    print(json.dumps(qc(a.clip, a.prompt, a.image, a.tier) if a.cmd == 'qc' else broll(a.image, a.prompt, a.out, a.log, a.seed, not a.no_wan)))
