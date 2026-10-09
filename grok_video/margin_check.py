"""Safe-area check (20 Oct 2026, the owner: 'some of the text is cut off at the margins').
Fails if any text/graphic pixels fall outside the title-safe rect: 6% left/right, 5% top, and bottom 15% on vertical
(X UI) / 5% on 16:9. Checks (a) the lyric/chip ASS layer rendered alone on black at 4 fps over the whole song, and
(b) every graphic template + the end card rendered at the longest real strings (from the plan and today's stories)."""
import json, os, subprocess, sys
import numpy as np
import kgfx2 as K


def _bad(bb, W, H, tol=2):
    x0, y0, x1, y1 = K.safe_rect(W, H)
    return bb is not None and (bb[0] < x0 - tol or bb[1] < y0 - tol or bb[2] > x1 + tol or bb[3] > y1 + tol)


def check_ass(assf, W, H, dur, fps=4):
    lines = [l for l in open(assf) if not l.startswith('Dialogue: 0,') or ',Band,' not in l]
    tmp = assf + '.nobband.ass'; open(tmp, 'w').writelines(lines)
    cmd = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=black:s={W}x{H}:r={fps}:d={dur:.2f}', '-vf', f"ass='{tmp}'",
           '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE); n = 0; fails = []; worst = [W, H, 0, 0]
    while True:
        b = p.stdout.read(W * H)
        if len(b) < W * H: break
        a = np.frombuffer(b, np.uint8).reshape(H, W) > 40
        ys, xs = np.nonzero(a)
        if len(xs):
            bb = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            worst = [min(worst[0], bb[0]), min(worst[1], bb[1]), max(worst[2], bb[2]), max(worst[3], bb[3])]
            if _bad(bb, W, H): fails.append({'t': round(n / fps, 2), 'bbox': bb})
        n += 1
    p.wait(); os.remove(tmp)
    return {'frames': n, 'fails': fails[:20], 'n_fail': len(fails), 'union_bbox': worst, 'safe': K.safe_rect(W, H)}


def longest(xs): return max([str(x) for x in xs if x] or [''], key=len)


def samples(plan, stories, lyrics):
    """Per template: every p used in the plan, plus a synthetic worst case built from the longest real strings."""
    used = {}
    for v in [v for ln in plan.get('lines', []) for v in ln.get('v', [])] + plan.get('intro', []) + plan.get('breaks', []) + plan.get('outro', []):
        if v.get('kind') == 'gfx': used.setdefault('terminal' if v['g'] == 'term' else v['g'], []).append(v.get('p') or {})
    S = longest(stories); Lg = longest(lyrics); F_ = longest([ln.get('fact') for ln in plan.get('lines', [])]) or S
    w = max(Lg.split() + S.split(), key=len)
    syn = {
        'headline': {'kicker': 'MAIN STORY', 'text': S[:90], 'sub': Lg},
        'bignum': {'top': S[:60], 'value': '1,000,000,000', 'sub': Lg},
        'bars': {'title': S[:60], 'items': [{'label': x[:40], 'value': 10 ** (i + 1), 'show': f'{10 ** (i + 1):,}'} for i, x in enumerate([S, Lg, F_, w])]},
        'post': {'handle': 'averyveryverylonghandle', 'name': S[:40], 'text': S[:140], 'stat': '12,345 reposts'},
        'feed': {'title': S[:50], 'items': [{'handle': 'averyverylonghandle', 'text': x[:120], 'metric': '99,999'} for x in (S, Lg, F_, S)]},
        'inbox': {'folder': 'Spam', 'rows': [{'from': x[:40], 'subject': y[:90], 'flag': 'SPAM'} for x, y in ((S, Lg), (Lg, S), (F_, S), (w, Lg))], 'stamp': w.upper()},
        'chat': {'title': S[:50], 'msgs': [{'who': ('me', 'them')[i % 2], 'name': 'Alex', 'text': x[:140]} for i, x in enumerate((S, Lg, F_, S))]},
        'code': {'file': 'a_really_long_module_name_for_tests.py', 'lines': [(x + ' ' * 40)[:34] for x in (S, Lg, F_, S, Lg, F_, S, Lg, F_)]},
        'terminal': {'title': S[:60], 'lines': [['cmd', S[:38]], ['out', Lg[:38]], ['err', F_[:38]], ['warn', S[:38]], ['dim', Lg[:38]]], 'stamp': w.upper()},
        'rows': {'title': S[:60], 'rows': [[x[:30], y[:30], '1,234,567', 'red'] for x, y in ((S, Lg), (Lg, F_), (F_, S), (S, Lg), (Lg, S), (F_, Lg))]},
        'stamp': {'above': S[:70], 'text': w.upper()[:16]},
        'quote': {'text': S[:200], 'by': '@averyverylonghandle'},
        'browser': {'url': 'https://www.example-news-site.com/2026/10/20/' + w, 'site': S[:30], 'headline': S[:90], 'lede': F_ + ' ' + Lg, 'highlight': Lg[:30]},
        'gauge': {'label': S[:50], 'value': '99.9%', 'frac': 0.999, 'sub': Lg},
        'compare': {'left': {'title': S[:30], 'lines': [S[:40], Lg[:40], F_[:40]]}, 'right': {'title': Lg[:30], 'lines': [F_[:40], S[:40], Lg[:40]]}},
        'countdown': {'top': S[:60], 'start': 3600, 'speed': 1, 'sub': Lg},
        'screen': {'device': 'laptop', 'app': 'news', 'text': S[:120], 'flag': w.upper()},
        'endcard': {'title': longest([plan.get('_title', '')]) or S[:60], 'credit': (plan.get('credit') or S)[:80]},
    }
    out = []
    for g, p in syn.items():
        out.append((g, 'synthetic-longest', p))
        if used.get(g):
            out.append((g, 'plan-longest', max(used[g], key=lambda q: len(json.dumps(q)))))
    return out


def check_gfx(plan, stories, lyrics, sizes, outdir, dur=2.6):
    from PIL import Image
    res = []; os.makedirs(outdir, exist_ok=True)
    for W, H in sizes:
        for g, kind, p in samples(plan, stories, lyrics):
            worst = None
            for t in (0.3, dur * 0.5, dur - 0.05):
                im = K.render(g, W, H, t, dur, dict(p))
                bb = K.content_bbox(im, K.base(W, H, t)[0])
                if bb: worst = bb if worst is None else (min(worst[0], bb[0]), min(worst[1], bb[1]), max(worst[2], bb[2]), max(worst[3], bb[3]))
            im.save(os.path.join(outdir, f'{g}_{kind}_{W}x{H}.png'))
            res.append({'g': g, 'case': kind, 'size': f'{W}x{H}', 'bbox': worst, 'ok': not _bad(worst, W, H)})
    return res


def run(work, plan, stories, lyrics, design_theme, dur):
    K.set_theme(design_theme)
    sizes = [(1080, 1920), (1920, 1080)]
    rep = {'gfx': check_gfx(plan, stories, lyrics, sizes, os.path.join(work, 'margin_frames')), 'ass': {}}
    for W, H in sizes:
        f = os.path.join(work, f'lyrics_{W}x{H}.ass')
        if os.path.exists(f): rep['ass'][f'{W}x{H}'] = check_ass(f, W, H, dur)
    rep['ok'] = all(r['ok'] for r in rep['gfx']) and all(a['n_fail'] == 0 for a in rep['ass'].values())
    json.dump(rep, open(os.path.join(work, 'margin_check.json'), 'w'), indent=1)
    return rep
