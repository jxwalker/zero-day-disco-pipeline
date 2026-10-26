#!/usr/bin/env python3
"""Headline mode: a clear, literal, funny news song + its video plan, written by Opus (headless claude).

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
import copy
import songcraft as SC   # one-thread concept + strict Opus judge

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
    ch = [[l['text'].strip().lower() for l in s['lines']] for s in res['sections'] if re.fullmatch(r'chorus', re.split(r':|\s+-\s+|,', s['tag'].strip('[] '))[0].strip().lower())]
    if len(ch) < 2 or any(not c or c[0] != ch[0][0] for c in ch[1:]):   # chorus 2 may vary; hook line identical
        probs.append('every [Chorus] must open with the same hook line')
    fc = [s for s in res['sections'] if 'final' in s['tag'].lower()]
    if ch and fc:
        b = [l['text'].strip().lower() for l in fc[0]['lines']]
        if not b or b[0] != ch[0][0]:
            probs.append('the final chorus must open with the hook line')
        elif all(b == c[:len(b)] for c in ch):     # a changed/flipped line counts as the callback
            probs.append('the final chorus needs a flip or callback line')
    n = sum(len(s['lines']) for s in res['sections'])
    if not 16 <= n <= 28:   # sparser lyrics
        probs.append(f'{n} lines (want about 20-24; cut lines if over)')
    if not any('breakdown' in s['tag'].lower() for s in res['sections']):   # viral format
        probs.append('missing [Breakdown - stripped] before the final chorus')
    probs += ['style: ' + x for x in SL.problems(SL.fix(res['style']))]
    if any(v < 8 for v in res['scores'].values()):
        probs.append(f"self-scores under 8: {res['scores']}")
    st = {s['n']: s for s in stories(day)}
    voc = vocab(day)
    for t in res['ticker']:
        ok, bad = ticker_ok(t['text'], voc, st.get(t['story'], {}).get('handles', []))
        if not ok:
            probs.append(f"ticker for story {t['story']} not verbatim from stories.md: {bad}")
    bots = re.compile(r'\b(robot|robotic|android|cyborg|mascot|toy|pip)s?\b', re.I)     # no robots
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
    """the picked hook option; Opus numbers them 1-based, so match the title first."""
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
          f"**Self-scores:** {res['scores']}  {res.get('rewrite_note', '')}", f"**Opus judge:** {(res.get('judge') or {}).get('final')}", f"**Headline card:** {res['headline_card']}",
          '**Ticker:**'] + [f"- (story {t['story']}) {t['text']}" for t in res['ticker']]
    o += ['', '**Cast:**'] + [f"- {c['id']} {c['role']}: {c['description']}" for c in res['cast']]
    o += ['', '## Storyboard draft']
    for b in res['storyboard']:
        o.append(f"### {b['section']} @ {b['location']} (story {b.get('story', 0)}; cast {', '.join(b.get('cast') or [])})")
        o += [f"{i+1}. {x}" for i, x in enumerate(b['shots'])]
    o += ['', '**Pip:** ' + ' / '.join(res['pip'])]
    return '\n'.join(o) + '\n'


def _files(res, out):
    lp = os.path.join(out, 'lyrics.txt')
    open(lp, 'w').write(lyrics_text(res))
    open(os.path.join(out, 'style.txt'), 'w').write(SL.fix(res['style']).strip() + '\n')
    open(os.path.join(out, 'title.txt'), 'w').write(res['title'].strip() + '\n')
    ok, msg = lint(lp)
    return check(res, out) + ([] if ok else [f'lint: {msg}'])


CRAFT = ("CRAFT (always): each verse is 4 lines and tells one beat of ONE story arc (set-up -> incident -> consequence); "
         "the chorus line that the bridge/final chorus flips must be SET UP earlier (we see the accusation before the denial); "
         "keep ONE motif/object recurring in every section with the same wording; the last chorus + outro must land the point "
         "(a turn that changes what the hook means), not just repeat it. Make room by trimming chants/post-choruses, not verses.")


def _lint_repair(res, probs, out, od, n, tries=2):
    """Targeted lint repair: minimal edits to the CURRENT draft until _files() is clean (max `tries` Opus passes)."""
    for t in range(tries):
        if not probs:
            break
        rf = os.path.join(od, f'lint_repair_{n}_{t}.txt')
        open(rf, 'w').write(
            "Fix ONLY these lint/format problems in this song package with the smallest possible edits. Do not change the "
            "concept, story, motif, hook wording or any line that is not implicated. Cut words or whole lines (prefer chant/"
            "post-chorus lines) rather than rewriting. Keep stories/tickers verbatim from the stories. Return the whole JSON."
            "\n\nPROBLEMS:\n- %s\n\nPACKAGE:\n%s" % ('\n- '.join(probs), json.dumps(res, ensure_ascii=False)))
        try:
            fixed, meta = SO.run_claude(rf, od, SCHEMA, int(os.environ.get('HL_LINT_REPAIR_S', 600)), tools='', effort='medium')
        except Exception as e:
            print(f"lint repair failed: {e!r}"[:300]); break
        p2 = _files(fixed, out)
        print(f"lint repair {n}.{t}: {len(probs)} -> {len(p2)} problems")
        if len(p2) <= len(probs):
            res, probs = fixed, p2
    _files(res, out)
    return res, probs


def judge_loop(res, out, od, pf, stories_md, concept_txt):
    rounds = int(os.environ.get('HL_JUDGE_ROUNDS', 5))
    best, log = None, []
    for n in range(rounds + 1):
        res, probs = _lint_repair(res, _files(res, out), out, od, n)   # repair THIS draft, never fall back to a weaker clean one
        try:
            j = SC.judge(lyrics_text(res), res['title'], concept_txt, stories_md, od, n)
        except Exception as e:
            print(f"songcraft judge failed: {e!r}"[:300]); break
        log.append({'round': n, 'scores': j['scores'], 'mean': j['mean'], 'pass': j['pass'], 'lint_problems': probs,
                    'must_fix': j['must_fix'], 'verdict': j['verdict']})
        key = (not probs, j['pass'], j['mean'])
        if best is None or key > best[0]:
            best = (key, copy.deepcopy(res), j)
        if (j['pass'] and not probs) or n == rounds:
            break
        rf = os.path.join(od, f'judge_rewrite_{n}.txt')
        open(rf, 'w').write(
            "A strict lyric judge REJECTED this song (pass = every score >= %d and mean >= %.1f). Rewrite the song to fix "
            "every must-fix and line note, keep the concept, thread and pun, keep every format/density rule (cut words, "
            "never add lines), re-score honestly and return the whole JSON.\n\nJUDGE SCORES: %s\nVERDICT: %s\nMUST FIX:\n- %s"
            "\nLINE NOTES:\n%s\n%s\nOriginal brief:\n%s\n\nPACKAGE:\n%s" % (
                SC.MIN, SC.MEAN, json.dumps(j['scores']), j['verdict'], '\n- '.join(j['must_fix']),
                '\n'.join(f"- {x['line']!r}: {x['problem']} -> {x['fix']}" for x in j['line_notes']),
                ('ALSO FIX THESE LINT/CHECK PROBLEMS:\n- ' + '\n- '.join(probs)) if probs else '',
                open(pf).read(), json.dumps(res, ensure_ascii=False)) + '\n\n' + CRAFT)
        try:
            res, meta = SO.run_claude(rf, od, SCHEMA, int(os.environ.get('HL_JUDGE_REWRITE_S', 900)), tools='',
                                      effort=os.environ.get('HL_JUDGE_EFFORT', 'medium'))   # high timed out at 700 s
        except Exception as e:
            print(f"judge rewrite failed: {e!r}"[:300]); break
    if best is None:
        return res
    res = best[1]
    res['judge'] = {'final': {'scores': best[2]['scores'], 'mean': best[2]['mean'], 'pass': best[2]['pass'],
                              'verdict': best[2]['verdict']}, 'rounds': log, 'min': SC.MIN, 'mean_needed': SC.MEAN}
    json.dump(res['judge'], open(os.path.join(od, 'judge_log.json'), 'w'), indent=1, ensure_ascii=False)
    _files(res, out)
    return res


def write(src, out):
    os.makedirs(out, exist_ok=True)
    for f in ('stories.md', 'sources.txt'):
        if os.path.abspath(src) != os.path.abspath(out) and os.path.exists(os.path.join(src, f)):
            shutil.copyfile(os.path.join(src, f), os.path.join(out, f))
    od = os.path.join(out, 'work_headline'); os.makedirs(od, exist_ok=True)
    pf = os.path.join(od, 'prompt.txt')
    stories_md = open(os.path.join(out, 'stories.md')).read().strip()
    concept_txt = ''
    if os.environ.get('HL_SONGCRAFT', '1') != '0':      # pick ONE thread + real-life pun first
        try:
            C = SC.concepts(stories_md, od)
            concept_txt = SC.concept_block(C, C['pick'].get('sharpen', ''))
            print(f"songcraft concept: {C['chosen']['phrase']!r} :: {C['pick'].get('why', '')[:200]}")
        except Exception as e:
            print(f"songcraft concepts failed (writer picks its own angle): {e!r}"[:300])
    open(pf, 'w').write(open(os.path.join(HERE, 'prompts', 'headline_writer.txt')).read()
                        .replace('{{STORIES}}', stories_md).replace('{{CONCEPT}}', concept_txt) + '\n\n' + CRAFT + '\n')
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
        open(os.path.join(out, 'title.txt'), 'w').write(res['title'].strip() + '\n')  # viral lint checks the title hook
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
    if os.environ.get('HL_SONGCRAFT', '1') != '0':      # strict independent Opus judge, up to N rewrites
        res = judge_loop(res, out, od, pf, stories_md, concept_txt)
    res['style'] = SL.fix(res['style'])  # no autotune/vocoder, no jingles
    open(os.path.join(out, 'style.txt'), 'w').write(res['style'].strip() + '\n')
    res['cast'] = (res.get('cast') or [])[:3]      # (Claudia mode): one lead A + at most 2 supporting
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
