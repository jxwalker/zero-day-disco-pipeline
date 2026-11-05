"""Typed, actionable job failures — never assemble an incomplete story silently."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class FailureKind(str, Enum):
    """One job → finished MP4 **or** one of these typed failures."""

    COVERAGE = 'coverage'
    NARRATIVE = 'narrative'
    STORYBOARD = 'storyboard'
    ART = 'art'
    CONSEQUENCE = 'consequence'
    PLAN = 'plan'
    GFX = 'gfx'
    SING = 'sing'
    GATE = 'gate'
    BUDGET = 'budget'
    IDENTITY = 'identity'
    RENDER = 'render'


# Map stages → default failure kind when a gate raises.
STAGE_KIND = {
    'coverage': FailureKind.COVERAGE,
    'storyboard_review': FailureKind.STORYBOARD,
    'narrative_qa': FailureKind.NARRATIVE,
    'story_model': FailureKind.PLAN,
    'art_bible': FailureKind.ART,
    'consequence': FailureKind.CONSEQUENCE,
    'gfx_lint': FailureKind.GFX,
    'sing_policy': FailureKind.SING,
    'creative_contract': FailureKind.NARRATIVE,
    'prompt_gate': FailureKind.PLAN,
    'timeline': FailureKind.COVERAGE,
    'gate': FailureKind.GATE,
    'render': FailureKind.BUDGET,
}


@dataclass
class JobFailure(RuntimeError):
    """Structured failure for unattended SaaS / PopVideoJob consumers."""

    kind: FailureKind
    message: str
    stage: str = ''
    hint: str = ''
    details: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 8

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)

    def to_dict(self) -> dict:
        return {
            'ok': False,
            'kind': self.kind.value if isinstance(self.kind, FailureKind) else str(self.kind),
            'error': self.message,
            'stage': self.stage,
            'hint': self.hint,
            'details': self.details,
            'exit_code': self.exit_code,
            'finished_mp4': False,
        }


def failure_from_exception(exc: BaseException, *, stage: str = '') -> JobFailure:
    """Normalize CoverageError / WatchdogError / JobFailure into a typed JobFailure."""
    if isinstance(exc, JobFailure):
        return exc
    kind = STAGE_KIND.get(stage, FailureKind.PLAN)
    details: Dict[str, Any] = {}
    hint = ''
    exit_code = 8
    if hasattr(exc, 'details') and isinstance(getattr(exc, 'details'), dict):
        details = dict(exc.details)
    if hasattr(exc, 'hint'):
        hint = str(getattr(exc, 'hint') or '')
    if hasattr(exc, 'exit_code'):
        exit_code = int(getattr(exc, 'exit_code') or 8)
    if hasattr(exc, 'stage') and not stage:
        stage = str(getattr(exc, 'stage') or '')
        kind = STAGE_KIND.get(stage, kind)
    # CoverageError subclass names
    name = type(exc).__name__
    if 'Coverage' in name or 'Timeline' in name:
        kind = FailureKind.COVERAGE
    msg = str(exc)
    lower = msg.lower()
    if 'gfx' in lower or 'graphics' in lower or 'black-void' in lower:
        kind = FailureKind.GFX
    elif 'sing' in lower and any(t in lower for t in ('reuse', 'share', 'policy', 'zero sing')):
        kind = FailureKind.SING
    elif 'storyboard' in lower or 'must not go to camera' in lower:
        kind = FailureKind.STORYBOARD
    elif 'art' in lower or 'clay' in lower or 'cartoon' in lower:
        kind = FailureKind.ART
    elif 'consequence' in lower or 'requires_next' in lower:
        kind = FailureKind.CONSEQUENCE
    elif 'narrative' in lower or 'premise' in lower or 'bookend' in lower:
        kind = FailureKind.NARRATIVE
    return JobFailure(
        kind=kind, message=msg, stage=stage or getattr(exc, 'stage', '') or '',
        hint=hint, details=details, exit_code=exit_code,
    )


def finished_ok(*, video_path: str = '', report: Optional[dict] = None) -> dict:
    """Success contract: finished MP4 (or dry-run gates_passed) with no typed failure."""
    return {
        'ok': True,
        'kind': None,
        'finished_mp4': bool(video_path),
        'video_path': video_path or '',
        'report': report or {},
    }
