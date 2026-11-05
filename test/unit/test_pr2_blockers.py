#!/usr/bin/env python3
"""Regression tests for PR #2 merge blockers — via public PopVideoJob / plan_gates entrypoints.

Blockers:
  1) graphics lint must allow endcard/karaoke infra; ban black-void narrative slides
  2) consequence edges must NOT be inferred away
  3) storyboard review required on generate AND resume (no fail-open)
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.failures import FailureKind, JobFailure
from pipeline.graphics_lint import (
    assert_graphics_and_sing, classify_gfx, lint_timeline_graphics, lint_plan_graphics,
)
from pipeline.narrative_gate import assert_storyboard_review, storyboard_must_abort
from pipeline.plan_gates import apply_coherence_gates
from pipeline.service import PopVideoJob, PopVideoRequest, _default_plan_from_idea
from pipeline.story_model import ensure_scene_states, validate_story_model, assert_story_model


def _img(td):
    p = os.path.join(td, 'lead.png')
    with open(p, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
    return p


def _clips(td, sids):
    out = {}
    for sid in sids:
        p = os.path.join(td, f'{sid}.mp4')
        with open(p, 'wb') as fh:
            fh.write(b'0' * 2000)
        out[sid] = p
    return out


SIDS = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
PASS_REVIEW = {'score': 8, 'verdict': 'ready for camera', 'viewer_retell': 'She dumps the feed, yanks the plug, and the overseer still holds power.'}


class TestBlocker1GraphicsInfraVsNarrative(unittest.TestCase):
    def test_typical_endcard_timeline_passes(self):
        """Repro: paced karaoke endcard >1.5s must NOT hard-fail (infra, not narrative slide)."""
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 8.0},
            {'src': ('clip', 's02'), 't0': 8.0, 't1': 16.0},
            # Typical karaoke endcard — several seconds, no plate
                {'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
                 't0': 16.0, 't1': 22.0,
                 'v': {'kind': 'gfx', 'g': 'endcard', 'p': {}, 'gfx_provenance': 'endcard'}},
        ]
        rep = lint_timeline_graphics(timeline)
        self.assertTrue(rep.ok, rep.summary)
        self.assertEqual(classify_gfx(timeline[-1], 'endcard'), 'infra')
        # Share excludes endcard
        self.assertLessEqual(rep.gfx_share, 0.10)
        assert_graphics_and_sing(timeline)

    def test_karaoke_caption_infra_excluded_from_share(self):
        timeline = [
            {'kind': 'clip', 'scene_id': 's01', 't0': 0, 't1': 5},
            {'kind': 'gfx', 'g': 'karaoke', 't0': 0, 't1': 5},  # overlays runtime; infra kind
            {'kind': 'gfx', 'g': 'endcard', 't0': 5, 't1': 8, 'gfx_provenance': 'endcard'},
        ]
        rep = lint_timeline_graphics(timeline)
        self.assertTrue(rep.ok, rep.summary)
        self.assertEqual(rep.narrative_gfx_s, 0.0)

    def test_black_void_bignum_narrative_slide_still_fails(self):
        timeline = [
            {'kind': 'clip', 'scene_id': 's01', 't0': 0, 't1': 4},
            {'kind': 'gfx', 'g': 'bignum', 't0': 4, 't1': 10, 'black_void': True, 'primary_story': True},
        ]
        with self.assertRaises(JobFailure) as cm:
            assert_graphics_and_sing(timeline)
        self.assertEqual(cm.exception.kind, FailureKind.GFX)
        self.assertIn('narrative', cm.exception.message.lower() + str(cm.exception.details).lower())

    def test_headline_story_share_still_capped(self):
        # 40% narrative headline void
        timeline = [
            {'kind': 'clip', 'scene_id': 's01', 't0': 0, 't1': 6},
            {'kind': 'gfx', 'g': 'headline', 't0': 6, 't1': 10, 'black_void': True},
        ]
        rep = lint_timeline_graphics(timeline, max_black_s=99.0)
        self.assertFalse(rep.ok)
        self.assertTrue(any(i['code'] == 'gfx_share_exceeded' for i in rep.issues))

    def test_plan_graphics_pre_gen_via_popvideojob(self):
        """Pre-generation: bare narrative story cards in graphics_plan abort before render."""
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            clips = _clips(td, SIDS)

            def planner(req):
                p = _default_plan_from_idea(req)
                p['storyboard_review'] = PASS_REVIEW
                p['creative_contract']['graphics_plan']['story'] = [
                    {'text': 'WE ASKED GPT-6', 'composite': True},  # no diegetic/plate
                ]
                return p

            req = PopVideoRequest(
                job_id='gfx_pre', image_path=img, song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips, storyboard_review=PASS_REVIEW,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.GFX.value)


class TestBlocker2NoInferredConsequenceEdges(unittest.TestCase):
    def test_ensure_scene_states_does_not_infer_edges(self):
        plan = {
            'scenes': [
                {
                    'id': 's1',
                    'prompt': '[LEAD] yanks the wall plug',
                    'role': 'action',
                    'world_before': {'plug': 'wall'},
                    'action': 'yank',
                    'world_after': {'plug': 'yanked'},
                    # deliberately NO requires_next
                },
                {
                    'id': 's2',
                    'prompt': '[LEAD] lights stay on',
                    'role': 'payoff',
                    'structural_role': 'payoff',
                    'world_before': {'lights': 'on'},
                    'action': 'reveal',
                    'world_after': {'lights': 'on', 'who': 'overseer'},
                },
            ],
            'required_shots': ['s2'],
        }
        filled = ensure_scene_states(plan)  # default infer_edges=False
        self.assertFalse(filled['scenes'][0].get('requires_next'))
        rep = validate_story_model(filled, require_states=True, strict_edges=True)
        self.assertFalse(rep.ok)
        self.assertTrue(any(i['code'] == 'missing_consequence_edge' for i in rep.issues))

    def test_popvideojob_fails_incomplete_consequence_planning(self):
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            clips = _clips(td, SIDS)

            def planner(req):
                p = _default_plan_from_idea(req)
                p['storyboard_review'] = PASS_REVIEW
                # Strip authored edges from the yank beat — must not be inferred back
                for sc in p['scenes']:
                    if sc['id'] == 's03_action':
                        sc.pop('requires_next', None)
                        sc['prompt'] = '[LEAD] CU yanks the wall plug, mouth closed'
                return p

            req = PopVideoRequest(
                job_id='edge_fail', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips, storyboard_review=PASS_REVIEW,
            )
            self.assertFalse(res.ok, res.error)
            self.assertEqual(res.failure_kind, FailureKind.CONSEQUENCE.value)
            self.assertIn('requires_next', res.error.lower() + str(res.report).lower())

    def test_apply_coherence_gates_preserves_missing_edge_failure(self):
        plan = _default_plan_from_idea(PopVideoRequest(
            job_id='x', image_path='/dev/null', song_idea='long enough song idea text here',
        ))
        # bypass image validate — just mutate plan
        for sc in plan['scenes']:
            if 'yank' in (sc.get('prompt') or '').lower() or sc.get('id') == 's03_action':
                sc.pop('requires_next', None)
        plan['storyboard_review'] = PASS_REVIEW
        with self.assertRaises(JobFailure) as cm:
            apply_coherence_gates(plan, song_idea='long enough song idea text here',
                                  storyboard_review=PASS_REVIEW)
        self.assertEqual(cm.exception.kind, FailureKind.CONSEQUENCE)


class TestBlocker3StoryboardRequiredNoFailOpen(unittest.TestCase):
    def test_missing_review_aborts(self):
        reason = storyboard_must_abort(None)
        self.assertIsNotNone(reason)
        self.assertIn('missing', reason.lower())
        with self.assertRaises(JobFailure) as cm:
            assert_storyboard_review({'scenes': []}, None)
        self.assertEqual(cm.exception.kind, FailureKind.STORYBOARD)

    def test_popvideojob_missing_review_fails(self):
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            clips = _clips(td, SIDS)
            req = PopVideoRequest(
                job_id='sb_miss', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            # No storyboard_review injected
            res = PopVideoJob(req).run(dry_run=True, available_clips=clips)
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.STORYBOARD.value)
            self.assertEqual(res.stage, 'storyboard_review')

    def test_resume_existing_plan_still_requires_passing_review(self):
        """Resume path: existing plan.json without review must still abort via plan_gates."""
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            plan = _default_plan_from_idea(PopVideoRequest(
                job_id='resume', image_path=img,
                song_idea='Dump the feed and watch this instead',
            ))
            # Simulate resumed artifact with no review
            plan.pop('storyboard_review', None)
            work = os.path.join(td, 'work')
            os.makedirs(work, exist_ok=True)
            with open(os.path.join(work, 'plan.json'), 'w') as fh:
                json.dump(plan, fh)
            with self.assertRaises(JobFailure) as cm:
                apply_coherence_gates(
                    json.load(open(os.path.join(work, 'plan.json'))),
                    song_idea='Dump the feed and watch this instead',
                    require_storyboard=True,
                )
            self.assertEqual(cm.exception.kind, FailureKind.STORYBOARD)

    def test_bad_score_still_aborts(self):
        with self.assertRaises(JobFailure):
            assert_storyboard_review({}, {'score': 4, 'verdict': 'needs work'})


class TestBlockerIntegrationPopVideoJobHappyPath(unittest.TestCase):
    def test_passing_job_with_endcard_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            clips = _clips(td, SIDS)
            req = PopVideoRequest(
                job_id='ok1', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            # Inject a realistic post-pace timeline including endcard
            tl = [
                {'scene_id': 's01_setup', 'src': clips['s01_setup'], 't0': 0, 't1': 2},
                {'scene_id': 's02_perf', 'src': clips['s02_perf'], 't0': 2, 't1': 4},
                {'scene_id': 's03_action', 'src': clips['s03_action'], 't0': 4, 't1': 6},
                {'scene_id': 's04_twist', 'src': clips['s04_twist'], 't0': 6, 't1': 8},
                {'scene_id': 's05_payoff', 'src': clips['s05_payoff'], 't0': 8, 't1': 10},
                {'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
                 't0': 10, 't1': 14,
                 'v': {'kind': 'gfx', 'g': 'endcard', 'gfx_provenance': 'endcard'}},
            ]
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review=PASS_REVIEW, timeline_shots=tl,
            )
            self.assertTrue(res.ok, res.error)
            self.assertEqual(res.report.get('performance_mode'), 'mouths_closed')


if __name__ == '__main__':
    unittest.main()
