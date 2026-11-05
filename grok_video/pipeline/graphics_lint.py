"""Picture-first graphics: overlays on live plates; short black-void caps; SING use ≤1.

Black-void corporate cards must never carry the story. Graphics integrate over in-focus
plates with short duration and share limits.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .failures import FailureKind, JobFailure
from .plan_fix import is_singing_shot

# Max continuous black-void / plate-less gfx (seconds)
MAX_BLACK_GFX_S = float(os.environ.get('GV_MAX_BLACK_GFX_S', '1.5'))
# Max gfx share of runtime
MAX_GFX_SHARE = float(os.environ.get('GV_MAX_GFX_SHARE', '0.10'))
# SING clips may appear at most once (no "SING reuse (no spare)")
SING_MAX_USES = int(os.environ.get('GV_SING_MAX_USES', '1'))

STORY_CARD_KINDS = frozenset({
    'headline', 'bignum', 'bars', 'post', 'feed', 'quote', 'compare', 'stamp',
    'story', 'card', 'terminal', 'code', 'browser', 'rows',
})


@dataclass
class GraphicsLintReport:
    ok: bool
    issues: List[dict] = field(default_factory=list)
    gfx_share: float = 0.0
    gfx_s: float = 0.0
    total_s: float = 0.0
    sing_uses: Dict[str, int] = field(default_factory=dict)
    summary: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'summary': self.summary, 'issues': self.issues,
            'gfx_share': self.gfx_share, 'gfx_s': self.gfx_s, 'total_s': self.total_s,
            'sing_uses': self.sing_uses,
            'errors': [i for i in self.issues if i.get('severity') == 'error'],
        }


def _shot_kind_src(shot: dict) -> Tuple[str, Any]:
    """Normalize timeline shot → (kind, src_id)."""
    src = shot.get('src')
    if isinstance(src, (list, tuple)) and src:
        kind = str(src[0])
        ref = src[1] if len(src) > 1 else ''
        return kind, ref
    if shot.get('kind'):
        return str(shot['kind']), shot.get('src') or shot.get('scene_id') or ''
    if shot.get('gfx') or shot.get('is_gfx') or shot.get('g'):
        return 'gfx', shot.get('g') or shot.get('src') or ''
    if shot.get('scene_id') or shot.get('src'):
        return 'clip', shot.get('scene_id') or shot.get('src')
    return 'unknown', ''


def _duration(shot: dict) -> float:
    if 'dur' in shot:
        return max(0.0, float(shot['dur']))
    t0 = float(shot.get('t0', 0.0))
    t1 = float(shot.get('t1', t0))
    return max(0.0, t1 - t0)


def _has_plate(shot: dict) -> bool:
    """True when gfx is integrated over a live plate (clip/still), not a black void."""
    if shot.get('plate') or shot.get('plate_src') or shot.get('over_plate'):
        return True
    src = shot.get('src')
    if isinstance(src, (list, tuple)) and len(src) >= 3:
        meta = src[2] if isinstance(src[2], dict) else {}
        if meta.get('plate') or meta.get('plate_src') or meta.get('over_plate'):
            return True
    meta = shot.get('meta') or {}
    if meta.get('plate') or meta.get('plate_src'):
        return True
    # Explicit black void markers
    if shot.get('black_void') or shot.get('on_black'):
        return False
    bg = str(shot.get('bg') or meta.get('bg') or '').lower()
    if bg in ('black', 'void', 'none', '#000', '#000000'):
        return False
    return False


def lint_timeline_graphics(timeline: Sequence[dict],
                           *,
                           max_black_s: Optional[float] = None,
                           max_share: Optional[float] = None) -> GraphicsLintReport:
    """Fail black-void story cards > max_black_s without a plate; fail gfx_share > max_share."""
    issues: List[dict] = []
    black_cap = MAX_BLACK_GFX_S if max_black_s is None else max_black_s
    share_cap = MAX_GFX_SHARE if max_share is None else max_share
    total = 0.0
    gfx_s = 0.0
    for i, sh in enumerate(timeline):
        dur = _duration(sh)
        total += dur
        kind, ref = _shot_kind_src(sh)
        if kind != 'gfx':
            continue
        gfx_s += dur
        gname = str(ref or sh.get('g') or '')
        is_story_card = (
            gname.lower() in STORY_CARD_KINDS
            or str(sh.get('g') or '').lower() in STORY_CARD_KINDS
            or sh.get('story_card')
        )
        plated = _has_plate(sh)
        if not plated and dur > black_cap:
            issues.append({
                'severity': 'error', 'code': 'black_void_gfx_too_long',
                'detail': (
                    f"shot[{i}] gfx {gname!r} duration {dur:.2f}s > {black_cap}s "
                    f"without live plate (black-void cards cannot carry the story)"
                ),
                'index': i, 'dur': dur, 'g': gname,
            })
        elif not plated and is_story_card and dur > black_cap:
            issues.append({
                'severity': 'error', 'code': 'story_card_on_black',
                'detail': f"shot[{i}] story card {gname!r} on black void for {dur:.2f}s",
                'index': i,
            })
        # Require plate: ref for any gfx that claims to be primary story carrier
        if sh.get('primary_story') and not plated:
            issues.append({
                'severity': 'error', 'code': 'gfx_missing_plate',
                'detail': f"shot[{i}] primary story gfx requires plate: clip/still ref",
                'index': i,
            })
    share = (gfx_s / total) if total > 0 else 0.0
    if total > 0 and share > share_cap + 1e-9:
        issues.append({
            'severity': 'error', 'code': 'gfx_share_exceeded',
            'detail': f'gfx_share={share:.1%} of runtime exceeds cap {share_cap:.0%}',
            'gfx_s': round(gfx_s, 3), 'total_s': round(total, 3),
        })
    errors = [i for i in issues if i.get('severity') == 'error']
    ok = not errors
    summary = (
        f"gfx_lint: {'ok' if ok else 'FAIL'} share={share:.1%} "
        f"gfx_s={gfx_s:.1f}/{total:.1f} errors={len(errors)}"
    )
    return GraphicsLintReport(
        ok=ok, issues=issues, gfx_share=round(share, 4),
        gfx_s=round(gfx_s, 3), total_s=round(total, 3), summary=summary,
    )


def lint_sing_reuse(timeline: Sequence[dict],
                    plan: Optional[dict] = None,
                    *,
                    max_uses: Optional[int] = None) -> GraphicsLintReport:
    """Fail when any SING source appears more than once (no spare redraw reuse)."""
    cap = SING_MAX_USES if max_uses is None else max_uses
    issues: List[dict] = []
    sing_ids = set()
    if plan:
        for sc in plan.get('scenes') or []:
            if sc.get('_sing') or is_singing_shot(sc):
                sing_ids.add(str(sc.get('id')))
    uses: Dict[str, int] = {}
    for i, sh in enumerate(timeline):
        kind, ref = _shot_kind_src(sh)
        sid = str(sh.get('scene_id') or ref or '')
        # Singing shots: clip sources tagged sing, or scene_id in sing set
        is_sing = (
            sh.get('sing') or sh.get('_sing')
            or sid in sing_ids
            or str(sh.get('role') or '').lower() in ('sing', 'singing', 'lipsync')
            or (isinstance(ref, str) and (ref.startswith('sing_') or '_sing' in ref))
        )
        if not is_sing or kind == 'gfx':
            continue
        key = os_path_stem(sid or str(ref))
        uses[key] = uses.get(key, 0) + 1
    offenders = {k: v for k, v in uses.items() if v > cap}
    if offenders:
        issues.append({
            'severity': 'error', 'code': 'sing_reuse',
            'detail': (
                f'SING reuse exceeds max_uses={cap}: {offenders}; '
                f'no "SING reuse (no spare)" — regenerate or cut away'
            ),
            'offenders': offenders,
        })
    ok = not issues
    summary = f"sing_reuse: {'ok' if ok else 'FAIL'} uses={uses}"
    return GraphicsLintReport(
        ok=ok, issues=issues, sing_uses=uses, summary=summary,
    )


def os_path_stem(path: str) -> str:
    base = path.replace('\\', '/').split('/')[-1]
    if base.endswith('.mp4') or base.endswith('.png'):
        return base.rsplit('.', 1)[0]
    return base


def assert_graphics_and_sing(timeline: Sequence[dict],
                             plan: Optional[dict] = None,
                             **kwargs) -> GraphicsLintReport:
    """Combined hard gate for gfx plate/share + SING reuse."""
    gfx = lint_timeline_graphics(timeline, **{
        k: kwargs[k] for k in ('max_black_s', 'max_share') if k in kwargs
    })
    sing = lint_sing_reuse(timeline, plan, max_uses=kwargs.get('max_uses'))
    issues = list(gfx.issues) + list(sing.issues)
    errors = [i for i in issues if i.get('severity') == 'error']
    ok = not errors
    summary = f"{gfx.summary}; {sing.summary}"
    rep = GraphicsLintReport(
        ok=ok, issues=issues, gfx_share=gfx.gfx_share, gfx_s=gfx.gfx_s,
        total_s=gfx.total_s, sing_uses=sing.sing_uses, summary=summary,
    )
    if not ok:
        codes = {e.get('code') for e in errors}
        if codes & {'sing_reuse'}:
            kind, stage = FailureKind.SING, 'sing_policy'
        else:
            kind, stage = FailureKind.GFX, 'gfx_lint'
        raise JobFailure(
            kind=kind,
            message=summary + ' | ' + '; '.join(e.get('detail', '') for e in errors[:3]),
            stage=stage,
            hint='Overlay gfx on live plates (≤1.5s black); keep gfx_share≤10%; SING max_uses=1.',
            details=rep.to_dict(),
        )
    return rep


def overlay_requires_plate(overlay: dict) -> bool:
    """True when an overlay is explicitly a long black-void story carrier (not edit-composite).

    Edit-composited HUD/terminal/kinetic overlays sit on live plates by pipeline design
    (``composite=True`` / ``term_composite``). Only flag overlays that declare a black
    void background and run longer than ``MAX_BLACK_GFX_S``.
    """
    if overlay.get('composite') is True or overlay.get('over_plate'):
        return False
    if overlay.get('src') or overlay.get('plate') or overlay.get('plate_src'):
        return False
    bg = str(overlay.get('bg') or overlay.get('background') or '').lower()
    on_black = bool(overlay.get('black_void') or overlay.get('on_black') or bg in {
        'black', 'void', 'none', '#000', '#000000',
    })
    if not on_black:
        return False
    kind = str(overlay.get('g') or overlay.get('kind') or '').lower()
    t0 = float(overlay.get('t0', 0.0))
    t1 = float(overlay.get('t1', t0))
    dur = max(0.0, t1 - t0)
    return kind in STORY_CARD_KINDS and dur > MAX_BLACK_GFX_S


def lint_overlays(overlays: Sequence[dict]) -> GraphicsLintReport:
    """Static overlay JSON check — long black-void story cards need a plate/src reference."""
    issues: List[dict] = []
    for i, ov in enumerate(overlays):
        if overlay_requires_plate(ov):
            issues.append({
                'severity': 'error', 'code': 'overlay_missing_plate',
                'detail': (
                    f"overlay[{i}] {ov.get('g')!r} duration "
                    f"{float(ov.get('t1', 0)) - float(ov.get('t0', 0)):.2f}s "
                    f"on black void needs plate/src (picture-first; no black-void story carrier)"
                ),
                'index': i,
            })
    ok = not issues
    return GraphicsLintReport(
        ok=ok, issues=issues,
        summary=f"overlay_lint: {'ok' if ok else 'FAIL'} errors={len(issues)}",
    )
