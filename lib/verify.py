"""Verify the rendered video against the spec and extract review frames.
usage: verify.py DAY_DIR WORK_DIR VIDEO AUDIO [FRAMES_DIR]"""
import sys, os, json, subprocess, re, shutil
sys.path.insert(0, os.path.dirname(__file__))
import common as C

day, work, video, audio = sys.argv[1:5]
p = C.ffprobe_json(video)
v = next(s for s in p['streams'] if s['codec_type'] == 'video')
a = next(s for s in p['streams'] if s['codec_type'] == 'audio')
adur = C.audio_duration(audio)
vdur = float(p['format']['duration'])
fr = v['r_frame_rate'].split('/'); fps = float(fr[0]) / float(fr[1])
# faststart: moov atom must precede mdat
with open(video, 'rb') as f:
    order = []; off = 0; size = os.path.getsize(video)
    while off < size and len(order) < 12:
        f.seek(off); hdr = f.read(16)
        n = int.from_bytes(hdr[:4], 'big'); typ = hdr[4:8].decode('latin1')
        if n == 1: n = int.from_bytes(hdr[8:16], 'big')
        order.append(typ); off += n if n else size
faststart = 'moov' in order and 'mdat' in order and order.index('moov') < order.index('mdat')
checks = {
    'resolution 1080x1920': (v['width'], v['height']) == (1080, 1920),
    'fps 30': abs(fps - 30) < 0.01,
    'h264 High': v['codec_name'] == 'h264' and v.get('profile') == 'High',
    'yuv420p': v['pix_fmt'] == 'yuv420p',
    'aac ~192k': a['codec_name'] == 'aac' and 170000 <= int(a.get('bit_rate', 0)) <= 200000,
    'faststart': faststart,
    'full duration (+-0.1s)': abs(vdur - adur) <= 0.1,
}
info = {'video': video, 'size_bytes': os.path.getsize(video), 'size_mb': round(os.path.getsize(video) / 1e6, 1),
        'duration_s': vdur, 'audio_source_duration_s': adur, 'video_stream_duration_s': float(v.get('duration', 0)),
        'width': v['width'], 'height': v['height'], 'fps': fps, 'vcodec': v['codec_name'], 'profile': v.get('profile'),
        'pix_fmt': v['pix_fmt'], 'acodec': a['codec_name'], 'abitrate': int(a.get('bit_rate', 0)),
        'sample_rate': a.get('sample_rate'), 'top_level_atoms': order, 'checks': checks}
for k, ok in checks.items(): print(('PASS ' if ok else 'FAIL ') + k)
print(f"size {info['size_mb']} MB, duration {vdur:.3f}s (audio {adur:.3f}s)")

# ---- review frames
L = C.load_json(os.path.join(work, 'timings.json'))
lay = C.load_json(os.path.join(work, 'layout.json'))
def mid(ln, frac=0.6): return ln['start'] + frac * (ln['end'] - ln['start'])
blocks = []
for ln in L:
    if not blocks or blocks[-1][0]['block'] != ln['block']: blocks.append([])
    blocks[-1].append(ln)
kinds = lambda k: [b for b in blocks if b[0]['kind'] == k]
shots = [('01_title', min(1.8, lay['title_end'] / 2))]
verses, choruses, bridges = kinds('verse'), kinds('chorus') + kinds('postchorus'), kinds('bridge') or kinds('prechorus')
choruses.sort(key=lambda b: b[0]['start'])
if verses: shots.append(('02_verse1', mid(verses[0][min(2, len(verses[0]) - 1)])))
if choruses: shots.append(('03_chorus', mid(choruses[0][min(1, len(choruses[0]) - 1)])))
if len(verses) > 1: shots.append(('04_verse2', mid(verses[1][min(2, len(verses[1]) - 1)])))
if bridges: shots.append(('05_bridge', mid(bridges[0][min(1, len(bridges[0]) - 1)])))
# one frame inside every story-tag span not already covered
taken = [t for _, t in shots]
for s, e, t in lay['tag_spans']:
    if t[0] in ('', 'NOW SINGING ABOUT') and t[1] and not any(s <= x < e for x in taken):
        c = [ln for ln in L if s <= ln['start'] < e]
        x = mid(c[len(c) // 2]) if c else (s + e) / 2
        slug = re.sub(r'[^a-z0-9]+', '_', t[1].lower()).strip('_')[:24]
        shots.append((f'06_story_{slug}', x)); taken.append(x)
shots.append(('09_end', vdur - 1.2))
fd = sys.argv[5] if len(sys.argv) > 5 else os.path.join(day, 'frames'); shutil.rmtree(fd, ignore_errors=True); os.makedirs(fd)
for name, t in shots:
    out = os.path.join(fd, f'{name}.jpg')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', video, '-frames:v', '1', '-q:v', '2', out], check=True)
    print(f'frame {out} @ {t:.2f}s')
info['frames'] = {n: round(t, 2) for n, t in shots}
C.save_json(info, os.path.join(work, 'verify.json'))
sys.exit(0 if all(checks.values()) else 1)
