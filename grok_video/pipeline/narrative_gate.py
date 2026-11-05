"""Narrative QA + storyboard hard gate (Watch Me + cross-curator craft checklist).

Lyric timing stays for captions; story structure is gated here before any generation spend.
Craft rules are narrative/storyboard/edit gates — not keyword checks or benchmark clones.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .failures import FailureKind, JobFailure
from .story_model import required_shot_ids, structural_role_of

# Storyboard review must clear this score (1–10) or hard-abort before generation.
STORYBOARD_MIN_SCORE = int(os.environ.get('GV_STORYBOARD_MIN_SCORE', '7'))
MUST_NOT_CAMERA_RE = re.compile(
    r'must not go to camera|do not (?:send|go) to camera|not ready for camera|'
    r'refuse(?:s)? (?:to )?film|block(?:s)? (?:the )?shoot|halt production',
    re.I,
)

STOPWORDS = frozenset({
    'that', 'with', 'from', 'this', 'have', 'into', 'about', 'visual', 'story',
    'then', 'when', 'they', 'them', 'their', 'hers', 'him', 'she', 'the', 'and',
    'for', 'her', 'his', 'own', 'onto', 'over', 'under', 'after', 'before',
})

ACCENTS = frozenset({'drop', 'hit', 'hold', 'build', 'break', 'hook', 'punchline', 'chorus'})

# Full-frame story carriers that must be diegetic / state-changing if used as narrative.
STORY_CARRIER_GFX = frozenset({
    'headline', 'bignum', 'bars', 'post', 'feed', 'quote', 'compare', 'stamp',
    'story', 'card', 'browser', 'rows',
})


@dataclass
class NarrativeReport:
    ok: bool
    issues: List[dict] = field(default_factory=list)
    checklist: Dict[str, bool] = field(default_factory=dict)
    summary: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'summary': self.summary, 'issues': self.issues,
            'checklist': self.checklist,
            'errors': [i for i in self.issues if i.get('severity') == 'error'],
        }


def storyboard_must_abort(review: Optional[dict],
                          *,
                          min_score: Optional[int] = None,
                          require_present: bool = True) -> Optional[str]:
    """Return abort reason if storyboard review is missing, below threshold, or forbids camera.

    ``review`` is the dict saved on plan['storyboard_review'] / storyboard_review.json.
    By default a *missing* review is an abort — every generate/resume path needs a
    present, passing review (no fail-open via absent artifacts).
    """
    if not review:
        if require_present:
            return (
                'storyboard review missing; must not go to camera without a present, '
                'passing review (no fail-open / resume bypass)'
            )
        return None
    thr = STORYBOARD_MIN_SCORE if min_score is None else min_score
    verdict = str(review.get('verdict') or review.get('summary') or '')
    if MUST_NOT_CAMERA_RE.search(verdict):
        return (
            f"storyboard review forbids camera: {verdict[:200]!r} "
            f"(must not go to camera → hard-abort before generation)"
        )
    blob = ' '.join(str(review.get(k) or '') for k in (
        'verdict', 'summary', 'notes', 'reason', 'blocker',
    ))
    for item in review.get('issues') or review.get('blockers') or []:
        blob += ' ' + (item if isinstance(item, str) else str(item.get('detail') or item))
    if MUST_NOT_CAMERA_RE.search(blob):
        return f"storyboard review blocker: {blob[:240]!r}"
    score = review.get('score')
    if score is None:
        return None
    try:
        sc = float(score)
    except (TypeError, ValueError):
        return None
    if sc < thr:
        return (
            f"storyboard review score {sc} < {thr}; "
            f"must not go to camera until fixed (hard-abort before generation)"
        )
    return None


def assert_storyboard_review(plan: dict,
                             review: Optional[dict] = None,
                             *,
                             min_score: Optional[int] = None,
                             require_present: bool = True) -> None:
    """Hard-abort on missing/bad storyboard review. Raises JobFailure(STORYBOARD)."""
    rev = review if review is not None else (plan.get('storyboard_review') or None)
    if rev is not None and not isinstance(rev, dict):
        rev = {'verdict': str(rev)}
    # Empty dict counts as missing
    if isinstance(rev, dict) and not rev:
        rev = None
    reason = storyboard_must_abort(
        rev, min_score=min_score, require_present=require_present,
    )
    if reason:
        raise JobFailure(
            kind=FailureKind.STORYBOARD,
            message=reason,
            stage='storyboard_review',
            hint='Produce a passing storyboard review before generate/resume; do not bypass via plan.json.',
            details={'review': {k: (rev or {}).get(k) for k in ('score', 'verdict')}},
        )


def _content_words(text: str) -> Set[str]:
    return {
        w for w in re.findall(r"[a-z]{3,}", (text or '').lower())
        if w not in STOPWORDS
    }


def _one_sentence(text: str) -> bool:
    """True when text is a single readable sentence-ish premise (not a multi-para dump)."""
    t = (text or '').strip()
    if not t or len(t) < 12:
        return False
    # Allow em-dash / arrow beats inside one sentence; reject multi-paragraph.
    if '\n\n' in t:
        return False
    # More than 2 hard sentence terminators → not one sentence
    stops = len(re.findall(r'[.!?]+(?:\s|$)', t))
    return stops <= 2 and len(t) <= 280


def _place_of(sc: dict) -> str:
    """Location id from world state or prompt — structural place, not lyric keywords."""
    for blob in (sc.get('world_before'), sc.get('world_after'), sc.get('prop_state')):
        if isinstance(blob, dict):
            for key in ('place', 'location', 'set', 'room'):
                if blob.get(key):
                    return str(blob[key]).strip().lower()
    loc = str(sc.get('location') or sc.get('place') or '').strip().lower()
    return loc


def _world_sig(sc: dict, which: str = 'after') -> Tuple:
    d = sc.get('world_after') if which == 'after' else sc.get('world_before')
    if not isinstance(d, dict) or not d:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in d.items()))


def _payoff_design(plan: dict, cc: dict, scenes: List[dict]) -> Optional[dict]:
    """Return declared payoff design (end state designed before the middle is filled)."""
    pd = plan.get('payoff_design') or cc.get('payoff_design') or plan.get('final_payoff')
    if isinstance(pd, dict) and pd:
        return pd
    if isinstance(pd, str) and pd.strip():
        return {'summary': pd.strip()}
    # Infer from structural payoff scene with a real end state
    for sc in scenes:
        role = structural_role_of(sc)
        if role in ('payoff', 'final_payoff', 'climax', 'bookend'):
            after = sc.get('world_after') or {}
            if after:
                return {
                    'scene_id': sc.get('id'),
                    'world_after': dict(after),
                    'summary': sc.get('action') or '',
                    'inferred': True,
                }
    return None


def _viewer_retell_text(plan: dict, cc: dict) -> str:
    return (
        (plan.get('viewer_retell') or '').strip()
        or (cc.get('viewer_retell') or '').strip()
        or (plan.get('retell') or '').strip()
    )


def narrative_checklist(plan: dict, timeline: Optional[Sequence[dict]] = None) -> NarrativeReport:
    """Watch Me + cross-curator craft checklist (sound-off / retell / payoff-first).

    Hard errors (abort) for multi-beat stories:
      - no one-sentence visual premise
      - no independent viewer_retell aligned with the premise
      - payoff not designed (payoff_design / structural end state) before a filled middle
      - lyric-literal props that do not change persistent world state
      - graphics not planned in preproduction, or non-diegetic story carriers
      - recurring locations that never visibly transform toward payoff
      - emotional performance peaks not placed on musical accents
      - missing required climax ids / bookend when structural roles exist
    """
    issues: List[dict] = []
    check: Dict[str, bool] = {}

    cc = plan.get('creative_contract') or plan.get('story_contract') or {}
    premise = (
        (cc.get('visual_premise') or '').strip()
        or (plan.get('arc') or '').strip()
        or (plan.get('logline') or '').strip()
        or (plan.get('premise') or '').strip()
    )
    check['has_premise'] = bool(premise) and _one_sentence(premise)
    if not premise:
        issues.append({
            'severity': 'error', 'code': 'missing_premise',
            'detail': 'No one-sentence visual premise; every shot must advance one readable arc.',
        })
    elif not _one_sentence(premise):
        issues.append({
            'severity': 'error', 'code': 'premise_not_one_sentence',
            'detail': 'visual_premise must be one short sentence an independent viewer can hold.',
        })

    scenes = list(plan.get('scenes') or [])
    n = len(scenes)
    multi = n >= 4

    # --- Independent viewer-retell gate ---
    retell = _viewer_retell_text(plan, cc)
    check['has_viewer_retell'] = bool(retell) and _one_sentence(retell)
    if multi and not retell:
        issues.append({
            'severity': 'error', 'code': 'missing_viewer_retell',
            'detail': (
                'Declare viewer_retell: one sentence an independent viewer would say '
                'after watching with the sound off (must match the premise arc).'
            ),
        })
    elif retell and not _one_sentence(retell):
        issues.append({
            'severity': 'error', 'code': 'retell_not_one_sentence',
            'detail': 'viewer_retell must be one sentence.',
        })
    elif retell and premise:
        pw, rw = _content_words(premise), _content_words(retell)
        overlap = pw & rw
        # Need some shared spine words; allow short premises with ≥1 overlap
        need = 1 if len(pw) <= 4 else max(2, len(pw) // 4)
        check['retell_aligns_premise'] = len(overlap) >= need
        if not check['retell_aligns_premise']:
            issues.append({
                'severity': 'error', 'code': 'retell_mismatch',
                'detail': (
                    'viewer_retell does not align with visual_premise '
                    f'(shared content words {sorted(overlap)[:8]}; need ≥{need}).'
                ),
            })
    else:
        check['retell_aligns_premise'] = bool(retell) or not multi

    req = required_shot_ids(plan)
    check['has_required_shots'] = bool(req)
    structural = [s for s in scenes if structural_role_of(s) in {
        'twist', 'payoff', 'climax', 'reveal', 'turn', 'final_payoff', 'bookend',
    }]
    if structural and not req:
        issues.append({
            'severity': 'error', 'code': 'missing_required_shot_ids',
            'detail': 'Structural twist/payoff scenes present but required_shots is empty.',
        })
    elif n >= 8 and not req:
        issues.append({
            'severity': 'warning', 'code': 'no_declared_climax',
            'detail': 'Plan has 8+ scenes but no required_shots / climax structural ids.',
        })

    # --- Payoff designed before the middle ---
    payoff = _payoff_design(plan, cc, scenes)
    check['payoff_designed_first'] = bool(payoff)
    if multi and not payoff:
        issues.append({
            'severity': 'error', 'code': 'payoff_not_designed',
            'detail': (
                'Design the final payoff before filling the middle: set payoff_design '
                '(end world state + scene id) or a structural payoff scene with world_after.'
            ),
        })
    elif multi and payoff and not req:
        issues.append({
            'severity': 'error', 'code': 'payoff_missing_required_id',
            'detail': 'payoff_design present but required_shots lacks the climax/payoff structural ids.',
        })

    # Bookend / payoff closure
    roles = {(s.get('structural_role') or s.get('role') or '').lower() for s in scenes}
    has_bookend = (
        'bookend' in roles or 'payoff' in roles or 'final_payoff' in roles
        or bool(req) or bool(payoff)
    )
    if scenes:
        p0, p1 = _place_of(scenes[0]), _place_of(scenes[-1])
        if p0 and p0 == p1:
            has_bookend = True
    check['has_bookend_or_payoff'] = bool(has_bookend)
    if multi and not has_bookend:
        issues.append({
            'severity': 'error', 'code': 'missing_bookend_or_payoff',
            'detail': 'Story lacks bookend/payoff closure (structural payoff id or matching open/close).',
        })

    # Cast anchors (soft)
    anchors = cc.get('character_anchors') or plan.get('character_anchors') or []
    check['has_cast_lock'] = bool(anchors) or bool(plan.get('lead') or plan.get('wardrobe'))
    if n >= 3 and not check['has_cast_lock']:
        issues.append({
            'severity': 'warning', 'code': 'missing_cast_lock',
            'detail': 'No character styling anchors / lead wardrobe lock.',
        })

    # --- Graphics: planned in preproduction; diegetic / state-changing ---
    gp = cc.get('graphics_plan') or plan.get('graphics_plan')
    check['has_graphics_plan'] = gp is not None
    if gp is None and n >= 3:
        issues.append({
            'severity': 'error', 'code': 'graphics_not_preplanned',
            'detail': (
                'Graphics must be planned in preproduction (creative_contract.graphics_plan); '
                'empty lists are fine — unplanned edit cards are not.'
            ),
        })
    elif isinstance(gp, dict):
        bad_carriers = []
        for kind in STORY_CARRIER_GFX:
            for item in gp.get(kind) or []:
                if isinstance(item, str):
                    bad_carriers.append(f'{kind}:bare_string')
                    continue
                if not isinstance(item, dict):
                    continue
                diegetic = bool(item.get('diegetic') or item.get('in_world'))
                state_chg = bool(item.get('state_change') or item.get('world_change'))
                if not (diegetic or state_chg):
                    bad_carriers.append(f"{kind}:{item.get('text', '')[:40]}")
        check['graphics_diegetic_or_stateful'] = not bad_carriers
        if bad_carriers:
            issues.append({
                'severity': 'error', 'code': 'graphics_not_diegetic',
                'detail': (
                    'Story-carrier graphics must be diegetic or state-changing '
                    f'(set diegetic/state_change on preplanned items): {bad_carriers[:6]}'
                ),
            })
        # Kinetic/slam/hud/terminal are allowed as punchlines when composited on plates
        for kind in ('hud', 'kinetic', 'terminal', 'slam', 'caption', 'ui'):
            for item in gp.get(kind) or []:
                if isinstance(item, dict) and item.get('composite') is False:
                    issues.append({
                        'severity': 'error', 'code': 'graphics_not_composite',
                        'detail': f'{kind} graphics must be edit-composited (composite=true).',
                    })
    else:
        check['graphics_diegetic_or_stateful'] = True

    # --- Ban lyric-literal props without persistent world-state consequences ---
    literal_bad = []
    for sc in scenes:
        props = sc.get('prop_state') if isinstance(sc.get('prop_state'), dict) else {}
        flagged = bool(sc.get('lyric_literal') or sc.get('lyric_prop'))
        # Inserts that show a prop but leave world unchanged and have no consequence edge
        before, after = _world_sig(sc, 'before'), _world_sig(sc, 'after')
        unchanged = before == after
        no_edge = not (sc.get('requires_next') or [])
        role = str(sc.get('role') or '').lower()
        is_insert = role in ('insert', 'prop_insert', 'lyric_insert') or flagged
        if (flagged or is_insert) and unchanged and no_edge and structural_role_of(sc) not in {
            'bookend', 'payoff', 'final_payoff',
        }:
            literal_bad.append(str(sc.get('id')))
            continue
        # Explicit lyric_literal without any world key change involving the prop
        if flagged and props and unchanged:
            literal_bad.append(str(sc.get('id')))
    check['no_orphan_lyric_props'] = not literal_bad
    if literal_bad:
        issues.append({
            'severity': 'error', 'code': 'lyric_literal_prop',
            'detail': (
                'Lyric-literal props banned unless they produce persistent world-state '
                f'consequences (world_after change and/or requires_next): {literal_bad[:8]}'
            ),
        })

    # --- Recurring locations must visibly transform for payoff ---
    by_place: Dict[str, List[dict]] = {}
    for sc in scenes:
        place = _place_of(sc)
        if place:
            by_place.setdefault(place, []).append(sc)
    stagnant = []
    for place, group in by_place.items():
        if len(group) < 2:
            continue
        sigs = {_world_sig(sc, 'after') or _world_sig(sc, 'before') for sc in group}
        sigs.discard(())
        # Declared location_arc covering this place counts as transform
        arcs = cc.get('location_arcs') or plan.get('location_arcs') or []
        covered = any(
            place in str(a.get('location') or '').lower()
            and len(a.get('states') or []) >= 2
            for a in arcs
        )
        if len(sigs) < 2 and not covered:
            stagnant.append(place)
    check['recurring_locations_transform'] = not stagnant
    if stagnant and multi:
        issues.append({
            'severity': 'error', 'code': 'location_no_transform',
            'detail': (
                'Recurring locations must visibly transform for the payoff '
                f'(distinct world states or location_arcs.states≥2): {stagnant[:6]}'
            ),
        })
    # Also enforce declared arcs still need ≥2 states (mirror creative_contract, as hard narrative)
    for arc in cc.get('location_arcs') or []:
        if len(arc.get('states') or []) < 2:
            issues.append({
                'severity': 'error', 'code': 'location_arc_needs_states',
                'detail': (
                    f"location_arc '{arc.get('location')}' needs ≥2 visible states for payoff."
                ),
            })

    # --- Emotional performance peaks on musical accents ---
    beats = cc.get('performance_beats') or plan.get('performance_beats') or []
    beat_by_id = {
        str(b.get('scene_id')): b for b in beats if isinstance(b, dict) and b.get('scene_id')
    }
    peak_roles = {
        'performance_closed', 'performance', 'singing', 'sing', 'lipsync', 'hook',
    }
    peaks_missing = []
    for sc in scenes:
        role = str(sc.get('role') or '').lower()
        tags = str(sc.get('tags') or '').upper()
        is_peak = (
            role in peak_roles
            or bool(sc.get('emotion'))
            or 'HOOK' in tags or 'CHORUS' in tags
            or sc.get('performance_peak')
        )
        if not is_peak:
            continue
        sid = str(sc.get('id'))
        b = beat_by_id.get(sid) or {}
        accent = str(b.get('accent') or sc.get('accent') or sc.get('musical_cue') or '').lower()
        cue = str(b.get('musical_cue') or sc.get('musical_cue') or '')
        if accent not in ACCENTS and not cue:
            peaks_missing.append(sid)
    check['performance_on_accents'] = not peaks_missing
    if peaks_missing and multi:
        issues.append({
            'severity': 'error', 'code': 'performance_off_accent',
            'detail': (
                'Emotional performance peaks must sit on musical accents '
                f'(performance_beats.accent or musical_cue): {peaks_missing[:8]}'
            ),
        })

    # Sound-off readable: majority of scenes should have an action or prop_state
    actionable = 0
    for sc in scenes:
        blob = f"{sc.get('action', '')} {sc.get('prompt', '')} {sc.get('prop_state', '')}"
        if re.search(r'\b[a-z]{4,}\b', blob, re.I):
            actionable += 1
    check['sound_off_readable'] = (not scenes) or (actionable >= max(1, int(0.6 * len(scenes))))
    if scenes and not check['sound_off_readable']:
        issues.append({
            'severity': 'error', 'code': 'not_sound_off_readable',
            'detail': 'Too many scenes lack visible action/prop state for sound-off reading.',
        })

    # Timeline gfx share (optional)
    if timeline is not None:
        total = 0.0
        gfx = 0.0
        for sh in timeline:
            t0 = float(sh.get('t0', 0.0))
            t1 = float(sh.get('t1', t0))
            dur = max(0.0, t1 - t0)
            total += dur
            src = sh.get('src')
            kind = sh.get('kind') or ''
            if kind == 'gfx' or (isinstance(src, (list, tuple)) and src and src[0] == 'gfx'):
                gfx += dur
            if sh.get('gfx') or sh.get('is_gfx'):
                gfx += dur
        share = (gfx / total) if total > 0 else 0.0
        check['gfx_share_ok'] = share <= float(os.environ.get('GV_MAX_GFX_SHARE', '0.10'))
        if not check['gfx_share_ok']:
            issues.append({
                'severity': 'error', 'code': 'gfx_share_exceeded',
                'detail': f'gfx_share={share:.1%} exceeds 10% runtime cap',
                'gfx_s': round(gfx, 2), 'total_s': round(total, 2),
            })

    errors = [i for i in issues if i.get('severity') == 'error']
    ok = not errors
    summary = (
        f"narrative_qa: {'ok' if ok else 'FAIL'} "
        f"premise={'yes' if check.get('has_premise') else 'no'} "
        f"retell={'yes' if check.get('has_viewer_retell') else 'no'} "
        f"payoff_first={'yes' if check.get('payoff_designed_first') else 'no'} "
        f"required_shots={req[:8]} errors={len(errors)}"
    )
    return NarrativeReport(ok=ok, issues=issues, checklist=check, summary=summary)


def assert_narrative_qa(plan: dict, timeline: Optional[Sequence[dict]] = None) -> NarrativeReport:
    rep = narrative_checklist(plan, timeline)
    if rep.ok:
        return rep
    raise JobFailure(
        kind=FailureKind.NARRATIVE,
        message=rep.summary + ' | ' + '; '.join(
            e.get('detail', '') for e in rep.issues if e.get('severity') == 'error'
        )[:400],
        stage='narrative_qa',
        hint=(
            'Fix premise, viewer_retell, payoff_design-first, lyric-prop consequences, '
            'diegetic preplanned graphics, location transforms, and accent-timed performance.'
        ),
        details=rep.to_dict(),
    )
