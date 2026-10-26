# Lyric rules (daily AI news song)

1. Never sing the phrase "AI news", or meta lines about the song, the news, the show,
   the broadcast or the listener ("sing it with me", "news on fire", "today's headlines",
   "this song", "tune in"). The chorus is a hook about the day's THEME, not about the news.
2. Never put instrument / genre / production / mix words in sung lines (jangly guitars,
   synths, 808s, bass drop, BPM, reverb, autotune, indie rock, "male vocals"...). They go
   ONLY in style.txt. Section tags like [Intro], [Chorus] are fine.
3. Run the lint before pasting into Suno:
     python3 /home/box/suno-daily/tools/lyrics_lint.py <day>/lyrics.txt          # exit 1 on violations
     python3 /home/box/suno-daily/tools/lyrics_lint.py <day>/lyrics.txt --fix     # drops offending lines (backs up to lyrics.txt.prelint)
   Prefer rewriting a flagged line by hand (keep meter); --fix only deletes lines.

## Density limits
"Sleeping On The Job" (84 BPM 6/8, 305 words, 12 syllables/line) felt rushed. lyrics_lint.py now fails over:
- slow (<100 BPM or 6/8, 12/8, 3/4): max 8 syllables / 7 words per line, 150 words total
- mid (100-119 BPM): max 9 / 8, 165 total
- uptempo (120+ BPM): max 10 / 9, 180 total
- verses 4 lines, chorus 4 lines with a repeated hook, final chorus 5, bridge 4 (spoken max 12 words/line), intro/outro 1
See `tools/lyric_metrics.py <lyrics.txt>` for the measurements. BPM/metre come from style.txt next to lyrics.txt.

## Viral-hit format
Default for every daily song . lyrics_lint.py fails (use --no-viral to skip) unless:
- the first section is a sung chant hook ([Intro - chant] + title line), no instrumental intro
- the first [Chorus] has at most 7 sung lines before it (hook 1 + verse 4 + pre-chorus 2, ~25 s)
- every section tag has an energy tag ("[Chorus - full energy]")
- there are [Pre-Chorus - build], [Post-Chorus - chant] (oh-oh), [Breakdown - stripped], [Final Chorus - key change, biggest]
- the title phrase (title.txt, or --title=) is sung in the chorus, post-chorus and outro
style_lint.py also requires "female lead vocal", high-energy wording, "pop", and at most 200 characters.
Plus: under 2:30, a cheeky PG-13 double entendre, 1-2 geeky jokes, pop flavour rotates daily.
