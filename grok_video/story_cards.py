"""Story cards (P7, the owner 12 Oct): each verse section gets 1-2 short news cards tied to the story being sung there:
a real @handle or company + the key number/fact + a 3-6 word headline ("B300 RENTALS +38%", "@morluto REA: 100K
STARS"), timed to the lyric line about that story. Opus writes them from stories.md ONLY; every word, number and handle
on a card is checked against stories.md (spelling included) and a card that fails the check is dropped. Chorus slams stay
the hook words. Fail-open: any error -> no cards (the old verse slams are used)."""
import json, os, re, tempfile, time
import common_gv as G
import real_plan as RP

SCHEMA = {"type": "object", "properties": {"cards": {"type": "array", "items": {"type": "object", "properties": {
    "line": {"type": "string", "description": "lyric line id exactly as given (the line that sings this story)"},
    "story": {"type": "integer"},
    "tag": {"type": "string", "description": "the real @handle or company from stories.md, e.g. @morluto or META"},
    "headline": {"type": "string", "description": "3-6 words, CAPS, the key number or fact, e.g. B300 RENTALS +38%"}},
    "required": ["line", "story", "tag", "headline"]}}}, "required": ["cards"]}
GLUE = {'a', 'an', 'the', 'of', 'in', 'on', 'to', 'vs', 'for', 'by', 'at', 'is', 'up', 'and', 'from', 'with', 'no', 'one',
        'two', 'new', 'now', 'top', 'its', 'it',
        # ticker words (never names or numbers, those must come from stories.md)
        'nearly', 'almost', 'over', 'under', 'hits', 'tops', 'up', 'down', 'days', 'weeks', 'months', 'week', 'day',
        'month', 'says', 'vs.', 'just', 'than', 'more', 'less', 'only', 'all'}
MAX_PER_SECTION = 2
MIN_GAP_S = 3.0


def _norm(s):
    return re.sub(r'[^a-z0-9%@#+.$]+', ' ', s.lower().replace(',', ''))


def check_card(c, md, lyrics=''):
    """Every token must come from stories.md: handles verbatim, numbers verbatim (100K = 100k), words spelled as in it."""
    text = f"{c.get('tag', '')} {c.get('headline', '')}"
    nh = len(c.get('headline', '').split())
    if not (2 <= nh <= 6) or len(c.get('headline', '')) > 32 or len(c.get('tag', '')) > 20:
        return 'length'
    low, toks = md.lower().replace(',', ''), set(_norm(md).split())
    facts = re.sub(r'https?://\S+', ' ', re.sub(r'(?m)^##\s*\d+\.', '##', md)).lower().replace(',', '')   # numbers: no ids/list nos
    for raw in re.split(r'[\s:/]+', text.replace('"', ' ').replace("'", ' ')):
        t = raw.strip('.,;:!?"\'()').lower()
        if not t or t in GLUE or t in ('-', '+', '→', '·', '|', '&'):
            continue
        if t.startswith('@'):
            if t not in low and t[1:] + '/status' not in low and t[1:] not in low:
                return f'handle {raw}'
            continue
        core = t.lstrip('+#$').rstrip('%')
        if re.search(r'\d', core):
            words = {'1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eight',
                     '9': 'nine', '10': 'ten', '14': 'fourteen', '100k': '100,000'}
            hit = re.search(r'(?<![\d.])' + re.escape(core) + r'(?![\d])', facts) or \
                (core in words and re.search(r'\b' + words[core] + r'\b', md.lower()))
            if not hit:
                return f'number {raw}'
            continue
        lyr = set(_norm(lyrics).split())
        if t not in toks and t.rstrip('s') not in toks and t not in low and t not in lyr:
            return f'word {raw}'
    return None


def make(day, work, L, deadline=None, timeout=150):
    """Returns {line_id: {'tag','headline','story'}} (possibly empty). Writes work/story_cards.json."""
    out_p = os.path.join(work, 'story_cards.json')
    if os.environ.get('GV_STORY_CARDS') == '0':
        return {}
    try:
        cached = G.load_json(out_p)
        if isinstance(cached, dict) and cached.get('cards') is not None:
            return cached['cards']
        md = G.read(os.path.join(day, 'stories.md'))
        if not md.strip():
            return {}
        if deadline and deadline - time.time() < 20 * 60:
            G.log("story cards: skipped (not enough time before the limit)")
            return {}
        if os.environ.get('GV_STORY_CARDS_FAIL'):
            raise RuntimeError('forced test failure (GV_STORY_CARDS_FAIL)')
        sung = [ln for ln in L if ln.get('words') or ln.get('text')]
        rows = [f"{RP.line_id(ln)} [{ln.get('kind')}] {ln.get('text') or ' '.join(w[0] for w in ln['words'])}"
                for ln in sung if ln.get('kind') in ('verse', 'bridge', 'pre', 'prechorus', 'pre-chorus')]
        if not rows:
            return {}
        prompt = f"""You write on-screen NEWS CARDS for an AI-news music video. Use ONLY facts from STORIES below; never
invent or round a number, never invent a handle, spell every name exactly as STORIES does.
For each verse section give 1 or {MAX_PER_SECTION} cards. Put each card on the lyric line that sings that story (the
first line where the story's fact is sung). "tag": the real @handle (as written in STORIES or its x.com URLs) or the
company/product name. "headline": 3-6 words (max 30 characters) in CAPS with the key number or fact, using only words that appear in STORIES or the
lyrics, punchy like a news ticker:
"B300 RENTALS +38%", "REA: 100K STARS", "MEMO TO DEMO: 2 WEEKS". Numbers must appear in STORIES exactly as digits or
words (write "100K" only if STORIES says 100k). No line may get two cards.

STORIES (stories.md):
{md[:9000]}

VERSE LINES (id [kind] text):
{chr(10).join(rows)}

Reply with JSON only: {{"cards": [{{"line": "...", "story": 1, "tag": "...", "headline": "..."}}]}}"""
        import slop_opus as SO
        od = os.path.join(work, 'opus'); os.makedirs(od, exist_ok=True)
        pf = os.path.join(od, 'cards_prompt.txt'); open(pf, 'w').write(prompt)
        tmo = timeout if not deadline else max(30, min(timeout, deadline - time.time() - 18 * 60))
        res, meta = SO.run_claude(pf, od, SCHEMA, tmo, tools='', effort='low')
        ids = {RP.line_id(ln): ln for ln in sung}
        cards, per_sec, dropped = {}, {}, []
        for c in (res or {}).get('cards') or []:
            lid = str(c.get('line', '')).strip()
            ln = ids.get(lid)
            why = 'unknown line' if not ln else ('duplicate line' if lid in cards else check_card(c, md, G.read(os.path.join(day, 'lyrics.txt'))))
            sec = (ln or {}).get('section'), (ln or {}).get('section_occ')
            if not why and per_sec.get(sec, 0) >= MAX_PER_SECTION:
                why = 'section full'
            if why:
                dropped.append({'card': c, 'why': why}); continue
            per_sec[sec] = per_sec.get(sec, 0) + 1
            cards[lid] = {'tag': c['tag'].strip().upper() if not c['tag'].strip().startswith('@') else c['tag'].strip(),
                          'headline': c['headline'].strip().upper(), 'story': c.get('story')}
        G.save_json({'cards': cards, 'dropped': dropped, 'secs': meta.get('secs')}, out_p)
        G.log(f"story cards: {len(cards)} cards ({len(dropped)} dropped by the stories.md check) in {meta.get('secs')}s")
        return cards
    except Exception as e:                                  # fail-open: the run never breaks for cards
        G.log(f"WARNING: story cards skipped: {e!r}"[:300])
        return {}


def director_note(cards):
    """Appended to the director's STORIES block: which line sings which story, so those shots show that story."""
    if not cards:
        return ''
    rows = '\n'.join(f"- {lid}: story {c.get('story')} -> on-screen card \"{c['tag']} {c['headline']}\"" for lid, c in cards.items())
    return ("\n\nNEWS CARDS (these lines carry an on-screen news card; their shots must show THAT story literally, with "
            "its real objects, numbers and setting, so the card, the words and the picture say the same thing; do not "
            "put text in the pictures, the card is added in the edit):\n" + rows)
