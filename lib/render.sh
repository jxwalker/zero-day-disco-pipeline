#!/bin/bash
# Render the karaoke video (27 Sep design). usage: render.sh AUDIO WORK_DIR OUT.mp4 [DURATION]
# Full song, audio untouched apart from AAC encode. Moving neon gradient bg, lissajous scope, cover with
# gentle zoom + hue-cycling glow, gradient spectrum (+reflection), gradient waveform, ASS overlay.
set -euo pipefail
AUDIO=$1; WORK=$2; OUT=$3
DUR=${4:-$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO")}
cd "$WORK"
ffmpeg -v error -stats -y -i "$AUDIO" \
 -loop 1 -framerate 30 -t "$DUR" -i cover.jpg \
 -loop 1 -framerate 30 -t "$DUR" -i glow.png \
 -f lavfi -t "$DUR" -i "gradients=s=1080x1920:r=30:n=4:c0=0x8e2de2:c1=0xff2e97:c2=0x2b5cff:c3=0x00a6c7:type=linear:speed=0.008:x0=0:y0=0:x1=1080:y1=1920" \
 -loop 1 -framerate 30 -t "$DUR" -i specgrad.png \
 -loop 1 -framerate 30 -t "$DUR" -i wavegrad.png \
 -filter_complex "
 [3:v]hue=h='25*sin(2*PI*t/45)':s=1.1,eq=brightness=-0.16:saturation=1.25,vignette=PI/4.5[bg];
 [0:a]asplit=4[a1][a2][a3][aout];
 [a1]avectorscope=s=1000x1000:r=30:mode=lissajous:draw=line:scale=sqrt:zoom=1.7:rc=0:gc=200:bc=255:ac=200:rf=60:gf=40:bf=30:af=45,format=rgba,gblur=sigma=1.5,colorchannelmixer=aa=0.75,transpose=1,scale=1080:1000[vs];
 [2:v]format=rgba,hue=h='t*12'[glow];
 [1:v]scale=640:640,format=rgba[cv];
 [cv]scale=w='2*trunc(640*(1+0.03*sin(2*PI*t/7.5))/2)':h=-2:eval=frame[cov];
 [bg][vs]overlay=0:120:format=auto[b0];
 [b0][glow]overlay=40:120[b1];
 [b1][cov]overlay=x='(W-w)/2':y='620-h/2':eval=frame[b2];
 [a2]aformat=channel_layouts=mono,showfreqs=s=1000x200:r=30:mode=bar:ascale=cbrt:fscale=log:win_size=2048:averaging=2:colors=white,format=gray[sm];
 [sm]split[sm1][sm2];
 [4:v]format=rgba,split[g1][g2];
 [g1][sm1]alphamerge[spec];
 [sm2]vflip,eq=brightness=-0.25[smr];
 [g2][smr]alphamerge,colorchannelmixer=aa=0.45[specr];
 [a3]aformat=channel_layouts=mono,showwaves=s=1000x80:r=30:mode=cline:colors=white:scale=sqrt,format=gray[wm];
 [5:v]format=rgba[wg];[wg][wm]alphamerge,colorchannelmixer=aa=0.85[wav];
 [b2][spec]overlay=40:960[b3];
 [b3][specr]overlay=40:1160[b4];
 [b4][wav]overlay=40:1765[b5];
 [b5]ass=video.ass,scale=out_range=tv:out_color_matrix=bt709,format=yuv420p[v]" \
 -map "[v]" -map "[aout]" -t "$DUR" -c:v libx264 -preset medium -crf 21 -maxrate 2900k -bufsize 5800k -profile:v high -level 4.1 \
 -pix_fmt yuv420p -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv -r 30 -g 60 \
 -c:a aac -b:a 192k -movflags +faststart "$OUT"
