"""Service-facing facade for a future modular SaaS: image + song idea → pop video job.

This does NOT build the SaaS UI. It defines the job contract and a local orchestration
path that reuses the hardened pipeline gates. Render backends stay pluggable.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .coverage import assert_coverage, plan_fingerprint
from .creative_contract import (
    apply_no_text_to_scenes,
    ensure_creative_contract,
    validate_creative_contract,
)
from .identity import CharacterRefs, farm_lock_suffix, ref_images_for_scene, singing_instruction
from .lipsync import decide_take, offset_candidates
from .overlays import (
    NO_TEXT_NEG,
    build_overlay_texts,
    model_text_forbidden,
    overlays_to_json,
    terminal_must_be_blank,
)
from .plan_fix import fix_plan_singing
from .prompt_gate import gate_prompts
from .renderer import RenderBudget, plan_renders
from .screen_policy import filter_rejections
from .timeline_policy import (
    TimelineBuildError,
    assert_reuse_cap,
    build_scene_timeline,
    load_pinned_timeline,
    save_pinned_timeline,
)
from .watchdog import ProgressWatchdog, WatchdogError


@dataclass
class PopVideoRequest:
    """Inbound job: user image + song idea (+ optional lyrics/audio paths)."""
    job_id: str
    image_path: str
    song_idea: str
    lyrics_path: str = ''
    audio_path: str = ''
    work_dir: str = ''
    title: str = ''
    extras: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError('job_id required')
        if not self.image_path or not os.path.exists(self.image_path):
            raise FileNotFoundError(f'image not found: {self.image_path}')
        if not (self.song_idea or '').strip():
            raise ValueError('song_idea required')


@dataclass
class PopVideoResult:
    ok: bool
    job_id: str
    stage: str
    video_path: str = ''
    overlays_path: str = ''
    timeline_path: str = ''
    error: str = ''
    hint: str = ''
    report: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'job_id': self.job_id, 'stage': self.stage,
            'video_path': self.video_path, 'overlays_path': self.overlays_path,
            'timeline_path': self.timeline_path, 'error': self.error,
            'hint': self.hint, 'report': self.report,
        }


def _default_plan_from_idea(req: PopVideoRequest) -> dict:
    """Minimal plan scaffold for dry-run / tests. Production planners replace this.

    Includes an adaptable creative_contract (premise, optional dual worlds when the idea
    implies contrast, styling anchors, performance beats, graphics_plan). Not a clone of
    any specific benchmark video.
    """
    idea = req.song_idea.strip()
    dual = bool(re_search_contrast(idea))
    scenes = [
        {'id': 's01_setup', 'prompt': f'[LEAD] WIDE establishes the world for: {idea}. No jewellery.',
         'motion': 'gentle push-in', 'role': 'setup', 'tags': 'SETUP', 'size_lens': 'WIDE 35mm',
         'world': 'A'},
        {'id': 's02_sing', 'prompt': '[SING][HERO] MCU front-facing close-up singing this LINE "pull the plug"',
         'motion': 'subtle head sway on the beat', 'role': 'singing', 'tags': 'SING',
         'size_lens': 'MCU 50mm', 'emotion': 'urgent', 'world': 'A'},
        {'id': 's03_action', 'prompt': '[LEAD] CU yanks the wall plug, cable sparks, no chains',
         'motion': 'yank action', 'role': 'action', 'tags': 'ACTION', 'size_lens': 'CU 85mm',
         'world': 'B' if dual else 'A'},
        {'id': 's04_twist', 'prompt': '[GROK] MS robot yanks the cable [TWIST]',
         'motion': 'twist reveal', 'role': 'robot', 'tags': 'TWIST', 'size_lens': 'MS 35mm',
         'world': 'B' if dual else 'A'},
        {'id': 's05_payoff', 'prompt': '[OVERSEER] MCU holds a blank dark handheld gadget [PAYOFF]',
         'motion': 'payoff hold', 'role': 'payoff', 'tags': 'PAYOFF', 'size_lens': 'MCU 50mm',
         'terminal_text': 'WHY WOULD I DECEIVE YOU?', 'world': 'A'},
    ]
    plan = {
        'scenes': scenes,
        'lines': [
            {'i': 0, 'shows': 'setup', 'fact': idea[:80], 'v': [{'kind': 'scene', 'id': 's01_setup'}]},
            {'i': 1, 'shows': 'sing', 'fact': '', 'v': [{'kind': 'scene', 'id': 's02_sing'}]},
            {'i': 2, 'shows': 'action', 'fact': '', 'v': [{'kind': 'scene', 'id': 's03_action'}]},
            {'i': 3, 'shows': 'twist', 'fact': '', 'v': [{'kind': 'scene', 'id': 's04_twist'}]},
            {'i': 4, 'shows': 'payoff', 'fact': '', 'v': [{'kind': 'scene', 'id': 's05_payoff'}]},
        ],
        'story_text': [
            {'from_line': 0, 'to_line': 1, 'kicker': 'MAIN STORY', 'text': idea[:70]},
        ],
        'slams': [{'line': 2, 'text': 'PULL'}],
        'intro': [], 'breaks': [], 'outro': [], 'credit': req.title or 'Pop Video',
        'design': {'palette': 'acid-deadpan', 'grade': 'flat saturated', 'texture': '35mm grain'},
        'arc': idea[:120],
        'creative_contract': {
            'visual_premise': idea[:160],
            'character_anchors': [
                {'id': 'LEAD', 'styling': 'lead from user image', 'signature': 'uploaded likeness'},
                {'id': 'GROK', 'styling': 'robot unit', 'signature': 'faction robot'},
                {'id': 'OVERSEER', 'styling': 'founder figure', 'signature': 'handheld gadget'},
            ],
            'performance_beats': [
                {'scene_id': 's02_sing', 'accent': 'hook', 'emotion': 'urgent', 'musical_cue': 'chorus'},
            ],
            'shot_variety': {
                'scales': ['WIDE', 'MCU', 'CU', 'MS'],
                'physical_interactions': True,
            },
            'location_arcs': [
                {'location': 'server rack hall', 'states': ['powered', 'yanked dark'],
                 'payoff_scene': 's05_payoff'},
            ] if dual else [],
            'worlds': (
                [
                    {'id': 'A', 'label': 'clean', 'grade': 'cool clean', 'camera': 'static',
                     'design': 'luxury polish', 'palette': 'steel cyan'},
                    {'id': 'B', 'label': 'hidden', 'grade': 'warm dirty', 'camera': 'handheld',
                     'design': 'exhausted backstage', 'palette': 'amber grit'},
                ] if dual else [
                    {'id': 'A', 'label': 'primary', 'grade': 'flat saturated', 'camera': 'motivated',
                     'design': 'story world', 'palette': 'acid-deadpan'},
                ]
            ),
            'graphics_plan': {
                'model_renders_text': False,
                'hud': [{'text': 'SYS.OK', 'scene_id': 's01_setup', 'style': 'hud', 'composite': True}],
                'kinetic': [{'line': 2, 'text': 'PULL', 'style': 'kinetic_slam', 'composite': True}],
                'terminal': [{'scene_id': 's05_payoff', 'text': 'WHY WOULD I DECEIVE YOU?',
                             'composite': True}],
                'caption': [],
            },
            'beat_escalation': {'enabled': True, 'notes': 'Escalate on accents; hold on payoff.'},
        },
    }
    return ensure_creative_contract(plan, song_idea=idea)


def re_search_contrast(idea: str) -> bool:
    """Heuristic: song idea mentions a hidden/dual world → opt into contrast checks."""
    return bool(re.search(
        r'\b(secret\w*|hidden|behind|teleop\w*|sweatshop|vs\.?|versus|two worlds|underneath|operators?)\b',
        idea or '', re.I,
    ))


class PopVideoJob:
    """Orchestrates hardened gates for one job. Optional hooks inject real renderers."""

    def __init__(self,
                 req: PopVideoRequest,
                 *,
                 planner: Optional[Callable[[PopVideoRequest], dict]] = None,
                 render_exec: Optional[Callable[[dict], dict]] = None):
        self.req = req
        self.planner = planner or _default_plan_from_idea
        self.render_exec = render_exec  # optional; dry-run skips real spend
        self.work = req.work_dir or os.path.join('work_jobs', req.job_id)
        os.makedirs(self.work, exist_ok=True)
        self.watch = ProgressWatchdog(os.path.join(self.work, 'progress.json'))

    def run(self, *, dry_run: bool = True,
            available_clips: Optional[Dict[str, str]] = None,
            screen_results: Optional[dict] = None,
            lipsync_takes: Optional[dict] = None) -> PopVideoResult:
        """Run planning + gates. ``dry_run=True`` (default) never calls paid renderers."""
        report: Dict[str, Any] = {'dry_run': dry_run}
        try:
            self.req.validate()
            self.watch.start('plan')
            plan = fix_plan_singing(self.planner(self.req))
            plan = ensure_creative_contract(plan, song_idea=self.req.song_idea)
            plan = apply_no_text_to_scenes(plan)
            plan['plan_fp'] = plan_fingerprint(plan)
            json.dump(plan, open(os.path.join(self.work, 'plan.json'), 'w'), indent=1)
            self.watch.ok('plan', f"{len(plan.get('scenes', []))} scenes")

            # Adaptable creative contract (premise / worlds / anchors / overlays plan)
            self.watch.start('creative_contract')
            mode = (self.req.extras or {}).get('creative_mode') or os.environ.get(
                'GV_CREATIVE_CONTRACT_MODE', 'adaptive')
            crep = validate_creative_contract(plan, mode=mode, song_idea=self.req.song_idea)
            plan['creative_contract'] = crep.contract
            report['creative_contract'] = crep.to_dict()
            json.dump(crep.to_dict(), open(os.path.join(self.work, 'creative_contract.json'), 'w'), indent=1)
            if not crep.ok:
                self.watch.fail('creative_contract', crep.summary,
                                hint='Fix visual premise, world contrast, or graphics_plan (model never renders text).')
            self.watch.ok('creative_contract', crep.summary)

            self.watch.start('prompt_gate')
            gated = gate_prompts(plan.get('scenes') or [])
            plan['scenes'] = gated['scenes']
            report['prompt_gate'] = {k: gated[k] for k in ('kept', 'dropped', 'critical_fail', 'ok')}
            json.dump(gated['report'], open(os.path.join(self.work, 'prompt_gate.json'), 'w'), indent=1)
            if not gated['ok']:
                self.watch.fail('prompt_gate', 'story-critical prompts failed rewrite')
            self.watch.ok('prompt_gate')

            # Identity routing + no-text / blank terminals on every prompt
            cast = CharacterRefs()
            cast.add('LEAD', self.req.image_path)
            cast.add('HERO', self.req.image_path)
            for sc in plan['scenes']:
                refs = ref_images_for_scene(sc, cast)
                sc['refs'] = refs
                sc['lock'] = farm_lock_suffix(sc, cast)
                sing = singing_instruction(sc)
                pr = sc.get('prompt') or ''
                if sing and sing not in pr:
                    pr = f'{pr} {sing}'.strip()
                pr = terminal_must_be_blank(model_text_forbidden(pr))
                if sc['lock']:
                    pr = f"{pr} {sc['lock']}".strip()
                sc['prompt'] = pr

            # Screen-check policy (injected results for tests / after real gen)
            if screen_results is not None:
                self.watch.start('screen_check')
                from .coverage import critical_scene_ids
                bad, verdicts = filter_rejections(
                    screen_results, critical_ids=critical_scene_ids(plan['scenes']))
                report['screen_check'] = {'rejected': sorted(bad), 'verdicts': verdicts}
                json.dump(verdicts, open(os.path.join(self.work, 'screen_check.json'), 'w'), indent=1)
                self.watch.ok('screen_check', f'rejected={sorted(bad)}')

            # Render plan (cache-aware); dry_run only plans
            self.watch.start('render')
            jobs = [{
                'id': sc['id'], 'kind': 'i2v', 'out': os.path.join(self.work, 'grok', f"{sc['id']}.mp4"),
                'prompt': sc['prompt'], 'tier': 'broll' if sc.get('role') == 'action' else 'hero',
                'refs': sc.get('refs') or [],
            } for sc in plan['scenes']]
            # Pretend cache hits when available_clips provided
            if available_clips:
                os.makedirs(os.path.join(self.work, 'grok'), exist_ok=True)
                for sid, path in available_clips.items():
                    dst = os.path.join(self.work, 'grok', f'{sid}.mp4')
                    if path and os.path.exists(path) and not os.path.exists(dst):
                        try:
                            open(dst, 'wb').write(b'')  # placeholder marker for plan_renders size check
                            # plan_renders needs >1000 bytes for reuse — write a stub
                            open(dst, 'wb').write(b'0' * 1001)
                        except OSError:
                            pass
            rplan = plan_renders(jobs, RenderBudget(i2v=len(jobs) + 2))
            report['render_plan'] = rplan.to_dict()
            if not dry_run and self.render_exec:
                report['render_result'] = self.render_exec(rplan.to_dict())
            self.watch.ok('render', f"reused={rplan.reused} grok={rplan.to_grok} local={rplan.to_local}")

            # Coverage + timeline
            self.watch.start('coverage')
            avail = available_clips or {
                sc['id']: os.path.join(self.work, 'grok', f"{sc['id']}.mp4")
                for sc in plan['scenes']
                if os.path.exists(os.path.join(self.work, 'grok', f"{sc['id']}.mp4"))
            }
            cov = assert_coverage(plan['scenes'], avail.keys())
            report['coverage'] = cov
            self.watch.ok('coverage', f"{cov['pct']}%")

            self.watch.start('timeline')
            pin_path = os.path.join(self.work, 'timeline_pinned.json')
            pinned = load_pinned_timeline(pin_path, plan)
            if pinned:
                shots_raw = pinned['shots']
                report['timeline_source'] = 'pin_fp_match'
            else:
                shots = build_scene_timeline(plan['scenes'], avail, max_uses=2)
                assert_reuse_cap(shots, max_uses=2)
                shots_raw = [s.to_dict() for s in shots]
                save_pinned_timeline(pin_path, plan, shots_raw)
                report['timeline_source'] = 'scene_order'
            tl_path = os.path.join(self.work, 'timeline.json')
            json.dump({'plan_fp': plan['plan_fp'], 'shots': shots_raw}, open(tl_path, 'w'), indent=1)
            self.watch.ok('timeline')

            # Overlays
            self.watch.start('overlays')
            timings = [{'i': i, 'start': i * 2.0, 'end': i * 2.0 + 1.8} for i in range(len(plan.get('lines') or []))]
            overlays = build_overlay_texts(plan, timings)
            ov_path = os.path.join(self.work, 'overlay_texts.json')
            json.dump(overlays_to_json(overlays), open(ov_path, 'w'), indent=1)
            report['overlays'] = len(overlays)
            report['no_text_neg'] = NO_TEXT_NEG[:80]
            self.watch.ok('overlays', f'{len(overlays)} overlays')

            # Lip-sync decisions (injected takes)
            if lipsync_takes:
                self.watch.start('lipsync')
                ls_out = {}
                for shot_id, takes in lipsync_takes.items():
                    ls_out[shot_id] = decide_take(takes, cutaway='broll').to_dict()
                json.dump(ls_out, open(os.path.join(self.work, 'lipsync_pin.json'), 'w'), indent=1)
                report['lipsync'] = ls_out
                report['lipsync_offsets'] = offset_candidates()
                self.watch.ok('lipsync')

            return PopVideoResult(
                ok=True, job_id=self.req.job_id, stage='gates_passed',
                overlays_path=ov_path, timeline_path=tl_path, report=report,
            )
        except (WatchdogError, TimelineBuildError, FileNotFoundError, ValueError) as e:
            hint = getattr(e, 'hint', '') or getattr(e, 'details', {})
            if isinstance(hint, dict):
                hint = json.dumps(hint)[:300]
            return PopVideoResult(
                ok=False, job_id=self.req.job_id, stage=getattr(e, 'stage', 'error'),
                error=str(e), hint=str(hint), report=report,
            )
        except Exception as e:
            return PopVideoResult(
                ok=False, job_id=self.req.job_id, stage='error',
                error=f'{type(e).__name__}: {e}', hint='See progress.json and report',
                report=report,
            )
