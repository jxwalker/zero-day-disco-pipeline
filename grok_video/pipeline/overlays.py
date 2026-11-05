"""Post-production story / UI / terminal overlays are first-class.

The rule "the model never renders text" means: ban readable gen-text in prompts,
then composite crisp editable overlays in the edit (story cards, slams, terminal
drawtext). Production wrongly set GV_NEWS_TEXT=0 / GV_NO_GFX=1 and emptied overlays.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .constants import NEWS_TEXT_DEFAULT, NO_GFX_DEFAULT, TERM_COMPOSITE_DEFAULT

# Appended to model prompts: no readable text in the generated frame.
NO_TEXT_NEG = (
    "Absolutely no readable text, letters, numbers, captions, logos, watermarks, "
    "UI labels or signage in the frame. Terminals, monitors and phone screens must be "
    "BLANK or DARK (no code, logs or prompts visible). Text is added later in the edit."
)

TERM_KIND = 'terminal'
STORY_KIND = 'story'
SLAM_KIND = 'slam'
UI_KIND = 'ui'
HUD_KIND = 'hud'
KINETIC_KIND = 'kinetic'
CAPTION_KIND = 'caption'


@dataclass
class OverlaySpec:
    kind: str                  # story | slam | terminal | ui
    text: str
    t0: float
    t1: float
    kicker: str = ''
    src: str = ''              # optional per-shot source id for terminal rect tracking
    rect: Optional[List[float]] = None  # normalized [x,y,w,h] for terminal composite
    style: str = 'default'
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            'g': self.kind, 'text': self.text, 't0': round(self.t0, 3), 't1': round(self.t1, 3),
            'kicker': self.kicker, 'style': self.style,
        }
        if self.src:
            d['src'] = self.src
        if self.rect:
            d['rect'] = self.rect
        if self.meta:
            d.update(self.meta)
        return d


def model_text_forbidden(prompt: str) -> str:
    """Ensure the no-gen-text negation is present in a model prompt."""
    p = (prompt or '').rstrip()
    if 'no readable text' in p.lower() or 'absolutely no text' in p.lower():
        return p
    return (p + ' ' + NO_TEXT_NEG).strip()


def terminal_must_be_blank(prompt: str) -> str:
    """Steer terminals/monitors/phones to blank/dark so term_composite can draw content."""
    p = prompt or ''
    if not re.search(r'\b(terminal|monitor|screen|laptop|phone|hud|display)\b', p, re.I):
        return p
    if re.search(r'\b(blank|dark|unlit)\b', p, re.I):
        return p
    return (p.rstrip('.') + '. Any terminal, monitor or phone screen is blank and dark.').strip()


def overlays_enabled() -> bool:
    return NEWS_TEXT_DEFAULT and not NO_GFX_DEFAULT


def build_overlay_texts(plan: dict,
                        line_timings: Sequence[dict],
                        *,
                        enabled: Optional[bool] = None,
                        term_composite: Optional[bool] = None) -> List[OverlaySpec]:
    """Build editable overlay specs from plan story_text + terminal cues.

    ``line_timings`` items need ``start``/``end`` (and optional ``i`` / ``text``).
    Numbers/dates stripped from prompts by sanitizers are re-added HERE as overlays.
    """
    if not (overlays_enabled() if enabled is None else enabled):
        return []
    do_term = TERM_COMPOSITE_DEFAULT if term_composite is None else term_composite
    by_i = {}
    for ln in line_timings:
        if 'i' in ln:
            by_i[ln['i']] = ln
        elif 'start' in ln:
            by_i[len(by_i)] = ln

    out: List[OverlaySpec] = []
    for card in plan.get('story_text') or []:
        a = by_i.get(card.get('from_line'))
        b = by_i.get(card.get('to_line'), a)
        if not a:
            continue
        t0 = float(a.get('start', 0.0))
        t1 = float((b or a).get('end', t0 + 2.0))
        out.append(OverlaySpec(
            kind=STORY_KIND,
            text=str(card.get('text') or ''),
            kicker=str(card.get('kicker') or 'STORY'),
            t0=t0, t1=t1, style='story_chip',
        ))

    for slam in plan.get('slams') or plan.get('word_slams') or []:
        ln = by_i.get(slam.get('line'))
        if not ln:
            continue
        out.append(OverlaySpec(
            kind=SLAM_KIND,
            text=str(slam.get('text') or slam.get('word') or '').upper(),
            t0=float(ln.get('start', 0.0)),
            t1=float(ln.get('end', ln.get('start', 0.0) + 0.8)),
            style='slam',
        ))

    if do_term:
        for sc in plan.get('scenes') or []:
            prompt = sc.get('prompt') or ''
            term_text = sc.get('terminal_text') or sc.get('screen_text') or ''
            if not term_text and re.search(r'\[TERM\]|terminal_text:', prompt, re.I):
                m = re.search(r'terminal_text:\s*[\'"]?(.+?)[\'"]?\s*(?:\[|$)', prompt, re.I | re.S)
                term_text = (m.group(1).strip() if m else '')
            if not term_text:
                continue
            # Approximate timing: use first line that references this scene id
            t0, t1 = 0.0, 2.0
            sid = sc.get('id')
            for ln in plan.get('lines') or []:
                for v in ln.get('v') or []:
                    if v.get('kind') == 'scene' and v.get('id') == sid:
                        tl = by_i.get(ln.get('i'))
                        if tl:
                            t0 = float(tl.get('start', 0.0))
                            t1 = float(tl.get('end', t0 + 2.0))
                        break
            out.append(OverlaySpec(
                kind=TERM_KIND,
                text=term_text,
                t0=t0, t1=t1,
                src=str(sid or ''),
                rect=sc.get('term_rect') or [0.55, 0.20, 0.40, 0.45],
                style='terminal',
            ))

    # Code-built HUD / kinetic / caption seeds from creative_contract.graphics_plan
    cc = plan.get('creative_contract') or plan.get('story_contract') or {}
    gp = cc.get('graphics_plan') or plan.get('graphics_plan') or {}
    for kind, default_style, default_rect in (
        (HUD_KIND, 'hud', [0.04, 0.04, 0.42, 0.22]),
        (KINETIC_KIND, 'kinetic', None),
        (CAPTION_KIND, 'caption', None),
        (TERM_KIND, 'terminal', [0.55, 0.20, 0.40, 0.45]),
    ):
        for item in gp.get(kind) or []:
            if isinstance(item, str):
                text, meta = item, {}
            else:
                text, meta = (item.get('text') or ''), item
            if not text:
                continue
            t0 = meta.get('t0')
            t1 = meta.get('t1')
            if t0 is None and meta.get('line') is not None:
                tl = by_i.get(meta['line'])
                if tl:
                    t0 = float(tl.get('start', 0.0))
                    t1 = float(tl.get('end', t0 + 0.8))
            if t0 is None:
                t0, t1 = 0.0, 2.0
            if t1 is None:
                t1 = float(t0) + (0.8 if kind == KINETIC_KIND else 2.0)
            # Avoid duplicating terminal text already added from scene.terminal_text
            if kind == TERM_KIND and any(o.kind == TERM_KIND and o.text == text for o in out):
                continue
            out.append(OverlaySpec(
                kind=kind,
                text=str(text),
                t0=float(t0), t1=float(t1),
                kicker=str(meta.get('kicker') or kind.upper()),
                src=str(meta.get('scene_id') or meta.get('src') or ''),
                rect=meta.get('rect') or default_rect,
                style=str(meta.get('style') or default_style),
                meta={'composite': True, 'source': 'graphics_plan'},
            ))
    return out


def overlays_to_json(overlays: Sequence[OverlaySpec]) -> List[dict]:
    return [o.to_dict() for o in overlays]


# --- Beat-driven edit helpers (Sam DRAM scam benchmark inspiration) ---------------

def beat_cut_points(beats: Sequence[float],
                    energy: str = 'mid',
                    *,
                    t0: float = 0.0,
                    t1: float = 0.0) -> List[float]:
    """Pick cut times on musical beats; denser on hooks ('fast'), holds on punchlines ('calm')."""
    beats_per = {'fast': 2, 'mid': 3, 'calm': 4}.get(energy, 3)
    cuts = [t0]
    k = 0
    for b in beats:
        if b <= t0 + 0.3 or b >= t1 - 0.3:
            continue
        k += 1
        if k >= beats_per and b - cuts[-1] >= 0.4:
            cuts.append(float(b)); k = 0
    if t1 - cuts[-1] < 0.35 and len(cuts) > 1:
        cuts.pop()
    cuts.append(t1)
    return cuts


def physical_payoff_required(plan: dict) -> List[str]:
    """Return scene ids that must show a physical visual story action / payoff (not talking heads)."""
    need = []
    for sc in plan.get('scenes') or []:
        blob = ' '.join(str(sc.get(k, '')) for k in ('id', 'prompt', 'tags', 'role', 'beat')).upper()
        if any(t in blob for t in ('PAYOFF', 'TWIST', 'TURN', 'ACTION')):
            need.append(str(sc.get('id')))
    return need
