"""Lean scene-state story model — lyric timing captions the film; it does not own structure.

Each beat carries before/action/after world state, role/allegiance/prop continuity, and
optional consequence edges (``requires_next``). This is a small domain model, not a huge FSM.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .failures import FailureKind, JobFailure

# Watch Me–class default complexity. Override with GV_MAX_SCENES.
DEFAULT_MAX_SCENES = int(os.environ.get('GV_MAX_SCENES', '28'))
# Soft lyric-relative cap: scenes may not explode far past lyric line count.
LYRIC_SCENE_RATIO = float(os.environ.get('GV_LYRIC_SCENE_RATIO', '1.2'))

# Structural roles that *are* required climax/twist/payoff (IDs, not keyword hunting).
STRUCTURAL_ROLES = frozenset({
    'twist', 'payoff', 'climax', 'reveal', 'turn', 'final_payoff', 'bookend',
})

# Art style / prop bans that caused PTP clay/cartoon chaos.
ART_BAN_RE = re.compile(
    r'\b(clay|claymation|cartoon|toon|anime|toy|mannequin|puppet|plush|chibi|emoji)\b',
    re.I,
)
# Multiple conflicting plug-scale tokens in one plan → nonsense.
PLUG_SCALE_TOKENS = (
    ('wall_plug', re.compile(r'\b(wall[- ]?plug|outlet plug|tiny plug|household plug)\b', re.I)),
    ('giant_plug', re.compile(r'\b(giant plug|oversized plug|rooftop plug|suitcase[- ]?scale|huge plug)\b', re.I)),
    ('cable_yank', re.compile(r'\b(yank(?:s|ed|ing)? the (?:cable|cord|plug)|pull(?:s|ed|ing)? the plug)\b', re.I)),
)

ACTION_EDGE_HINT = re.compile(
    r'\b(press(?:es|ed|ing)?|slam(?:s|med|ming)?|yank(?:s|ed|ing)?|pull(?:s|ed|ing)?|'
    r'rip(?:s|ped|ping)?|cut(?:s|ting)?|flip(?:s|ped|ping)?|kill[- ]?switch|'
    r'red button|plug|cable)\b',
    re.I,
)

MOUTH_CLOSED_STEER = (
    'Mouth closed; no singing, no lip-sync, no faux-singing — performance is gesture, gaze, and action.'
)


@dataclass
class SceneState:
    """Continuous world state for one beat."""

    scene_id: str
    world_before: Dict[str, Any] = field(default_factory=dict)
    action: str = ''
    world_after: Dict[str, Any] = field(default_factory=dict)
    role: str = ''
    allegiance: str = ''
    prop_state: Dict[str, Any] = field(default_factory=dict)
    requires_next: List[str] = field(default_factory=list)
    structural_role: str = ''

    def to_dict(self) -> dict:
        return {
            'scene_id': self.scene_id,
            'world_before': dict(self.world_before),
            'action': self.action,
            'world_after': dict(self.world_after),
            'role': self.role,
            'allegiance': self.allegiance,
            'prop_state': dict(self.prop_state),
            'requires_next': list(self.requires_next),
            'structural_role': self.structural_role,
        }


@dataclass
class StoryModelReport:
    ok: bool
    issues: List[dict] = field(default_factory=list)
    required_shots: List[str] = field(default_factory=list)
    scene_count: int = 0
    max_scenes: int = DEFAULT_MAX_SCENES
    states: List[dict] = field(default_factory=list)
    summary: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'summary': self.summary, 'issues': self.issues,
            'required_shots': self.required_shots, 'scene_count': self.scene_count,
            'max_scenes': self.max_scenes, 'states': self.states,
            'errors': [i for i in self.issues if i.get('severity') == 'error'],
        }


def _scene_blob(sc: dict) -> str:
    return ' '.join(str(sc.get(k, '')) for k in (
        'id', 'prompt', 'tags', 'role', 'beat', 'motion', 'structural_role', 'action',
    ))


def structural_role_of(sc: dict) -> str:
    """Return normalized structural role from explicit field or legacy tags (compat only)."""
    explicit = str(sc.get('structural_role') or '').strip().lower()
    if explicit in STRUCTURAL_ROLES:
        return explicit
    role = str(sc.get('role') or '').strip().lower()
    if role in STRUCTURAL_ROLES:
        return role
    blob = _scene_blob(sc).upper()
    for tag, mapped in (
        ('FINAL PAYOFF', 'final_payoff'),
        ('[PAYOFF]', 'payoff'),
        ('[TWIST]', 'twist'),
        ('[TURN]', 'turn'),
        ('[CLIMAX]', 'climax'),
        ('[REVEAL]', 'reveal'),
        ('[BOOKEND]', 'bookend'),
    ):
        if tag in blob:
            return mapped
    return ''


def required_shot_ids(plan: dict) -> List[str]:
    """Structural required climax/twist/payoff IDs — not blind keyword matching.

    Priority:
      1. plan.required_shots / plan.climax_ids (explicit structural list)
      2. scenes with structural_role / role in STRUCTURAL_ROLES
      3. legacy TWIST/PAYOFF/TURN/CLIMAX/FINAL PAYOFF tags (compat)
      4. plan.climax_tail_n → last N scene ids when declared
    """
    scenes = list(plan.get('scenes') or [])
    out: List[str] = []
    seen: Set[str] = set()

    def add(sid: Any) -> None:
        s = str(sid or '').strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    for sid in plan.get('required_shots') or []:
        add(sid)
    for sid in plan.get('climax_ids') or []:
        add(sid)

    for sc in scenes:
        sid = sc.get('id')
        if not sid:
            continue
        if structural_role_of(sc):
            add(sid)

    tail_n = plan.get('climax_tail_n')
    if isinstance(tail_n, int) and tail_n > 0 and scenes:
        for sc in scenes[-tail_n:]:
            add(sc.get('id'))

    return out


def extract_scene_state(sc: dict) -> SceneState:
    """Read scene-state from explicit fields; light inference only when missing."""
    sid = str(sc.get('id') or '')
    before = dict(sc.get('world_before') or sc.get('state_before') or {})
    after = dict(sc.get('world_after') or sc.get('state_after') or {})
    props = dict(sc.get('prop_state') or {})
    if sc.get('prop') and 'prop' not in props:
        props['focus'] = sc.get('prop')
    action = str(sc.get('action') or '').strip()
    if not action:
        # First verb-ish clause from prompt — documentation aid only
        prompt = (sc.get('prompt') or '')[:160]
        action = re.sub(r'\[[^\]]+\]', '', prompt).strip()[:80]
    req = sc.get('requires_next') or sc.get('consequence') or []
    if isinstance(req, str):
        req = [req]
    return SceneState(
        scene_id=sid,
        world_before=before,
        action=action,
        world_after=after,
        role=str(sc.get('cast_role') or sc.get('role') or ''),
        allegiance=str(sc.get('allegiance') or ''),
        prop_state=props,
        requires_next=[str(x) for x in req],
        structural_role=structural_role_of(sc),
    )


def ensure_scene_states(plan: dict, *, infer_edges: bool = False) -> dict:
    """Attach ``scene_state`` on every scene; ensure plan.required_shots is populated.

    Does **not** invent lore or auto-wire consequence edges by default.
    ``infer_edges=True`` is opt-in for offline scaffolding only — acceptance paths
    (PopVideoJob / karaoke gates) must keep ``infer_edges=False`` so missing authored
    ``requires_next`` fails ``assert_story_model`` with an actionable error.
    """
    out = dict(plan)
    scenes = [dict(s) for s in (plan.get('scenes') or [])]
    for i, sc in enumerate(scenes):
        st = extract_scene_state(sc)
        if infer_edges and not st.requires_next and ACTION_EDGE_HINT.search(sc.get('prompt') or ''):
            # Opt-in scaffold only — never used on acceptance / generate paths.
            if i + 1 < len(scenes) and scenes[i + 1].get('id'):
                st.requires_next = [str(scenes[i + 1]['id'])]
        sc['world_before'] = st.world_before
        sc['action'] = st.action or sc.get('action') or ''
        sc['world_after'] = st.world_after
        sc['prop_state'] = st.prop_state
        if st.allegiance:
            sc['allegiance'] = st.allegiance
        # Preserve explicit requires_next (including empty list); do not invent edges.
        if 'requires_next' in sc or st.requires_next:
            sc['requires_next'] = list(st.requires_next)
        if st.structural_role:
            sc['structural_role'] = st.structural_role
        sc['scene_state'] = st.to_dict()
        scenes[i] = sc
    out['scenes'] = scenes
    req = required_shot_ids(out)
    if req:
        out['required_shots'] = req
    # Global art / prop bible stub (locks) — keep if present
    bible = dict(out.get('art_bible') or out.get('prop_bible') or {})
    bible.setdefault('photoreal', True)
    bible.setdefault('banned_styles', ['clay', 'cartoon', 'toy', 'mannequin'])
    bible.setdefault('mouths_closed_default', True)
    out['art_bible'] = bible
    return out


def validate_scene_cap(plan: dict,
                       *,
                       max_scenes: Optional[int] = None,
                       lyric_line_count: Optional[int] = None,
                       allow_override: bool = False) -> Optional[str]:
    """Return error message if plan exceeds Watch Me–class complexity."""
    if allow_override or os.environ.get('GV_ALLOW_LARGE_PLAN', '0') == '1':
        return None
    n = len(plan.get('scenes') or [])
    cap = DEFAULT_MAX_SCENES if max_scenes is None else max_scenes
    if n > cap:
        return f'plan has {n} scenes > max {cap} (Watch Me–class cap); set GV_ALLOW_LARGE_PLAN=1 to override'
    if lyric_line_count is not None and lyric_line_count > 0:
        soft = max(cap, int(lyric_line_count * LYRIC_SCENE_RATIO))
        if n > soft:
            return (
                f'plan has {n} scenes > {LYRIC_SCENE_RATIO}× lyric lines '
                f'({lyric_line_count} → soft cap {soft})'
            )
    return None


def validate_art_bible(plan: dict) -> List[dict]:
    """Fail when prompts use banned clay/cartoon/toy styles or conflicting prop scales."""
    issues: List[dict] = []
    bible = plan.get('art_bible') or {}
    ban = ART_BAN_RE
    if bible.get('banned_styles'):
        extra = '|'.join(re.escape(str(x)) for x in bible['banned_styles'])
        ban = re.compile(rf'\b({extra}|clay|claymation|cartoon|toon|anime|toy|mannequin)\b', re.I)
    plug_hits: Dict[str, List[str]] = {k: [] for k, _ in PLUG_SCALE_TOKENS}
    for sc in plan.get('scenes') or []:
        blob = f"{sc.get('prompt', '')} {sc.get('motion', '')}"
        m = ban.search(blob)
        if m:
            issues.append({
                'severity': 'error', 'code': 'banned_art_style',
                'detail': f"scene {sc.get('id')} uses banned style token {m.group(0)!r}",
                'scene_id': sc.get('id'),
            })
        for key, cre in PLUG_SCALE_TOKENS:
            if cre.search(blob):
                plug_hits[key].append(str(sc.get('id')))
    # Conflicting wall vs giant plug scales in the same plan
    if plug_hits['wall_plug'] and plug_hits['giant_plug']:
        issues.append({
            'severity': 'error', 'code': 'prop_scale_conflict',
            'detail': (
                f"plug scale conflict: wall_plug in {plug_hits['wall_plug'][:6]} vs "
                f"giant_plug in {plug_hits['giant_plug'][:6]}; lock one prop mesh+scale"
            ),
            'wall_plug': plug_hits['wall_plug'],
            'giant_plug': plug_hits['giant_plug'],
        })
    return issues


def validate_consequence_edges(plan: dict, *, strict: bool = True) -> List[dict]:
    """Button/plug/kill-switch actions must cite requires_next that exist in the plan."""
    issues: List[dict] = []
    ids = {str(sc.get('id')) for sc in (plan.get('scenes') or []) if sc.get('id')}
    for sc in plan.get('scenes') or []:
        prompt = sc.get('prompt') or ''
        needs_edge = bool(ACTION_EDGE_HINT.search(prompt))
        req = sc.get('requires_next') or []
        if isinstance(req, str):
            req = [req]
        if needs_edge and not req:
            issues.append({
                'severity': 'error' if strict else 'warning',
                'code': 'missing_consequence_edge',
                'detail': (
                    f"scene {sc.get('id')} has a consequence action but no requires_next; "
                    f"button/plug beats must name the next shot that shows the result"
                ),
                'scene_id': sc.get('id'),
            })
            continue
        missing = [r for r in req if str(r) not in ids]
        if missing:
            issues.append({
                'severity': 'error',
                'code': 'invalid_consequence_edge',
                'detail': f"scene {sc.get('id')} requires_next {missing} not in plan scenes",
                'scene_id': sc.get('id'),
                'missing': missing,
            })
    # Allegiance continuity: both sides pressing the same kill control without consequence
    pressers = []
    for sc in plan.get('scenes') or []:
        if re.search(r'\b(red button|kill[- ]?switch)\b', sc.get('prompt') or '', re.I):
            pressers.append((str(sc.get('id')), str(sc.get('allegiance') or sc.get('role') or '')))
    allegiances = {a for _, a in pressers if a}
    if len(allegiances) >= 2:
        # Allowed only if every presser has a consequence edge
        for sid, _ in pressers:
            sc = next((s for s in plan.get('scenes') or [] if str(s.get('id')) == sid), {})
            if not (sc.get('requires_next')):
                issues.append({
                    'severity': 'error',
                    'code': 'allegiance_button_without_consequence',
                    'detail': (
                        f"opposing allegiances press the kill control ({sorted(allegiances)}) "
                        f"but scene {sid} lacks requires_next consequence"
                    ),
                    'scene_id': sid,
                })
    return issues


def validate_scene_states(plan: dict, *, require_before_after: bool = True) -> List[dict]:
    """Every scene needs before/action/after when require_before_after (P1 schema)."""
    issues: List[dict] = []
    for sc in plan.get('scenes') or []:
        before = sc.get('world_before') or {}
        after = sc.get('world_after') or {}
        action = (sc.get('action') or '').strip()
        if require_before_after:
            if not isinstance(before, dict):
                issues.append({
                    'severity': 'error', 'code': 'invalid_world_before',
                    'detail': f"scene {sc.get('id')} world_before must be a dict",
                    'scene_id': sc.get('id'),
                })
            if not isinstance(after, dict):
                issues.append({
                    'severity': 'error', 'code': 'invalid_world_after',
                    'detail': f"scene {sc.get('id')} world_after must be a dict",
                    'scene_id': sc.get('id'),
                })
            if not action:
                issues.append({
                    'severity': 'error', 'code': 'missing_action',
                    'detail': f"scene {sc.get('id')} missing action",
                    'scene_id': sc.get('id'),
                })
            # State must change OR be an explicit hold/bookend
            if before == after and structural_role_of(sc) not in ('bookend',) and before:
                # Same non-empty state with no declared hold → warn as orphan beat
                issues.append({
                    'severity': 'warning', 'code': 'world_state_unchanged',
                    'detail': f"scene {sc.get('id')} world_after equals world_before",
                    'scene_id': sc.get('id'),
                })
    return issues


def validate_story_model(plan: dict,
                         *,
                         max_scenes: Optional[int] = None,
                         lyric_line_count: Optional[int] = None,
                         allow_large: bool = False,
                         require_states: bool = True,
                         strict_edges: bool = True) -> StoryModelReport:
    """Run scene-cap, art-bible, consequence, and state-schema checks."""
    issues: List[dict] = []
    cap_err = validate_scene_cap(
        plan, max_scenes=max_scenes, lyric_line_count=lyric_line_count, allow_override=allow_large,
    )
    if cap_err:
        issues.append({'severity': 'error', 'code': 'scene_cap', 'detail': cap_err})
    issues.extend(validate_art_bible(plan))
    issues.extend(validate_consequence_edges(plan, strict=strict_edges))
    if require_states:
        issues.extend(validate_scene_states(plan, require_before_after=True))
    errors = [i for i in issues if i.get('severity') == 'error']
    req = required_shot_ids(plan)
    n = len(plan.get('scenes') or [])
    cap = DEFAULT_MAX_SCENES if max_scenes is None else max_scenes
    states = [extract_scene_state(sc).to_dict() for sc in (plan.get('scenes') or [])]
    ok = not errors
    summary = (
        f"story_model: {'ok' if ok else 'FAIL'} scenes={n}/{cap} "
        f"required_shots={req} errors={len(errors)} warnings="
        f"{sum(1 for i in issues if i.get('severity') == 'warning')}"
    )
    return StoryModelReport(
        ok=ok, issues=issues, required_shots=req, scene_count=n,
        max_scenes=cap, states=states, summary=summary,
    )


def assert_story_model(plan: dict, **kwargs) -> StoryModelReport:
    """Hard-abort wrapper → JobFailure(PLAN|ART|CONSEQUENCE)."""
    rep = validate_story_model(plan, **kwargs)
    if rep.ok:
        return rep
    errors = [i for i in rep.issues if i.get('severity') == 'error']
    codes = {e.get('code') for e in errors}
    if codes & {'banned_art_style', 'prop_scale_conflict'}:
        kind = FailureKind.ART
        stage = 'art_bible'
    elif codes & {'missing_consequence_edge', 'invalid_consequence_edge',
                  'allegiance_button_without_consequence'}:
        kind = FailureKind.CONSEQUENCE
        stage = 'consequence'
    else:
        kind = FailureKind.PLAN
        stage = 'story_model'
    raise JobFailure(
        kind=kind,
        message=rep.summary + ' | ' + '; '.join(e.get('detail', '') for e in errors[:4]),
        stage=stage,
        hint='Cap scenes near Watch Me (≤28), lock art/prop bible, and wire requires_next on actions.',
        details=rep.to_dict(),
    )


def apply_mouths_closed(plan: dict) -> dict:
    """Story-mode default: every non-SING scene gets an explicit mouths-closed steer."""
    out = dict(plan)
    scenes = []
    for sc in plan.get('scenes') or []:
        sc = dict(sc)
        role = str(sc.get('role') or '').lower()
        tags = str(sc.get('tags') or '').upper()
        is_sing = role in ('sing', 'singing', 'lipsync', 'performance') or 'SING' in tags
        if not is_sing:
            pr = sc.get('prompt') or ''
            if 'mouth closed' not in pr.lower() and 'no singing' not in pr.lower():
                sc['prompt'] = (pr.rstrip('.') + '. ' + MOUTH_CLOSED_STEER).strip()
            sc['mouths_closed'] = True
        scenes.append(sc)
    out['scenes'] = scenes
    out.setdefault('performance_mode', 'mouths_closed')
    return out
