"""Coverage and story-critical gates. Abort clearly; never ship a cut missing twists."""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Iterable, List, Optional, Sequence, Set, Union

from .constants import CRITICAL_TAGS, GATE_EXIT_CODE, MIN_CLIP_COVERAGE

try:
    from .story_model import required_shot_ids as _structural_required_ids
except ImportError:  # pragma: no cover
    def _structural_required_ids(plan: dict) -> List[str]:
        return []


class CoverageError(RuntimeError):
    """Raised when clip coverage or required climax/payoff presence fails. Exit code GATE_EXIT_CODE."""

    exit_code = GATE_EXIT_CODE
    kind = 'coverage'

    def __init__(self, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}
        self.stage = 'coverage'
        self.hint = 'Do not assemble — regenerate missing required shots or abort the job.'


def plan_fingerprint(plan: dict) -> str:
    """Stable fingerprint of scene ids + prompts so pinned timelines cannot outlive a re-plan."""
    scenes = plan.get('scenes') or []
    payload = [{'id': s.get('id'), 'prompt': (s.get('prompt') or '')[:240],
                'tags': s.get('tags'), 'role': s.get('role'),
                'structural_role': s.get('structural_role')} for s in scenes]
    payload.append({'required_shots': list(plan.get('required_shots') or plan.get('climax_ids') or [])})
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def _tagged(scene: dict, tags: Sequence[str]) -> bool:
    blob = ' '.join(str(scene.get(k, '')) for k in
                    ('id', 'prompt', 'tags', 'role', 'beat', 'structural_role')).upper()
    return any(f'[{t}]' in blob or f'_{t}' in blob or f' {t} ' in f' {blob} ' for t in tags)


def critical_scene_ids(scenes: Iterable[dict],
                       tags: Sequence[str] = CRITICAL_TAGS) -> List[str]:
    """Legacy tag-based critical ids (TWIST/PAYOFF/TURN/…). Prefer required_shot_ids(plan)."""
    return [str(s.get('id')) for s in scenes if s.get('id') and _tagged(s, tags)]


def required_payoff_ids(plan_or_scenes: Union[dict, Sequence[dict]],
                       *,
                       tags: Sequence[str] = CRITICAL_TAGS) -> List[str]:
    """Structural required climax/twist/payoff ids.

    Prefer plan.required_shots / structural_role; fall back to critical tags for compat.
    """
    if isinstance(plan_or_scenes, dict) and (
        'scenes' in plan_or_scenes or 'required_shots' in plan_or_scenes
        or 'climax_ids' in plan_or_scenes
    ):
        plan = plan_or_scenes
        structural = _structural_required_ids(plan)
        if structural:
            return structural
        scenes = plan.get('scenes') or []
        return critical_scene_ids(scenes, tags)
    scenes = list(plan_or_scenes)  # type: ignore[arg-type]
    return critical_scene_ids(scenes, tags)


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


def _normalize_rejected(rejected: Iterable[str]) -> Set[str]:
    """Map clip_rejected paths / basenames → scene ids."""
    out: Set[str] = set()
    for r in rejected or []:
        s = str(r)
        base = s.replace('\\', '/').split('/')[-1]
        # strip extensions and QC suffixes: s59.mp4.qcfail.mp4 → s59
        base = re.sub(r'\.(mp4|png|webm)(\.(qcfail|screen|reject).*)?$', '', base, flags=re.I)
        base = re.sub(r'\.(qcfail|screen|reject).*$', '', base, flags=re.I)
        base = base.replace('_f', '') if base.endswith('_f') else base
        # also accept raw id
        out.add(base)
        # path like .../s59.mp4
        stem = os.path.splitext(base)[0]
        out.add(stem)
        if '/' in s:
            out.add(os.path.splitext(os.path.basename(s))[0])
    return {x for x in out if x}


def assert_coverage(scenes: Sequence[dict], available_ids: Iterable[str],
                    *, min_ratio: Optional[float] = None,
                    require_critical: bool = True,
                    tags: Sequence[str] = CRITICAL_TAGS,
                    plan: Optional[dict] = None,
                    rejected_ids: Optional[Iterable[str]] = None) -> dict:
    """Abort if coverage < min_ratio or any required climax/payoff scene has no clip.

    When ``plan`` is provided, required shots come from structural IDs
    (``required_shots`` / ``structural_role``), not blind keyword matching alone.

    When ``rejected_ids`` intersects the required set → abort (rejected climax ≠ silent hole).
    """
    min_r = MIN_CLIP_COVERAGE if min_ratio is None else min_ratio
    cov = clip_coverage(scenes, available_ids)
    have = {str(x) for x in available_ids}
    if plan is not None:
        crit = required_payoff_ids(plan, tags=tags)
    else:
        crit = critical_scene_ids(scenes, tags)
    missing_crit = [c for c in crit if c not in have]
    cov['critical'] = crit
    cov['required_shots'] = crit
    cov['missing_critical'] = missing_crit
    cov['missing_twist_payoff'] = missing_crit  # alias used by production status/gate reports
    errors = []
    if cov['wanted'] and cov['ratio'] < min_r:
        errors.append(
            f"clip coverage {cov['pct']}% < {100 * min_r:.0f}% "
            f"({cov['have']}/{cov['wanted']}); missing={missing_crit and missing_crit or cov['missing'][:12]}"
        )
    if require_critical and missing_crit:
        errors.append(f"missing TWIST/PAYOFF/required climax clips: {missing_crit}")

    # Rejected required shots must abort — never assemble around a deleted climax.
    if rejected_ids is not None and crit:
        rej = _normalize_rejected(rejected_ids)
        rejected_required = sorted({c for c in crit if c in rej})
        cov['rejected_required'] = rejected_required
        if rejected_required:
            errors.append(
                f"required climax/payoff clips were QC-rejected: {rejected_required} "
                f"(cannot assemble without payoff)"
            )

    if errors:
        raise CoverageError('; '.join(errors), details=cov)
    return cov


def assert_rejected_required(plan: dict, rejected_ids: Iterable[str],
                             *, tags: Sequence[str] = CRITICAL_TAGS) -> List[str]:
    """Standalone check: rejected ∩ required_shots → CoverageError."""
    crit = required_payoff_ids(plan, tags=tags)
    rej = _normalize_rejected(rejected_ids)
    hit = sorted({c for c in crit if c in rej})
    if hit:
        raise CoverageError(
            f"required climax/payoff clips were QC-rejected: {hit}",
            details={'required_shots': crit, 'rejected_required': hit,
                     'missing_twist_payoff': hit},
        )
    return hit


def gate_score_should_abort(score: Optional[float],
                            threshold: Optional[int] = None) -> bool:
    """True when a judge GATE score must hard-abort (sys.exit 8), not just hide from James."""
    if score is None:
        return False
    thr = int(os.environ.get('GV_GATE_ABORT_SCORE', '80')) if threshold is None else threshold
    return float(score) < thr
