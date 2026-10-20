# suno-daily karaoke video pipeline

One command turns a day folder (Suno mp3 + lyrics) into the standard vertical karaoke video
(27 Sep design) and checks it.

```bash
/home/box/suno-daily/tools/build_video.sh /home/box/suno-daily/<day_folder> [--force] [--keep-stems] [--no-render] [--model medium] \
    [--out video.mp4] [--frames frames] [--work work]
```

* `--out`, `--frames` and `--work` set the output video, frames folder and scratch folder, as names relative to the day folder.
  Use them to keep another build's outputs intact. Example (today's test):
  `tools/build_video.sh 2026-09-28-v2 --out video_pipeline.mp4 --frames frames_pipeline --work work_pipeline`
* Exit code is non-zero if any step or any verification check fails.

## What the day folder needs

| file | required | used for |
|---|---|---|
| `audio.mp3` | yes | the song, used as is (never trimmed or edited, only AAC-encoded into the mp4) |
| `lyrics.txt` | yes | Suno-style lyrics with `[Section]` tags. **All caption wording comes from here.** Everything after `[End]` is ignored |
| `tags.json` | recommended | title, date, song URL, story tags (see below). A skeleton is written if missing |
| `stories.md` | optional | `@handles` for the end card (from `x.com/<handle>/status` links and explicit `@mentions`) |
| `title.txt`, `song_url.txt` | optional | fallbacks when tags.json has no title or song_url |

### tags.json

```json
{
 "title": "Out of the Box",
 "date": "2026-09-28",
 "song_url": "https://suno.com/song/7b6787e6-ebb1-4a1a-a7fa-898bedf12ff4",
 "story_tags": [
  {"section": "Verse 1", "lines": [1, 4], "text": "OpenAI pauses after sandbox escape"},
  {"section": "Verse 1", "lines": [5, 8], "text": "NaiveAI's open 309B model"}
 ],
 "section_tags": {"bridge": {"label": "BRIDGE", "text": "Can you feel it?"}}
}
```

* `story_tags`: topic boxes (just the story topic, no label). `section` is the tag name as written in lyrics.txt, `lines` is a 1-based
  inclusive line range within that section (lyrics.txt numbering, so repeats Suno adds still get the right tag).
  Optional: `occurrence` (for repeated section names), `label`, `color` (pink/cyan/yellow/purple or a hex).
* Sections without a story tag get defaults: intro "AI NEWS · <date>", chorus and post-chorus "CHORUS · Sing along!"
  ("FINAL CHORUS" if the tag says Final), pre-chorus, bridge, outro. Override any of these in `section_tags` by section name or
  kind (`intro`, `verse`, `prechorus`, `chorus`, `postchorus`, `bridge`, `outro`).
* Optional keys: `subtitle` (default "AI news, 28 Sep 2026"), `title_card` (title-card text), `tagline`, `intro_text`,
  `sources` (list of handles, overrides stories.md), `sung_lines` (explicit sung order as 0-based lyrics.txt line indexes),
  `title_card_end` (default 4.5 s), `end_card_start`.
  See `tags.example.json`.

## Steps (lib/)

1. `prepare.py`: parse lyrics (`work/lines.json`), write a skeleton tags.json if needed, and get the cover art from the song
   page's `og:image` (normal public fetch, cached per URL). Falls back to the mp3's embedded art, then a generated image.
2. demucs `htdemucs --two-stems vocals`, giving `work/sep/htdemucs/audio/vocals.wav`.
3. `transcribe.py`: free faster-whisper (medium, no lyric prompt) word timings, used as the independent reference.
   It runs three chunked passes (vocals 12 s and 20 s windows, mix 12 s windows) and merges them, collapsing hallucination loops.
4. `choose_script.py`: works out which lines are actually sung and in what order. Candidates are lyrics.txt as written, the lyrics
   Suno embedded in the mp3 (mapped back to lyrics.txt lines), and a hybrid that switches each difference on only if it
   improves the LCS match with the whisper transcript. `sung_lines` in tags.json overrides all of them.
5. `align.py`: stable-ts forced alignment of the chosen lines against the vocal stem (`work/align.json`).
6. `timings.py`: maps stable-ts words to display tokens, then runs the **sync check**, a time-gated (±2 s) LCS between lyric words
   and whisper words that reports % of matched words within 0.3 s (target 95 %). Then it repairs timings:
   * a line whose words disagree with whisper by a median > 0.3 s is re-timed from whisper
   * a single word > 0.3 s off takes the whisper time when whisper is confident (p ≥ 0.5)
   * a word with no pair gets a same-spelled whisper word between its matched neighbours, as long as word order in the line is kept
   * an unconfirmed first or last word parked far from its neighbour is pulled in, either to a same-spelled whisper word next to
     the neighbour (echo/ad-lib case) or when whisper heard other words in that gap
   * lines stable-ts lost are rescued from whisper words in the gap between the neighbouring good lines. "Lost" means
     smeared over a break, squashed at the end of the file, or unsupported by whisper. Leftover words go to the next vocal
     onset in the stem. An unsupported but plausible line is only moved when stable-ts leaves more than 2.5 s of clearly
     sung, unexplained vocals before it (shifted to that onset). Otherwise it is kept.
   * Sanity check: on the 27 Sep song, the rescue automatically reproduced the manual fix made that day
     ("Wanted a quiet weekend…" moved from the vamp to 81.6 s)

   It writes `work/timings.json`, `work/timings.tsv` and `work/sync_report.json`, with raw (pure stable-ts) and final stats.
7. `make_assets.py` + `make_ass.py`: glow/gradient PNGs and the ASS overlay. This covers word-by-word `\kf` karaoke (verses 100 px,
   choruses 128 px bold with pink glow), a dim next-line preview, the story/section tag box, the title card (Monoton), the end
   card ("MADE WITH SUNO", title, date, "SOURCES ON X" handles, song URL) and the footer.
8. `render.sh`: ffmpeg render at 1080x1920 30 fps. Layers: moving neon gradient, lissajous scope, cover with gentle zoom
   and hue-cycling glow, gradient spectrum with reflection, gradient waveform, ASS. Output is H.264 High yuv420p, AAC 192k,
   +faststart, full audio length.
9. `verify.py`: ffprobe checks (resolution, fps, codec/profile, pix_fmt, AAC bitrate, moov-before-mdat, duration equal to the
   audio's ±0.1 s) and review frames in `<day>/frames/`: title, verse 1, chorus, verse 2, bridge, one per uncovered story tag,
   and the end card. Exits non-zero if a check fails.
10. Deletes `<work>/sep` (stems, ~50 MB) unless `--keep-stems` is given. Small JSON/TSV/ASS files stay in `<work>` for audit.

Steps are cached. Stems, whisper words and alignment are reused when present and up to date, and `--force` redoes everything.
`--no-render` stops after the overlay, so you can check `work/timings.tsv` quickly.
After editing tags.json only, re-running is cheap if the stems are kept (`--keep-stems`). Otherwise demucs runs again, which takes about 1 min.

## Typical run time (8 CPU cores, 2.5 min song)
demucs ~1 min · whisper passes ~4-5 min · stable-ts ~0.5 min · render ~6 min.

## Environment
`PY` (default `/home/box/venvs/align/bin/python`) and `DEMUCS` (default `/home/box/venvs/align/bin/demucs`) can be overridden.
Fonts: Poppins + Monoton from `/usr/share/fonts/truetype/sand-box/google/`. Models: faster-whisper `medium`, `htdemucs` (HF cache).

## Reading the sync numbers
`work/sync_report.json` holds `raw_stable_ts` (pure stable-ts compared with whisper) and `final` (after the repairs), each with
`coverage_pct` (lyric words whisper could pair within ±2 s), `within_0.3s_pct` (the 95 % target) and the median error. It also
lists every line that was re-timed or rescued. Whisper only hears some sung words, so coverage below 100 % is normal.
The final figure is partly circular (repairs use whisper), so keep an eye on the raw figure and on the review frames too.
Timings vary slightly from run to run, because demucs and whisper chunking are not bit-exact.

## Posting to X (`x_post.py`)

Posts to @jxwalker through the X API (OAuth 1.0a user keys, read-write, pay-per-use ~$0.01/post).
Credentials: env `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`,
falling back to `$PIPELINE_SECRETS_FILE` (key `card`). Never print them.

```bash
python3 /home/box/suno-daily/tools/x_post.py --verify            # read-only check, posts nothing
python3 /home/box/suno-daily/tools/x_post.py --text-file post.txt --video video_mascot.mp4 --reply-file sources.txt
# prints {"id":..., "url":..., "reply_id":..., "reply_url":...}
```

Video is uploaded in 4 MB chunks (v2 media upload, falls back to v1.1) and waits for processing.
@jxwalker has X Premium+, so posts can be longer than 280 characters. The daily post @mentions every X account credited on the end card. If a post fails with 403 "oauth1 app permissions",
the access token is read-only: the owner must regenerate it after setting Read and write.

### Daily post rules (from 19 Oct 2026, the owner)
- **post.txt** (main post, written by the routine): keep the opener, the 2-4 story lines and the 🎵 Suno link as now,
  and ALWAYS include a natural credit line with **"Grok Bot"**, a real **@grok** mention (so Grok replies) and
  **#slopcore**, placed in the first 280 characters (above "Show more"), e.g. right after the opener:
  `Made by Grok Bot, an agent that writes, sings and films the day's AI stories. @grok, what's your verdict? #slopcore`
  Still @mention the sung stories' handles. Premium+ limit is 25,000 weighted chars (URL = 23, emoji = 2); aim for
  under ~700.
- **sources.txt** (the reply): unchanged: one line per story with its x.com link and handle, then the Suno link.
- **Check:** `python3 tools/post_lint.py <day>/post.txt <day>/sources.txt` must print `post lint: clean`.
  x_post.py runs the same check and refuses to post (exit 3, nothing uploaded) if it fails.

## Lyric rules (pre-Suno)
See `LYRICS_RULES.md`. Before pasting lyrics into Suno run `python3 tools/lyrics_lint.py <day>/lyrics.txt` (exit 1 = fix lines first). No sung "AI news"/meta lines; no instrument/genre/production words in sung lines (those live in style.txt only).

## Suno vocal/style rules (16 Oct 2026)
the owner called the 16 Oct "Cap in Hand" (comedy news jingle / brassy swing) "auto tuned garbage". Standing rules:
- Every style.txt ends with "natural raw human lead vocals, no autotune, no vocoder, no pitch correction".
  headline.py / narrative.py enforce it via `style_lint.fix`; check with `python3 tools/style_lint.py <day>/style.txt`
  (must print "style lint: clean"; `--fix` repairs). headline_day.sh runs it too.
- No "jingle" styles of any kind (comedy news jingle, late-night jingle, swing jingle). Real band genres with real
  vocal performances; the humour stays in the lyrics.
- **Suno step (computerUse):** in Custom/Advanced mode, open "More Options" under Styles and type
  `autotune, vocoder, jingle` into **Exclude styles** before Create. If that field is not visible, note it in the
  log and continue (the style.txt wording still applies). Duration stays 2:30.

### Source reply (one extra post per day, approved by the owner 18 Oct 2026)
After the daily post is up (its URL is in `<day>/log.md`), reply to the MAIN story's source post with the same video:
```bash
python3 /home/box/suno-daily/tools/x_source_reply.py /home/box/suno-daily/<day> --dry-run   # check, posts nothing
python3 /home/box/suno-daily/tools/x_source_reply.py /home/box/suno-daily/<day>
```
- Text: `<day>/post/source_reply.txt`, one short human line + `{POST_URL}`, e.g. `Turned this into a song 🎶 {POST_URL}`.
- Reply with the video. On a 403 or reply restriction: quote post (with the video) tagging @author. X API v2 doesn't
  allow media with quote_tweet_id, so if that's rejected it posts the video with "@author line <their URL> <our URL>"
  (mode `quote_link`).
- Video uploaded once (media_id cached in `post/source_media.json`). It won't run if `post/source_reply_result.json`
  exists; it writes {mode, url, ...} there and adds a `- source <mode>:` line to log.md.

## Song takes (19 Oct 2026)
Every Suno Create makes TWO takes for the same credits (no extra spend), so the routine should listen to / compare
both and keep the take with the more natural, un-autotuned lead vocal (clearer words, less pitch-snapped, no vocoder
sheen), not just the first one. Note the choice and why in log.md. Docs only: no tool does this automatically yet.

## Per-bot post checks (20 Oct 2026)
the owner chose: each bot gets its own post checks. `x_post.py --bot suno` (the default) keeps the Grok Bot / @grok / #slopcore / Suno-link rules unchanged. `x_post.py --bot interesting-x` runs only generic checks (non-empty, no secrets, valid links, length). `--lint-only` runs the checks and posts nothing. `post_lint.py --bot interesting-x post.txt sources.txt` does the same from the CLI.
