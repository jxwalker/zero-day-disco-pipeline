"""Per-video art direction for karaoke mode.
Opus picks one option per axis from these menus, derived from the song's genre/mood and the stories; Python enforces
variety against the recent days (karaoke_design_history.json) and never defaults to the stock IT-ops look
(green-on-black terminal/NOC, Poppins Black colour wipe)."""
import hashlib, json, os, time
FD = '/usr/share/fonts/truetype/sand-box/google/'
HIST = '/home/box/suno-daily/karaoke_design_history.json'

PALETTES = {   # bg, panel, ink, muted, a1, a2, a3, good, bad
    'risograph':   dict(bg=(244, 238, 224), panel=(255, 251, 242), ink=(28, 30, 60), muted=(120, 116, 130), a1=(236, 70, 90), a2=(40, 90, 200), a3=(250, 180, 40), good=(20, 150, 110), bad=(225, 50, 70)),
    'newsprint':   dict(bg=(236, 233, 226), panel=(250, 249, 245), ink=(18, 18, 18), muted=(110, 110, 110), a1=(210, 30, 40), a2=(18, 18, 18), a3=(240, 200, 0), good=(30, 120, 60), bad=(210, 30, 40)),
    'sunset-pop':  dict(bg=(42, 16, 70), panel=(70, 28, 110), ink=(255, 244, 236), muted=(200, 160, 210), a1=(255, 120, 60), a2=(255, 70, 160), a3=(255, 210, 80), good=(90, 230, 190), bad=(255, 80, 90)),
    'candy':       dict(bg=(255, 228, 236), panel=(255, 255, 255), ink=(60, 30, 80), muted=(160, 120, 160), a1=(255, 90, 150), a2=(110, 120, 255), a3=(40, 200, 200), good=(40, 180, 120), bad=(240, 60, 90)),
    'teal-coral':  dict(bg=(12, 56, 64), panel=(20, 80, 90), ink=(240, 250, 248), muted=(140, 190, 190), a1=(255, 120, 100), a2=(255, 214, 120), a3=(120, 230, 220), good=(140, 240, 170), bad=(255, 100, 100)),
    'noir-yellow': dict(bg=(20, 20, 22), panel=(38, 38, 42), ink=(245, 245, 240), muted=(140, 140, 140), a1=(255, 214, 0), a2=(255, 255, 255), a3=(255, 140, 0), good=(255, 214, 0), bad=(255, 70, 60)),
    'cobalt-cream':dict(bg=(24, 44, 140), panel=(36, 60, 170), ink=(250, 244, 226), muted=(170, 180, 230), a1=(255, 196, 70), a2=(255, 110, 90), a3=(150, 220, 255), good=(150, 240, 160), bad=(255, 110, 90)),
    'y2k-chrome':  dict(bg=(210, 220, 235), panel=(240, 244, 252), ink=(20, 30, 70), muted=(110, 120, 150), a1=(0, 120, 255), a2=(255, 60, 200), a3=(0, 200, 160), good=(0, 170, 110), bad=(255, 50, 90)),
    'neon-chrome': dict(bg=(8, 8, 14), panel=(28, 30, 40), ink=(240, 244, 250), muted=(160, 170, 190), a1=(255, 40, 170), a2=(0, 230, 255), a3=(200, 210, 225), good=(0, 230, 255), bad=(255, 40, 170)),   # hot pink, electric cyan, chrome on black
    # house style: Acid Deadpan = Klein blue / acid green / safety orange; Glitch Tape = magenta/cyan on black (chorus drops)
    'acid-deadpan': dict(bg=(0, 47, 167), panel=(0, 32, 120), ink=(250, 250, 244), muted=(150, 170, 220), a1=(255, 103, 0), a2=(176, 255, 0), a3=(255, 103, 0), good=(176, 255, 0), bad=(255, 103, 0)),
    'glitch-tape': dict(bg=(8, 6, 14), panel=(26, 20, 40), ink=(240, 244, 250), muted=(150, 150, 180), a1=(0, 240, 255), a2=(255, 40, 200), a3=(255, 255, 255), good=(0, 240, 255), bad=(255, 40, 200)),
    'forest-mustard': dict(bg=(26, 48, 36), panel=(38, 66, 50), ink=(244, 236, 214), muted=(160, 180, 150), a1=(232, 180, 60), a2=(230, 110, 70), a3=(170, 220, 160), good=(200, 230, 120), bad=(240, 100, 80)),
}
TYPE = {   # display, body (bold), mono  -> (ASS family name, file)
    'poster':    dict(display=('Anton', 'Anton/Anton-Regular.ttf'), body=('Barlow Condensed', 'Barlow Condensed/BarlowCondensed-Bold.ttf'), mono=('DM Mono', 'DM Mono/DMMono-Medium.ttf')),
    'retro':     dict(display=('Bungee', 'Bungee/Bungee-Regular.ttf'), body=('Righteous', 'Righteous/Righteous-Regular.ttf'), mono=('Space Mono', 'Space Mono/SpaceMono-Bold.ttf')),
    'editorial': dict(display=('DM Serif Display', 'DM Serif Display/DMSerifDisplay-Regular.ttf'), body=('Archivo Black', 'Archivo Black/ArchivoBlack-Regular.ttf'), mono=('Courier Prime', 'Courier Prime/CourierPrime-Bold.ttf')),
    'marker':    dict(display=('Permanent Marker', 'Permanent Marker/PermanentMarker-Regular.ttf'), body=('Caveat Brush', 'Caveat Brush/CaveatBrush-Regular.ttf'), mono=('Courier Prime', 'Courier Prime/CourierPrime-Bold.ttf')),
    'slab':      dict(display=('Alfa Slab One', 'Alfa Slab One/AlfaSlabOne-Regular.ttf'), body=('Barlow Condensed', 'Barlow Condensed/BarlowCondensed-ExtraBold.ttf'), mono=('DM Mono', 'DM Mono/DMMono-Medium.ttf')),
    'pixel':     dict(display=('Press Start 2P', 'Press Start 2P/PressStart2P-Regular.ttf'), body=('VT323', 'VT323/VT323-Regular.ttf'), mono=('VT323', 'VT323/VT323-Regular.ttf')),
    'condensed': dict(display=('Bebas Neue', 'Bebas Neue/BebasNeue-Regular.ttf'), body=('Barlow Condensed', 'Barlow Condensed/BarlowCondensed-Bold.ttf'), mono=('Space Mono', 'Space Mono/SpaceMono-Bold.ttf')),
    'groovy':    dict(display=('Shrikhand', 'Shrikhand/Shrikhand-Regular.ttf'), body=('Righteous', 'Righteous/Righteous-Regular.ttf'), mono=('Space Mono', 'Space Mono/SpaceMono-Bold.ttf')),
}
LYRIC = ['pop', 'block', 'underline', 'bounce', 'reveal', 'neon', 'marker', 'wipe']
LYRIC_POS = ['lower-center', 'lower-left', 'bottom-band']
TRANS = ['cut', 'flash', 'dip', 'punch', 'slide', 'glitch']
GRADE = {'warm-film': "eq=contrast=1.06:saturation=1.08:gamma_r=1.04:gamma_b=0.95,noise=alls=7:allf=t",
         'cool-clean': "eq=contrast=1.05:saturation=0.95:gamma_b=1.05:gamma_r=0.97",
         'faded-pastel': "eq=contrast=0.9:saturation=0.85:brightness=0.04,noise=alls=5:allf=t",
         'punchy': "eq=contrast=1.15:saturation=1.25",
         'bleach': "eq=contrast=1.18:saturation=0.6",
         'cross-process': "eq=contrast=1.08:saturation=1.15:gamma_g=1.06:gamma_b=0.9,noise=alls=6:allf=t"}
TEXTURE = ['none', 'grain', 'halftone', 'paper']   # 'grid' dropped (line pattern)   # 'scanlines' removed
AXES = dict(palette=list(PALETTES), type=list(TYPE), lyric_style=LYRIC, lyric_pos=LYRIC_POS, transition=TRANS,
            grade=list(GRADE), texture=TEXTURE)


def menu_text():
    return '\n'.join(f"- {k}: {', '.join(v)}" for k, v in AXES.items())


def history(n=7):
    try:
        return json.load(open(HIST))[-n:]
    except Exception:
        return []


def resolve(day, want, force_palette=''):
    """Validate Opus's choice; enforce difference from the previous day on the main axes; fill gaps by hash."""
    prev = [h for h in history() if h.get('day') != os.path.basename(day)]
    last = prev[-1] if prev else {}
    recent = prev[-3:]
    d = {}
    seed = int(hashlib.md5(os.path.basename(day).encode()).hexdigest(), 16)
    for i, (k, opts) in enumerate(AXES.items()):
        v = (want or {}).get(k)
        if v not in opts:
            v = opts[(seed >> (i * 4)) % len(opts)]
        banned = {last.get(k)} if k in ('palette', 'type', 'lyric_style', 'transition') else set()
        if k in ('palette', 'type', 'lyric_style'):
            banned |= {h.get(k) for h in recent}
        if v in banned:
            free = [o for o in opts if o not in banned] or opts
            v = free[(seed >> (i * 3)) % len(free)]
        d[k] = v
    if d['lyric_style'] == 'wipe' and d['lyric_pos'] == 'lower-center':
        d['lyric_pos'] = 'lower-left'                 # never the stock lyric treatment
    if d['type'] == 'pixel' and d['lyric_style'] == 'marker':
        d['lyric_style'] = 'pop'
    if force_palette in PALETTES: d['palette'] = force_palette
    if sum(PALETTES[d['palette']]['bg']) > 500 and d['lyric_style'] in ('neon', 'reveal', 'underline'):
        d['lyric_style'] = 'block'   # pale neon lyrics were unreadable on a light (candy) palette     # day direction.txt can force the palette
    d['why'] = (want or {}).get('why', '')
    return house(day, d)


def record(day, d, templates):
    h = []
    try:
        h = json.load(open(HIST))
    except Exception:
        pass
    h = [x for x in h if x.get('day') != os.path.basename(day)]
    h.append(dict(d, day=os.path.basename(day), templates=templates, at=time.strftime('%Y-%m-%d %H:%M')))
    json.dump(h[-60:], open(HIST, 'w'), indent=1)


# house style: every day is Acid Deadpan (verses/pre/breakdown) with Glitch Tape on chorus drops. Variation is
# WITHIN the house style (type, lyric position, grade, texture rotate); palette and lyric treatment are fixed.
# GV_HOUSESTYLE=0 restores the old free menu.
HOUSE = os.environ.get('GV_HOUSESTYLE', '1') != '0'
HOUSE_AXES = dict(type=['poster', 'condensed', 'slab'], lyric_pos=['lower-center', 'bottom-band'],
                  grade=['punchy', 'cool-clean', 'bleach'], texture=['grain', 'none', 'grain'])


def house(day, d):
    if not HOUSE: return d
    seed = int(hashlib.md5(os.path.basename(day).encode()).hexdigest(), 16)
    prev = [h for h in history() if h.get('day') != os.path.basename(day)]
    last = prev[-1] if prev else {}
    d = dict(d, palette='acid-deadpan', lyric_style='block', transition='cut', house='acid-deadpan', chorus='glitch-tape')
    for i, (k, opts) in enumerate(HOUSE_AXES.items()):
        if d.get(k) not in opts: d[k] = opts[(seed >> (i * 5)) % len(opts)]
        if k == 'type' and d[k] == last.get('type'):
            d[k] = [o for o in opts if o != d[k]][seed % (len(opts) - 1)]
    return d


def chorus_theme(d):
    """Glitch Tape theme for chorus-drop text (VHS OSD: VT323 mono, cyan with magenta RGB split)."""
    p = theme(dict(d, palette='glitch-tape', type='pixel'))
    return p


def theme(d):
    p = dict(PALETTES[d['palette']]); t = TYPE[d['type']]
    p.update({f: FD + t[f][1] for f in ('display', 'body', 'mono')})
    p.update({f + '_name': t[f][0] for f in ('display', 'body', 'mono')})
    p['light'] = sum(p['bg']) > 450
    p['texture'] = d.get('texture', 'none')
    return p

# libass renders a family at (ASS Fontsize x ratio) of PIL's em size (measured on the box); the ASS size
# for a wanted PIL em E is E / ratio, so per-word layout measured with PIL matches what libass draws.
ASS_SCALE = {'Anton': 0.573, 'Barlow Condensed': 0.689, 'DM Mono': 0.758, 'Bungee': 0.382, 'Righteous': 0.8,
             'Space Mono': 0.664, 'DM Serif Display': 0.737, 'Archivo Black': 0.735, 'Courier Prime': 0.745,
             'Permanent Marker': 0.697, 'Caveat Brush': 0.776, 'Alfa Slab One': 0.639, 'Press Start 2P': 0.719,
             'VT323': 0.768, 'Bebas Neue': 0.758, 'Shrikhand': 0.683}
def ass_size(fam, em): return int(round(em / ASS_SCALE.get(fam, 0.75)))
