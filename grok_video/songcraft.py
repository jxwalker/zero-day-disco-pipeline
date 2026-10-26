#!/usr/bin/env python3
"""Songcraft: every song follows one common thread, the chorus is a pun/crossover with real life, and an Opus
judge reviews the lyrics strictly.

1. concepts(): Opus pitches 5 one-thread concepts, each built on an everyday phrase that is true in real life AND in
   the tech story. A second, independent Opus call scores them and picks one -> work_headline/concept.json.
2. judge(): a strict independent Opus lyric judge with an 8-item rubric. pass = every item >= MIN and mean >= MEAN.
   headline.py rewrites up to HL_JUDGE_ROUNDS times with the judge's must-fix list and logs every score."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import slop_opus as SO

S = {"type": "string"}; I = {"type": "integer"}
RUBRIC = ['single_story_focus', 'normie_test', 'pun_strength', 'hook_clarity', 'story_arc', 'specificity', 'quotability',
          'singability', 'tiktok_first3s']
MIN = int(os.environ.get('HL_JUDGE_MIN', 8)); MEAN = float(os.environ.get('HL_JUDGE_MEAN', 8.5))

CONCEPT = {"type": "object", "properties": {
    "phrase": S, "real_life_meaning": S, "tech_meaning": S, "thread": S, "persona": S, "stories": {"type": "array", "items": I},
    "arc_v1": S, "arc_v2": S, "arc_breakdown": S, "final_flip": S, "first_3s_visual": S, "quotable_line": S,
    "comment_prompt": S, "lead_visual": S},
    "required": ["phrase", "real_life_meaning", "tech_meaning", "thread", "persona", "stories", "arc_v1", "arc_v2",
                 "arc_breakdown", "final_flip", "first_3s_visual", "quotable_line", "comment_prompt", "lead_visual"]}
PITCH_SCHEMA = {"type": "object", "properties": {"concepts": {"type": "array", "items": CONCEPT}}, "required": ["concepts"]}
PICK_SCHEMA = {"type": "object", "properties": {
    "scores": {"type": "array", "items": {"type": "object", "properties": {
        "i": I, "pun_strength": I, "real_life_truth": I, "thread_fit": I, "normie": I, "news_clarity": I, "tiktok": I, "note": S},
        "required": ["i", "pun_strength", "real_life_truth", "thread_fit", "normie", "news_clarity", "tiktok", "note"]}},
    "chosen": I, "why": S, "sharpen": S}, "required": ["scores", "chosen", "why", "sharpen"]}
JUDGE_SCHEMA = {"type": "object", "properties": {
    "scores": {"type": "object", "properties": {k: I for k in RUBRIC}, "required": RUBRIC},
    "line_notes": {"type": "array", "items": {"type": "object", "properties": {"line": S, "problem": S, "fix": S},
                                               "required": ["line", "problem", "fix"]}},
    "must_fix": {"type": "array", "items": S}, "verdict": S}, "required": ["scores", "line_notes", "must_fix", "verdict"]}

CRAFT = """CRAFT RULES (from the research brief; these are what make a hit, not decoration):
- ONE THREAD: the whole song is ONE scenario told by ONE persona. If more than one story is used, the extra stories are
  new events INSIDE the same scenario (verse 2 = "then what happened?"), never a new topic.
- THE PUN: the title is an everyday phrase people already say in real life (a flirt, a breakup line, an excuse, an
  office phrase, a parent's line) that is ALSO literally true of the tech story. Example: a data
  centre dressed up and stood up, waiting for grid power: a flirty "switch me on" line = power on AND a flirt.
  Weak = a tech pun only geeks get, or a phrase that is true of only one side.
- THE CHORUS TURN: the chorus words stay identical but mean something new after each verse; the final chorus swaps
  ONE word so the pun flips (the quotable callback).
- ARC: V1 setup (who, what, the key fact, a concrete image) -> V2 escalation of the same situation -> breakdown =
  confession / low point / geeky deep cut -> final chorus flip. The last line before each chorus hands into the title.
- SPECIFIC: concrete nouns, places, actions and one real number; show, don't tell.
- PROSODY: stressed syllables on the beat, title words on long open vowels, short plain words, singable by a crowd.
- TIKTOK: the first sung line (0-3 s) already tells a stranger what this is and is chantable; one cheeky quotable line
  people would caption a video with; an end that loops back to the start; a natural comment question (A or B, whose
  side are you on) - never fake or false bait.
- Facts, numbers and @handles only from TODAY'S STORIES. PG-13 flirty, never crude. No robots."""


def _run(pf, od, schema, t, effort='high'):
    res, meta = SO.run_claude(pf, od, schema, t, tools='', effort=effort)
    print(f"songcraft {os.path.basename(pf)}: {meta['secs']}s ${meta.get('cost_usd')}")
    return res


def concepts(stories_md, od):
    pf = os.path.join(od, 'concept_pitch.txt')
    open(pf, 'w').write(
        "You are a top-line pop songwriter in a writers' room pitching today's song for the owner's daily AI-news song on X "
        "(bright pop, female lead, 2:30, viral-hit format).\n\n" + CRAFT +
        "\n\nPitch 5 DIFFERENT concepts. ONE MAIN STORY per song: pick the single strongest story; other stories "
        "may appear only as one passing line if they live in the same scenario. The chorus hook must be a MAINSTREAM "
        "CROSSOVER: an inside joke for tech people that ALSO makes sense and is fun for someone who never heard the story "
        "(the standard: a flirty power-on line for a data centre waiting on grid power). For each give the title phrase, what it means in real life, what it means in the tech story, the "
        "one-line thread, the persona singing, the story numbers used, the arc beats (v1, v2, breakdown, final flip = the "
        "one-word swap and what it flips to), the first-3-seconds visual, the quotable line, a comment prompt, and the lead "
        "character's visual (an original woman aged 21-28, a manic-pixie indie engineer; no real people).\n\n"
        "TODAY'S STORIES:\n" + stories_md + "\n\nReply with the JSON only.")
    pitch = _run(pf, od, PITCH_SCHEMA, 600)
    cs = pitch['concepts']
    jf = os.path.join(od, 'concept_pick.txt')
    open(jf, 'w').write(
        "You are a ruthless A&R judge who has signed novelty-pop hits. Score each pitched concept 1-10 on pun_strength "
        "(a double meaning a non-tech person gets instantly and smiles at), real_life_truth (people really say this "
        "phrase), thread_fit (ONE main story holds the whole song; multi-story pitches max 5), normie (would someone who never heard the story get and enjoy the hook? must be >= 8 to pick), news_clarity (a stranger can name the story) and "
        "tiktok (scroll-stop + quotable + loop). Reference point: a flirty power-on line for a data centre waiting on grid power = 9-10 "
        "pun. Be harsh; 8 means it would really work. Pick the best (index i from 0), say why, and give one 'sharpen' "
        "note that would make it better.\n\n" + CRAFT + "\n\nTODAY'S STORIES:\n" + stories_md + "\n\nCONCEPTS:\n" +
        json.dumps([dict(c, i=i) for i, c in enumerate(cs)], indent=1, ensure_ascii=False))
    pick = _run(jf, od, PICK_SCHEMA, 420)
    ch = max(0, min(len(cs) - 1, int(pick.get('chosen', 0))))
    out = {'concepts': cs, 'pick': pick, 'chosen': cs[ch]}
    json.dump(out, open(os.path.join(od, 'concept.json'), 'w'), indent=1, ensure_ascii=False)
    return out


def concept_block(c, sharpen=''):
    k = c['chosen'] if 'chosen' in c else c
    return ("TODAY'S CONCEPT (chosen by the writers' room and A&R; write THIS song, do not pick a different angle):\n"
            f"- Title phrase / chorus pun: {k['phrase']}\n- Real-life meaning: {k['real_life_meaning']}\n"
            f"- Tech meaning: {k['tech_meaning']}\n- One thread: {k['thread']}\n- Persona: {k['persona']}\n"
            f"- Stories used: {k['stories']} (sing ONLY these; main_story = the first)\n- V1: {k['arc_v1']}\n- V2: {k['arc_v2']}\n"
            f"- Breakdown: {k['arc_breakdown']}\n- Final chorus flip: {k['final_flip']}\n- First 3 s visual: {k['first_3s_visual']}\n"
            f"- Quotable line idea: {k['quotable_line']}\n- Lead: {k['lead_visual']}\n"
            + (f"- A&R sharpen note: {sharpen}\n" if sharpen else '') + "\n" + CRAFT)


JAMES_RULES = ("HOUSE RULES:\n"
    "- A singable natural line beats an exact number, handle or stat. Never ask to add a number/handle that cramps a line; "
    "a real number counts for specificity only if it sings naturally.\n"
    "- The video must be filmable with NO device screens, phones, laptops or tablets on screen. Never ask to add them; "
    "penalise (specificity/thread) lyrics whose story needs a phone/laptop/screen to be seen. Wearables, earbuds, smart "
    "speakers, voices and objects are fine.\n"
    "- The second chorus must vary from the first (new 2nd/3rd lines that move the story); identical = story_arc max 6.\n"
    "- The opener must tell a stranger the premise in under 3 s; unclear = hook_clarity and tiktok_first3s max 6.\n"
    "- The outro must not introduce new facts or switch who did what.\n"
    "- Verses are four lines and form an arc (setup -> incident -> consequence).")


def judge(lyrics, title, concept_txt, stories_md, od, n):
    pf = os.path.join(od, f'judge_{n}.txt')
    open(pf, 'w').write(
        "You are the strictest lyric editor in pop (think a hit-factory topliner plus a TikTok A&R). Judge this song "
        "on its own merits; you did not write it. Score 1-10 each, where 8 = genuinely release-worthy and 10 = hit:\n"
        "- single_story_focus: the song is built on ONE main story, one scenario, one persona; verse 2 escalates the same situation (two or more separate stories = max 5)\n"
        "- normie_test: would someone who has never heard the story get AND enjoy the hook? It must be an inside joke for tech people that also works as a mainstream pop line (a flirty power-on line for a data centre waiting on grid power = 9); needs >= 8\n"
        "- pun_strength: the title works as an everyday real-life phrase AND literally in the tech story; the chorus "
        "turns; the final flip lands (a flirty power-on line for a data centre waiting on power = 9)\n"
        "- hook_clarity: title chant is first, plain, chantable; a stranger names the story after one listen\n"
        "- story_arc: setup -> escalation -> breakdown confession -> flip; trigger lines hand into the chorus\n"
        "- specificity: concrete images, actions and a real number; show not tell; no filler or clichés\n"
        "- quotability: at least one cheeky caption-worthy line\n"
        "- singability: prosody, stresses on beats, short words, no tongue-twisters, fits 124-128 BPM lines\n"
        "- tiktok_first3s: the first sung words stop the scroll and say what it is; ending loops\n"
        f"Pass needs every score >= {MIN} and mean >= {MEAN}. Do not inflate. For every weak line give line/problem/fix "
        "(the fix must keep the line short: max 9 words). must_fix = the few changes that would lift the lowest scores. "
        "Facts must come only from the stories; flag any invented fact.\n\n" + JAMES_RULES + "\n\nINTENDED CONCEPT:\n" + concept_txt +
        "\n\nTODAY'S STORIES:\n" + stories_md + f"\n\nTITLE: {title}\n\nLYRICS:\n{lyrics}\n\nReply with the JSON only.")
    r = _run(pf, od, JUDGE_SCHEMA, 420, effort='high')
    sc = r['scores']; mean = sum(sc[k] for k in RUBRIC) / len(RUBRIC)
    r['mean'] = round(mean, 2); r['pass'] = all(sc[k] >= MIN for k in RUBRIC) and mean >= MEAN
    json.dump(r, open(os.path.join(od, f'judge_{n}.json'), 'w'), indent=1, ensure_ascii=False)
    print(f"songcraft judge {n}: mean={r['mean']} pass={r['pass']} {sc}")
    return r
