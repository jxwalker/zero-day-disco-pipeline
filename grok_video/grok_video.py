"""Grok-clip music video for a suno-daily day folder. See README.md.
usage: grok_video.py DAY_DIR [--style mascot|cine-real] [--look auto|pop-video|edm|rock|punk|standard] [--clips 14]
                     [--skip-gen] [--clips-from DIR]
                     [--out FILE] [--work DIR] [--plan-only] [--parallel 4] [--whisper-model medium] [--seed S]
                     [--min-clips K] [--gen-budget G] [--allow-instrumental] [--no-chat-copy]
exit codes: 0 ok, 2 bad input, 3 generation failed / too few clips, 4 lyric timing failed, 5 output failed verification,
            6 song looks instrumental (stopped before generating), 7 Grok CLI not signed in"""
import argparse, os, shutil, subprocess, sys, threading, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_gv as G
import plan_gen, assemble, captions, looks

PY = os.environ.get('PY', '/home/box/venvs/align/bin/python')
DEMUCS = os.environ.get('DEMUCS', '/home/box/venvs/align/bin/demucs')


def fresh(out, *inputs):
    return os.path.exists(out) and os.path.getsize(out) > 0 and all(os.path.getmtime(out) >= os.path.getmtime(i)
                                                                      for i in inputs if os.path.exists(i))


def vocal_metrics(stem, music):
    """Level of the demucs vocal stem vs the backing stem, and how much of the song has audible vocals."""
    import numpy as np, soundfile as sf
    def rd(f):
        y, sr = sf.read(f, dtype='float32')
        return (y.mean(1) if y.ndim > 1 else y), sr
    v, sr = rd(stem); m, _ = rd(music)
    db = lambda x: float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9))
    w = int(sr * 0.5)
    win = np.array([db(v[i:i + w]) for i in range(0, max(len(v) - w, 1), w)])
    vd, md = db(v), db(m)
    return {'vocal_db': round(vd, 1), 'music_db': round(md, 1), 'rel_db': round(vd - md, 1),
            'active_frac': round(float((win > -35).mean()), 3), 'seconds': round(len(v) / sr, 1)}


def stem_says_vocals(vm):
    """True = clearly sung vocals (generation may start at once); False = low vocal stem, so wait for whisper to decide.
    Calibrated on 2026-10-07: the vocal take measured -2.3 dB vs the backing with voice in 92% of half-second windows;
    the instrumental take's demucs bleed measured -14.3 dB and 30%."""
    return vm['rel_db'] > -8 and vm['active_frac'] >= 0.5


def stem_is_low(vm):
    """Clearly instrumental-looking stem (the 7 Oct instrumental: -14.3 dB, 30 %). Between this and stem_says_vocals the
    stem is ambiguous and never stops a run on its own."""
    return vm['rel_db'] <= -10 or vm['active_frac'] < 0.4


def lyric_timings(day, work, model, on_stem=None):
    """Word timings for lyrics.txt. Reuses <day>/work/timings.json from the karaoke pipeline if it is up to date,
    otherwise runs that pipeline's alignment steps (demucs vocals -> faster-whisper reference -> sung-line choice ->
    stable-ts forced alignment -> whisper-checked repair) read-only, against a shadow copy of the day folder."""
    audio, lyr = G.audio_path(day), os.path.join(day, 'lyrics.txt')
    aw = os.path.join(work, 'align'); os.makedirs(aw, exist_ok=True)
    out = os.path.join(aw, 'timings.json')
    ext = os.path.join(day, 'work', 'timings.json')
    if fresh(ext, audio, lyr):
        shutil.copyfile(ext, out)
        for f in ('sync_report.json', 'timings.tsv', 'fw_words.json'):
            if os.path.exists(os.path.join(day, 'work', f)):
                shutil.copyfile(os.path.join(day, 'work', f), os.path.join(aw, f))
        G.log(f"timings: reused {ext}")
        on_stem and on_stem(None)
        return out
    vcf = os.path.join(aw, 'vocal_check.json')
    if fresh(out, audio, lyr):
        G.log("timings: cached")
        on_stem and on_stem(G.load_json(vcf) if fresh(vcf, audio) else None)
        return out
    shadow = os.path.join(work, 'day_shadow'); os.makedirs(shadow, exist_ok=True)
    for f in ('audio.mp3', 'lyrics.txt', 'tags.json', 'stories.md', 'title.txt', 'song_url.txt'):
        src, dst = (audio if f == 'audio.mp3' else os.path.join(day, f)), os.path.join(shadow, f)
        if os.path.lexists(dst):
            os.remove(dst)
        if os.path.exists(src):
            shutil.copyfile(src, dst)     # copies, so nothing can ever write back into the day folder
    lib = G.LIB
    logf = open(os.path.join(aw, 'align_pipeline.log'), 'a')
    run = lambda cmd: subprocess.run(cmd, check=True, stdout=logf, stderr=subprocess.STDOUT)
    t0 = time.time()
    run([PY, f'{lib}/prepare.py', shadow, aw])
    stem = os.path.join(aw, 'sep', 'htdemucs', 'audio', 'vocals.wav')
    if not fresh(stem, audio):
        run([DEMUCS, '-n', 'htdemucs', '--two-stems', 'vocals', '-o', os.path.join(aw, 'sep'), os.path.join(shadow, 'audio.mp3')])
    G.log(f"timings: demucs done ({time.time()-t0:.0f}s)")
    vm = None
    try:
        vm = vocal_metrics(stem, stem.replace('vocals.wav', 'no_vocals.wav'))
        vm['stem_vocals'] = stem_says_vocals(vm)
        G.save_json(vm, vcf)
        G.log(f"vocal stem: {vm['vocal_db']} dB vs backing {vm['music_db']} dB ({vm['rel_db']:+} dB), voice in "
              f"{vm['active_frac']*100:.0f}% of the song -> {'vocals' if vm['stem_vocals'] else 'LOW (instrumental?)'}")
    except Exception as e:
        G.log(f"vocal stem check failed: {e!r}")
    on_stem and on_stem(vm)
    if not fresh(os.path.join(aw, 'fw_words.json'), audio):
        run([PY, f'{lib}/transcribe.py', stem, os.path.join(shadow, 'audio.mp3'), os.path.join(aw, 'fw_words.json'), model])
    G.log(f"timings: whisper done ({time.time()-t0:.0f}s)")
    run([PY, f'{lib}/choose_script.py', aw, os.path.join(shadow, 'audio.mp3'), os.path.join(shadow, 'tags.json')])
    run([PY, f'{lib}/align.py', stem, os.path.join(aw, 'lyrics_sung.txt'), os.path.join(aw, 'align.json'), model])
    run([PY, f'{lib}/timings.py', aw, str(G.duration(audio))])
    shutil.rmtree(os.path.join(aw, 'sep'), ignore_errors=True)
    G.log(f"timings: done in {time.time()-t0:.0f}s")
    return out


def grok_auth_ok():
    """`grok models` must report a signed-in session. If it does not, run one cheap headless prompt (which makes the CLI
    refresh its OAuth token) and check again. Never prints or reads tokens."""
    def check():
        try:
            r = subprocess.run([G.GROK, 'models'], capture_output=True, text=True, timeout=60)
            return r.returncode == 0 and 'logged in' in r.stdout.lower(), (r.stdout + r.stderr)[-200:]
        except Exception as e:
            return False, repr(e)
    ok, msg = check()
    if ok:
        return True, 'ok', msg
    G.log(f"auth: `grok models` says not signed in ({msg.strip()[:120]!r}); trying a refresh via a cheap prompt")
    try:
        r = subprocess.run([G.GROK, '-p', 'ok', '--max-turns', '1', '--output-format', 'json', '--disallowed-tools',
                            'web_search,web_fetch,Agent,image_gen,image_edit,image_to_video,reference_to_video,run_terminal_command'],
                           capture_output=True, text=True, timeout=180, cwd='/tmp')
        prompt_ok = r.returncode == 0
    except Exception as e:
        prompt_ok = False
    ok, msg2 = check()
    if ok:
        G.log("auth: refreshed, signed in")
        return True, 'refreshed', msg2
    if prompt_ok:
        G.log("auth: WARNING `grok models` still not signed in, but the headless prompt worked; continuing")
        return True, 'prompt_ok_models_not', msg2
    return False, 'failed', msg2


def verify(out, audio, L, meta, frames_dir):
    os.makedirs(frames_dir, exist_ok=True)
    j = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', out],
                                  capture_output=True, text=True, check=True).stdout)
    v = [s for s in j['streams'] if s['codec_type'] == 'video'][0]
    a = [s for s in j['streams'] if s['codec_type'] == 'audio']
    dur, adur = float(j['format']['duration']), G.duration(audio)
    head = open(out, 'rb').read(200000)
    checks = {
        'resolution_1080x1920': (v['width'], v['height']) == (1080, 1920),
        'h264_high_yuv420p': v['codec_name'] == 'h264' and v.get('pix_fmt') == 'yuv420p',
        'aac_audio': bool(a) and a[0]['codec_name'] == 'aac',
        'duration_matches_song': abs(dur - adur) <= 0.15,
        'faststart': head.find(b'moov') != -1 and (head.find(b'mdat') == -1 or head.find(b'moov') < head.find(b'mdat')),
        'size_under_512MB': os.path.getsize(out) < 512 * 1024 * 1024,
    }
    shots = [('title', 1.5)]
    seen = set()
    for ln in L:
        k = (ln['kind'], ln['section_occ'])
        if ln['kind'] in ('verse', 'chorus', 'bridge') and k not in seen and len(shots) < 8:
            seen.add(k); shots.append((f"{ln['section'].lower().replace(' ', '')}{ln['section_occ']}_l{ln['line_no']}",
                                       (ln['words'][0][1] + ln['words'][-1][2]) / 2))
    shots.append(('end', dur - 1.0))
    for name, t in shots:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f"{t:.2f}", '-i', out, '-frames:v', '1', '-q:v', '3',
                        os.path.join(frames_dir, f"{t:06.2f}_{name}.jpg")])
    return {'ok': all(checks.values()), 'checks': checks, 'duration': dur, 'audio_duration': adur,
            'fps': v.get('avg_frame_rate'), 'bitrate': j['format'].get('bit_rate'), 'size_bytes': os.path.getsize(out),
            'frames': sorted(os.listdir(frames_dir))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day')
    ap.add_argument('--clips', type=int, default=14)
    ap.add_argument('--skip-gen', action='store_true')
    ap.add_argument('--audio', default=None, help='use this audio file instead of <day>/audio.mp3 (special folders)')
    ap.add_argument('--clips-from')
    ap.add_argument('--out')
    ap.add_argument('--work')
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--parallel', type=int, default=4)
    ap.add_argument('--whisper-model', default='medium')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--min-clips', type=int)
    ap.add_argument('--no-chat-copy', action='store_true')
    ap.add_argument('--gen-budget', type=int, help='max generations this run (default clips+3)')
    ap.add_argument('--look', choices=looks.CHOICES, default='auto',
                    help='auto (default) picks from style.txt: big-room/EDM -> edm, rock -> rock, pop-punk -> punk, pop -> pop-video')
    ap.add_argument('--allow-instrumental', action='store_true', help='do not stop when the song looks instrumental')
    ap.add_argument('--style', choices=['cine-real', 'slopcore', 'mascot'], default='slopcore',
                    help='slopcore (default since 10 Oct 2026): cine-real v2 (people-driven scenes with a recurring cast, '
                         'one gritty look, mostly video clips, sparse type, 2-3 Pip cameos; writes video_cine_real_v2.mp4); '
                         'cine-real: the v1 photoreal lyric-literal video with a Pip cameo (first fallback); '
                         'mascot: the earlier Pip-clip video (last fallback)')
    ap.add_argument('--real-look', default='auto', help='cine-real look: auto, candy-pop, neon-accent, vhs, 35mm, xerox')
    ap.add_argument('--real-images', type=int, default=None, help='cine-real: distinct pictures to generate (stills); '
                    'default 110 (slopcore: 95 scenes)')
    ap.add_argument('--real-heroes', type=int, default=None, help='cine-real: hero reference_to_video clips (max); '
                    'default 25 (slopcore: 45 clips + 3 Pip, about 6%% of the weekly pool)')
    ap.add_argument('--real-clip-sec', type=int, default=None, choices=[2, 3, 4, 5],
                    help='cine-real: hero clip length in seconds; default 4 (slopcore: 3)')
    ap.add_argument('--real-planner', choices=['opus', 'script', 'slop'], default='opus',
                    help='slopcore planner: opus (default since 10 Oct: Claude Opus writes the script + storyboard, '
                         'falls back to script then the template; writes work_cine_real_v4 / video_cine_real_v4.mp4), '
                         'script (Grok line-by-line script + critic, *_v3) or slop (the v2 cast/mood planner, *_v2)')
    ap.add_argument('--real-reuse-plan', action='store_true',
                    help='slopcore: re-edit from an existing plan even if it came from an older planner version '
                    '(use with --skip-gen to re-render from existing media at zero cost)')
    ap.add_argument('--real-max-pct', type=float, default=7.5, help='cine-real: stop spending after about this %% of the weekly pool')
    ap.add_argument('--real-time-limit', '--real-deadline-min', dest='real_time_limit', type=float, default=None,
                    help='cine-real: hard time limit in minutes from the start. Generation stops 9 min before it (the edit '
                         'uses what exists), the render is aborted at it, then the mascot fallback runs')
    ap.add_argument('--hard-stop-min', type=float, default=58,
                    help='cine-real: the mascot fallback is killed if the whole run passes this many minutes (exit 3)')
    ap.add_argument('--no-fallback', action='store_true', help='cine-real: exit 3 instead of falling back to the mascot style')
    ap.add_argument('--no-cine-fallback', action='store_true',
                    help='slopcore: skip the cine-real step of the fallback chain (go straight to mascot)')
    ap.add_argument('--fallback-args', default='', help='cine-real: extra arguments for the mascot fallback run (tests)')
    a = ap.parse_args()
    v2 = a.style == 'slopcore'
    for k, d1, d2 in (('real_images', 110, 95), ('real_heroes', 25, 45), ('real_clip_sec', 4, 3), ('real_time_limit', 32, 34)):
        if getattr(a, k) is None:
            setattr(a, k, d2 if v2 else d1)
    real = a.style in ('cine-real', 'slopcore')
    t_start = time.time()
    day = os.path.abspath(a.day)
    vtag = {'opus': '_v4', 'script': '_v3', 'slop': '_v2'}[a.real_planner] if v2 else ''
    work = os.path.abspath(a.work or os.path.join(day, f'work_cine_real{vtag}' if real else 'work_grok'))
    out = os.path.abspath(a.out or os.path.join(day, f'video_cine_real{vtag}.mp4' if real else 'video_grok.mp4'))
    os.makedirs(work, exist_ok=True); os.makedirs(os.path.dirname(out), exist_ok=True)
    status = {'day': day, 'out': out, 'work': work, 'started': time.strftime('%Y-%m-%d %H:%M:%S %Z'),
              'ok': False, 'warnings': [], 'style': a.style}
    sp = os.path.join(work, 'status.json')

    def fail(msg, code):
        status.update(error=msg, exit_code=code, elapsed_s=round(time.time() - t_start))
        G.save_json(status, sp)
        G.log(f"FAILED: {msg}")
        print(f"GROK_VIDEO_STATUS=failed code={code} reason={msg!r}", flush=True)
        sys.exit(code)
    if a.audio:
        G.AUDIO_OVERRIDE = os.path.abspath(a.audio)
        status['audio'] = G.AUDIO_OVERRIDE
    for f in ('audio.mp3', 'lyrics.txt'):
        if not os.path.exists(G.audio_path(day) if f == 'audio.mp3' else os.path.join(day, f)):
            fail(f'missing {f}', 2)
    audio = G.audio_path(day)
    dur = G.duration(audio)
    tags = G.load_json(os.path.join(day, 'tags.json'), {}) or {}
    seed = a.seed if a.seed is not None else int(os.path.basename(day).replace('-', '')[:8] or 0) if os.path.basename(day)[:8].replace('-', '').isdigit() else 7
    look, why = looks.resolve(day, a.look)
    status['look'] = look; status['look_reason'] = why
    G.log(f"day {day} | song {dur:.1f}s | genre {G.genre_of(day)[0] or G.genre_of(day)[1][:40]} | out {out}")
    G.log(f"look: {look} ({why})")

    # ---- lyric timings run in the background (demucs -> vocal check -> whisper -> alignment)
    tres = {}
    stem_evt = threading.Event()

    def on_stem(vm):
        tres['vocal'] = vm
        stem_evt.set()

    def tjob():
        try:
            tres['path'] = lyric_timings(day, work, a.whisper_model, on_stem)
        except Exception as e:
            tres['err'] = repr(e)
        stem_evt.set()
    th = threading.Thread(target=tjob, daemon=True)
    if not a.plan_only or real:
        th.start()

    def sync_cov():
        sync = G.load_json(os.path.join(work, 'align', 'sync_report.json'), {}) or {}
        f = sync.get('final') or {}
        return f.get('coverage_pct'), f.get('whisper_words'), sync

    def vocal_gate():
        """Stop BEFORE any clip generation if the song looks instrumental: a low demucs vocal stem AND whisper hearing
        under 25% of the lyric words. A clearly loud vocal stem passes straight away (whisper keeps running in the
        background); a low or unknown stem waits for whisper to decide."""
        stem_evt.wait()
        if 'err' in tres:
            fail('lyric timing failed: ' + tres['err'], 4)
        vm = tres.get('vocal')
        status['vocal_check'] = vm
        if vm and vm.get('stem_vocals'):
            return
        G.log("vocal check: stem " + (('LOW' if stem_is_low(vm) else 'not clearly vocal') if vm else 'not measured') + "; waiting for whisper before spending allowance")
        th.join()
        if 'err' in tres:
            fail('lyric timing failed: ' + tres['err'], 4)
        cov, heard, _ = sync_cov()
        status['vocal_check'] = dict(vm or {}, whisper_coverage_pct=cov, whisper_words=heard)
        # whisper alone is noisy on heavily produced vocals (a 2026-10-05 re-run heard 12 % where the routine's run heard
        # 69 %), so stopping needs BOTH a low stem and low coverage; with no stem measurement only a near-zero coverage stops
        instrumental = cov is not None and ((vm and stem_is_low(vm) and cov < 25) or (not vm and cov < 5))
        if cov is not None and cov < 25 and not instrumental:
            w = f"vocal check ambiguous (stem {('%+.1f dB' % vm['rel_db']) if vm else 'not measured'}, whisper {cov}%): continuing"
            status['warnings'].append(w); G.log('WARNING: ' + w)
        if instrumental:
            msg = (f"song looks INSTRUMENTAL: whisper heard only {cov}% of the lyric words ({heard} words)"
                   + (f", vocal stem {vm['rel_db']:+} dB vs backing, voice in {vm['active_frac']*100:.0f}% of the song" if vm else '')
                   + " - remake the song in Suno with vocals")
            if a.allow_instrumental:
                status['warnings'].append(msg); G.log('WARNING (allowed): ' + msg)
            else:
                fail(msg, 6)
        elif cov is not None and cov >= 25:
            G.log(f"vocal check: whisper coverage {cov}% - vocals confirmed")

    if real:
        return run_real(a, day, work, out, audio, dur, look, status, sp, fail, vocal_gate, th, tres, t_start)

    # ---- shots + clips
    clips_dir = os.path.abspath(a.clips_from) if a.clips_from else os.path.join(work, 'clips')
    if a.skip_gen:
        plan = G.load_json(os.path.join(clips_dir, 'shots.json')) or G.load_json(os.path.join(work, 'shots.json'))
        files = sorted(f for f in os.listdir(clips_dir) if f.endswith('.mp4')) if os.path.isdir(clips_dir) else []
        if not plan:
            plan = {'shots': [{'id': i + 1, 'story': 0, 'section': 'chorus', 'file': f, 'setting': f} for i, f in enumerate(files)]}
        shots = [s for s in plan['shots'] if os.path.exists(os.path.join(clips_dir, s['file']))]
        G.log(f"skip-gen: {len(shots)} clips from {clips_dir}")
        status['generation'] = {'skipped': True, 'clips_from': clips_dir, 'clips': len(shots)}
    else:
        ok, how, msg = grok_auth_ok()
        status['auth'] = how
        if not ok:
            fail('grok CLI not signed in (after one refresh attempt) - run `grok login --device-auth`: ' + msg.strip()[-150:], 7)
        if how != 'ok':
            status['warnings'].append(f'auth needed a refresh ({how})')
        if not os.path.exists(G.PIP_REF):
            fail(f'missing Pip reference {G.PIP_REF}', 2)
        t0 = time.time()
        plan = G.load_json(os.path.join(work, 'shots.json'))
        stale = (not plan or len(plan.get('shots', [])) != a.clips or plan.get('look', 'standard') != look
                 or (look in looks.LOOKS and plan.get('planner') != plan_gen.PLANNER_VERSION))
        if stale:
            # caption timings, if already there (re-runs, or the karaoke pipeline's), let the planner see when each
            # line is sung; otherwise the slots follow section order (the editor still uses the real timings)
            Lp = None
            for tp in (os.path.join(day, 'work', 'timings.json'), os.path.join(work, 'align', 'timings.json')):
                if fresh(tp, audio, os.path.join(day, 'lyrics.txt')):
                    Lp = G.load_json(tp); break
            plan = plan_gen.plan_shots(day, work, a.clips, look, L=Lp)
        status['plan'] = {'secs': round(time.time() - t0), 'fallback': bool(plan.get('fallback')), 'shots': len(plan['shots'])}
        if a.plan_only:
            G.log(f"plan written: {os.path.join(work, 'shots.json')}")
            status.update(ok=True, plan_only=True, elapsed_s=round(time.time() - t_start)); G.save_json(status, sp)
            return
        vocal_gate()
        gen = plan_gen.Generator(work, plan['shots'], max_parallel=a.parallel, budget=a.gen_budget if a.gen_budget is not None else a.clips + 3, look=look)
        gs = gen.run()
        status['generation'] = gs
        shots = [s for s in plan['shots'] if os.path.exists(os.path.join(clips_dir, s['file']))]
        G.log(f"generation: {gs['ok']}/{gs['wanted']} clips, {gs['generations_used']} generations, {gs['wall_s']}s"
              + (f" | ABORT: {gs['abort']}" if gs['abort'] else ''))
    min_clips = a.min_clips or max(4, (a.clips + 1) // 2 if not a.skip_gen else 1)
    if len(shots) < min_clips:
        fail(f"only {len(shots)} usable clips (need {min_clips})"
             + (f"; {status['generation'].get('abort')}" if isinstance(status.get('generation'), dict) and status['generation'].get('abort') else ''), 3)

    # ---- timings
    if a.skip_gen:
        vocal_gate()
    th.join()
    if 'err' in tres:
        fail('lyric timing failed: ' + tres['err'], 4)
    L = G.load_json(tres['path'])
    sync = G.load_json(os.path.join(work, 'align', 'sync_report.json'), {}) or {}
    status['captions'] = {'lines': len(L), 'sync_final': sync.get('final'), 'sync_raw': sync.get('raw_stable_ts')}
    cov = (sync.get('final') or {}).get('coverage_pct')
    if cov is not None and cov < 25:
        w = (f"caption sync unverifiable: whisper matched only {cov}% of lyric words "
             f"({(sync.get('final') or {}).get('whisper_words')} words heard) - instrumental or unclear vocals?")
        status['warnings'].append(w); G.log('WARNING: ' + w)

    # ---- assemble
    t0 = time.time()
    beats = assemble.beat_grid(audio, G.read(os.path.join(day, 'style.txt')), work)
    ass = os.path.join(work, 'captions.ass')
    lay = captions.build(day, L, dur, ass, handle=tags.get('handle', '@jxwalker'), look=look)
    cuts = assemble.cut_list(beats, L, dur, lay['end_start'], seed, look=look)
    cplan = assemble.assign(cuts, shots, L, tags.get('story_tags') or [], clips_dir, work, seed, look=look, beats=beats,
                           end_start=lay['end_start'])
    G.save_json({'beats': {k: v for k, v in beats.items() if k != 'beats'}, 'layout': lay, 'cuts': cplan},
                os.path.join(work, 'edit.json'))
    lens = [c['t1'] - c['t0'] for c in cplan]
    if look in looks.LOOKS:
        fxc = {}
        for c in cplan:
            for f in c.get('fx', []) + (['slowmo'] if c.get('speed', 1) < 1 else ['speedup'] if c.get('speed', 1) > 1 else []):
                fxc[f] = fxc.get(f, 0) + 1
        status['edit_fx'] = fxc
        G.log(f"edit fx ({look}): {fxc}")
    G.log(f"edit: {len(cplan)} cuts (median {sorted(lens)[len(lens)//2]:.2f}s, min {min(lens):.2f}, max {max(lens):.2f}), "
          f"tempo {beats['tempo']:.1f} ({beats['source']}), {len(set(c['clip'] for c in cplan))} clips used")
    seg_list, nframes = assemble.render_segments(cplan, clips_dir, os.path.join(work, 'segments'), threads=4)
    G.log(f"segments rendered ({nframes} frames, {time.time()-t0:.0f}s); final render...")
    assemble.final_render(seg_list, audio, ass, out, dur)
    shutil.rmtree(os.path.join(work, 'segments'), ignore_errors=True)
    G.log(f"render done ({time.time()-t0:.0f}s)")
    vr = verify(out, audio, L, lay, os.path.join(work, 'frames'))
    if not a.no_chat_copy:
        chat = os.path.splitext(out)[0] + '_chat.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-vf', 'scale=720:1280:flags=lanczos', '-c:v', 'libx264',
                        '-preset', 'medium', '-crf', '25', '-maxrate', '2500k', '-bufsize', '5000k', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', chat], check=False)
        if os.path.exists(chat):
            status['chat_copy'] = {'path': chat, 'size_bytes': os.path.getsize(chat)}
            G.log(f"chat copy: {chat} ({os.path.getsize(chat)/1e6:.0f} MB)")
    if vr['ok']:
        messenger_copy(out, status)
    status.update(verify=vr, cuts=len(cplan), clips_used=len(set(c['clip'] for c in cplan)),
                  ok=vr['ok'], elapsed_s=round(time.time() - t_start))
    G.save_json(status, sp)
    G.log(f"verify: {'OK' if vr['ok'] else 'FAILED'} {vr['checks']}")
    status['exit_code'] = 0 if vr['ok'] else 5
    G.save_json(status, sp)
    print(f"GROK_VIDEO_STATUS={'ok' if vr['ok'] else 'verify_failed'} code={status['exit_code']} look={look} out={out} "
          f"chat={status.get('chat_copy', {}).get('path', '-')} elapsed={status['elapsed_s']}s"
          + (f" warnings={len(status['warnings'])}: {' | '.join(status['warnings'])}" if status['warnings'] else ''))
    sys.exit(0 if vr['ok'] else 5)


MESSENGER_MAX_BYTES = 18_000_000          # the owner's Messenger rejected 23 MB (9 Oct 22:19)


def messenger_copy(out, status):
    """Special (non-daily) folders: a Messenger copy under MESSENGER_MAX_BYTES (18 MB): H.264 720x1280, AAC 128k, faststart, two-pass at a
    bitrate fitted to the duration (about 1.1 Mbps video for 2:30). Never for the daily runs."""
    import tone as T
    day = status.get('day') or os.path.dirname(out)
    if T.is_daily(day):
        return None
    dst = os.path.splitext(out)[0] + '_messenger.mp4'
    dur = G.duration(out)
    budget = 0.95 * MESSENGER_MAX_BYTES * 8 / max(dur, 1)          # bits/s for the whole file, 5 % container headroom
    vk = int((budget - 128_000) / 1000)
    passlog = os.path.join(os.path.dirname(dst), '.messenger_2pass')
    for attempt in range(3):
        base = ['ffmpeg', '-v', 'error', '-y', '-i', out, '-vf', 'scale=720:1280:flags=lanczos', '-c:v', 'libx264',
                '-preset', 'slow', '-b:v', f'{vk}k', '-maxrate', f'{int(vk * 1.5)}k', '-bufsize', f'{vk * 2}k',
                '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-passlogfile', passlog]
        subprocess.run(base + ['-pass', '1', '-an', '-f', 'mp4', '/dev/null'], check=False)
        subprocess.run(base + ['-pass', '2', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', dst], check=False)
        for f in os.listdir(os.path.dirname(dst)):
            if f.startswith('.messenger_2pass'):
                os.remove(os.path.join(os.path.dirname(dst), f))
        if os.path.exists(dst) and os.path.getsize(dst) < MESSENGER_MAX_BYTES:
            status['messenger_copy'] = {'path': dst, 'size_bytes': os.path.getsize(dst), 'video_kbps': vk}
            G.log(f"messenger copy: {dst} ({os.path.getsize(dst)/1e6:.1f} MB, video {vk} kbps)")
            return dst
        vk = int(vk * 0.88)
    status['warnings'].append('messenger copy failed or over the size cap')
    return None


def finish(a, out, audio, L, status, sp, t_start, look, extra='', exit=True):
    vr = verify(out, audio, L, {}, os.path.join(status['work'], 'frames'))
    if not a.no_chat_copy:
        chat = os.path.splitext(out)[0] + '_chat.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-vf', 'scale=720:1280:flags=lanczos', '-c:v', 'libx264',
                        '-preset', 'medium', '-crf', '25', '-maxrate', '2200k', '-bufsize', '4400k', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', chat], check=False)
        if os.path.exists(chat):
            status['chat_copy'] = {'path': chat, 'size_bytes': os.path.getsize(chat)}
            G.log(f"chat copy: {chat} ({os.path.getsize(chat)/1e6:.0f} MB)")
    if vr['ok']:
        messenger_copy(out, status)
        if status.get('messenger_copy'):
            extra = f" messenger={status['messenger_copy']['path']}" + extra
    status.update(verify=vr, ok=vr['ok'], elapsed_s=round(time.time() - t_start))
    status['exit_code'] = 0 if vr['ok'] else 5
    G.save_json(status, sp)
    G.log(f"verify: {'OK' if vr['ok'] else 'FAILED'} {vr['checks']}")
    if exit or vr['ok']:
        print(f"GROK_VIDEO_STATUS={'ok' if vr['ok'] else 'verify_failed'} code={status['exit_code']} style={status.get('style')} "
              f"look={look} out={out} chat={status.get('chat_copy', {}).get('path', '-')} elapsed={status['elapsed_s']}s"
              + extra + (f" warnings={len(status['warnings'])}: {' | '.join(status['warnings'])}" if status['warnings'] else ''),
              flush=True)
    if not exit:
        return status['exit_code']
    sys.exit(0 if vr['ok'] else 5)


CINE_FALLBACK_MIN_LEFT = 26   # slopcore -> cine-real fallback only with >= 26 min before the hard stop (else mascot)


def run_real(a, day, work, out, audio, dur, look, status, sp, fail, vocal_gate, th, tres, t_start):
    """cine-real style. The plan and the media are made from lyrics.txt while demucs/whisper/alignment are still
    running (they take about 10 min); the real cut timeline is built from the word timings afterwards and mapped onto
    the pictures, then rendered.
    Any cine-real failure after the safety gates (planner, generation, edit, render, verification, a crash) falls back
    to the mascot style, so the routine always gets a video; the status line then says fallback=mascot."""
    import traceback
    import cine_real
    if not a.skip_gen:
        ok, how, msg = grok_auth_ok()
        status['auth'] = how
        if not ok:
            fail('grok CLI not signed in (after one refresh attempt) - run `grok login --device-auth`: ' + msg.strip()[-150:], 7)
        if how != 'ok':
            status['warnings'].append(f'auth needed a refresh ({how})')
    if not os.path.exists(G.PIP_REF):
        fail(f'missing Pip reference {G.PIP_REF}', 2)
    a.deadline = t_start + a.real_time_limit * 60
    why = None
    try:
        # the plan needs only lyrics.txt: plan while demucs runs; generate while whisper/alignment run
        box = {}

        def prep_job():
            try:
                box['P'] = cine_real.prepare(day, work, look, a, status)
            except Exception as e:
                box['err'] = e
                box['tb'] = traceback.format_exc()
        pt = threading.Thread(target=prep_job, daemon=True)
        pt.start()
        vocal_gate()                     # exit 6 (or 4) before anything is generated
        pt.join()
        if 'err' in box:
            G.log('cine-real prepare error:\n' + box['tb'][-1500:])
            raise box['err']
        P = box['P']
        if a.plan_only:
            status.update(ok=True, plan_only=True, elapsed_s=round(time.time() - t_start)); G.save_json(status, sp)
            G.log(f"plan written: {os.path.join(work, 'real_plan.json')}")
            print(f"GROK_VIDEO_STATUS=ok code=0 style={a.style} plan_only=1 work={work}")
            return
        cine_real.generate_media(P, a, status)
        if th.is_alive():
            G.log("waiting for the lyric timings")
        th.join()
        if 'err' in tres:
            fail('lyric timing failed: ' + tres['err'], 4)
        L = G.load_json(tres['path'])
        sync = G.load_json(os.path.join(work, 'align', 'sync_report.json'), {}) or {}
        status['captions'] = {'lines': len(L), 'sync_final': sync.get('final')}
        G.log(f"timings ready at {time.time() - t_start:.0f}s")
        ok, info = cine_real.edit_and_render(P, L, out, a, status)
        m = status.get('real_metrics', {})
        code = finish(a, out, audio, L, status, sp, t_start, status.get('real_look', look),
                      extra=(f" tone={status.get('tone', 'edgy')} planner={(status.get('plan') or {}).get('planner')}"
                             f" shots={m.get('shots')} avg_shot={m.get('avg_shot_s')}s motion={m.get('motion_share')} "
                             f"clips={m.get('clips_used')} pip_shots={m.get('pip_shots')}") if 'motion_share' in m else
                            f" shots={m.get('shots')} avg_shot={m.get('avg_shot_s')}s pictures={m.get('distinct_pictures')}",
                      exit=False)
        if code == 0:
            sys.exit(0)
        why = 'output failed verification'
    except SystemExit:
        raise
    except Exception as e:
        why = f'{type(e).__name__}: {e}'
        G.log('cine-real error:\n' + traceback.format_exc()[-1500:])
    # ---- fallback: the mascot style (its own work dir and output name unless --fallback-args says otherwise)
    # a half-written cine-real file from this run must not be mistaken for a finished video
    try:
        if os.path.exists(out) and os.path.getmtime(out) >= t_start:
            os.replace(out, os.path.splitext(out)[0] + '.failed.mp4')
            G.log(f"moved the unfinished output aside: {os.path.splitext(out)[0] + '.failed.mp4'}")
    except OSError:
        pass
    status.update(ok=False, error=why, exit_code=3, fallback='mascot', elapsed_s=round(time.time() - t_start))
    G.save_json(status, sp)
    if a.no_fallback:
        G.log(f"FAILED: cine-real: {why} (no fallback requested)")
        print(f"GROK_VIDEO_STATUS=failed code=3 style={a.style} reason={why!r}", flush=True)
        sys.exit(3)
    errkey = 'slopcore_error' if a.style == 'slopcore' else 'cine_real_error'
    import shlex
    import signal
    fb_extra = shlex.split(a.fallback_args or '')
    if th.is_alive():                    # failed early: let the timings finish rather than redo them
        G.log("fallback: waiting for this run's lyric timings")
        th.join(timeout=max(0, t_start + 20 * 60 - time.time()))

    def hand_over_timings(fb_work):
        # hand the finished lyric timings + vocal check to the next run so it doesn't redo demucs/whisper (about 4 min)
        try:
            src_a, dst_a = os.path.join(work, 'align'), os.path.join(fb_work, 'align')
            if fresh(os.path.join(src_a, 'timings.json'), audio, os.path.join(day, 'lyrics.txt')) and \
                    not fresh(os.path.join(dst_a, 'timings.json'), audio, os.path.join(day, 'lyrics.txt')):
                os.makedirs(dst_a, exist_ok=True)
                for f in ('timings.json', 'vocal_check.json', 'sync_report.json', 'timings.tsv', 'fw_words.json'):
                    if os.path.exists(os.path.join(src_a, f)):
                        shutil.copy2(os.path.join(src_a, f), os.path.join(dst_a, f))
                G.log(f"fallback: reused this run's lyric timings in {dst_a}")
        except Exception as e:
            G.log(f"fallback: could not hand over timings ({e!r}); the next run will redo them")

    def run_child(cmd, left, env):
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, start_new_session=True, env=env)
        try:
            so, _ = pr.communicate(timeout=left)
            return pr.returncode, so, False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pr.pid, signal.SIGKILL)       # the child run and everything it started
            except OSError:
                pass
            so, _ = pr.communicate()
            return 3, so, True

    def base_cmd(style):
        cmd = [sys.executable, os.path.abspath(__file__), day, '--style', style, '--look', a.look,
               '--whisper-model', a.whisper_model, '--parallel', str(a.parallel), '--clips', str(a.clips)]
        for flag in ('no_chat_copy', 'allow_instrumental'):
            if getattr(a, flag):
                cmd.append('--' + flag.replace('_', '-'))
        if a.seed is not None:
            cmd += ['--seed', str(a.seed)]
        return cmd

    # ---- step 1 of the slopcore chain: the cine-real (v1) style, when there is time for it AND its own mascot fallback
    left = t_start + a.hard_stop_min * 60 - time.time()
    if a.style == 'slopcore' and not a.no_cine_fallback and left >= CINE_FALLBACK_MIN_LEFT * 60:
        spent = (status.get('generation') or {}).get('spent_pct')
        pct = max(2.5, a.real_max_pct - spent) if isinstance(spent, (int, float)) else max(2.5, a.real_max_pct / 2)
        left_min = left / 60
        cmd = base_cmd('cine-real') + ['--hard-stop-min', f'{left_min - 0.5:.1f}',
                                       '--real-time-limit', f'{min(32.0, left_min - 11):.1f}',
                                       '--real-max-pct', f'{pct:.1f}']
        if a.fallback_args:
            cmd += ['--fallback-args', a.fallback_args]
        hand_over_timings(os.path.join(day, 'work_cine_real'))
        G.log(f"slopcore FAILED ({why}); falling back to cine-real (v1) with {left_min:.0f} min left before the hard stop "
              f"(its own mascot fallback included), spend cap {pct:.1f}%")
        status.update(fallback='cine-real'); G.save_json(status, sp)
        cenv = dict(os.environ)
        if not os.environ.get('CINE_REAL_FAIL_ALL'):    # tests: a forced failure hits the first style only
            cenv.pop('CINE_REAL_FAIL', None)
        rc, so, killed = run_child(cmd, left, cenv)
        sys.stdout.write((so or '') if not killed else '')
        last = [l for l in (so or '').splitlines() if l.startswith('GROK_VIDEO_STATUS=')]
        status['fallback_result'] = {'exit_code': rc, 'status_line': last[-1] if last else None, 'killed': killed}
        G.save_json(status, sp)
        if killed or not last:
            print(f"GROK_VIDEO_STATUS=failed code=3 fallback=1 style=cine-real {errkey}={why!r} "
                  f"reason='fallback passed the {a.hard_stop_min:g} min hard stop'", flush=True)
            sys.exit(3)
        print(f"GROK_VIDEO_STATUS={'ok' if rc == 0 else 'failed'} code={rc} fallback=1 {errkey}={why!r} "
              + last[-1].split(' ', 2)[-1], flush=True)
        sys.exit(rc)

    # ---- last step: the mascot style (its own work dir and output name unless --fallback-args says otherwise)
    G.log(f"{a.style} FAILED ({why}); falling back to the mascot style so a video still gets made")
    cmd = base_cmd('mascot') + fb_extra
    fb_work = fb_extra[fb_extra.index('--work') + 1] if '--work' in fb_extra else os.path.join(day, 'work_grok')
    hand_over_timings(fb_work)
    left = max(8 * 60, t_start + a.hard_stop_min * 60 - time.time())
    G.log(f"fallback: mascot run, at most {left / 60:.0f} min")
    # time is short now: the mascot planner gets 5 min in total, or none if the cine-real planner just failed twice
    # (the API is then slow or down, and the mascot template plan is fine)
    fenv = dict(os.environ, GROK_VIDEO_PLAN_MAX_S='0' if (status.get('plan') or {}).get('fallback') else '300')
    status.update(fallback='mascot')
    rc, so, killed = run_child(cmd, left, fenv)
    sys.stdout.write(so or '')
    if killed:
        status['fallback_result'] = {'exit_code': 3, 'status_line': None, 'error': 'mascot fallback over the hard stop'}
        G.save_json(status, sp)
        print(f"GROK_VIDEO_STATUS=failed code=3 style=mascot fallback=1 {errkey}={why!r} "
              f"reason='mascot fallback passed the {a.hard_stop_min:g} min hard stop'", flush=True)
        sys.exit(3)
    last = [l for l in (so or '').splitlines() if l.startswith('GROK_VIDEO_STATUS=')]
    status['fallback_result'] = {'exit_code': rc, 'status_line': last[-1] if last else None}
    G.save_json(status, sp)
    print(f"GROK_VIDEO_STATUS={'ok' if rc == 0 else 'failed'} code={rc} style=mascot fallback=1 "
          f"{errkey}={why!r} " + (last[-1].split(' ', 2)[-1] if last else ''), flush=True)
    sys.exit(rc)


if __name__ == '__main__':
    main()
