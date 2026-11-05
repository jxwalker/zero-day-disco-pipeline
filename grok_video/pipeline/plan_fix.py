"""Plan fix: mouths-closed story default; SING only with explicit opt-in.

Watch Me rule: NO FAUX-SINGING. Production failure: GV_PLAN_FIX + SING_SHARE rewrote
action scenes into SING wrappers (~34% of PTP). Story mode defaults to SING share 0;
reliable singing requires GV_SING=1 (or sing_enabled=True) and dedicated HERO shots.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence

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

MOUTH_CLOSED = (
    'Mouth closed; no singing, no lip-sync, no faux-singing — '
    'performance is gesture, gaze, and action.'
)


def singing_opt_in() -> bool:
    """Reliable singing is opt-in only (GV_SING=1). Default story mode = mouths closed."""
    return os.environ.get('GV_SING', '0') == '1'


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


def fix_scene_singing(scene: dict, *, allow_sing: bool = False) -> dict:
    """Return a copy with SING policy applied.

    When ``allow_sing`` is False (story default), all SING is stripped and mouths-closed
    steers are applied. When True, SING is kept only on dedicated HERO performance shots.
    """
    sc = dict(scene)
    prompt = sc.get('prompt') or ''
    if not allow_sing:
        if SING_TAG.search(prompt) or SING_WRAPPER.search(prompt) or SING_HINT.search(prompt) \
                or _explicit_sing_role(sc):
            sc['prompt'] = strip_sing_wrapper(prompt)
            motion = sc.get('motion') or ''
            if SING_HINT.search(motion):
                sc['motion'] = strip_sing_wrapper(motion)
            # Demote sing roles so later stages do not re-inject singing instructions
            if str(sc.get('role') or '').lower() in ('sing', 'singing', 'lipsync', 'performance'):
                sc['role'] = 'performance_closed'
            tags = str(sc.get('tags') or '')
            if re.search(r'SING', tags, re.I):
                sc['tags'] = re.sub(r'\[?SING\]?', '', tags, flags=re.I).strip(' ,|')
            sc['_sing'] = False
            sc['_sing_stripped'] = True
            sc['mouths_closed'] = True
            if 'mouth closed' not in (sc.get('prompt') or '').lower():
                sc['prompt'] = ((sc.get('prompt') or '').rstrip('.') + '. ' + MOUTH_CLOSED).strip()
            return sc
        sc['_sing'] = False
        sc['mouths_closed'] = True
        if 'mouth closed' not in prompt.lower() and 'no singing' not in prompt.lower():
            sc['prompt'] = (prompt.rstrip('.') + '. ' + MOUTH_CLOSED).strip() if prompt else MOUTH_CLOSED
        return sc

    # allow_sing=True: keep dedicated sing shots; strip from action/robot
    if not (SING_TAG.search(prompt) or SING_WRAPPER.search(prompt) or SING_HINT.search(prompt)):
        sc['_sing'] = False
        return sc
    if _explicit_sing_role(sc) or (is_singing_shot(sc) and not is_action_or_robot_shot(sc)):
        sc['_sing'] = True
        return sc
    sc['prompt'] = strip_sing_wrapper(prompt)
    motion = sc.get('motion') or ''
    if SING_HINT.search(motion) and is_action_or_robot_shot(sc):
        sc['motion'] = strip_sing_wrapper(motion)
    sc['_sing'] = False
    sc['_sing_stripped'] = True
    return sc


def fix_plan_singing(plan: dict,
                     *,
                     sing_share: float = 0.0,
                     sing_enabled: Optional[bool] = None) -> dict:
    """Fix a plan (returns new dict). Story default: strip all SING unless opted in.

    ``sing_share`` is ignored as a rewrite quota — singing is never forced onto scenes
    to hit a ratio. Opt in with ``sing_enabled=True`` or ``GV_SING=1``.
    """
    allow = singing_opt_in() if sing_enabled is None else bool(sing_enabled)
    # sing_share > 0 alone must NOT enable singing in story mode (PTP regression).
    # Only explicit GV_SING / sing_enabled opts in.
    out = dict(plan)
    scenes: List[dict] = [fix_scene_singing(s, allow_sing=allow) for s in (plan.get('scenes') or [])]
    out['scenes'] = scenes
    stripped = [s['id'] for s in scenes if s.get('_sing_stripped')]
    singing = [s['id'] for s in scenes if s.get('_sing')]
    out['plan_fix'] = {
        'sing_stripped': stripped,
        'singing_shots': singing,
        'sing_share_ignored': sing_share,
        'sing_enabled': allow,
        'performance_mode': 'sing' if allow else 'mouths_closed',
        'note': (
            'SING opt-in (GV_SING=1) on dedicated HERO shots only'
            if allow else
            'Story default: mouths closed; SING stripped (Watch Me rule); set GV_SING=1 to enable'
        ),
    }
    out['performance_mode'] = 'sing' if allow else 'mouths_closed'
    lines = []
    for ln in plan.get('lines') or []:
        ln = dict(ln)
        lines.append(ln)
    out['lines'] = lines
    return out


def singing_scene_ids(scenes: Sequence[dict]) -> List[str]:
    return [str(s['id']) for s in scenes if s.get('_sing') or is_singing_shot(s)]


def assert_zero_sing(plan: dict) -> None:
    """Dry-run helper: story-mode plans must have zero SING after fix_plan_singing."""
    from .failures import FailureKind, JobFailure
    singing = singing_scene_ids(plan.get('scenes') or [])
    # After mouths-closed fix, _sing should be false; also ban leftover [SING] tags
    leftover = []
    for sc in plan.get('scenes') or []:
        blob = f"{sc.get('prompt', '')} {sc.get('tags', '')}"
        if SING_TAG.search(blob) or sc.get('_sing'):
            leftover.append(sc.get('id'))
    if leftover or singing:
        raise JobFailure(
            kind=FailureKind.SING,
            message=f'story mode requires zero SING; found {leftover or singing}',
            stage='sing_policy',
            hint='Default is mouths closed; set GV_SING=1 only for reliable singing shots.',
            details={'singing': leftover or singing},
        )
