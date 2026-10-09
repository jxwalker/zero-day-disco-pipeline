"""Forced alignment of the known (sung) lyric lines to the demucs vocal stem with stable-ts.
usage: align.py VOCALS.wav LYRICS_SUNG.txt OUT.json [model]"""
import sys, json
import stable_whisper
vocals, lyr, out = sys.argv[1:4]
name = sys.argv[4] if len(sys.argv) > 4 else 'medium'
m = stable_whisper.load_faster_whisper(name, device='cpu', compute_type='int8', cpu_threads=8)
text = open(lyr).read()
r = m.align(vocals, text, language='en', original_split=True)
r.save_as_json(out)
for s in r.segments:
    print(f"{s.start:7.2f}-{s.end:7.2f} {s.text}", flush=True)
