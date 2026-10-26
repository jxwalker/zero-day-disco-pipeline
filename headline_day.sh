#!/bin/bash
# Daily lyrics step, headline mode.
# usage: tools/headline_day.sh <day_dir>      (needs <day_dir>/stories.md)
# Writes lyrics.txt style.txt title.txt headline.json headline.md storyboard_draft.md tags.json (lint-checked, Opus self-scored).
# Exit 0: use lyrics.txt/style.txt/title.txt in Suno; grok_video.sh then runs in headline mode automatically (headline.json).
# Exit non-zero: headline.json etc. are moved aside; write lyrics yourself, run lyrics_lint.py, and the video runs in v5 mode.
set -uo pipefail
DAY=${1:?usage: headline_day.sh <day_dir>}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-/home/box/venvs/align/bin/python}
[ -s "$DAY/stories.md" ] || { echo "HEADLINE_DAY_STATUS=fail code=2 reason=no_stories"; exit 2; }
timeout "${HEADLINE_TIMEOUT:-3000}" "$PY" "$HERE/grok_video/headline.py" write "$DAY" 2>&1 | tee -a "$DAY/headline_day.log"
rc=${PIPESTATUS[0]}
if [ "$rc" -eq 0 ] && [ -s "$DAY/lyrics.txt" ] && [ -s "$DAY/headline.json" ] && python3 "$HERE/lyrics_lint.py" "$DAY/lyrics.txt" | grep -q "lint: clean" \
   && python3 "$HERE/style_lint.py" "$DAY/style.txt" --fix | tee -a "$DAY/headline_day.log" | grep -q "style lint: clean"; then
  echo "HEADLINE_DAY_STATUS=ok code=0 title=$(cat "$DAY/title.txt") suno_exclude_styles='autotune, vocoder, jingle'"
  exit 0
fi
mkdir -p "$DAY/headline_failed"
for f in headline.json headline.md storyboard_draft.md lyrics.txt style.txt title.txt; do
  [ -e "$DAY/$f" ] && mv "$DAY/$f" "$DAY/headline_failed/"
done
echo "HEADLINE_DAY_STATUS=fallback code=${rc:-1} reason=headline.py_failed_or_lint (drafts in $DAY/headline_failed/)"
exit 1
