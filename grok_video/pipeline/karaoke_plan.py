"""Karaoke plan schema helpers: normalize Opus output so new plans can pass coherence gates.

Never invents ``requires_next`` or independent viewer-retell. Caption infra exemption is
provenance-only (code-built line_card / title fallback / match redraw / endcard) — never
by template name or planner-controlled tags.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Provenance values set ONLY by karaoke code paths (never trust planner tags).
CAPTION_PROVENANCE = frozenset({
    'line_card',
    'title_fallback',
    'match_redraw',
    'template_cap_redraw',
    'stamp_cap_redraw',
    'fact_lint_replace',
    'endcard',
})

# Still banned as unplated primary story carriers unless diegetic/state_change/plate.
NARRATIVE_POOL_GFX = frozenset({
    'bignum', 'bars', 'post', 'feed', 'compare', 'story', 'card', 'rows', 'inbox', 'chat',
    'gauge', 'countdown', 'screen', 'headline', 'quote', 'stamp', 'browser',
})

SCENE_STATE_KEYS = ('world_before', 'action', 'world_after')


def mark_code_caption(visual: dict, provenance: str) -> dict:
    """Stamp a visual as a code-built karaoke caption. ``provenance`` must be in CAPTION_PROVENANCE."""
    if provenance not in CAPTION_PROVENANCE:
        raise ValueError(f'invalid caption provenance {provenance!r}')
    out = dict(visual or {})
    out['gfx_provenance'] = provenance
    # Convenience mirrors for older call sites; lint trusts provenance only.
    out['line_card'] = provenance == 'line_card' or out.get('line_card')
    return out


def tag_caption_gfx(visual: dict) -> dict:
    """Preserve code-built caption provenance. Does NOT promote planner headline/quote by name.

    Planner-authored ``infra`` / ``karaoke_caption`` flags are stripped so they cannot
    bypass picture-first duration/share caps.
    """
    if not isinstance(visual, dict):
        return visual
    out = dict(visual)
    if out.get('kind') != 'gfx' and out.get('g') != 'endcard':
        # endcard may omit kind
        if str(out.get('g') or '').lower() != 'endcard':
            # Strip planner-controlled bypass tags
            out.pop('infra', None)
            out.pop('karaoke_caption', None)
            return out
    g = str(out.get('g') or '').lower()
    prov = str(out.get('gfx_provenance') or '').lower()
    # Strip planner-controlled tags always; re-apply only when provenance is code-built
    out.pop('infra', None)
    out.pop('karaoke_caption', None)
    if g == 'endcard' and not prov:
        out['gfx_provenance'] = 'endcard'
        prov = 'endcard'
    if prov in CAPTION_PROVENANCE:
        out['gfx_provenance'] = prov
        return out
    # Unknown / planner graphic — leave untagged (subject to narrative gfx rules)
    out.pop('gfx_provenance', None)
    out.pop('line_card', None)
    return out


def extract_required_accents(plan: dict) -> List[str]:
    """Musical accents the plan declares must be covered by performance peaks."""
    raw = (
        plan.get('required_accents')
        or (plan.get('creative_contract') or {}).get('required_accents')
        or plan.get('musical_accents')
        or []
    )
    out: List[str] = []
    for a in raw:
        if isinstance(a, dict):
            name = str(a.get('accent') or a.get('name') or '').lower().strip()
        else:
            name = str(a).lower().strip()
        if name and name not in out:
            out.append(name)
    return out


def normalize_karaoke_plan(plan: dict, *, invent_edges: bool = False) -> dict:
    """Normalize Opus/template karaoke JSON into gate-ready shape.

    Raises ValueError with actionable text when required coherence fields are absent.
    Never silently invents causal ``requires_next``. Does not mark planner gfx as caption infra.
    """
    if invent_edges:
        raise ValueError('normalize_karaoke_plan refuses invent_edges=True on acceptance paths')
    P = dict(plan)
    missing: List[str] = []

    arc = (
        (P.get('arc') or '').strip()
        or (P.get('visual_premise') or '').strip()
        or ((P.get('design') or {}).get('why') or '').strip()
    )
    if not arc:
        missing.append('arc / visual_premise (one-sentence story)')
    else:
        P['arc'] = arc

    retell = (P.get('viewer_retell') or '').strip()
    if not retell:
        missing.append('viewer_retell (planner-intended sound-off retell; not labeled independent)')
    else:
        low = retell.lower()
        if low.startswith('an independent viewer'):
            missing.append(
                'viewer_retell must not claim independence; independent retell comes from '
                'storyboard_review.viewer_retell / independent_retell'
            )
        P['viewer_retell'] = retell

    payoff = P.get('payoff_design') or (P.get('creative_contract') or {}).get('payoff_design')
    if not payoff:
        missing.append('payoff_design {scene_id, summary, world_after}')
    else:
        P['payoff_design'] = payoff

    scenes = [dict(s) for s in (P.get('scenes') or [])]
    if not scenes:
        P['scenes'] = []
    else:
        for sc in scenes:
            sid = sc.get('id')
            for k in SCENE_STATE_KEYS:
                if k not in sc or sc.get(k) in (None, '', {}):
                    missing.append(f'scene {sid} missing {k}')
            role = str(sc.get('role') or sc.get('structural_role') or '').lower()
            prompt = str(sc.get('prompt') or '')
            needs_edge = (
                role in ('action', 'twist', 'turn')
                or any(w in prompt.lower() for w in ('yank', 'pull the plug', 'kill switch', 'unplug'))
            )
            if needs_edge and 'requires_next' not in sc:
                missing.append(
                    f'scene {sid} needs authored requires_next (do not auto-fake causal edges)'
                )
        P['scenes'] = scenes

    if P.get('required_shots') is None and scenes:
        req = [
            str(s['id']) for s in scenes
            if str(s.get('structural_role') or '').lower() in {
                'twist', 'payoff', 'climax', 'reveal', 'final_payoff', 'bookend',
            } and s.get('id')
        ]
        if req:
            P['required_shots'] = req
        elif not P.get('required_shots'):
            missing.append('required_shots (structural climax/payoff ids)')

    accents = extract_required_accents(P)
    if scenes and not accents:
        missing.append(
            'required_accents (musical accents the plan must cover, e.g. hook/drop/chorus)'
        )
    else:
        P['required_accents'] = accents

    if missing:
        raise ValueError(
            'karaoke plan incomplete for coherence gates: ' + '; '.join(missing[:12])
        )

    # Strip planner bypass tags from pools; do NOT promote headline/quote by name.
    def _scrub_pool(items: Sequence[dict]) -> List[dict]:
        return [tag_caption_gfx(dict(v)) if isinstance(v, dict) else v for v in (items or [])]

    P['intro'] = _scrub_pool(P.get('intro') or [])
    P['breaks'] = _scrub_pool(P.get('breaks') or [])
    P['outro'] = _scrub_pool(P.get('outro') or [])
    lines = []
    for ln in P.get('lines') or []:
        L = dict(ln)
        L['v'] = _scrub_pool(L.get('v') or [])
        lines.append(L)
    P['lines'] = lines

    cc = dict(P.get('creative_contract') or {})
    cc.setdefault('visual_premise', arc)
    cc['planner_retell'] = retell
    if 'viewer_retell' in cc and str(cc.get('viewer_retell') or '').lower().startswith(
        'an independent viewer'
    ):
        cc.pop('viewer_retell', None)
    cc['payoff_design'] = payoff
    cc['required_accents'] = accents
    if 'graphics_plan' not in cc:
        cc['graphics_plan'] = {
            'kinetic': [], 'slam': [], 'hud': [], 'terminal': [],
            'caption': [], 'story': [], 'model_renders_text': False,
        }
    P['creative_contract'] = cc

    bible = dict(P.get('art_bible') or {})
    bible.setdefault('photoreal', True)
    bible.setdefault('banned_styles', ['clay', 'cartoon', 'toy', 'mannequin'])
    bible.setdefault('mouths_closed_default', True)
    P['art_bible'] = bible
    return P


def representative_opus_plan() -> dict:
    """Fixture shaped like a valid new karaoke Opus plan for planner→dry-run tests."""
    return {
        'planner': 'opus',
        'arc': 'Lead dumps the feed, yanks the plug, then learns who still holds power.',
        'viewer_retell': (
            'She rejects the feed, yanks the wall plug, and the overseer still controls the lights.'
        ),
        'payoff_design': {
            'scene_id': 's05_payoff',
            'summary': 'Overseer reveal with blank gadget; who controlled the plug',
            'world_after': {'who_controls': 'overseer', 'reveal': True},
        },
        'required_shots': ['s04_twist', 's05_payoff'],
        'required_accents': ['hook', 'drop'],
        'scenes': [
            {
                'id': 's01_setup',
                'prompt': '[LEAD] WIDE on couch staring at the feed, mouth closed, no jewellery',
                'motion': '0-2s: sit; 2-4s: slow push; 4-6s: remote rises',
                'role': 'setup', 'tags': 'SETUP',
                'world_before': {'place': 'home', 'watching': 'feed'},
                'action': 'establish the trap of the feed',
                'world_after': {'place': 'home', 'watching': 'feed'},
                'prop_state': {'remote': 'in_hand'},
                'requires_next': ['s02_perf'],
            },
            {
                'id': 's02_perf',
                'prompt': '[LEAD][HERO] MCU defiant glare on the hook, mouth closed',
                'motion': '0-6s: head sway on the beat',
                'role': 'performance_closed', 'tags': 'HOOK',
                'emotion': 'defiant', 'accent': 'hook', 'musical_cue': 'chorus',
                'world_before': {'place': 'home', 'watching': 'feed'},
                'action': 'decide to dump the feed',
                'world_after': {'place': 'home', 'watching': 'rejected'},
                'prop_state': {'remote': 'raised'},
                'requires_next': ['s03_action'],
            },
            {
                'id': 's03_action',
                'prompt': '[LEAD] CU yanks the wall plug, cable sparks, mouth closed',
                'motion': '0-3s: reach; 3-6s: yank',
                'role': 'action', 'tags': 'ACTION',
                'world_before': {'prop:plug': 'wall', 'lights': 'on'},
                'action': 'yank the wall plug',
                'world_after': {'prop:plug': 'yanked', 'lights': 'on'},
                'prop_state': {'plug': 'yanked', 'scale': 'wall_plug'},
                'requires_next': ['s04_twist'],
            },
            {
                'id': 's04_twist',
                'prompt': '[GROK] MS robot still holds the cable',
                'motion': '0-6s: twist reveal',
                'role': 'robot', 'tags': 'TWIST', 'structural_role': 'twist',
                'world_before': {'prop:plug': 'yanked', 'who_controls': 'unknown'},
                'action': 'reveal the robot still holds power',
                'world_after': {'prop:plug': 'yanked', 'who_controls': 'robot'},
                'prop_state': {'plug': 'yanked', 'scale': 'wall_plug'},
                'requires_next': ['s05_payoff'],
            },
            {
                'id': 's05_payoff',
                'prompt': '[OVERSEER] MCU blank dark gadget, mouth closed',
                'motion': '0-6s: payoff hold',
                'role': 'payoff', 'tags': 'PAYOFF', 'structural_role': 'payoff',
                'accent': 'drop', 'musical_cue': 'final chorus',
                'world_before': {'who_controls': 'robot', 'reveal': False},
                'action': 'overseer reveal',
                'world_after': {'who_controls': 'overseer', 'reveal': True},
                'prop_state': {'gadget': 'blank_dark'},
                'requires_next': [],
            },
        ],
        'lines': [
            {'i': 0, 'shows': 'setup on couch', 'fact': 'feed trap',
             'v': [{'kind': 'scene', 'id': 's01_setup'}]},
            {'i': 1, 'shows': 'defiant MCU', 'fact': '',
             'v': [{'kind': 'scene', 'id': 's02_perf'}]},
            {'i': 2, 'shows': 'yank plug', 'fact': 'wall plug',
             'v': [{'kind': 'scene', 'id': 's03_action'}]},
            {'i': 3, 'shows': 'robot twist', 'fact': '',
             'v': [{'kind': 'scene', 'id': 's04_twist'}]},
            {'i': 4, 'shows': 'overseer gadget', 'fact': '',
             'v': [{'kind': 'scene', 'id': 's05_payoff'}]},
            # Planner narrative headline (NOT code-built) — must remain subject to gfx caps
            {'i': 5, 'shows': 'lyric card', 'fact': 'dump the feed',
             'v': [{'kind': 'gfx', 'g': 'headline',
                    'p': {'kicker': 'DUMP', 'text': 'Dump the feed', 'sub': 'watch this'}}]},
        ],
        'intro': [{'kind': 'gfx', 'g': 'headline',
                   'p': {'kicker': 'TODAY', 'text': 'Dump the feed'}}],
        'breaks': [],
        'outro': [{'kind': 'gfx', 'g': 'headline',
                   'p': {'kicker': 'END', 'text': 'Who held the plug?'}}],
        'story_text': [
            {'from_line': 0, 'to_line': 4, 'kicker': 'MAIN STORY', 'text': 'Dump the feed, yank the plug'},
        ],
        'credit': 'Dump the feed — who held the plug',
        'design': {
            'palette': 'acid-deadpan', 'type': 'grotesque', 'lyric_style': 'block',
            'lyric_pos': 'lower', 'transition': 'cut', 'grade': 'flat saturated',
            'texture': '35mm grain',
            'why': 'Arc: dump the feed then learn who still holds power.',
        },
        'performance_beats': [
            {'scene_id': 's02_perf', 'accent': 'hook', 'emotion': 'defiant',
             'musical_cue': 'chorus', 'mouths_closed': True},
            {'scene_id': 's05_payoff', 'accent': 'drop', 'emotion': 'reveal',
             'musical_cue': 'final chorus', 'mouths_closed': True},
        ],
        'art_bible': {
            'photoreal': True,
            'banned_styles': ['clay', 'cartoon', 'toy', 'mannequin'],
            'prop_locks': {'plug': {'scale': 'wall_plug'}},
            'mouths_closed_default': True,
        },
    }
