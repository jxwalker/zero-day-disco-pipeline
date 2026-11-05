"""Coverage and story-critical gates. Abort clearly; never ship a cut missing twists."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable, List, Optional, Sequence

from .constants import CRITICAL_TAGS, GATE_EXIT_CODE, MIN_CLIP_COVERAGE


class CoverageError(RuntimeError):
    """Raised when clip coverage or twist/payoff presence fails. Exit code GATE_EXIT_CODE."""

    exit_code = GATE_EXIT_CODE

    def __init__(self, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}


def plan_fingerprint(plan: dict) -> str:
    """Stable fingerprint of scene ids + prompts so pinned timelines cannot outlive a re-plan."""
    scenes = plan.get('scenes') or []
    payload = [{'id': s.get('id'), 'prompt': (s.get('prompt') or '')[:240],
                'tags': s.get('tags'), 'role': s.get('role')} for s in scenes]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def _tagged(scene: dict, tags: Sequence[str]) -> bool:
    blob = ' '.join(str(scene.get(k, '')) for k in ('id', 'prompt', 'tags', 'role', 'beat')).upper()
    return any(f'[{t}]' in blob or f'_{t}' in blob or f' {t} ' in f' {blob} ' for t in tags)


def critical_scene_ids(scenes: Iterable[dict],
                       tags: Sequence[str] = CRITICAL_TAGS) -> List[str]:
    return [str(s.get('id')) for s in scenes if s.get('id') and _tagged(s, tags)]


def clip_coverage(scenes: Sequence[dict], available_ids: Iterable[str]) -> dict:
    have = {str(x) for x in available_ids}
    wanted = [str(s.get('id')) for s in scenes if s.get('id')]
    present = [i for i in wanted if i in have]
    missing = [i for i in wanted if i not in have]
    ratio = (len(present) / len(wanted)) if wanted else 1.0
    return {
        'wanted': len(wanted),
        'have': len(present),
        'missing': missing,
        'ratio': round(ratio, 4),
        'pct': round(100 * ratio, 1),
    }


def assert_coverage(scenes: Sequence[dict], available_ids: Iterable[str],
                    *, min_ratio: Optional[float] = None,
                    require_critical: bool = True,
                    tags: Sequence[str] = CRITICAL_TAGS) -> dict:
    """Abort if coverage < min_ratio or any TWIST/PAYOFF/TURN scene has no clip.

    Returns the coverage report on success.
    """
    min_r = MIN_CLIP_COVERAGE if min_ratio is None else min_ratio
    cov = clip_coverage(scenes, available_ids)
    have = {str(x) for x in available_ids}
    crit = critical_scene_ids(scenes, tags)
    missing_crit = [c for c in crit if c not in have]
    cov['critical'] = crit
    cov['missing_critical'] = missing_crit
    errors = []
    if cov['wanted'] and cov['ratio'] < min_r:
        errors.append(
            f"clip coverage {cov['pct']}% < {100 * min_r:.0f}% "
            f"({cov['have']}/{cov['wanted']}); missing={missing_crit and missing_crit or cov['missing'][:12]}"
        )
    if require_critical and missing_crit:
        errors.append(f"missing TWIST/PAYOFF/TURN clips: {missing_crit}")
    if errors:
        raise CoverageError('; '.join(errors), details=cov)
    return cov


def gate_score_should_abort(score: Optional[float],
                            threshold: Optional[int] = None) -> bool:
    """True when a judge GATE score must hard-abort (sys.exit 8), not just hide from James."""
    if score is None:
        return False
    thr = int(os.environ.get('GV_GATE_ABORT_SCORE', '80')) if threshold is None else threshold
    return float(score) < thr
