"""Themed karaoke graphics (v2, 20 Oct 2026). Every renderer: f(W, H, t, dur, p) -> RGB image, styled by the per-video
theme (design.theme): palette, fonts, texture. Story-domain templates; exact text from the plan only.
Graphics keep the lower ~36% of the frame calm for the lyrics."""
import math, random, re
from PIL import Image, ImageDraw, ImageFont
T = {}
_fc = {}


def set_theme(th): T.clear(); T.update(th)
def F(kind, s):
    k = (kind, int(s))
    if k not in _fc: _fc[k] = ImageFont.truetype(T[kind], max(8, int(s)))
    return _fc[k]
def U(W, H): return min(W, H) / 1080
def C(n, d='ink'):
    n = str(n or '').lower()
    m = {'red': 'bad', 'green': 'good', 'amber': 'a3', 'yellow': 'a3', 'blue': 'a2', 'cyan': 'a3', 'pink': 'a1', 'white': 'ink'}
    return T.get(m.get(n, n), T.get(d)) if n else T[d]
def top0(W, H): return H * (0.13 if H > W else 0.15)   # below the story chip
def zone(W, H): return H * (0.60 if H > W else 0.64)
def ease(x): x = max(0, min(1, x)); return 1 - (1 - x) ** 3


def base(W, H, t=0):
    im = Image.new('RGB', (W, H), T['bg']); d = ImageDraw.Draw(im); u = U(W, H); tx = T.get('texture')
    sh = tuple(max(0, min(255, c + (-10 if T['light'] else 10))) for c in T['bg'])
    if tx == 'grid':
        for x in range(0, W, int(60 * u)): d.line([(x, 0), (x, H)], fill=sh)
        for y in range(0, H, int(60 * u)): d.line([(0, y), (W, y)], fill=sh)
    elif tx == 'halftone':
        for y in range(0, H, int(26 * u)):
            for x in range(0, W, int(26 * u)):
                r = 3 * u * (0.4 + 0.6 * y / H); d.ellipse([x - r, y - r, x + r, y + r], fill=sh)
    elif tx == 'scanlines':
        for y in range(0, H, 4): d.line([(0, y), (W, y)], fill=sh)
    elif tx in ('paper', 'grain'):
        random.seed(int(t * 12))
        for _ in range(int(W * H / 900)):
            x, y = random.randrange(W), random.randrange(H); d.point((x, y), fill=sh)
    return im, d


def wrap(d, s, font, maxw):
    out, cur = [], ''
    for w in str(s).split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=font) <= maxw or not cur: cur = t
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    return out


def fit(d, s, kind, size, maxw, maxlines, minsize=22):
    while size > minsize:
        f = F(kind, size); ls = wrap(d, s, f, maxw)
        if len(ls) <= maxlines and all(d.textlength(l, font=f) <= maxw for l in ls): return f, ls
        size = int(size * 0.9)
    f = F(kind, minsize); return f, wrap(d, s, f, maxw)[:maxlines]


def card(d, box, fill=None, u=1.0, accent=None):
    x0, y0, x1, y1 = box; o = int(8 * u)
    d.rectangle([x0 + o, y0 + o, x1 + o, y1 + o], fill=accent or T['a2'])        # offset "print" shadow
    d.rectangle(box, fill=fill or T['panel'], outline=T['ink'], width=max(2, int(4 * u)))


def slide_in(t, k=0, dist=80):
    return (1 - ease((t - 0.08 * k) / 0.35)) * dist


# ---------------------------------------------------------------- templates
def headline(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.08; mw = W * 0.84; y = top0(W, H)
    if p.get('kicker'):
        fk = F('mono', 34 * u); tw = d.textlength(p['kicker'], font=fk)
        d.rectangle([x0, y, x0 + tw + 36 * u, y + 60 * u], fill=C(p.get('color'), 'a1'))
        d.text((x0 + 18 * u, y + 30 * u), p['kicker'], font=fk, fill=T['bg'] if not T['light'] else T['panel'], anchor='lm'); y += 100 * u
    f, ls = fit(d, p.get('text', ''), 'display', int(104 * u), mw, 5 if H > W else 3)
    for i, l in enumerate(ls):
        dx = slide_in(t, i, 120 * u); d.text((x0 - dx, y + i * f.size * 1.12), l, font=f, fill=T['ink'])
    y += len(ls) * f.size * 1.12 + 30 * u
    if p.get('sub') and t > 0.4:
        fs, sl = fit(d, p['sub'], 'mono', int(40 * u), mw, 3)
        for i, l in enumerate(sl): d.text((x0, y + i * fs.size * 1.35), l, font=fs, fill=C(p.get('color'), 'a2'))
    return im


def bignum(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); cy = H * (0.28 if H > W else 0.32)
    v = str(p.get('value', '')); m = re.fullmatch(r'([^\d]*)([\d,]+)(.*)', v); shown = v
    if m and t < 0.5:
        n = int(m.group(2).replace(',', '')); cur = int(round(n * ease(t / 0.5)))
        shown = m.group(1) + (f"{cur:,}" if ',' in m.group(2) else str(cur)) + m.group(3)
    r = min(W, H) * 0.34 * (0.9 + 0.1 * ease(t / 0.3))
    d.ellipse([W / 2 - r, cy - r, W / 2 + r, cy + r], fill=C(p.get('color'), 'a1'))
    f, _ = fit(d, v, 'display', int(240 * u), r * 1.7, 1, 50)
    d.text((W / 2, cy), shown, font=f, fill=T['panel'] if not T['light'] else T['ink'] if sum(C(p.get('color'), 'a1')) > 500 else (255, 255, 255), anchor='mm')
    d.text((W / 2, cy - r - 50 * u), p.get('top', ''), font=F('body', 54 * u), fill=T['ink'], anchor='mm')
    fs, sl = fit(d, p.get('sub', ''), 'mono', int(42 * u), W * 0.86, 2)
    for i, l in enumerate(sl): d.text((W / 2, cy + r + 50 * u + i * fs.size * 1.35), l, font=fs, fill=T['ink'], anchor='mm')
    return im


def bars(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); items = p.get('items', [])[:5]
    y = top0(W, H); d.text((W * 0.06, y), p.get('title', ''), font=F('display', 64 * u), fill=T['ink']); y += 120 * u
    mx = max([float(i.get('value', 0) or 0) for i in items] + [1]); bh = 84 * u; gap = 60 * u; bw = W * 0.66
    for k, it in enumerate(items):
        yy = y + k * (bh + gap + 40 * u); g = ease((t - 0.12 * k) / 0.7)
        d.text((W * 0.06, yy), str(it.get('label', '')), font=F('body', 38 * u), fill=T['ink'])
        w = bw * float(it.get('value', 0) or 0) / mx * g; c = C(it.get('color'), ['a1', 'a2', 'a3', 'good'][k % 4])
        d.rectangle([W * 0.06, yy + 46 * u, W * 0.06 + max(8, w), yy + 46 * u + bh], fill=c, outline=T['ink'], width=3)
        d.text((W * 0.06 + w + 16 * u, yy + 46 * u + bh / 2), str(it.get('show', it.get('value'))), font=F('display', 54 * u), fill=T['ink'], anchor='lm')
    return im


def post(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.07; mw = W * 0.86; y = top0(W, H) + slide_in(t, 0, 60 * u)
    ch = zone(W, H) - top0(W, H) - 40 * u
    card(d, [x0, y, x0 + mw, y + ch], u=u)
    h = p.get('handle', '').lstrip('@'); r = 44 * u
    d.ellipse([x0 + 34 * u, y + 34 * u, x0 + 34 * u + 2 * r, y + 34 * u + 2 * r], fill=T['a1'])
    d.text((x0 + 34 * u + r, y + 34 * u + r), (h[:1] or '?').upper(), font=F('display', 44 * u), fill=T['panel'], anchor='mm')
    d.text((x0 + 140 * u, y + 40 * u), p.get('name', h), font=F('body', 42 * u), fill=T['ink'])
    d.text((x0 + 140 * u, y + 92 * u), '@' + h, font=F('mono', 30 * u), fill=T['muted'])
    txt = p.get('text', ''); n = int(len(txt) * min(1, t / max(0.4, dur * 0.45)))
    f, ls = fit(d, txt, 'body', int(58 * u), mw - 80 * u, 7 if H > W else 4)
    shown = 0; yy = y + 170 * u
    for l in ls:
        d.text((x0 + 40 * u, yy), l[:max(0, n - shown)], font=f, fill=T['ink']); shown += len(l) + 1; yy += f.size * 1.25
    if p.get('stat') and t > dur * 0.4:
        d.text((x0 + 40 * u, y + ch - 70 * u), p['stat'], font=F('mono', 36 * u), fill=T['a2'])
    return im


def feed(W, H, t, dur, p):
    """Scrolling social timeline: items [{handle, text, metric}] (metric e.g. 'active seconds: all-time high')."""
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.08; mw = W * 0.84
    items = p.get('items', [])[:4] or [{'handle': 'x', 'text': ''}]
    off = ease(t / max(0.6, dur)) * 200 * u; y = top0(W, H) - off
    if p.get('title'):
        d.text((x0, top0(W, H) - 60 * u), p['title'], font=F('display', 46 * u), fill=T['a1'])
    for k, it in enumerate(items * 2):
        hgt = 230 * u
        if y > zone(W, H): break
        if y + hgt > top0(W, H) - 10 * u:
            card(d, [x0, y, x0 + mw, y + hgt - 24 * u], u=u, accent=[T['a1'], T['a2'], T['a3']][k % 3])
            d.text((x0 + 26 * u, y + 20 * u), '@' + it.get('handle', '').lstrip('@'), font=F('mono', 30 * u), fill=T['muted'])
            f, ls = fit(d, it.get('text', ''), 'body', int(42 * u), mw - 52 * u, 2)
            for i, l in enumerate(ls): d.text((x0 + 26 * u, y + 64 * u + i * f.size * 1.2), l, font=f, fill=T['ink'])
            if it.get('metric'): d.text((x0 + mw - 26 * u, y + hgt - 70 * u), it['metric'], font=F('mono', 28 * u), fill=T['a2'], anchor='ra')
        y += hgt
    return im


def inbox(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.06; mw = W * 0.88; y = top0(W, H) - 20 * u
    spam = p.get('folder', '').lower() == 'spam'
    d.rectangle([x0, y, x0 + mw, y + 86 * u], fill=T['bad'] if spam else T['a2'], outline=T['ink'], width=3)
    d.text((x0 + 30 * u, y + 43 * u), ('⚠ ' if False else '') + p.get('folder', 'Inbox'), font=F('display', 46 * u), fill=(255, 255, 255), anchor='lm')
    y += 110 * u; rh = 140 * u
    for k, r in enumerate(p.get('rows', [])[:4]):
        if t < 0.15 * k: break
        yy = y + k * rh + slide_in(t, k, 40 * u)
        card(d, [x0, yy, x0 + mw, yy + rh - 22 * u], u=u * 0.6)
        d.text((x0 + 24 * u, yy + 16 * u), str(r.get('from', ''))[:30], font=F('body', 38 * u), fill=T['ink'])
        d.text((x0 + 24 * u, yy + 66 * u), str(r.get('subject', ''))[:40], font=F('mono', 30 * u), fill=T['muted'])
        if r.get('flag'):
            fb = F('mono', 28 * u); fl = str(r['flag']); tw = d.textlength(fl, font=fb)
            d.rectangle([x0 + mw - tw - 52 * u, yy + 18 * u, x0 + mw - 18 * u, yy + 64 * u], fill=T['bad'])
            d.text((x0 + mw - 35 * u - tw / 2, yy + 41 * u), fl, font=fb, fill=(255, 255, 255), anchor='mm')
    if p.get('stamp') and t > dur * 0.5: stamp_over(im, t - dur * 0.5, p['stamp'], 'bad')
    return im


def chat(W, H, t, dur, p):
    """Message bubbles: msgs [{who: 'me'|'them', name, text}]."""
    im, d = base(W, H, t); u = U(W, H); y = top0(W, H)
    if p.get('title'):
        d.text((W / 2, y), p['title'], font=F('body', 40 * u), fill=T['muted'], anchor='mm'); y += 60 * u
    for k, m in enumerate(p.get('msgs', [])[:5]):
        if t < 0.45 * k: break
        me = m.get('who') == 'me'; f, ls = fit(d, m.get('text', ''), 'body', int(44 * u), W * 0.6, 3)
        bw = max(d.textlength(l, font=f) for l in ls) + 60 * u; bh = len(ls) * f.size * 1.25 + 40 * u
        x = W * 0.92 - bw if me else W * 0.08
        if y + bh > zone(W, H): break
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=int(30 * u), fill=T['a2'] if me else T['panel'], outline=T['ink'], width=3)
        for i, l in enumerate(ls): d.text((x + 30 * u, y + 20 * u + i * f.size * 1.25), l, font=f, fill=(255, 255, 255) if me else T['ink'])
        if m.get('name') and not me: d.text((x + 10 * u, y - 34 * u), m['name'], font=F('mono', 26 * u), fill=T['muted'])
        y += bh + 56 * u
    return im


def code(W, H, t, dur, p):
    """Editor window themed to the palette (not green-on-black)."""
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.06; mw = W * 0.88; y0 = top0(W, H) - 20 * u; bh = zone(W, H) - y0 - 30 * u
    card(d, [x0, y0, x0 + mw, y0 + bh], u=u)
    d.rectangle([x0, y0, x0 + mw, y0 + 60 * u], fill=T['a1'], outline=T['ink'], width=3)
    d.text((x0 + 24 * u, y0 + 30 * u), p.get('file', 'main.c'), font=F('mono', 30 * u), fill=(255, 255, 255), anchor='lm')
    kw = re.compile(r'\b(IDENTIFICATION|DIVISION|PROCEDURE|DISPLAY|MOVE|PERFORM|PROGRAM-ID|STOP|RUN|END|IF|THEN|ELSE|PROGRAM|SUBROUTINE|def|return|import|from|int|void|char|if|for|while|function|const|let|class|Sub|Dim|As|PRINT|CALL)\b')
    fs = 36 * u; f = F('mono', fs); clock = t * p.get('cps', 50) + 3; y = y0 + 90 * u
    for i, l in enumerate(p.get('lines', [])[:12]):
        if clock <= 0 or y > y0 + bh - fs: break
        s = l[:int(clock)]; clock -= len(l) + 3
        d.text((x0 + 22 * u, y), f"{i + 1:>2}", font=f, fill=T['muted']); x = x0 + 90 * u
        for tok in re.split(r'(\s+)', s):
            c = T['a2'] if kw.fullmatch(tok.strip('.')) else (T['good'] if tok.startswith(('"', "'")) else T['muted'] if tok.startswith(('*', '#', '//')) else T['ink'])
            d.text((x, y), tok, font=f, fill=c); x += d.textlength(tok, font=f)
        y += fs * 1.45
    return im


def terminal(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.06; mw = W * 0.88; y0 = top0(W, H) - 20 * u; bh = zone(W, H) * 0.8 - y0
    card(d, [x0, y0, x0 + mw, y0 + bh], fill=T['ink'] if T['light'] else T['panel'], u=u)
    d.text((x0 + 24 * u, y0 + 22 * u), p.get('title', 'user@host: ~'), font=F('mono', 28 * u), fill=T['muted'])
    fg = T['panel'] if T['light'] else T['ink']
    fs = 36 * u; f = F('mono', fs); y = y0 + 80 * u; clock = t * p.get('cps', 34) + 4
    for kind, txt in p.get('lines', []):
        if clock <= 0 or y > y0 + bh - fs: break
        col = {'cmd': fg, 'out': T['a3'], 'err': T['bad'], 'warn': T['a1'], 'dim': T['muted']}.get(kind, fg)
        if kind == 'cmd':
            n = int(min(len(txt), clock)); clock -= len(txt) + 6; d.text((x0 + 28 * u, y), '$ ' + txt[:n], font=f, fill=col)
            if n < len(txt): break
        else:
            d.text((x0 + 28 * u, y), txt, font=f, fill=col); clock -= 4
        y += fs * 1.5
    if p.get('stamp') and t > dur * 0.55: stamp_over(im, t - dur * 0.55, p['stamp'], 'bad')
    return im


def rows(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); y0 = top0(W, H)
    cnt = p.get('counter')
    if cnt:
        d.text((W / 2, y0 + 40 * u), str(cnt.get('value', '')), font=F('display', 110 * u), fill=C(cnt.get('color'), 'bad'), anchor='mm')
        d.text((W / 2, y0 + 125 * u), cnt.get('label', ''), font=F('mono', 34 * u), fill=T['ink'], anchor='mm'); y0 += 190 * u
    elif p.get('title'):
        d.text((W * 0.06, y0), p['title'], font=F('display', 58 * u), fill=T['ink']); y0 += 110 * u
    R_ = p.get('rows', []) or [['-', '', '', 'muted']]; lh = 64 * u; f = F('mono', 32 * u)
    for r in range(min(len(R_), int((zone(W, H) - y0) / lh))):
        if t < 0.1 * r: break
        row = list(R_[r]) + ['', '', '', '']; y = y0 + r * lh
        if r % 2 == 0: d.rectangle([W * 0.05, y - 8 * u, W * 0.95, y + lh - 14 * u], fill=T['panel'])
        d.text((W * 0.07, y), str(row[0]), font=f, fill=T['ink']); d.text((W * 0.47, y), str(row[1]), font=f, fill=T['muted'])
        d.text((W * 0.93, y), str(row[2]), font=f, fill=C(row[3], 'a1'), anchor='ra')
    return im


def stamp_over(im, t, text, colour='bad'):
    W, H = im.size; u = U(W, H); a = ease(t * 5)
    lay = Image.new('RGBA', (W, H)); dl = ImageDraw.Draw(lay)
    fb, _ = fit(dl, text, 'display', int(130 * u), W * 0.78, 1, 40); tw = dl.textlength(text, font=fb)
    cx, cy = W / 2, zone(W, H) * 0.6; c = C(colour, 'bad')
    dl.rectangle([cx - tw / 2 - 34 * u, cy - fb.size * 0.8, cx + tw / 2 + 34 * u, cy + fb.size * 0.8], outline=c + (int(255 * a),), width=int(12 * u))
    dl.text((cx, cy), text, font=fb, fill=c + (int(255 * a),), anchor='mm')
    lay = lay.rotate(-7, center=(cx, cy)); im.paste(lay, (0, 0), lay); return im


def stamp(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H)
    if p.get('above'):
        f, ls = fit(d, p['above'], 'body', int(62 * u), W * 0.84, 3)
        for i, l in enumerate(ls): d.text((W / 2, top0(W, H) + 40 * u + i * f.size * 1.25), l, font=f, fill=T['ink'], anchor='mm')
    return stamp_over(im, t - 0.1, p.get('text', ''), p.get('color') or 'bad')


def quote(W, H, t, dur, p):
    """Big pull quote with attribution."""
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.1
    d.text((x0 - 20 * u, top0(W, H) - 40 * u), '“', font=F('display', 260 * u), fill=T['a1'])
    f, ls = fit(d, p.get('text', ''), 'display', int(84 * u), W * 0.8, 6 if H > W else 3)
    y = top0(W, H) + 150 * u
    for i, l in enumerate(ls):
        if t > 0.12 * i: d.text((x0, y + i * f.size * 1.15), l, font=f, fill=T['ink'])
    if p.get('by') and t > 0.5: d.text((x0, y + len(ls) * f.size * 1.15 + 30 * u), '— ' + p['by'], font=F('mono', 38 * u), fill=T['a2'])
    return im


def browser(W, H, t, dur, p):
    """News/article page: site, headline, lede, optional highlight phrase."""
    im, d = base(W, H, t); u = U(W, H); x0 = W * 0.05; mw = W * 0.9; y0 = top0(W, H) - 30 * u
    bh = zone(W, H) - y0 - 20 * u; card(d, [x0, y0, x0 + mw, y0 + bh], u=u)
    d.rectangle([x0, y0, x0 + mw, y0 + 64 * u], fill=T['muted'])
    d.rounded_rectangle([x0 + 110 * u, y0 + 14 * u, x0 + mw - 30 * u, y0 + 50 * u], radius=18, fill=T['panel'])
    d.text((x0 + 130 * u, y0 + 32 * u), p.get('url', 'news'), font=F('mono', 26 * u), fill=T['ink'], anchor='lm')
    y = y0 + 100 * u
    d.text((x0 + 36 * u, y), p.get('site', '').upper(), font=F('mono', 30 * u), fill=T['a1']); y += 60 * u
    f, ls = fit(d, p.get('headline', ''), 'display', int(76 * u), mw - 72 * u, 4)
    for l in ls: d.text((x0 + 36 * u, y), l, font=f, fill=T['ink']); y += f.size * 1.12
    y += 20 * u; fs, sl = fit(d, p.get('lede', ''), 'body', int(40 * u), mw - 72 * u, 4)
    hl = p.get('highlight', '').lower()
    for l in sl:
        if hl and hl.split()[0] in l.lower() and t > dur * 0.4:
            d.rectangle([x0 + 30 * u, y - 4 * u, x0 + 42 * u + d.textlength(l, font=fs) * ease((t - dur * 0.4) / 0.4), y + fs.size * 1.1], fill=T['a3'])
        d.text((x0 + 36 * u, y), l, font=fs, fill=T['ink']); y += fs.size * 1.3
    return im


def gauge(W, H, t, dur, p):
    """Dial: label, value text, frac 0..1 (position of the needle), sub."""
    im, d = base(W, H, t); u = U(W, H); cx, cy = W / 2, H * (0.36 if H > W else 0.44); r = min(W, H) * 0.36
    d.arc([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=T['muted'], width=int(40 * u))
    fr = max(0, min(1, float(p.get('frac', 0.9) or 0.9))) * ease(t / 0.8)
    d.arc([cx - r, cy - r, cx + r, cy + r], 180, 180 + 180 * fr, fill=C(p.get('color'), 'a1'), width=int(40 * u))
    a = math.pi * (1 + fr); d.line([(cx, cy), (cx + r * 0.8 * math.cos(a), cy + r * 0.8 * math.sin(a))], fill=T['ink'], width=int(12 * u))
    d.ellipse([cx - 20 * u, cy - 20 * u, cx + 20 * u, cy + 20 * u], fill=T['ink'])
    d.text((cx, cy - r - 60 * u), p.get('label', ''), font=F('body', 52 * u), fill=T['ink'], anchor='mm')
    fv, _ = fit(d, p.get('value', ''), 'display', int(90 * u), W * 0.86, 1)
    d.text((cx, cy + 80 * u), p.get('value', ''), font=fv, fill=C(p.get('color'), 'a1'), anchor='mm')
    if p.get('sub'): d.text((cx, cy + 170 * u), p['sub'], font=F('mono', 34 * u), fill=T['muted'], anchor='mm')
    return im


def compare(W, H, t, dur, p):
    """Then vs now / A vs B: left {title, lines}, right {title, lines}."""
    im, d = base(W, H, t); u = U(W, H); vert = H > W
    boxes = ([W * 0.06, top0(W, H), W * 0.94, top0(W, H) + 340 * u], [W * 0.06, top0(W, H) + 400 * u, W * 0.94, top0(W, H) + 740 * u]) if vert \
        else ([W * 0.05, top0(W, H), W * 0.48, zone(W, H) - 20 * u], [W * 0.52, top0(W, H), W * 0.95, zone(W, H) - 20 * u])
    for k, (side, b) in enumerate(zip([p.get('left', {}), p.get('right', {})], boxes)):
        if t < 0.35 * k: break
        card(d, b, u=u, accent=[T['a1'], T['a2']][k])
        d.text((b[0] + 30 * u, b[1] + 24 * u), side.get('title', ''), font=F('display', 60 * u), fill=[T['a1'], T['a2']][k])
        y = b[1] + 110 * u
        for l in side.get('lines', [])[:4]:
            f, ls = fit(d, l, 'body', int(40 * u), b[2] - b[0] - 60 * u, 1); d.text((b[0] + 30 * u, y), ls[0] if ls else '', font=f, fill=T['ink']); y += 56 * u
    return im


def countdown(W, H, t, dur, p):
    im, d = base(W, H, t); u = U(W, H); cy = H * 0.3
    left = max(0, int(p.get('start', 600)) - t * float(p.get('speed', 60)))
    s = f"{int(left // 3600):02d}:{int(left % 3600 // 60):02d}:{int(left % 60):02d}"
    d.text((W / 2, cy - 170 * u), p.get('top', ''), font=F('body', 60 * u), fill=T['ink'], anchor='mm')
    f, _ = fit(d, '00:00:00', 'display', int(220 * u), W * 0.9, 1); d.text((W / 2, cy), s, font=f, fill=T['bad'], anchor='mm')
    if p.get('sub'): d.text((W / 2, cy + 160 * u), p['sub'], font=F('mono', 40 * u), fill=T['muted'], anchor='mm')
    return im


def screen_insert(W, H, t, dur, p):
    """Code-rendered device screen (replaces Grok shots whose screens face the wrong way): a laptop/phone frame facing
    the camera with themed content (headline/app text from the story)."""
    im, d = base(W, H, t); u = U(W, H); phone = p.get('device') == 'phone'
    if phone:
        w, h = W * 0.56, (zone(W, H) - top0(W, H)) * 0.98; x0, y0 = (W - w) / 2, top0(W, H) - 40 * u
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=int(60 * u), fill=T['ink'])
        sx0, sy0, sx1, sy1 = x0 + 24 * u, y0 + 24 * u, x0 + w - 24 * u, y0 + h - 24 * u
    else:
        w = W * 0.9; h = w * 0.62; x0, y0 = (W - w) / 2, top0(W, H)
        if H <= W: h = zone(W, H) - y0 - 60 * u; w = h / 0.62; x0 = (W - w) / 2
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=int(24 * u), fill=T['ink'])
        d.polygon([(x0 - 40 * u, y0 + h), (x0 + w + 40 * u, y0 + h), (x0 + w + 80 * u, y0 + h + 40 * u), (x0 - 80 * u, y0 + h + 40 * u)], fill=T['muted'])
        sx0, sy0, sx1, sy1 = x0 + 20 * u, y0 + 20 * u, x0 + w - 20 * u, y0 + h - 20 * u
    d.rectangle([sx0, sy0, sx1, sy1], fill=T['panel'])
    d.rectangle([sx0, sy0, sx1, sy0 + 56 * u], fill=T['a2'])
    d.text((sx0 + 20 * u, sy0 + 28 * u), p.get('app', ''), font=F('mono', 28 * u), fill=(255, 255, 255), anchor='lm')
    f, ls = fit(d, p.get('text', ''), 'body', int(50 * u), sx1 - sx0 - 40 * u, 6)
    y = sy0 + 80 * u
    for i, l in enumerate(ls):
        if t > 0.1 * i: d.text((sx0 + 20 * u, y), l, font=f, fill=T['ink']); y += f.size * 1.25
    if p.get('flag') and t > dur * 0.4:
        fb = F('mono', 34 * u); tw = d.textlength(p['flag'], font=fb)
        d.rectangle([sx0 + 20 * u, y + 20 * u, sx0 + 60 * u + tw, y + 80 * u], fill=T['bad'])
        d.text((sx0 + 40 * u, y + 50 * u), p['flag'], font=fb, fill=(255, 255, 255), anchor='lm')
    return im


def endcard(W, H, t, dur, p):
    bg = p.get('bg'); u = U(W, H)
    im = bg.copy() if bg is not None else base(W, H, t)[0]
    ov = Image.new('RGBA', (W, H), T['bg'] + (int(200 * ease(t / 0.6)),)); im.paste(ov, (0, 0), ov); d = ImageDraw.Draw(im)
    cy = H * (0.30 if H > W else 0.32)
    f, ls = fit(d, p.get('title', ''), 'display', int(150 * u), W * 0.86, 2, 50)
    for i, l in enumerate(ls): d.text((W / 2, cy - 60 * u + i * f.size * 1.08), l, font=f, fill=T['ink'], anchor='mm')
    yb = cy - 60 * u + len(ls) * f.size * 1.08 + 20 * u
    d.rectangle([W / 2 - 120 * u, yb, W / 2 + 120 * u, yb + 10 * u], fill=T['a1'])
    if t > 0.4 and p.get('credit'):
        fc, cl = fit(d, p['credit'], 'body', int(48 * u), W * 0.82, 3)
        for i, l in enumerate(cl): d.text((W / 2, yb + 70 * u + i * fc.size * 1.3), l, font=fc, fill=T['ink'], anchor='mm')
    fh = F('mono', 28 * u if H > W else 26 * u)
    d.text((W / 2, H * (0.88 if H > W else 0.94)), 'X: @jxwalker  ·  scorpion-labs.com', font=fh, fill=T['muted'], anchor='mm')
    return im


R = dict(headline=headline, bignum=bignum, bars=bars, post=post, feed=feed, inbox=inbox, chat=chat, code=code,
         terminal=terminal, term=terminal, rows=rows, stamp=stamp, quote=quote, browser=browser, gauge=gauge,
         compare=compare, countdown=countdown, screen=screen_insert, endcard=endcard)
TEMPLATES = sorted(k for k in R if k not in ('term', 'endcard'))
