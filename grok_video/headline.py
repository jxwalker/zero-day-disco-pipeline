#!/usr/bin/env python3
"""Headline mode (13 Oct 2026): a clear, literal, funny news song + its video plan, written by Opus (headless claude).

usage: headline.py write <src_day> [--out DIR]
Structure: hook (headline gag + title) / Verse 1 = the MAIN story literally / identical chorus with a wordplay twist /
Verse 2 = 2-3 secondary stories / Bridge with a Suno meta-tag surprise / Final chorus with a one-word callback / Outro
punchline. Writes into DIR: lyrics.txt style.txt title.txt headline.json headline.md storyboard_draft.md, and
tags.json 'sources' = handles of the SUNG stories only. lyrics must pass tools/lyrics_lint.py and self-scores >= 8
(up to 2 rewrite calls). <day>/headline.json switches grok_video into headline mode (ticker, headline card, hook words).
Exit 0 ok, 1 checks failed, 3 Opus failed."""
import json, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import slop_opus as SO
import common_gv as G

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import style_lint as SL

LINT = os.path.join(os.path.dirname(HERE), 'lyrics_lint.py')
S = {"type": "string"}; I = {"type": "integer"}
SCHEMA = {"type": "object", "properties": {
    "ranking": {"type": "array", "items": {"type": "object", "properties": {"story": I, "clarity": I, "comedy": I, "angle": S},
                                           "required": ["story", "clarity", "comedy", "angle"]}},
    "main_story": I, "secondary": {"type": "array", "items": I},
    "hook_options": {"type": "array", "items": {"type": "object", "properties": {"title": S, "visual_gag": S, "twist": S},
                                                "required": ["title", "visual_gag", "twist"]}},
    "chosen_hook": I, "why_funniest": S,
    "title": S, "style": S,
    "sections": {"type": "array", "items": {"type": "object", "properties": {
        "tag": S, "meta": {"type": "array", "items": S},
        "lines": {"type": "array", "items": {"type": "object", "properties": {"text": S, "story": I}, "required": ["text", "story"]}}},
        "required": ["tag", "lines"]}},
    "hook_words": {"type": "string", "description": "the chorus hook phrase shown on screen in choruses (2-6 words)"},
    "callback_word": S, "bridge_surprise": S,
    "scores": {"type": "object", "properties": {"clarity": I, "wordplay": I, "catchiness": I}, "required": ["clarity", "wordplay", "catchiness"]},
    "rewrite_note": S,
    "ticker": {"type": "array", "items": {"type": "object", "properties": {"story": I, "text": S}, "required": ["story", "text"]}},
    "headline_card": S,
    "cast": {"type": "array", "items": {"type": "object", "properties": {"id": S, "role": S, "description": S}, "required": ["id", "role", "description"]}},
    "storyboard": {"type": "array", "items": {"type": "object", "properties": {
        "section": S, "location": S, "story": I, "cast": {"type": "array", "items": S}, "shots": {"type": "array", "items": S}},
        "required": ["section", "location", "shots"]}},
    "pip": {"type": "array", "items": S}, "outro_punchline_shot": S},
    "required": ["ranking", "main_story", "secondary", "hook_options", "chosen_hook", "why_funniest", "title", "style",
                 "sections", "hook_words", "callback_word", "bridge_surprise", "scores", "ticker", "headline_card", "cast",
                 "storyboard", "pip", "outro_punchline_shot"]}


def stories(day):
    """[{n, title, body, handles}] from stories.md (## N. title)."""
    txt = open(os.path.join(day, 'stories.md')).read()
    out = []
    for m in re.finditer(r'^##\s*(\d+)\.\s*(.+?)\n(.*?)(?=^##\s*\d+\.|\Z)', txt, re.S | re.M):
        body = m.group(3)
        hs = []
        for h in re.findall(r'@([A-Za-z0-9_]+)', body) + re.findall(r'x\.com/([A-Za-z0-9_]+)/status', body):
            if h not in hs:
                hs.append(h)
        out.append({'n': int(m.group(1)), 'title': m.group(2).strip(), 'body': body, 'handles': hs})
    return out


def vocab(day):
    txt = open(os.path.join(day, 'stories.md')).read()
    return {w.lower().strip(".,'\"") for w in re.findall(r"[A-Za-z0-9@%$~.,'+\-–]+", txt)}


STOP = set("a an the of to in on by and or for with from at is are was were it its as up down vs than over under via "
           "new now off out back cuts cut gets got says".split())


def ticker_ok(text, voc, handles):
    ws = re.findall(r"[A-Za-z0-9@%$~.'+\-–]+", text)
    bad = [w for w in ws if w.lower().strip(".,'") not in voc and w.lower() not in STOP]
    hs = re.findall(r'@([A-Za-z0-9_]+)', text)
    bad += [f'@{h}' for h in hs if h not in handles]
    return (not bad and bool(hs) and len(text) <= 70), bad


def lyrics_text(res):
    out = []
    for s in res['sections']:
        out.append(f"[{s['tag'].strip('[]')}]")
        out += [f"[{m.strip('[]')}]" for m in s.get('meta') or []]
        out += [l['text'].strip() for l in s['lines']]
        out.append('')
    return '\n'.join(out).strip() + '\n'


def check(res, day):
    probs = []
    ch = [[l['text'].strip().lower() for l in s['lines']] for s in res['sections'] if re.fullmatch(r'chorus', s['tag'].strip('[] ').lower())]
    if len(ch) < 2 or any(c != ch[0] for c in ch[1:]):
        probs.append('the [Chorus] sections must be identical')
    fc = [s for s in res['sections'] if 'final' in s['tag'].lower()]
    if ch and fc:
        a, b = ch[0], [l['text'].strip().lower() for l in fc[0]['lines']][:len(ch[0])]
        diff = sum(len(set(x.split()) ^ set(y.split())) for x, y in zip(a, b))
        if diff == 0:
            probs.append('the final chorus needs a one-word callback swap')
    n = sum(len(s['lines']) for s in res['sections'])
    if not 16 <= n <= 28:   # 17 Oct: sparser lyrics
        probs.append(f'{n} lines (want about 20-24; cut lines if over)')
    if not any(s.get('meta') for s in res['sections'] if 'bridge' in s['tag'].lower()):
        probs.append('the bridge has no Suno meta-tag surprise')
    if any(v < 8 for v in res['scores'].values()):
        probs.append(f"self-scores under 8: {res['scores']}")
    st = {s['n']: s for s in stories(day)}
    voc = vocab(day)
    for t in res['ticker']:
        ok, bad = ticker_ok(t['text'], voc, st.get(t['story'], {}).get('handles', []))
        if not ok:
            probs.append(f"ticker for story {t['story']} not verbatim from stories.md: {bad}")
    bots = re.compile(r'\b(robot|robotic|android|cyborg|mascot|toy|pip)s?\b', re.I)     # 14 Oct: no robots
    vis = json.dumps([res.get('cast'), res.get('storyboard'), res.get('pip'), res.get('outro_punchline_shot'),
                      [h['visual_gag'] for h in res.get('hook_options', [])]])
    if bots.search(vis):
        probs.append(f"robots/mascots are banned in cast and storyboard (found '{bots.search(vis).group(0)}'); show AI through real people, screens, offices, labs")
    sung = {l['story'] for s in res['sections'] for l in s['lines']} - {0}
    if res['main_story'] not in sung:
        probs.append('the main story is not tagged on any sung line')
    return probs


def lint(path):
    r = subprocess.run([sys.executable, LINT, path], capture_output=True, text=True)
    return r.returncode == 0, r.stdout.strip()


def chosen(res):
    """the picked hook option; Opus numbers them 1-based (13 Oct: index 1 showed option 2), so match the title first."""
    ho = res['hook_options']
    for x in ho:
        if x['title'].strip().lower() == res['title'].strip().lower():
            return x
    i = res.get('chosen_hook', 1)
    return ho[i - 1] if 1 <= i <= len(ho) else ho[0]


def md(res, day):
    st = {s['n']: s for s in stories(day)}
    h = chosen(res)
    o = [f"# {res['title']}", f"**Style:** {res['style']}", '',
         f"**Main story:** #{res['main_story']} {st.get(res['main_story'], {}).get('title', '')}",
         '**Secondary:** ' + '; '.join(f"#{n} {st.get(n, {}).get('title', '')}" for n in res['secondary']), '',
         '**Ranking (clarity/comedy):** ' + '; '.join(f"#{r['story']} {r['clarity']}/{r['comedy']} ({r['angle']})" for r in res['ranking']), '',
         '**Hook options:**'] + [f"{i+1}. \"{x['title']}\" - gag: {x['visual_gag']} - twist: {x['twist']}" for i, x in enumerate(res['hook_options'])]
    o += [f"**Chosen:** \"{h['title']}\" - {res['why_funniest']}", f"**Hook visual (0-3 s):** {h['visual_gag']}",
          f"**Chorus hook words:** {res['hook_words']}  |  **final-chorus callback word:** {res['callback_word']}",
          f"**Bridge surprise:** {res['bridge_surprise']}", f"**Outro punchline shot:** {res['outro_punchline_shot']}",
          f"**Self-scores:** {res['scores']}  {res.get('rewrite_note', '')}", f"**Headline card:** {res['headline_card']}",
          '**Ticker:**'] + [f"- (story {t['story']}) {t['text']}" for t in res['ticker']]
    o += ['', '**Cast:**'] + [f"- {c['id']} {c['role']}: {c['description']}" for c in res['cast']]
    o += ['', '## Storyboard draft']
    for b in res['storyboard']:
        o.append(f"### {b['section']} @ {b['location']} (story {b.get('story', 0)}; cast {', '.join(b.get('cast') or [])})")
        o += [f"{i+1}. {x}" for i, x in enumerate(b['shots'])]
    o += ['', '**Pip:** ' + ' / '.join(res['pip'])]
    return '\n'.join(o) + '\n'


def write(src, out):
    os.makedirs(out, exist_ok=True)
    for f in ('stories.md', 'sources.txt'):
        if os.path.abspath(src) != os.path.abspath(out) and os.path.exists(os.path.join(src, f)):
            shutil.copyfile(os.path.join(src, f), os.path.join(out, f))
    od = os.path.join(out, 'work_headline'); os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'prompt.txt')
    open(pf, 'w').write(open(os.path.join(HERE, 'prompts', 'headline_writer.txt')).read()
                        .replace('{{STORIES}}', open(os.path.join(out, 'stories.md')).read().strip()))
    try:
        res, meta = SO.run_claude(pf, od, SCHEMA, 900, tools='', effort='high')
    except Exception as e:
        print(f"HEADLINE_STATUS=failed code=3 reason={e!r}"[:400]); return 3
    print(f"opus: {meta['secs']}s ${meta.get('cost_usd')}")
    for attempt in range(3):
        json.dump(res, open(os.path.join(od, f'reply_{attempt}.json'), 'w'), indent=1, ensure_ascii=False)
        lp = os.path.join(out, 'lyrics.txt')
        open(lp, 'w').write(lyrics_text(res))
        open(os.path.join(out, 'style.txt'), 'w').write(SL.fix(res['style']).strip() + '\n')  # density lint reads BPM/metre
        ok, msg = lint(lp)
        probs = check(res, out) + ([] if ok else [f'lint: {msg}'])
        if not probs or attempt == 2:
            break
        print('rewrite:', probs)
        rf = os.path.join(od, f'rewrite_{attempt}.txt')
        open(rf, 'w').write("Fix these problems in this song package. Rewrite only what is needed, re-score the lyrics "
                            "honestly (clarity, wordplay, catchiness; all must reach 8) and return the whole JSON. If any problem says "
                            "'density' or 'too many words': TRIM - cut whole lines and filler, make every flagged line "
                            "shorter, keep the news plain and literal in fewer words, never add lines:\n- "
                            + '\n- '.join(probs) + "\n\nOriginal brief:\n" + open(pf).read() + "\n\nPACKAGE:\n" + json.dumps(res))
        try:
            res, meta = SO.run_claude(rf, od, SCHEMA, 700, tools='', effort='medium')
        except Exception as e:
            print(f"rewrite failed: {e!r}"[:300]); break
    res['style'] = SL.fix(res['style'])  # 16 Oct: no autotune/vocoder, no jingles
    open(os.path.join(out, 'style.txt'), 'w').write(res['style'].strip() + '\n')
    res['cast'] = (res.get('cast') or [])[:3]      # 19 Oct (Claudia mode): one lead A + at most 2 supporting
    open(os.path.join(out, 'title.txt'), 'w').write(res['title'].strip() + '\n')
    json.dump(res, open(os.path.join(out, 'headline.json'), 'w'), indent=1, ensure_ascii=False)
    open(os.path.join(out, 'headline.md'), 'w').write(md(res, out))
    # credits = handles of the SUNG stories only (main first)
    st = {s['n']: s for s in stories(out)}
    sung = [res['main_story']] + [n for n in res['secondary'] if n != res['main_story']]
    hs = []
    for n in sung:
        for h in st.get(n, {}).get('handles', []):
            if h not in hs:
                hs.append(h)
    tf = os.path.join(out, 'tags.json')
    tags = G.load_json(tf, {}) or {}
    tags.update(sources=hs, mode='headline', title=res['title'])
    json.dump(tags, open(tf, 'w'), indent=1)
    ok, msg = lint(os.path.join(out, 'lyrics.txt'))
    probs = check(res, out) + ([] if ok else [f'lint: {msg}'])
    print(f"HEADLINE_STATUS={'ok' if not probs else 'checks_failed'} code={0 if not probs else 1} out={out} "
          f"title={res['title']!r} scores={res['scores']} problems={probs}")
    return 0 if not probs else 1


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2 or a[0] != 'write':
        print(__doc__); sys.exit(2)
    sys.exit(write(a[1], a[a.index('--out') + 1] if '--out' in a else a[1]))
