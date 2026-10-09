"""Shot planning (one cheap headless grok text call) and clip generation (image_edit -> image_to_video, concurrent
headless grok runs). Uses the signed-in Grok subscription; never an API key."""
import json, os, re, random, subprocess, threading, time, shutil
from concurrent.futures import ThreadPoolExecutor
import common_gv as G
from looks import LOOKS
import cine

PLANNER_VERSION = 'cine-4'
SECTIONS = ['intro', 'verse', 'chorus', 'bridge', 'outro']
SCHEMA = {
    "type": "object",
    "properties": {"shots": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "story": {"type": "integer", "description": "1-based story number, or 0 for chorus / intro / outro moments"},
        "section": {"type": "string", "enum": SECTIONS},
        "setting": {"type": "string", "description": "short unique location name"},
        "props": {"type": "string", "description": "the main props, unique to this shot"},
        "scene": {"type": "string", "description": "the still: what Pip is doing where, composition, lighting"},
        "motion": {"type": "string", "description": "the 10 s animation: explicit movement from where to where"},
        "outfit": {"type": "string", "description": "genre looks: Pip's styling for this shot (or 'none')"},
        "camera": {"type": "string", "description": "genre looks: the named camera move"}},
        "required": ["id", "story", "section", "setting", "props", "scene", "motion"]}}},
    "required": ["shots"]}


def plan_prompt(day, n):
    genre, style = G.genre_of(day)
    fam = G.genre_family(genre, style)
    stories = G.story_list(day)
    lyr = G.read(os.path.join(day, 'lyrics.txt'))
    title = G.read(os.path.join(day, 'title.txt')) or (G.load_json(os.path.join(day, 'tags.json'), {}) or {}).get('title', '')
    st = '\n'.join(f"{s['idx']}. {s['text']} (lyrics: {s['section']} lines {s['lines']}) :: {s['detail']}" for s in stories)
    k = len(stories)
    n_ch = max(2, round(n / 4))
    fam_words = {'rock': 'mosh pits, stage dives, arenas, amps', 'pop': 'glossy sets, choreography, confetti',
                 'bigroom': 'festival stages, lasers, drops, hands up'}.get(fam, 'stages and crowds')
    return f"""Plan a shot list for a vertical 9:16 AI music video of today's AI-news song "{title}".
Genre: {genre or '?'} / style: {style}
Visual direction for this genre: {G.GENRE_RULES[fam]}

The star of EVERY shot is our mascot Pip: {G.PIP_DESC}
Each shot will be made by restaging Pip from a reference image into ONE still (image edit), then animating that still
for 10 seconds (image-to-video). So each shot is a single continuous camera setup, Pip large and fully in frame
head-to-feet, with clear, visible motion.

Stories (numbered):
{st}

Lyrics:
{lyr}

Write exactly {n} shots:
- Every story gets at least one shot (story = its number); give the stories with more lyric lines a second shot if the
  count allows. About {n_ch} shots are chorus moments (story 0, section "chorus") built on the hook / title. One shot is
  an intro shot (story 0, section "intro"). Order the shots roughly in song order.
- EVERY shot is a music-video performance moment in this genre (see the visual direction: instruments, stage, crowd,
  {fam_words}); Pip performs. Story shots tell THAT story through the set dressing and props around the performance
  (numbers as physical objects, companies as abstract stand-ins), never real people, logos, brand marks or readable text.
- No repeated settings and no repeated main props across the {n} shots; vary camera angle and time of day.
- Pip is the performer; any guitar must be slung LOW at the hip or off to the side so the pink chest heart stays
  visible; keep Pip's short stubby legs and round feet visible; closed arc eyes.
- motion: state movement as a change of position (from where to where), plus secondary motion (crowd, lights,
  particles, camera move). One sentence or two.
- scene and motion together under 90 words. No text, letters, captions or logos in any shot.
Return JSON only, matching the schema."""


def look_plan_prompt(day, n, look):
    """Planner prompt for the genre looks (pop-video, edm, rock, punk); see looks.py."""
    LK = LOOKS[look]
    genre, style = G.genre_of(day)
    stories = G.story_list(day)
    lyr = G.read(os.path.join(day, 'lyrics.txt'))
    title = G.read(os.path.join(day, 'title.txt')) or (G.load_json(os.path.join(day, 'tags.json'), {}) or {}).get('title', '')
    st = '\n'.join(f"{s['idx']}. {s['text']} (lyrics: {s['section']} lines {s['lines']}) :: {s['detail']}" for s in stories)
    n_ch = max(3, round(n * 0.3))
    return f"""Plan a shot list for a vertical 9:16 AI music video of today's AI-news song "{title}".
Genre: {genre or '?'} / style: {style}

{LK['direction']}
- Every shot is a high-production music-video PERFORMANCE moment, never a static explainer: a named camera move, the
  choreography / performance, the atmosphere.
- Pip's crew, if any: {LK['crew']}, so Pip stands out.
- Pip's outfit changes per section but keeps the core look: white egg body, bunny ears with pink insides, yellow antenna
  ball, navy face screen with cyan closed arc eyes, pink blush, short stubby legs, PINK HEART ON THE CHEST ALWAYS
  VISIBLE (jackets and shirts stay open; any guitar slung low at the hip or off to the side).

The star of EVERY shot is our mascot Pip: {G.PIP_DESC}
Each shot is made by restaging Pip from a reference image into ONE still (image edit), then animating that still for
10 seconds (image-to-video). So each shot is a single continuous camera setup with Pip large and fully in frame
head-to-feet, and big visible motion.

Stories (numbered):
{st}

Lyrics:
{lyr}

Write exactly {n} shots, in song order:
- 1 intro shot (story 0, section "intro"): {LK['intro']}.
- About {n_ch} {LK['chorus_word'].upper()} shots (story 0, section "chorus"): they all share {LK['hero']} (identical
  "setting" text for every chorus shot) with matching choreography for the hook, varied only by camera move, outfit and
  moment (the hit as the chorus lands, hands-up, slow-mo confetti, the final big pose).
- Every story gets at least one VERSE shot (story = its number; section "bridge" for bridge stories) on its own story set
  inside this world. The story appears as a nod through a set piece or prop around the performance: numbers as huge
  physical objects, a product or model as a giant glowing machine or robot, apps or documents as giant floating blank
  screens, a vote as a sea of raised hands or glowing buttons, papers exploding into confetti. Companies appear only as
  abstract stand-ins: no real people, logos, brand marks or readable text/numbers. Give stories with more lyric lines a
  second shot if the count allows.
- 1 outro shot (story 0, section "outro"): {LK['outro']}.
- No two story sets alike; the chorus shots share the hero set. Change Pip's outfit between sections.
- motion: state movement as a change of position (from where to where), the performance move, the crew, the camera move
  and the atmosphere. camera: the named camera move. outfit: Pip's styling.
- scene + motion under 100 words. No text, letters, captions or logos in any shot.
Return JSON only, matching the schema."""


def run_grok_text(prompt_file, cwd, schema=None, timeout=480, model='grok-4.7', effort='low'):
    cmd = [G.GROK, '--prompt-file', os.path.abspath(prompt_file), '--output-format', 'json', '-m', model,
           '--effort', effort, '--max-turns', '2', '--disallowed-tools',
           'web_search,web_fetch,Agent,image_gen,image_edit,image_to_video,reference_to_video,run_terminal_command,'
           'write,search_replace,read_file,list_dir,grep,todo_write,monitor,workflow,use_tool,search_tool',
           '--cwd', cwd]
    if schema:
        cmd += ['--json-schema', json.dumps(schema)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"grok exit {r.returncode}: {(r.stderr or r.stdout)[-500:]}")
    return json.loads(r.stdout)


def _extract_json(text):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, re.S)
        return json.loads(m.group(0)) if m else None


def fallback_plan(day, n):
    """Deterministic plan used only if the planner call fails."""
    fam = G.genre_family(*G.genre_of(day))
    stories = G.story_list(day)
    places = {
        'rock': ['an arena stage with pyro jets', 'a packed mosh pit', 'a garage band practice', 'a rooftop gig at sunset',
                 'a skate-park half-pipe', 'a tour bus roof on a desert highway', 'a stadium stage in the rain',
                 'a basement punk show', 'a festival main stage at night', 'a record shop', 'a backstage corridor',
                 'a monster-truck arena'],
        'pop': ['a candy-coloured studio set', 'a pastel roller rink', 'a glitter staircase', 'a neon arcade',
                'a bubblegum cloudscape', 'a glossy mirror-ball ballroom', 'a pink convertible on a beach road',
                'a giant music box', 'a confetti-filled TV studio', 'a pool party', 'a rooftop garden', 'a dance hall'],
        'bigroom': ['a festival main stage with lasers', 'a DJ booth above a sea of hands', 'a laser tunnel',
                    'a beach festival at sunset', 'a giant LED cube stage', 'a warehouse rave', 'a CO2 cannon platform',
                    'a ferris wheel at a festival', 'a stage-top pyro platform', 'a desert festival at dawn',
                    'a neon city rooftop rave', 'a confetti storm on stage'],
    }.get(fam, ['a big stage', 'a city rooftop', 'a neon street', 'a studio', 'a forest clearing', 'a beach'] * 2)
    shots = []
    order = [0] + [s['idx'] for s in stories] + [0] * n
    for i in range(n):
        si = order[i] if i < len(order) else 0
        sec = 'intro' if i == 0 else ('chorus' if si == 0 else 'verse')
        topic = next((s['text'] for s in stories if s['idx'] == si), 'the song title')
        place = places[i % len(places)]
        shots.append({'id': i + 1, 'story': si, 'section': sec, 'setting': place, 'props': topic,
                      'scene': f"Pip performing with huge energy in {place}, with playful props that stand for {topic}.",
                      'motion': "Pip jumps from the left of the frame to the centre and bounces on the beat, crowd and lights "
                                "moving, camera slowly pushing in."})
    return {'shots': shots, 'fallback': True}


def plan_shots(day, work, n, look='standard', L=None):
    """Genre looks: story-driven cinematic plan on a fixed slot skeleton (cine.py), using caption timings L when given.
    standard: the original free-form gig plan."""
    os.makedirs(work, exist_ok=True)
    pf = os.path.join(work, 'plan_prompt.txt')
    slots = cine.story_slots(day, n, L) if look in LOOKS else None
    if slots:
        n = len(slots)
        G.save_json(slots, os.path.join(work, 'slots.json'))
    open(pf, 'w').write(cine.plan_prompt(day, n, look, slots) if slots else plan_prompt(day, n))
    plan = None
    # GROK_VIDEO_PLAN_MAX_S: total planner budget (set by the cine-real fallback, where time is short; 0 = template plan)
    pmax = os.environ.get('GROK_VIDEO_PLAN_MAX_S')
    t_first = time.time()
    for attempt in (1, 2):
        try:
            t0 = time.time()
            tmo = 480 if pmax in (None, '') else int(float(pmax) - (t0 - t_first))
            if tmo < 60:
                G.log(f"planner: skipped attempt {attempt} (planner time budget {pmax}s used up)")
                break
            res = run_grok_text(pf, work, schema=cine.SCHEMA if slots else SCHEMA, timeout=min(480, tmo))
            plan = _extract_json(res.get('text', ''))
            G.log(f"planner: {time.time()-t0:.0f}s, session {res.get('sessionId')}")
            if plan and len(plan.get('shots', [])) >= n:
                plan['shots'] = plan['shots'][:n]
                break
            G.log(f"planner returned {len((plan or {}).get('shots', []))} shots, want {n}")
            plan = None
        except Exception as e:
            G.log(f"planner attempt {attempt} failed: {e}")
    if not plan:
        G.log("WARNING: using fallback shot plan")
        plan = fallback_plan(day, n)
    if slots:      # the skeleton decides story / section / lyric mapping; the planner only supplies the creative fields
        for sh, sl in zip(plan['shots'], slots):
            for k in ('story', 'section', 'beat', 'lyric', 'line_refs', 'window', 'slot', 'story_text'):
                if k in sl:
                    sh[k] = sl[k]
            if sl['story'] and plan.get('fallback'):
                sh['scene'] = (f"Pip acting out the story '{sl['story_text']}' in its own world, the story's players "
                               f"and numbers shown as big physical objects. " + ' / '.join(sl['lyric']))
        plan['timed'] = bool(L)
        plan['planner'] = PLANNER_VERSION
    # sanity: unique ids, unique settings
    seen = set()
    for i, s in enumerate(plan['shots']):
        s['id'] = i + 1
        s['file'] = f"clip{i+1:02d}.mp4"
        key = s.get('setting', '').lower().strip()
        if s.get('story'):
            key = (key, s['story'])       # a story's establishing + payoff shots may share their world
        if key in seen and s.get('section') != 'chorus':
            G.log(f"WARNING: repeated setting in plan: {key}")
        seen.add(key)
        if s.get('section') not in SECTIONS:
            s['section'] = 'verse' if s.get('story') else 'chorus'
    plan['look'] = look
    G.save_json(plan, os.path.join(work, 'shots.json'))
    return plan


# ------------------------------------------------------------------ generation
def gen_prompt(shot):
    return f"""You are generating ONE short vertical music-video clip of our mascot "Pip". Use your media tools directly.
Do not use web search, do not spawn subagents, do not run shell commands, and make NO extra or retry generations:
exactly ONE image_edit call followed by exactly ONE image_to_video call. If a tool call fails, report the error
verbatim and stop.

{G.PIP_DESC}

Step 1: call image_edit with image = ["{G.PIP_REF}"] and a prompt that re-stages this exact character (same design,
proportions, colours, flat 2D cartoon style with thick dark-navy outlines; restate Pip's traits: closed arc eyes, the
visible pink chest heart, short stubby legs with round feet) in this scene: {shot['scene']} Setting: {shot.get('setting','')}.
Vertical 9:16 composition that fills the ENTIRE frame edge to edge (no borders, no letterbox or dark bands at the top
or bottom), Pip large and fully in frame head-to-feet. No text, letters, logos or captions.

Step 2: call image_to_video on the image produced by step 1 with duration=10, resolution_name="720p", and this prompt:
"{shot['motion']} Keep Pip on-model throughout: closed arc eyes, short stubby legs, pink heart on chest visible, bunny
ears, flat 2D cartoon style. No text."

Step 3: reply with the two saved file paths. Do nothing else."""


def gen_prompt_look(shot, look):
    LK = LOOKS[look]
    outfit = (shot.get('outfit') or '').strip()
    wear = (f"Pip's styling for this shot: {outfit}. Any jacket or shirt stays OPEN so the pink chest heart shows; "
            f"sunglasses, caps or headphones never hide the bunny ears or antenna.") if outfit and outfit.lower() != 'none' else "No clothing."
    cam = (shot.get('camera') or '').strip()
    return f"""You are generating ONE shot of a high-budget {LK['label']} music video starring our mascot "Pip". Use your
media tools directly. Do not use web search, do not spawn subagents, do not run shell commands, and make NO extra or retry
generations: exactly ONE image_edit call followed by exactly ONE image_to_video call. If a tool call fails, report the
error verbatim and stop.

{G.PIP_DESC.replace(' No clothing.', '')} {wear}
Any other performers are {LK['crew']}, so Pip stands out.

Step 1: call image_edit with image = ["{G.PIP_REF}"] and a prompt that re-stages this exact character (same design,
proportions, colours, flat 2D cartoon style with thick dark-navy outlines; restate Pip's traits: white egg body, bunny
ears with pink insides, yellow antenna ball, navy face screen with cyan closed arc eyes, pink blush, the visible pink
chest heart, short stubby legs with round feet) in this {LK['scene_style']}: {shot['scene']}
Setting: {shot.get('setting', '')}. {LK['lighting']} Vertical 9:16 composition that fills the ENTIRE frame edge to edge
(no borders, no letterbox or dark bands), Pip large and fully in frame head-to-feet. No text, letters, logos or captions.

Step 2: call image_to_video on the image produced by step 1 with duration=10, resolution_name="720p", and this prompt:
"{shot['motion']} Camera: {cam or LK['default_camera']}. {LK['motion_tail']} Keep Pip on-model throughout: closed arc
eyes, short stubby legs, pink heart on chest visible, bunny ears, flat 2D cartoon style. No text."

Step 3: reply with the two saved file paths. Do nothing else."""


# allowance / plan problems: stop generating at once
QUOTA = re.compile(r'upgrade|subscription|quota|limit (?:reached|exceeded)|usage limit|weekly limit|insufficient|'
                   r'zero.data|ZDR|not available on your plan', re.I)
# per-second request throttling (e.g. "Your team's rate limit is - Requests per Second (actual/limit): 2/2") is
# transient: wait and retry, never abort
THROTTLE = re.compile(r'requests per second|requests/s\b|\bRPS\b|too many requests|\b429\b', re.I)
RATE = re.compile(r'rate.?limit', re.I)


def classify(text):
    """'quota' (abort), 'throttle' (wait + retry) or None."""
    if QUOTA.search(text):
        return 'quota'
    if THROTTLE.search(text):
        return 'throttle'
    if RATE.search(text):
        return 'quota'      # an unrecognised rate-limit message: be safe, stop spending
    return None


class Generator:
    def __init__(self, work, shots, max_parallel=4, budget=None, timeout=900, look='standard'):
        self.look = look
        self.work = work
        self.shots = shots
        self.clips = os.path.join(work, 'clips')
        self.pdir = os.path.join(work, 'prompts')
        self.ldir = os.path.join(work, 'gen_logs')
        for d in (self.clips, self.pdir, self.ldir):
            os.makedirs(d, exist_ok=True)
        self.budget = budget if budget is not None else len(shots) + 3
        self.used = 0
        self.lock = threading.Lock()
        self.abort = None
        self.max_parallel = max_parallel
        self.timeout = timeout
        self.results = {}
        self.start_gap = 12.0           # seconds between any two job starts (no same-second bursts on the media API)
        self.next_start = 0.0           # also pushed forward by a throttle response (global cool-down)
        self.throttled = 0
        self.max_throttle = max(6, len(shots))   # total throttle retries per run before giving up on them

    def _wait_turn(self):
        while True:
            with self.lock:
                now = time.time()
                if now >= self.next_start:
                    self.next_start = now + self.start_gap
                    return
                wait = self.next_start - now
            time.sleep(min(wait, 5))

    def _take(self):
        with self.lock:
            if self.abort or self.used >= self.budget:
                return False
            self.used += 1
            return True

    def _run_one(self, shot, attempt):
        sid = shot['id']
        pf = os.path.abspath(os.path.join(self.pdir, f"shot{sid:02d}.txt"))
        open(pf, 'w').write(cine.clip_prompt(shot, self.look) if self.look in LOOKS else gen_prompt(shot))
        logf = os.path.join(self.ldir, f"shot{sid:02d}_try{attempt}_{time.strftime('%H%M%S')}.ndjson")
        cmd = [G.GROK, '--prompt-file', pf, '--output-format', 'streaming-json', '--always-approve',
               '--max-turns', '8', '--disallowed-tools',
               'web_search,web_fetch,Agent,image_gen,reference_to_video,run_terminal_command',
               '--cwd', os.path.abspath(self.work)]
        t0 = time.time()
        err = ''
        try:
            with open(logf, 'w') as out, open(logf + '.err', 'w') as er:
                rc = subprocess.run(cmd, stdout=out, stderr=er, timeout=self.timeout).returncode
        except subprocess.TimeoutExpired:
            rc, err = -9, f'timeout after {self.timeout}s'
        img = vid = None
        texts = []
        for line in open(logf, errors='ignore'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            ro = d.get('rawOutput') if isinstance(d.get('rawOutput'), dict) else None
            if ro and ro.get('type') == 'ImageEdit' and ro.get('path'):
                img = ro['path']
            if ro and ro.get('type') == 'ImageToVideo' and ro.get('path'):
                vid = ro['path']
            if d.get('type') == 'tool_call_update' and d.get('status') == 'failed':
                texts.append(json.dumps(d.get('rawOutput'))[:400])
            if d.get('type') in ('text', 'error'):
                texts.append(str(d.get('data') or d.get('message') or ''))
        alltext = ''.join(texts) + G.read(logf + '.err')
        dst = os.path.join(self.clips, shot['file'])
        ok = False
        if vid and os.path.exists(vid):
            pv = G.probe_video(vid)
            if pv and pv[2] >= 4.0:
                shutil.copyfile(vid, dst)
                if img and os.path.exists(img):
                    shutil.copyfile(img, dst.replace('.mp4', '-keyframe.jpg'))
                ok = True
            else:
                err = err or f'bad video {pv}'
        else:
            err = err or f'no video (rc={rc}): {alltext[-300:]}'
        kind = None if ok else classify(alltext)
        transient = kind == 'throttle' and not vid
        if kind == 'quota':
            with self.lock:
                self.abort = self.abort or f"fatal Grok response on shot {sid}: {alltext[-300:]}"
        G.log(f"shot {sid:02d} try {attempt}: {'OK' if ok else 'FAIL'} in {time.time()-t0:.0f}s"
              + ('' if ok else f" ({err[:200]})"))
        return ok, round(time.time() - t0, 1), err, transient

    def _shot(self, shot):
        attempt, rerolls, waits = 0, 0, 0
        while True:
            attempt += 1
            self._wait_turn()                      # staggered starts + global cool-down after a throttle
            if not self._take():
                return {'ok': False, 'err': self.abort or 'generation budget exhausted', 'tries': attempt - 1}
            ok, secs, err, transient = self._run_one(shot, attempt)
            if ok:
                return {'ok': True, 'secs': secs, 'tries': attempt, 'throttle_waits': waits}
            if self.abort:
                return {'ok': False, 'err': self.abort, 'tries': attempt}
            if transient:
                with self.lock:
                    can = waits < 4 and self.throttled < self.max_throttle
                    if can:
                        # a throttled try produced no video: it does not use up a generation or the reroll
                        self.throttled += 1; self.used -= 1
                        back = 30 * (waits + 1) + random.random() * 15
                        self.next_start = max(self.next_start, time.time() + back)
                if can:
                    waits += 1
                    G.log(f"shot {shot['id']:02d}: throttled (requests per second); all starts paused {back:.0f}s, retry {waits}/4")
                    continue
            rerolls += 1
            if rerolls > 1:                        # one reroll per failed clip
                return {'ok': False, 'err': err, 'tries': attempt}

    def run(self):
        t0 = time.time()
        todo = [s for s in self.shots if not (os.path.exists(os.path.join(self.clips, s['file']))
                                              and (G.probe_video(os.path.join(self.clips, s['file'])) or (0, 0, 0))[2] >= 4)]
        G.log(f"generating {len(todo)} clips ({len(self.shots)-len(todo)} cached), {self.max_parallel} at a time, "
              f"budget {self.budget} generations")
        with ThreadPoolExecutor(self.max_parallel) as ex:
            for s, r in zip(todo, ex.map(self._shot, todo)):
                self.results[s['id']] = r
        summary = {'wall_s': round(time.time() - t0, 1), 'generations_used': self.used, 'budget': self.budget,
                   'ok': sum(1 for s in self.shots if os.path.exists(os.path.join(self.clips, s['file']))),
                   'wanted': len(self.shots), 'abort': self.abort, 'throttle_retries': self.throttled,
                   'per_shot': {str(k): v for k, v in self.results.items()}}
        G.save_json(summary, os.path.join(self.work, 'gen_summary.json'))
        return summary
