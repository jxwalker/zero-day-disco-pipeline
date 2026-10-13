#!/bin/bash
# Build the daily Suno karaoke video for a day folder.
# usage: tools/build_video.sh <day_folder> [--force] [--keep-stems] [--no-render] [--model NAME]
#                              [--out video.mp4] [--frames frames] [--work work]   (names relative to the day folder)
# Needs in <day_folder>: audio.mp3, lyrics.txt, tags.json (skeleton auto-created), optional stories.md/title.txt
# Writes: <day>/<out>, <day>/<frames>/*.jpg, <day>/<work>/{timings.tsv,sync_report.json,verify.json,...}
set -euo pipefail
TOOLS=$(cd "$(dirname "$0")" && pwd); LIB=$TOOLS/lib
PY=${PY:-/home/box/venvs/align/bin/python}
DEMUCS=${DEMUCS:-/home/box/venvs/align/bin/demucs}
DAY=""; FORCE=0; KEEP=0; RENDER=1; MODEL=medium; OUT=video.mp4; FRAMES=frames; WORKN=work
while [ $# -gt 0 ]; do case "$1" in
  --force) FORCE=1;; --keep-stems) KEEP=1;; --no-render) RENDER=0;;
  --model) MODEL=$2; shift;; --out) OUT=$2; shift;; --frames) FRAMES=$2; shift;; --work) WORKN=$2; shift;;
  --karaoke) KARAOKE=1;;
  -h|--help) sed -n 2,7p "$0"; exit 0;;
  *) DAY=$1;; esac; shift; done
[ -n "$DAY" ] || { sed -n 2,3p "$0"; exit 2; }
# 13 Oct 2026: the owner dropped the karaoke video on 5 Oct. Daily folders (exactly YYYY-MM-DD) skip it unless --karaoke
# (or KARAOKE=1); grok_video does its own lyric alignment. Special / dated-variant folders are unaffected.
if [ "${KARAOKE:-0}" != 1 ] && [[ "$(basename "$DAY")" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "KARAOKE_SKIPPED: the daily karaoke video was dropped on 2026-10-05; post grok_video's out= file. (--karaoke to build anyway)"
  exit 0
fi
DAY=$(cd "$DAY" && pwd); WORK=$DAY/$WORKN; AUDIO=$DAY/audio.mp3; VIDEO=$DAY/$OUT
for f in "$AUDIO" "$DAY/lyrics.txt"; do [ -f "$f" ] || { echo "missing $f"; exit 2; }; done
mkdir -p "$WORK"; cd "$DAY"
log(){ echo -e "\n=== [$(date +%H:%M:%S)] $*"; }
fresh(){ [ $FORCE -eq 0 ] && [ -s "$1" ] && [ "$1" -nt "$2" ]; }   # output exists and newer than input
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO")
STEM=$WORK/sep/htdemucs/audio/vocals.wav

log "1/8 prepare (tags.json, lyrics, cover art)"
$PY $LIB/prepare.py "$DAY" "$WORK"

log "2/8 demucs vocal separation"
if fresh "$STEM" "$AUDIO"; then echo "cached $STEM"; else
  $DEMUCS -n htdemucs --two-stems vocals -o "$WORK/sep" "$AUDIO" > "$WORK/demucs.log" 2>&1; fi

log "3/8 faster-whisper free word timings (reference)"
if fresh "$WORK/fw_words.json" "$AUDIO"; then echo "cached fw_words.json"; else
  $PY $LIB/transcribe.py "$STEM" "$AUDIO" "$WORK/fw_words.json" $MODEL 2>&1 | grep -v Warning | tee "$WORK/fw.log"; fi

log "4/8 choose sung line sequence"
$PY $LIB/choose_script.py "$WORK" "$AUDIO" "$DAY/tags.json" | tee "$WORK/choose.log"

log "5/8 stable-ts forced alignment on vocal stem"
if [ $FORCE -eq 0 ] && [ -s "$WORK/align.json" ] && cmp -s "$WORK/lyrics_sung.txt" "$WORK/align_input.txt"; then
  echo "cached align.json"; else
  $PY $LIB/align.py "$STEM" "$WORK/lyrics_sung.txt" "$WORK/align.json" $MODEL 2>&1 | grep -v Warning | tee "$WORK/align.log"
  cp "$WORK/lyrics_sung.txt" "$WORK/align_input.txt"; fi

log "6/8 merge + sync check"
$PY $LIB/timings.py "$WORK" "$DUR" | tee "$WORK/timings.log"

log "7/8 overlay (ASS) + assets"
$PY $LIB/make_assets.py "$WORK"
$PY $LIB/make_ass.py "$DAY" "$WORK" "$DAY/tags.json" "$DUR"

if [ $RENDER -eq 1 ]; then
  log "8/8 render + verify"
  PART="$WORK/render.part.mp4"
  bash $LIB/render.sh "$AUDIO" "$WORK" "$PART" "$DUR" 2> >(tr '\r' '\n' | grep -v '^frame=' >&2)
  mv "$PART" "$VIDEO"
  $PY $LIB/verify.py "$DAY" "$WORK" "$VIDEO" "$AUDIO" "$DAY/$FRAMES" | tee "$WORK/verify.log"
  if [ $KEEP -eq 0 ]; then rm -rf "$WORK/sep"; echo "removed stems ($WORK/sep)"; fi
fi
log "done: $VIDEO"
