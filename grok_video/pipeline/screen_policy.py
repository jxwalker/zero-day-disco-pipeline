"""Screen-check policy: robots / cast / blank terminals must not die via ``other_problem``.

Production failure: catch-all ``other_problem`` deleted every GROK/CLAUDE/GPT/OVERSEER shot
and the founder's gadget (twist 2). Garbled readable gen-text still fails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Set

# Cast / prop tokens that may appear in screen_check issue strings for story shots.
CAST_TOKENS = (
    'robot', 'android', 'grok', 'claude', 'gpt', 'overseer', 'faction',
    'mascot', 'toy character',
)
TERMINAL_TOKENS = (
    'terminal', 'monitor', 'screen', 'display', 'handheld', 'gadget', 'device',
    'phone', 'laptop', 'hud', 'rack',
)
BLANK_DARK = re.compile(
    r'\b(blank|dark|unlit|off|empty|no (?:text|content|ui|readable))\b', re.I,
)
GARBLED_TEXT = re.compile(
    r'\b(garbled|gibberish|readable text|mirrored text|upside[- ]down text|generated text)\b', re.I,
)
DUPLICATE_FRAME = re.compile(r'\b(stacked|duplicate|two copies)\b', re.I)
BAD_HANDS = re.compile(r'\b(malformed hands?|extra (?:hand|finger)|melted hands?)\b', re.I)


@dataclass
class ScreenVerdict:
    ok: bool
    waived: bool
    reason: str
    raw_issue: str = ''

    def to_dict(self) -> dict:
        return {'ok': self.ok, 'waived': self.waived, 'reason': self.reason, 'raw_issue': self.raw_issue}


def waive_other_problem(issue: str, *, allow_cast: bool = True,
                        allow_blank_terminals: bool = True) -> Optional[str]:
    """Return a waiver reason if ``other_problem`` should NOT reject, else None."""
    text = (issue or '').strip()
    if not text:
        return 'empty_issue'
    low = text.lower()
    # Garbled readable gen-text ALWAYS fails — never waive.
    if GARBLED_TEXT.search(text) and not BLANK_DARK.search(text):
        return None
    if DUPLICATE_FRAME.search(text) or BAD_HANDS.search(text):
        return None
    if allow_cast and any(tok in low for tok in CAST_TOKENS):
        # "Robot/android is the main subject" / "Two robots..." — story may require this.
        if GARBLED_TEXT.search(text):
            return None
        return 'cast_or_robot_subject'
    if allow_blank_terminals and any(tok in low for tok in TERMINAL_TOKENS):
        # Founder gadget / blank terminal facing camera is OK when content is blank/dark
        # OR the issue is only that a device screen faces camera (content will be composited).
        if GARBLED_TEXT.search(text) and not BLANK_DARK.search(text):
            return None
        if BLANK_DARK.search(text) or 'faces the camera' in low or 'facing the camera' in low:
            return 'blank_or_story_device'
        # Device present without garbled text → allow; overlay will draw content.
        return 'device_for_overlay'
    return None


def evaluate_screen_result(result: dict, *,
                           story_critical: bool = False,
                           allow_cast: bool = True,
                           allow_blank_terminals: bool = True) -> ScreenVerdict:
    """Apply hard screen geometry rules + other_problem waiver policy.

    Geometry rejects (lid-back screens, wrong-facing, laptops) still fail unless
    the shot is story-critical AND the only soft flag is ``other_problem``.
    """
    issue = str(result.get('issue') or '')
    geometry_fail = bool(
        (result.get('user_faces_camera_behind_device') and result.get('display_visible_to_camera'))
        or result.get('laptop_present')
        or result.get('screen_on_outer_lid')
        or result.get('screen_not_facing_camera')
    )
    other = bool(result.get('other_problem'))
    if geometry_fail and not (story_critical and not (
            result.get('laptop_present') or result.get('screen_on_outer_lid'))):
        # Story-critical handheld gadget: allow screen_not_facing / user_faces if tagged.
        if story_critical and not result.get('laptop_present') and not result.get('screen_on_outer_lid'):
            return ScreenVerdict(True, True, 'story_critical_device_geometry', issue)
        return ScreenVerdict(False, False, 'geometry', issue)
    if other:
        waiver = waive_other_problem(issue, allow_cast=allow_cast,
                                     allow_blank_terminals=allow_blank_terminals)
        if waiver:
            return ScreenVerdict(True, True, waiver, issue)
        if story_critical:
            # Never silently delete twist/payoff for a soft other_problem.
            return ScreenVerdict(True, True, 'story_critical_soft_other', issue)
        return ScreenVerdict(False, False, 'other_problem', issue)
    return ScreenVerdict(True, False, 'pass', issue)


def filter_rejections(results: dict, *,
                      critical_ids: Optional[Iterable[str]] = None,
                      allow_cast: bool = True) -> tuple[Set[str], dict]:
    """Return (rejected_ids, per_id verdicts) after applying the waiver policy."""
    crit = {str(x) for x in (critical_ids or [])}
    bad: Set[str] = set()
    verdicts = {}
    for sid, raw in (results or {}).items():
        v = evaluate_screen_result(raw, story_critical=sid in crit, allow_cast=allow_cast)
        verdicts[sid] = v.to_dict()
        if not v.ok:
            bad.add(sid)
    return bad, verdicts
