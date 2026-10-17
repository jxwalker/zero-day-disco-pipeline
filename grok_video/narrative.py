#!/usr/bin/env python3
"""Narrative mode (13 Oct 2026): song and video written together as ONE short musical story by Opus (headless claude).

usage: narrative.py write <src_day> [--out DIR]
  Reads <src_day>/stories.md (+ sources.txt), asks Opus for: main-story pick, treatment, lyrics, title, style and a
  storyboard draft. Writes into DIR (default <src_day>, i.e. replaces the routine's lyrics step):
    lyrics.txt  style.txt  title.txt  treatment.json  treatment.md  storyboard_draft.md  narrative.json
  lyrics.txt must pass tools/lyrics_lint.py (one Opus repair call, then exit 1 if still dirty).
  The presence of <day>/treatment.json switches grok_video's slopcore planner + type into narrative mode
  (slop_opus.narrative(), real_render.build_ass_narrative); delete it to get the old behaviour.
Exit 0 ok, 1 lint failed, 3 Opus failed."""
import json, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import slop_opus as SO
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import style_lint as SL

LINT = os.path.join(os.path.dirname(HERE), 'lyrics_lint.py')
S = {"type": "string"}
SCHEMA = {"type": "object", "properties": {
    "main_story": {"type": "integer", "description": "number of the chosen story in STORIES"},
    "why": S,
    "background_gags": {"type": "array", "items": S},
    "treatment": {"type": "object", "properties": {
        "logline": S,
        "protagonist": {"type": "object", "properties": {"id": S, "role": S, "description": S, "want": S},
                        "required": ["role", "description", "want"]},
        "cast": {"type": "array", "items": {"type": "object", "properties": {"id": S, "role": S, "description": S},
                                            "required": ["id", "role", "description"]}},
        "obstacle": S, "turn": S, "payoff": S,
        "locations": {"type": "array", "items": {"type": "object", "properties": {"id": S, "name": S, "look": S},
                                                 "required": ["id", "name", "look"]}},
        "chorus_motif": {"type": "object", "properties": {"image": S, "escalation": {"type": "array", "items": S}},
                         "required": ["image", "escalation"]},
        "opening_image": S, "final_image": S,
        "facts": {"type": "array", "items": {"type": "object", "properties": {"fact": S, "source": S},
                                             "required": ["fact", "source"]}}},
        "required": ["logline", "protagonist", "cast", "obstacle", "turn", "payoff", "locations", "chorus_motif",
                     "opening_image", "final_image", "facts"]},
    "title": S, "style": S, "lyrics": {"type": "string", "description": "full lyrics with [Section] tags, one line per sung line"},
    "storyboard": {"type": "array", "items": {"type": "object", "properties": {
        "section": S, "location": S, "beat": S, "cast": {"type": "array", "items": S}, "light": S,
        "shots": {"type": "array", "items": S}}, "required": ["section", "location", "beat", "shots"]}},
    "pip": {"type": "array", "items": S},
    "diegetic_text": {"type": "array", "items": {"type": "object", "properties": {"text": S, "where": S, "section": S},
                                                 "required": ["text", "where", "section"]}}},
    "required": ["main_story", "why", "treatment", "title", "style", "lyrics", "storyboard", "pip", "diegetic_text"]}


def stories_block(day):
    txt = open(os.path.join(day, 'stories.md')).read()
    return txt.strip()


def lint(path):
    r = subprocess.run([sys.executable, LINT, path], capture_output=True, text=True)
    return r.returncode == 0, r.stdout.strip()


def check_lyrics(lyr, title):
    """structural checks: chorus identical on every repeat, line count, title in the chorus."""
    secs, cur = [], None
    for ln in lyr.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith('[') and s.endswith(']'):
            cur = [s.strip('[]'), []]; secs.append(cur); continue
        if cur is None:
            cur = ['Verse', []]; secs.append(cur)
        cur[1].append(s)
    probs = []
    ch = [l for n, l in secs if 'chorus' in n.lower() and 'pre' not in n.lower()]
    if len(ch) < 2:
        probs.append('fewer than 2 choruses')
    elif any(c[:len(ch[0])] != ch[0] for c in ch[1:]):
        probs.append('chorus repeats are not identical (a final chorus may only ADD a tag line at the end)')
    n = sum(len(l) for _, l in secs)
    if not 16 <= n <= 30:   # 17 Oct: sparser lyrics
        probs.append(f'{n} lines (want about 20-26; cut lines if over)')
    if ch and title.lower().split()[0] not in ' '.join(ch[0]).lower():
        probs.append('title not in the chorus')
    if any(re.search(r'\(.*\)', l) for _, ls in secs for l in ls):
        probs.append('parenthetical text in sung lines')
    return probs


def md(res, stories):
    t = res['treatment']
    p = t['protagonist']
    o = [f"# {res['title']}\n", f"**Style:** {res['style']}\n",
         f"**Main story:** #{res['main_story']} - {res['why']}\n"]
    if res.get('background_gags'):
        o.append('**Background gags:** ' + '; '.join(res['background_gags']) + '\n')
    o += [f"**Logline:** {t['logline']}\n", f"**Protagonist ({p.get('id', 'A')}, {p['role']}):** {p['description']}. "
          f"Wants: {p['want']}\n", '**Cast:**'] + [f"- {c['id']} {c['role']}: {c['description']}" for c in t['cast']]
    o += ['', f"**Obstacle:** {t['obstacle']}", f"**Turn (bridge):** {t['turn']}", f"**Payoff:** {t['payoff']}", '',
          '**Locations:**'] + [f"- {l['id']} {l['name']}: {l['look']}" for l in t['locations']]
    o += ['', f"**Chorus motif:** {t['chorus_motif']['image']}"] + [f"  {i+1}. {e}" for i, e in enumerate(t['chorus_motif']['escalation'])]
    o += ['', f"**Opening image:** {t['opening_image']}", f"**Final image:** {t['final_image']}", '', '**Facts dramatised:**']
    o += [f"- {f['fact']}  _(source: {f['source']})_" for f in t['facts']]
    return '\n'.join(o) + '\n'


def board_md(res):
    o = [f"# Storyboard draft - {res['title']}\n", '(before audio; the final shot list is written by the slopcore '
         'planner from this treatment + the word timings)\n']
    for b in res['storyboard']:
        o.append(f"## {b['section']} - {b['location']}" + (f" ({b.get('light')})" if b.get('light') else ''))
        o.append(f"_{b['beat']}_  cast: {', '.join(b.get('cast') or [])}")
        o += [f"{i+1}. {s}" for i, s in enumerate(b['shots'])] + ['']
    o.append('## Pip cameos'); o += [f"- {p}" for p in res.get('pip') or []]
    o.append('\n## Diegetic text'); o += [f"- \"{d['text']}\" - {d['where']} ({d['section']})" for d in res.get('diegetic_text') or []]
    n = sum(len(b['shots']) for b in res['storyboard'])
    o.append(f"\n{n} shots drafted.")
    return '\n'.join(o) + '\n'


def write(src, out):
    os.makedirs(out, exist_ok=True)
    for f in ('stories.md', 'sources.txt'):
        if os.path.exists(os.path.join(src, f)) and os.path.abspath(src) != os.path.abspath(out):
            shutil.copyfile(os.path.join(src, f), os.path.join(out, f))
    od = os.path.join(out, 'work_narrative'); os.makedirs(od, exist_ok=True)
    tpl = open(os.path.join(HERE, 'prompts', 'narrative_writer.txt')).read()
    pf = os.path.join(od, 'prompt.txt')
    open(pf, 'w').write(tpl.replace('{{STORIES}}', stories_block(out)))
    try:
        res, meta = SO.run_claude(pf, od, SCHEMA, 900, tools='', effort='high')
    except Exception as e:
        print(f"NARRATIVE_STATUS=failed code=3 reason={e!r}"[:400]); return 3
    json.dump(res, open(os.path.join(od, 'reply_1.json'), 'w'), indent=1)
    print(f"opus: {meta['secs']}s ${meta.get('cost_usd')}")
    for attempt in range(2):
        lp = os.path.join(out, 'lyrics.txt')
        open(lp, 'w').write(res['lyrics'].strip() + '\n')
        open(os.path.join(out, 'style.txt'), 'w').write(SL.fix(res['style']).strip() + '\n')  # density lint reads BPM/metre
        ok, msg = lint(lp)
        probs = check_lyrics(res['lyrics'], res['title']) + ([] if ok else [f"lint: {msg}"])
        if not probs or attempt == 1:
            break
        print('repair:', probs)
        rf = os.path.join(od, 'repair.txt')
        open(rf, 'w').write("Fix ONLY these problems in the lyrics of this song package (keep the story, treatment and "
                            "everything else; rewrite flagged lines keeping the meter) and return the whole JSON:\n- "
                            + '\n- '.join(probs) + "\n\nThe lint rules: no 'AI news'/news/headline/meta lines; no instrument, "
                            "genre or production words in sung lines. Density problems: TRIM - cut whole lines and filler, shorten flagged "
                            "lines, never add lines.\n\nPACKAGE:\n" + json.dumps(res))
        try:
            res, meta = SO.run_claude(rf, od, SCHEMA, 600, tools='', effort='medium')
        except Exception as e:
            print(f"repair failed: {e!r}"[:300]); break
    res['style'] = SL.fix(res['style'])  # 16 Oct: no autotune/vocoder, no jingles
    open(os.path.join(out, 'style.txt'), 'w').write(res['style'].strip() + '\n')
    open(os.path.join(out, 'title.txt'), 'w').write(res['title'].strip() + '\n')
    json.dump(res, open(os.path.join(out, 'treatment.json'), 'w'), indent=1, ensure_ascii=False)
    open(os.path.join(out, 'treatment.md'), 'w').write(md(res, None))
    open(os.path.join(out, 'storyboard_draft.md'), 'w').write(board_md(res))
    ok, msg = lint(os.path.join(out, 'lyrics.txt'))
    probs = check_lyrics(res['lyrics'], res['title'])
    json.dump({'mode': 'narrative', 'lint_ok': ok, 'problems': probs}, open(os.path.join(out, 'narrative.json'), 'w'))
    print(f"NARRATIVE_STATUS={'ok' if ok else 'lint_failed'} code={0 if ok else 1} out={out} title={res['title']!r} "
          f"warnings={probs}")
    return 0 if ok else 1


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2 or a[0] != 'write':
        print(__doc__); sys.exit(2)
    out = a[a.index('--out') + 1] if '--out' in a else a[1]
    sys.exit(write(a[1], out))
