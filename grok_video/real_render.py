"""cine-real style renderer: local camera moves on stills (push / pull / pan / tilt / parallax / handheld), hero video
windows, one bold grade + grain + halation + light leaks, white flashes and whips on drops, giant kinetic lyric type
(ASS, libass), 2-3 s credits. Frames are rendered in python (OpenCV) and piped straight into ffmpeg with the song."""
import math, os, random, re, subprocess, time
import numpy as np
import cv2
import common_gv as G

W, H, FPS = 1080, 1920, 30
OVER = 1.12                      # overscan of the prepared sources (room for moves and shake)
SW, SH = int(W * OVER) // 2 * 2, int(H * OVER) // 2 * 2


# ------------------------------------------------------------------------------------------------ grade
_VIG = {}


def _vignette(h, w, v=0.32):
    if (h, w, v) not in _VIG:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        _VIG[(h, w, v)] = np.clip(1 + 0.375 * v - v * r ** 2, 0.55, 1)[..., None].astype(np.float32)
    return _VIG[(h, w, v)]


def grade(img, LK):
    """img: BGR uint8 -> graded BGR uint8 (same size)."""
    f = img.astype(np.float32) / 255.0
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)          # H 0..360, S 0..1, V 0..1
    sat = hsv[..., 1]
    if LK.get('accent_hue') is not None:
        d = np.abs(((hsv[..., 0] - LK['accent_hue']) + 180) % 360 - 180)
        keep = np.clip((28 - d) / 14, 0, 1) * np.clip((sat - 0.18) / 0.2, 0, 1)
    else:
        keep = np.zeros_like(sat)
    hsv[..., 1] = np.clip(sat * (LK['sat'] * (1 - keep) + 1.2 * keep), 0, 1)
    f = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if LK.get('vhs'):
        small = cv2.resize(f, (f.shape[1] // 2, f.shape[0] // 2), interpolation=cv2.INTER_AREA)
        f = cv2.resize(small, (f.shape[1], f.shape[0]), interpolation=cv2.INTER_LINEAR)
        f[..., 2] = np.roll(f[..., 2], 3, axis=1)
    lum = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[..., None]
    tr, tg, tb = LK.get('tint', (0, 0, 0))
    f = f + (1 - lum) * np.array([tb, tg, tr], np.float32) / 255.0 * 1.6
    c = LK.get('contrast', 1.1)
    f = np.clip(0.5 + (f - 0.5) * c, 0, 1)
    cr = LK.get('crush', 0.035)
    f = np.clip((f - cr) / (1 - cr), 0, 1)             # crush the blacks a little (glossy looks: lift)
    # halation: blurred highlights, warm-red, added back
    hl = np.clip((cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) - 0.72) / 0.28, 0, 1)
    hl = cv2.GaussianBlur(hl, (0, 0), f.shape[1] / 70)
    f = f + hl[..., None] * np.array([0.10, 0.16, 0.38], np.float32)
    f = f * _vignette(f.shape[0], f.shape[1], LK.get('vignette', 0.32))
    return np.clip(f * 255, 0, 255).astype(np.uint8)


def prep_still(path, LK):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = max(SW / w, SH / h)
    img = cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_CUBIC)
    y0, x0 = (img.shape[0] - SH) // 2, (img.shape[1] - SW) // 2
    img = img[y0:y0 + SH, x0:x0 + SW]
    img = grade(img, LK)
    blur = cv2.GaussianBlur(img, (0, 0), 1.2)               # gentle sharpen after the upscale
    return cv2.addWeighted(img, 1.35, blur, -0.35, 0)


# ------------------------------------------------------------------------------------------------ motion
def ease_out(p):
    return 1 - (1 - p) ** 3


def noise(t, seed, amp, speed=1.0):
    r = random.Random(seed)
    ph = [r.random() * 6.28 for _ in range(6)]
    return amp * (0.55 * math.sin(t * 7.1 * speed + ph[0]) + 0.3 * math.sin(t * 13.3 * speed + ph[1])
                  + 0.15 * math.sin(t * 23.7 * speed + ph[2]))


def move_params(move, p, k, cut_in):
    """scale, dx, dy (fractions of the output size), rotation (deg) for progress p in 0..1 at strength k."""
    e = ease_out(p)
    base = 1.0 if not cut_in else 1.32
    s, dx, dy, rot = base, 0.0, 0.0, 0.0
    if move == 'push_in':
        s = base * (1.0 + 0.16 * k * e)
    elif move == 'pull_out':
        s = base * (1.17 - 0.16 * k * e)
    elif move in ('pan_left', 'pan_right'):
        s = base * 1.1; dx = (0.05 - 0.10 * e) * k * (1 if move == 'pan_left' else -1)
    elif move in ('tilt_up', 'tilt_down'):
        s = base * 1.1; dy = (0.05 - 0.10 * e) * k * (1 if move == 'tilt_up' else -1)
    elif move == 'parallax':
        s = base * (1.03 + 0.14 * k * e); dx = 0.035 * k * (e - 0.5); rot = 1.6 * k * (e - 0.5)
    elif move == 'shake':
        s = base * 1.08
    else:  # drift
        s = base * (1.04 + 0.06 * e); dx = 0.02 * (e - 0.5); dy = -0.015 * e
    return s, dx, dy, rot


def warp(src, s, dx, dy, rot, cx=0.5, cy=0.5):
    """Sample an output W x H frame from the overscanned source."""
    sh, sw = src.shape[:2]
    a = math.radians(rot)
    k = s * W / (sw / OVER)               # output px per source px
    ca, sa = math.cos(a) * k, math.sin(a) * k
    ox, oy = sw * cx, sh * cy
    M = np.array([[ca, -sa, W / 2 + dx * W - (ca * ox - sa * oy)],
                  [sa, ca, H / 2 + dy * H - (sa * ox + ca * oy)]], np.float32)
    return cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ------------------------------------------------------------------------------------------------ fx
class Grain:
    def __init__(self, amp, seed=1):
        r = np.random.default_rng(seed)
        self.tiles = [np.clip(r.normal(0, amp, (H // 2, W // 2)), -40, 40).astype(np.int16) for _ in range(6)]
        self.tiles = [cv2.resize(t.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR).astype(np.int16) for t in self.tiles]
        self.i = 0

    def apply(self, frame):
        self.i = (self.i + 1) % len(self.tiles)
        f = frame.astype(np.int16) + self.tiles[self.i][..., None]
        return np.clip(f, 0, 255).astype(np.uint8)


def leak(frame, colour, p, seed):
    r = random.Random(seed)
    cx = (r.uniform(-0.2, 0.3) + 0.9 * p) * W
    cy = r.uniform(0.1, 0.9) * H
    rad = r.uniform(0.45, 0.8) * W
    yy, xx = np.ogrid[0:H:4, 0:W:4]
    m = np.exp(-(((xx * 1.0 - cx / 1) ** 2 + (yy * 1.0 - cy) ** 2) / (rad ** 2)))
    m = cv2.resize(m.astype(np.float32), (W, H)) * (0.42 * math.sin(math.pi * min(max(p, 0), 1)))
    col = np.array(colour[::-1], np.float32)
    f = frame.astype(np.float32) + m[..., None] * col
    return np.clip(f, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------------ type (ASS)
def ass_colour(rgb, alpha=0):
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def esc(t):
    return t.replace('{', '(').replace('}', ')').replace('\\', '/')


def ts(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def line_tokens(ln, disp):
    """[(token, start, end)] for a sung line, using the planner's display tokens ('' merges into the previous)."""
    words = ln['words']
    toks = disp if disp and len(disp) == len(words) else [w[0] for w in words]
    out = []
    for (w, a, b), tk in zip(words, toks):
        tk = (tk or '').strip()
        if not tk and out:
            out[-1] = (out[-1][0], out[-1][1], b)
            continue
        tk = re.sub(r'[,.;:!?"]+$', '', tk or w).strip() or w
        out.append((tk, a, b))
    return out


def group_tokens(toks, kind):
    mx = 2 if kind in ('chorus', 'intro', 'outro') else 3
    groups, cur = [], []
    for t in toks:
        if cur and (len(cur) >= mx or t[1] - cur[-1][2] > 0.32 or sum(len(x[0]) for x in cur) + len(t[0]) > 15):
            groups.append(cur); cur = []
        cur.append(t)
    if cur:
        groups.append(cur)
    return groups


_FONT = None


def text_w(t):
    """width of t in px for ASS \\fs 1 (Anton; libass sizes the font by ascender+descender)."""
    global _FONT
    if _FONT is None:
        from PIL import ImageFont
        path = subprocess.run(['fc-match', '-f', '%{file}', 'Anton'], capture_output=True, text=True).stdout.strip()
        f = ImageFont.truetype(path, 1000)
        a, d = f.getmetrics()
        _FONT = (f, a + d)
    f, m = _FONT
    return f.getlength(t) / m * 1.04 + 0.01 * len(t)


def layout(words):
    """split a group into 1-2 display lines and pick the biggest font size that fits 900 px (giant type)."""
    text = ' '.join(words)
    if len(text) <= 9 or len(words) == 1:
        lines = [list(range(len(words)))]
    else:
        best = None
        for k in range(1, len(words)):
            a, b = ' '.join(words[:k]), ' '.join(words[k:])
            m = max(len(a), len(b))
            if best is None or m < best[0]:
                best = (m, k)
        k = best[1]
        lines = [list(range(k)), list(range(k, len(words)))]
    widest = max(text_w(' '.join(words[i] for i in ln)) for ln in lines)
    size = int(max(110, min(560 if len(lines) == 1 else 420, 900 / max(widest, 1e-3))))
    return lines, size


def build_ass(path, L, display, accent, cuts_meta, LK, credits, dur, hook_words, footer='@jxwalker'):
    if LK.get('type') == 'sparse':
        return build_ass_sparse(path, L, display, accent, LK, credits, dur, hook_words, footer)
    acc = ass_colour(LK['accent'])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Slam,Anton,200,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,9,5,5,40,40,40,1
Style: Small,Anton,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,2,0,1,4,2,5,40,40,40,1
Style: VHS,DejaVu Sans Mono,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,7,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    rnd = random.Random(11)
    end_type = credits['t0'] - 1.6
    sung = [ln for ln in L if ln.get('words')]
    # hook: the first sung words, giant, from frame 0
    if hook_words:
        lines, size = layout(hook_words)
        txt = '\\N'.join(' '.join((f"{{\\c{acc}}}" + esc(hook_words[i].upper()) + "{\\c&H00FFFFFF&}") if i == len(hook_words) - 1 else esc(hook_words[i].upper()) for i in ln) for ln in lines)
        ev.append(f"Dialogue: 5,{ts(0)},{ts(1.7)},Slam,,0,0,0,,{{\\pos(540,1000)\\fs{size}\\fscx135\\fscy135\\t(0,120,\\fscx100\\fscy100)\\fad(0,120)}}{txt}")
    for li, ln in enumerate(sung):
        lid = f"{ln['section']}#{ln['section_occ']}:{ln['line_no']}"
        toks = line_tokens(ln, display.get(lid))
        accs = {re.sub(r'[,.;:!?"]+$', '', a).strip().lower() for a in accent.get(lid, [])}
        groups = group_tokens(toks, ln['kind'])
        nxt_line = sung[li + 1]['words'][0][1] if li + 1 < len(sung) else dur
        for gi, g in enumerate(groups):
            g0 = g[0][1] - 0.03
            g1 = groups[gi + 1][0][1] - 0.03 if gi + 1 < len(groups) else min(g[-1][2] + 0.45, nxt_line - 0.05)
            g1 = max(g1, g0 + 0.25)
            if g0 >= end_type:
                continue
            g1 = min(g1, end_type)
            words = [t[0].upper() for t in g]
            lines, size = layout(words)
            chorus = ln['kind'] in ('chorus', 'intro', 'outro')
            y = 960 if chorus else 1060
            rot = rnd.uniform(-3, 3) if chorus else 0
            for k, (tk, a, b) in enumerate(g):
                s0 = g0 if k == 0 else a - 0.03
                s1 = (g[k + 1][1] - 0.03) if k + 1 < len(g) else g1
                if s1 <= s0:
                    continue
                parts = []
                for ln_idx in lines:
                    seg = []
                    for i in ln_idx:
                        w = esc(words[i])
                        col = acc if (g[i][0].lower() in accs or re.search(r'\d', g[i][0])) else '&H00FFFFFF&'
                        if i > k:
                            seg.append(f"{{\\alpha&HFF&}}{w}{{\\alpha&H00&}}")
                        elif i == k and k > 0:
                            seg.append(f"{{\\c{col}\\fscx122\\fscy122\\t(0,90,\\fscx100\\fscy100)}}{w}{{\\c&H00FFFFFF&}}")
                        else:
                            seg.append(f"{{\\c{col}}}{w}{{\\c&H00FFFFFF&}}")
                    parts.append(' '.join(seg))
                slam = "\\fscx128\\fscy128\\t(0,100,\\fscx100\\fscy100)" if k == 0 else ""
                ev.append(f"Dialogue: 5,{ts(s0)},{ts(s1)},Slam,,0,0,0,,{{\\pos(540,{y})\\fs{size}\\frz{rot:.1f}{slam}}}" + '\\N'.join(parts))
    # credits (2-3 s)
    c0, c1 = credits['t0'], dur
    def fit(t, cap, width=920):
        return int(min(cap, width / max(text_w(t), 1e-3)))
    rows = credits['rows']
    ev.append(f"Dialogue: 6,{ts(c0)},{ts(c1)},Slam,,0,0,0,,{{\\pos(540,640)\\fs{fit('MADE WITH SUNO', 300)}\\fad(120,0)}}MADE WITH {{\\c{acc}}}SUNO")
    rs = min([fit(r, 104, 900) for r in rows] or [104])          # one size for all handle rows, phone-readable
    step = int(rs * 1.18)
    y = 640 + 150 + step // 2
    for row in rows:
        ev.append(f"Dialogue: 6,{ts(c0 + 0.1)},{ts(c1)},Small,,0,0,0,,{{\\pos(540,{y})\\fs{rs}\\fad(150,0)}}{esc(row)}")
        y += step
    footer = credits.get('footer', footer)            # None = no sources (gift songs etc.): no footer
    if footer:
        ft = f"SOURCES ON X  ·  {footer}"
        ev.append(f"Dialogue: 6,{ts(c0 + 0.1)},{ts(c1)},Small,,0,0,0,,{{\\pos(540,{y + 40})\\fs{fit(ft, 76, 860)}\\alpha&H20&}}{esc(ft)}")
    if LK.get('vhs'):
        for sec in range(int(c0)):
            ev.append(f"Dialogue: 4,{ts(sec)},{ts(sec + 1)},VHS,,0,0,0,,{{\\pos(60,90)}}PLAY ▶\\N{{\\fs38}}0:{sec // 60:02d}:{sec % 60:02d}")
    open(path, 'w').write(head + '\n'.join(ev) + '\n')
    return len(ev)


FILLER_SLAMS = {'know', 'go', 'get', 'got', 'it', 'all', 'now', 'yeah', 'oh', 'up', 'out', 'down', 'the', 'and', 'you',
                'me', 'we', 'this', 'that', 'so', 'just', 'again', 'away', 'right', 'way', 'time', 'thing', 'things'}


def _filler_slam(tok):
    """P7: a weak giant slam word (filler or an -ING verb); numbers are never filler."""
    t = re.sub(r'[^a-z0-9%$+.]', '', tok.lower())
    if not t or re.search(r'\d', t):
        return False
    return t in FILLER_SLAMS or (t.endswith('ing') and len(t) > 4)


def diegetic_ok(text, vocab):
    """spell check: every word must appear in the day's stories / lyrics / title / treatment."""
    v = set(vocab or [])
    ws = re.findall(r"[A-Za-z0-9@%$.'+-]+", text)
    bad = [w for w in ws if w.lower() not in v and w.lower().strip(".'!?,") not in v]
    return not bad, bad


def narrative_events(NV, sung, display, acc, end_type, dur):
    ev = []
    title = (NV.get('title') or '').upper()
    first = sung[0]['words'][0][1] if sung else 2.0
    if title:
        t1 = max(1.6, min(first - 0.1, 3.5))
        rows = [title] if len(title) <= 14 or ' ' not in title else [title[:title.rfind(' ', 0, len(title) // 2 + 4)], title[title.rfind(' ', 0, len(title) // 2 + 4) + 1:]]
        size = int(min(220, min(960 / max(text_w(r), 1e-3) for r in rows)))
        ev.append(f"Dialogue: 6,{ts(0.05)},{ts(t1)},Title,,0,0,0,,{{\\pos(540,900)\\fs{size}\\fscx114\\fscy114\\t(0,140,\\fscx100\\fscy100)\\fad(0,160)}}" + '\\N'.join(esc(r) for r in rows))
    NV.setdefault('dropped', [])
    for li, ln in enumerate(sung):
        lid = f"{ln['section']}#{ln['section_occ']}:{ln['line_no']}"
        nxt = sung[li + 1]['words'][0][1] if li + 1 < len(sung) else dur
        toks = line_tokens(ln, display.get(lid))
        a0 = toks[0][1] - 0.05
        a1 = min(max(min(toks[-1][2] + 0.5, nxt - 0.06), a0 + 0.6), end_type)
        if a0 >= end_type:
            continue
        if ln['kind'] == 'chorus':                     # the chorus hook line, same style on every repeat
            ev.append(f"Dialogue: 5,{ts(a0)},{ts(a1)},Hook,,0,0,0,,{{\\fad(80,100)\\3c{acc}}}" + esc(' '.join(t[0] for t in toks).upper()))
        txt = ((NV.get('onscreen') or {}).get(lid) or '').strip()
        if txt and a0 < NV.get('_dg_end', -1):          # never two diegetic labels at once (13 Oct QA)
            NV['dropped'].append({'seg': lid, 'text': txt, 'bad': ['overlap']}); txt = ''
        if txt:
            ok, bad = diegetic_ok(txt, NV.get('vocab'))
            if ok and len(txt.split()) <= 6:
                NV['_dg_end'] = min(a1 + 0.2, nxt - 0.05, end_type)
                ev.append(f"Dialogue: 4,{ts(a0)},{ts(NV['_dg_end'])},Diegetic,,0,0,0,,{{\\fad(120,120)}}" + esc(txt))
            else:
                NV['dropped'].append({'seg': lid, 'text': txt, 'bad': bad})
    return ev


def _norm(t):
    return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


TICK_Y, TICK_H, TICK_PX_S = 1630, 84, 230      # band top (px), band height, scroll speed (px/s)
LYR_MV = 1920 - TICK_Y + 26                   # lyric captions sit just above the ticker band


def headline_events(HV, sung, display, acc, end_type, dur):
    """headline mode (13 Oct): the title card in the hook (0-3 s); ONE big headline card on the main story's first sung
    line; the chorus hook words on chorus lines (one style); a news ticker along the bottom during story lines,
    scrolling '@handle fact' of the story being sung and changing exactly when the story changes. No other text."""
    ev = []
    title = (HV.get('title') or '').upper()
    first = sung[0]['words'][0][1] if sung else 3.0
    if title:
        t1 = max(1.6, min(3.0, first - 0.1))
        rows = [title] if len(title) <= 14 or ' ' not in title else [title[:title.rfind(' ', 0, len(title) // 2 + 4)], title[title.rfind(' ', 0, len(title) // 2 + 4) + 1:]]
        size = int(min(220, min(960 / max(text_w(r), 1e-3) for r in rows)))
        ev.append(f"Dialogue: 6,{ts(0.05)},{ts(t1)},Title,,0,0,0,,{{\\pos(540,900)\\fs{size}\\fscx114\\fscy114\\t(0,140,\\fscx100\\fscy100)\\fad(0,160)}}" + '\\N'.join(esc(r) for r in rows))
    ls_ = HV.get('line_story') or {}
    hook = _norm(HV.get('hook_words') or '')
    spans, card_done = [], False                   # ticker spans [(story, t0, t1)]
    for li, ln in enumerate(sung):
        lid = f"{ln['section']}#{ln['section_occ']}:{ln['line_no']}"
        nxt = sung[li + 1]['words'][0][1] if li + 1 < len(sung) else dur
        toks = line_tokens(ln, display.get(lid))
        a0 = toks[0][1] - 0.05
        a1 = min(max(min(toks[-1][2] + 0.5, nxt - 0.06), a0 + 0.6), end_type)
        if a0 >= end_type:
            continue
        story = ls_.get(_norm(ln.get('text') or ' '.join(t[0] for t in toks)), 0)
        is_ch = ln['kind'] == 'chorus' or re.fullmatch(r'(final |last )?chorus.*', ln['section'].lower())
        if not is_ch and story == 0 and ln['kind'] == 'other':  # 13 Oct: a meta tag ([Key Change]) parsed as a section
            is_ch = True
        if is_ch:
            story = 0

        # 13 Oct (the owner: "we might need all the lyrics"): EVERY sung line as a word-synced karaoke caption above the
        # ticker; chorus lines bigger in the hook style. Words fill in as they are sung (\\kf from the alignment).
        kf, prev = [], a0
        for k, (tk, w0, w1) in enumerate(toks):
            w0 = max(w0, prev)
            gap = int(round((w0 - prev) * 100))
            dur_cs = max(1, int(round(((toks[k + 1][1] if k + 1 < len(toks) else w1) - w0) * 100)))
            kf.append((f"{{\\k{gap}}}" if gap > 0 else '') + f"{{\\kf{dur_cs}}}" + esc(tk if not is_ch else tk.upper()))
            prev = w0 + dur_cs / 100
        sty = 'LyricHook' if is_ch else 'Lyric'
        ev.append(f"Dialogue: 5,{ts(a0)},{ts(a1)},{sty},,0,0,0,,{{\\fad(60,80)\\q0}}" + ' '.join(kf))
        if story and story == HV.get('main') and not card_done and HV.get('card'):
            card_done = True
            c1 = min(a0 + 2.6, end_type)                # 2.6 s: long enough to read 2-6 words
            ev.append(f"Dialogue: 6,{ts(a0)},{ts(c1)},HCard,,0,0,0,,{{\\fscx110\\fscy110\\t(0,90,\\fscx100\\fscy100)\\fad(0,120)}}" + esc(HV['card'].upper()))
        if story and story in (HV.get('ticker') or {}):
            t_end = min(nxt - 0.08, end_type) if li + 1 < len(sung) else min(a1, end_type)
            if spans and spans[-1][0] == story and a0 - spans[-1][2] < 2.5:
                spans[-1][2] = t_end
            else:
                spans.append([story, a0, t_end])
    HV['spans'] = [(a, round(b, 2), round(c, 2)) for a, b, c in spans]
    band = f"m 0 0 l 1080 0 l 1080 {TICK_H} l 0 {TICK_H}"
    for story, t0, t1 in spans:
        txt = HV['ticker'][story]
        unit = esc(txt) + '      •      '
        fs = 60
        w_unit = text_w(txt + '      •      ') * fs
        dur_s = t1 - t0
        need = 1080 + TICK_PX_S * dur_s
        reps = max(3, 2 * int(need / max(w_unit, 1)) + 2)      # text_w is Anton; Inter runs wider: double up
        x0, x1 = 300, int(300 - TICK_PX_S * dur_s)
        ev.append(f"Dialogue: 2,{ts(t0)},{ts(t1)},Ticker,,0,0,0,,{{\\an7\\pos(0,{TICK_Y})\\p1\\1c&H101010&\\1a&H30&\\fad(120,120)}}{band}")
        ev.append(f"Dialogue: 3,{ts(t0)},{ts(t1)},Ticker,,0,0,0,,{{\\an4\\move({x0},{TICK_Y + TICK_H // 2},{x1},{TICK_Y + TICK_H // 2})\\clip(270,{TICK_Y},1080,{TICK_Y + TICK_H})\\q2\\fs{fs}\\fad(120,120)}}" + unit * reps)
        ev.append(f"Dialogue: 4,{ts(t0)},{ts(t1)},TickTag,,0,0,0,,{{\\an7\\pos(0,{TICK_Y})\\p1\\1c{acc}\\fad(120,120)}}m 0 0 l 260 0 l 260 {TICK_H} l 0 {TICK_H}")
        ev.append(f"Dialogue: 5,{ts(t0)},{ts(t1)},TickTag,,0,0,0,,{{\\an5\\pos(130,{TICK_Y + TICK_H // 2})\\c&H00000000&\\fad(120,120)}}BREAKING")
    return ev


def build_ass_sparse(path, L, display, accent, LK, credits, dur, hook_words, footer='@jxwalker', day_label=None):
    """slopcore type (javif4_ / SAY. SI. style): a small clean subtitle of the whole line with the punch word in the
    accent colour, plus at most one giant single-word slam per line (chorus / punchline words); a found-footage overlay (VHS PLAY /
    timecode / date, or a digicam date stamp) on every frame before the credits."""
    acc = ass_colour(LK['accent'])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Slam,Anton,200,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,7,6,5,40,40,40,1
Style: Sub,Inter,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,4,3,2,90,90,300,1
Style: Small,Anton,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,2,0,1,4,2,5,40,40,40,1
Style: VHS,DejaVu Sans Mono,50,&H00F0F0F0,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,1,0,1,1.5,2,7,70,70,90,1
Style: Card,Anton,130,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,3,14,0,8,50,50,330,1
Style: Hook,Anton,116,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,2,0,1,5,4,2,70,70,330,1
Style: Title,Anton,170,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,3,0,1,8,6,5,50,50,40,1
Style: Diegetic,DejaVu Sans,64,&H00202020,&H00FFFFFF,&H00F2F2F2,&H00F2F2F2,1,0,0,0,100,100,0,0,3,18,0,8,120,120,260,1
Style: Ticker,Inter,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,4,0,0,0,1
Style: TickTag,Anton,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,4,0,0,0,1
Style: Lyric,Inter,62,&H0040D8FF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,4,2,2,80,80,{LYR_MV},1
Style: LyricHook,Anton,104,&H0040D8FF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,6,3,2,60,60,{LYR_MV},1
Style: HCard,Anton,120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,3,22,0,8,60,60,300,1
Style: Stamp,DejaVu Sans Mono,58,&H000090FF,&H00FFFFFF,&H00002040,&H00000000,1,0,0,0,100,100,2,0,1,1,1,3,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    end_type = credits['t0'] - 0.2
    sung = [ln for ln in L if ln.get('words')]
    HV = LK.get('headline')
    if HV:                                             # headline mode: title, ticker, headline card, chorus hook words
        ev += headline_events(HV, sung, display, acc, end_type, dur)
        hook_words = None
        sung = []
    NV = LK.get('narrative')
    if NV:                                             # narrative mode: title card, chorus hook line, diegetic text only
        ev += narrative_events(NV, sung, display, acc, end_type, dur)
        hook_words = None
        sung = []
    if hook_words:
        w = esc(hook_words[0].upper())
        _, size = layout([hook_words[0].upper()])
        ev.append(f"Dialogue: 5,{ts(0)},{ts(1.3)},Slam,,0,0,0,,{{\\pos(540,900)\\fs{min(size, 470)}\\fscx130\\fscy130\\t(0,110,\\fscx100\\fscy100)\\fad(0,100)}}{w}")
    slam_n = 0
    last_slam = 1.3 if hook_words else -9.0
    for li, ln in enumerate(sung):
        lid = f"{ln['section']}#{ln['section_occ']}:{ln['line_no']}"
        toks = line_tokens(ln, display.get(lid))
        accs = [re.sub(r'[,.;:!?"]+$', '', a).strip().lower() for a in accent.get(lid, [])][:2]
        nxt = sung[li + 1]['words'][0][1] if li + 1 < len(sung) else dur
        a0 = toks[0][1] - 0.05
        a1 = min(toks[-1][2] + 0.5, nxt - 0.06)
        if a0 >= end_type:
            continue
        a1 = min(max(a1, a0 + 0.6), end_type)
        parts = []
        for tk, _, _ in toks:
            col = acc if tk.lower() in accs else '&H00FFFFFF&'
            parts.append(f"{{\\c{col}}}{esc(tk)}{{\\c&H00FFFFFF&}}" if col != '&H00FFFFFF&' else esc(tk))
        ev.append(f"Dialogue: 3,{ts(a0)},{ts(a1)},Sub,,0,0,0,,{{\\fad(60,80)}}" + ' '.join(parts))
        # giant slams at reference density: at most ONE per line, mostly chorus/intro/outro (first accent token, else
        # the last word) and verse punchlines (the accent of the last line of a section, or every other verse line);
        # never within 1.8 s of the previous slam. The small red-keyword subtitle carries the rest.
        card = (LK.get('story_cards') or {}).get(lid) if ln['kind'] not in ('chorus', 'intro', 'outro') else None
        if card and toks[0][1] - last_slam >= 0.9:
            # P7 story card: "@handle" (accent) over a 3-6 word headline, slammed in on the line's first sung word
            c0 = toks[0][1] - 0.04
            c1 = min(c0 + 2.2, max(a1 + 0.3, c0 + 1.4), nxt + 0.6, end_type)
            hl = card['headline'].upper()
            rows_ = [hl]
            if len(hl) > 16 and ' ' in hl:                 # two big rows beat one small row
                sp = [i for i, ch in enumerate(hl) if ch == ' ']
                cut = min(sp, key=lambda i: abs(i - len(hl) / 2))
                rows_ = [hl[:cut], hl[cut + 1:]]
            hs = int(min(165, min(960 / max(text_w(r), 1e-3) for r in rows_)))
            hl = '\\N'.join(esc(r) for r in rows_)
            tg = card.get('tag') or ''
            ts_ = int(min(95, 900 / max(text_w(tg), 1e-3))) if tg else 0
            body = (f"{{\\fs{ts_}\\c{acc}}}{esc(tg)}\\N" if tg else '') + f"{{\\fs{hs}\\c&H00FFFFFF&}}{hl}"
            ev.append(f"Dialogue: 5,{ts(c0)},{ts(c1)},Card,,0,0,0,,{{\\fscx112\\fscy112\\t(0,80,\\fscx100\\fscy100)"
                      f"\\fad(0,90)}}" + body)
            last_slam = c1
            continue
        last_of_sec = li + 1 >= len(sung) or sung[li + 1]['section'] != ln['section'] or sung[li + 1]['section_occ'] != ln['section_occ']
        pick = [t for t in toks if t[0].lower() in accs][:1]
        if ln['kind'] in ('chorus', 'outro', 'intro'):
            pick = pick or [toks[-1]]
        elif not (last_of_sec or ln['line_no'] % 2 == 0):
            pick = []
        pick = [t for t in pick if not _filler_slam(t[0])]      # P7: no KNOW / RUNNING / LAUGHING filler slams
        if pick and pick[0][1] - last_slam < 1.8:
            pick = []
        if pick:
            last_slam = pick[0][1]
        for k, (tk, s0, s1) in enumerate(pick):
            e0 = s0 - 0.04
            e1 = min(max(s1 + 0.35, e0 + 0.5), e0 + 0.9, a1, nxt - 0.05, end_type)   # a hit, never bleeding into the next line
            if k + 1 < len(pick):
                e1 = min(e1, pick[k + 1][1] - 0.05)
            if e1 - e0 < 0.25:
                continue
            word = tk.upper()
            _, size = layout([word])
            size = min(size, 520)
            # P7 colour code by word kind: numbers and news nouns (the planner's accent outside the chorus) in the
            # look's accent colour; chorus / hook words in white
            news = bool(re.search(r'\d', tk)) or (tk.lower() in accs and ln['kind'] not in ('chorus', 'intro', 'outro'))
            col = acc if news else '&H00FFFFFF&'
            slam_n += 1
            y = 880 if ln['kind'] == 'chorus' else 960
            ev.append(f"Dialogue: 5,{ts(e0)},{ts(e1)},Slam,,0,0,0,,{{\\pos(540,{y})\\fs{size}\\c{col}"
                      f"\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}}{esc(word)}")
    # credits (2-3 s)
    c0, c1 = credits['t0'], dur
    def fit(t, cap, width=920):
        return int(min(cap, width / max(text_w(t), 1e-3)))
    rows = credits['rows']
    ev.append(f"Dialogue: 6,{ts(c0)},{ts(c1)},Slam,,0,0,0,,{{\\pos(540,640)\\fs{fit('MADE WITH SUNO', 300)}\\fad(120,0)}}MADE WITH {{\\c{acc}}}SUNO")
    rs = min([fit(r, 104, 900) for r in rows] or [104])
    step = int(rs * 1.18)
    y = 640 + 150 + step // 2
    for row in rows:
        ev.append(f"Dialogue: 6,{ts(c0 + 0.1)},{ts(c1)},Small,,0,0,0,,{{\\pos(540,{y})\\fs{rs}\\fad(150,0)}}{esc(row)}")
        y += step
    footer = credits.get('footer', footer)            # None = no sources (gift songs etc.): no footer
    if footer:
        ft = f"SOURCES ON X  ·  {footer}"
        ev.append(f"Dialogue: 6,{ts(c0 + 0.1)},{ts(c1)},Small,,0,0,0,,{{\\pos(540,{y + 40})\\fs{fit(ft, 76, 860)}\\alpha&H20&}}{esc(ft)}")
    # found-footage overlay
    ov = LK.get('overlay') or ('vhs' if LK.get('vhs') else None)
    dl = day_label or LK.get('day_label') or ('', '10:00')      # undated folders: no date on the overlay
    if ov == 'vhs':
        ev.append(f"Dialogue: 4,{ts(0)},{ts(c0)},VHS,,0,0,0,,{{\\an9\\pos(1010,90)}}PLAY ▶")
        ev.append(f"Dialogue: 4,{ts(0)},{ts(c0)},VHS,,0,0,0,,{{\\an7\\pos(70,90)}}TBC")
        # the camcorder clock runs from the routine's start time to just before midnight: the song is one day
        h0, m0 = (int(x) for x in dl[1].split(':'))
        start_min, end_min = h0 * 60 + m0, 23 * 60 + 59
        for sec in range(int(c0) + 1):
            mn = int(start_min + (end_min - start_min) * min(sec / max(c0 - 1, 1), 1.0))
            hh, mm = divmod(mn, 60)
            ampm = 'AM' if hh < 12 else 'PM'
            h12 = hh % 12 or 12
            ev.append(f"Dialogue: 4,{ts(sec)},{ts(min(sec + 1, c0))},VHS,,0,0,0,,{{\\an1\\pos(70,1830)}}{ampm} {h12:02d}:{mm:02d}" + (f"\\N{dl[0]}" if dl[0] else ''))
        fps = 25
        t = 0.0
        while t < c0:                                  # running tape timecode, 4 updates a second
            fr = int(round((t % 1) * fps))
            ev.append(f"Dialogue: 4,{ts(t)},{ts(min(t + 0.25, c0))},VHS,,0,0,0,,{{\\an9\\pos(1010,150)\\fs44}}"
                      f"0:{int(t) // 60:02d}:{int(t) % 60:02d}:{fr:02d}")
            t += 0.25
    elif ov == 'datestamp' and dl[0]:
        ev.append(f"Dialogue: 4,{ts(0)},{ts(c0)},Stamp,,0,0,0,,{{\\an3\\pos(1000,1840)}}'26 {dl[0][:3]} {dl[0][4:6]}")
    open(path, 'w').write(head + '\n'.join(ev) + '\n')
    return len(ev)


# ------------------------------------------------------------------------------------------------ render
class Clip:
    def __init__(self, path, LK):
        self.cap = cv2.VideoCapture(path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 24
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.LK = LK
        self.cache = {}

    def frame(self, t):
        i = max(0, min(self.n - 1, int(round(t * self.fps))))
        if i in self.cache:
            return self.cache[i]
        if getattr(self, 'pos', None) != i:          # seek only when not reading straight on
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = self.cap.read()
        self.pos = i + 1 if ok else None
        if not ok:
            return self.cache.get(max(self.cache) if self.cache else -1)
        h, w = fr.shape[:2]
        s = max(SW / w, SH / h)
        fr = cv2.resize(fr, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_LINEAR)
        y0, x0 = (fr.shape[0] - SH) // 2, (fr.shape[1] - SW) // 2
        fr = grade(fr[y0:y0 + SH, x0:x0 + SW], self.LK)
        if len(self.cache) > 6:
            self.cache.pop(next(iter(self.cache)))
        self.cache[i] = fr
        return fr

    def close(self):
        self.cap.release(); self.cache.clear()


def _frames(edit, LK, f0, f1, seed, log_every=0, tag=''):
    """Yield (frame index, BGR frame) for output frames f0..f1-1. Starts one frame early (not yielded) so a whip at a
    chunk boundary still has its previous frame."""
    grain = Grain(LK.get('grain', 8), seed + f0)
    stills, clips = {}, {}
    ci = 0
    prev_frame = None
    for fi in range(max(0, f0 - 1), f1):
        t = fi / FPS
        while ci + 1 < len(edit) and t >= edit[ci + 1]['t0']:
            ci += 1
        c = edit[ci]
        d = max(c['t1'] - c['t0'], 1 / FPS)
        lt = t - c['t0']
        p = min(max(lt / d, 0), 1)
        k = 1.0 if c['seg_kind'] in ('chorus', 'drop', 'hook') else 0.75
        if c['kind'] == 'video':
            if c['src'] not in clips:
                if len(clips) > 2:
                    clips.pop(next(iter(clips))).close()
                clips[c['src']] = Clip(c['src'], LK)
            src = clips[c['src']].frame(c.get('win0', 0) + lt)
            s, dx, dy, rot = (1.0 + 0.05 * ease_out(p)) * (1.25 if c.get('cut_in') else 1.0), 0, 0, 0
        else:
            if c['src'] not in stills:
                if len(stills) > 8:
                    stills.pop(next(iter(stills)))
                stills[c['src']] = prep_still(c['src'], LK)
            src = stills[c['src']]
            s, dx, dy, rot = move_params(c.get('move', 'push_in'), p, k, c.get('cut_in'))
        if src is None:
            frame = np.zeros((H, W, 3), np.uint8)
        else:
            amp = (0.010 if c.get('move') == 'shake' else 0.0035 if k < 1 else 0.006)
            if LK.get('handheld') and c['kind'] != 'video':           # slopcore filler stills: real handheld + push
                amp = max(amp, 0.009); s *= 1 + 0.06 * p
            dx += noise(t, ci, amp); dy += noise(t + 3.3, ci + 99, amp)
            rot += noise(t + 7.7, ci + 7, 0.5 if c.get('move') == 'shake' else 0.15)
            if c['seg_kind'] in ('chorus', 'drop') and lt < 0.12:          # impact punch on the cut
                s *= 1 + 0.05 * (1 - lt / 0.12)
            cx, cy = c.get('anchor', (0.5, 0.5))
            frame = warp(src, s, dx, dy, rot, cx, cy)
        if c.get('whip') and lt < 2 / FPS and prev_frame is not None:  # whip: directional smear between shots
            ksz = 61
            kern = np.zeros((1, ksz), np.float32); kern[0, :] = 1.0 / ksz
            frame = cv2.filter2D(cv2.addWeighted(prev_frame, 0.5, frame, 0.5, 0), -1, kern)
        if c.get('leak'):
            frame = leak(frame, LK['leak'], p, ci)
        if c.get('flash') and lt < 3 / FPS:
            a = 1 - lt / (3 / FPS)
            frame = cv2.addWeighted(frame, 1 - a * 0.9, np.full_like(frame, 255), a * 0.9, 0)
        if c['seg_kind'] == 'credits':
            frame = (cv2.GaussianBlur(frame, (0, 0), 18) * 0.35).astype(np.uint8)
        frame = grain.apply(frame)
        prev_frame = frame
        if fi >= f0:
            if log_every and (fi - f0) % log_every == 0:
                G.log(f"render{tag}: {fi - f0}/{f1 - f0} frames")
            yield fi, frame
    for cl in clips.values():
        cl.close()


def _render_part(edit, LK, f0, f1, seed, path, ass=None):
    """Worker: frames f0..f1-1, with the type burned in, as a delivery-quality H.264 part (no audio). Parts are later
    joined without re-encoding."""
    vf = f"setpts=PTS+{f0}/({FPS}*TB),ass={ass}:fontsdir=/usr/share/fonts,setpts=PTS-STARTPTS" if ass else 'null'
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-vf', vf, '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-maxrate', '12M', '-bufsize', '24M',
           '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-threads', '2', path]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for _, frame in _frames(edit, LK, f0, f1, seed):
            pr.stdin.write(frame.tobytes())
    finally:
        pr.stdin.close()
    rc = pr.wait()
    if rc != 0:
        raise RuntimeError(f'part render failed rc={rc}')
    return path


def _chunks(edit, nframes, n):
    """n contiguous frame ranges of about equal size, split at cut starts."""
    starts = sorted({int(round(e['t0'] * FPS)) for e in edit if 0 < e['t0'] * FPS < nframes})
    bounds = [0]
    for k in range(1, n):
        target = nframes * k / n
        b = min(starts, key=lambda x: abs(x - target)) if starts else int(target)
        if b > bounds[-1]:
            bounds.append(b)
    bounds.append(nframes)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def render(edit, LK, audio, ass, out, dur, seed=7, log_every=600, hard_deadline=None, workers=None):
    """edit: list of cuts {t0, t1, src, kind ('still'|'video'), move, cut_in, win0, seg_kind, flash, whip, leak}.
    Frames are rendered in parallel chunks (separate processes) to intermediates, then one final pass adds the type
    (ASS), the song and the delivery encode. Raises if hard_deadline (epoch s) passes."""
    import multiprocessing as mp
    nframes = int(round(dur * FPS))
    workers = workers or int(os.environ.get('CINE_REAL_WORKERS', 0) or max(1, min(4, (os.cpu_count() or 2) // 2)))
    tmp = os.path.splitext(out)[0] + '.parts'
    os.makedirs(tmp, exist_ok=True)
    chunks = _chunks(edit, nframes, workers)
    G.log(f"render: {nframes} frames in {len(chunks)} parallel parts")
    t0 = time.time()
    ctx = mp.get_context('fork')
    with ctx.Pool(len(chunks)) as pool:
        jobs = [pool.apply_async(_render_part, (edit, LK, a, b, seed, os.path.join(tmp, f'part{i:02d}.mp4'), ass))
                for i, (a, b) in enumerate(chunks)]
        while not all(j.ready() for j in jobs):
            if hard_deadline and time.time() > hard_deadline:
                pool.terminate()
                raise RuntimeError('render over the hard time budget (frame parts)')
            time.sleep(2)
        parts = [j.get() for j in jobs]          # re-raises a worker error
    G.log(f"render: parts done in {time.time() - t0:.0f}s; joining with the song")
    lst = os.path.join(tmp, 'parts.txt')
    open(lst, 'w').write(''.join(f"file '{p}'\n" for p in parts))
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio, '-map', '0:v', '-map', '1:a',
           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{dur:.3f}', '-movflags', '+faststart', out]
    left = (hard_deadline - time.time()) if hard_deadline else None
    if left is not None and left < 30:
        raise RuntimeError('render over the hard time budget (before the join)')
    try:
        rc = subprocess.run(cmd, timeout=left).returncode
    except subprocess.TimeoutExpired:
        raise RuntimeError('render over the hard time budget (join)')
    if rc != 0:
        raise RuntimeError(f'ffmpeg join failed rc={rc}')
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    G.log(f"render: total {time.time() - t0:.0f}s")
