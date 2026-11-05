"""Per-character identity / reference routing and duplicate-lead QC.

Production failure: GV_FARM_LOCK="Same person as the first frame" + HERO-first refs
turned every cast member into a Vex clone; OVERSEER sheet loaded into scenes she
wasn't in; SING wrapper on action shots.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .plan_fix import is_singing_shot

CHAR_TOKEN = re.compile(
    r'\[(?P<tag>HERO|LEAD|GROK|CLAUDE|GPT|OVERSEER|PIP|[A-Z][A-Z0-9_]{1,20})\]'
    r'|\b(?P<name>grok|claude|gpt|overseer|vex|pip)\b',
    re.I,
)


@dataclass
class CharacterRefs:
    """Maps character id -> reference image path(s). Never cross-wire refs."""
    refs: Dict[str, List[str]] = field(default_factory=dict)
    lock_same_as_first_frame: bool = False  # MUST stay False for multi-character stories

    def add(self, character: str, path: str) -> None:
        key = character.strip().upper()
        self.refs.setdefault(key, [])
        if path not in self.refs[key]:
            self.refs[key].append(path)

    def for_character(self, character: str) -> List[str]:
        return list(self.refs.get(character.strip().upper(), []))


def characters_in_prompt(prompt: str) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for m in CHAR_TOKEN.finditer(prompt or ''):
        tag = (m.group('tag') or m.group('name') or '').upper()
        if tag and tag not in seen:
            seen.add(tag); found.append(tag)
    return found


def ref_images_for_scene(scene: dict, cast: CharacterRefs) -> List[str]:
    """Return only the reference images for characters present in this scene.

    Never falls back to 'first frame' / HERO lock for robot or non-lead casts.
    """
    prompt = scene.get('prompt') or ''
    role = str(scene.get('role') or '').upper()
    chars = characters_in_prompt(prompt)
    if scene.get('cast'):
        for c in scene['cast']:
            cu = str(c).upper()
            if cu not in chars:
                chars.append(cu)
    if role and role not in chars and role in cast.refs:
        chars.append(role)
    paths: List[str] = []
    for c in chars:
        for p in cast.for_character(c):
            if p not in paths:
                paths.append(p)
    # Single-lead human scene with no explicit tag: allow LEAD/HERO refs only.
    if not paths and not any(c in ('GROK', 'CLAUDE', 'GPT', 'OVERSEER') for c in chars):
        for key in ('LEAD', 'HERO'):
            for p in cast.for_character(key):
                if p not in paths:
                    paths.append(p)
    return paths


def singing_allowed(scene: dict) -> bool:
    """Singing instructions only on dedicated singing shots."""
    return is_singing_shot(scene)


def singing_instruction(scene: dict, line_text: str = '') -> str:
    if not singing_allowed(scene):
        return ''
    line = (line_text or scene.get('line') or '').strip()
    if line:
        return f'singing this line clearly to camera: "{line}"'
    return 'singing clearly to camera'


def duplicate_lead_flags(detections: Sequence[dict],
                         *, lead_ids: Optional[Iterable[str]] = None) -> List[dict]:
    """QC: flag frames where the lead identity appears more than once.

    ``detections`` items: ``{frame|shot_id, identities: [str, ...]}`` (identity labels
    from a vision checker). Returns a list of flag dicts.
    """
    leads = {x.upper() for x in (lead_ids or ('LEAD', 'HERO', 'VEX'))}
    flags = []
    for det in detections:
        ids = [str(x).upper() for x in (det.get('identities') or [])]
        lead_hits = [i for i in ids if i in leads or i.startswith('LEAD')]
        # Also count exact duplicate labels (two "VEX")
        counts: Dict[str, int] = {}
        for i in ids:
            counts[i] = counts.get(i, 0) + 1
        dupes = {k: v for k, v in counts.items() if v > 1 and (k in leads or k.startswith('LEAD') or k == 'VEX')}
        if len(lead_hits) > 1 or dupes:
            flags.append({
                'shot_id': det.get('shot_id') or det.get('frame'),
                'identities': ids,
                'issue': 'duplicate_lead',
                'detail': f'lead appears {max(len(lead_hits), max(dupes.values(), default=0))} times in frame',
            })
    return flags


def farm_lock_suffix(scene: dict, cast: CharacterRefs) -> str:
    """Optional short lock for THIS scene's characters only. Never a global kitchen/cardigan lock."""
    chars = characters_in_prompt(scene.get('prompt') or '')
    if not chars:
        return ''
    if any(c in ('GROK', 'CLAUDE', 'GPT', 'OVERSEER') for c in chars):
        # Robots: identity from their own ref sheet, not "same person as first frame".
        return 'Match the reference sheet for this character only; do not reuse other cast faces.'
    if cast.lock_same_as_first_frame:
        # Explicitly refused for multi-character; keep behaviour opt-in and narrow.
        return 'Same person as the reference image for this shot only.'
    return 'Match the reference image for this character only.'
