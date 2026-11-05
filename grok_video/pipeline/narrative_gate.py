"""Narrative QA + storyboard hard gate (Watch Me checklist).

Lyric timing stays for captions; story structure is gated here before any generation spend.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .failures import FailureKind, JobFailure
from .story_model import required_shot_ids

# Storyboard review must clear this score (1–10) or hard-abort before generation.
STORYBOARD_MIN_SCORE = int(os.environ.get('GV_STORYBOARD_MIN_SCORE', '7'))
MUST_NOT_CAMERA_RE = re.compile(
    r'must not go to camera|do not (?:send|go) to camera|not ready for camera|'
    r'refuse(?:s)? (?:to )?film|block(?:s)? (?:the )?shoot|halt production',
    re.I,
)


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
                          min_score: Optional[int] = None) -> Optional[str]:
    """Return abort reason if storyboard review is below threshold or forbids camera.

    ``review`` is the dict saved on plan['storyboard_review'] / storyboard_review.json.
    Missing review is not an abort (offline / GV_STORYBOARD=0); only an explicit bad review.
    """
    if not review:
        return None
    thr = STORYBOARD_MIN_SCORE if min_score is None else min_score
    verdict = str(review.get('verdict') or review.get('summary') or '')
    if MUST_NOT_CAMERA_RE.search(verdict):
        return (
            f"storyboard review forbids camera: {verdict[:200]!r} "
            f"(must not go to camera → hard-abort before generation)"
        )
    # Also scan free-text notes / issues
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
                             min_score: Optional[int] = None) -> None:
    """Hard-abort on bad storyboard review. Raises JobFailure(STORYBOARD)."""
    rev = review if review is not None else (plan.get('storyboard_review') or {})
    reason = storyboard_must_abort(rev, min_score=min_score)
    if reason:
        raise JobFailure(
            kind=FailureKind.STORYBOARD,
            message=reason,
            stage='storyboard_review',
            hint='Fix the storyboard (premise, cast lock, consequence) and re-review before generate.',
            details={'review': {k: rev.get(k) for k in ('score', 'verdict') if k in rev}},
        )


def narrative_checklist(plan: dict, timeline: Optional[Sequence[dict]] = None) -> NarrativeReport:
    """Watch Me checklist from plan (+ optional timeline) — sound-off readable story.

    Hard errors (abort):
      - no one-sentence visual premise
      - no required climax/twist/payoff structural ids declared when scenes imply a twisty arc
      - no bookend / payoff closure signal on a multi-scene story
      - consequence-required actions without edges (delegated detail lives on story_model;
        here we only require that required_shots is non-empty when structural roles exist)
    Soft warnings: thin cast anchors, missing graphics_plan object.
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
    check['has_premise'] = bool(premise)
    if not premise:
        issues.append({
            'severity': 'error', 'code': 'missing_premise',
            'detail': 'No one-sentence visual premise; every shot must advance one readable arc.',
        })

    scenes = list(plan.get('scenes') or [])
    req = required_shot_ids(plan)
    check['has_required_shots'] = bool(req)
    # Multi-scene stories that declare twisty tags/roles must expose structural required ids
    structural = [s for s in scenes if (s.get('structural_role') or '').lower() in {
        'twist', 'payoff', 'climax', 'reveal', 'turn', 'final_payoff',
    }]
    if structural and not req:
        issues.append({
            'severity': 'error', 'code': 'missing_required_shot_ids',
            'detail': 'Structural twist/payoff scenes present but required_shots is empty.',
        })
    elif len(scenes) >= 8 and not req:
        # Ambition without a declared climax list → narrative risk
        issues.append({
            'severity': 'warning', 'code': 'no_declared_climax',
            'detail': 'Plan has 8+ scenes but no required_shots / climax structural ids.',
        })

    # Bookend / payoff closure: first and last scene, or explicit bookend role, or required payoff
    roles = {(s.get('structural_role') or s.get('role') or '').lower() for s in scenes}
    has_bookend = 'bookend' in roles or 'payoff' in roles or 'final_payoff' in roles or bool(req)
    if scenes and str(scenes[0].get('id')) and str(scenes[-1].get('id')):
        # Same location token across first/last counts as bookend signal
        def loc_tok(sc: dict) -> str:
            blob = (sc.get('prompt') or '').lower()
            for w in ('sofa', 'couch', 'living room', 'lab', 'rooftop', 'kitchen', 'bedroom'):
                if w in blob:
                    return w
            return ''
        if loc_tok(scenes[0]) and loc_tok(scenes[0]) == loc_tok(scenes[-1]):
            has_bookend = True
    check['has_bookend_or_payoff'] = bool(has_bookend)
    if len(scenes) >= 4 and not has_bookend:
        issues.append({
            'severity': 'error', 'code': 'missing_bookend_or_payoff',
            'detail': 'Story lacks bookend/payoff closure (structural payoff id or matching open/close).',
        })

    # Cast anchors (soft unless empty on multi-cast prompts)
    anchors = cc.get('character_anchors') or plan.get('character_anchors') or []
    check['has_cast_lock'] = bool(anchors) or bool(plan.get('lead') or plan.get('wardrobe'))
    if len(scenes) >= 3 and not check['has_cast_lock']:
        issues.append({
            'severity': 'warning', 'code': 'missing_cast_lock',
            'detail': 'No character styling anchors / lead wardrobe lock.',
        })

    # Graphics plan object present (may be empty lists) — cards must not carry the story alone
    gp = cc.get('graphics_plan') or plan.get('graphics_plan')
    check['has_graphics_plan'] = gp is not None
    if gp is None and len(scenes) >= 3:
        issues.append({
            'severity': 'warning', 'code': 'missing_graphics_plan',
            'detail': 'Declare graphics_plan (code-built overlays on live plates; may be empty).',
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
        hint='Fix premise, structural required_shots, bookend/payoff, and sound-off action before GATE.',
        details=rep.to_dict(),
    )
