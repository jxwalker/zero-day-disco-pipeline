#!/usr/bin/env python3
"""PR #2 release blockers at 512a967 — independent retell via real review(); provenance-only captions.

1) storyboard.review() must request/persist viewer_retell; E2E through review() with stubbed
   runner into PopVideoJob / karaoke dry-run — no hand-editing the returned review.
2) 6s black planner headline must FAIL; only code-built line_card / endcard provenance passes.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'grok_video'))

import storyboard as SB
from pipeline.failures import FailureKind, JobFailure
from pipeline.graphics_lint import assert_graphics_and_sing, classify_gfx, lint_timeline_graphics
from pipeline.karaoke_plan import mark_code_caption, normalize_karaoke_plan, representative_opus_plan
from pipeline.plan_gates import apply_coherence_gates
from pipeline.service import PopVideoJob, PopVideoRequest


INDEP_RETELL = (
    'She dumps the feed, yanks the wall plug, and the overseer still holds power.'
)


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


def _stub_runner(retell=INDEP_RETELL, score=8, verdict='ready for camera', **extra):
    """Stub for storyboard.review runner — returns reviewer JSON only (no hand-edit after)."""
    def run(pf, od, schema, timeout, tools='', effort='high'):
        # Prompt must ask for independent viewer_retell
        prompt = open(pf).read()
        assert 'viewer_retell' in prompt.lower() or 'INDEPENDENT SOUND-OFF RETELL' in prompt
        assert 'CONSEQUENCE' in prompt or 'consequence' in prompt.lower()
        result = {
            'score': score,
            'verdict': verdict,
            'viewer_retell': retell,
            'scene_fixes': [],
            'line_scene': [],
        }
        result.update(extra)
        return result, {'secs': 0.01}
    return run


def _day_stub(td, plan):
    day = os.path.join(td, 'day')
    os.makedirs(day, exist_ok=True)
    with open(os.path.join(day, 'direction.txt'), 'w') as fh:
        fh.write('LEAD: test lead\nOne continuous mini-story.\n')
    with open(os.path.join(day, 'title.txt'), 'w') as fh:
        fh.write('Dump the feed\n')
    with open(os.path.join(day, 'lyrics.txt'), 'w') as fh:
        fh.write('[Verse]\nDump the feed\nYank the plug\n')
    lines = ['Dump the feed', 'Yank the plug']
    work = os.path.join(td, 'work')
    os.makedirs(work, exist_ok=True)
    return day, work, lines


class TestIndependentRetellViaReview(unittest.TestCase):
    def test_review_persists_viewer_retell_without_hand_edit(self):
        with tempfile.TemporaryDirectory() as td:
            plan = normalize_karaoke_plan(representative_opus_plan())
            day, work, lines = _day_stub(td, plan)
            raw = SB.review(plan, day, work, lines, runner=_stub_runner())
            # Do not hand-edit raw or plan['storyboard_review']
            self.assertIsNotNone(raw)
            self.assertEqual(raw.get('viewer_retell'), INDEP_RETELL)
            persisted = plan['storyboard_review']
            self.assertEqual(persisted.get('viewer_retell'), INDEP_RETELL)
            self.assertEqual(persisted.get('score'), 8)
            # Schema required field present on disk
            disk = json.load(open(os.path.join(work, 'opus', 'storyboard_review.json')))
            self.assertEqual(disk.get('viewer_retell'), INDEP_RETELL)

    def test_missing_retell_from_review_fails_before_generation(self):
        with tempfile.TemporaryDirectory() as td:
            plan = normalize_karaoke_plan(representative_opus_plan())
            day, work, lines = _day_stub(td, plan)
            SB.review(plan, day, work, lines, runner=_stub_runner(retell=''))
            # Persisted empty retell — gates must abort
            with self.assertRaises(JobFailure) as cm:
                apply_coherence_gates(
                    plan, song_idea='Dump the feed and watch this instead',
                    storyboard_review=plan['storyboard_review'],
                )
            self.assertIn('independent', cm.exception.message.lower())

    def test_popvideojob_e2e_through_review_no_hand_edit(self):
        with tempfile.TemporaryDirectory() as td:
            plan = normalize_karaoke_plan(representative_opus_plan())
            day, work, lines = _day_stub(td, plan)
            SB.review(plan, day, work, lines, runner=_stub_runner())
            review = plan['storyboard_review']  # as persisted by review() only
            self.assertIn('viewer_retell', review)
            img = _img(td)
            sids = [s['id'] for s in plan['scenes']]
            clips = _clips(td, sids)

            def planner(req):
                # Fresh plan without storyboard_review — job uses review() output
                return normalize_karaoke_plan(representative_opus_plan())

            req = PopVideoRequest(
                job_id='via_review', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'job'),
            )
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips,
                storyboard_review=review,  # unmodified persistence from review()
            )
            self.assertTrue(res.ok, res.error)

    def test_karaoke_dry_run_through_review_no_hand_edit(self):
        with tempfile.TemporaryDirectory() as td:
            plan = normalize_karaoke_plan(representative_opus_plan())
            day, work, lines = _day_stub(td, plan)
            SB.review(plan, day, work, lines, runner=_stub_runner())
            gated = apply_coherence_gates(
                plan, song_idea='Dump the feed and watch this instead',
                storyboard_review=plan['storyboard_review'],
            )
            self.assertTrue(gated['reports']['ok'])

    def test_score_verdict_only_still_fails_independent_retell(self):
        """Default unattended path without review() retell must not pass."""
        with tempfile.TemporaryDirectory() as td:
            img = _img(td)
            sids = ['s01_setup', 's02_perf', 's03_action', 's04_twist', 's05_payoff']
            clips = _clips(td, sids)
            req = PopVideoRequest(
                job_id='no_retell', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'work'),
            )
            res = PopVideoJob(req).run(
                dry_run=True, available_clips=clips,
                storyboard_review={'score': 8, 'verdict': 'ready'},  # no viewer_retell
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_kind, FailureKind.NARRATIVE.value)
            self.assertIn('independent', (res.error or '').lower())


class TestCaptionProvenanceOnly(unittest.TestCase):
    def test_6s_black_narrative_headline_bypass_fails(self):
        """Verified bypass: planner/tag 'infra' on 6s black headline must NOT exempt."""
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 4.0},
            {
                't0': 4.0, 't1': 10.0,  # 6s
                'g': 'headline',
                'src': ('gfx', 'headline', {
                    'kicker': 'FEED', 'text': 'THE FEED OWNS YOU',
                    # Planner-controlled tags that previously bypassed the gate:
                    'infra': True, 'karaoke_caption': True, 'line_card': True,
                }),
                'v': {
                    'kind': 'gfx', 'g': 'headline',
                    'p': {'text': 'THE FEED OWNS YOU'},
                    'infra': True, 'karaoke_caption': True,
                },
                'black_void': True, 'primary_story': True,
            },
        ]
        self.assertEqual(classify_gfx(timeline[1], 'headline'), 'narrative_slide')
        rep = lint_timeline_graphics(timeline)
        self.assertFalse(rep.ok, rep.summary)
        self.assertGreater(rep.gfx_share, 0.0)
        with self.assertRaises(JobFailure) as cm:
            assert_graphics_and_sing(timeline)
        self.assertEqual(cm.exception.kind, FailureKind.GFX)

    def test_2_2s_line_card_provenance_passes(self):
        card = mark_code_caption(
            {'kind': 'gfx', 'g': 'headline',
             'p': {'kicker': 'DUMP', 'text': 'Dump the feed'}},
            'line_card',
        )
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 4.0},
            {
                't0': 4.0, 't1': 6.2,
                'v': card,
                'src': ('gfx', 'headline', {
                    'kicker': 'DUMP', 'text': 'Dump the feed',
                    'gfx_provenance': 'line_card',
                }),
                'redrawn': 'scene missing/rejected',
            },
        ]
        self.assertEqual(classify_gfx(timeline[1], 'headline'), 'infra')
        assert_graphics_and_sing(timeline)

    def test_5_5s_endcard_provenance_passes(self):
        end = mark_code_caption({'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'endcard')
        timeline = [
            {'src': ('clip', 's01'), 't0': 0.0, 't1': 8.0},
            {
                't0': 8.0, 't1': 13.5,
                'v': end,
                'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
            },
        ]
        assert_graphics_and_sing(timeline)

    def test_popvideojob_public_path_caption_vs_narrative(self):
        with tempfile.TemporaryDirectory() as td:
            plan = normalize_karaoke_plan(representative_opus_plan())
            day, work, lines = _day_stub(td, plan)
            SB.review(plan, day, work, lines, runner=_stub_runner())
            review = plan['storyboard_review']
            img = _img(td)
            sids = [s['id'] for s in plan['scenes']]
            clips = _clips(td, sids)

            def planner(req):
                return normalize_karaoke_plan(representative_opus_plan())

            # Positive: line_card 2.2s + endcard 5.5s
            t0 = 0.0
            tl_ok = []
            for sid in sids:
                tl_ok.append({'scene_id': sid, 'src': clips[sid], 't0': t0, 't1': t0 + 2.0})
                t0 += 2.0
            tl_ok.append({
                't0': t0, 't1': t0 + 2.2,
                'src': ('gfx', 'headline', {
                    'text': 'Dump the feed', 'gfx_provenance': 'line_card',
                }),
                'v': mark_code_caption(
                    {'kind': 'gfx', 'g': 'headline', 'p': {'text': 'Dump the feed'}},
                    'line_card',
                ),
            })
            tl_ok.append({
                't0': t0 + 2.2, 't1': t0 + 7.7,
                'src': ('gfx', 'endcard', {'gfx_provenance': 'endcard'}),
                'v': mark_code_caption({'kind': 'gfx', 'g': 'endcard', 'p': {}}, 'endcard'),
            })
            req = PopVideoRequest(
                job_id='cap_ok', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'ok'),
            )
            res = PopVideoJob(req, planner=planner).run(
                dry_run=True, available_clips=clips,
                storyboard_review=review, timeline_shots=tl_ok,
            )
            self.assertTrue(res.ok, res.error)

            # Negative: 6s black narrative headline with forged infra tags
            tl_bad = [
                {'scene_id': sid, 'src': clips[sid], 't0': i * 2.0, 't1': (i + 1) * 2.0}
                for i, sid in enumerate(sids)
            ]
            te = len(sids) * 2.0
            tl_bad.append({
                't0': te, 't1': te + 6.0,
                'src': ('gfx', 'headline', {
                    'text': 'THE FEED OWNS YOU',
                    'infra': True, 'karaoke_caption': True,
                }),
                'v': {
                    'kind': 'gfx', 'g': 'headline',
                    'p': {'text': 'THE FEED OWNS YOU'},
                    'infra': True, 'karaoke_caption': True,
                },
                'black_void': True, 'primary_story': True,
            })
            req2 = PopVideoRequest(
                job_id='cap_bad', image_path=img,
                song_idea='Dump the feed and watch this instead',
                work_dir=os.path.join(td, 'bad'),
            )
            res2 = PopVideoJob(req2, planner=planner).run(
                dry_run=True, available_clips=clips,
                storyboard_review=review, timeline_shots=tl_bad,
            )
            self.assertFalse(res2.ok)
            self.assertEqual(res2.failure_kind, FailureKind.GFX.value)


class TestReviewSchemaRequiresRetell(unittest.TestCase):
    def test_rev_schema_requires_viewer_retell(self):
        self.assertIn('viewer_retell', SB.REV_SCHEMA.get('required', []))


if __name__ == '__main__':
    unittest.main()
