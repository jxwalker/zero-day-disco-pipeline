#!/bin/bash
# compare.sh OUT.mp4 SHEET.jpg  "grok.mp4|local.mp4|label" ...   -> side-by-side (Grok left, local right) + contact sheet
set -e
OUT=$1; SHEET=$2; shift 2
F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
T=$(mktemp -d); i=0; list=$T/list.txt; : > $list; sheets=()
for spec in "$@"; do
  IFS='|' read -r G L LAB <<< "$spec"
  printf '%s' "$LAB" > $T/lab$i.txt; printf '%s' "$LAB    (left 3 = Grok, right 3 = local)" > $T/slab$i.txt
  LD=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$L")
  GD=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$G")
  D=$(python3 -c "print(max($LD,$GD))")
  ffmpeg -v error -y -i "$G" -i "$L" -filter_complex "
   [0:v]fps=24,scale=540:960,setsar=1,tpad=stop_mode=clone:stop_duration=10,trim=duration=$D,
     drawtext=fontfile=$F:text='GROK (720p 24fps, ${GD%.*}s clip)':x=14:y=14:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6,
     drawtext=fontfile=$F:text='held last frame':x=14:y=h-44:fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.6:boxborderw=5:enable='gt(t,$GD)'[g];
   [1:v]fps=24,scale=540:960,setsar=1,tpad=stop_mode=clone:stop_duration=10,trim=duration=$D,
     drawtext=fontfile=$F:text='LOCAL Spark - Wan2.2 I2V 14B':x=14:y=14:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6[l];
   [g][l]hstack=2,pad=1080:1010:0:0:black,drawtext=fontfile=$F:textfile=$T/lab$i.txt:x=14:y=972:fontsize=24:fontcolor=white[v]" \
   -map "[v]" -an -c:v libx264 -preset slow -crf 25 -pix_fmt yuv420p -r 24 $T/seg$i.mp4
  echo "file '$T/seg$i.mp4'" >> $list
  # contact sheet row: 3 grok frames + 3 local frames
  ffmpeg -v error -y -i "$G" -vf "select='eq(n\,0)+eq(n\,36)+eq(n\,72)',scale=240:-1,tile=3x1" -frames:v 1 $T/g$i.png
  ffmpeg -v error -y -i "$L" -vf "select='eq(n\,0)+eq(n\,40)+eq(n\,80)',scale=240:-1,tile=3x1" -frames:v 1 $T/l$i.png
  ffmpeg -v error -y -i $T/g$i.png -i $T/l$i.png -filter_complex "[0][1]hstack=2,pad=iw+0:ih+36:0:36:white,drawtext=fontfile=$F:textfile=$T/slab$i.txt:x=8:y=6:fontsize=22:fontcolor=black" $T/row$i.png
  sheets+=(-i $T/row$i.png); i=$((i+1))
done
ffmpeg -v error -y -f concat -safe 0 -i $list -c copy -movflags +faststart "$OUT"
if [ $i -gt 1 ]; then ffmpeg -v error -y "${sheets[@]}" -filter_complex "vstack=$i" -q:v 3 "$SHEET"; else cp $T/row0.png "$SHEET"; fi
ls -la "$OUT" "$SHEET"; rm -rf $T
