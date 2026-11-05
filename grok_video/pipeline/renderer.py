"""Grok-primary renderer plan: cache reuse, local fallback, budget guard, no needless still regen."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


@dataclass
class RenderBudget:
    gen: int = 20
    edit: int = 20
    i2v: int = 14
    spent: Dict[str, int] = field(default_factory=lambda: {'gen': 0, 'edit': 0, 'i2v': 0})

    def can(self, kind: str, n: int = 1) -> bool:
        return self.spent.get(kind, 0) + n <= getattr(self, kind, 0)

    def spend(self, kind: str, n: int = 1) -> None:
        if not self.can(kind, n):
            raise RuntimeError(f'render budget exhausted for {kind}: {self.spent} / {self.as_caps()}')
        self.spent[kind] = self.spent.get(kind, 0) + n

    def as_caps(self) -> dict:
        return {'gen': self.gen, 'edit': self.edit, 'i2v': self.i2v}


@dataclass
class RenderItem:
    id: str
    kind: str          # gen | edit | i2v
    out: str
    prompt: str
    action: str        # reuse_cache | grok | local_fallback | skip
    reason: str = ''
    image: str = ''
    refs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'id': self.id, 'kind': self.kind, 'out': self.out, 'prompt': self.prompt[:200],
            'action': self.action, 'reason': self.reason, 'image': self.image, 'refs': self.refs,
        }


@dataclass
class RenderPlan:
    items: List[RenderItem]
    budget: RenderBudget
    reused: int = 0
    to_grok: int = 0
    to_local: int = 0
    skipped: int = 0

    def to_dict(self) -> dict:
        return {
            'items': [i.to_dict() for i in self.items],
            'budget': self.budget.as_caps(),
            'spent': dict(self.budget.spent),
            'reused': self.reused, 'to_grok': self.to_grok,
            'to_local': self.to_local, 'skipped': self.skipped,
        }


def _usable(path: str, min_bytes: int = 1000) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > min_bytes


def plan_renders(jobs: Sequence[dict],
                 budget: Optional[RenderBudget] = None,
                 *,
                 prefer_local_for: Optional[Sequence[str]] = None,
                 force: bool = False) -> RenderPlan:
    """Decide cache reuse vs Grok vs local fallback without regenerating good stills.

    Each job: ``{id, kind, out, prompt, image?, refs?, tier?}``.
    """
    bud = budget or RenderBudget()
    local_tiers = set(prefer_local_for or ('broll',))
    items: List[RenderItem] = []
    reused = to_grok = to_local = skipped = 0

    for j in jobs:
        out = j['out']
        kind = j.get('kind') or 'gen'
        if not force and _usable(out):
            reused += 1
            items.append(RenderItem(
                id=j['id'], kind=kind, out=out, prompt=j.get('prompt') or '',
                action='reuse_cache', reason='existing artefact reused',
                image=j.get('image') or '', refs=list(j.get('refs') or []),
            ))
            continue
        tier = (j.get('tier') or '').lower()
        if tier in local_tiers and kind == 'i2v':
            if bud.can('i2v'):
                # Local path does not spend Grok i2v budget up-front; on local failure
                # the caller re-plans with force and grok.
                to_local += 1
                items.append(RenderItem(
                    id=j['id'], kind=kind, out=out, prompt=j.get('prompt') or '',
                    action='local_fallback', reason=f'tier={tier} prefers local',
                    image=j.get('image') or '', refs=list(j.get('refs') or []),
                ))
            else:
                skipped += 1
                items.append(RenderItem(
                    id=j['id'], kind=kind, out=out, prompt=j.get('prompt') or '',
                    action='skip', reason='i2v budget exhausted',
                ))
            continue
        if not bud.can(kind):
            skipped += 1
            items.append(RenderItem(
                id=j['id'], kind=kind, out=out, prompt=j.get('prompt') or '',
                action='skip', reason=f'{kind} budget exhausted',
            ))
            continue
        bud.spend(kind)
        to_grok += 1
        items.append(RenderItem(
            id=j['id'], kind=kind, out=out, prompt=j.get('prompt') or '',
            action='grok', reason='grok-primary',
            image=j.get('image') or '', refs=list(j.get('refs') or []),
        ))

    return RenderPlan(items=items, budget=bud, reused=reused, to_grok=to_grok,
                      to_local=to_local, skipped=skipped)


def parse_farm_res(res: Optional[str] = None) -> tuple[int, int]:
    raw = res or os.environ.get('GV_FARM_RES', '1280x720')
    w, h = raw.lower().split('x')
    return int(w), int(h)


def stretch_banned(src_w: int, src_h: int, dst_w: int = 1920, dst_h: int = 1080) -> bool:
    """True when mastering would stretch a low-res farm render up to HD (forbidden)."""
    return src_w * src_h < 1280 * 720 and (dst_w >= 1920 or dst_h >= 1080)
