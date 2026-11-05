"""Service-facing facade for a future modular SaaS: image + song idea → pop video job.

This does NOT build the SaaS UI. It defines the job contract and a local orchestration
path that reuses the hardened pipeline gates. Render backends stay pluggable.

Contract: one job → finished MP4 **or** typed actionable failure
(coverage|narrative|storyboard|art|consequence|gfx|sing|gate|budget|plan).
Never assemble an incomplete story.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .coverage import CoverageError, assert_coverage
from .creative_contract import ensure_creative_contract
from .failures import FailureKind, JobFailure, failure_from_exception
from .graphics_lint import assert_graphics_and_sing, lint_overlays
from .identity import CharacterRefs, farm_lock_suffix, ref_images_for_scene, singing_instruction
from .lipsync import decide_take, offset_candidates
from .overlays import (
    NO_TEXT_NEG,
    build_overlay_texts,
    model_text_forbidden,
    overlays_to_json,
    terminal_must_be_blank,
)
from .plan_gates import apply_coherence_gates
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
    failure_kind: str = ''
    report: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'job_id': self.job_id, 'stage': self.stage,
            'video_path': self.video_path, 'overlays_path': self.overlays_path,
            'timeline_path': self.timeline_path, 'error': self.error,
            'hint': self.hint, 'failure_kind': self.failure_kind,
            'finished_mp4': bool(self.video_path) if self.ok else False,
            'report': self.report,
        }


def _default_plan_from_idea(req: PopVideoRequest) -> dict:
    """Minimal Watch Me–class plan scaffold for dry-run / tests.

    Mouths-closed performance, ≤5 scenes, structural required_shots, before/after state,
    consequence edges, art bible. Not a clone of any specific benchmark video.
    """
    idea = req.song_idea.strip()
    dual = bool(re_search_contrast(idea))
    scenes = [
        {
            'id': 's01_setup',
            'prompt': f'[LEAD] WIDE establishes the world for: {idea}. No jewellery. Mouth closed.',
            'motion': 'gentle push-in', 'role': 'setup', 'tags': 'SETUP', 'size_lens': 'WIDE 35mm',
            'world': 'A', 'allegiance': 'lead',
            'world_before': {'place': 'home', 'prop:remote': 'hand', 'watching': 'feed'},
            'action': 'establish the trap of the feed',
            'world_after': {'place': 'home', 'prop:remote': 'hand', 'watching': 'feed'},
            'prop_state': {'remote': 'in_hand'},
            'requires_next': ['s02_perf'],
        },
        {
            'id': 's02_perf',
            'prompt': '[LEAD][HERO] MCU reacts to the lyric beat, mouth closed, eyes sharp, no singing',
            'motion': 'subtle head sway on the beat', 'role': 'performance_closed', 'tags': 'HOOK',
            'size_lens': 'MCU 50mm', 'emotion': 'defiant', 'world': 'A', 'allegiance': 'lead',
            'world_before': {'place': 'home', 'watching': 'feed'},
            'action': 'glare and decide to dump the feed',
            'world_after': {'place': 'home', 'watching': 'rejected'},
            'prop_state': {'remote': 'raised'},
            'requires_next': ['s03_action'],
        },
        {
            'id': 's03_action',
            'prompt': '[LEAD] CU yanks the wall plug, cable sparks, no chains, mouth closed',
            'motion': 'yank action', 'role': 'action', 'tags': 'ACTION', 'size_lens': 'CU 85mm',
            'world': 'B' if dual else 'A', 'allegiance': 'lead',
            'world_before': {'prop:plug': 'wall', 'lights': 'on'},
            'action': 'yank the wall plug',
            'world_after': {'prop:plug': 'yanked', 'lights': 'on'},
            'prop_state': {'plug': 'yanked', 'scale': 'wall_plug'},
            'requires_next': ['s04_twist'],
        },
        {
            'id': 's04_twist',
            'prompt': '[GROK] MS robot yanks the cable',
            'motion': 'twist reveal', 'role': 'robot', 'tags': 'TWIST',
            'structural_role': 'twist', 'size_lens': 'MS 35mm',
            'world': 'B' if dual else 'A', 'allegiance': 'systems',
            'world_before': {'prop:plug': 'yanked', 'who_controls': 'unknown'},
            'action': 'reveal the robot still holds power',
            'world_after': {'prop:plug': 'yanked', 'who_controls': 'robot'},
            'prop_state': {'plug': 'yanked', 'scale': 'wall_plug'},
            'requires_next': ['s05_payoff'],
        },
        {
            'id': 's05_payoff',
            'prompt': '[OVERSEER] MCU holds a blank dark handheld gadget, mouth closed',
            'motion': 'payoff hold', 'role': 'payoff', 'tags': 'PAYOFF',
            'structural_role': 'payoff', 'size_lens': 'MCU 50mm',
            'terminal_text': 'WHY WOULD I DECEIVE YOU?', 'world': 'A', 'allegiance': 'overseer',
            'world_before': {'who_controls': 'robot', 'reveal': False},
            'action': 'overseer reveal with blank gadget',
            'world_after': {'who_controls': 'overseer', 'reveal': True},
            'prop_state': {'gadget': 'blank_dark'},
            'requires_next': [],
        },
    ]
    premise = idea[:160] if len(idea) >= 12 else f'Visual story for: {idea}'
    retell = (
        f'An independent viewer sees: {premise}'
        if len(premise) >= 12 else
        f'An independent viewer can retell the visual story for {idea}'
    )
    plan = {
        'scenes': scenes,
        'required_shots': ['s04_twist', 's05_payoff'],
        'viewer_retell': retell,
        'payoff_design': {
            'scene_id': 's05_payoff',
            'summary': 'Overseer reveal; who really controlled the plug',
            'world_after': {'who_controls': 'overseer', 'reveal': True},
        },
        'lines': [
            {'i': 0, 'shows': 'setup', 'fact': idea[:80], 'v': [{'kind': 'scene', 'id': 's01_setup'}]},
            {'i': 1, 'shows': 'perf', 'fact': '', 'v': [{'kind': 'scene', 'id': 's02_perf'}]},
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
        'arc': premise,
        'art_bible': {
            'photoreal': True,
            'banned_styles': ['clay', 'cartoon', 'toy', 'mannequin'],
            'prop_locks': {'plug': {'scale': 'wall_plug', 'mesh': 'household_outlet'}},
            'mouths_closed_default': True,
        },
        'creative_contract': {
            'visual_premise': premise,
            'viewer_retell': retell,
            'payoff_design': {
                'scene_id': 's05_payoff',
                'summary': 'Overseer reveal; who really controlled the plug',
                'world_after': {'who_controls': 'overseer', 'reveal': True},
            },
            'character_anchors': [
                {'id': 'LEAD', 'styling': 'lead from user image', 'signature': 'uploaded likeness'},
                {'id': 'GROK', 'styling': 'photoreal robot unit', 'signature': 'faction robot'},
                {'id': 'OVERSEER', 'styling': 'founder figure', 'signature': 'handheld gadget'},
            ],
            'performance_beats': [
                {'scene_id': 's02_perf', 'accent': 'hook', 'emotion': 'defiant',
                 'musical_cue': 'chorus', 'mouths_closed': True},
            ],
            'shot_variety': {
                'scales': ['WIDE', 'MCU', 'CU', 'MS'],
                'physical_interactions': True,
            },
            'location_arcs': (
                [
                    {'location': 'server rack hall', 'states': ['powered', 'yanked dark'],
                     'payoff_scene': 's05_payoff'},
                ] if dual else [
                    {'location': 'home', 'states': ['watching feed', 'feed rejected / reveal'],
                     'payoff_scene': 's05_payoff'},
                ]
            ),
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
                'hud': [{'text': 'SYS.OK', 'scene_id': 's01_setup', 'style': 'hud',
                         'composite': True, 'plate': 's01_setup', 'diegetic': True}],
                'kinetic': [{'line': 2, 'text': 'PULL', 'style': 'kinetic_slam',
                             'composite': True, 'plate': 's03_action'}],
                'terminal': [{'scene_id': 's05_payoff', 'text': 'WHY WOULD I DECEIVE YOU?',
                              'composite': True, 'plate': 's05_payoff', 'diegetic': True,
                              'state_change': True}],
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

    def _fail(self, exc: BaseException, report: dict, *, stage: str = '') -> PopVideoResult:
        jf = failure_from_exception(exc, stage=stage or getattr(exc, 'stage', '') or '')
        report['failure'] = jf.to_dict()
        try:
            json.dump(report['failure'], open(os.path.join(self.work, 'failure.json'), 'w'), indent=1)
        except OSError:
            pass
        return PopVideoResult(
            ok=False, job_id=self.req.job_id,
            stage=jf.stage or stage or 'error',
            error=jf.message, hint=jf.hint or str(getattr(exc, 'hint', '') or ''),
            failure_kind=jf.kind.value if isinstance(jf.kind, FailureKind) else str(jf.kind),
            report=report,
        )

    def run(self, *, dry_run: bool = True,
            available_clips: Optional[Dict[str, str]] = None,
            screen_results: Optional[dict] = None,
            lipsync_takes: Optional[dict] = None,
            rejected_ids: Optional[List[str]] = None,
            storyboard_review: Optional[dict] = None,
            timeline_shots: Optional[List[dict]] = None) -> PopVideoResult:
        """Run planning + gates. ``dry_run=True`` (default) never calls paid renderers.

        Result is either gates_passed / finished mp4, or a typed failure_kind.
        """
        report: Dict[str, Any] = {'dry_run': dry_run}
        stage = 'plan'
        try:
            self.req.validate()
            self.watch.start('plan')
            sing_on = bool((self.req.extras or {}).get('sing_enabled')) or os.environ.get('GV_SING', '0') == '1'
            raw = self.planner(self.req)
            # Inject review before shared gates (required — no fail-open)
            if storyboard_review is not None:
                raw = dict(raw)
                raw['storyboard_review'] = storyboard_review
            stage = 'coherence_gates'
            self.watch.start('coherence_gates')
            gated = apply_coherence_gates(
                raw,
                song_idea=self.req.song_idea,
                storyboard_review=storyboard_review if storyboard_review is not None
                else raw.get('storyboard_review'),
                sing_enabled=sing_on,
                require_storyboard=True,
                allow_large=bool((self.req.extras or {}).get('allow_large_plan')),
                creative_mode=(self.req.extras or {}).get('creative_mode'),
            )
            plan = gated['plan']
            report.update(gated['reports'])
            with open(os.path.join(self.work, 'plan.json'), 'w') as fh:
                json.dump(plan, fh, indent=1)
            for name in ('story_model', 'narrative_qa', 'creative_contract', 'gfx_plan_lint'):
                if name in gated['reports']:
                    with open(os.path.join(self.work, f'{name}.json'), 'w') as fh:
                        json.dump(gated['reports'][name], fh, indent=1)
            self.watch.ok(
                'coherence_gates',
                f"{len(plan.get('scenes', []))} scenes mode={plan.get('performance_mode')}",
            )
            report['performance_mode'] = plan.get('performance_mode')
            report['plan_fix'] = plan.get('plan_fix')

            # Identity routing + no-text / blank terminals on every prompt
            cast = CharacterRefs()
            cast.add('LEAD', self.req.image_path)
            cast.add('HERO', self.req.image_path)
            for sc in plan['scenes']:
                refs = ref_images_for_scene(sc, cast)
                sc['refs'] = refs
                sc['lock'] = farm_lock_suffix(sc, cast)
                sing = singing_instruction(sc) if sing_on else ''
                pr = sc.get('prompt') or ''
                if sing and sing not in pr:
                    pr = f'{pr} {sing}'.strip()
                pr = terminal_must_be_blank(model_text_forbidden(pr))
                if sc['lock']:
                    pr = f"{pr} {sc['lock']}".strip()
                sc['prompt'] = pr

            # Screen-check policy (injected results for tests / after real gen)
            rejected = list(rejected_ids or [])
            if screen_results is not None:
                stage = 'screen_check'
                self.watch.start('screen_check')
                from .coverage import critical_scene_ids, required_payoff_ids
                bad, verdicts = filter_rejections(
                    screen_results, critical_ids=required_payoff_ids(plan) or critical_scene_ids(plan['scenes']))
                rejected.extend(sorted(bad))
                report['screen_check'] = {'rejected': sorted(bad), 'verdicts': verdicts}
                json.dump(verdicts, open(os.path.join(self.work, 'screen_check.json'), 'w'), indent=1)
                self.watch.ok('screen_check', f'rejected={sorted(bad)}')

            # Render plan (cache-aware); dry_run only plans
            stage = 'render'
            self.watch.start('render')
            jobs = [{
                'id': sc['id'], 'kind': 'i2v', 'out': os.path.join(self.work, 'grok', f"{sc['id']}.mp4"),
                'prompt': sc['prompt'], 'tier': 'broll' if sc.get('role') == 'action' else 'hero',
                'refs': sc.get('refs') or [],
            } for sc in plan['scenes']]
            if available_clips:
                os.makedirs(os.path.join(self.work, 'grok'), exist_ok=True)
                for sid, path in available_clips.items():
                    dst = os.path.join(self.work, 'grok', f'{sid}.mp4')
                    if path and os.path.exists(path) and not os.path.exists(dst):
                        try:
                            with open(dst, 'wb') as fh:
                                fh.write(b'0' * 1001)
                        except OSError:
                            pass
            rplan = plan_renders(jobs, RenderBudget(i2v=len(jobs) + 2))
            report['render_plan'] = rplan.to_dict()
            if not dry_run and self.render_exec:
                report['render_result'] = self.render_exec(rplan.to_dict())
            self.watch.ok('render', f"reused={rplan.reused} grok={rplan.to_grok} local={rplan.to_local}")

            # Coverage + rejected required climax abort
            stage = 'coverage'
            self.watch.start('coverage')
            avail = available_clips or {
                sc['id']: os.path.join(self.work, 'grok', f"{sc['id']}.mp4")
                for sc in plan['scenes']
                if os.path.exists(os.path.join(self.work, 'grok', f"{sc['id']}.mp4"))
            }
            cov = assert_coverage(
                plan['scenes'], avail.keys(), plan=plan, rejected_ids=rejected or None,
            )
            report['coverage'] = cov
            self.watch.ok('coverage', f"{cov['pct']}% required={cov.get('required_shots')}")

            stage = 'timeline'
            self.watch.start('timeline')
            pin_path = os.path.join(self.work, 'timeline_pinned.json')
            pinned = load_pinned_timeline(pin_path, plan)
            if timeline_shots is not None:
                shots_raw = timeline_shots
                report['timeline_source'] = 'injected'
            elif pinned:
                shots_raw = pinned['shots']
                report['timeline_source'] = 'pin_fp_match'
            else:
                shots = build_scene_timeline(plan['scenes'], avail, max_uses=2)
                assert_reuse_cap(shots, max_uses=2)
                shots_raw = [s.to_dict() for s in shots]
                save_pinned_timeline(pin_path, plan, shots_raw)
                report['timeline_source'] = 'scene_order'
            # Graphics + SING reuse lint
            assert_graphics_and_sing(shots_raw, plan)
            tl_path = os.path.join(self.work, 'timeline.json')
            with open(tl_path, 'w') as fh:
                json.dump({'plan_fp': plan['plan_fp'], 'shots': shots_raw}, fh, indent=1)
            self.watch.ok('timeline')

            # Overlays (picture-first; long cards need plate refs)
            stage = 'overlays'
            self.watch.start('overlays')
            timings = [{'i': i, 'start': i * 2.0, 'end': i * 2.0 + 1.8}
                       for i in range(len(plan.get('lines') or []))]
            overlays = build_overlay_texts(plan, timings)
            ov_json = overlays_to_json(overlays)
            orep = lint_overlays(ov_json)
            report['overlay_lint'] = orep.to_dict()
            if not orep.ok:
                raise JobFailure(
                    kind=FailureKind.GFX, message=orep.summary,
                    stage='gfx_lint', hint='Attach plate/src on long story/terminal overlays.',
                    details=orep.to_dict(),
                )
            ov_path = os.path.join(self.work, 'overlay_texts.json')
            with open(ov_path, 'w') as fh:
                json.dump(ov_json, fh, indent=1)
            report['overlays'] = len(overlays)
            report['no_text_neg'] = NO_TEXT_NEG[:80]
            self.watch.ok('overlays', f'{len(overlays)} overlays')

            # Lip-sync decisions (injected takes) — only meaningful when SING opted in
            if lipsync_takes and sing_on:
                stage = 'lipsync'
                self.watch.start('lipsync')
                ls_out = {}
                for shot_id, takes in lipsync_takes.items():
                    ls_out[shot_id] = decide_take(takes, cutaway='broll').to_dict()
                with open(os.path.join(self.work, 'lipsync_pin.json'), 'w') as fh:
                    json.dump(ls_out, fh, indent=1)
                report['lipsync'] = ls_out
                report['lipsync_offsets'] = offset_candidates()
                self.watch.ok('lipsync')

            video_path = ''
            if not dry_run and (self.req.extras or {}).get('video_path'):
                video_path = str(self.req.extras['video_path'])

            return PopVideoResult(
                ok=True, job_id=self.req.job_id,
                stage='finished' if video_path else 'gates_passed',
                video_path=video_path,
                overlays_path=ov_path, timeline_path=tl_path, report=report,
            )
        except (JobFailure, CoverageError, TimelineBuildError, WatchdogError) as e:
            try:
                self.watch.fail(stage, str(e), hint=getattr(e, 'hint', '') or '')
            except WatchdogError:
                pass
            return self._fail(e, report, stage=stage)
        except (FileNotFoundError, ValueError) as e:
            return self._fail(e, report, stage=stage)
        except Exception as e:
            return PopVideoResult(
                ok=False, job_id=self.req.job_id, stage='error',
                error=f'{type(e).__name__}: {e}', hint='See progress.json and report',
                failure_kind=FailureKind.PLAN.value, report=report,
            )
