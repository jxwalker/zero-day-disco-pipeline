#!/usr/bin/env python3
import os, sys, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.plan_fix import fix_plan_singing, fix_scene_singing, is_singing_shot
from pipeline.identity import (
    CharacterRefs, characters_in_prompt, duplicate_lead_flags,
    ref_images_for_scene, singing_allowed, singing_instruction,
)
from pipeline.lipsync import decide_take, offset_candidates, best_offset, search_offsets_and_decide


class TestPlanFixSinging(unittest.TestCase):
    def test_strip_sing_from_action(self):
        sc = fix_scene_singing({
            'id': 's15_stop_slam',
            'prompt': '[SING][HERO] front-facing close-up, eyes to lens, singing this line. '
                      'Top-down close-up Vex bare hand slams the stop button',
            'role': 'action',
        }, allow_sing=True)
        self.assertTrue(sc.get('_sing_stripped'))
        self.assertNotIn('[SING]', sc['prompt'])
        self.assertFalse(singing_allowed(sc))

    def test_keep_sing_on_hero_performance_when_opted_in(self):
        sc = {
            'id': 'sing_u12',
            'prompt': '[SING][HERO] front-facing close-up singing this LINE "pull the plug"',
            'role': 'singing', 'tags': 'SING',
        }
        self.assertTrue(is_singing_shot(sc))
        fixed = fix_scene_singing(sc, allow_sing=True)
        self.assertTrue(fixed.get('_sing'))
        self.assertIn('[SING]', fixed['prompt'])

    def test_story_default_strips_all_sing(self):
        """Watch Me rule: mouths closed; sing_share must not re-inject SING."""
        plan = fix_plan_singing({
            'scenes': [
                {'id': 'a', 'prompt': '[SING] slam the button', 'role': 'action'},
                {'id': 'b', 'prompt': '[SING][HERO] singing this LINE "hey"', 'role': 'singing', 'tags': 'SING'},
            ]
        }, sing_share=0.35)
        self.assertEqual(plan['performance_mode'], 'mouths_closed')
        self.assertEqual(plan['plan_fix']['singing_shots'], [])
        self.assertNotIn('[SING]', plan['scenes'][1]['prompt'])

    def test_opt_in_keeps_dedicated_sing_ignores_quota(self):
        plan = fix_plan_singing({
            'scenes': [
                {'id': 'a', 'prompt': '[SING] slam the button', 'role': 'action'},
                {'id': 'b', 'prompt': '[SING][HERO] singing this LINE "hey"', 'role': 'singing', 'tags': 'SING'},
            ]
        }, sing_share=0.35, sing_enabled=True)
        self.assertIn('a', plan['plan_fix']['sing_stripped'])
        self.assertIn('b', plan['plan_fix']['singing_shots'])


class TestIdentity(unittest.TestCase):
    def test_per_character_refs_no_cross_wire(self):
        cast = CharacterRefs()
        cast.add('GROK', '/refs/grok.png')
        cast.add('LEAD', '/refs/vex.png')
        cast.add('OVERSEER', '/refs/overseer.png')
        sc = {'id': 's08', 'prompt': '[GROK] robot arrives at the rack'}
        refs = ref_images_for_scene(sc, cast)
        self.assertEqual(refs, ['/refs/grok.png'])
        self.assertNotIn('/refs/vex.png', refs)
        self.assertNotIn('/refs/overseer.png', refs)

    def test_singing_instruction_only_on_sing_shots(self):
        action = {'id': 's15', 'prompt': 'slam button', 'role': 'action'}
        sing = {'id': 'sing_1', 'prompt': '[SING][HERO] vocal', 'role': 'singing', 'tags': 'SING'}
        self.assertEqual(singing_instruction(action, 'hello'), '')
        self.assertIn('hello', singing_instruction(sing, 'hello'))

    def test_duplicate_lead_qc(self):
        flags = duplicate_lead_flags([
            {'shot_id': 's22', 'identities': ['VEX', 'VEX', 'GROK']},
            {'shot_id': 's01', 'identities': ['VEX', 'CLAUDE']},
        ], lead_ids=('VEX', 'LEAD'))
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]['shot_id'], 's22')

    def test_characters_in_prompt(self):
        self.assertEqual(characters_in_prompt('[CLAUDE] and GPT tug the cable'), ['CLAUDE', 'GPT'])


class TestLipsync(unittest.TestCase):
    def test_never_pin_below_threshold(self):
        d = decide_take([
            {'path': 'a.mp4', 'score': 0.157, 'offset_s': 0.0},
            {'path': 'b.mp4', 'score': -0.103, 'offset_s': 0.0},
            {'path': 'c.mp4', 'score': 0.224, 'offset_s': 0.0},
        ], cutaway='broll.mp4')
        self.assertEqual(d.action, 'cutaway')
        self.assertEqual(d.cutaway, 'broll.mp4')

    def test_pin_passing_take(self):
        d = decide_take([
            {'path': 'fail.mp4', 'score': 0.1},
            {'path': 'ok.mp4', 'score': 0.55, 'offset_s': -0.08},
        ])
        self.assertEqual(d.action, 'pin')
        self.assertEqual(d.take, 'ok.mp4')
        self.assertEqual(d.offset_s, -0.08)

    def test_offset_search(self):
        self.assertEqual(offset_candidates(), [0.0, -0.08, 0.08, -0.16, 0.16])
        off, sc = best_offset([(0.0, 0.1), (-0.08, 0.4), (0.08, 0.2)])
        self.assertEqual((off, sc), (-0.08, 0.4))

    def test_search_offsets_and_decide(self):
        def score_fn(path, off):
            return 0.5 if abs(off - (-0.08)) < 1e-9 and path.endswith('good.mp4') else 0.1
        d = search_offsets_and_decide(['good.mp4', 'bad.mp4'], score_fn)
        self.assertEqual(d.action, 'pin')
        self.assertAlmostEqual(d.offset_s, -0.08)


if __name__ == '__main__':
    unittest.main()
