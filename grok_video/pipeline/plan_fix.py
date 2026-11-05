"""Plan fix: SING wrappers only on dedicated HERO performance / lip-sync shots.

Production failure: GV_PLAN_FIX + SING_SHARE rewrote action scenes into
"[SING][HERO] front-facing close-up" wrappers, creating contradictory prompts
(red-dress stranger, clones).
"""
from __future__ import annotations

import re
from typing import List, Sequence

SING_TAG = re.compile(r'\[SING\]', re.I)
HERO_TAG = re.compile(r'\[HERO\]', re.I)
SING_WRAPPER = re.compile(
    r'(?:,?\s*)?(?:steady\s+)?front-facing close-up[^.;]{0,80}?'
    r'(?:eyes to (?:the )?lens)?[^.;]{0,40}?'
    r'(?:singing this line)?',
    re.I,
)
ACTION_HINT = re.compile(
    r'\b(slam|yank|rip|pull|tug|punch|throw|knock|pinch|rack|dial|steal|tear|'
    r'wall|button|plug|cable|robot|android|grok|claude|gpt|overseer|action)\b',
    re.I,
)
SING_HINT = re.compile(
    r'\b(sings?|singing|lip[- ]?sync|performance|vocal|chorus close-?up)\b',
    re.I,
)
ROBOT_OR_ID = re.compile(
    r'\b(robot|android|grok|claude|gpt|overseer|\[(?:GROK|CLAUDE|GPT|OVERSEER)\])\b',
    re.I,
)


def is_singing_shot(scene: dict) -> bool:
    """True only for dedicated HERO performance / lip-sync scenes."""
    role = str(scene.get('role') or scene.get('kind') or '').lower()
    tags = str(scene.get('tags') or '').upper()
    prompt = scene.get('prompt') or ''
    sid = str(scene.get('id') or '')
    if role in ('sing', 'singing', 'lipsync', 'performance'):
        return True
    if '[SING]' in tags or sid.startswith('sing_') or '_sing' in sid:
        return True
    # Explicit singing intent without action/robot conflict
    if SING_HINT.search(prompt) and not ACTION_HINT.search(prompt) and not ROBOT_OR_ID.search(prompt):
        if HERO_TAG.search(prompt) or '[HERO]' in tags or role == 'hero':
            return True
    return False


def is_action_or_robot_shot(scene: dict) -> bool:
    prompt = scene.get('prompt') or ''
    role = str(scene.get('role') or '').lower()
    if role in ('action', 'robot', 'id-action', 'insert'):
        return True
    return bool(ACTION_HINT.search(prompt) or ROBOT_OR_ID.search(prompt))


def strip_sing_wrapper(prompt: str) -> str:
    out = SING_TAG.sub('', prompt or '')
    out = SING_WRAPPER.sub('', out)
    out = re.sub(r'\b(?:singing this line|eyes to lens)\b', '', out, flags=re.I)
    return re.sub(r'\s{2,}', ' ', out).strip(' ,;.')


def _explicit_sing_role(scene: dict) -> bool:
    role = str(scene.get('role') or scene.get('kind') or '').lower()
    tags = str(scene.get('tags') or '').upper()
    sid = str(scene.get('id') or '')
    return (
        role in ('sing', 'singing', 'lipsync', 'performance')
        or '[SING]' in tags or tags == 'SING'
        or sid.startswith('sing_') or '_sing' in sid
    )


def fix_scene_singing(scene: dict) -> dict:
    """Return a copy with SING removed from action/robot/id-action scenes."""
    sc = dict(scene)
    prompt = sc.get('prompt') or ''
    if not (SING_TAG.search(prompt) or SING_WRAPPER.search(prompt) or SING_HINT.search(prompt)):
        return sc
    # Dedicated sing roles keep SING even when the lyric text contains action verbs.
    if _explicit_sing_role(sc) or (is_singing_shot(sc) and not is_action_or_robot_shot(sc)):
        sc['_sing'] = True
        return sc
    # Action / robot / id-action: strip singing
    sc['prompt'] = strip_sing_wrapper(prompt)
    motion = sc.get('motion') or ''
    if SING_HINT.search(motion) and is_action_or_robot_shot(sc):
        sc['motion'] = strip_sing_wrapper(motion)
    sc['_sing'] = False
    sc['_sing_stripped'] = True
    return sc


def fix_plan_singing(plan: dict, *, sing_share: float = 0.0) -> dict:
    """Fix a plan in place (returns new dict). ``sing_share`` is ignored as a rewrite quota:
    singing is never forced onto action scenes to hit a ratio.
    """
    out = dict(plan)
    scenes: List[dict] = [fix_scene_singing(s) for s in (plan.get('scenes') or [])]
    out['scenes'] = scenes
    stripped = [s['id'] for s in scenes if s.get('_sing_stripped')]
    singing = [s['id'] for s in scenes if s.get('_sing')]
    out['plan_fix'] = {
        'sing_stripped': stripped,
        'singing_shots': singing,
        'sing_share_ignored': sing_share,
        'note': 'SING only on dedicated HERO performance shots; action/robot never rewritten to sing',
    }
    # Also scrub line visuals that glued SING onto action scene ids
    lines = []
    for ln in plan.get('lines') or []:
        ln = dict(ln)
        lines.append(ln)
    out['lines'] = lines
    return out


def singing_scene_ids(scenes: Sequence[dict]) -> List[str]:
    return [str(s['id']) for s in scenes if s.get('_sing') or is_singing_shot(s)]
