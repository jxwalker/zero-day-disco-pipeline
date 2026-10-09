# Lyric rules (daily AI news song) — added 2026-10-10 after the owner's feedback

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
