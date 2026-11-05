"""Composite blank-terminal overlays with ffmpeg drawbox + drawtext (post-production).

Model frames keep screens blank/dark; readable content is drawn here from overlay_texts.json
entries with g=terminal.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from typing import List, Optional, Sequence


def _esc_drawtext(s: str) -> str:
    return (s or '').replace('\\', '\\\\').replace(':', '\\:').replace("'", r"\'").replace('%', '%%')


def filter_for_overlay(ov: dict, *, W: int = 1920, H: int = 1080,
                       fontfile: str = '') -> str:
    """Build an ffmpeg filter fragment for one terminal overlay dict."""
    rect = ov.get('rect') or [0.55, 0.20, 0.40, 0.45]
    x, y, w, h = [float(v) for v in rect]
    x0, y0 = int(x * W), int(y * H)
    bw, bh = max(8, int(w * W)), max(8, int(h * H))
    text = _esc_drawtext(ov.get('text') or '')
    font = f":fontfile={fontfile}" if fontfile and os.path.exists(fontfile) else ''
    box = f"drawbox=x={x0}:y={y0}:w={bw}:h={bh}:color=black@0.85:t=fill"
    # Multi-line: replace newlines with drawtext line breaks
    lines = text.split('\\n') if '\\n' in text else text.split('\n')
    parts = [box]
    line_h = max(14, bh // max(1, len(lines) + 1))
    for i, line in enumerate(lines[:12]):
        ty = y0 + 8 + i * line_h
        parts.append(
            f"drawtext=text='{_esc_drawtext(line)}':x={x0 + 10}:y={ty}:fontsize={max(12, line_h - 4)}"
            f":fontcolor=0x7CFF9A{font}:box=0"
        )
    enable = ''
    if 't0' in ov and 't1' in ov:
        enable = f":enable='between(t,{float(ov['t0']):.3f},{float(ov['t1']):.3f})'"
        parts = [p + enable for p in parts]
    return ','.join(parts)


COMPOSITE_KINDS = frozenset({'terminal', 'hud', 'caption'})


def from_overlays(overlays: Sequence[dict], *, W: int = 1920, H: int = 1080,
                  fontfile: str = '') -> str:
    """Combine terminal/HUD/caption overlays into one -vf chain (may be empty).

    Kinetic/story/slam overlays are typically ASS/kgfx layers; terminal+HUD use drawtext.
    """
    terms = [
        o for o in overlays
        if (o.get('g') or o.get('kind')) in COMPOSITE_KINDS and o.get('text')
    ]
    if not terms:
        return ''
    return ','.join(filter_for_overlay(o, W=W, H=H, fontfile=fontfile) for o in terms)


def composite(src: str, dst: str, overlays: Sequence[dict],
              *, W: Optional[int] = None, H: Optional[int] = None,
              fontfile: str = '') -> dict:
    """Apply terminal overlays onto ``src`` video → ``dst``. No-op copy if none."""
    vf = from_overlays(overlays, W=W or 1920, H=H or 1080, fontfile=fontfile)
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
    if not vf:
        if os.path.abspath(src) != os.path.abspath(dst):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-c', 'copy', dst], check=True)
        return {'ok': True, 'composited': False, 'out': dst}
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', vf, '-c:v', 'libx264',
           '-preset', 'fast', '-crf', '18', '-c:a', 'copy', dst]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return {
        'ok': r.returncode == 0 and os.path.exists(dst),
        'composited': True,
        'out': dst if r.returncode == 0 else src,
        'vf': vf[:300],
        'err': (r.stderr or '')[-300:],
    }
