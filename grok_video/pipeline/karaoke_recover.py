"""Deterministic karaoke cut recovery from a preserved timeline (no generation).

Used by ``karaoke.py --from-timeline`` to rebuild an approved daily cut into a
*separate* output path. Does not invent story edges or call paid APIs.

Preserved ``timeline.json`` from older karaoke builds often truncates ``src`` to
``[kind, path_or_g]``. Hydration restores clip offsets (default 0) and rebuilds
missing gfx payloads from the plan + lyric line when needed. Bit-identical
rebuild of an old master is only guaranteed when the timeline retained full
``src`` tuples (and preferably an existing ``bg_*.mp4`` remux path).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Filenames we refuse to overwrite during recovery (approved masters / posted cuts).
PROTECTED_OUT_BASENAMES = frozenset({
    'video_karaoke.mp4',
    'video_karaoke.v10f.mp4',
    'video_karaoke_chat.mp4',
    'video_karaoke_16x9.mp4',
})


class RecoveryError(RuntimeError):
    """Preserved artifacts are insufficient for a safe rebuild."""


def assert_safe_recovery_out(out: str, *, force: bool = False) -> None:
    """Refuse clobbering approved masters unless explicitly forced."""
    out = os.path.abspath(out)
    base = os.path.basename(out)
    if base in PROTECTED_OUT_BASENAMES and not force:
        raise RecoveryError(
            f'refusing to overwrite protected master {base!r}; '
            f'pass a separate --out path (e.g. recovery/video_karaoke.v10f_rebuild.mp4) '
            f'or set GV_RECOVERY_OVERWRITE=1'
        )
    if os.path.exists(out) and not force:
        raise RecoveryError(
            f'recovery --out already exists: {out}; choose a new path or GV_RECOVERY_OVERWRITE=1'
        )


def load_preserved_timeline(path: str) -> dict:
    if not path or not os.path.exists(path):
        raise RecoveryError(f'missing preserved timeline: {path}')
    try:
        data = json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        raise RecoveryError(f'cannot read timeline {path}: {e}') from e
    shots = data.get('shots')
    if not isinstance(shots, list) or not shots:
        raise RecoveryError(f'timeline has no shots: {path}')
    return data


def find_timings(work: str) -> Optional[str]:
    """Locate preserved lyric timings without re-running demucs/whisper."""
    candidates = [
        os.path.join(work, 'kalign', 'timings.json'),
        os.path.join(work, 'align', 'timings.json'),
        os.path.join(work, 'timings.json'),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 8:
            return p
    return None


def find_plan(work: str) -> Optional[str]:
    """Prefer live plan.json; fall back to known bak names (Watch Me v10f)."""
    candidates = [
        os.path.join(work, 'plan.json'),
        os.path.join(work, 'plan.json.bak-v10f'),
        os.path.join(work, 'plan.json.bak'),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 8:
            return p
    return None


def timeline_record(shots: Sequence[dict], *, plan_fp: str = '',
                    story: Optional[list] = None, overlays: int = 0) -> dict:
    """Persist enough shot detail to re-render later (full ``src`` + ``v``)."""
    rows = []
    for s in shots:
        src = s.get('src')
        if isinstance(src, tuple):
            src = list(src)
        row = {
            't0': round(float(s['t0']), 3),
            't1': round(float(s['t1']), 3),
            'src': src,
            'line': s.get('line'),
            'redrawn': s.get('redrawn'),
        }
        if s.get('v') is not None:
            row['v'] = s['v']
        rows.append(row)
    return {
        'plan_fp': plan_fp or '',
        'shots': rows,
        'story': story or [],
        'overlays': overlays,
        'recoverable': True,
    }


def _resolve_clip_path(ref: Any, gdir: str) -> str:
    """Map timeline clip refs onto ``gdir`` (attachment-safe).

    Prefer basename under ``gdir`` so box-absolute paths in an attached
    timeline.json still resolve after staging clips into recovery/grok/.
    Absolute paths are accepted only when they already live under ``gdir``,
    or when ``GV_RECOVERY_ALLOW_ABS=1`` (local box reassembly of untouched work).
    """
    path = str(ref or '')
    gdir_abs = os.path.abspath(gdir)
    base = os.path.basename(path) if path else ''
    if base:
        cand = os.path.join(gdir_abs, base)
        if os.path.exists(cand):
            return cand
    # bare scene id → grok/<id>.mp4
    if path and not path.endswith(('.mp4', '.png', '.jpg', '.jpeg', '.webp')):
        cand = os.path.join(gdir_abs, f'{path}.mp4')
        if os.path.exists(cand):
            return cand
    if path and os.path.isabs(path) and os.path.exists(path):
        ap = os.path.abspath(path)
        if ap == gdir_abs or ap.startswith(gdir_abs + os.sep):
            return ap
        if os.environ.get('GV_RECOVERY_ALLOW_ABS', '0') == '1':
            return ap
        raise RecoveryError(
            f'clip path {path!r} is outside recovery grok dir {gdir_abs}; '
            f'stage the file as {os.path.join(gdir_abs, base)} or set GV_RECOVERY_ALLOW_ABS=1'
        )
    raise RecoveryError(f'clip not found for timeline src {ref!r} under {gdir}')


def remux_allowed() -> bool:
    """Stale ``bg_*.mp4`` must not be treated as v10f without an explicit opt-in."""
    return os.environ.get('GV_RECOVERY_REMUX', '0') == '1'


def hydrate_shots(
    tl: dict,
    *,
    gdir: str,
    plan: Optional[dict] = None,
    L: Optional[Sequence[dict]] = None,
    title: str = '',
    line_card_fn=None,
    gfx_src_fn=None,
) -> Tuple[List[dict], Dict[str, Any]]:
    """Turn a preserved timeline into render_seg-ready shots.

    Returns (shots, report) where report notes truncated/hydrated fields.
    ``line_card_fn`` / ``gfx_src_fn`` are injected by karaoke.py (no circular import).
    """
    report: Dict[str, Any] = {
        'n_shots': 0, 'clips': 0, 'gfx': 0, 'stills': 0,
        'truncated_src': 0, 'hydrated_gfx': 0, 'missing_clips': [],
        'ok': True, 'warnings': [],
    }
    pl = {ln.get('i'): ln for ln in (plan or {}).get('lines') or [] if isinstance(ln, dict)}
    out: List[dict] = []
    for i, raw in enumerate(tl.get('shots') or []):
        t0 = float(raw['t0']); t1 = float(raw['t1'])
        if t1 <= t0:
            raise RecoveryError(f'shot {i}: t1 ({t1}) <= t0 ({t0})')
        src = raw.get('src')
        if not isinstance(src, (list, tuple)) or not src:
            raise RecoveryError(f'shot {i}: missing src')
        kind = str(src[0])
        shot: Dict[str, Any] = {
            't0': t0, 't1': t1, 'line': raw.get('line'),
            'redrawn': raw.get('redrawn'),
        }
        if raw.get('v') is not None:
            shot['v'] = raw['v']

        if kind == 'clip':
            try:
                path = _resolve_clip_path(src[1], gdir)
            except RecoveryError as e:
                report['missing_clips'].append(str(e))
                report['ok'] = False
                continue
            if len(src) >= 3:
                off = float(src[2]) if src[2] is not None else 0.0
                opt = src[3] if len(src) > 3 and isinstance(src[3], dict) else {'zoom': 1.0}
            else:
                report['truncated_src'] += 1
                off = 0.0
                opt = {'zoom': 1.0}
            shot['src'] = ('clip', path, off, opt)
            report['clips'] += 1
        elif kind == 'still':
            path = str(src[1])
            if not os.path.isabs(path):
                path = os.path.join(gdir, os.path.basename(path))
            if not os.path.exists(path):
                report['missing_clips'].append(f'still missing: {src[1]}')
                report['ok'] = False
                continue
            shot['src'] = ('still', path, int(src[2]) if len(src) > 2 else 0)
            report['stills'] += 1
        elif kind == 'gfx':
            g = src[1]
            if len(src) >= 3 and isinstance(src[2], dict):
                meta = dict(src[2])
                shot['src'] = ('gfx', g, meta)
                if 'v' not in shot:
                    shot['v'] = {
                        'kind': 'gfx', 'g': g,
                        'p': {k: v for k, v in meta.items() if k != 'gfx_provenance'},
                        'gfx_provenance': meta.get('gfx_provenance'),
                    }
            elif shot.get('v') and gfx_src_fn is not None:
                shot['src'] = gfx_src_fn(shot['v'])
                report['hydrated_gfx'] += 1
            else:
                # Watch Me v10f: timeline gfx is truncated AND plan line inventory can disagree
                # (e.g. timeline terminal vs plan bignum). Never invent payloads from plan.
                report['truncated_src'] += 1
                allow = os.environ.get('GV_RECOVERY_HYDRATE_GFX', '0') == '1'
                if not allow:
                    raise RecoveryError(
                        f'shot {i}: truncated gfx {g!r} (no payload/v); refuse silent plan hydrate '
                        f'(timeline vs plan inventories may differ). Provide full src in timeline '
                        f'or set GV_RECOVERY_HYDRATE_GFX=1 knowing gfx will not match v10f.'
                    )
                if line_card_fn is None or gfx_src_fn is None:
                    raise RecoveryError(f'shot {i}: truncated gfx {g!r}; missing hydrate callables')
                li = shot.get('line')
                txt = title
                fact = ''
                if L is not None and li is not None and 0 <= int(li) < len(L):
                    txt = L[int(li)].get('text') or title
                if isinstance(li, int) and li in pl:
                    fact = (pl[li] or {}).get('fact') or ''
                v = line_card_fn(txt, fact, {}, provenance='recovery_hydrate')
                if g:
                    v = dict(v)
                    v['g'] = g
                shot['v'] = v
                shot['src'] = gfx_src_fn(v)
                report['hydrated_gfx'] += 1
                report['warnings'].append(
                    f'shot {i}: OPT-IN hydrated gfx {g!r} from line/plan — NOT faithful to v10f'
                )
            report['gfx'] += 1
        else:
            raise RecoveryError(f'shot {i}: unknown src kind {kind!r}')
        out.append(shot)

    report['n_shots'] = len(out)
    if report['missing_clips']:
        report['ok'] = False
    if not out:
        raise RecoveryError('no shots hydrated from timeline')
    return out, report


def remux_bg_ass_audio(
    *,
    bg: str,
    band: Optional[str],
    ass: str,
    audio: str,
    out: str,
    dur: float,
    fps: int = 30,
) -> str:
    """Fast remux path when a *provenanced* concat background already exists.

    Callers must set ``GV_RECOVERY_REMUX=1`` after confirming ``bg`` is the v10f
    (or other approved) concat — presence of ``bg_1080x1920.mp4`` alone is not proof.
    """
    import subprocess
    if not remux_allowed():
        raise RecoveryError(
            'refusing auto-remux of bg without provenance; set GV_RECOVERY_REMUX=1 '
            'only after confirming bg_1080x1920.mp4 is the approved cut concat'
        )
    if not (os.path.exists(bg) and os.path.exists(ass) and os.path.exists(audio)):
        raise RecoveryError('remux requires bg mp4 + lyrics ASS + audio.mp3')
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    tmp = out + '.part.mp4'
    if band and os.path.exists(band):
        fc = f"[0:v][1:v]overlay=0:0,ass='{ass}',scale=in_range=auto:out_range=tv,format=yuv420p[v]"
        cmd = [
            'ffmpeg', '-v', 'error', '-y', '-i', bg, '-i', band, '-i', audio,
            '-filter_complex', fc,
            '-map', '[v]', '-map', '2:a',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
            '-color_range', 'tv', '-profile:v', 'high', '-r', str(fps),
            '-c:a', 'aac', '-b:a', '192k', '-t', f'{dur:.3f}', '-movflags', '+faststart', tmp,
        ]
    else:
        fc = f"ass='{ass}',scale=in_range=auto:out_range=tv,format=yuv420p"
        cmd = [
            'ffmpeg', '-v', 'error', '-y', '-i', bg, '-i', audio,
            '-vf', fc,
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
            '-color_range', 'tv', '-profile:v', 'high', '-r', str(fps),
            '-c:a', 'aac', '-b:a', '192k', '-t', f'{dur:.3f}', '-movflags', '+faststart', tmp,
        ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, out)
    return out
