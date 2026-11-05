#!/usr/bin/env python3
import os, sys, tempfile, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.overlays import (
    NO_TEXT_NEG, beat_cut_points, build_overlay_texts, model_text_forbidden,
    overlays_to_json, physical_payoff_required, terminal_must_be_blank,
)
from pipeline.term_composite import from_overlays, filter_for_overlay
from pipeline.renderer import RenderBudget, plan_renders, stretch_banned
from pipeline.service import PopVideoJob, PopVideoRequest
from pipeline.watchdog import ProgressWatchdog, WatchdogError


class TestOverlays(unittest.TestCase):
    def test_model_text_forbidden_appended(self):
        p = model_text_forbidden('A person walks')
        self.assertIn('no readable text', p.lower())
        self.assertIn(NO_TEXT_NEG[:20], p)

    def test_terminal_blank_steer(self):
        p = terminal_must_be_blank('She holds a glowing terminal full of logs')
        self.assertRegex(p, r'blank and dark')

    def test_build_story_and_terminal_overlays(self):
        plan = {
            'story_text': [{'from_line': 0, 'to_line': 1, 'kicker': 'MAIN', 'text': 'GPT edited 0.016%'}],
            'slams': [{'line': 1, 'text': 'yank'}],
            'scenes': [{
                'id': 's57', 'prompt': '[PAYOFF]', 'terminal_text': 'WHY WOULD I DECEIVE YOU?',
                'term_rect': [0.5, 0.2, 0.4, 0.4],
            }],
            'lines': [{'i': 0, 'v': [{'kind': 'scene', 'id': 's01'}]},
                      {'i': 1, 'v': [{'kind': 'scene', 'id': 's57'}]}],
        }
        timings = [{'i': 0, 'start': 0.0, 'end': 2.0}, {'i': 1, 'start': 2.0, 'end': 4.0}]
        ov = build_overlay_texts(plan, timings)
        kinds = {o.kind for o in ov}
        self.assertIn('story', kinds)
        self.assertIn('slam', kinds)
        self.assertIn('terminal', kinds)
        data = overlays_to_json(ov)
        self.assertTrue(any(d.get('g') == 'terminal' and 'DECEIVE' in d['text'] for d in data))

    def test_overlays_off_when_disabled(self):
        self.assertEqual(build_overlay_texts({'story_text': [{'from_line': 0, 'to_line': 0, 'kicker': 'X', 'text': 'Y'}]},
                                             [{'i': 0, 'start': 0, 'end': 1}], enabled=False), [])

    def test_beat_cuts_and_payoff_list(self):
        cuts = beat_cut_points([0.5, 1.0, 1.5, 2.0, 2.5], 'fast', t0=0.0, t1=3.0)
        self.assertEqual(cuts[0], 0.0)
        self.assertEqual(cuts[-1], 3.0)
        need = physical_payoff_required({'scenes': [
            {'id': 'a', 'tags': 'SETUP'}, {'id': 'b', 'prompt': '[PAYOFF] button'},
        ]})
        self.assertEqual(need, ['b'])

    def test_term_composite_filter(self):
        vf = from_overlays([{'g': 'terminal', 'text': 'hello\nworld', 't0': 1.0, 't1': 2.0,
                             'rect': [0.1, 0.1, 0.3, 0.3]}])
        self.assertIn('drawbox', vf)
        self.assertIn('drawtext', vf)
        self.assertIn('between(t', vf)


class TestRenderer(unittest.TestCase):
    def test_cache_reuse_no_regen(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 's1.png')
            open(out, 'wb').write(b'0' * 2000)
            plan = plan_renders([
                {'id': 's1', 'kind': 'gen', 'out': out, 'prompt': 'x'},
                {'id': 's2', 'kind': 'gen', 'out': os.path.join(td, 'missing.png'), 'prompt': 'y'},
            ], RenderBudget(gen=5))
            self.assertEqual(plan.reused, 1)
            self.assertEqual(plan.to_grok, 1)
            actions = {i.id: i.action for i in plan.items}
            self.assertEqual(actions['s1'], 'reuse_cache')
            self.assertEqual(actions['s2'], 'grok')

    def test_budget_guard(self):
        plan = plan_renders([
            {'id': f's{i}', 'kind': 'i2v', 'out': f'/nope/{i}.mp4', 'prompt': 'x'}
            for i in range(5)
        ], RenderBudget(i2v=2))
        self.assertEqual(plan.to_grok, 2)
        self.assertEqual(plan.skipped, 3)

    def test_local_fallback_tier(self):
        plan = plan_renders([
            {'id': 'b1', 'kind': 'i2v', 'out': '/nope/b1.mp4', 'prompt': 'x', 'tier': 'broll'},
        ], RenderBudget(i2v=5), prefer_local_for=('broll',))
        self.assertEqual(plan.to_local, 1)
        self.assertEqual(plan.items[0].action, 'local_fallback')

    def test_stretch_ban(self):
        self.assertTrue(stretch_banned(832, 480))
        self.assertFalse(stretch_banned(1280, 720))


class TestWatchdogAndService(unittest.TestCase):
    def test_watchdog_actionable_fail(self):
        with tempfile.TemporaryDirectory() as td:
            w = ProgressWatchdog(os.path.join(td, 'progress.json'), stall_s=9999)
            w.start('coverage')
            with self.assertRaises(WatchdogError) as cm:
                w.fail('coverage', 'missing TWIST clips')
            self.assertIn('hint', cm.exception.actionable().lower())

    def test_service_dry_run_success(self):
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, 'lead.png')
            open(img, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
            # Provide all clips so coverage passes
            clips = {}
            for sid in ('s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff'):
                p = os.path.join(td, f'{sid}.mp4')
                open(p, 'wb').write(b'0' * 2000)
                clips[sid] = p
            req = PopVideoRequest(
                job_id='t1', image_path=img, song_idea='Pull the plug on the rack',
                work_dir=os.path.join(td, 'work'),
                extras={'sing_enabled': True},
            )
            res = PopVideoJob(req).run(
                dry_run=True,
                available_clips=clips,
                storyboard_review={'score': 8, 'verdict': 'ready'},
                screen_results={
                    's04_twist': {'other_problem': True, 'issue': 'Robot/android is the main subject'},
                    's05_payoff': {'other_problem': True,
                                   'issue': "Her handheld device's lit screen faces the camera"},
                },
                lipsync_takes={
                    's02_perf': [
                        {'path': 'bad.mp4', 'score': 0.1},
                        {'path': 'good.mp4', 'score': 0.6, 'offset_s': -0.08},
                    ],
                },
            )
            self.assertTrue(res.ok, res.error)
            self.assertTrue(os.path.exists(res.overlays_path))
            self.assertTrue(os.path.exists(res.timeline_path))
            # lipsync only runs when SING opted in; mouths-closed default skips it
            self.assertIn('lipsync', res.report)
            self.assertEqual(res.report['lipsync']['s02_perf']['action'], 'pin')

    def test_service_aborts_missing_payoff(self):
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, 'lead.png')
            open(img, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
            clips = {sid: os.path.join(td, f'{sid}.mp4') for sid in
                     ('s01_setup', 's02_perf', 's03_action')}
            for p in clips.values():
                open(p, 'wb').write(b'0' * 2000)
            req = PopVideoRequest(
                job_id='t2', image_path=img, song_idea='idea', work_dir=os.path.join(td, 'work2'),
            )
            res = PopVideoJob(req).run(dry_run=True, available_clips=clips)
            self.assertFalse(res.ok)
            self.assertTrue(res.failure_kind)
            blob = (res.error + res.failure_kind).upper()
            self.assertTrue('PAYOFF' in blob or 'COVERAGE' in blob or 'CLIMAX' in blob, res.error)


if __name__ == '__main__':
    unittest.main()
