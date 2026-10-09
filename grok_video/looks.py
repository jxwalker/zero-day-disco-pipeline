"""Genre looks for the Grok-clip music video. Every look shares the same high-production music-video recipe (named camera
moves, an outfit per section, choreography, beat-synced edit with flashes / slow-mo / whips, bold pop-up captions, a colour
grade); the look changes the world, the edit rhythm and the grade. `standard` is the original gig-style look (no recipe).
pick_look(day) maps style.txt (+ tags.json genre) to a look for `--look auto`."""
import os, re
import common_gv as G

LOOKS = {
    'pop-video': dict(
        label='glossy pop music video',
        direction="""LOOK: a slick, high-budget POP MUSIC VIDEO (a big-label pop star video).
- World: glossy, saturated, art-directed sets: neon tubes, chrome, mirrors and mirror floors, LED walls, candy-coloured
  studio cycloramas, glitter, smoke. Expensive lighting with coloured rim lights and light leaks.
- Performance: Pip performs choreographed dance moves (step-touch, body roll, shoulder pops, spins, power poses), often with
  2-4 BACKUP DANCERS dancing in sync behind Pip.
- Cameras: dolly-in, orbit around Pip, crane up/down, low-angle hero shot, handheld push, whip pan, slow-motion moment.
- Outfits per section (examples): star sunglasses, an open cropped leather jacket, an open glitter jacket, a sequinned
  cape, chunky headphones, a gold chain.
- Atmosphere: wind machines, confetti cannons, sparks, haze, light leaks, slow-motion confetti on big hits.""",
        crew='simple glossy silver/chrome robot backup dancers WITHOUT bunny ears or antenna',
        hero='ONE giant stadium-sized LED stage with a mirror floor',
        chorus_word='chorus',
        intro='a hero reveal (e.g. Pip rising on a platform, silhouette to light)',
        outro='the final power pose',
        scene_style='glossy, saturated, art-directed pop-music-video scene',
        lighting='Expensive music-video lighting (coloured rim light, haze, light leaks).',
        motion_tail='Big, clear dance motion on the beat, glossy pop music video.',
        default_camera='slow dolly-in',
        edit=dict(chorus_beats=[2, 2, 3, 4, 4, 5], verse_beats=[4, 4, 5, 6, 8], build=False, drop_fx=['flash'],
                  speedup=True, whip=(0.45, 0.15), punch=0.35, shake=0.0, fisheye=0.0, slowmo=4),
        grade=['eq=contrast=1.07:saturation=1.22:brightness=0.005', 'vignette=angle=PI/7'],
        caption=('ffd84d', 'ff5fb0')),
    'edm': dict(
        label='big-room festival mainstage',
        direction="""LOOK: a huge BIG-ROOM / EDM FESTIVAL music video at the mainstage at night.
- World: a festival mainstage at night: a giant LED wall stage, lasers fanning over the crowd, CO2 cannon blasts, pyro
  flames, streamers, a sea of festival crowd silhouettes with waving blank flags and hands up (no faces, no readable
  text), a catwalk into the crowd, the DJ booth.
- Performance: Pip is the DJ / hype MC: hands on the decks, fist pumps, jumping on the booth, conducting the crowd, running
  down the catwalk, hands-up moments, often with 2-4 hype dancers.
- The drop: every chorus is a DROP: confetti explosions, laser hits, CO2 blasts, pyro, the whole crowd jumping.
- Cameras: drone fly-over of the crowd towards the stage, crane over the crowd, low-angle hero shot at the decks, orbit
  around the DJ booth, tracking shot down the catwalk, slow-motion confetti on the drop.
- Outfits per section (examples): LED visor sunglasses, an open reflective festival jacket, glow bracelets, a bucket hat
  sitting between the ears, light-up gloves, headphones around the neck.
- Atmosphere: laser beams through haze, strobes, confetti, CO2 jets, sparks.""",
        crew='simple glossy chrome robot hype dancers WITHOUT bunny ears or antenna',
        hero='ONE giant festival mainstage at night with the DJ booth on a huge LED wall',
        chorus_word='drop / chorus',
        intro='the build-up: Pip walks up to the decks in silhouette against the LED wall, crowd waiting, lasers sweeping',
        outro='the final hands-up moment under a last confetti blast',
        scene_style='huge night-time festival-mainstage EDM music-video scene',
        lighting='Festival lighting: laser beams through haze, LED wall glow, coloured rim light, strobes.',
        motion_tail='Big festival energy on the beat, lasers and crowd moving, EDM music video.',
        default_camera='crane over the crowd',
        edit=dict(chorus_beats=[2, 2, 4, 4, 4], verse_beats=[4, 4, 6, 8], build=True, drop_fx=['flash', 'strobe'],
                  speedup=False, whip=(0.25, 0.1), punch=0.5, shake=0.0, fisheye=0.0, slowmo=3),
        grade=['eq=contrast=1.09:saturation=1.25', 'colorbalance=bs=0.03:bm=0.02', 'vignette=angle=PI/6'],
        caption=('5fe3ff', 'ffd84d')),
    'rock': dict(
        label='stadium rock show',
        direction="""LOOK: a STADIUM ROCK SHOW music video (an arena-rock band at its peak).
- World: a stadium rock stage: pyro columns, smoke, big backlights and spotlights, amp walls, a drum riser, a crowd sea of
  lighters and phone torches (silhouettes, no faces), gritty backlit silhouettes, rain or sparks.
- Performance: Pip is the rock star: guitar-hero poses, knee slides across the stage, a shredding solo on a riser, one foot
  on the monitor, windmill strums, crowd call-and-response, with a robot band behind (drummer, bassist).
- Cameras: low-angle hero shot from the stage floor, crane over the crowd, orbit around Pip on the riser, a dolly along the
  stage front, slow-motion knee slide, backlit silhouette shot.
- Outfits per section (examples): an open black leather jacket, studded wristbands, aviator sunglasses, a bandana, an open
  sleeveless denim vest.
- Atmosphere: pyro bursts, smoke, sparks, wind, light shafts through haze.""",
        crew='a simple glossy chrome robot band (drummer, bassist) WITHOUT bunny ears or antenna',
        hero='ONE stadium rock stage with pyro columns and a giant backlit lighting rig',
        chorus_word='chorus',
        intro='a backlit silhouette reveal: Pip walks out through smoke into the spotlight, guitar slung low',
        outro='the final power chord jump with pyro',
        scene_style='gritty, high-contrast stadium rock-show music-video scene',
        lighting='Rock-show lighting: hard backlights through smoke, warm spotlights, pyro glow, rim light.',
        motion_tail='Big rock-star performance motion on the beat, stadium rock music video.',
        default_camera='low-angle hero push-in',
        edit=dict(chorus_beats=[2, 3, 4, 4, 6], verse_beats=[4, 6, 6, 8], build=False, drop_fx=['flash'],
                  speedup=True, whip=(0.2, 0.08), punch=0.45, shake=0.25, fisheye=0.0, slowmo=4),
        grade=['colorbalance=rs=0.04:bs=-0.04:rm=0.05:bm=-0.05:rh=0.03:bh=-0.03',
               'eq=contrast=1.15:saturation=1.08:gamma=0.97', 'vignette=angle=PI/5'],
        caption=('ffb02e', 'ff5a36')),
    'punk': dict(
        label='pop-punk club / skatepark video',
        direction="""LOOK: a POP-PUNK music video: sweaty club gig into garage, skatepark and backyard party.
- World: a sweaty low-ceiling club stage, a garage band practice, a concrete skatepark with ramps and bowls, a backyard
  house party, string lights, tagged walls with NO readable text, pizza boxes, flying solo cups.
- Performance: Pip jumps off amps, stage dives, crowd-surfs over a mosh pit of small round white robots, skates a ramp,
  pogos, screams the chorus into a mic, guitar slung low, a gang-vocal huddle.
- Cameras: handheld shaky push-in, fisheye close-up, skate follow-cam, crowd-surf POV, low-angle from the floor, whip pan.
- Outfits per section (examples): an open flannel shirt, a backwards cap sitting between the ears, an open band-style
  hoodie with no text, checkerboard wristbands, a bandana.
- Atmosphere: sweat and haze, flying confetti, streamers, camera flash pops, golden-hour sun flares outside.""",
        crew='a mosh pit / band of small round white robots WITHOUT bunny ears or antenna',
        hero='ONE sweaty packed club stage with a mosh pit',
        chorus_word='chorus',
        intro='a garage-door reveal: the door rolls up on Pip and the band',
        outro='the final stage dive into the pit',
        scene_style='energetic, handheld pop-punk music-video scene',
        lighting='Club / DIY lighting: harsh stage spots, haze, camera-flash pops, warm golden-hour sun outside.',
        motion_tail='Wild jumping punk energy on the beat, handheld camera, pop-punk music video.',
        default_camera='handheld shaky push-in',
        edit=dict(chorus_beats=[2, 2, 3, 4], verse_beats=[3, 4, 4, 6], build=False, drop_fx=['flash'],
                  speedup=True, whip=(0.35, 0.15), punch=0.3, shake=0.6, fisheye=0.22, slowmo=3),
        grade=['eq=contrast=0.94:saturation=0.86:brightness=0.02', "curves=all='0/0.07 0.5/0.52 1/0.95'",
               'noise=alls=6:allf=t', 'vignette=angle=PI/6'],
        caption=('ffd84d', 'b6ff4d')),
}
LOOK_ALIASES = {'pop': 'pop-video', 'bigroom': 'edm', 'big-room': 'edm', 'festival': 'edm', 'pop-punk': 'punk'}
CHOICES = ['auto', 'standard', 'pop-video', 'pop', 'edm', 'rock', 'punk']

_KW = {
    'edm': [('big-room', 3), ('big room', 3), ('edm', 3), ('festival', 2), ('drops', 2), ('drop', 1), ('build-up', 1),
            ('house', 2), ('techno', 3), ('trance', 3), ('dubstep', 3), ('drum and bass', 3), ('dnb', 3), ('rave', 2),
            ('dance-floor', 2), ('dance floor', 2), ('hardstyle', 3), ('supersaw', 2), ('uk garage', 3), ('2-step', 2),
            ('four-on-the-floor', 0.5), ('electro', 0.5)],
    'punk': [('pop-punk', 4), ('pop punk', 4), ('punk', 3), ('emo', 2), ('skate', 2), ('hardcore', 2), ('palm-muted', 1.5),
             ('ska', 1), ('gang-vocal', 1)],
    'rock': [('arena rock', 4), ('stadium', 2), ('rock', 2.5), ('metal', 3), ('grunge', 3), ('distorted', 1.5),
             ('guitar riff', 1.5), ('riffs', 1), ('shoegaze', 2), ('power ballad', 2), ('garage rock', 2)],
    'pop-video': [('synth-pop', 3), ('k-pop', 3), ('pop', 2), ('disco', 3), ('funk', 2), ('r&b', 2), ('soul', 1.5),
                  ('hip hop', 2), ('hip-hop', 2), ('rap', 1.5), ('ballad', 1), ('dance-pop', 3)],
}


def pick_look(day):
    """(look, reason) from tags.json genre + style.txt. The first comma-separated style phrase (the main genre) weighs 3x."""
    genre, style = G.genre_of(day)
    text = f"{genre}, {style}".lower() if genre else (style or '').lower()
    if not text.strip(', '):
        return 'pop-video', 'no style.txt/genre: default pop-video'
    head = re.split(r'[,;\n]', text.strip(', '))[0]
    scores = {}
    for look, kws in _KW.items():
        s = 0.0
        for k, w in kws:
            for part, mult in ((head, 3.0), (text, 1.0)):
                t = part
                if k == 'pop':     # 'pop' inside pop-punk / electro-pop is not a pop vote
                    t = t.replace('pop-punk', '').replace('pop punk', '')
                if k == 'punk':
                    t = t.replace('pop-punk', '').replace('pop punk', '')
                if k == 'rock':
                    t = t.replace('garage rock', '')
                if k == 'drop':
                    t = t.replace('drops', '')
                if k == 'rap':
                    t = re.sub(r'\brap\b', ' rap ', t) if re.search(r'\brap\b', t) else ''
                if k in t:
                    s += w * mult
        scores[look] = s
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return 'pop-video', f"no genre keywords in {head!r}: nearest look pop-video"
    top = sorted(scores.items(), key=lambda kv: -kv[1])
    return best, f"main genre {head!r} -> {best} (scores " + ', '.join(f"{k} {v:g}" for k, v in top if v) + ')'


def resolve(day, look):
    look = LOOK_ALIASES.get(look, look)
    if look == 'auto':
        return pick_look(day)
    return look, 'set on the command line'
