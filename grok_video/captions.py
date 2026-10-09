"""ASS overlay for the Grok-clip video, styled like the current Pip videos: lyric line in a dark rounded box
(lower third, word-by-word karaoke fill from timings.json), dim next-line preview, story topic pill at the top (topic text
only, no label), title card, end card (title, 'Made with Suno' pill, 'Sources on X' card with handles), @handle footer.
genre looks (pop-video, edm, rock, punk): no box; big bold outlined words, the line pops in and the sung word lights up (one event per word,
no reflow), chorus lines in caps. Topic pill, title card and end card unchanged.
All caption wording comes from timings.json, i.e. lyrics.txt display tokens (brand spellings exactly as written)."""
import functools, os, re
from PIL import ImageFont
import common_gv as G
from looks import LOOKS

W, H = 1080, 1920
FD = '/usr/share/fonts/truetype/sand-box/google/Poppins/'
F_BLACK, F_XB, F_SB = FD + 'Poppins-Black.ttf', FD + 'Poppins-ExtraBold.ttf', FD + 'Poppins-SemiBold.ttf'
col = lambda h, a=0: f"&H{a:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()
PINK, CYAN, YEL, PURP, GREEN, WHITE, INK = 'ff4f9a', '5fe3ff', 'ffd84d', '9b7bff', '4fe0a0', 'ffffff', '1b1035'
DOTS = [PINK, CYAN, YEL, PURP, GREEN]
_f = {}


def width(text, path, size):
    k = (path, size)
    if k not in _f:
        a, d = ImageFont.truetype(path, 1000).getmetrics()
        _f[k] = ImageFont.truetype(path, max(1, int(round(size * 1000 / (a + d)))))
    return _f[k].getlength(text)


def wrap(words, path, size, maxw, maxlines=4):
    n = len(words); sp = width(' ', path, size); wl = [width(w, path, size) for w in words]
    lw = lambda i, j: sum(wl[i:j]) + sp * (j - i - 1)
    for k in range(1, maxlines + 1):
        @functools.lru_cache(None)
        def f(i, k):
            if k == 1:
                return (lw(i, n), (n,)) if n > i else (1e9, ())
            res = (1e9, ())
            for j in range(i + 1, n - k + 2):
                w1 = lw(i, j)
                if w1 > maxw:
                    break
                r = f(j, k - 1); mm = max(w1, r[0])
                if mm < res[0]:
                    res = (mm, (j,) + r[1])
            return res
        r = f(0, k)
        if r[0] <= maxw:
            out, i = [], 0
            for j in r[1]:
                out.append(list(range(i, j))); i = j
            return out
    return [list(range(n))]


def ts(t):
    cs = int(round(max(t, 0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def rrect(w, h, r):
    return (f"m {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} b {w} {h} {w} {h} {w-r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h-r} l 0 {r} b 0 0 0 0 {r} 0")


esc = lambda s: s.replace('{', '(').replace('}', ')').replace('\\', '/')


def pop_lyrics(L, ES, D, colours=(None, 'ff5fb0')):
    Y = 1350
    for ln in L:
        s0, e0 = ln['ds'], min(ln['de'], ES)
        if e0 - s0 < 0.05 or not ln['words']:
            continue
        ch = ln['kind'] in ('chorus', 'postchorus')
        words = [w[0].upper() if ch else w[0] for w in ln['words']]
        size = 100 if ch else 90
        rows = wrap(words, F_BLACK, size, 960)
        while len(rows) > 2 and size > 60:
            size -= 4; rows = wrap(words, F_BLACK, size, 960)
        hi = (colours[0] or YEL) if not ch else colours[1]
        ws = [w[1] for w in ln['words']]; we = ln['words'][-1][2]
        bounds = [(s0, ws[0], -1)] + [(max(ws[k], s0), ws[k + 1] if k + 1 < len(ws) else max(we, ws[k] + 0.05), k)
                                      for k in range(len(ws))] + [(max(we, ws[-1] + 0.05), e0, len(ws))]
        first = True
        for a, b, cur in bounds:
            b = min(b, e0)
            if b - a < 0.01:
                continue
            parts = []
            for r in rows:
                toks = []
                for k in r:
                    if k == cur:
                        toks.append(f"{{\\1c{col(hi)}\\1a&H00&\\3a&H00&\\4a&H70&}}{esc(words[k])}")
                    elif k < cur:
                        toks.append(f"{{\\1c{col(WHITE)}\\1a&H00&\\3a&H00&\\4a&H70&}}{esc(words[k])}")
                    else:
                        toks.append(f"{{\\1c{col(WHITE)}\\1a&H60&\\3a&H90&\\4a&HD0&}}{esc(words[k])}")
                parts.append(' '.join(toks))
            # whole-line pop-in on the first event only (uniform scale, so no word reflow); quick fade out at the end
            intro = "\\fscx86\\fscy86\\t(0,110,\\fscx100\\fscy100)\\fad(70,0)" if first else ''
            outro = "\\fad(0,110)" if b >= e0 - 0.005 and not first else ''
            D(4, a, b, 'PopCap', f"{{\\an8\\pos({W//2},{Y})\\fs{size}{intro}{outro}}}" + '\\N'.join(parts))
            first = False


def build(day, L, dur, out_ass, handle='@jxwalker', look='standard'):
    tags = G.load_json(os.path.join(day, 'tags.json'), {}) or {}
    title = tags.get('title') or G.read(os.path.join(day, 'title.txt')) or 'Untitled'
    date = G.C.day_date(day, tags)
    subtitle = tags.get('subtitle') or f"AI news, {date.day} {date:%b %Y}"
    ev = []

    def D(layer, s, e, style, text):
        if e - s > 0.01:
            ev.append(f"Dialogue: {layer},{ts(s)},{ts(e)},{style},,0,0,0,,{text}")

    TE = float(tags.get('title_card_end', 4.0))
    last_end = L[-1]['end'] if L else dur - 6
    ES = float(tags.get('end_card_start', min(max(last_end + 0.6, dur - 7.0), dur - 3.5)))

    if look in LOOKS:
        pop_lyrics(L, ES, D, LOOKS[look]['caption'])
    # ---- lyric captions (lower third box, karaoke fill white -> yellow)
    BOX_Y = 1330
    for i, ln in enumerate(L if look not in LOOKS else []):
        s0, e0 = ln['ds'], min(ln['de'], ES)
        if e0 - s0 < 0.05:
            continue
        ch = ln['kind'] in ('chorus', 'postchorus')
        size = 84 if ch else 74
        words = [w[0] for w in ln['words']]
        rows = wrap(words, F_BLACK, size, 900)
        while len(rows) > 2 and size > 54:
            size -= 4; rows = wrap(words, F_BLACK, size, 900)
        rowh = int(size * 1.18)
        tw = max(width(' '.join(words[k] for k in r), F_BLACK, size) for r in rows)
        bw, bh = int(tw + 90), int(rowh * len(rows) + 46)
        x = (W - bw) // 2
        fad = "\\fad(90,120)"
        D(3, s0, e0, 'Box', f"{{\\pos({x},{BOX_Y})\\p1\\1c{col(INK)}\\1a&H22&\\3c{col('e9e4ff')}\\3a&H30&\\bord4\\shad0{fad}}}{rrect(bw, bh, 34)}")
        t = s0; parts = []
        for r in rows:
            seg = []
            for k in r:
                tok, ws, we = ln['words'][k]
                gap = ws - t
                if gap > 0.02:
                    seg.append(f"{{\\k{int(round(gap * 100))}}}")
                nxt = ln['words'][k + 1][1] if k + 1 < len(words) else None
                d = max((min(nxt, we + 0.3) if nxt is not None else we) - ws, 0.08)
                seg.append(f"{{\\kf{int(round(d * 100))}}}{esc(tok)} ")
                t = ws + d
            parts.append(''.join(seg).rstrip())
        D(4, s0, e0, 'Cap', f"{{\\an8\\pos({W//2},{BOX_Y + 20})\\fs{size}{fad}}}" + '\\N'.join(parts))
        if i + 1 < len(L) and L[i + 1]['ds'] - ln['de'] < 3 and L[i + 1]['ds'] < ES:
            D(4, s0, e0, 'Next', f"{{\\an8\\pos({W//2},{BOX_Y + bh + 26})\\fad(150,100)}}" + esc(L[i + 1]['text']))

    # ---- topic pill (story text only; chorus shows the title)
    stories = tags.get('story_tags') or []

    def topic(ln):
        for s in stories:
            if s.get('section', '').lower() == ln['section'].lower() and s['lines'][0] <= ln['line_no'] <= s['lines'][-1] \
                    and ('occurrence' not in s or s['occurrence'] == ln['section_occ']):
                return s['text'], stories.index(s)
        if ln['kind'] in ('chorus', 'postchorus'):
            return title, -1
        return None, None
    spans = []
    for ln in L:
        tp, k = topic(ln)
        if not tp:
            continue
        if spans and spans[-1][2] == tp and ln['ds'] - spans[-1][1] < 6:
            spans[-1][1] = ln['de']
        else:
            spans.append([ln['ds'], ln['de'], tp, k])
    for j, (s, e, tp, k) in enumerate(spans):
        e2 = min(spans[j + 1][0] if j + 1 < len(spans) else ES, e + 2.5, ES)
        s = max(s, TE)
        if e2 - s < 0.4:
            continue
        size = 58
        tw = width(tp, F_XB, size)
        while tw > 900 and size > 36:
            size -= 2; tw = width(tp, F_XB, size)
        bw, bh = int(tw + 90), int(size * 1.25 + 36)
        x, y = (W - bw) // 2, 110
        accent = YEL if k == -1 else DOTS[k % len(DOTS)]
        fad = "\\fad(220,200)"
        D(5, s, e2, 'Box', f"{{\\pos({x},{y})\\p1\\1c{col(INK)}\\1a&H18&\\3c{col(accent)}\\bord5\\shad0{fad}}}{rrect(bw, bh, bh // 2)}")
        D(6, s, e2, 'Tag', f"{{\\an5\\pos({W//2},{y + bh // 2})\\fs{size}\\1c{col(YEL if k == -1 else WHITE)}{fad}}}{esc(tp.upper() if k == -1 else tp)}")

    # ---- title card
    tw_ = title.upper().split(); tsize = 132
    rows = wrap(tw_, F_BLACK, tsize, 960, 3)
    while any(width(' '.join(tw_[k] for k in r), F_BLACK, tsize) > 960 for r in rows) and tsize > 70:
        tsize -= 6; rows = wrap(tw_, F_BLACK, tsize, 960, 3)
    gap = int(tsize * 1.08); y0 = 130
    for k, r in enumerate(rows):
        D(8, 0, TE, 'Title', f"{{\\an8\\pos({W//2},{y0 + k*gap})\\fs{tsize}\\fad(200,450)\\t(0,{int(TE*1000)},\\fscx105\\fscy105)}}"
                             + esc(' '.join(tw_[i] for i in r)))
    ys = y0 + len(rows) * gap + 30
    sw = int(width(subtitle, F_XB, 50) + 80)
    D(7, 0.2, TE, 'Box', f"{{\\pos({(W-sw)//2},{ys})\\p1\\1c{col(INK)}\\1a&H10&\\3c{col(WHITE)}\\bord4\\shad0\\fad(200,450)}}{rrect(sw, 92, 46)}")
    D(8, 0.2, TE, 'Tag', f"{{\\an5\\pos({W//2},{ys + 46})\\fs50\\fad(200,450)}}{esc(subtitle)}")

    # ---- end card (block vertically centred)
    D(10, ES, dur, 'Box', f"{{\\pos(0,0)\\p1\\1c{col('2a145c')}\\1a&H38&\\fad(500,0)}}m 0 0 l {W} 0 l {W} {H} l 0 {H}")
    tsz = 110
    while width(title.upper(), F_BLACK, tsz) > 980 and tsz > 50:
        tsz -= 4
    rows_ = G.credit_rows(day)
    hs, ss = (54, 38) if len(rows_) <= 6 else (40, 28)
    has_story = any(r[1] for r in rows_)
    rowh = int(hs * 1.15 + (ss * 1.25 if has_story else 0) + 26)
    card_h = (130 + rowh * len(rows_) + 20) if rows_ else 0
    title_h = int(tsz * 1.15); pill_h = 100
    total = title_h + 30 + pill_h + (50 + card_h if rows_ else 0)
    y = max(120, (H - total) // 2 - 60)
    D(11, ES, dur, 'Title', f"{{\\an8\\pos({W//2},{y})\\fs{tsz}\\fad(500,0)}}{esc(title.upper())}")
    y += title_h + 30
    mw = int(width('Made with Suno', F_XB, 54) + 100)
    D(11, ES + 0.15, dur, 'Box', f"{{\\pos({(W-mw)//2},{y})\\p1\\1c{col(WHITE)}\\3c{col(INK)}\\bord4\\shad0\\fad(400,0)}}{rrect(mw, pill_h, pill_h // 2)}")
    D(12, ES + 0.15, dur, 'Pill', f"{{\\an5\\pos({W//2},{y + pill_h // 2})\\fs54\\fad(400,0)}}Made with Suno")
    y += pill_h + 50
    if rows_:
        cy = y
        D(11, ES + 0.4, dur, 'Box', f"{{\\pos(60,{cy})\\p1\\1c{col('fbf8ff')}\\3c{col(INK)}\\bord5\\shad0\\fad(400,0)}}{rrect(960, card_h, 40)}")
        D(12, ES + 0.4, dur, 'Head', f"{{\\an8\\pos({W//2},{cy + 32})\\fad(400,0)}}Sources on X")
        for k, (h, story) in enumerate(rows_):
            yy = cy + 130 + k * rowh
            st = re.sub(r'\s*\([^)]*\)\s*$', '', story or '')
            D(12, ES + 0.5 + 0.1 * k, dur, 'Box', f"{{\\pos(110,{yy + int(hs*0.38)})\\p1\\1c{col(DOTS[k % 5])}\\3c{col(INK)}\\bord3\\shad0\\fad(300,0)}}{rrect(30, 30, 15)}")
            D(12, ES + 0.5 + 0.1 * k, dur, 'Handle', f"{{\\an7\\pos(165,{yy})\\fs{hs}\\fad(300,0)}}{esc(h)}")
            if st:
                D(12, ES + 0.5 + 0.1 * k, dur, 'Story', f"{{\\an7\\pos(167,{yy + int(hs*1.15)})\\fs{ss}\\fad(300,0)}}{esc(st)}")
    D(1, 0, dur, 'Foot', esc(handle))

    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins Black,74,{col(YEL)},{col(WHITE)},{col(INK)},{col('000000',0x80)},0,0,0,0,100,100,0,0,1,3,0,8,30,30,0,1
Style: Next,Poppins SemiBold,40,{col(WHITE,0x30)},{col(WHITE,0x30)},{col(INK,0x30)},{col('000000',0xA0)},0,0,0,0,100,100,0,0,1,4,0,8,60,60,0,1
Style: Tag,Poppins ExtraBold,50,{col(WHITE)},{col(WHITE)},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1
Style: Box,Poppins Black,20,{col(WHITE)},{col(WHITE)},{col(WHITE)},{col(WHITE)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Title,Poppins Black,132,{col(YEL)},{col(YEL)},{col(INK)},{col('000000',0x70)},0,0,0,0,100,100,2,0,1,10,6,8,20,20,0,1
Style: Pill,Poppins ExtraBold,52,{col(INK)},{col(INK)},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1
Style: Head,Poppins ExtraBold,60,{col(PINK)},{col(PINK)},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1
Style: Handle,Poppins Black,52,{col(INK)},{col(INK)},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Story,Poppins SemiBold,36,{col('5a4a86')},{col('5a4a86')},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: PopCap,Poppins Black,84,{col(WHITE)},{col(WHITE)},{col('120a26')},{col('000000',0x70)},0,0,0,0,100,100,1,0,1,7,4,8,30,30,0,1
Style: Foot,Poppins SemiBold,32,{col(WHITE,0x20)},{col(WHITE,0x20)},{col(INK,0x30)},{col('000000',0xFF)},0,0,0,0,100,100,1,0,1,3,0,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    open(out_ass, 'w', encoding='utf-8').write(hdr + '\n'.join(ev) + '\n')
    return {'title_end': TE, 'end_start': round(ES, 2), 'events': len(ev),
            'topic_spans': [[round(s, 2), round(e, 2), t] for s, e, t, _ in spans]}
