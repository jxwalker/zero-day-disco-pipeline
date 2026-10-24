"""Karaoke lyric layer v2 (20 Oct 2026): per-word ASS events laid out with the theme's font (PIL metrics), so the
highlight style can vary per video: pop, block, underline, bounce, reveal, neon, marker, wipe; positions lower-center,
lower-left, bottom-band. Colours come from the palette (design.theme)."""
from PIL import ImageFont
from design import ass_size as AZ


def _ts(x):
    x = max(0, x); return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"
def _esc(s): return s.replace('{', '(').replace('}', ')').replace('\\', '/')
def _c(rgb, a=0): r, g, b = rgb; return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


def build(path, L, W, H, dur, story, sync_ok, design, th, line_ok):
    v = H > W; st = design['lyric_style']; pos = design['lyric_pos']
    fam = th['display_name']; ffile = th['display']
    if design['type'] == 'pixel': fam, ffile = th['body_name'], th['body']
    fs = (84 if v else 72) * (0.8 if design['type'] == 'pixel' else 1.0)
    if fam in ('Anton', 'Bebas Neue'): fs *= 1.12
    pil = ImageFont.truetype(ffile, int(fs))
    sp = max(pil.getlength(' '), fs * 0.30)
    light = th['light']
    hot, dim, ink = th['a1'], th['ink'], th['ink']
    outline = th['bg'] if not light else th['panel']
    if pos == 'bottom-band':
        ybase = int(H * (0.80 if v else 0.86)); maxw = W * 0.85; align = 'c'
    elif pos == 'lower-left':
        ybase = int(H * (0.76 if v else 0.82)); maxw = W * (0.84 if v else 0.6); align = 'l'
    else:
        ybase = int(H * (0.755 if v else 0.82)); maxw = W * 0.85; align = 'c'
    x_left = int(W * 0.075); cm = int(W * 0.075)   # safe area: >= 6% sides incl. borders/boxes
    bord = 6 if st not in ('neon',) else 3
    # 21 Oct (narrative rebuild): not-yet-sung words were unreadable over dark photos; give them a solid dark outline + shadow
    dark_ol = tuple(int(c * 0.25) for c in (th['bg'] if not light else (0, 0, 0)))
    if st == 'pop':   # 21 Oct: the 'pop' overshoot scales words past the side margins; leave room for it
        maxw *= 0.88; x_left += int(W * 0.03)
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dim,{fam},{AZ(fam, fs)},{_c(dim, 0x38 if st != 'neon' else 0x48)},{_c(dim)},{_c(dark_ol, 0x00)},{_c((0, 0, 0), 0x40)},0,0,0,0,100,100,0,0,1,{max(bord, 6)},3,5,0,0,0,1
Style: Hot,{fam},{AZ(fam, fs)},{_c(hot if st not in ('block', 'neon', 'marker') else ink)},{_c(hot)},{_c(outline if st != 'neon' else hot)},{_c((0, 0, 0), 0x80)},0,0,0,0,100,100,0,0,1,{bord},2,5,0,0,0,1
Style: Box,{fam},{AZ(fam, fs)},{_c(th['panel'] if not light else th['bg'])},{_c(hot)},{_c(hot)},{_c(hot)},0,0,0,0,100,100,0,0,3,10,0,5,0,0,0,1
Style: Shape,{fam},20,{_c(hot)},{_c(hot)},{_c(hot)},{_c(hot)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Next,{fam},{AZ(fam, fs * 0.6)},{_c(ink, 0x60)},{_c(ink, 0x60)},{_c(outline, 0x60)},{_c((0, 0, 0), 0xB0)},0,0,0,0,100,100,0,0,1,4,0,5,0,0,0,1
Style: Kick,{th['mono_name']},{AZ(th['mono_name'], 30 if v else 24)},{_c(th['panel'] if not light else th['bg'])},{_c(th['a2'])},{_c(th['a2'])},{_c(th['a2'])},0,0,0,0,100,100,1,0,3,8,0,7,{cm},{cm},40,1
Style: Chip,{th['body_name']},{AZ(th['body_name'], 40 if v else 32)},{_c(ink)},{_c(ink)},{_c(th['bg'] if not light else th['panel'])},{_c(th['bg'] if not light else th['panel'], 0x30)},0,0,0,0,100,100,0,0,3,10,0,7,{cm},{cm},40,1
Style: Band,{fam},20,{_c(th['panel'] if light else th['bg'], 0x30)},{_c(hot)},{_c(hot)},{_c(hot)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if pos == 'bottom-band':
        y0, y1 = int(H * (0.62 if v else 0.74)), int(H * (0.85 if v else 0.95))
        ev.append(f"Dialogue: 0,{_ts(0)},{_ts(dur)},Band,,0,0,0,,{{\\pos(0,{y0})\\p1}}m 0 0 l {W} 0 {W} {y1 - y0} 0 {y1 - y0}{{\\p0}}")
    T = [ln for ln in L if ln.get('words') or ln.get('start') is not None]
    # 24 Oct house style: chorus drops get the Glitch Tape VHS on-screen-display treatment (VT323, cyan + magenta split)
    osd = bool(design.get('house'))
    if osd:
        import design as DZ
        ct = DZ.chorus_theme(design); ofam, offile = ct['body_name'], ct['body']; ofs = (96 if v else 80)
        opil = ImageFont.truetype(offile, int(ofs)); osp = max(opil.getlength(' '), ofs * 0.30)
        hdr = hdr.replace('[Events]', f"Style: Osd,{ofam},{AZ(ofam, ofs)},{_c(ct['a1'])},{_c(ct['a1'])},{_c((0, 0, 0))},{_c((0, 0, 0), 0x60)},0,0,0,0,100,100,2,0,1,3,2,5,0,0,0,1\nStyle: OsdM,{ofam},{AZ(ofam, ofs)},{_c(ct['a2'], 0x30)},{_c(ct['a2'])},{_c(ct['a2'], 0xFF)},{_c((0, 0, 0), 0xFF)},0,0,0,0,100,100,2,0,1,0,0,5,0,0,0,1\nStyle: OsdDim,{ofam},{AZ(ofam, ofs)},{_c((240, 244, 250), 0x50)},{_c((240, 244, 250))},{_c((0, 0, 0))},{_c((0, 0, 0), 0x60)},0,0,0,0,100,100,2,0,1,3,2,5,0,0,0,1\n[Events]")
    pend = 0.0; nll = 0
    for i, s in enumerate(T):
        st0 = s['start']; nx = T[i + 1]['start'] if i + 1 < len(T) else dur
        end = min(s['end'] + 0.8, nx - 0.05) if nx - s['end'] < 2.5 else s['end'] + 0.8
        end = min(end, nx - 0.02, dur); a = min(st0, max(st0 - 0.3, pend + 0.01)); pend = end
        words = s.get('words') or []
        good = sync_ok and line_ok(s) and s.get('sync_score', 1) >= 0.45
        if not good:
            nll += 1
            n = max(1, len(s['text'].split())); step = (s['end'] - st0) / n
            words = [[w, st0 + k * step, st0 + (k + 1) * step - 0.02] for k, w in enumerate(s['text'].split())]
        toks = [_esc(w[0]) for w in words]
        isc = osd and s.get('kind') == 'chorus'
        if isc: toks = [t.upper() for t in toks]
        wid = [(opil if isc else pil).getlength(t) for t in toks]
        sp_l, fs_l = (osp, ofs) if isc else (sp, fs)
        # wrap into <= 2 rows, balanced
        tot = sum(wid) + sp_l * (len(wid) - 1); rows = [list(range(len(toks)))]
        if tot > maxw and len(toks) > 1:
            best = None
            for k in range(1, len(toks)):
                l1 = sum(wid[:k]) + sp_l * (k - 1); l2 = sum(wid[k:]) + sp_l * (len(wid) - k - 1)
                sc = max(l1, l2)
                if best is None or sc < best[0]: best = (sc, k)
            rows = [list(range(best[1])), list(range(best[1], len(toks)))]
        # auto-shrink: any row still wider than the safe width (measured) scales the whole line down
        rmax = max(sum(wid[j] for j in idx) + sp_l * (len(idx) - 1) for idx in rows)
        k = min(1.0, maxw / rmax) if rmax else 1.0
        wid = [w_ * k for w_ in wid]; spk = sp_l * k
        SC = f"\\fscx{100 * k:.0f}\\fscy{100 * k:.0f}" if k < 0.999 else ''
        lh = fs_l * 1.08 * k; xy = {}
        for r, idx in enumerate(rows):
            rw = sum(wid[j] for j in idx) + spk * (len(idx) - 1)
            x = (W - rw) / 2 if align == 'c' else x_left
            yy = ybase - (len(rows) - 1 - r) * lh
            for j in idx: xy[j] = (x + wid[j] / 2, yy); x += wid[j] + spk
        inpar = False
        for j, w in enumerate(words):
            x, y = xy[j]; ws, we = w[1], max(w[2], w[1] + 0.12)
            nws = words[j + 1][1] if j + 1 < len(words) else we
            tok = toks[j]
            if '(' in tok: inpar = True
            ad = (f"\\i1\\fscx{85 * k:.0f}\\fscy{85 * k:.0f}" + f"\\1c{_c(th['a2'])}") if inpar else SC
            if ')' in tok: inpar = False
            P = f"\\an5\\pos({x:.0f},{y:.0f})"
            if isc:   # VHS OSD: dim until sung, then cyan with a magenta ghost offset (RGB split) that jitters in
                ev.append(f"Dialogue: 1,{_ts(a)},{_ts(ws)},OsdDim,,0,0,0,,{{{P}\\fad(60,0){SC}}}{tok}")
                ev.append(f"Dialogue: 1,{_ts(ws)},{_ts(end)},OsdM,,0,0,0,,{{\\an5\\move({x + 14:.0f},{y:.0f},{x + 5:.0f},{y:.0f},0,120){SC}}}{tok}")
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Osd,,0,0,0,,{{{P}{SC}}}{tok}")
                continue
            if st != 'reveal':
                ev.append(f"Dialogue: 1,{_ts(a)},{_ts(ws)},Dim,,0,0,0,,{{{P}\\fad(80,0){ad}}}{tok}")
            if st == 'pop':
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{{P}\\fscx{118 * k:.0f}\\fscy{118 * k:.0f}\\t(0,170,\\fscx{100 * k:.0f}\\fscy{100 * k:.0f}){ad if inpar else ''}}}{tok}")
            elif st == 'block':
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(we)},Box,,0,0,0,,{{{P}{ad}}}{tok}")
                ev.append(f"Dialogue: 2,{_ts(we)},{_ts(end)},Hot,,0,0,0,,{{{P}\\1c{_c(hot)}{ad}}}{tok}")
            elif st == 'reveal':
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{\\an5\\move({x:.0f},{y + 40:.0f},{x:.0f},{y:.0f},0,160)\\fad(120,0){ad}}}{tok}")
            elif st == 'neon':
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{{P}\\blur5\\1c{_c((255, 255, 255))}\\t(0,90,\\alpha&H60&)\\t(90,180,\\alpha&H00&){ad}}}{tok}")
            elif st == 'marker':
                x0, y0b = x - wid[j] / 2 - 8, y - fs * 0.32; hgt = fs * 0.62; wd = wid[j] + 16
                ev.append(f"Dialogue: 1,{_ts(ws)},{_ts(end)},Shape,,0,0,0,,{{\\an7\\pos({x0:.0f},{y0b:.0f})\\1c{_c(th['a3'])}\\clip(0,0,{int(x0)},{H})\\t(0,{max(60, int((we - ws) * 1000))},\\clip(0,0,{int(x0 + wd)},{H}))\\p1}}m 0 0 l {wd:.0f} 0 {wd:.0f} {hgt:.0f} 0 {hgt:.0f}{{\\p0}}")
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{{P}{ad}}}{tok}")
            elif st == 'wipe':
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{{P}\\clip({int(x - wid[j] / 2)},0,{int(x - wid[j] / 2)},{H})\\t(0,{max(60, int((we - ws) * 1000))},\\clip({int(x - wid[j] / 2)},0,{int(x + wid[j] / 2 + 4)},{H})){ad}}}{tok}")
                ev.append(f"Dialogue: 1,{_ts(ws)},{_ts(end)},Dim,,0,0,0,,{{{P}{ad}}}{tok}")
            else:   # underline / bounce: plain colour + a moving marker
                ev.append(f"Dialogue: 2,{_ts(ws)},{_ts(end)},Hot,,0,0,0,,{{{P}{ad}}}{tok}")
            if st == 'underline':
                ww = wid[j]; px = xy[j - 1][0] - wid[j - 1] / 2 if j and xy[j - 1][1] == y else x - ww / 2
                ev.append(f"Dialogue: 3,{_ts(ws)},{_ts(max(nws, we))},Shape,,0,0,0,,{{\\an7\\move({px:.0f},{y + fs * 0.48:.0f},{x - ww / 2:.0f},{y + fs * 0.48:.0f},0,120)\\p1}}m 0 0 l {ww:.0f} 0 {ww:.0f} 10 0 10{{\\p0}}")
            if st == 'bounce':
                px, py = xy[j - 1] if j else (x, y)
                r = 16; t1 = max(0.1, nws - ws) if j + 1 < len(words) else 0.3
                mid = int(t1 * 500)
                yt = y - fs * 0.75
                ev.append(f"Dialogue: 3,{_ts(ws)},{_ts(ws + t1)},Shape,,0,0,0,,{{\\an7\\move({x - r:.0f},{yt - r - fs * 0.35:.0f},{x - r:.0f},{yt - r:.0f},0,{min(mid, 160)})\\1c{_c(th['a3'])}\\p1}}m {r} 0 b {r * 1.55:.0f} 0 {2 * r} {r * 0.45:.0f} {2 * r} {r} b {2 * r} {r * 1.55:.0f} {r * 1.55:.0f} {2 * r} {r} {2 * r} b {r * 0.45:.0f} {2 * r} 0 {r * 1.55:.0f} 0 {r} b 0 {r * 0.45:.0f} {r * 0.45:.0f} 0 {r} 0{{\\p0}}")
        if i + 1 < len(T) and T[i + 1]['start'] - end < 1.5:
            ny = (ybase + fs * 0.95) if pos != 'bottom-band' else (ybase - fs * 1.15 * len(rows))
            nxp = W / 2 if align == 'c' else x_left
            an = 5 if align == 'c' else 4
            if pos == 'bottom-band': ny = min(ny, ybase - fs * 1.05)
            nt = _esc(T[i + 1]['text']); nw_ = ImageFont.truetype(ffile, int(fs * 0.6)).getlength(nt)
            kn = min(1.0, maxw / nw_) if nw_ else 1.0
            ev.append(f"Dialogue: 0,{_ts(a)},{_ts(end)},Next,,0,0,0,,{{\\an{an}\\pos({nxp:.0f},{ny:.0f})\\fscx{100 * kn:.0f}\\fscy{100 * kn:.0f}\\fad(80,0)}}{nt}")
    for c in story:
        y = int(H * 0.068)   # kicker box border (8px) must stay inside the 5% top margin
        ev.append(f"Dialogue: 4,{_ts(c['t0'])},{_ts(c['t1'])},Kick,,0,0,0,,{{\\an7\\pos({cm},{y})\\fad(150,150)}}{_esc(c['kicker'].upper())}")
        ev.append(f"Dialogue: 4,{_ts(c['t0'])},{_ts(c['t1'])},Chip,,0,0,0,,{{\\an7\\pos({cm},{y + (62 if v else 50)})\\fad(150,150)\\q0}}{_esc(c['text'])}")
    open(path, 'w').write(hdr + '\n'.join(ev) + '\n')
    return nll
