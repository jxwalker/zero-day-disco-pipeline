#!/usr/bin/env python3
"""Final PR #2 release-blocker repros (public entrypoints).

Blocker 1: karaoke non-plated headline >1.5s (line_card / fallback) must pass when tagged
as caption infra; bare narrative headline still fails; endcard still passes.
Blocker 2: representative karaoke Opus output → normalize → dry-run gates must pass;
legacy incomplete plans fail without auto-faking edges.
Also: score-less verdict fails; fabricated independent retell fails; accent coverage.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

from pipeline.failures import FailureKind, JobFailure
from pipeline.graphics_lint import assert_graphics_and_sing, classify_gfx, lint_timeline_graphics
from pipeline.karaoke_plan import mark_code_caption, normalize_karaoke_plan, representative_opus_plan
from pipeline.narrative_gate import assert_narrative_qa, assert_storyboard_review, storyboard_must_abort
from pipeline.plan_gates import apply_coherence_gates
from pipeline.service import PopVideoJob, PopVideoRequest, _default_plan_from_idea

INDEP = 'She dumps the feed, yanks the wall plug, and the overseer still holds power.'
PASS_REVIEW = {
    'score': 8, 'verdict': 'ready for camera',
    'viewer_retell': INDEP,
}


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


class TestBlocker1HeadlineCaptionInfra(unittest.TestCase):
    def test_original_2_2s_headline_repro_passes_when_caption(self):
        """Exact shape of karaoke line_card / fallback after pace (~2.2s headline)."""
        v = mark_code_caption({
            'kind': 'gfx', 'g': 'headline',
            'p': {'kicker': 'DUMP', 'text': 'Dump the feed', 'sub': 'watch this'},
        }, 'line_card')
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 4.0},
            {
                't0': 4.0, 't1': 6.2,  # 2.2s — the original failing repro
                'v': v,
                'src': ('gfx', 'headline', {
                    'kicker': 'DUMP', 'text': 'Dump the feed',
                    'gfx_provenance': 'line_card',
                }),
                'line': 0, 'redrawn': 'scene missing/rejected',
            },
            {
                't0': 6.2, 't1': 11.7,  # 5.5s endcard
                'v': mark_code_caption({'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'endcard'),
                'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
            },
        ]
        self.assertEqual(classify_gfx(timeline[1], 'headline'), 'infra')
        rep = lint_timeline_graphics(timeline)
        self.assertTrue(rep.ok, rep.summary)
        assert_graphics_and_sing(timeline)

    def test_bare_narrative_headline_2_2s_still_fails(self):
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 4.0},
            {
                't0': 4.0, 't1': 6.2,
                'src': ('gfx', 'headline', {'kicker': 'STORY', 'text': 'WE ASKED GPT-6'}),
                'g': 'headline', 'primary_story': True, 'black_void': True,
            },
        ]
        with self.assertRaises(JobFailure) as cm:
            assert_graphics_and_sing(timeline)
        self.assertEqual(cm.exception.kind, FailureKind.GFX)

    def test_popvideojob_end_to_end_headline_fallback_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            clips = _clips(td, sids)
            tl = [
                {'scene_id': 's01_setup', 'src': clips['s01_setup'], 't0': 0, 't1': 2},
                {'scene_id': 's02_perf', 'src': clips['s02_perf'], 't0': 2, 't1': 4},
                {'scene_id': 's03_action', 'src': clips['s03_action'], 't0': 4, 't1': 6},
                {'scene_id': 's04_twist', 'src': clips['s04_twist'], 't0': 6, 't1': 8},
                {'scene_id': 's05_payoff', 'src': clips['s05_payoff'], 't0': 8, 't1': 10},
                # Fallback headline >1.5s (code-built line_card provenance)
                {
                    't0': 10, 't1': 12.2,
                    'src': ('gfx', 'headline', {
                        'text': 'Dump the feed', 'gfx_provenance': 'line_card',
                    }),
                    'v': mark_code_caption(
                        {'kind': 'gfx', 'g': 'headline', 'p': {'text': 'Dump the feed'}},
                        'line_card',
                    ),
                    'redrawn': 'match check: no clip',
                },
                {
                    't0': 12.2, 't1': 17.7,
                    'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
                    'v': mark_code_caption({'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'endcard'),
                },
            ]
            req = PopVideoRequest(
                job_id='headline_fb', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review=PASS_REVIEW, timeline_shots=tl,
            )
            self.assertTrue(res.ok, res.error)


class TestBlocker2KaraokePlannerDryRun(unittest.TestCase):
    def test_legacy_incomplete_plan_fails_without_autofake(self):
        legacy = {
            'planner': 'opus',
            'scenes': [
                {'id': 's1', 'prompt': '[LEAD] yanks the wall plug', 'motion': 'yank'},
                {'id': 's2', 'prompt': '[LEAD] lights stay on', 'motion': 'hold'},
            ],
            'lines': [{'i': 0, 'shows': 'yank', 'fact': '', 'v': [{'kind': 'scene', 'id': 's1'}]}],
            'intro': [], 'breaks': [], 'outro': [],
            'story_text': [{'from_line': 0, 'to_line': 0, 'kicker': 'MAIN', 'text': 'x'}],
            'credit': 'x',
            'design': {
                'palette': 'a', 'type': 'b', 'lyric_style': 'c', 'lyric_pos': 'd',
                'transition': 'e', 'grade': 'f', 'texture': 'g', 'why': 'old',
            },
        }
        with self.assertRaises(ValueError) as cm:
            normalize_karaoke_plan(legacy, invent_edges=False)
        msg = str(cm.exception).lower()
        self.assertTrue(any(k in msg for k in ('viewer_retell', 'payoff', 'world_before', 'requires_next')))
        self.assertIn('do not auto-fake', msg)  # explicit refusal, not silent invent

    def test_representative_opus_plan_normalize_and_dry_run(self):
        raw = representative_opus_plan()
        P = normalize_karaoke_plan(raw, invent_edges=False)
        # Planner headline pools are NOT auto-tagged as caption infra
        self.assertNotEqual(P['intro'][0].get('gfx_provenance'), 'line_card')
        self.assertFalse(P['intro'][0].get('infra'))
        gated = apply_coherence_gates(
            P, song_idea='Dump the feed and watch this instead',
            storyboard_review=PASS_REVIEW, require_storyboard=True,
        )
        self.assertTrue(gated['reports']['ok'])
        self.assertEqual(gated['plan'].get('performance_mode'), 'mouths_closed')

        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            sids = [s['id'] for s in P['scenes']]
            clips = _clips(td, sids)

            def planner(req):
                return normalize_karaoke_plan(representative_opus_plan(), invent_edges=False)

            req = PopVideoRequest(
                job_id='karaoke_opus', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            # Include >1.5s caption headline + endcard like post-edit karaoke
            tl = [
                {'scene_id': sid, 'src': clips[sid], 't0': i * 2.0, 't1': (i + 1) * 2.0}
                for i, sid in enumerate(sids)
            ]
            t_end = len(sids) * 2.0
            tl.append({
                't0': t_end, 't1': t_end + 2.2,
                'src': ('gfx', 'headline', {'text': 'Dump', 'gfx_provenance': 'line_card'}),
                'v': mark_code_caption(
                    {'kind': 'gfx', 'g': 'headline', 'p': {'text': 'Dump'}}, 'line_card',
                ),
            })
            tl.append({
                't0': t_end + 2.2, 't1': t_end + 7.7,
                'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
                'v': mark_code_caption({'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'endcard'),
            })
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips,
                storyboard_review=PASS_REVIEW, timeline_shots=tl,
            )
            self.assertTrue(res.ok, res.error)

    def test_normalize_refuses_invent_edges(self):
        with self.assertRaises(ValueError):
            normalize_karaoke_plan(representative_opus_plan(), invent_edges=True)


class TestReviewAndAccentTightening(unittest.TestCase):
    def test_scoreless_harmless_verdict_aborts(self):
        reason = storyboard_must_abort({'verdict': 'harmless looks fine'})
        self.assertIsNotNone(reason)
        self.assertIn('score', reason.lower())
        with self.assertRaises(JobFailure) as cm:
            assert_storyboard_review({}, {'verdict': 'ship it'})
        self.assertEqual(cm.exception.kind, FailureKind.STORYBOARD)

    def test_default_planner_does_not_fabricate_independent_label(self):
        req = PopVideoRequest(
            job_id='x', image_path='/dev/null',
            song_idea='Dump the feed and watch this instead',
        )
        plan = _default_plan_from_idea(req)
        self.assertFalse(plan['viewer_retell'].lower().startswith('an independent viewer'))
        # Without independent review retell, narrative gate fails
        plan.pop('storyboard_review', None)
        with self.assertRaises(JobFailure) as cm:
            assert_narrative_qa(plan)
        self.assertIn('independent', cm.exception.message.lower())

    def test_keyword_overlap_alone_not_enough_for_independent_retell(self):
        plan = _default_plan_from_idea(PopVideoRequest(
            job_id='x', image_path='/dev/null',
            song_idea='Dump the feed and watch this instead',
        ))
        plan['storyboard_review'] = {
            'score': 8, 'verdict': 'ready',
            # No action/consequence verbs and no scene-action word overlap
            'viewer_retell': 'Purple balloons drift above a quiet courtyard fountain.',
        }
        with self.assertRaises(JobFailure) as cm:
            assert_narrative_qa(plan)
        blob = cm.exception.message.lower()
        self.assertTrue(any(k in blob for k in (
            'substantive', 'independent', 'retell', 'consequence', 'align',
        )))

    def test_required_accents_coverage_not_vacuous(self):
        plan = _default_plan_from_idea(PopVideoRequest(
            job_id='x', image_path='/dev/null',
            song_idea='Dump the feed and watch this instead',
        ))
        plan['storyboard_review'] = PASS_REVIEW
        plan['required_accents'] = ['hook', 'drop']
        plan['creative_contract']['required_accents'] = ['hook', 'drop']
        # Only hook covered by default planner
        with self.assertRaises(JobFailure) as cm:
            assert_narrative_qa(plan)
        self.assertIn('accent', cm.exception.message.lower())


if __name__ == '__main__':
    unittest.main()
