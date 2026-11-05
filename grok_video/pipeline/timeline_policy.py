"""Timeline from script scene order; reuse caps; pin fingerprint; no BPM slot inflation.

Production failure: 76 BPM-paced slots filled by looping ~25 clips; stale timeline_pinned.json
reused across re-plans; no abort when twist/payoff clips were missing.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .constants import CLIP_MAX_USES
from .coverage import CoverageError, assert_coverage, plan_fingerprint


class TimelineBuildError(CoverageError):
    """Timeline cannot be built safely."""


@dataclass
class TimelineShot:
    scene_id: str
    src: str
    t0: float
    t1: float
    use_index: int = 0
    cutaway: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'scene_id': self.scene_id, 'src': self.src, 't0': round(self.t0, 3),
            't1': round(self.t1, 3), 'use_index': self.use_index,
            'cutaway': self.cutaway, **self.meta,
        }


def load_pinned_timeline(path: str, plan: dict) -> Optional[dict]:
    """Load a pinned timeline only when its plan_fp matches the current plan.

    Returns None (caller must rebuild) when missing, stale, or fingerprint mismatch.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        data = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        return None
    fp = plan_fingerprint(plan)
    if data.get('plan_fp') != fp:
        return None
    return data


def save_pinned_timeline(path: str, plan: dict, shots: Sequence[dict]) -> dict:
    data = {'plan_fp': plan_fingerprint(plan), 'shots': list(shots)}
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    json.dump(data, open(path, 'w'), indent=1)
    return data


def _available_map(available: Dict[str, str] | Iterable[str]) -> Dict[str, str]:
    if isinstance(available, dict):
        return {str(k): str(v) for k, v in available.items()}
    return {os.path.splitext(os.path.basename(p))[0]: str(p) for p in available}


def build_scene_timeline(scenes: Sequence[dict],
                         available: Dict[str, str] | Iterable[str],
                         *,
                         durations: Optional[Dict[str, float]] = None,
                         max_uses: Optional[int] = None,
                         default_dur: float = 1.9,
                         require_coverage: bool = True,
                         min_coverage: Optional[float] = None,
                         broll_pool: Optional[Sequence[str]] = None) -> List[TimelineShot]:
    """Build a timeline that follows script scene order using only available clips.

    - Order = plan scene list (not BPM slot count).
    - Each clip may appear at most ``max_uses`` times (default GV_CLIP_MAX_USES=2).
    - Missing non-critical scenes become cutaways from b-roll (also capped); missing
      critical scenes abort via assert_coverage.
    """
    avail = _available_map(available)
    cap = CLIP_MAX_USES if max_uses is None else max_uses
    if require_coverage:
        assert_coverage(scenes, avail.keys(), min_ratio=min_coverage)

    uses: Dict[str, int] = {}
    broll = list(broll_pool or [])
    broll_i = 0
    t = 0.0
    out: List[TimelineShot] = []

    def take_broll() -> Optional[str]:
        nonlocal broll_i
        tried = 0
        while tried < len(broll):
            path = broll[broll_i % len(broll)]
            broll_i += 1
            tried += 1
            key = os.path.splitext(os.path.basename(path))[0]
            if uses.get(key, 0) < cap:
                uses[key] = uses.get(key, 0) + 1
                return path
        return None

    for sc in scenes:
        sid = str(sc.get('id') or '')
        dur = float((durations or {}).get(sid, sc.get('dur', default_dur)))
        path = avail.get(sid)
        if path and uses.get(sid, 0) < cap:
            uses[sid] = uses.get(sid, 0) + 1
            out.append(TimelineShot(sid, path, t, t + dur, use_index=uses[sid] - 1))
        else:
            # Prefer regenerating shortfall signal over looping forever.
            alt = take_broll()
            if alt is None:
                if path and uses.get(sid, 0) >= cap:
                    raise TimelineBuildError(
                        f"clip reuse cap ({cap}) exhausted for {sid} and no b-roll left; "
                        f"regenerate shortfalls instead of looping",
                        details={'scene': sid, 'uses': dict(uses)},
                    )
                raise TimelineBuildError(
                    f"no available clip for scene {sid}",
                    details={'scene': sid, 'available': sorted(avail)},
                )
            out.append(TimelineShot(
                sid, alt, t, t + dur, use_index=0, cutaway=True,
                meta={'reason': 'missing_or_capped', 'wanted': sid},
            ))
        t += dur
    return out


def reuse_histogram(shots: Sequence[TimelineShot]) -> Dict[str, int]:
    hist: Dict[str, int] = {}
    for s in shots:
        key = os.path.splitext(os.path.basename(s.src))[0]
        hist[key] = hist.get(key, 0) + 1
    return hist


def assert_reuse_cap(shots: Sequence[TimelineShot], max_uses: Optional[int] = None) -> None:
    cap = CLIP_MAX_USES if max_uses is None else max_uses
    hist = reuse_histogram(shots)
    offenders = {k: v for k, v in hist.items() if v > cap}
    if offenders:
        raise TimelineBuildError(
            f"clip reuse exceeds cap {cap}: {offenders}",
            details={'histogram': hist},
        )
