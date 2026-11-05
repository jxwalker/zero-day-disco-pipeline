"""Adaptable creative contract for story / storyboard quality.

Lessons distilled from high-quality AI music-video craft (visual premise per shot,
contrasting worlds, character styling anchors, performance-on-accent, shot variety,
recurring-location transformation, code-built HUD/kinetic type, beat-timed escalation).

These are **adaptable requirements**, not a brittle imitation of any one video:
- A simple single-world job can pass with a clear premise, styling anchors, and an
  edit-composited graphics plan (possibly empty).
- Dual-world / payoff-heavy jobs unlock the stronger contrast and location-arc checks.
- Models never render readable text; HUD / terminals / kinetic lyrics are always
  post-production overlays (see ``overlays.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .overlays import NO_TEXT_NEG, model_text_forbidden, terminal_must_be_blank

# --- Schema-ish field names (kept as plain dicts for planner JSON compatibility) ---

WORLD_AXES = ('grade', 'camera', 'design', 'palette', 'energy')
SHOT_SCALES = ('EWS', 'WIDE', 'FS', 'MFS', 'MS', 'MCU', 'CU', 'ECU', 'POV', 'OTS', 'INSERT')
ACCENTS = ('drop', 'hit', 'hold', 'build', 'break', 'hook', 'punchline')

GRAPHICS_KINDS = ('hud', 'kinetic', 'terminal', 'caption', 'story', 'slam', 'ui')


@dataclass
class ContractIssue:
    code: str
    severity: str          # 'error' | 'warning' | 'info'
    detail: str
    adaptive: bool = True  # True = only applies when the plan opted into that dimension

    def to_dict(self) -> dict:
        return {
            'code': self.code, 'severity': self.severity, 'detail': self.detail,
            'adaptive': self.adaptive,
        }


@dataclass
class ContractReport:
    ok: bool
    mode: str
    issues: List[ContractIssue] = field(default_factory=list)
    contract: Dict[str, Any] = field(default_factory=dict)
    summary: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'mode': self.mode, 'summary': self.summary,
            'issues': [i.to_dict() for i in self.issues],
            'contract': self.contract,
            'errors': [i.to_dict() for i in self.issues if i.severity == 'error'],
            'warnings': [i.to_dict() for i in self.issues if i.severity == 'warning'],
        }


def _get_contract(plan: dict) -> dict:
    return dict(plan.get('creative_contract') or plan.get('story_contract') or {})


def _scenes(plan: dict) -> List[dict]:
    return list(plan.get('scenes') or [])


def infer_visual_premise(plan: dict, song_idea: str = '') -> str:
    """Derive a one-line premise from plan fields when not explicitly set."""
    cc = _get_contract(plan)
    if (cc.get('visual_premise') or '').strip():
        return cc['visual_premise'].strip()
    for key in ('arc', 'logline', 'premise', 'story'):
        if (plan.get(key) or '').strip():
            return str(plan[key]).strip()
    st = plan.get('story_text') or []
    if st and (st[0].get('text') or '').strip():
        return str(st[0]['text']).strip()
    if (song_idea or '').strip():
        return f"Visual story for: {song_idea.strip()[:120]}"
    return ''


def worlds_need_contrast(contract: dict) -> bool:
    worlds = contract.get('worlds') or []
    return isinstance(worlds, list) and len(worlds) >= 2


def ensure_creative_contract(plan: dict, *, song_idea: str = '') -> dict:
    """Fill a creative_contract from existing plan fields without inventing benchmark lore.

    Idempotent. Does not invent a second world or location arcs unless already present.
    Always sets ``graphics_plan.model_renders_text = False``.
    """
    out = dict(plan)
    cc = _get_contract(plan)
    premise = infer_visual_premise(plan, song_idea)
    if premise:
        cc['visual_premise'] = premise

    # Character styling anchors from cast / lead / scene tags
    anchors = list(cc.get('character_anchors') or [])
    if not anchors:
        if plan.get('lead') or plan.get('wardrobe'):
            anchors.append({
                'id': 'LEAD',
                'styling': str(plan.get('lead') or plan.get('wardrobe') or '')[:200],
                'signature': str(plan.get('wardrobe') or '')[:120],
            })
        # Distinct non-lead roles tagged in scenes
        seen = {'LEAD', 'HERO'}
        for sc in _scenes(plan):
            for tok in re.findall(r'\[([A-Z][A-Z0-9_]{1,20})\]', sc.get('prompt') or ''):
                if tok in seen or tok in ('SING', 'CHORUS', 'TWIST', 'PAYOFF', 'TURN', 'SETUP', 'ACTION', 'TERM', 'PIP'):
                    continue
                seen.add(tok)
                anchors.append({'id': tok, 'styling': f'{tok} styling locked to its reference sheet', 'signature': tok})
        cc['character_anchors'] = anchors

    # Worlds: keep if present; otherwise a single default world from design/palette
    if not cc.get('worlds'):
        des = plan.get('design') or {}
        cc['worlds'] = [{
            'id': 'A',
            'label': 'primary',
            'grade': des.get('grade') or 'neutral',
            'camera': des.get('transition') or 'motivated',
            'design': des.get('texture') or plan.get('setting') or 'story world',
            'palette': des.get('palette') or plan.get('palette') or '',
        }]

    # Shot variety stub from scene prompts (scales mentioned)
    if not cc.get('shot_variety'):
        scales = []
        for sc in _scenes(plan):
            blob = f"{sc.get('prompt', '')} {sc.get('size_lens', '')} {sc.get('shot_size', '')}".upper()
            for s in SHOT_SCALES:
                if re.search(rf'\b{s}\b', blob) and s not in scales:
                    scales.append(s)
        cc['shot_variety'] = {
            'scales': scales,
            'physical_interactions': any(
                re.search(r'\b(yank|slam|pull|push|hold|hand|grab|touch|throw|rip)\b',
                          sc.get('prompt') or '', re.I)
                for sc in _scenes(plan)
            ),
        }

    # Location arcs: only keep/pass through; do not invent
    cc.setdefault('location_arcs', list(cc.get('location_arcs') or []))

    # Performance beats: derive lightly from SING / emotion tags when missing
    if not cc.get('performance_beats'):
        beats = []
        for sc in _scenes(plan):
            role = str(sc.get('role') or '').lower()
            tags = str(sc.get('tags') or '').upper()
            if role in ('singing', 'performance') or 'SING' in tags:
                beats.append({
                    'scene_id': sc.get('id'),
                    'accent': 'hook' if 'CHORUS' in tags else 'hit',
                    'emotion': sc.get('emotion') or 'expressive performance on the musical accent',
                    'musical_cue': sc.get('musical_cue') or role or 'sing',
                })
        cc['performance_beats'] = beats

    # Graphics plan: always code-built; model never renders text
    gp = dict(cc.get('graphics_plan') or plan.get('graphics_plan') or {})
    gp['model_renders_text'] = False
    gp.setdefault('hud', list(gp.get('hud') or []))
    gp.setdefault('kinetic', list(gp.get('kinetic') or []))
    gp.setdefault('terminal', list(gp.get('terminal') or []))
    gp.setdefault('caption', list(gp.get('caption') or []))
    # Seed terminals from scene terminal_text / story overlays already on the plan
    if not gp['terminal']:
        for sc in _scenes(plan):
            if sc.get('terminal_text') or sc.get('screen_text'):
                gp['terminal'].append({
                    'scene_id': sc.get('id'),
                    'text': sc.get('terminal_text') or sc.get('screen_text'),
                    'composite': True,
                })
    if not gp['kinetic'] and (plan.get('slams') or plan.get('word_slams')):
        for slam in plan.get('slams') or plan.get('word_slams') or []:
            gp['kinetic'].append({
                'line': slam.get('line'),
                'text': slam.get('text') or slam.get('word'),
                'style': 'kinetic_slam',
                'composite': True,
            })
    cc['graphics_plan'] = gp
    cc.setdefault('beat_escalation', cc.get('beat_escalation') or {
        'enabled': True,
        'notes': 'Escalate cuts and performance intensity on musical accents; hold on punchlines.',
    })

    out['creative_contract'] = cc
    return out


def _world_signature(world: dict) -> Tuple[str, ...]:
    return tuple(str(world.get(ax) or '').strip().lower() for ax in WORLD_AXES)


def validate_creative_contract(plan: dict,
                               *,
                               mode: str = 'adaptive',
                               song_idea: str = '') -> ContractReport:
    """Validate creative quality dimensions.

    Modes:
      - ``adaptive`` (default): hard-fail only universal invariants and dimensions the
        plan opted into (e.g. 2+ worlds → contrast required). Missing optional craft
        for simple jobs → warnings, not rejection.
      - ``strict``: also require premise, anchors, shot variety signal, and a graphics
        plan object (still does not demand dual worlds).
      - ``advisory``: never hard-fail; everything is warning/info.
    """
    if mode not in ('adaptive', 'strict', 'advisory'):
        mode = 'adaptive'
    issues: List[ContractIssue] = []

    def err(code, detail, adaptive=False):
        issues.append(ContractIssue(code, 'error' if mode != 'advisory' else 'warning', detail, adaptive))

    def warn(code, detail, adaptive=True):
        issues.append(ContractIssue(code, 'warning', detail, adaptive))

    # Catch model_renders_text=True on the *incoming* plan before ensure() normalizes it.
    raw_gp = (_get_contract(plan).get('graphics_plan') or plan.get('graphics_plan') or {})
    if raw_gp.get('model_renders_text') is True:
        err('model_must_not_render_text',
            'graphics_plan.model_renders_text must be False; HUD, terminals, captions and '
            'kinetic lyrics are composited in the edit.',
            adaptive=False)

    filled = ensure_creative_contract(plan, song_idea=song_idea)
    cc = _get_contract(filled)

    # --- Universal: visual premise ---
    premise = (cc.get('visual_premise') or '').strip()
    if not premise:
        (err if mode == 'strict' else warn)(
            'missing_visual_premise',
            'Job should state one visual premise that every shot advances.',
            adaptive=False,
        )
    else:
        # Soft: scenes should not be pure orphan filler when we can tell
        orphans = []
        for sc in _scenes(filled):
            blob = f"{sc.get('prompt', '')} {sc.get('tags', '')} {sc.get('role', '')}".lower()
            if not blob.strip():
                orphans.append(sc.get('id'))
                continue
            # A shot advances premise if it has action/role/tag or shares a content word
            words = {w for w in re.findall(r'[a-z]{4,}', premise.lower()) if w not in {
                'that', 'with', 'from', 'this', 'have', 'into', 'about', 'visual', 'story',
            }}
            if words and not (words & set(re.findall(r'[a-z]{4,}', blob))):
                if not any(t in blob for t in ('setup', 'sing', 'action', 'twist', 'payoff', 'turn', 'chorus')):
                    orphans.append(sc.get('id'))
        if orphans and len(orphans) > max(1, len(_scenes(filled)) // 2):
            warn('shots_may_not_advance_premise',
                 f'Many scenes lack a clear link to the visual premise: {orphans[:8]}')

    # --- Character styling anchors ---
    anchors = cc.get('character_anchors') or []
    if not anchors:
        (err if mode == 'strict' else warn)(
            'missing_character_anchors',
            'Provide at least one character styling anchor (wardrobe/signature).',
            adaptive=False,
        )
    else:
        for a in anchors:
            if not (a.get('styling') or a.get('signature')):
                warn('thin_character_anchor', f"Anchor {a.get('id')} lacks styling/signature text")

    # --- Contrasting worlds (only when opted in with 2+) ---
    worlds = cc.get('worlds') or []
    if worlds_need_contrast(cc):
        sigs = [_world_signature(w) for w in worlds]
        if len(set(sigs)) < 2:
            err('worlds_not_contrasting',
                'Two or more worlds are declared but grade/camera/design are not contrasting; '
                'differentiate production design, grade and camera language.',
                adaptive=True)
        else:
            # Encourage aggressive contrast across at least two axes
            diffs = sum(1 for ax_i in range(len(WORLD_AXES))
                        if len({s[ax_i] for s in sigs if s[ax_i]}) > 1)
            if diffs < 2:
                warn('weak_world_contrast',
                     'Worlds differ on fewer than two axes (grade/camera/design/palette/energy).')
    elif mode == 'strict' and len(worlds) < 1:
        warn('no_world_defined', 'Strict mode expects at least a primary world description.')

    # --- Performance beats (adaptive: warn if singing scenes exist without beats) ---
    sing_scenes = [
        sc for sc in _scenes(filled)
        if 'SING' in str(sc.get('tags', '')).upper()
        or str(sc.get('role') or '').lower() in ('singing', 'performance')
    ]
    beats = cc.get('performance_beats') or []
    if sing_scenes and not beats:
        warn('missing_performance_beats',
             'Singing/performance scenes exist but no performance_beats place emotion on musical accents.')
    for b in beats:
        if b.get('accent') and str(b['accent']).lower() not in ACCENTS:
            warn('unknown_accent', f"performance beat accent '{b.get('accent')}' is nonstandard")

    # --- Shot variety (soft) ---
    sv = cc.get('shot_variety') or {}
    scales = sv.get('scales') or []
    if mode == 'strict' and len(scales) < 2 and len(_scenes(filled)) >= 4:
        warn('low_shot_variety',
             'Strict mode: with 4+ scenes, prefer at least two distinct shot scales / POVs.')
    elif len(_scenes(filled)) >= 6 and len(scales) < 2:
        warn('low_shot_variety',
             'Consider varying shot scale/POV across the cut (WIDE/MCU/CU/POV/INSERT).')
    if len(_scenes(filled)) >= 4 and not sv.get('physical_interactions'):
        warn('few_physical_interactions',
             'Prefer tangible hand/prop/body interactions over talking heads alone.')

    # --- Location transformations / payoff (adaptive) ---
    arcs = cc.get('location_arcs') or []
    scene_ids = {str(sc.get('id')) for sc in _scenes(filled)}
    for arc in arcs:
        states = arc.get('states') or []
        if len(states) < 2:
            err('location_arc_needs_states',
                f"Location '{arc.get('location')}' must show a visible state change for payoff "
                f"(e.g. crowded → empty).",
                adaptive=True)
        payoff = str(arc.get('payoff_scene') or '')
        if payoff and payoff not in scene_ids:
            err('location_payoff_missing',
                f"Location arc payoff_scene '{payoff}' not in plan scenes.",
                adaptive=True)

    # If plan has TWIST/PAYOFF tags but no location_arcs, info only (not required)
    has_payoff_tag = any(
        any(t in f"{sc.get('tags', '')} {sc.get('prompt', '')}".upper() for t in ('PAYOFF', 'TWIST'))
        for sc in _scenes(filled)
    )
    if has_payoff_tag and not arcs:
        issues.append(ContractIssue(
            'payoff_without_location_arc', 'info',
            'Payoff/twist present; optional location_arcs can make recurring places transform visibly.',
            adaptive=True,
        ))

    # --- Graphics plan: model never renders text ---
    gp = cc.get('graphics_plan') or {}
    if not gp:
        (err if mode == 'strict' else warn)(
            'missing_graphics_plan',
            'Declare a code-built graphics/overlay plan (HUD/kinetic/terminal may be empty lists).',
            adaptive=False,
        )
    else:
        # Any overlay copy must be marked composite / destined for edit
        for kind in GRAPHICS_KINDS:
            for item in gp.get(kind) or []:
                if isinstance(item, dict) and item.get('composite') is False:
                    err('overlay_marked_non_composite',
                        f'{kind} item must be edit-composited (composite=true), never model-burned.',
                        adaptive=False)
                if isinstance(item, dict) and item.get('in_model_prompt'):
                    err('overlay_text_in_model_prompt',
                        f'{kind} readable text must not be requested inside model prompts.',
                        adaptive=False)

    # Scene prompts must keep no-text / blank-terminal steers when screens mentioned
    for sc in _scenes(filled):
        pr = sc.get('prompt') or ''
        if re.search(r'\b(hud|caption|kinetic|subtitles?|lyrics on screen)\b', pr, re.I):
            if 'no readable text' not in pr.lower() and 'blank' not in pr.lower():
                warn('hud_in_prompt_without_no_text',
                     f"Scene {sc.get('id')} mentions HUD/captions; keep screens blank and composite text in edit.")

    errors = [i for i in issues if i.severity == 'error']
    ok = not errors
    summary = (
        f"creative_contract {mode}: {'ok' if ok else 'FAIL'} "
        f"({len(errors)} errors, {sum(1 for i in issues if i.severity == 'warning')} warnings); "
        f"premise={'yes' if premise else 'no'} worlds={len(worlds)} anchors={len(anchors)} "
        f"arcs={len(arcs)} gfx={'yes' if gp else 'no'}"
    )
    return ContractReport(ok=ok, mode=mode, issues=issues, contract=cc, summary=summary)


def apply_no_text_to_scenes(plan: dict) -> dict:
    """Ensure every scene prompt carries no-gen-text + blank-terminal steers."""
    out = dict(plan)
    scenes = []
    for sc in _scenes(plan):
        sc = dict(sc)
        sc['prompt'] = terminal_must_be_blank(model_text_forbidden(sc.get('prompt') or ''))
        scenes.append(sc)
    out['scenes'] = scenes
    return out


def graphics_plan_to_overlay_seeds(contract: dict) -> List[dict]:
    """Normalize graphics_plan entries into overlay seed dicts for ``build_overlay_texts``."""
    gp = (contract or {}).get('graphics_plan') or {}
    seeds = []
    for kind in ('hud', 'kinetic', 'terminal', 'caption', 'story', 'slam', 'ui'):
        for item in gp.get(kind) or []:
            if isinstance(item, str):
                seeds.append({'g': kind, 'text': item, 'composite': True})
            elif isinstance(item, dict) and item.get('text'):
                seeds.append({
                    'g': kind,
                    'text': item['text'],
                    't0': item.get('t0'),
                    't1': item.get('t1'),
                    'line': item.get('line'),
                    'src': item.get('scene_id') or item.get('src') or '',
                    'rect': item.get('rect'),
                    'style': item.get('style') or kind,
                    'kicker': item.get('kicker') or kind.upper(),
                    'composite': True,
                })
    return seeds


def storyboard_direction_addendum() -> str:
    """Short block appended to storyboard/direction prompts (adaptable craft goals)."""
    return (
        "\nCREATIVE CONTRACT (adaptable; scale to the song — do not invent a second world unless the story needs it):\n"
        "- visual_premise: one sentence every shot advances.\n"
        "- worlds: one world is fine; if two, contrast them via grade, production design and camera language "
        "(e.g. clean/static/cool vs dirty/handheld/warm).\n"
        "- character_anchors: distinct styling signatures per cast member.\n"
        "- performance_beats: expressive performances deliberately on musical accents (drop/hit/hold).\n"
        "- shot_variety: vary scale/POV; prefer physical interactions over talking heads.\n"
        "- location_arcs: recurring places may transform for payoff (crowded→empty, lit→dark).\n"
        "- graphics_plan: HUD, kinetic typography, terminals, captions are CODE-BUILT in the edit only; "
        "model frames stay text-free (blank/dark screens). model_renders_text must be false.\n"
        "- beat_escalation: escalate on accents; hold on punchlines.\n"
        f"NO TEXT IN MODEL FRAMES: {NO_TEXT_NEG}\n"
    )
