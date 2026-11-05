"""Shared pre-generate / resume coherence gates for karaoke + PopVideoJob.

Every generate and resume path must pass these gates. Missing storyboard review,
inferred-away consequence edges, or unplanned narrative gfx all hard-abort.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .creative_contract import (
    apply_no_text_to_scenes,
    ensure_creative_contract,
    validate_creative_contract,
)
from .coverage import plan_fingerprint
from .failures import FailureKind, JobFailure
from .graphics_lint import assert_plan_graphics
from .narrative_gate import assert_narrative_qa, assert_storyboard_review
from .plan_fix import fix_plan_singing
from .prompt_gate import gate_prompts
from .story_model import assert_story_model, ensure_scene_states


def apply_coherence_gates(plan: dict,
                          *,
                          song_idea: str = '',
                          lyric_line_count: Optional[int] = None,
                          storyboard_review: Optional[dict] = None,
                          sing_enabled: Optional[bool] = None,
                          require_storyboard: bool = True,
                          allow_large: bool = False,
                          creative_mode: Optional[str] = None) -> Dict[str, Any]:
    """Run all pre-generation narrative/story gates. Returns updated plan + reports.

    Raises JobFailure on any hard abort. Does **not** infer consequence edges.
    """
    reports: Dict[str, Any] = {}
    sing_on = (
        bool(sing_enabled) if sing_enabled is not None
        else os.environ.get('GV_SING', '0') == '1'
    )
    P = fix_plan_singing(plan, sing_enabled=sing_on)
    # Never auto-wire requires_next — missing authored edges must fail assert_story_model.
    P = ensure_scene_states(P, infer_edges=False)
    P = ensure_creative_contract(P, song_idea=song_idea)
    P = apply_no_text_to_scenes(P)

    rev = storyboard_review if storyboard_review is not None else P.get('storyboard_review')
    if rev:
        P['storyboard_review'] = rev
    assert_storyboard_review(P, rev, require_present=require_storyboard)
    reports['storyboard_review'] = {
        'score': (rev or {}).get('score'), 'verdict': (rev or {}).get('verdict'),
        'ok': True,
    }

    srep = assert_story_model(
        P, lyric_line_count=lyric_line_count, allow_large=allow_large,
        require_states=True, strict_edges=True,
    )
    reports['story_model'] = srep.to_dict()

    # Picture-first graphics plan before narrative checklist (typed GFX vs NARRATIVE).
    grep = assert_plan_graphics(P)
    reports['gfx_plan_lint'] = grep.to_dict()

    nrep = assert_narrative_qa(P)
    reports['narrative_qa'] = nrep.to_dict()

    mode = creative_mode or os.environ.get('GV_CREATIVE_CONTRACT_MODE', 'adaptive')
    crep = validate_creative_contract(P, mode=mode, song_idea=song_idea)
    P['creative_contract'] = crep.contract
    reports['creative_contract'] = crep.to_dict()
    if not crep.ok and os.environ.get('GV_CREATIVE_CONTRACT_ABORT', '0') == '1':
        raise JobFailure(
            kind=FailureKind.NARRATIVE,
            message=f'creative contract failed: {crep.summary}',
            stage='creative_contract',
            hint='Fix visual premise, world contrast, or graphics_plan.',
            details=crep.to_dict(),
        )

    gated = gate_prompts(P.get('scenes') or [])
    P['scenes'] = gated['scenes']
    reports['prompt_gate'] = {k: gated[k] for k in ('kept', 'dropped', 'critical_fail', 'ok')}
    if gated['critical_fail']:
        raise JobFailure(
            kind=FailureKind.PLAN,
            message=f"prompt gate: {gated['critical_fail']} story-critical prompts failed rewrite",
            stage='prompt_gate',
            hint='Rewrite story-critical prompts; do not silent-drop them.',
            details=gated.get('report') or {},
        )

    P['plan_fp'] = plan_fingerprint(P)
    P['performance_mode'] = P.get('performance_mode') or ('sing' if sing_on else 'mouths_closed')
    reports['performance_mode'] = P['performance_mode']
    reports['ok'] = True
    return {'plan': P, 'reports': reports}
