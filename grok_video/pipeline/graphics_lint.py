"""Picture-first graphics: overlays on live plates; short black-void caps; SING use ≤1.

Distinguish intentional code-built infrastructure (endcard, karaoke captions, short
kinetic slams, diegetic HUD/terminal composites) from banned black-void *narrative*
slides that carry the story (bignum / PowerPoint cards / long headline voids).

Validate narrative gfx in the plan before generation whenever possible; timeline lint
after edit still enforces the same rules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .failures import FailureKind, JobFailure
from .plan_fix import is_singing_shot

# Max continuous black-void *narrative* gfx (seconds)
MAX_BLACK_GFX_S = float(os.environ.get('GV_MAX_BLACK_GFX_S', '1.5'))
# Max *narrative* gfx share of runtime (endcard/captions excluded)
MAX_GFX_SHARE = float(os.environ.get('GV_MAX_GFX_SHARE', '0.10'))
SING_MAX_USES = int(os.environ.get('GV_SING_MAX_USES', '1'))

# Intentional edit infrastructure — never treated as black-void story carriers.
INFRA_GFX_KINDS = frozenset({
    'endcard', 'karaoke', 'lyrics', 'caption', 'ass', 'lower_third',
    'credit', 'credits', 'title_safe',
})

# Short punchlines allowed without a plate if ≤ MAX_BLACK_GFX_S (still picture-first preferred).
PUNCHLINE_GFX_KINDS = frozenset({
    'slam', 'kinetic', 'word_slam', 'hook_slam',
})

# Diegetic / UI composites — allowed when marked diegetic/composite/plate; else capped.
DIEGETIC_GFX_KINDS = frozenset({
    'hud', 'ui', 'terminal', 'code',
})

# Banned as primary story carriers on black voids (PTP regression: bignum / story cards).
NARRATIVE_SLIDE_KINDS = frozenset({
    'headline', 'bignum', 'bars', 'post', 'feed', 'quote', 'compare', 'stamp',
    'story', 'card', 'browser', 'rows', 'inbox', 'chat', 'gauge', 'countdown', 'screen',
})

STORY_CARD_KINDS = NARRATIVE_SLIDE_KINDS | DIEGETIC_GFX_KINDS


@dataclass
class GraphicsLintReport:
    ok: bool
    issues: List[dict] = field(default_factory=list)
    gfx_share: float = 0.0
    gfx_s: float = 0.0
    total_s: float = 0.0
    narrative_gfx_s: float = 0.0
    sing_uses: Dict[str, int] = field(default_factory=dict)
    summary: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'summary': self.summary, 'issues': self.issues,
            'gfx_share': self.gfx_share, 'gfx_s': self.gfx_s, 'total_s': self.total_s,
            'narrative_gfx_s': self.narrative_gfx_s, 'sing_uses': self.sing_uses,
            'errors': [i for i in self.issues if i.get('severity') == 'error'],
        }


def _shot_kind_src(shot: dict) -> Tuple[str, Any]:
    src = shot.get('src')
    if isinstance(src, (list, tuple)) and src:
        kind = str(src[0])
        ref = src[1] if len(src) > 1 else ''
        return kind, ref
    if shot.get('kind'):
        return str(shot['kind']), shot.get('src') or shot.get('scene_id') or shot.get('g') or ''
    if shot.get('gfx') or shot.get('is_gfx') or shot.get('g'):
        return 'gfx', shot.get('g') or shot.get('src') or ''
    # Karaoke timeline often stores v.kind == 'gfx' with nested g
    v = shot.get('v') or {}
    if isinstance(v, dict) and v.get('kind') == 'gfx':
        return 'gfx', v.get('g') or ''
    if shot.get('scene_id') or shot.get('src'):
        return 'clip', shot.get('scene_id') or shot.get('src')
    return 'unknown', ''


def _gfx_name(shot: dict, ref: Any = '') -> str:
    v = shot.get('v') if isinstance(shot.get('v'), dict) else {}
    return str(
        shot.get('g') or (v.get('g') if v else '') or ref or ''
    ).lower()


def _duration(shot: dict) -> float:
    if 'dur' in shot:
        return max(0.0, float(shot['dur']))
    t0 = float(shot.get('t0', 0.0))
    t1 = float(shot.get('t1', t0))
    return max(0.0, t1 - t0)


def _has_plate(shot: dict) -> bool:
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
    v = shot.get('v') if isinstance(shot.get('v'), dict) else {}
    p = v.get('p') if isinstance(v.get('p'), dict) else {}
    if p.get('plate') or p.get('plate_src') or shot.get('diegetic') or p.get('diegetic'):
        return True
    if shot.get('black_void') or shot.get('on_black'):
        return False
    bg = str(shot.get('bg') or meta.get('bg') or p.get('bg') or '').lower()
    if bg in ('black', 'void', 'none', '#000', '#000000'):
        return False
    return False


def classify_gfx(shot: dict, gname: str = '') -> str:
    """Classify a gfx shot: infra | punchline | diegetic | narrative_slide | other."""
    name = (gname or _gfx_name(shot)).lower()
    if shot.get('infra') or shot.get('karaoke_infra') or name in INFRA_GFX_KINDS:
        return 'infra'
    if name in PUNCHLINE_GFX_KINDS or shot.get('punchline'):
        return 'punchline'
    if (
        name in DIEGETIC_GFX_KINDS
        or shot.get('diegetic')
        or shot.get('in_world')
        or (isinstance(shot.get('v'), dict) and (shot['v'].get('p') or {}).get('diegetic'))
    ):
        return 'diegetic'
    if name in NARRATIVE_SLIDE_KINDS or shot.get('story_card') or shot.get('primary_story'):
        return 'narrative_slide'
    return 'other'


def is_narrative_carrier(shot: dict, gname: str = '') -> bool:
    """True when this gfx counts toward narrative black-void / share caps."""
    cls = classify_gfx(shot, gname)
    return cls in ('narrative_slide', 'other') or (
        cls == 'diegetic' and not _has_plate(shot) and not shot.get('diegetic')
        and not shot.get('composite')
    )


def lint_timeline_graphics(timeline: Sequence[dict],
                           *,
                           max_black_s: Optional[float] = None,
                           max_share: Optional[float] = None) -> GraphicsLintReport:
    """Fail banned black-void *narrative* slides; ignore endcard/karaoke infra for share.

    Intentional infrastructure (endcard, captions) may exceed 1.5s on a designed card.
    Narrative slides (bignum/story/headline voids) still hard-fail without a live plate
    when duration > max_black_s, and count toward gfx_share.
    """
    issues: List[dict] = []
    black_cap = MAX_BLACK_GFX_S if max_black_s is None else max_black_s
    share_cap = MAX_GFX_SHARE if max_share is None else max_share
    total = 0.0
    gfx_all = 0.0
    narrative_s = 0.0
    for i, sh in enumerate(timeline):
        dur = _duration(sh)
        total += dur
        kind, ref = _shot_kind_src(sh)
        if kind != 'gfx':
            continue
        gname = _gfx_name(sh, ref)
        cls = classify_gfx(sh, gname)
        gfx_all += dur
        plated = _has_plate(sh)

        if cls == 'infra':
            # endcard / karaoke captions — allowed; do not count toward narrative share
            continue

        if cls == 'punchline':
            if not plated and dur > black_cap:
                issues.append({
                    'severity': 'error', 'code': 'punchline_too_long',
                    'detail': (
                        f"shot[{i}] punchline gfx {gname!r} {dur:.2f}s > {black_cap}s "
                        f"without plate"
                    ),
                    'index': i, 'dur': dur, 'g': gname,
                })
            continue

        # Diegetic HUD/terminal: require plate or explicit diegetic/composite flag
        if cls == 'diegetic':
            if plated or sh.get('diegetic') or sh.get('composite'):
                continue
            if dur > black_cap:
                issues.append({
                    'severity': 'error', 'code': 'diegetic_gfx_on_black',
                    'detail': (
                        f"shot[{i}] diegetic gfx {gname!r} {dur:.2f}s on black void; "
                        f"composite onto a live plate"
                    ),
                    'index': i, 'dur': dur, 'g': gname,
                })
            narrative_s += dur
            continue

        # Narrative slides / other unknown gfx → picture-first hard rules
        narrative_s += dur
        if not plated and dur > black_cap:
            issues.append({
                'severity': 'error', 'code': 'black_void_narrative_slide',
                'detail': (
                    f"shot[{i}] narrative gfx {gname!r} duration {dur:.2f}s > {black_cap}s "
                    f"without live plate (black-void cards cannot carry the story)"
                ),
                'index': i, 'dur': dur, 'g': gname, 'class': cls,
            })
        if sh.get('primary_story') and not plated:
            issues.append({
                'severity': 'error', 'code': 'gfx_missing_plate',
                'detail': f"shot[{i}] primary story gfx requires plate: clip/still ref",
                'index': i,
            })

    share = (narrative_s / total) if total > 0 else 0.0
    if total > 0 and share > share_cap + 1e-9:
        issues.append({
            'severity': 'error', 'code': 'gfx_share_exceeded',
            'detail': (
                f'narrative gfx_share={share:.1%} of runtime exceeds cap {share_cap:.0%} '
                f'(endcard/karaoke captions excluded)'
            ),
            'gfx_s': round(narrative_s, 3), 'total_s': round(total, 3),
        })
    errors = [i for i in issues if i.get('severity') == 'error']
    ok = not errors
    summary = (
        f"gfx_lint: {'ok' if ok else 'FAIL'} narrative_share={share:.1%} "
        f"narrative_s={narrative_s:.1f}/{total:.1f} (all_gfx={gfx_all:.1f}) errors={len(errors)}"
    )
    return GraphicsLintReport(
        ok=ok, issues=issues, gfx_share=round(share, 4),
        gfx_s=round(gfx_all, 3), narrative_gfx_s=round(narrative_s, 3),
        total_s=round(total, 3), summary=summary,
    )


def lint_plan_graphics(plan: dict) -> GraphicsLintReport:
    """Pre-generation check: graphics_plan must not schedule black-void narrative carriers.

    Call before Grok spend. Empty graphics_plan lists are fine; story/bignum/headline
    items need diegetic/state_change/plate.
    """
    issues: List[dict] = []
    cc = plan.get('creative_contract') or plan.get('story_contract') or {}
    gp = cc.get('graphics_plan') or plan.get('graphics_plan')
    if gp is None:
        return GraphicsLintReport(ok=True, summary='gfx_plan_lint: ok (no graphics_plan)')
    for kind, items in (gp.items() if isinstance(gp, dict) else []):
        if kind in ('model_renders_text',):
            continue
        if not isinstance(items, list):
            continue
        k = str(kind).lower()
        if k in INFRA_GFX_KINDS or k in PUNCHLINE_GFX_KINDS:
            continue
        for i, item in enumerate(items):
            if isinstance(item, str):
                if k in NARRATIVE_SLIDE_KINDS:
                    issues.append({
                        'severity': 'error', 'code': 'plan_narrative_gfx_bare',
                        'detail': (
                            f'graphics_plan.{kind}[{i}] is a bare narrative slide string; '
                            f'require diegetic/state_change/plate in preproduction'
                        ),
                    })
                continue
            if not isinstance(item, dict):
                continue
            if k not in NARRATIVE_SLIDE_KINDS and k not in DIEGETIC_GFX_KINDS:
                continue
            ok_flags = bool(
                item.get('diegetic') or item.get('in_world') or item.get('state_change')
                or item.get('world_change') or item.get('plate') or item.get('plate_src')
                or item.get('src')
            )
            # Kinetic-like short items inside wrong bucket still need a flag if narrative
            if k in NARRATIVE_SLIDE_KINDS and not ok_flags:
                issues.append({
                    'severity': 'error', 'code': 'plan_narrative_gfx_not_picture_first',
                    'detail': (
                        f'graphics_plan.{kind}[{i}] narrative carrier '
                        f'{str(item.get("text") or "")[:40]!r} must be diegetic/'
                        f'state_change/plate before generation'
                    ),
                })
            if k in DIEGETIC_GFX_KINDS and item.get('composite') is False:
                issues.append({
                    'severity': 'error', 'code': 'plan_gfx_not_composite',
                    'detail': f'graphics_plan.{kind}[{i}] must be edit-composited.',
                })
    errors = [i for i in issues if i.get('severity') == 'error']
    ok = not errors
    return GraphicsLintReport(
        ok=ok, issues=issues,
        summary=f"gfx_plan_lint: {'ok' if ok else 'FAIL'} errors={len(errors)}",
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
    return GraphicsLintReport(ok=ok, issues=issues, sing_uses=uses, summary=summary)


def os_path_stem(path: str) -> str:
    base = path.replace('\\', '/').split('/')[-1]
    if base.endswith('.mp4') or base.endswith('.png'):
        return base.rsplit('.', 1)[0]
    return base


def assert_graphics_and_sing(timeline: Sequence[dict],
                             plan: Optional[dict] = None,
                             **kwargs) -> GraphicsLintReport:
    """Combined hard gate for narrative gfx plate/share + SING reuse."""
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
        narrative_gfx_s=gfx.narrative_gfx_s, total_s=gfx.total_s,
        sing_uses=sing.sing_uses, summary=summary,
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
            hint=(
                'Ban black-void narrative slides; keep endcard/karaoke captions as infra; '
                'plate diegetic HUD/terminal; SING max_uses=1.'
            ),
            details=rep.to_dict(),
        )
    return rep


def assert_plan_graphics(plan: dict) -> GraphicsLintReport:
    """Hard-abort wrapper for pre-generation graphics_plan lint."""
    rep = lint_plan_graphics(plan)
    if not rep.ok:
        raise JobFailure(
            kind=FailureKind.GFX,
            message=rep.summary + ' | ' + '; '.join(
                e.get('detail', '') for e in rep.issues if e.get('severity') == 'error'
            )[:400],
            stage='gfx_lint',
            hint='Plan diegetic/state-changing graphics on plates before generation.',
            details=rep.to_dict(),
        )
    return rep


def overlay_requires_plate(overlay: dict) -> bool:
    """Long black-void *narrative* overlays need a plate; infra/captions do not."""
    kind = str(overlay.get('g') or overlay.get('kind') or '').lower()
    if kind in INFRA_GFX_KINDS or kind in PUNCHLINE_GFX_KINDS:
        return False
    if overlay.get('composite') is True or overlay.get('over_plate') or overlay.get('diegetic'):
        return False
    if overlay.get('src') or overlay.get('plate') or overlay.get('plate_src'):
        return False
    bg = str(overlay.get('bg') or overlay.get('background') or '').lower()
    on_black = bool(overlay.get('black_void') or overlay.get('on_black') or bg in {
        'black', 'void', 'none', '#000', '#000000',
    })
    if not on_black:
        return False
    t0 = float(overlay.get('t0', 0.0))
    t1 = float(overlay.get('t1', t0))
    dur = max(0.0, t1 - t0)
    return kind in NARRATIVE_SLIDE_KINDS and dur > MAX_BLACK_GFX_S


def lint_overlays(overlays: Sequence[dict]) -> GraphicsLintReport:
    issues: List[dict] = []
    for i, ov in enumerate(overlays):
        if overlay_requires_plate(ov):
            issues.append({
                'severity': 'error', 'code': 'overlay_missing_plate',
                'detail': (
                    f"overlay[{i}] {ov.get('g')!r} duration "
                    f"{float(ov.get('t1', 0)) - float(ov.get('t0', 0)):.2f}s "
                    f"on black void needs plate/src (picture-first narrative slide)"
                ),
                'index': i,
            })
    ok = not issues
    return GraphicsLintReport(
        ok=ok, issues=issues,
        summary=f"overlay_lint: {'ok' if ok else 'FAIL'} errors={len(issues)}",
    )
