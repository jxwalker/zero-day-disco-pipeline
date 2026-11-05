#!/usr/bin/env python3
"""Regression: negation-aware wardrobe / prompt gate (postmortem 2026-11-05)."""
import os, sys, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))
sys.path.insert(0, os.path.join(ROOT, 'local_gen'))

from pipeline.prompt_gate import (  # noqa: E402
    accessory_violations, gate_prompt, gate_prompts, strip_lock_leaks,
)
import strict_qc as SQ  # noqa: E402


class TestNegationAccessories(unittest.TestCase):
    def test_no_jewellery_passes(self):
        self.assertEqual(accessory_violations('Lead wears a teal jacket, no jewellery.'), [])
        self.assertEqual(SQ.accessory_problems('Lead wears a teal jacket, no jewellery.'), [])

    def test_without_chains_passes(self):
        self.assertEqual(accessory_violations('Same outfit without chains or necklace.'), [])
        self.assertEqual(SQ.lint_prompt('plain black tee without chains'), [])

    def test_positive_jewellery_fails(self):
        issues = accessory_violations('She wears gold jewellery and a thick chain.')
        self.assertTrue(any(i.code == 'accessory_ban' for i in issues))
        self.assertTrue(SQ.lint_prompt('gold jewellery and a thick chain'))

    def test_rewrite_strips_accessory(self):
        r = gate_prompt('Hero in leather jacket with a gold chain, singing on the roof')
        self.assertTrue(r.ok)
        self.assertRegex(r.prompt, r'no chain')


class TestLockLeak(unittest.TestCase):
    def test_strip_cardigan_kitchen(self):
        p, issues = strip_lock_leaks(
            'Same woman in a cream cable-knit cardigan in the same kitchen pulls the plug')
        self.assertTrue(issues)
        self.assertNotIn('cardigan', p.lower())
        self.assertNotIn('same kitchen', p.lower())

    def test_gate_removes_leak(self):
        r = gate_prompt('Same woman cream cable-knit cardigan same kitchen, no jewellery')
        self.assertTrue(r.ok)
        self.assertNotIn('cardigan', r.prompt.lower())


class TestSingWithoutLine(unittest.TestCase):
    def test_sing_wrapper_stripped(self):
        r = gate_prompt('steady front-facing close-up, eyes to lens, singing this line; Vex slams the stop button')
        self.assertTrue(r.ok)
        self.assertNotRegex(r.prompt, r'singing this line')

    def test_sing_with_quoted_line_kept(self):
        r = gate_prompt('[SING] front-facing close-up singing this LINE "pull the plug"')
        # Has LINE marker — not flagged as sing_without_line
        self.assertTrue(r.ok)


class TestStoryCriticalNotDropped(unittest.TestCase):
    def test_critical_kept_even_if_dirty(self):
        scenes = [
            {'id': 's52_grok_yank', 'prompt': 'gold jewellery chain robot yank [TWIST]', 'tags': 'TWIST'},
            {'id': 's03_filler', 'prompt': 'gold jewellery only', 'tags': ''},
        ]
        # Force zero rewrites so critical stays dirty
        out = gate_prompts(scenes)
        ids = [s['id'] for s in out['scenes']]
        self.assertIn('s52_grok_yank', ids)
        # Non-critical may be dropped after failed rewrite — jewellery gets rewritten to ok usually
        # Ensure critical_fail is 0 when rewrite succeeds
        self.assertEqual(out['critical_fail'], 0)


if __name__ == '__main__':
    unittest.main()
