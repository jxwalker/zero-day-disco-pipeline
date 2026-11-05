"""Hardened karaoke pipeline modules (postmortem 2026-11-05).

Service-facing entry: ``pipeline.service.PopVideoJob``.
All gates are pure / local-first so they can be unit-tested without GPUs or accounts.
"""
from .coverage import CoverageError, assert_coverage, plan_fingerprint
from .identity import (
    CharacterRefs,
    duplicate_lead_flags,
    ref_images_for_scene,
    singing_allowed,
)
from .lipsync import LipsyncDecision, decide_take, offset_candidates, ensure_min_height
from .overlays import (
    NO_TEXT_NEG,
    OverlaySpec,
    build_overlay_texts,
    model_text_forbidden,
    terminal_must_be_blank,
)
from .plan_fix import fix_plan_singing
from .prompt_gate import PromptGateResult, gate_prompt, gate_prompts, strip_lock_leaks
from .renderer import RenderBudget, RenderPlan, plan_renders
from .screen_policy import ScreenVerdict, evaluate_screen_result, waive_other_problem
from .service import PopVideoJob, PopVideoRequest, PopVideoResult
from .timeline_policy import TimelineBuildError, build_scene_timeline, load_pinned_timeline
from .watchdog import ProgressWatchdog, WatchdogError

__all__ = [
    'CoverageError', 'assert_coverage', 'plan_fingerprint',
    'CharacterRefs', 'duplicate_lead_flags', 'ref_images_for_scene', 'singing_allowed',
    'LipsyncDecision', 'decide_take', 'offset_candidates', 'ensure_min_height',
    'NO_TEXT_NEG', 'OverlaySpec', 'build_overlay_texts', 'model_text_forbidden',
    'terminal_must_be_blank',
    'fix_plan_singing',
    'PromptGateResult', 'gate_prompt', 'gate_prompts', 'strip_lock_leaks',
    'RenderBudget', 'RenderPlan', 'plan_renders',
    'ScreenVerdict', 'evaluate_screen_result', 'waive_other_problem',
    'PopVideoJob', 'PopVideoRequest', 'PopVideoResult',
    'TimelineBuildError', 'build_scene_timeline', 'load_pinned_timeline',
    'ProgressWatchdog', 'WatchdogError',
]
