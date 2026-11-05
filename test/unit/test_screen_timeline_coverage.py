#!/usr/bin/env python3
import json, os, sys, tempfile, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.screen_policy import evaluate_screen_result, filter_rejections, waive_other_problem
from pipeline.coverage import CoverageError, assert_coverage, plan_fingerprint
from pipeline.timeline_policy import (
    TimelineBuildError, build_scene_timeline, load_pinned_timeline,
    save_pinned_timeline, assert_reuse_cap,
)


class TestScreenPolicy(unittest.TestCase):
    def test_robot_other_problem_waived(self):
        w = waive_other_problem('Robot/android is the main subject')
        self.assertEqual(w, 'cast_or_robot_subject')
        v = evaluate_screen_result({'other_problem': True, 'issue': 'Two robots/androids are the main subjects'})
        self.assertTrue(v.ok)
        self.assertTrue(v.waived)

    def test_founder_gadget_waived(self):
        v = evaluate_screen_result({
            'other_problem': True,
            'issue': "Her handheld device's lit screen faces the camera",
            'screen_not_facing_camera': False,
        }, story_critical=True)
        self.assertTrue(v.ok)

    def test_garbled_text_still_fails(self):
        v = evaluate_screen_result({
            'other_problem': True,
            'issue': 'garbled readable text across the terminal',
        })
        self.assertFalse(v.ok)

    def test_critical_soft_other_kept(self):
        bad, verdicts = filter_rejections(
            {'s52': {'other_problem': True, 'issue': 'something odd but not garbled'}},
            critical_ids=['s52'],
        )
        self.assertNotIn('s52', bad)
        self.assertTrue(verdicts['s52']['waived'])


class TestCoverage(unittest.TestCase):
    def test_missing_twist_aborts(self):
        scenes = [
            {'id': 's01', 'prompt': 'setup'},
            {'id': 's52_grok_yank', 'prompt': 'yank [TWIST]', 'tags': 'TWIST'},
            {'id': 's57', 'prompt': 'gadget [PAYOFF]', 'tags': 'PAYOFF'},
        ]
        with self.assertRaises(CoverageError) as cm:
            assert_coverage(scenes, ['s01'])
        self.assertIn('TWIST', str(cm.exception))
        self.assertEqual(cm.exception.exit_code, 8)

    def test_low_coverage_aborts(self):
        scenes = [{'id': f's{i:02d}', 'prompt': 'x'} for i in range(10)]
        with self.assertRaises(CoverageError):
            assert_coverage(scenes, ['s00', 's01'], min_ratio=0.9)

    def test_fingerprint_changes_with_prompt(self):
        a = plan_fingerprint({'scenes': [{'id': 's1', 'prompt': 'a'}]})
        b = plan_fingerprint({'scenes': [{'id': 's1', 'prompt': 'b'}]})
        self.assertNotEqual(a, b)


class TestTimeline(unittest.TestCase):
    def test_scene_order_and_reuse_cap(self):
        scenes = [{'id': f's{i}', 'dur': 1.0} for i in range(4)]
        avail = {f's{i}': f'/clips/s{i}.mp4' for i in range(4)}
        shots = build_scene_timeline(scenes, avail, max_uses=2, require_coverage=False)
        self.assertEqual([s.scene_id for s in shots], ['s0', 's1', 's2', 's3'])
        assert_reuse_cap(shots, max_uses=2)

    def test_reuse_cap_blocks_looping(self):
        scenes = [{'id': 's1', 'dur': 1.0}] * 5
        avail = {'s1': '/clips/s1.mp4'}
        with self.assertRaises(TimelineBuildError):
            build_scene_timeline(scenes, avail, max_uses=2, require_coverage=False, broll_pool=[])

    def test_stale_pin_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            plan = {'scenes': [{'id': 's1', 'prompt': 'one'}]}
            path = os.path.join(td, 'timeline_pinned.json')
            save_pinned_timeline(path, plan, [{'scene_id': 's1'}])
            self.assertIsNotNone(load_pinned_timeline(path, plan))
            plan2 = {'scenes': [{'id': 's1', 'prompt': 'two'}]}
            self.assertIsNone(load_pinned_timeline(path, plan2))


if __name__ == '__main__':
    unittest.main()
