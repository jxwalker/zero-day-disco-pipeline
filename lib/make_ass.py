"""Build the ASS overlay (karaoke captions, story tags, title card, end card, footer) — 27 Sep design.
usage: make_ass.py DAY_DIR WORK_DIR TAGS_JSON DURATION"""
import sys, os, json, functools
sys.path.insert(0, os.path.dirname(__file__))
import common as C
from PIL import ImageFont

day, work, tagsp, DUR = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
T = C.load_json(tagsp, {}) or {}
L = C.load_json(os.path.join(work, 'timings.json'))
W, H = 1080, 1920
FD = '/usr/share/fonts/truetype/sand-box/google/'
F_BLACK = FD + 'Poppins/Poppins-Black.ttf'; F_XB = FD + 'Poppins/Poppins-ExtraBold.ttf'
F_MONO = FD + 'Monoton/Monoton-Regular.ttf'
date = C.day_date(day, T)
title = T.get('title') or (open(os.path.join(day, 'title.txt')).read().strip() if os.path.exists(os.path.join(day, 'title.txt')) else 'Untitled')
DATE_LONG = f"{date.day} {date:%b %Y}"
subtitle = T.get('subtitle') or f"AI news, {DATE_LONG}"
handles = T.get('sources') or C.source_handles(os.path.join(day, 'stories.md'))
handles = ['@' + h.lstrip('@') for h in handles]

fonts = {}
def width(text, path, size):
    k = (path, size)
    if k not in fonts:
        a, d = ImageFont.truetype(path, 1000).getmetrics()
        fonts[k] = ImageFont.truetype(path, max(1, int(round(size * 1000 / (a + d)))))  # libass size = ascent+descent
    return fonts[k].getlength(text)


def wrap(words, path, size, maxw, maxlines=6):
    """balanced wrap: fewest rows, then minimise the widest row"""
    n = len(words); sp = width(' ', path, size); wl = [width(w, path, size) for w in words]
    lw = lambda i, j: sum(wl[i:j]) + sp * (j - i - 1)
    for k in range(1, maxlines + 1):
        @functools.lru_cache(None)
        def f(i, k):
            if k == 1: return (lw(i, n), (n,)) if n > i else (1e9, ())
            res = (1e9, ())
            for j in range(i + 1, n - k + 2):
                w1 = lw(i, j)
                if w1 > maxw: break
                r = f(j, k - 1); mm = max(w1, r[0])
                if mm < res[0]: res = (mm, (j,) + r[1])
            return res
        r = f(0, k)
        if r[0] <= maxw:
            out = []; i = 0
            for j in r[1]: out.append(list(range(i, j))); i = j
            return out
    return [list(range(n))]


col = lambda hexrgb, a=0: f"&H{a:02X}{hexrgb[4:6]}{hexrgb[2:4]}{hexrgb[0:2]}".upper()
PINK = 'ff2e97'; CYAN = '00e5ff'; YEL = 'ffe14d'; PURP = '7b2cff'; WHITE = 'ffffff'; INK = '1a0633'
COLS = {'pink': PINK, 'cyan': CYAN, 'yellow': YEL, 'purple': PURP}
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins Black,100,{col(YEL)},{col(WHITE)},{col(INK)},{col('000000',0x60)},0,0,0,0,100,100,0,0,1,7,4,8,40,40,0,1
Style: Chor,Poppins Black,136,{col(YEL)},{col(WHITE)},{col(INK)},{col('000000',0x50)},-1,0,0,0,100,100,1,0,1,9,5,8,30,30,0,1
Style: ChorGlow,Poppins Black,136,{col(PINK)},{col(PINK)},{col(PINK)},{col('000000',0xFF)},-1,0,0,0,100,100,1,0,1,16,0,8,30,30,0,1
Style: Next,Poppins ExtraBold,48,{col(WHITE,0x50)},{col(WHITE,0x50)},{col(INK,0x40)},{col('000000',0xA0)},0,0,0,0,100,100,0,0,1,4,0,2,60,60,0,1
Style: TagL,Poppins ExtraBold,34,{col(INK)},{col(INK)},{col(INK)},{col(INK)},0,0,0,0,100,100,4,0,1,0,0,7,0,0,0,1
Style: TagT,Poppins Black,64,{col(WHITE)},{col(WHITE)},{col(INK)},{col(INK)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Box,Poppins Black,20,{col(WHITE)},{col(WHITE)},{col(WHITE)},{col(WHITE)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Title,Monoton,118,{col(PINK)},{col(PINK)},{col(WHITE)},{col('000000',0xFF)},0,0,0,0,100,100,2,0,1,0,0,5,20,20,0,1
Style: Sub,Poppins Black,56,{col(CYAN)},{col(CYAN)},{col(INK)},{col('000000',0xFF)},0,0,0,0,100,100,2,0,1,5,0,5,20,20,0,1
Style: Small,Poppins SemiBold,38,{col(WHITE)},{col(WHITE)},{col(INK)},{col('000000',0xFF)},0,0,0,0,100,100,0,0,1,3,0,5,40,40,0,1
Style: Foot,Poppins SemiBold,30,{col(WHITE,0x30)},{col(WHITE,0x30)},{col(INK,0x40)},{col('000000',0xFF)},0,0,0,0,100,100,2,0,1,3,0,2,20,20,28,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
ev = []
def ts(t):
    t = max(t, 0); cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"
def D(layer, s, e, style, text):
    if e - s > 0.01: ev.append(f"Dialogue: {layer},{ts(s)},{ts(e)},{style},,0,0,0,,{text}")
def rrect(w, h, r):
    return (f"m {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} b {w} {h} {w} {h} {w-r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h-r} l 0 {r} b 0 0 0 0 {r} 0")
esc = lambda s: s.replace('{', '(').replace('}', ')').replace('\\', '/')

# ---------- timeline anchors
TE = float(T.get('title_card_end', 4.5))
last_end = L[-1]['end']
ES = float(T.get('end_card_start', min(max(last_end + 0.6, DUR - 7.0), DUR - 3.5)))

# ---------- karaoke captions
CHORUS_KINDS = ('chorus', 'postchorus')
CAP_Y = 1275
for i, ln in enumerate(L):
    ch = ln['kind'] in CHORUS_KINDS
    size, style, maxw = (136, 'Chor', 1010) if ch else (100, 'Cap', 960)
    words = [w[0] for w in ln['words']]
    rows = wrap(words, F_BLACK, size, maxw)
    while len(rows) > 3 and size > 70:
        size -= 6; rows = wrap(words, F_BLACK, size, maxw)
    t = ln['ds']; parts = []
    for r in rows:
        seg = []
        for k in r:
            tok, s, e = ln['words'][k]
            gap = s - t
            if gap > 0.02: seg.append(f"{{\\k{int(round(gap * 100))}}}")
            if k + 1 < len(words):
                dur = max(min(ln['words'][k + 1][1], e + 0.3) - s, 0.08)
            else:
                dur = max(e - s, 0.08)
            seg.append(f"{{\\kf{int(round(dur * 100))}}}{esc(tok)} ")
            t = s + dur
        parts.append(''.join(seg).rstrip())
    txt = '\\N'.join(parts)
    fs = f"\\fs{size}" if size not in (100, 136) else ''
    y = CAP_Y - (20 if ch else 0)
    if ch:
        plain = '\\N'.join(' '.join(esc(words[k]) for k in r) for r in rows)
        D(9, ln['ds'], ln['de'], 'ChorGlow', f"{{\\pos({W//2},{y})\\blur18\\bord20\\1a&HFF&\\3a&H38&{fs}\\fad(120,150)\\fscx92\\fscy92\\t(0,160,\\fscx100\\fscy100)}}" + plain)
        D(10, ln['ds'], ln['de'], style, f"{{\\pos({W//2},{y})\\blur0.6{fs}\\fad(120,150)\\fscx92\\fscy92\\t(0,160,\\fscx100\\fscy100)}}" + txt)
    else:
        D(10, ln['ds'], ln['de'], style, f"{{\\pos({W//2},{y})\\fad(120,150)\\blur0.6{fs}}}" + txt)
    if i + 1 < len(L) and L[i + 1]['ds'] - ln['de'] < 3:
        D(10, ln['ds'], ln['de'], 'Next', f"{{\\pos({W//2},1745)\\fad(150,100)}}" + esc(L[i + 1]['text']))

# ---------- story / section tags
story = T.get('story_tags', [])
sec_over = T.get('section_tags', {})
defaults = {
    'intro': (f"AI NEWS \u00b7 {date.day} {date:%b %Y}".upper(), T.get('intro_text', "Today's AI news, as a song"), 'cyan'),
    'verse': ('', None, 'pink'),
    'prechorus': ('PRE-CHORUS', 'Here it comes\u2026', 'purple'),
    'chorus': ('CHORUS', 'Sing along!', 'yellow'),
    'postchorus': ('POST-CHORUS', 'Sing along!', 'yellow'),
    'bridge': ('BRIDGE', 'Hands in the air!', 'purple'),
    'outro': ('OUTRO', 'See you tomorrow on the feed', 'cyan'),
    'other': (None, '', 'cyan'), 'instrumental': (None, '', 'cyan'),
}
def tag_for(ln):
    for s in story:
        if s['section'].lower() == ln['section'].lower() and s['lines'][0] <= ln['line_no'] <= s['lines'][-1] \
                and ('occurrence' not in s or s['occurrence'] == ln['section_occ']):
            return (s.get('label', ''), s['text'], s.get('color', 'pink' if story.index(s) % 2 == 0 else 'cyan'))
    lab, txt, c = defaults.get(ln['kind'], defaults['other'])
    if ln['kind'] == 'chorus' and 'final' in ln['section'].lower(): lab = 'FINAL CHORUS'
    o = sec_over.get(ln['section']) or sec_over.get(ln['kind']) or {}
    lab = o.get('label', lab if (lab or ln['kind'] == 'verse') else ln['section'].upper()); txt = o.get('text', txt if txt is not None else ln['section'])
    return (lab, txt, o.get('color', c))
groups = []
for ln in L:
    tg = tag_for(ln)
    if groups and groups[-1]['tag'] == tg and groups[-1]['block'] == ln['block']:
        groups[-1]['end'] = ln['end']
    elif groups and groups[-1]['tag'] == tg and ln['start'] - groups[-1]['end'] < 6:
        groups[-1]['end'] = ln['end']
    else:
        groups.append({'tag': tg, 'start': ln['ds'], 'end': ln['end'], 'block': ln['block'], 'kind': ln['kind']})
spans = []
if groups and groups[0]['start'] > TE + 1.0:
    spans.append([TE, groups[0]['start'], defaults['intro']])
for gi, g in enumerate(groups):
    s = max(g['start'], TE) if gi == 0 else g['start']
    e = groups[gi + 1]['start'] if gi + 1 < len(groups) else ES
    nxt = groups[gi + 1] if gi + 1 < len(groups) else None
    if nxt and nxt['start'] - g['end'] > 6 and nxt['kind'] == 'verse':
        spans.append([s, g['end'] + 1.5, g['tag']])
        spans.append([g['end'] + 1.5, e, ('UP NEXT',) + tuple(nxt['tag'][1:])])
    else:
        spans.append([s, e, g['tag']])
spans = [[max(s, TE), min(e, ES), t] for s, e, t in spans if min(e, ES) - max(s, TE) > 0.3]
merged_spans = []
for sp in spans:                      # adjacent identical tags -> one box
    if merged_spans and merged_spans[-1][2] == sp[2] and abs(merged_spans[-1][1] - sp[0]) < 0.05:
        merged_spans[-1][1] = sp[1]
    else:
        merged_spans.append(sp)
spans = merged_spans
for s, e, (lab, txt, c) in spans:
    cc = COLS.get(c, c)
    size = 64
    tw = width(txt, F_BLACK, size)
    while tw > 920 and size > 40: size -= 2; tw = width(txt, F_BLACK, size)
    lw = (width(lab, F_XB, 34) + 4 * len(lab)) if lab else 0
    bw = int(max(tw, lw) + 90); bh = (132 if lab else 100) if txt else 80; x = (W - bw) // 2; y = 64
    fad = "\\fad(250,200)"
    D(4, s, e, 'Box', f"{{\\pos({x},{y})\\p1\\1c{col(cc)}\\1a&H70&\\blur14{fad}\\bord0\\shad0}}{rrect(bw, bh, 32)}")
    D(5, s, e, 'Box', f"{{\\pos({x},{y})\\p1\\1c{col(INK)}\\1a&H28&\\3c{col(cc)}\\bord4\\shad0{fad}}}{rrect(bw, bh, 32)}")
    if lab: D(6, s, e, 'TagL', f"{{\\pos({W//2},{y+14 if txt else 22})\\an8\\1c{col(cc)}{fad}}}{esc(lab)}")
    if txt: D(6, s, e, 'TagT', f"{{\\pos({W//2},{y+50 if lab else y+16})\\an8\\fs{size}{fad}}}{esc(txt)}")

# ---------- title card
D(7, 0, TE, 'Box', f"{{\\pos(0,0)\\p1\\1c{col(INK)}\\1a&H20&\\fad(0,500)}}m 0 0 l {W} 0 l {W} {H} l 0 {H}")
tw_ = (T.get('title_card') or title).upper().split()
tsize = 128
rows = wrap(tw_, F_MONO, tsize, 980, 4)
while any(width(' '.join(tw_[k] for k in r), F_MONO, tsize) > 980 for r in rows) and tsize > 70:
    tsize -= 8; rows = wrap(tw_, F_MONO, tsize, 980, 4)
gap = int(tsize * 1.17)
y0 = 700 - gap * (len(rows) - 1) / 2
for k, r in enumerate(rows):
    txt = ' '.join(tw_[i] for i in r); y = int(y0 + k * gap)
    D(8, 0, TE, 'Title', f"{{\\pos({W//2},{y})\\fs{tsize}\\1c{col(PINK)}\\bord10\\3c{col(PINK)}\\3a&H90&\\blur12\\fad(300,500)\\t(0,{int(TE*1000)},\\fscx106\\fscy106)}}{esc(txt)}")
    D(9, 0, TE, 'Title', f"{{\\pos({W//2},{y})\\fs{tsize}\\1c{col('ffe6f4')}\\bord0\\fad(300,500)\\t(0,{int(TE*1000)},\\fscx106\\fscy106)}}{esc(txt)}")
ysub = int(y0 + (len(rows) - 1) * gap + tsize * 0.5 + 140)
D(9, 0.3, TE, 'Sub', f"{{\\pos({W//2},{ysub})\\fs66\\fad(300,500)}}{esc(subtitle)}")
D(9, 0.5, TE, 'Small', f"{{\\pos({W//2},{ysub+90})\\fs42\\fad(300,500)\\1c{col(YEL)}}}{esc(T.get('tagline', 'a daily song from the feed'))}")

# ---------- end card
D(7, ES, DUR, 'Box', f"{{\\pos(0,0)\\p1\\1c{col(INK)}\\1a&H18&\\fad(600,0)}}m 0 0 l {W} 0 l {W} {H} l 0 {H}")
D(8, ES, DUR, 'Sub', f"{{\\pos({W//2},560)\\fs60\\1c{col(WHITE)}\\fad(600,0)}}MADE WITH")
D(8, ES, DUR, 'Title', f"{{\\pos({W//2},700)\\fs170\\1c{col(PINK)}\\bord12\\3c{col(PINK)}\\3a&H90&\\blur14\\fad(600,0)}}SUNO")
D(9, ES, DUR, 'Title', f"{{\\pos({W//2},700)\\fs170\\1c{col('ffe6f4')}\\bord0\\fad(600,0)}}SUNO")
tsz = 52
while width(title, F_BLACK, tsz) > 980 and tsz > 34: tsz -= 2
D(9, ES + 0.2, DUR, 'Sub', f"{{\\pos({W//2},900)\\fs{tsz}\\1c{col(YEL)}\\fad(600,0)}}{esc(title)}")
D(9, ES + 0.2, DUR, 'Small', f"{{\\pos({W//2},975)\\fad(600,0)}}AI news \u00b7 {DATE_LONG}")
if handles:
    D(9, ES + 0.6, DUR, 'Sub', f"{{\\pos({W//2},1150)\\fs58\\1c{col(CYAN)}\\fad(500,0)}}SOURCES ON X")
    hrows = wrap([h + ' \u00b7' for h in handles], FD + 'Poppins/Poppins-SemiBold.ttf', 36, 900, 6)
    htxt = '\\N'.join(' \u00b7 '.join(esc(handles[k]) for k in r) for r in hrows)
    D(9, ES + 0.6, DUR, 'Small', f"{{\\pos({W//2},{1250 + 25 * len(hrows)})\\fs36\\fad(500,0)}}{htxt}")
    yl = 1300 + 50 * len(hrows)
else:
    yl = 1250
D(9, ES + 0.9, DUR, 'Small', f"{{\\pos({W//2},{yl})\\fs34\\1c{col(YEL)}\\fad(500,0)}}links in the post \u2193")
url = T.get('song_url')
if url:
    D(9, ES + 0.9, DUR, 'Small', f"{{\\pos({W//2},{yl+60})\\fs28\\1c{col(WHITE)}\\fad(500,0)}}{esc(url.replace('https://', ''))}")
HANDLE = T.get('handle', '@jxwalker')
D(1, TE, ES, 'Foot', f"{esc(HANDLE)}  \u00b7  {esc(title.upper())}  \u00b7  AI NEWS {date:%d.%m.%Y}")
D(1, 0, TE, 'Foot', esc(HANDLE))
D(1, ES, DUR, 'Foot', esc(HANDLE))
open(os.path.join(work, 'video.ass'), 'w').write(hdr + '\n'.join(ev) + '\n')
C.save_json({'title_end': TE, 'end_start': ES, 'tag_spans': [[round(s, 2), round(e, 2), list(t)] for s, e, t in spans]},
            os.path.join(work, 'layout.json'))
for s, e, t in spans: print(f"tag {s:7.2f}-{e:7.2f} {t[0]} | {t[1]}")
print('events', len(ev), 'title_end', TE, 'end_card', round(ES, 2))
