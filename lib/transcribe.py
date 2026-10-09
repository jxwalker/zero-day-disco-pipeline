"""Free (unconstrained, no lyric prompt) faster-whisper word timings used as the independent sync reference.
Whisper misses a lot of sung words on long windows, so several chunked passes are run (vocal stem with
12 s and 20 s windows, full mix with 12 s windows); each chunk only contributes words whose start falls
in its central region, obvious hallucination loops are dropped, and the passes are merged (common.merge_passes:
largest pass first, later passes only fill words not already present within 1 s).
usage: transcribe.py VOCALS.wav MIX_AUDIO OUT.json [model]"""
import sys, json, subprocess, re
import numpy as np
from faster_whisper import WhisperModel

vocals, mix, out = sys.argv[1:4]
name = sys.argv[4] if len(sys.argv) > 4 else 'medium'
SR = 16000


def load(p):
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', p, '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768


def nrm(w):
    return re.sub(r'[^a-z0-9]', '', w.lower())


m = WhisperModel(name, device='cpu', compute_type='int8', cpu_threads=8)
audio = {'vocals': load(vocals), 'mix': load(mix)}
dur = len(audio['vocals']) / SR


def run_pass(src, L, HOP):
    a = audio[src]
    starts = [0.0]
    while starts[-1] + L < dur:
        starts.append(starts[-1] + HOP)
    words = []
    for ci, st in enumerate(starts):
        seg = a[int(st * SR):int((st + L) * SR)]
        lo = st + (L - HOP) / 2 if ci > 0 else 0.0
        hi = st + (L + HOP) / 2 if ci < len(starts) - 1 else 1e9
        ss, _ = m.transcribe(seg, language='en', word_timestamps=True, beam_size=5, vad_filter=False,
                             condition_on_previous_text=False, no_speech_threshold=0.95, log_prob_threshold=-5,
                             temperature=0)
        got = []
        for s in ss:
            for w in s.words:
                ws = w.start + st
                if lo <= ws < hi and nrm(w.word):
                    got.append({'s': round(ws, 3), 'e': round(w.end + st, 3), 'w': w.word.strip(),
                                'p': round(w.probability, 3), 'pass': f'{src}{int(L)}'})
        words += got
    # collapse hallucination loops (3+ identical tokens in a row -> first one), drop zero-length stacked words
    clean = []
    for i, w in enumerate(words):
        n = nrm(w['w'])
        run = 1; j = i - 1
        while j >= 0 and nrm(words[j]['w']) == n:
            run += 1; j -= 1
        k = i + 1
        while k < len(words) and nrm(words[k]['w']) == n:
            run += 1; k += 1
        if run >= 3 and j >= 0 and nrm(words[j]['w']) == n:   # keep only the first word of a 3+ loop
            continue
        if clean and abs(clean[-1]['s'] - w['s']) < 0.01 and abs(clean[-1]['e'] - w['e']) < 0.01:
            continue
        clean.append(w)
    print(f"pass {src} L={L}: {len(words)} words, {len(clean)} after loop filter", flush=True)
    return clean


passes = [('vocals', 12.0, 6.0), ('vocals', 20.0, 10.0), ('mix', 12.0, 6.0)]
per = {}
for p in passes:
    w = run_pass(*p)
    per[f'{p[0]}{int(p[1])}'] = w
sys.path.insert(0, __import__('os').path.dirname(__file__))
import common
merged = common.merge_passes(per)
json.dump({'model': name, 'duration': dur, 'words': merged, 'passes': per}, open(out, 'w'), indent=1)
print('merged words', len(merged))
print(' '.join(f"{w['w']}@{w['s']:.1f}" for w in merged))
