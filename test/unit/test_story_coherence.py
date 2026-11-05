#!/usr/bin/env python3
"""Dry-run acceptance tests for Watch Me–class story coherence (P0–P2).

No Grok spend, no assemble, no benchmark-specific lore beyond generic fixtures.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.coverage import CoverageError, assert_coverage, assert_rejected_required, required_payoff_ids
from pipeline.failures import FailureKind, JobFailure
from pipeline.graphics_lint import assert_graphics_and_sing, lint_timeline_graphics, lint_sing_reuse
from pipeline.narrative_gate import (
    assert_narrative_qa, assert_storyboard_review, narrative_checklist, storyboard_must_abort,
)
from pipeline.plan_fix import assert_zero_sing, fix_plan_singing
from pipeline.service import PopVideoJob, PopVideoRequest
from pipeline.story_model import (
    assert_story_model, ensure_scene_states, required_shot_ids, validate_story_model,
)


def _wm_like_plan():
    """Watch Me–class fixture: ≤28 scenes, mouths closed, structural payoff, consequence edges."""
    scenes = []
    for i in range(1, 9):
        sid = f's{i:02d}'
        nxt = f's{i + 1:02d}' if i < 8 else None
        structural = ''
        tags = 'BEAT'
        if i == 1:
            tags, role = 'SETUP', 'setup'
        elif i == 7:
            tags, role, structural = 'TWIST', 'twist', 'twist'
        elif i == 8:
            tags, role, structural = 'PAYOFF', 'payoff', 'payoff'
        else:
            role = 'action' if i % 2 == 0 else 'performance_closed'
        sc = {
            'id': sid,
            'prompt': f'[LEAD] photoreal living-room beat {i}, mouth closed, remote in hand',
            'role': role, 'tags': tags, 'allegiance': 'lead',
            'world_before': {'place': 'living_room', 'feed': 'on' if i < 4 else 'off'},
            'action': f'advance beat {i}',
            'world_after': {'place': 'living_room', 'feed': 'off' if i >= 4 else 'on'},
            'prop_state': {'remote': 'hand'},
            'requires_next': [nxt] if nxt else [],
        }
        if structural:
            sc['structural_role'] = structural
        if i == 4:
            sc['prompt'] = '[LEAD] CU yanks the wall plug, mouth closed'
            sc['action'] = 'yank the wall plug'
            sc['prop_state'] = {'plug': 'yanked', 'scale': 'wall_plug'}
            sc['requires_next'] = ['s05']
        scenes.append(sc)
    return {
        'scenes': scenes,
        'required_shots': ['s07', 's08'],
        'arc': 'Feed traps her → she dumps it → builds her own channel → curls up watching this.',
        'creative_contract': {
            'visual_premise': 'Feed traps her → she dumps it → builds her channel → bookend sofa.',
            'character_anchors': [
                {'id': 'LEAD', 'styling': 'fixed wardrobe', 'signature': 'remote + popcorn'},
            ],
            'graphics_plan': {'model_renders_text': False, 'hud': [], 'kinetic': [], 'terminal': []},
            'worlds': [{'id': 'A', 'label': 'primary', 'grade': 'warm', 'camera': 'static',
                        'design': '60s living room', 'palette': 'mustard-tangerine'}],
        },
        'art_bible': {
            'photoreal': True,
            'banned_styles': ['clay', 'cartoon', 'toy'],
            'prop_locks': {'plug': {'scale': 'wall_plug'}},
            'mouths_closed_default': True,
        },
        'lines': [{'i': i, 'v': [{'kind': 'scene', 'id': f's{i + 1:02d}'}]} for i in range(8)],
    }


class TestRequiredClimaxStructural(unittest.TestCase):
    def test_missing_climax_aborts(self):
        plan = _wm_like_plan()
        # Drop climax clips S07/S08 from availability
        avail = [f's{i:02d}' for i in range(1, 7)]
        with self.assertRaises(CoverageError) as cm:
            assert_coverage(plan['scenes'], avail, plan=plan)
        self.assertTrue(cm.exception.details.get('missing_twist_payoff'))
        self.assertIn('s07', cm.exception.details['missing_twist_payoff'])
        self.assertIn('s08', cm.exception.details['missing_twist_payoff'])

    def test_rejected_climax_aborts(self):
        plan = _wm_like_plan()
        avail = [f's{i:02d}' for i in range(1, 9)]
        with self.assertRaises(CoverageError) as cm:
            assert_coverage(plan['scenes'], avail, plan=plan,
                            rejected_ids=['/work/grok/s08.mp4.qcfail.mp4'])
        self.assertIn('s08', cm.exception.details.get('rejected_required', []))
        with self.assertRaises(CoverageError):
            assert_rejected_required(plan, ['s07.mp4.screen.mp4'])

    def test_structural_ids_not_overseer_keyword(self):
        """OVERSEER alone is not auto-critical; structural required_shots / roles are."""
        scenes = [
            {'id': 's01', 'prompt': '[OVERSEER] walks by', 'tags': 'SETUP'},
            {'id': 's02', 'prompt': '[LEAD] holds gadget', 'structural_role': 'payoff', 'tags': 'PAYOFF'},
        ]
        plan = {'scenes': scenes, 'required_shots': ['s02']}
        self.assertEqual(required_payoff_ids(plan), ['s02'])
        self.assertNotIn('s01', required_shot_ids(plan))


class TestStoryboardHardGate(unittest.TestCase):
    def test_bad_score_aborts_before_generation(self):
        reason = storyboard_must_abort({'score': 6, 'verdict': 'needs work'})
        self.assertIsNotNone(reason)
        self.assertIn('must not go to camera', reason.lower())
        with self.assertRaises(JobFailure) as cm:
            assert_storyboard_review({}, {'score': 6, 'verdict': 'messy'})
        self.assertEqual(cm.exception.kind, FailureKind.STORYBOARD)

    def test_must_not_go_to_camera_verdict(self):
        reason = storyboard_must_abort({'score': 9, 'verdict': 'must not go to camera until fixed'})
        self.assertIsNotNone(reason)
        with self.assertRaises(JobFailure):
            assert_storyboard_review({'storyboard_review': {
                'score': 8, 'verdict': 'Cute but must not go to camera',
            }})

    def test_good_review_passes(self):
        self.assertIsNone(storyboard_must_abort({'score': 8, 'verdict': 'ready'}))
        assert_storyboard_review({}, {'score': 8, 'verdict': 'ship it'})


class TestSingMouthsClosed(unittest.TestCase):
    def test_watch_me_plan_zero_sing(self):
        plan = fix_plan_singing(_wm_like_plan())
        self.assertEqual(plan['performance_mode'], 'mouths_closed')
        self.assertEqual(plan['plan_fix']['singing_shots'], [])
        assert_zero_sing(plan)
        for sc in plan['scenes']:
            self.assertNotIn('[SING]', sc.get('prompt', ''))
            self.assertIn('mouth closed', sc.get('prompt', '').lower())

    def test_strips_injected_sing_quota(self):
        dirty = _wm_like_plan()
        dirty['scenes'][1]['prompt'] = '[SING][HERO] front-facing close-up singing this line'
        dirty['scenes'][1]['role'] = 'singing'
        dirty['scenes'][1]['tags'] = 'SING'
        fixed = fix_plan_singing(dirty, sing_share=0.35)
        assert_zero_sing(fixed)
        self.assertEqual(fixed['plan_fix']['singing_shots'], [])

    def test_opt_in_keeps_dedicated_sing(self):
        plan = {
            'scenes': [
                {'id': 'a', 'prompt': '[SING] slam the button', 'role': 'action'},
                {'id': 'b', 'prompt': '[SING][HERO] singing this LINE "hey"',
                 'role': 'singing', 'tags': 'SING'},
            ]
        }
        fixed = fix_plan_singing(plan, sing_enabled=True)
        self.assertIn('a', fixed['plan_fix']['sing_stripped'])
        self.assertIn('b', fixed['plan_fix']['singing_shots'])


class TestStoryModelArtConsequence(unittest.TestCase):
    def test_invalid_consequence_edge_fails(self):
        plan = ensure_scene_states(_wm_like_plan())
        plan['scenes'][3]['requires_next'] = ['s99_missing']
        with self.assertRaises(JobFailure) as cm:
            assert_story_model(plan)
        self.assertEqual(cm.exception.kind, FailureKind.CONSEQUENCE)

    def test_banned_art_style_fails(self):
        plan = ensure_scene_states(_wm_like_plan())
        plan['scenes'][2]['prompt'] = '[CLAUDE] matte clay-orange robot smiles cartoonishly'
        with self.assertRaises(JobFailure) as cm:
            assert_story_model(plan)
        self.assertEqual(cm.exception.kind, FailureKind.ART)

    def test_prop_scale_conflict_fails(self):
        plan = ensure_scene_states(_wm_like_plan())
        plan['scenes'][0]['prompt'] = '[LEAD] reaches for the wall plug'
        plan['scenes'][5]['prompt'] = '[LEAD] rooftop giant plug suitcase-scale'
        with self.assertRaises(JobFailure) as cm:
            assert_story_model(plan)
        self.assertEqual(cm.exception.kind, FailureKind.ART)

    def test_scene_cap(self):
        plan = ensure_scene_states(_wm_like_plan())
        plan['scenes'] = plan['scenes'] + [
            {'id': f'x{i}', 'prompt': 'filler', 'world_before': {}, 'action': 'x',
             'world_after': {'n': i}, 'requires_next': []}
            for i in range(30)
        ]
        rep = validate_story_model(plan, max_scenes=28, require_states=False, strict_edges=False)
        self.assertFalse(rep.ok)
        self.assertTrue(any(i['code'] == 'scene_cap' for i in rep.issues))

    def test_wm_like_passes(self):
        plan = ensure_scene_states(_wm_like_plan())
        rep = assert_story_model(plan)
        self.assertTrue(rep.ok)
        self.assertLessEqual(rep.scene_count, 28)


class TestGraphicsAndSingReuse(unittest.TestCase):
    def test_excessive_black_void_gfx_fails(self):
        timeline = [
            {'src': ('clip', 's01'), 't0': 0, 't1': 2},
            {'src': ('gfx', 'bignum', {'bg': 'black'}), 't0': 2, 't1': 9, 'g': 'bignum',
             'black_void': True},
        ]
        with self.assertRaises(JobFailure) as cm:
            assert_graphics_and_sing(timeline)
        self.assertEqual(cm.exception.kind, FailureKind.GFX)

    def test_gfx_share_exceeded_fails(self):
        # 4s gfx of 10s = 40%
        timeline = [
            {'kind': 'clip', 'scene_id': 's01', 't0': 0, 't1': 6, 'plate': True},
            {'kind': 'gfx', 'g': 'headline', 't0': 6, 't1': 10, 'black_void': True},
        ]
        rep = lint_timeline_graphics(timeline, max_black_s=99.0, max_share=0.10)
        self.assertFalse(rep.ok)
        self.assertTrue(any(i['code'] == 'gfx_share_exceeded' for i in rep.issues))

    def test_plated_short_gfx_ok(self):
        timeline = [
            {'kind': 'clip', 'scene_id': 's01', 't0': 0, 't1': 8},
            {'kind': 'gfx', 'g': 'slam', 't0': 8, 't1': 8.8, 'plate': 's01'},
        ]
        rep = lint_timeline_graphics(timeline)
        self.assertTrue(rep.ok, rep.summary)

    def test_duplicate_sing_fails(self):
        plan = {
            'scenes': [
                {'id': 'sing_a', 'role': 'singing', 'tags': 'SING', 'prompt': '[SING][HERO] vocal',
                 '_sing': True},
            ]
        }
        timeline = [
            {'kind': 'clip', 'scene_id': 'sing_a', 'src': '/c/sing_a.mp4', 't0': 0, 't1': 2},
            {'kind': 'clip', 'scene_id': 'sing_a', 'src': '/c/sing_a.mp4', 't0': 2, 't1': 4},
        ]
        with self.assertRaises(JobFailure) as cm:
            assert_graphics_and_sing(timeline, plan)
        self.assertEqual(cm.exception.kind, FailureKind.SING)


class TestNarrativeQA(unittest.TestCase):
    def test_missing_premise_fails(self):
        plan = ensure_scene_states(_wm_like_plan())
        plan['arc'] = ''
        plan['creative_contract']['visual_premise'] = ''
        with self.assertRaises(JobFailure) as cm:
            assert_narrative_qa(plan)
        self.assertEqual(cm.exception.kind, FailureKind.NARRATIVE)

    def test_wm_like_passes(self):
        plan = ensure_scene_states(_wm_like_plan())
        rep = assert_narrative_qa(plan)
        self.assertTrue(rep.ok)


class TestPopVideoJobContract(unittest.TestCase):
    def _img_and_clips(self, td, sids):
        img = os.path.join(td, 'lead.png')
        open(img, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        clips = {}
        for sid in sids:
            p = os.path.join(td, f'{sid}.mp4')
            open(p, 'wb').write(b'0' * 2000)
            clips[sid] = p
        return img, clips

    def test_watch_me_like_plan_passes_zero_sing(self):
        with tempfile.TemporaryDirectory() as td:
            sids = [f's{i:02d}_{x}' for i, x in enumerate(
                ('setup', 'perf', 'action', 'twist', 'payoff'), 1)]
            # Default planner uses s01_setup … s05_payoff
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='wm1', image_path=img, song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review={'score': 8, 'verdict': 'ready for camera'},
            )
            self.assertTrue(res.ok, res.error)
            self.assertEqual(res.failure_kind, '')
            self.assertEqual(res.report.get('performance_mode'), 'mouths_closed')
            self.assertEqual(res.report.get('plan_fix', {}).get('singing_shots'), [])
            self.assertIn(res.stage, ('gates_passed', 'finished'))

    def test_missing_climax_typed_failure(self):
        with tempfile.TemporaryDirectory() as td:
            img, clips = self._img_and_clips(td, ['s01_setup', 's02_perf', 's03_action'])
            req = PopVideoRequest(
                job_id='fail_cov', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(dry_run=True, available_clips=clips)
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.COVERAGE.value)
            self.assertTrue(res.report.get('failure'))
            self.assertFalse(res.to_dict().get('finished_mp4'))

    def test_rejected_climax_typed_failure(self):
        with tempfile.TemporaryDirectory() as td:
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='fail_rej', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips, rejected_ids=['s05_payoff.mp4.qcfail.mp4'],
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.COVERAGE.value)
            self.assertIn('rejected', res.error.lower())

    def test_bad_storyboard_aborts_before_generation(self):
        with tempfile.TemporaryDirectory() as td:
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='fail_sb', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review={'score': 5, 'verdict': 'must not go to camera until fixed'},
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.STORYBOARD.value)
            self.assertEqual(res.stage, 'storyboard_review')

    def test_duplicate_sing_timeline_fails(self):
        with tempfile.TemporaryDirectory() as td:
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='fail_sing', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
                extras={'sing_enabled': True},
            )
            # Inject a timeline that reuses a SING clip twice
            def planner(r):
                from pipeline.service import _default_plan_from_idea
                p = _default_plan_from_idea(r)
                p['scenes'][1]['role'] = 'singing'
                p['scenes'][1]['tags'] = 'SING'
                p['scenes'][1]['prompt'] = '[SING][HERO] MCU singing this LINE "pull"'
                p['scenes'][1]['id'] = 's02_sing'
                # Keep consequence graph consistent after the id rename.
                p['scenes'][0]['requires_next'] = ['s02_sing']
                p['scenes'][1]['requires_next'] = ['s03_action']
                return p

            bad_tl = [
                {'scene_id': 's01_setup', 'src': clips['s01_setup'], 't0': 0, 't1': 1.5},
                {'scene_id': 's02_sing', 'src': clips['s02_perf'], 't0': 1.5, 't1': 3.0, 'sing': True},
                {'scene_id': 's02_sing', 'src': clips['s02_perf'], 't0': 3.0, 't1': 4.5, 'sing': True},
                {'scene_id': 's03_action', 'src': clips['s03_action'], 't0': 4.5, 't1': 6.0},
                {'scene_id': 's04_twist', 'src': clips['s04_twist'], 't0': 6.0, 't1': 7.5},
                {'scene_id': 's05_payoff', 'src': clips['s05_payoff'], 't0': 7.5, 't1': 9.0},
            ]
            clips2 = dict(clips)
            clips2['s02_sing'] = clips['s02_perf']
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips2, timeline_shots=bad_tl,
                storyboard_review={'score': 8, 'verdict': 'ok'},
            )
            self.assertFalse(res.ok, res.error)
            self.assertEqual(res.failure_kind, FailureKind.SING.value)

    def test_excessive_graphics_fails(self):
        with tempfile.TemporaryDirectory() as td:
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='fail_gfx', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
            )
            # ~50% black-void gfx
            bad_tl = [
                {'scene_id': 's01_setup', 'src': clips['s01_setup'], 't0': 0, 't1': 2},
                {'kind': 'gfx', 'g': 'bignum', 'src': ('gfx', 'bignum'), 't0': 2, 't1': 6,
                 'black_void': True},
                {'scene_id': 's04_twist', 'src': clips['s04_twist'], 't0': 6, 't1': 7},
                {'scene_id': 's05_payoff', 'src': clips['s05_payoff'], 't0': 7, 't1': 8},
            ]
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips, timeline_shots=bad_tl,
                storyboard_review={'score': 8, 'verdict': 'ok'},
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.GFX.value)

    def test_finished_or_typed_failure_contract(self):
        """Unattended job contract: ok with gates_passed, or failure_kind set — never silent."""
        with tempfile.TemporaryDirectory() as td:
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            img, clips = self._img_and_clips(td, sids)
            req = PopVideoRequest(
                job_id='contract', image_path=img, song_idea='idea',
                work_dir=os.path.join(td, 'work'),
                extras={'video_path': os.path.join(td, 'out.mp4')},
            )
            open(req.extras['video_path'], 'wb').write(b'0' * 100)
            res = PopVideoJob(req).run(
                dry_run=False, available_clips=clips,
                storyboard_review={'score': 9, 'verdict': 'go'},
            )
            # dry_run=False without render_exec still passes gates; extras video_path marks finished
            d = res.to_dict()
            if res.ok:
                self.assertTrue(d['finished_mp4'] or res.stage == 'gates_passed' or res.stage == 'finished')
            else:
                self.assertTrue(d['failure_kind'])
                self.assertFalse(d['finished_mp4'])


if __name__ == '__main__':
    unittest.main()
