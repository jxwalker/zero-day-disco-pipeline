"""Lip-sync gate: never pin failing takes; cut away; offset search; min source resolution.

Production failure: FINALIZE pinned sub-0.25 and negative scores; every offset was 0.0;
SING clips at 832x480 left mouths ~150 px tall after upscale.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .constants import LIPSYNC_MIN_SCORE, LIPSYNC_OFFSETS_MS, SING_MIN_HEIGHT


@dataclass
class LipsyncDecision:
    action: str            # 'pin' | 'cutaway'
    take: Optional[str]
    score: Optional[float]
    offset_s: float = 0.0
    reason: str = ''
    cutaway: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'action': self.action, 'take': self.take, 'score': self.score,
            'offset_s': self.offset_s, 'reason': self.reason, 'cutaway': self.cutaway,
        }


def offset_candidates(offsets_ms: Sequence[int] = LIPSYNC_OFFSETS_MS) -> List[float]:
    """Audio timing offsets (seconds) to search when scoring a take."""
    return [ms / 1000.0 for ms in offsets_ms]


def best_offset(scores_by_offset: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Pick (offset_s, score) with the highest score. Empty -> (0.0, -1.0)."""
    if not scores_by_offset:
        return 0.0, -1.0
    return max(scores_by_offset, key=lambda x: x[1])


def decide_take(takes: Sequence[dict],
                *,
                min_score: Optional[float] = None,
                cutaway: Optional[str] = None) -> LipsyncDecision:
    """Choose the best take at/above threshold; otherwise cut away to B-roll.

    Each take: ``{path, score, offset_s?}``. Negative and sub-threshold scores are never pinned.
    """
    thr = LIPSYNC_MIN_SCORE if min_score is None else min_score
    ranked = sorted(
        (t for t in takes if t.get('score') is not None),
        key=lambda t: float(t['score']),
        reverse=True,
    )
    for t in ranked:
        sc = float(t['score'])
        if sc >= thr:
            return LipsyncDecision(
                action='pin', take=t.get('path'), score=sc,
                offset_s=float(t.get('offset_s') or 0.0),
                reason=f'score {sc:.3f} >= {thr}',
            )
    best = ranked[0] if ranked else None
    return LipsyncDecision(
        action='cutaway',
        take=None,
        score=float(best['score']) if best else None,
        offset_s=0.0,
        reason=(f"best score {float(best['score']):.3f} < {thr}; cut away"
                if best else 'no scored takes; cut away'),
        cutaway=cutaway,
    )


def probe_height(path: str) -> int:
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=height', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=30,
        )
        return int((r.stdout or '0').strip().splitlines()[0] or 0)
    except Exception:
        return 0


def ensure_min_height(src: str, dst: str,
                      *, min_h: Optional[int] = None) -> dict:
    """Upscale a SING clip to at least ``min_h`` (default GV_SING_MIN_H=720). No-op if already tall enough."""
    need = SING_MIN_HEIGHT if min_h is None else min_h
    h = probe_height(src)
    if h >= need:
        if os.path.abspath(src) != os.path.abspath(dst):
            # copy without re-encode when possible
            try:
                import shutil
                shutil.copyfile(src, dst)
            except OSError:
                pass
        return {'ok': True, 'scaled': False, 'height': h, 'out': src if h >= need and src == dst else dst}
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
    vf = f"scale=-2:{need}"
    r = subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', vf, '-c:v', 'libx264',
         '-preset', 'fast', '-crf', '18', '-c:a', 'copy', dst],
        capture_output=True, text=True, timeout=600,
    )
    ok = r.returncode == 0 and os.path.exists(dst)
    return {'ok': ok, 'scaled': True, 'height_in': h, 'height_out': need if ok else h,
            'out': dst if ok else src, 'err': (r.stderr or '')[-300:]}


def search_offsets_and_decide(take_paths: Sequence[str],
                              score_fn,
                              *,
                              offsets_ms: Sequence[int] = LIPSYNC_OFFSETS_MS,
                              min_score: Optional[float] = None,
                              cutaway: Optional[str] = None) -> LipsyncDecision:
    """Run ``score_fn(path, offset_s) -> float`` across offset grid; decide pin vs cutaway.

    ``score_fn`` is injected so unit tests need no model; production wires SyncNet / similar.
    """
    scored = []
    for path in take_paths:
        pairs = []
        for off in offset_candidates(offsets_ms):
            try:
                sc = float(score_fn(path, off))
            except Exception:
                sc = -9.0
            pairs.append((off, sc))
        off, sc = best_offset(pairs)
        scored.append({'path': path, 'score': sc, 'offset_s': off})
    return decide_take(scored, min_score=min_score, cutaway=cutaway)
