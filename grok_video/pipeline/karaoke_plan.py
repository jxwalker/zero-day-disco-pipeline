"""Karaoke plan schema helpers: normalize Opus output so new plans can pass coherence gates.

Never invents ``requires_next`` or independent viewer-retell. Tags intentional karaoke
caption/title/endcard gfx so graphics lint does not treat them as black-void narrative slides.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set

# Caption/title templates used as line-locked karaoke fallbacks (not narrative story carriers).
CAPTION_GFX = frozenset({
    'headline', 'quote', 'stamp', 'browser',  # short lyric/title cards when infra-tagged
})
# Still banned as unplated primary story carriers unless diegetic/state_change/plate.
NARRATIVE_POOL_GFX = frozenset({
    'bignum', 'bars', 'post', 'feed', 'compare', 'story', 'card', 'rows', 'inbox', 'chat',
    'gauge', 'countdown', 'screen',
})


SCENE_STATE_KEYS = ('world_before', 'action', 'world_after')


def tag_caption_gfx(visual: dict) -> dict:
    """Mark intentional karaoke caption/title cards so gfx lint treats them as infra."""
    if not isinstance(visual, dict):
        return visual
    out = dict(visual)
    if out.get('kind') != 'gfx':
        return out
    g = str(out.get('g') or '').lower()
    if g in ('endcard', 'karaoke', 'lyrics', 'caption', 'credit', 'credits'):
        out['infra'] = True
        out['karaoke_caption'] = True
        return out
    if g in CAPTION_GFX or out.get('redrawn') or out.get('line_card'):
        out['karaoke_caption'] = True
        out['infra'] = True
    return out


def _tag_pool(items: Sequence[dict]) -> List[dict]:
    return [tag_caption_gfx(dict(v)) if isinstance(v, dict) else v for v in (items or [])]


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
    Never silently invents causal ``requires_next`` (``invent_edges`` stays False on
    acceptance paths).
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
        # Strip fake "independent" labels from planner text — independence comes from review stage
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
        # Template plans with zero scenes are gfx-only; coherence gates for scene-state N/A
        P['scenes'] = []
    else:
        for sc in scenes:
            sid = sc.get('id')
            for k in SCENE_STATE_KEYS:
                if k not in sc or sc.get(k) in (None, '', {}):
                    missing.append(f'scene {sid} missing {k}')
            # Action / consequence scenes need authored requires_next (may be empty list only for terminal payoff)
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
        # Derive only from explicit structural_role — not keyword lore
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

    # Tag caption gfx in all pools (intentional karaoke cards ≠ narrative black-void slides)
    P['intro'] = _tag_pool(P.get('intro') or [])
    P['breaks'] = _tag_pool(P.get('breaks') or [])
    P['outro'] = _tag_pool(P.get('outro') or [])
    lines = []
    for ln in P.get('lines') or []:
        L = dict(ln)
        L['v'] = _tag_pool(L.get('v') or [])
        lines.append(L)
    P['lines'] = lines

    cc = dict(P.get('creative_contract') or {})
    cc.setdefault('visual_premise', arc)
    # Planner retell is NOT the independent review retell
    cc['planner_retell'] = retell
    if 'viewer_retell' in cc and str(cc.get('viewer_retell') or '').lower().startswith(
        'an independent viewer'
    ):
        cc.pop('viewer_retell', None)
    cc['payoff_design'] = payoff
    cc['required_accents'] = accents
    if 'graphics_plan' not in cc:
        # Empty preplanned lists are fine; unplanned edit cards are not
        cc['graphics_plan'] = {
            'kinetic': [], 'slam': [], 'hud': [], 'terminal': [],
            'caption': [], 'story': [], 'model_renders_text': False,
        }
    # Collect caption gfx into graphics_plan.caption as infra
    caps = list(cc['graphics_plan'].get('caption') or [])
    for pool in (P.get('intro'), P.get('breaks'), P.get('outro')):
        for v in pool or []:
            if isinstance(v, dict) and v.get('karaoke_caption'):
                caps.append({
                    'g': v.get('g'), 'diegetic': False, 'infra': True,
                    'text': str((v.get('p') or {}).get('text') or '')[:70],
                })
    cc['graphics_plan']['caption'] = caps[:24]
    P['creative_contract'] = cc

    bible = dict(P.get('art_bible') or {})
    bible.setdefault('photoreal', True)
    bible.setdefault('banned_styles', ['clay', 'cartoon', 'toy', 'mannequin'])
    bible.setdefault('mouths_closed_default', True)
    P['art_bible'] = bible
    return P


def representative_opus_plan() -> dict:
    """Fixture shaped like a valid new karaoke Opus plan (not hand-patched gate fields only).

    Mirrors fields the updated SCHEMA/prompt require so planner→dry-run tests exercise
    ``normalize_karaoke_plan`` + ``apply_coherence_gates``.
    """
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
            # Caption fallback sample (standard when clip missing)
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
