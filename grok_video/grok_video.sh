#!/bin/bash
# Daily Grok music video for a suno-daily day folder. See README.md.
# usage: grok_video.sh <day_dir> [--style cine-real|mascot] [options]
# Default (since 9 Oct 2026): --style cine-real -> <day_dir>/video_cine_real.mp4 (+ _chat.mp4), scratch work_cine_real;
# if cine-real fails it falls back to --style mascot -> <day_dir>/video_grok.mp4. ALWAYS post the file named by out=
# in the last line (GROK_VIDEO_STATUS=...). Exit 0 = ok, 6 = song looks instrumental, 7 = grok not signed in,
# 3 = generation failed (no video), 4 = lyric timing failed, 5 = output failed verification, 2 = bad input.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-/home/box/venvs/align/bin/python}
export PYTHONWARNINGS=ignore
exec "$PY" "$HERE/grok_video.py" "$@"
