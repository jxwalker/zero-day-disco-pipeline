"""Hardened karaoke pipeline modules (postmortem 2026-11-05 + Watch Me coherence).

Service-facing entry: ``pipeline.service.PopVideoJob``.
All gates are pure / local-first so they can be unit-tested without GPUs or accounts.

One job → finished MP4 **or** typed ``JobFailure`` (never assemble an incomplete story).
"""
from .coverage import (
    CoverageError, assert_coverage, assert_rejected_required,
    plan_fingerprint, required_payoff_ids,
)
from .creative_contract import (
    ContractReport,
    ensure_creative_contract,
    validate_creative_contract,
)
from .failures import FailureKind, JobFailure, failure_from_exception, finished_ok
from .graphics_lint import (
    assert_graphics_and_sing, assert_plan_graphics,
    lint_plan_graphics, lint_sing_reuse, lint_timeline_graphics,
)
from .plan_gates import apply_coherence_gates
from .identity import (
    CharacterRefs,
    duplicate_lead_flags,
    ref_images_for_scene,
    singing_allowed,
)
from .lipsync import LipsyncDecision, decide_take, offset_candidates, ensure_min_height
from .narrative_gate import (
    NarrativeReport,
    assert_narrative_qa,
    assert_storyboard_review,
    narrative_checklist,
    storyboard_must_abort,
)
from .overlays import (
    NO_TEXT_NEG,
    OverlaySpec,
    build_overlay_texts,
    model_text_forbidden,
    terminal_must_be_blank,
)
from .plan_fix import fix_plan_singing, assert_zero_sing
from .prompt_gate import PromptGateResult, gate_prompt, gate_prompts, strip_lock_leaks
from .renderer import RenderBudget, RenderPlan, plan_renders
from .screen_policy import ScreenVerdict, evaluate_screen_result, waive_other_problem
from .service import PopVideoJob, PopVideoRequest, PopVideoResult
from .story_model import (
    SceneState,
    StoryModelReport,
    assert_story_model,
    ensure_scene_states,
    required_shot_ids,
    validate_story_model,
)
from .timeline_policy import TimelineBuildError, build_scene_timeline, load_pinned_timeline
from .watchdog import ProgressWatchdog, WatchdogError

__all__ = [
    'CoverageError', 'assert_coverage', 'assert_rejected_required',
    'plan_fingerprint', 'required_payoff_ids',
    'ContractReport', 'ensure_creative_contract', 'validate_creative_contract',
    'FailureKind', 'JobFailure', 'failure_from_exception', 'finished_ok',
    'assert_graphics_and_sing', 'assert_plan_graphics',
    'lint_plan_graphics', 'lint_sing_reuse', 'lint_timeline_graphics',
    'apply_coherence_gates',
    'CharacterRefs', 'duplicate_lead_flags', 'ref_images_for_scene', 'singing_allowed',
    'LipsyncDecision', 'decide_take', 'offset_candidates', 'ensure_min_height',
    'NarrativeReport', 'assert_narrative_qa', 'assert_storyboard_review',
    'narrative_checklist', 'storyboard_must_abort',
    'NO_TEXT_NEG', 'OverlaySpec', 'build_overlay_texts', 'model_text_forbidden',
    'terminal_must_be_blank',
    'fix_plan_singing', 'assert_zero_sing',
    'PromptGateResult', 'gate_prompt', 'gate_prompts', 'strip_lock_leaks',
    'RenderBudget', 'RenderPlan', 'plan_renders',
    'ScreenVerdict', 'evaluate_screen_result', 'waive_other_problem',
    'PopVideoJob', 'PopVideoRequest', 'PopVideoResult',
    'SceneState', 'StoryModelReport', 'assert_story_model', 'ensure_scene_states',
    'required_shot_ids', 'validate_story_model',
    'TimelineBuildError', 'build_scene_timeline', 'load_pinned_timeline',
    'ProgressWatchdog', 'WatchdogError',
]
