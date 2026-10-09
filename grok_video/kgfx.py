"""Karaoke-mode motion graphics (code-rendered, exact text). Every renderer is f(W, H, t, dur, p) -> PIL RGB image.
All words/numbers come from the plan (taken from stories.md); nothing here invents facts.
Graphics keep the lower ~35% of the frame calm: the karaoke lyrics sit there."""
import math, random, re
from PIL import Image, ImageDraw
from kgfx_base import *          # F, base, U, ctext, colours, term, countdown, dash, bluegreen, pipeline

COL = dict(green=GREEN, red=RED, amber=AMBER, blue=BLUE, cyan=CY, white=WH, dim=DIM)
def col(n, d=WH): return COL.get(str(n or '').lower(), d)

def wrap(d, s, font, maxw):
    out, cur = [], ''
    for w in str(s).split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=font) <= maxw or not cur: cur = t
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    return out

def fit(d, s, path, size, maxw, maxlines, minsize=24):
    while size > minsize:
        f = F(path, size); ls = wrap(d, s, f, maxw)
        if len(ls) <= maxlines: return f, ls
        size = int(size * 0.9)
    f = F(path, minsize); return f, wrap(d, s, f, maxw)[:maxlines]

def top0(W, H): return H * (0.10 if H > W else 0.08)
def zone(W, H): return H * (0.60 if H > W else 0.66)      # graphics stay above this

def headline(W, H, t, dur, p):
    im, d = base(W, H, (10, 12, 22)); u = U(W, H); x0 = W * 0.08; mw = W * 0.84; y = top0(W, H)
    a = min(1, t / 0.35)
    kick = p.get('kicker', '')
    if kick:
        fk = F(MONOB, 34 * u); tw = d.textlength(kick, font=fk)
        d.rounded_rectangle([x0, y, x0 + tw + 36 * u, y + 58 * u], radius=10, fill=col(p.get('color'), AMBER))
        d.text((x0 + 18 * u, y + 29 * u), kick, font=fk, fill=(10, 10, 14), anchor='lm'); y += 100 * u
    f, ls = fit(d, p.get('text', ''), SANS, int(92 * u), mw, 5 if H > W else 3)
    lh = f.size * 1.18
    for i, l in enumerate(ls):
        if t > 0.12 * i: d.text((x0, y + i * lh), l, font=f, fill=WH)
    y += len(ls) * lh + 30 * u
    if p.get('sub') and t > 0.5:
        fs, sl = fit(d, p['sub'], MONO, int(38 * u), mw, 3)
        for i, l in enumerate(sl): d.text((x0, y + i * fs.size * 1.35), l, font=fs, fill=CY)
    d.rectangle([x0, y - 14 * u, x0 + mw * min(1, t / max(0.5, dur)), y - 8 * u], fill=col(p.get('color'), AMBER))
    return im

def bignum(W, H, t, dur, p):
    im, d = base(W, H, (6, 10, 14)); u = U(W, H); cy = H * (0.27 if H > W else 0.32)
    c = col(p.get('color'), GREEN)
    ctext(d, (W / 2, cy - 210 * u), p.get('top', ''), F(SANSB, 56 * u), DIM)
    v = str(p.get('value', '')); m = re.fullmatch(r'([^\d]*)([\d,]+)(.*)', v)
    if m and t < 0.5:                       # quick count-up (0.5 s), then the exact figure holds
        n = int(m.group(2).replace(',', '')); k = min(1, t / 0.5); k = 1 - (1 - k) ** 3
        cur = int(round(n * k)); v = m.group(1) + (f"{cur:,}" if ',' in m.group(2) else str(cur)) + m.group(3)
    f, _ = fit(d, str(p.get('value', '')), MONOB, int(250 * u), W * 0.9, 1, 60)
    ctext(d, (W / 2, cy), v, f, c)
    fs, sl = fit(d, p.get('sub', ''), MONO, int(44 * u), W * 0.86, 3)
    for i, l in enumerate(sl): ctext(d, (W / 2, cy + 170 * u + i * fs.size * 1.35), l, fs, WH)
    return im

def bars(W, H, t, dur, p):
    im, d = base(W, H, (8, 10, 18)); u = U(W, H); items = p.get('items', [])[:6]
    y = top0(W, H); ctext(d, (W / 2, y), p.get('title', ''), F(SANSB, 54 * u), WH); y += 90 * u
    mx = max([float(i.get('value', 0)) for i in items] + [1]); bh = 76 * u; gap = 46 * u
    lw = W * 0.30; x0 = W * 0.06; bw = W * 0.88 - lw - 140 * u
    for k, it in enumerate(items):
        yy = y + k * (bh + gap); g = min(1, max(0, (t - 0.12 * k) / 0.7)); g = 1 - (1 - g) ** 3
        d.text((x0, yy + bh / 2), str(it.get('label', '')), font=F(MONOB, 34 * u), fill=WH, anchor='lm')
        w = bw * float(it.get('value', 0)) / mx * g; c = col(it.get('color'), [RED, AMBER, CY, GREEN, BLUE][k % 5])
        d.rounded_rectangle([x0 + lw, yy, x0 + lw + max(6, w), yy + bh], radius=8, fill=c)
        d.text((x0 + lw + w + 16 * u, yy + bh / 2), str(it.get('show', it.get('value'))), font=F(MONOB, 40 * u), fill=WH, anchor='lm')
    return im

def post(W, H, t, dur, p):
    """X-post style card: handle + exact quoted text (from stories.md)."""
    im, d = base(W, H, (0, 0, 0)); u = U(W, H); x0 = W * 0.07; mw = W * 0.86; y = top0(W, H)
    card_h = zone(W, H) - y - 20 * u
    d.rounded_rectangle([x0, y, x0 + mw, y + card_h], radius=int(28 * u), fill=(22, 24, 28), outline=(60, 64, 72), width=2)
    h = p.get('handle', '').lstrip('@'); r = 44 * u
    random.seed(h); av = (random.randint(60, 220), random.randint(60, 220), random.randint(60, 220))
    d.ellipse([x0 + 34 * u, y + 34 * u, x0 + 34 * u + 2 * r, y + 34 * u + 2 * r], fill=av)
    ctext(d, (x0 + 34 * u + r, y + 34 * u + r), (h[:1] or '?').upper(), F(SANSB, 44 * u), (15, 15, 15))
    d.text((x0 + 140 * u, y + 44 * u), p.get('name', h), font=F(SANSB, 40 * u), fill=WH)
    d.text((x0 + 140 * u, y + 92 * u), '@' + h, font=F(MONO, 32 * u), fill=DIM)
    txt = p.get('text', ''); n = int(len(txt) * min(1, t / max(0.4, dur * 0.5)) + 0.5)
    f, ls = fit(d, txt, SANSB, int(54 * u), mw - 80 * u, 7 if H > W else 4)
    shown = 0; yy = y + 170 * u
    for l in ls:
        part = l[:max(0, n - shown)]; shown += len(l) + 1
        d.text((x0 + 40 * u, yy), part, font=f, fill=WH); yy += f.size * 1.3
    if p.get('stat') and t > dur * 0.4:
        d.text((x0 + 40 * u, y + card_h - 70 * u), p['stat'], font=F(MONOB, 36 * u), fill=col(p.get('color'), CY))
    return im

def inbox(W, H, t, dur, p):
    """Mail client list; rows {from, subject, flag}; flagged rows get a red badge."""
    im, d = base(W, H, (240, 242, 246)); u = U(W, H); x0 = W * 0.05; mw = W * 0.9; y = top0(W, H) - 30 * u
    d.rounded_rectangle([x0, y, x0 + mw, y + 80 * u], radius=14, fill=(200, 40, 50) if p.get('folder', '').lower() == 'spam' else (40, 90, 200))
    d.text((x0 + 30 * u, y + 40 * u), p.get('folder', 'Inbox'), font=F(SANSB, 42 * u), fill=WH, anchor='lm')
    y += 110 * u; rh = 128 * u
    for k, r in enumerate(p.get('rows', [])[:5]):
        if t < 0.18 * k: break
        yy = y + k * rh
        d.rectangle([x0, yy, x0 + mw, yy + rh - 10 * u], fill=WH)
        d.text((x0 + 26 * u, yy + 18 * u), str(r.get('from', ''))[:34], font=F(SANSB, 34 * u), fill=(20, 20, 30))
        d.text((x0 + 26 * u, yy + 64 * u), str(r.get('subject', ''))[:44], font=F(MONO, 30 * u), fill=(70, 70, 90))
        if r.get('flag'):
            fl = str(r['flag']); fb = F(MONOB, 28 * u); tw = d.textlength(fl, font=fb)
            d.rounded_rectangle([x0 + mw - tw - 50 * u, yy + 20 * u, x0 + mw - 18 * u, yy + 66 * u], radius=8, fill=RED)
            d.text((x0 + mw - 34 * u - tw / 2, yy + 43 * u), fl, font=fb, fill=WH, anchor='mm')
    if p.get('stamp') and t > dur * 0.55:
        stamp(None, None, t, dur, {'text': p['stamp']}, im)
    return im

def code(W, H, t, dur, p):
    """Editor window with a code snippet (typed in)."""
    im, d = base(W, H, (14, 16, 24)); u = U(W, H); x0 = W * 0.06; mw = W * 0.88; y0 = top0(W, H) - 30 * u
    bh = zone(W, H) - y0 - 20 * u
    d.rounded_rectangle([x0, y0, x0 + mw, y0 + bh], radius=16, fill=(24, 26, 36), outline=(60, 64, 80), width=2)
    d.rectangle([x0, y0, x0 + mw, y0 + 56 * u], fill=(36, 38, 50))
    d.text((x0 + 24 * u, y0 + 28 * u), p.get('file', 'main.c'), font=F(MONO, 28 * u), fill=CY, anchor='lm')
    lines = p.get('lines', []); fs = 34 * u if H > W else 32 * u; f = F(MONO, fs)
    kw = re.compile(r'\b(IDENTIFICATION|DIVISION|PROCEDURE|DISPLAY|MOVE|PERFORM|PROGRAM|SUBROUTINE|END|IF|THEN|ELSE|def|return|import|from|int|void|char|if|for|while|function|const|let|class|Sub|Dim|As|PRINT|CALL)\b')
    clock = t * p.get('cps', 45) + 3; y = y0 + 80 * u
    for i, l in enumerate(lines[:14]):
        if clock <= 0: break
        s = l[:int(clock)]; clock -= len(l) + 3
        d.text((x0 + 20 * u, y), f"{i + 1:>3}", font=f, fill=(80, 86, 110))
        x = x0 + 100 * u
        for tok in re.split(r'(\s+)', s):
            c = AMBER if kw.fullmatch(tok) else (GREEN if tok.startswith(('"', "'")) else (DIM if tok.startswith(('*>', '#', '//', '!')) else WH))
            d.text((x, y), tok, font=f, fill=c); x += d.textlength(tok, font=f)
        y += fs * 1.42
        if y > y0 + bh - fs: break
    return im

def rows(W, H, t, dur, p):
    """Scrolling table, e.g. findings list. p: title, rows [[left, mid, right, colour]], counter {value, label}."""
    im, d = base(W, H, (10, 8, 10)); u = U(W, H); y0 = top0(W, H) - 20 * u
    cnt = p.get('counter')
    if cnt:
        bignum_txt = str(cnt.get('value', '')); ctext(d, (W / 2, y0 + 40 * u), bignum_txt, F(SANS, 110 * u), col(cnt.get('color'), RED))
        ctext(d, (W / 2, y0 + 125 * u), cnt.get('label', ''), F(MONO, 34 * u), WH); y0 += 180 * u
    elif p.get('title'):
        ctext(d, (W / 2, y0 + 30 * u), p['title'], F(SANSB, 52 * u), WH); y0 += 90 * u
    f = F(MONO, 30 * u); lh = 46 * u; R_ = p.get('rows', []) or [['-', '', '', 'dim']]
    nrows = int((zone(W, H) - y0) / lh); off = t * 6
    for r in range(nrows):
        i = int(off) + r; y = y0 + (r - (off - int(off))) * lh
        if y < y0 - 2: continue
        row = R_[i % len(R_)] + ['', '', '', '']
        d.text((W * 0.06, y), str(row[0]), font=f, fill=WH); d.text((W * 0.50, y), str(row[1]), font=f, fill=DIM)
        d.text((W * 0.94, y), str(row[2]), font=f, fill=col(row[3], AMBER), anchor='ra')
    return im

def stamp(W, H, t, dur, p, im=None):
    """Big rotated rubber stamp over a dark plate (or over `im`)."""
    if im is None:
        im, d = base(W, H, (12, 10, 14)); u = U(W, H)
        if p.get('above'):
            f, ls = fit(d, p['above'], SANSB, int(60 * u), W * 0.84, 3)
            for i, l in enumerate(ls): ctext(d, (W / 2, top0(W, H) + 40 * u + i * f.size * 1.25), l, f, WH)
    W, H = im.size; u = U(W, H)
    s = p.get('text', ''); a = min(1, max(0, (t - (dur * 0.1 if 'above' in p else 0)) * 6))
    lay = Image.new('RGBA', (W, H)); dl = ImageDraw.Draw(lay); fb, _ = fit(dl, s, SANS, int(120 * u), W * 0.8, 1, 40)
    tw = dl.textlength(s, font=fb); cx, cy = W / 2, zone(W, H) * 0.62; c = col(p.get('color'), RED)
    dl.rounded_rectangle([cx - tw / 2 - 34 * u, cy - fb.size * 0.85, cx + tw / 2 + 34 * u, cy + fb.size * 0.85], radius=14,
                         outline=c + (int(255 * a),), width=int(11 * u))
    dl.text((cx, cy), s, font=fb, fill=c + (int(255 * a),), anchor='mm')
    sc = 1.6 - 0.6 * a; lay = lay.rotate(-8, center=(cx, cy))
    if sc > 1.01:
        lw, lh = int(W * sc), int(H * sc); big = lay.resize((lw, lh)); lay = big.crop(((lw - W) // 2, (lh - H) // 2, (lw - W) // 2 + W, (lh - H) // 2 + H))
    im.paste(lay, (0, 0), lay)
    return im

def endcard(W, H, t, dur, p):
    bg = p.get('bg'); u = U(W, H)
    im = bg.copy() if bg is not None else base(W, H, (8, 10, 18))[0]
    ov = Image.new('RGBA', (W, H), (0, 0, 0, int(160 * min(1, t / 0.8)))); im.paste(ov, (0, 0), ov); d = ImageDraw.Draw(im)
    cy = H * (0.30 if H > W else 0.33)
    f, ls = fit(d, p.get('title', '').upper(), SANS, int(140 * u), W * 0.88, 2, 50)
    for i, l in enumerate(ls): ctext(d, (W / 2, cy - (len(ls) - 1) * f.size * 0.55 + i * f.size * 1.1 - 60 * u), l, f, WH)
    if t > 0.5 and p.get('credit'):
        fc, cl = fit(d, p['credit'], SANSB, int(46 * u), W * 0.86, 3)
        for i, l in enumerate(cl): ctext(d, (W / 2, cy + 80 * u + i * fc.size * 1.3), l, fc, CY)
    if t > 1.0 and p.get('sub'):
        ctext(d, (W / 2, cy + 260 * u), p['sub'], F(SANSB, 40 * u), AMBER)
    # discreet handles, bottom corner area (above the platform UI on vertical)
    fh = F(MONO, 28 * u if H > W else 26 * u); hy = H * (0.86 if H > W else 0.93)
    ctext(d, (W / 2, hy), 'X: @jxwalker   ·   scorpion-labs.com', fh, (200, 205, 215))
    return im

R = dict(term=term, countdown=countdown, dash=dash, bluegreen=bluegreen, pipeline=pipeline, headline=headline,
         bignum=bignum, bars=bars, post=post, inbox=inbox, code=code, rows=rows, stamp=stamp, endcard=endcard)
