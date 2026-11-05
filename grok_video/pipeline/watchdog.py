"""Progress watchdog with actionable errors (not silent hangs / vague failures)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


class WatchdogError(RuntimeError):
    """Raised when a stage stalls or reports an actionable failure."""

    def __init__(self, message: str, *, stage: str = '', hint: str = '', details: Optional[dict] = None):
        super().__init__(message)
        self.stage = stage
        self.hint = hint
        self.details = details or {}

    def actionable(self) -> str:
        parts = [str(self)]
        if self.stage:
            parts.append(f'stage={self.stage}')
        if self.hint:
            parts.append(f'hint: {self.hint}')
        return ' | '.join(parts)


@dataclass
class StageEvent:
    stage: str
    status: str          # start | progress | ok | fail
    t: float
    message: str = ''
    pct: Optional[float] = None
    hint: str = ''

    def to_dict(self) -> dict:
        return {
            'stage': self.stage, 'status': self.status, 't': self.t,
            'message': self.message, 'pct': self.pct, 'hint': self.hint,
        }


HINTS = {
    'plan': 'Re-run with --replan after fixing lyrics/stories; check plan.json.',
    'creative_contract': 'Set visual_premise, character anchors, graphics_plan (model_renders_text=false). '
                         'Dual worlds must contrast on grade/camera/design; location_arcs need state changes.',
    'prompt_gate': 'Inspect prompt_gate report; rewrite incompatible prompts; do not silent-drop story shots.',
    'generate': 'Check Grok auth (`grok login`), budget, and cache under work/*/grok/.',
    'screen_check': 'See screen_check_*.json; cast/robots should not die via other_problem.',
    'coverage': 'Fewer than 90% of scenes have clips, or TWIST/PAYOFF missing — abort, do not assemble.',
    'timeline': 'Rebuild from scene order; delete stale timeline_pinned.json if plan_fp mismatch.',
    'lipsync': 'Failed takes must cut away; run offset search; SING sources >= 720p height.',
    'overlays': 'Ensure GV_NEWS_TEXT=1 and overlay_texts.json is written from plan story_text/graphics_plan. '
                'HUD/kinetic/terminal are edit-composited; never model-burned.',
    'render': 'Budget exhausted or local fallback failed; reuse cache before regenerating stills.',
}


@dataclass
class ProgressWatchdog:
    path: str
    stall_s: float = 900.0
    events: List[StageEvent] = field(default_factory=list)
    _last: Dict[str, float] = field(default_factory=dict)
    _on_event: Optional[Callable[[StageEvent], None]] = None

    def _emit(self, ev: StageEvent) -> None:
        self.events.append(ev)
        self._last[ev.stage] = ev.t
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or '.', exist_ok=True)
            json.dump([e.to_dict() for e in self.events[-200:]], open(self.path, 'w'), indent=1)
        except OSError:
            pass
        if self._on_event:
            self._on_event(ev)

    def start(self, stage: str, message: str = '') -> None:
        self._emit(StageEvent(stage, 'start', time.time(), message=message,
                              hint=HINTS.get(stage, '')))

    def progress(self, stage: str, pct: float, message: str = '') -> None:
        self._emit(StageEvent(stage, 'progress', time.time(), message=message, pct=pct,
                              hint=HINTS.get(stage, '')))

    def ok(self, stage: str, message: str = '') -> None:
        self._emit(StageEvent(stage, 'ok', time.time(), message=message))

    def fail(self, stage: str, message: str, *, hint: str = '') -> None:
        h = hint or HINTS.get(stage, '')
        self._emit(StageEvent(stage, 'fail', time.time(), message=message, hint=h))
        raise WatchdogError(message, stage=stage, hint=h)

    def check_stall(self, stage: str) -> None:
        t0 = self._last.get(stage)
        if t0 is None:
            return
        dt = time.time() - t0
        if dt > self.stall_s:
            raise WatchdogError(
                f'stage {stage} stalled for {dt:.0f}s (limit {self.stall_s:.0f}s)',
                stage=stage,
                hint=HINTS.get(stage, 'Inspect status.json and the stage log; resume with --skip-gen if media exists.'),
                details={'stalled_s': dt},
            )

    def summary(self) -> dict:
        fails = [e.to_dict() for e in self.events if e.status == 'fail']
        return {
            'events': len(self.events),
            'fails': fails,
            'last_by_stage': {k: v for k, v in self._last.items()},
            'ok': not fails,
        }
