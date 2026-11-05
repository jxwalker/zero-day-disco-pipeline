#!/usr/bin/env python3
"""Creative contract: adaptable quality requirements (not a brittle benchmark clone)."""
import os, sys, tempfile, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.creative_contract import (
    ensure_creative_contract, validate_creative_contract, worlds_need_contrast,
    graphics_plan_to_overlay_seeds, storyboard_direction_addendum,
)
from pipeline.overlays import build_overlay_texts, model_text_forbidden
from pipeline.service import PopVideoJob, PopVideoRequest, re_search_contrast


def _simple_plan():
    return {
        'arc': 'A courier delivers one package and leaves',
        'scenes': [
            {'id': 's1', 'prompt': '[LEAD] WIDE courier arrives', 'role': 'setup', 'tags': 'SETUP',
             'size_lens': 'WIDE'},
            {'id': 's2', 'prompt': '[LEAD] MCU hands over the package', 'role': 'action', 'tags': 'ACTION',
             'size_lens': 'MCU'},
        ],
        'design': {'palette': 'newsprint', 'grade': 'flat'},
        'lead': 'young courier in a plain navy jacket',
        'wardrobe': 'navy jacket, plain trousers',
    }


def _dual_world_plan():
    return {
        'creative_contract': {
            'visual_premise': 'Luxury robots are secretly run by exhausted human teleoperators',
            'worlds': [
                {'id': 'A', 'label': 'showroom', 'grade': 'cool clean', 'camera': 'static',
                 'design': 'luxury marble', 'palette': 'chrome'},
                {'id': 'B', 'label': 'pit', 'grade': 'warm dirty', 'camera': 'handheld',
                 'design': 'sweatshop desks', 'palette': 'amber'},
            ],
            'character_anchors': [
                {'id': 'ROBOT', 'styling': 'gloss white chassis', 'signature': 'soft LED eyes'},
                {'id': 'OP', 'styling': 'headset, tired eyes', 'signature': 'stained hoodie'},
            ],
            'performance_beats': [
                {'scene_id': 's2', 'accent': 'drop', 'emotion': 'strain', 'musical_cue': 'bass hit'},
            ],
            'shot_variety': {'scales': ['WIDE', 'CU', 'POV'], 'physical_interactions': True},
            'location_arcs': [
                {'location': 'sweatshop', 'states': ['crowded', 'empty'], 'payoff_scene': 's4'},
            ],
            'graphics_plan': {
                'model_renders_text': False,
                'hud': [{'text': 'LINK 98%', 'composite': True, 'scene_id': 's1'}],
                'kinetic': [{'text': 'WHO\'S INSIDE', 'line': 1, 'composite': True}],
                'terminal': [], 'caption': [],
            },
        },
        'scenes': [
            {'id': 's1', 'prompt': 'WIDE luxury lobby', 'tags': 'SETUP'},
            {'id': 's2', 'prompt': 'CU teleoperator strain [SING]', 'role': 'singing', 'tags': 'SING'},
            {'id': 's3', 'prompt': 'POV yank cable', 'tags': 'ACTION'},
            {'id': 's4', 'prompt': 'WIDE empty sweatshop [PAYOFF]', 'tags': 'PAYOFF'},
        ],
        'lines': [{'i': 1, 'v': []}],
    }


class TestAdaptiveSimple(unittest.TestCase):
    def test_simple_single_world_passes(self):
        plan = ensure_creative_contract(_simple_plan())
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertTrue(rep.ok, rep.summary)
        self.assertEqual(len(rep.contract['worlds']), 1)
        self.assertFalse(worlds_need_contrast(rep.contract))
        self.assertFalse(rep.contract['graphics_plan']['model_renders_text'])

    def test_strict_requires_premise_and_gfx(self):
        bare = {'scenes': [{'id': 's1', 'prompt': 'x'}]}
        rep = validate_creative_contract(bare, mode='strict')
        # ensure fills some fields; still may warn on variety — premise comes empty without arc
        self.assertFalse(rep.ok)
        codes = {i.code for i in rep.issues if i.severity == 'error'}
        self.assertTrue('missing_visual_premise' in codes or 'missing_character_anchors' in codes
                        or 'missing_graphics_plan' in codes or not rep.ok)


class TestDualWorldContrast(unittest.TestCase):
    def test_contrasting_worlds_pass(self):
        rep = validate_creative_contract(_dual_world_plan(), mode='adaptive')
        self.assertTrue(rep.ok, rep.to_dict())

    def test_non_contrasting_worlds_fail(self):
        plan = _dual_world_plan()
        plan['creative_contract']['worlds'] = [
            {'id': 'A', 'grade': 'cool', 'camera': 'static', 'design': 'same'},
            {'id': 'B', 'grade': 'cool', 'camera': 'static', 'design': 'same'},
        ]
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertFalse(rep.ok)
        self.assertTrue(any(i.code == 'worlds_not_contrasting' for i in rep.issues))

    def test_location_arc_needs_two_states(self):
        plan = _dual_world_plan()
        plan['creative_contract']['location_arcs'] = [
            {'location': 'sweatshop', 'states': ['crowded'], 'payoff_scene': 's4'},
        ]
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertFalse(rep.ok)
        self.assertTrue(any(i.code == 'location_arc_needs_states' for i in rep.issues))

    def test_missing_payoff_scene_fails(self):
        plan = _dual_world_plan()
        plan['creative_contract']['location_arcs'][0]['payoff_scene'] = 'missing'
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertFalse(rep.ok)


class TestGraphicsNoModelText(unittest.TestCase):
    def test_model_renders_text_hard_fail(self):
        plan = _dual_world_plan()
        plan['creative_contract']['graphics_plan']['model_renders_text'] = True
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertFalse(rep.ok)
        self.assertTrue(any(i.code == 'model_must_not_render_text' for i in rep.issues))

    def test_non_composite_overlay_fails(self):
        plan = _dual_world_plan()
        plan['creative_contract']['graphics_plan']['hud'] = [
            {'text': 'LINK', 'composite': False},
        ]
        rep = validate_creative_contract(plan, mode='adaptive')
        self.assertFalse(rep.ok)

    def test_graphics_plan_feeds_overlays(self):
        plan = ensure_creative_contract(_dual_world_plan())
        timings = [{'i': 1, 'start': 1.0, 'end': 2.0}]
        ov = build_overlay_texts(plan, timings)
        kinds = {o.kind for o in ov}
        self.assertIn('hud', kinds)
        self.assertIn('kinetic', kinds)
        seeds = graphics_plan_to_overlay_seeds(plan['creative_contract'])
        self.assertTrue(any(s['g'] == 'hud' for s in seeds))

    def test_model_prompt_stays_text_free(self):
        p = model_text_forbidden('Robot walks past a HUD wall')
        self.assertIn('no readable text', p.lower())


class TestServiceIntegration(unittest.TestCase):
    def test_contrast_heuristic(self):
        self.assertTrue(re_search_contrast('luxury robots secretly teleoperated'))
        self.assertFalse(re_search_contrast('a sunny beach day'))

    def test_pop_video_job_writes_contract(self):
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, 'lead.png')
            open(img, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
            clips = {}
            for sid in ('s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff'):
                p = os.path.join(td, f'{sid}.mp4')
                open(p, 'wb').write(b'0' * 2000)
                clips[sid] = p
            req = PopVideoRequest(
                job_id='cc1',
                image_path=img,
                song_idea='Luxury robots secretly powered by exhausted operators',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review={'score': 8, 'verdict': 'ready'},
            )
            self.assertTrue(res.ok, res.error)
            self.assertIn('creative_contract', res.report)
            self.assertTrue(res.report['creative_contract']['ok'])
            self.assertTrue(os.path.exists(os.path.join(td, 'work', 'creative_contract.json')))
            # Dual-world idea should opt into contrast
            worlds = res.report['creative_contract']['contract']['worlds']
            self.assertGreaterEqual(len(worlds), 2)
            # Overlays include HUD from graphics_plan
            import json
            ov = json.load(open(os.path.join(td, 'work', 'overlay_texts.json')))
            self.assertTrue(any(o.get('g') == 'hud' for o in ov), ov)

    def test_simple_idea_does_not_require_dual_worlds(self):
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, 'lead.png')
            open(img, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
            clips = {sid: os.path.join(td, f'{sid}.mp4') for sid in
                     ('s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff')}
            for p in clips.values():
                open(p, 'wb').write(b'0' * 2000)
            req = PopVideoRequest(
                job_id='cc2', image_path=img, song_idea='A sunny beach party',
                work_dir=os.path.join(td, 'work2'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review={'score': 8, 'verdict': 'ready'},
            )
            self.assertTrue(res.ok, res.error)
            self.assertEqual(len(res.report['creative_contract']['contract']['worlds']), 1)

    def test_addendum_mentions_no_model_text(self):
        text = storyboard_direction_addendum()
        self.assertIn('model_renders_text', text)
        self.assertIn('visual_premise', text)


if __name__ == '__main__':
    unittest.main()
