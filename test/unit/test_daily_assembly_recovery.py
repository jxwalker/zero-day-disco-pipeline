"""Labelled local media assembly + --from-timeline recovery helpers.

No paid APIs. Uses ffmpeg synthetic colour bars as clearly labelled test clips.
Does not prove footage is watchable — only that the recovery path assembles bytes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
GV = os.path.join(HERE, 'grok_video')
sys.path.insert(0, GV)

from pipeline.karaoke_recover import (  # noqa: E402
    RecoveryError,
    assert_safe_recovery_out,
    hydrate_shots,
    load_preserved_timeline,
    remux_bg_ass_audio,
    timeline_record,
)


def _have_ffmpeg() -> bool:
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _labelled_clip(path: str, label: str, seconds: float = 2.0, color: str = 'blue') -> str:
    """Write a short labelled colour-bar clip (filename + drawtext = LABEL_*)."""
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'color=c={color}:s=1080x1920:d={seconds}:r=30',
        '-f', 'lavfi', '-i', f'sine=f=440:d={seconds}',
        '-vf', f"drawtext=text='{label}':fontsize=64:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', path,
    ], check=True)
    return path


def _sine_mp3(path: str, seconds: float = 6.0) -> str:
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'sine=f=220:d={seconds}',
        '-c:a', 'libmp3lame', '-q:a', '4', path,
    ], check=True)
    return path


class TestSafeRecoveryOut(unittest.TestCase):
    def test_refuses_protected_masters(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ('video_karaoke.mp4', 'video_karaoke.v10f.mp4'):
                with self.assertRaises(RecoveryError):
                    assert_safe_recovery_out(os.path.join(td, name))

    def test_allows_separate_recovery_path(self):
        with tempfile.TemporaryDirectory() as td:
            assert_safe_recovery_out(os.path.join(td, 'recovery', 'video_karaoke.v10f_rebuild.mp4'))


class TestTimelineRecordRoundTrip(unittest.TestCase):
    def test_full_src_survives_record(self):
        shots = [{
            't0': 0.0, 't1': 2.0,
            'src': ('clip', '/tmp/LABEL_CLIP_A.mp4', 0.5, {'zoom': 1.0}),
            'line': 0, 'v': {'kind': 'scene', 'id': 'v10_01'},
        }]
        doc = timeline_record(shots, plan_fp='fp1')
        self.assertTrue(doc['recoverable'])
        self.assertEqual(doc['shots'][0]['src'][2], 0.5)
        self.assertEqual(doc['shots'][0]['v']['id'], 'v10_01')


@unittest.skipUnless(_have_ffmpeg(), 'ffmpeg required')
class TestHydrateAndAssembleLabelled(unittest.TestCase):
    def test_hydrate_truncated_clip_and_render_concat(self):
        with tempfile.TemporaryDirectory() as td:
            gdir = os.path.join(td, 'grok'); os.makedirs(gdir)
            a = _labelled_clip(os.path.join(gdir, 'LABEL_CLIP_A.mp4'), 'LABEL_CLIP_A', 2.0, 'blue')
            b = _labelled_clip(os.path.join(gdir, 'LABEL_CLIP_B.mp4'), 'LABEL_CLIP_B', 2.0, 'green')
            # Truncated timeline (Watch Me–era shape: kind + path only)
            tl = {
                'shots': [
                    {'t0': 0.0, 't1': 1.5, 'src': ['clip', a], 'line': 0},
                    {'t0': 1.5, 't1': 3.0, 'src': ['clip', b], 'line': 1},
                    {'t0': 3.0, 't1': 4.0, 'src': ['gfx', 'endcard', {'title': 'LABEL_END', 'gfx_provenance': 'endcard'}], 'line': None},
                ]
            }
            shots, rep = hydrate_shots(tl, gdir=gdir, title='Label Test')
            self.assertTrue(rep['ok'])
            self.assertEqual(rep['clips'], 2)
            self.assertEqual(rep['truncated_src'], 2)  # clip offsets defaulted
            self.assertEqual(shots[0]['src'][0], 'clip')
            self.assertEqual(shots[0]['src'][2], 0.0)

            # Assembly proof with labelled clips only (no kgfx/fonts): trim to shot windows + concat.
            sd = os.path.join(td, 'seg'); os.makedirs(sd)
            segs = []
            for i, s in enumerate(shots):
                if s['src'][0] != 'clip':
                    continue
                outp = os.path.join(sd, f'{i:03d}.mp4')
                nfr = max(1, round((s['t1'] - s['t0']) * 30))
                subprocess.run([
                    'ffmpeg', '-v', 'error', '-y', '-ss', str(s['src'][2]), '-i', s['src'][1],
                    '-frames:v', str(nfr), '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', outp,
                ], check=True)
                segs.append(outp)
            self.assertEqual(len(segs), 2)
            for p in segs:
                self.assertGreater(os.path.getsize(p), 1000)
            lst = os.path.join(sd, 'list.txt')
            open(lst, 'w').write(''.join(f"file '{p}'\n" for p in segs))
            bg = os.path.join(td, 'bg.mp4')
            subprocess.run(
                ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', bg],
                check=True,
            )
            self.assertGreater(os.path.getsize(bg), 1000)
            # Remux with labelled audio (ASS omitted → simple mux)
            audio = _sine_mp3(os.path.join(td, 'audio.mp3'), 4.0)
            # Write a tiny ASS so remux_bg_ass_audio can run
            ass = os.path.join(td, 'lyrics.ass')
            open(ass, 'w').write(
                '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n'
                '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
                'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, '
                'Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
                'Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n'
                '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
                'Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,LABEL_LYRIC\n'
            )
            out = os.path.join(td, 'recovery', 'LABEL_RECOVERY.mp4')
            remux_bg_ass_audio(bg=bg, band=None, ass=ass, audio=audio, out=out, dur=3.0)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 1000)

    def test_load_preserved_timeline_requires_shots(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'timeline.json')
            json.dump({'shots': []}, open(p, 'w'))
            with self.assertRaises(RecoveryError):
                load_preserved_timeline(p)


if __name__ == '__main__':
    unittest.main()
