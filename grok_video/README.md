# grok_video: the daily Grok music video

## karaoke mode: THE DEFAULT since Tue 20 Oct 2026 (the owner approved the ONUG "No Window" video as the standard)

`grok_video.sh <day>` now runs `karaoke.py` (no flags needed). The old chain below (Claudia/slopcore -> cine-real ->
mascot) is kept as the automatic fallback and can be switched back on:
- **Switch back for good:** `export GV_KARAOKE=0` in the routine (or `GV_KARAOKE=0 grok_video.sh <day>`).
- **One-off:** pass any `--style ...` (e.g. `--style slopcore`) and grok_video.sh goes straight to grok_video.py.
- **Automatic:** if karaoke fails (anything except exit 6 instrumental / 7 not signed in) it exec's grok_video.py with the
  same arguments, so the status line and `out=` then come from the old chain. `--no-fallback` stops that (tests).

Format: word-by-word karaoke (current line bold lower-middle with a colour wipe, next line dimmer below, (ad-libs)
italic amber), on a dark band; above it fast cuts on lyric-line starts (~1.5-3 s shots) mixing code-rendered motion
graphics with exact text (`kgfx.py`: term, headline, bignum, bars, post, inbox, code, rows, stamp, dash, countdown,
pipeline, bluegreen) and Grok Imagine live-action stills/6 s clips (young adults 21-28, balanced expressions, no robots,
no real people, no text in pictures). Story text layer: a top-left chip (MAIN STORY, then the secondary stories) over
the lines that sing each story. End card: title, one-line story credit, "Grok Bot · <date>", and small
"X: @jxwalker · scorpion-labs.com".

Pipeline: (in parallel) Opus plan (`prompts/karaoke_plan.txt`, ~2 min, 2 tries, else a no-LLM template plan from
stories.md) + alignment -> fact lint (every 2+ digit figure, CVE id and @handle in a graphic must be in
stories.md/lyrics/title, else the graphic becomes a story headline) -> Grok: <=14 stills (stacked-duplicate pictures
are detected and rerolled once), <=8 six-second clips; no new Grok work after 26 min -> timeline (cut on every lyric
line start, long shots split at 3.6 s, `GV_KARAOKE_MAX_SHOT`) -> render 1080x1920 + 1920x1080 (8 procs) -> ASS burn +
audio -> chat copy (~40 MB target) -> verify (grok_video.verify) + `work_karaoke/contact_sheet.jpg` + spelling check.

Alignment (the ONUG method, `work_karaoke/kalign/`): demucs htdemucs vocals (~35 s idle box, ~4.5 min when the box is
busy) -> stable-ts `medium.en` forced alignment of the lyrics.txt lines (~30 s). Sanity: each line gets a score
(monotonic words, no >4 s words, not squeezed, words on audible vocal-stem frames); if the line count is wrong or >30 %
of lines are suspect, the old pipeline (`lyric_timings()` in grok_video.py: whisper + stable-ts + repair, ~11 min) runs
and the better-scoring result wins. Suspect lines get a line-level wipe instead of word-by-word; the whole song goes
line-level if >30 % of lines are suspect. Tails parked after a >4 s gap or past the next line are re-spread.
Instrumental gate: vocal stem low (stem_is_low) AND weak alignment -> exit 6.
Outputs: `<day>/video_karaoke.mp4` (1080x1920, **posted**), `video_karaoke_chat.mp4` (<45 MB, send in chat),
`video_karaoke_16x9.mp4` (1920x1080); scratch `<day>/work_karaoke/` (plan.json, timeline.json, status.json,
contact_sheet.jpg, grok/). Status line: `GROK_VIDEO_STATUS=ok code=0 style=karaoke ... out=<mp4> chat=<mp4> wide=<mp4> ...`
(post `out=` exactly as before; the 5pm routine is unchanged).
Options: `--stills N` `--clips N` (or GV_KARAOKE_STILLS/CLIPS), `--time-limit MIN` (40), `--replan`, `--skip-gen`
(re-render from cached media, never spends), `--no-16x9`, `--no-fallback`. Re-render at zero Grok cost:
`grok_video.sh <day> --skip-gen --no-fallback`.
Grok usage: about 14 stills + 8 clips per day (measured on the 20 Oct test, see below). Runtime: see below.


### karaoke v2 (20 Oct 2026 afternoon): per-video design, screen check
the owner: "similar style but it can't look copied" and "the screens are on the back of the laptops".
- **Art direction per video** (`design.py`): Opus picks palette (9), type family (8), lyric_style (pop, block,
  underline, bounce, reveal, neon, marker, wipe), lyric position (lower-center, lower-left, bottom-band), transition
  (cut, flash, dip, punch, slide, glitch), grade (6) and texture from the song's genre/mood and the stories.
  `design.resolve()` forces a different palette/type/lyric_style from the last 3 days and transition from yesterday,
  and never the exact No Window lyric look. Each day's choice + template counts go to
  `/home/box/suno-daily/karaoke_design_history.json` (fed back into the next plan).
- **Graphics** (`kgfx2.py`, themed by the design): story-domain templates headline, bignum, bars, post, feed, inbox,
  chat, code, terminal, rows, stamp, quote, browser, gauge, compare, countdown, screen. The ONUG ones (NOC dashboard,
  blue/green switch, pipeline, CAB calendar, change ticket, DNS) are gone (unknown types become headlines). No template
  more than twice per video (`MAX_PER_TEMPLATE`); extras become the least-used live-action scene.
- **Lyrics** (`klyrics.py`): per-word ASS events laid out with PIL metrics; `design.ASS_SCALE` holds the measured
  libass/PIL size ratio per font (re-measure if fonts are added).
- **Screens**: the Grok prompts carry a screen rule (screen faces camera, over-the-shoulder or straight-on, never a lid
  back). After the stills, Claude (headless, Read tool) checks every still (`screen_check()`: reversed/away screens,
  content on a lid, stacked duplicates, robots, garbled text, bad hands); rejects are rerolled once with an
  over-the-shoulder framing, re-checked, and still-bad ones are dropped (their uses become a code-rendered `screen`
  insert, at most 2, or another scene). Only checked stills are animated. Results: `work_*/grok/screen_check_*.json`.
- v1 files (`kgfx.py`, `kgfx_base.py`) are kept but no longer used. Backups: `*.bak-20261020-karaoke2`.

---


Builds the daily song's video with Grok Imagine, through the signed-in Grok Build CLI on the SuperGrok Heavy
subscription (**no API key**).

- **Default since Sat 10 Oct 2026: `slopcore` with the Opus planner (`opus-2` = v5 prompts, 10 Oct).** Claude Opus (headless Claude
  Code on the signed-in Max plan) writes the cast, script, storyboard and cinematography; people-driven, deadpan,
  lyric-literal video where every shot acts out the line being sung (see "slopcore v4: the Opus planner" below).
  Planner fallback: Opus -> Grok script planner (v3) -> template plan, then the style fallbacks below:
  - a recurring cast (3-4 portraits), about 85 stills and 45 x 3 s `reference_to_video` clips (about 6 % of the weekly pool)
  - one gritty look per genre (pop: VHS camcorder, edm: cold + one accent, rock: 16mm doc, pop-punk: 2003 digicam date stamp)
  - subtitle (66 px, heavy outline) with a coloured keyword + at most one giant word per line (max 0.9 s, never over the
    next line); the VHS clock runs 06:37 AM -> 11:59 PM over the song; 2-3 Pip cameos; see "slopcore (v2)" below
- **Fallback chain, so a video is always made:** slopcore -> `cine-real` (v1, only if at least 26 min remain before the
  58 min hard stop) -> `mascot`. Each step reuses the lyric timings. Everything is killed at 58 min (exit 3).
- **`--style cine-real`:** the v1 photoreal video (default on 9 Oct): about 107 stills, 25 hero clips, word-by-word type.
- **`--style mascot`:** the earlier video, 14 image-to-video clips of Pip cut to the beat with captions (8 Oct).

## Daily routine usage

Once the Suno files are in the day folder (`audio.mp3`, `lyrics.txt`, `tags.json`, `stories.md`, `style.txt`,
`title.txt`), start it in the background. **No flags are needed**; the defaults are the daily settings:

```bash
nohup /home/box/suno-daily/tools/grok_video/grok_video.sh /home/box/suno-daily/<YYYY-MM-DD> \
  > /home/box/suno-daily/<YYYY-MM-DD>/grok_video.log 2>&1 &
```

**Always post the file named by `out=`** in the last log line, and send the one named by `chat=` in chat:
- normally `<day>/video_cine_real_v4.mp4` and `<day>/video_cine_real_v4_chat.mp4` (`style=slopcore planner=opus-2`; if
  Opus failed, still the `_v4` names with `planner=script-1` or `planner=template`; `--real-planner script` / `slop` give
  `video_cine_real_v3.mp4` / `_v2.mp4`)
- after a fallback to cine-real, `<day>/video_cine_real.mp4` / `_chat.mp4` (`fallback=1 slopcore_error='...' style=cine-real`)
- after a fallback to mascot, `<day>/video_grok.mp4` / `_chat.mp4` (`style=mascot fallback=1`)

- **Status line:** the last line of the log is one of these:
  - `GROK_VIDEO_STATUS=ok code=0 style=slopcore look=<look> out=<mp4> chat=<mp4> elapsed=<s> planner=opus-2 shots=.. avg_shot=.. motion=.. clips=.. pip_shots=..`
  - `GROK_VIDEO_STATUS=ok code=0 fallback=1 slopcore_error='...' style=cine-real look=<look> out=<mp4> chat=<mp4> ...`
  - `GROK_VIDEO_STATUS=ok code=0 fallback=1 slopcore_error='...' style=mascot fallback=1 cine_real_error='...' look=.. out=<mp4> ...`
    (cine-real ran and also failed), or `... code=0 style=mascot fallback=1 slopcore_error='...' out=<mp4> ...` (too late for cine-real)
  - `GROK_VIDEO_STATUS=failed code=<N> ... reason='...'`
- **Time (slopcore default, Opus planner v5 prompts):** about 21 min (stand-in dry run 9 Oct with Opus 316 s + doctor
  45 s: 1263 s; real v5 calls measured 302-353 s + 40-54 s), so from a 06:49 start the video is ready about **07:10**.
  If Opus fails fast (auth, limits), the Grok script planner runs instead (about 26 min, ready about 07:15); if Opus
  hangs to its 450 s cap first, see "slopcore v4/v5" below for the worst case. Slopcore's time limit is 34 min (generation stops at
  25 min); a slopcore failure then falls back to cine-real (if >= 26 min remain) and/or mascot, all inside the 58 min hard stop. Fallback timings: see "slopcore (v2)" below. **Older cine-real figures:** about 19 min. The hard limit is 32 min for cine-real; a fallback mascot run adds about 15 min; everything is
  killed at 58 min (`--hard-stop-min`). The routine starts grok_video at about 06:49 BST, so expect the video at about
  07:08. In the worst case (cine-real fails at its limit, then the fallback) it is done by about 07:47 at the latest.
  See "Time budget" below.
- **Allowance:** about 6 % of the SuperGrok Heavy weekly pool per day (about 107 stills at about 0.012 % each, plus 25 hero
  clips at about 0.2 % each), capped at 7.5 % by the live usage meter. The cap is relative: meter now minus the
  meter when this run started (a weekly reset during a run is handled), never an absolute meter value. Check it in the TUI: run `grok`, then `/usage`,
  then the "Usage limit" tab.

| exit code | meaning | what the routine does |
|---|---|---|
| 0 | ok (slopcore, or the cine-real / mascot fallback) | post the `out=` file, send the `chat=` file in chat |
| 6 | **the song looks instrumental** (stopped before anything was generated) | remake the song in Suno with vocals, put the new files in the day folder, run again |
| 7 | **Grok CLI not signed in** (even after one automatic refresh) | tell the owner to run `grok login --device-auth` on the box; nothing else can fix it |
| 3 | no video: slopcore failed AND the fallback chain (cine-real, mascot) failed or passed the hard stop | rerun the same command once (it resumes: plans, stills, clips are cached); if it fails again, tell the owner with the reason from `status.json` |
| 4 | lyric timing failed | rerun once; if it fails again, tell the owner |
| 5 | output failed verification | rerun once; if it fails again, tell the owner |
| 2 | bad input (missing `audio.mp3`/`lyrics.txt`) | fix the day folder and run again |

**Vocal check (exit 6).** After demucs, the vocal stem is compared with the backing stem.
- A clearly sung track passes straight away: the stem is above -8 dB vs the backing with voice in at least 50 % of the
  song. Measured: 7 Oct vocal take -2.3 dB / 92 %, 5 Oct big-room -4.0 dB / 80 %.
- Otherwise the script waits for whisper before spending any allowance.
- It stops with code 6, generating nothing, only if BOTH the stem is low (at or below -10 dB, or voice in under 40 %;
  the 7 Oct instrumental measured -14.3 dB / 30 %) AND whisper hears fewer than 25 % of the lyric words.
- If there is no stem measurement (timings reused from the karaoke pipeline), only coverage under 5 % stops it.
- An ambiguous result only adds a warning. Whisper alone is noisy: a re-run on 5 Oct heard 12 %, where the routine had
  heard 69 %.
- `--allow-instrumental` overrides the stop.

**Auth (exit 7).** `grok models` must say "logged in". If it doesn't, the script runs one cheap
`grok -p ok --max-turns 1`, which refreshes the OAuth token, and checks again.

**Throttling (mascot).** "Requests per Second" replies from the media API aren't fatal:
- All job starts pause 30/60/90/120 s plus jitter, then the shot is retried, up to 4 times per shot.
- A throttled try that produced no video doesn't use up the shot's reroll or the generation budget.
- Job starts are always at least 12 s apart.

Allowance or plan replies (quota, usage limit, upgrade, subscription) stop generation at once.

## cine-real (photoreal) style: the default
A photoreal, film-grade lyric video in the "slopcore" short-form style (see `/workspace/slopcore/analysis.md`). Pip
appears only as a 1.5 s vinyl-toy cameo before the credits.

- **Outputs:**
  - `<day>/video_cine_real.mp4`: 1080x1920 native vertical, 30 fps, H.264 High (crf 20, max 12 Mbps) + AAC,
    faststart, about 230 MB.
  - `<day>/video_cine_real_chat.mp4`: 720x1280, max 2.2 Mbps, under 50 MB.
  - Work files go to `<day>/work_cine_real/`, with `status.json`.
- **How it is built** (`cine_real.py`, `real_plan.py`, `real_gen.py`, `real_render.py`):
  1. **Look:** one bold look per song, from the genre look (`real_plan.REAL_LOOKS`):

     | genre look | cine-real look | what it is |
     |---|---|---|
     | edm (big-room, house, garage...) | `neon-accent` | cold desaturated night, Kodak Vision3 500T, halation, ONE magenta-red accent |
     | pop-video (pop, synth-pop, disco, k-pop, r&b...) | `candy-pop` | glossy candy-saturated 35mm Ektachrome: bubblegum pink, aqua, lemon, hard flash and gels, lifted blacks, light vignette |
     | rock | `vhs` | 1990s VHS camcorder, golden hour, PLAY/timecode overlay |
     | punk | `xerox` | Tri-X black and white, acid-yellow accent |
     | standard | `35mm` | Portra 400, direct flash |

     Override with `--real-look`. Each look also names three chorus worlds and the cameo scene. For example, edm goes
     warehouse rave -> festival over a city -> cosmic, and candy-pop goes candy pop-video set -> golden-hour street
     flash mob -> pink-sky dream finale.
  2. **Timeline** (`timeline.json`): one segment per sung line plus the hook, instrumental drops, the cameo and the
     credits.
     - Cuts land on lyric word onsets and on the beat grid (about half on the beat), about 1.0-1.4 s per shot,
       faster in choruses, with holds on story punchlines.
     - Up to 25 hero slots (`--real-heroes`), strongest first: the hook, long drops, chorus lines 1/3, story
       payoffs, then the other chorus and verse lines. Each hero covers 2 cuts with two windows of its clip.
  3. **Plan** (`real_plan.json`, planner `real-3`, from lyrics.txt): one text call (grok-4.7, schema, no tools).
     - 1-4 lyric-literal, meme-literate image prompts per line, with exact lens and scale, film stock, hard motivated
       light and deliberate imperfection.
     - **No text at all:** no letters, numbers, writing, signatures, receipts, documents, signs, labels, readable
       screens or logos.
     - **Original designs only:** no lookalikes of famous film/TV characters, robots (e.g. Terminator-style),
       mascots, superheroes or real people. People appear only as archetypes.
     - **Chorus variety:** each chorus is in a new, bigger world. At most one crowd shot and one raised-hands shot per
       chorus, lasers in at most a third of the images, and the rest literal, surprising pictures of the chorus words.
     - A motion line for each hero and the giant-type tokens for each line.
     - If the planner fails twice or runs out of time, a lyric-literal template plan is used.
     - The image prompts also carry the no-text / no-lookalike wording.
  4. **Generate** (`generate()`): stills and hero clips run **at the same time**.
     - Order: the Pip cameo (`image_edit` of `assets/pip_ref_9x16.png`, nothing on his head or face), then the 25 hero
       first frames, then the other stills.
     - `image_gen` 9:16 stills (`stills/sNN_k.jpg`): 4 sessions, 6 calls each, starts at least 6 s apart.
     - Heroes (`heroes/hNN.mp4`): `reference_to_video`, `--real-clip-sec` (4) s at 720p, with the still pinned as
       `first_frame`. Each starts as soon as its still exists: 4 sessions, 2 clips each, starts at least 8 s apart.
     - The usage meter is read every 90 s, and all generation stops when this run has used `--real-max-pct` (7.5 %).
     - Before starting, the hero count is trimmed to what fits under the cap (stills about 0.012 %, a 4 s clip
       about 0.2 %).
  5. **Edit and render:**
     - OpenCV draws every frame: the look grade, grain, light leaks, flashes, whips, and Ken Burns, parallax, tilt and
       handheld moves on the stills. Rendering runs in 4 parallel processes (about 4-5 min for a 2.5 min song).
     - A still is used at most twice, the second time as a punched-in cut-in.
     - Giant Anton lyric type (1-3 words at a time, word by word, from the stable-ts word timings; brand spelling from
       lyrics.txt) is burned in with libass.
     - The first word is huge on the strongest image at 0.0 s.
     - 2.5 s credits: "MADE WITH SUNO", the story @handles, "SOURCES ON X · @jxwalker".
- **Cost** (measured 8 Oct, whole-percent meter):
  - An `image_gen` still is about 0.01 % of the weekly pool (5 stills: 17 % -> 17 %).
  - A 4 s `reference_to_video` hero is under 0.25 %.
  - The test run with 91 stills, the cameo, 11 heroes and the planner took the meter from 17 % to 19 %.
  - With 25 heroes, expect about 6 % per day. The cap is `--real-max-pct` (7.5).

### Time budget (routine starts 06:37 BST; grok_video itself starts at about 06:49 once the Suno files are in)

The plan and all generation are made from `lyrics.txt` alone, so they run **while** the lyric timings are made
(demucs, whisper and stable-ts take about 10 min on the box). The real cut timeline is built from the word timings
afterwards and mapped onto the pictures by segment id (lines that Suno didn't sing give their pictures to the
neighbours).

| phase (minutes from the start) | typical | limit |
|---|---|---|
| lyric timings + vocal check, in the background | 0-10 (demucs 3.5, whisper ~9) | exit 4 if they fail |
| planner, during demucs | 0-3 (measured 159 s) | 6 min for attempt 1, 8 min in total, then the template plan |
| vocal gate | at about 3.5 | exit 6 before any generation |
| stills + 25 hero clips (overlapped) | about 4-13.5 | nothing new starts after limit - 10 min; running sessions are cut at limit - 9 min (23 min) |
| wait for timings, edit | about 13.5 | - |
| render (4 parallel parts) + join | 4.5 | aborted at the limit |
| chat copy + checks | 1 | - |
| **cine-real total** | **about 19 min** (dry run 1141 s) | **`--real-time-limit` 32 min** |
| slow API (stills 45 s, clips 150 s, planner hanging) | about 29 min (dry run 1762 s, before the planner cap), fewer clips, cut from stills | 32 min |
| mascot fallback (only if cine-real failed; reuses the timings) | 12-16 min | killed at `--hard-stop-min` 58 min from the start (exit 3) |

From a 06:49 start: video at about **07:08** normally, about 07:19 with a slow API, and in the worst case (cine-real
fails at its 32 min limit, then the fallback) about 07:37-07:47, never past 07:47 (hard stop, exit 3).

The dry runs with the stand-in Grok are in "Dry runs" below.

**Reliability.** The goal is that a video always gets made.

| failure | what happens |
|---|---|
| not signed in / instrumental / bad input / timing failure | the same exits as mascot: 7 / 6 / 2 / 4, before anything is spent (no fallback: the mascot run would hit the same wall) |
| one still or hero fails | per item: throttled or not-attempted calls are retried up to 3 times after a 20-30 s cool-down without being charged; a real failure gets one reroll |
| hero clips run out of time / fail / are corrupt | that slot cuts from its stills instead (animated); the second clip window is fitted to the clip's real length |
| stills missing | the slot borrows the nearest pictures, still at most 2 uses each. Only when there aren't enough pictures for that are some used 3 times, which adds a status warning. |
| render runs over the limit / output fails verification | the unfinished file is moved aside to `video_cine_real.failed.mp4`, then the fallback below |
| planner fails twice / runs out of time | lyric-literal template plan |
| allowance reply (quota, usage limit) or the 7.5 % usage cap | generation stops at once; the edit uses what exists, with a status warning |
| under max(12, 1/3) of the stills, a render error, a verify failure, the time limit, or any other error | **automatic fallback**: the mascot style runs in `work_grok/` (reusing this run's lyric timings) and writes `video_grok.mp4`; the exit code is the mascot's own (0 = ok). `--no-fallback` exits 3 instead. |
| a downloaded still or hero clip is corrupt | it is checked before the edit (the image must decode; the clip must decode with at least 24 frames) and treated as missing |

Resume: a rerun reuses `timeline.json`, the cached plan, every finished still or hero, and recovers media from
`gen_logs/` that a killed run made but never copied.

**Testing without spending.** These use `--skip-gen`, the time limit or a stand-in CLI, with `--work`/`--out` in a
test folder:
- `CINE_REAL_HIDE=0.4` pretends 40 % of the stills and all heroes failed.
- `CINE_REAL_FAIL=plan|gen|render` forces those failures.
- `--fallback-args "--skip-gen --clips-from <day>/work_grok/clips --work <dir> --out <file>"` keeps the fallback
  mascot run cheap and out of the day folder.
- `GROK_BIN=<fake>` swaps the CLI for a stand-in: `/workspace/grok-test/cine_real_fail/batcher/fake_grok.py`.
  - It can throttle, fail, skip or answer "usage limit" after N calls (`FAKE_QUOTA_AFTER`).
  - It can emulate API latency (`FAKE_DELAY_IMG`, `FAKE_DELAY_VID`, `FAKE_DELAY_SESSION`, `FAKE_DELAY_PLAN`).
  - It uses no network and spends nothing. Its `test_batcher.py` runs the per-item retry tests.

| option | default | meaning |
|---|---|---|
| `--style cine-real\|mascot` | cine-real | which video to make |
| `--real-look L` | auto | `auto`, `candy-pop`, `neon-accent`, `vhs`, `35mm`, `xerox` |
| `--real-images N` | 110 | max stills (planned from lyrics.txt; about 107 for a 36-line song) |
| `--real-heroes N` | 25 | max hero clips |
| `--real-clip-sec S` | 4 | hero clip length, 3-5 s |
| `--real-max-pct P` | 7.5 | stop generating once this run has used about this much of the weekly pool |
| `--real-time-limit M` | 32 (slopcore: 34) | hard limit for cine-real in minutes from the start (see the table above); `--real-deadline-min` is an old alias |
| `--hard-stop-min M` | 58 | the mascot fallback is killed past this (exit 3) |
| `--no-fallback` | off | exit 3 instead of falling back to mascot |
| `--fallback-args "..."` | '' | extra flags for the fallback mascot run (tests) |

**Switching back** to the earlier Pip video for a day: add `--style mascot`. The outputs are then `video_grok.mp4` and
`work_grok/`, as before.

A 16:9 master (1920x1080, re-framed from the same stills with landscape type) is possible but not built: Grok's media is
generated 9:16, so it would need 16:9 stills too (about +1 % per day).

## Judge, story cards and the 12 Oct changes (approved by the owner, 12 Oct 2026)
From the Opus judge of "Take It Apart" (scored 6/10; report `/workspace/grok-test/judge/2026-10-12_proposals.md`).
Backup of the code before these changes: `/home/box/suno-daily/tools/grok_video.bak_20261012_judge`.

- **P1 keep planned shots** (`slop_real.make_edit_script`): a planned shot that lands under 0.45 s after the previous
  one, or too near the end of its line, is nudged instead of dropped. The director prompt gains rules 9 (the payoff is the first clip of
  the last sung line), 10 (timing) and 11 (every robot uses D's reference; A appears only when listed).
- **P2 judge-and-reroll loop** (`judge.py`, called from `slop_real.generate_media` after generation): stills are tiled
  20 per sheet with the cast portraits, and one Opus call (low effort, max 240 s) flags off-model cast, unlisted cast,
  clones, bad hands, a person wearing another's head, mugging, a chorus crowd without the pose, and text. Up to **15**
  stills are rerolled (the prompt gets "fix: <reason>"; the original is kept as `*.orig.jpg`) and re-judged. Clips are
  judged on 3 frames each, up to **4** are rerolled and re-judged, and every clip that still fails goes into
  `work/qa_exclude.json` (its still stands in). Logs and sheets are in `work/judge/`, and the result is in `status.json` under
  `judge_loop`. Budget: it rerolls only while spent + cost <= cap - 0.8 %. Time: stills need >= 7 min and clips >= 9 min
  before the generation stop. **Fail-open:** any Opus error or timeout means the step is skipped, a warning is logged and the run goes on.
  Switches: `GV_JUDGE=0` (off), `GV_JUDGE_FAIL=opus` (test fail-open).
- **P3** the article "A" no longer pulls in cast A (`scene_prompt`); robot shots get a "stays a machine" clip prompt.
- **P4/P5** the signature gesture is a held POSE that reads in a frozen frame; the doctor rewrites stills as frozen instants.
- **P6 hold caps** (`HOLD_STILL_S` 1.2 s, `HOLD_CLIP_S` 2.0 s in `slop_real.py`): longer spans are split, and the extra
  pieces rotate in unused shots of the same line. **Outro coverage** (`slop_script`): the outro tail, the outro lines and the last
  chorus get up to 3 shots and at least one clip each (this may go a few clips over `--real-heroes`; the meter budget
  still trims). Director rule 12: the lead's gender matches the vocal in the style text.
- **P7 story cards** (`story_cards.py`, edgy daily songs only): one Opus call (low effort, about 10 s) before the
  director writes 1-2 news cards per verse section ("@handle" over a 3-6 word headline such as `B300 RENTALS UP 38%`),
  each on the lyric line that sings that story. **Every card is checked against stories.md**: handles and numbers must
  appear in it verbatim; words must be spelt as in stories.md or the lyrics, or be ticker glue (UP, NEARLY...). A card that
  fails is dropped (see `work/story_cards.json` -> `dropped`). The line-to-story map is appended to the director's
  STORIES block, so those shots show that story literally. The cards render in the `Card` ASS style (top third, boxed,
  on the line's first sung word, about 2 s) in place of that line's verse slam. Chorus slams stay as the hook words.
  Slams skip filler and -ING words (`real_render._filler_slam`). Colour code: numbers and news nouns are in the look's
  accent colour; chorus and hook words are white. Fail-open: no cards means the old verse slams. `GV_STORY_CARDS=0` turns them off.
- **Post-run judge** (`judge.post_run`, from `grok_video.finish` after a verified slopcore/cine-real video): a
  detached, niced Opus run writes `<day>/judge_<style>.md` (scores, top 5 gaps, up to 5 proposals with meter cost) and
  `<day>/judge_<style>.log`. It never blocks the run or the post, and **nothing is applied**: the owner approves. `GV_POST_JUDGE=0` turns it off.
- **Safety fix:** a `--skip-gen` run no longer starts the cine-real or mascot fallbacks (on 12 Oct a dry run that failed
  fell back and spent about 3 %).
- **Tests 12 Oct:** dry run (`--skip-gen`) OK in 430 s; 4 story cards, all passing the stories.md check. Real test
  (`/workspace/grok-test/judge/real/`, cap 1.5 %): the judge flagged 8/87 stills (mostly the old A leak), rerolled 8 and
  2 still failed and were left out; it flagged 14/48 clips, rerolled 4 and left out 10. The loop took 193 s and the meter went 14 -> 15 %
  (about 0.5 %). Fail-open was checked with `GV_JUDGE_FAIL=opus` and `GV_STORY_CARDS_FAIL=1`. The post-run judge writes its report in about 4 min.
- **Expected cost per run:** about 6.6-7.0 % (it was about 6 %): rerolls are up to 15 stills (about 0.2 %) and 4 clips (about 0.4 %),
  plus 2-4 outro clips; it is all inside the unchanged 7.5 % cap and time limits. Rollback:
  `rm -rf /home/box/suno-daily/tools/grok_video && cp -a /home/box/suno-daily/tools/grok_video.bak_20261012_judge /home/box/suno-daily/tools/grok_video`.

## Tone profiles (9 Oct 2026): the tone follows the song

`tone.py` picks a profile at the start of slopcore (`<work>/tone.json`, `tone=` in the status line):
- **edgy**: the v5 deadpan-menace prompts (`prompts/opus_*_v5.txt`) and the genre's slopcore look. **Daily folders**
  (`<YYYY-MM-DD>`, no `"special"` in tags.json) whose stories carry news sources are always edgy, with no extra call,
  so the daily path is byte-for-byte the same planner prompt as before (checked 9 Oct).
- **joyful**: bright, warm, funny, wholesome-cute (`prompts/opus_director_joyful.txt`, `opus_doctor_joyful.txt`): its
  own rules, banned list (menace, cults, judges, hospitals, anything medical/anatomical/creepy, night/rain by default,
  robot formations...) and a sunshine -> golden -> fairy-light light arc; look `sunny-pastel` (sunny glossy 35mm, pastel
  pinks, low grain, no VHS overlay). The Grok script fallback gets a joyful tone override too.
- Literal-first, hook, signature gesture, chorus escalation, payoff, identity rules, Pip rules, Grok limits and the JSON
  schema are the same in every profile. (romantic/epic: not built yet; add `prompts/opus_*_<tone>.txt`, a look in
  `tone.LOOK` and the name in `tone.PROFILES`.)
- How it is chosen: `tone.txt` in the folder wins (first word = profile, the rest is a note passed to the director as
  `{{TONE_NOTE}}`); else a daily news song = edgy; else a short Opus call (about 6-20 s; a daily song only leaves edgy if
  Opus says it is clearly personal); if that fails, daily = edgy, other folders = a style.txt keyword guess.
- **Credits for non-daily folders:** `credits.txt` (one row per line, up to 6) replaces the end-card rows and drops the
  "SOURCES ON X · @jxwalker" footer; with no source rows at all the footer is dropped too. Undated folders get no date on
  the VHS/datestamp overlay.

## slopcore v4/v5: the Opus planner (default inside slopcore since Sat 10 Oct 2026)

**v5 prompts (planner `opus-2`, default from 10 Oct):** after an Opus self-review of v4 (critique + rewrite, 9 Oct,
`/workspace/grok-test/opus_selfreview.md`) the director and doctor prompts live in `prompts/opus_director_v5.txt` and
`prompts/opus_doctor_v5.txt` (`{{PLACEHOLDER}}` templates filled by `opus_prompt()` / `doctor_prompt()`). Tone: deadpan
menace (headlines as ceremony/parade/tribunal/takeover, scale, night, formations; banned twee props and sitcom mugging);
a hook that is the most extreme image; A performs to the lens; one copyable signature gesture across hook, choruses and
end; chorus repeats rhyme but change place; shot-size quotas; morning-to-night light arc; literal-first and
anti-repetition caps; the doctor scores twee/prop-holding shots 3 and keeps cast forms and callbacks. A 4th reference
sheet (donaldjewkes) is read. **`OPUS_PROMPTS=v4`** restores the old built-in prompts (planner `opus-1`).
Same pass also changed: the vhs-camcorder look no longer forces golden hour (energy now "euphoric and ominous"), bigger
subtitle, shorter slams, running VHS clock (`real_render.build_ass_sparse`, `slop_plan.SLOP_LOOKS`).
Backups of the pre-v5 code, prompts and README: `/workspace/grok-test/backups_20261009/`.

`slop_opus.py` (planner `opus-2`, or `opus-1` with the v4 prompts, `--real-planner opus`, the default) has Claude Opus write the whole video plan.
- **How it runs:** `claude -p ... --model opus --output-format json --json-schema <schema> --no-session-persistence`
  (Claude Code CLI, `CLAUDE_BIN` overrides the path), authenticated from `~/.claude_oauth_token` passed only in the
  subprocess environment (never printed or logged). Working files in `<work>/opus/` (prompt.txt, reply_main.txt,
  doctor.txt, ref1-3.jpg).
- **Inputs:** lyrics with word onsets (when timings are cached), stories.md, style.txt and the look, the slopcore notes
  (vibe.md, analysis.md) and 3 reference contact sheets it reads as images; Pip rules (2 scenes + the final cameo,
  nothing on his head or face) and the Grok limits (stills, 3 s r2v clips, no text, no real people or logos).
- **Output (strict JSON):** cast bible (A + up to B, C, D; anyone seen in more than one shot must be a lettered cast
  member, so the same face is edited from the same portrait), one beat per line (meaning, the literal gag), 1-3 shots
  each with the word it cuts on, prompt, framing, lens, light, move, motion, camera, edit note and clip/still; the
  final line and outro pay off the hook. Converted to the same plan the v3 generator and line-locked edit use.
- **Call 2, the script doctor** (Opus, no tools): scores every shot on "does it act out the sung words?" and rewrites
  anything under 4.
- **Caps / robustness:** main call 450 s (v5 measured 302-353 s), doctor 150 s, whole planner 600 s; an invalid reply gets one repair call;
  any Claude failure (not logged in, rate limit, timeout, bad JSON) falls back to the Grok script planner below, then
  the template plan. The status line's `planner=` says which ran; status.json/real_plan.json keep `opus_meta`
  (seconds, turns, `total_cost_usd`) and `opus_error`.
- **Measured 9 Oct (real):** Opus 258 s + doctor 27 s = 285 s; notional $0.78 + $0.19 (on the Max plan this is
  subscription usage, about 1 call a day: far inside the limits); 40 beats, 83 shots, 2 rewritten; generation 5 % of
  the Grok weekly pool (37 -> 42 %). Outputs `video_cine_real_v4*.mp4` and `work_cine_real_v4/script.md`.
- **Test without Opus:** `CLAUDE_BIN=<stub>` (see `/workspace/grok-test/opusdef/fake_claude.py`); `CINE_REAL_FAIL=opus`
  forces the fallback to the Grok script planner.

## slopcore v3: the Grok script planner (now the first fallback of the Opus planner)

`slop_script.py` (planner `script-1`, `--real-planner script`) replaced the v2 cast/mood planner; `--real-planner slop`
brings v2 back.
- **Call 1, the script** (cap 570 s for the first attempt): for every sung line a beat = the exact line, what it means
  (the story from stories.md), ONE literal, funny, instantly readable visual acted out by the recurring cast, split into
  1-3 shots that each start on a sung word (shot 1 on word 0 = the main gag; later shots on the key noun/verb/number).
  Chorus lines keep one idea that escalates on every repeat (A and a few people -> the whole office -> a stadium).
  Each shot carries a self-score 1-5.
- **Call 2, the critic** (cap 200 s, only with time left): scores every shot 1-5 on "would a viewer with the sound off,
  reading the subtitle, connect this picture to the line?" and rewrites anything under 4. The whole planner is capped
  at 780 s (a failed script falls back to the template plan; a failed review keeps the self-scores).
- **`<work>/script.md`**: the readable script with meaning, visual, shots, word, clip yes/no, self/critic/final scores
  and the rewrites.
- **Clips** (45): the first shot of every line, then the hook and drops, then second shots of choruses #1-2 and verses.
- **Edit** (`make_edit_script`): each line uses ONLY its own shots. Shot k cuts in on its word's onset (from the timings;
  estimated from the line's position if missing); beat cuts inside a shot are alternate takes of the same shot (the clip
  continuing, punched in, then its still), then the line's other shots. A Pip toy shot sits on its own line (splitting
  its longest shot). Only a line whose pictures all failed borrows the nearest line's (logged in status.json
  `script_edit.borrowed_segments`).
- Measured 9 Oct (real): script 477 s + critic 181 s = 658 s, 80 shots, critic >= 4: 91 % before rewrites; generation
  6 % of the weekly pool (3 cast, 82 stills, 48 clips); every cut on its own line. Outputs `video_cine_real_v3*.mp4`.

## slopcore (v2) style: the default since Sat 10 Oct 2026 (now with the v4 Opus planner above)

No flags needed (`--style slopcore` is the default). `--style cine-real` runs v1; `--no-cine-fallback` skips the cine-real
step of the fallback chain. The cine-real fallback gets `--hard-stop-min` = minutes left, `--real-time-limit` = min(32,
left - 11) and the unspent part of the cap (at least 2.5 %); forced test failures (`CINE_REAL_FAIL`) hit only the first
style unless `CINE_REAL_FAIL_ALL=1`.
Writes `video_cine_real_v2.mp4` + `video_cine_real_v2_chat.mp4` and `work_cine_real_v2/`; never touches v1/posted files.

- Vibe brief: `/workspace/slopcore/vibe.md`. Planner `slop_plan.py` (version slop-1, caps 420 s / 540 s):
  a recurring cast (A/B/C), deadpan people literally acting the lyrics in mundane places, escalating; no still-life, no text in images.
- One gritty look per song (`SLOP_LOOKS`): pop -> `vhs-camcorder` (PLAY/timecode/date overlay), edm -> `cold-accent`,
  rock -> `16mm-doc`, punk -> `digicam-2003` (datestamp). Genre changes energy, not gloss.
- Media (`slop_real.py`): 3 cast portraits first, then cast scenes as `image_edit` from the portraits; ~95 stills,
  45 x 3 s (default; was 55 in the 9 Oct test) `reference_to_video` clips (`--real-heroes`, `--real-clip-sec`, `--real-images` override).
  Edit is motion-first (~1.1 s shots); stills only as filler with handheld shake/push.
- Pip: 2 planned cameos + end cameo, always `image_edit` from the locked `PIP_REF` plus a "toy stays still" clip;
  any planner image mentioning the toy is converted to this path.
- Type (`build_ass_sparse`): small bottom subtitle with accent words in the look colour + at most ONE giant Anton slam per line
  (chorus/intro/outro and verse punchlines, >=1.8 s apart); 2.5 s credits card.
- Edit: a still is used at most twice; then cuts borrow other clip windows. Punched-in shots keep heads in frame.
  QA blocklist: `work_cine_real_v2/qa_exclude.json` (e.g. `["s23_1.jpg"]`) drops bad stills/clips; re-render at zero cost with
  `--skip-gen --real-reuse-plan` (reuses an older-version plan and existing media).
- Planner slop-2: protagonist always mid-action and off-centre (<=1 in 6 lens stares), deadpan escalation, 30-55-word prompts.
- Cost/time (9 Oct test, As Fast As Ideas): 3 cast + 82 stills + 54/55 clips = ~7% of the weekly pool;
  generation ~12 min, render ~5.3 min, run 1128 s + planner 365 s (overlaps demucs in the routine) -> done ~07:14.
  Default now 45 clips (about 6 %/day). Same safeguards: generation stops at time limit - 9 min, fallback, hard stop, status line
  (extra fields `motion= clips= pip_shots=`).

## Options (both styles; the clip options are for `--style mascot`)
| option | default | meaning |
|---|---|---|
| `--look L` | auto | `auto`, `edm`, `rock`, `punk`, `pop-video` (`pop` is an alias), or `standard` (the original gig-style trial look: boxed captions, slower cuts, no grade) |
| `--clips N` | 14 | number of shots to plan and generate |
| `--gen-budget G` | N+3 | max generations this run (one reroll per failed clip, inside this cap) |
| `--skip-gen` | off | no Grok calls: reuse clips from `--clips-from DIR` (or `work_grok/clips`); DIR may hold a `shots.json`, otherwise clips are treated as generic |
| `--clips-from DIR` | `work_grok/clips` | clip folder for `--skip-gen` |
| `--out FILE` / `--work DIR` | `<day>/video_grok.mp4` / `<day>/work_grok` | write elsewhere (tests) |
| `--plan-only` | off | only run the shot-list planner (one cheap text call) |
| `--parallel 4` | 4 | concurrent generation jobs |
| `--whisper-model medium` | medium | model for the lyric alignment steps |
| `--min-clips K` | max(4, N/2) | fail (exit 3) below this many good clips |
| `--allow-instrumental` | off | don't stop on an instrumental-looking song |
| `--no-chat-copy` | off | skip the 720p chat copy |

## Looks (`looks.py`, mascot style; the genre look also picks the cine-real look)
Every genre look keeps the same recipe:
- a named camera move per shot
- an outfit change per section (jackets open, so Pip's chest heart stays visible)
- choreography or performance, with a crew of chrome robots without bunny ears so Pip stands out
- all chorus shots share one hero set with matching moves
- verse shots are **story shots** (see "Story-driven, cinematic shots" below); choruses are genre performance
- Pip's core look is restated in every planner and clip prompt
- a beat-synced edit: punchy choruses with flashes, slow-mo and whips; verse story shots hold 3-5 s inside
  letterbox bars
- bold pop-up captions (the sung word lights up, chorus in caps)
- a colour grade

The look changes the world, the rhythm and the grade:

| look | world | edit | grade / caption accent |
|---|---|---|---|
| `edm` | festival mainstage at night: lasers, CO2, pyro, LED walls, crowd silhouettes with flags; Pip as DJ or hype MC at the decks and on the catwalk; drops land on confetti and laser hits | 2 bars before each drop cut every 2 beats, then every beat (build-up); flash plus strobe on each drop | punchy, saturated, slightly cool; cyan / yellow |
| `rock` | stadium rock show: pyro columns, smoke, lighters and phone torches, guitar-hero poses, knee slides, solo on a riser, backlit silhouettes, leather jacket | 2-6 beats in choruses, flash into choruses, speed-up into them, light handheld shake on some chorus shots | warmer and more contrasty; orange / red |
| `punk` | sweaty club, then garage, skatepark and backyard party: stage dives, mosh pit of small round robots, skate ramp | fastest cuts, handheld shake, some fisheye shots, whips | lightly washed-out film look with grain; yellow / lime |
| `pop-video` | glossy neon, chrome, mirror and LED sets, choreography with backup dancers, confetti, wind machines | 2-5 beats in choruses, flash, speed-up, slow-mo, whips, punch-ins | contrast 1.07, saturation 1.22, soft vignette; yellow / pink |

`shots.json` records `look`, `outfit` and `camera`; a cached plan with a different look, or from an older planner
version (`plan_gen.PLANNER_VERSION`, now `cine-4`), is re-planned. Effect counts are
logged as `edit fx (<look>): {...}` and saved in `status.json` (`edit_fx`).

## Story-driven, cinematic shots (`cine.py`, mascot style)
**Slots.** `story_slots()` maps shots to the song before planning: an intro shot; per story an *establishing* and a
*payoff* shot (the story's sung lines split in half; one shot if the count is short); chorus shots spread over the
choruses; an outro shot if there's room. Each slot carries its exact lyric lines (`line_refs`) and, when caption
timings are already available (`work/timings.json` or `align/timings.json`, fresher than the audio), its time
`window`; otherwise section order is used. 14 clips on a 5-story song = intro, 2 per story, 3 chorus shots.
Saved as `slots.json` next to `shots.json`.

**Story shots** depict the story literally (who, what, the number) with Pip acting it out, in the story's own world
tinted by the look: e.g. a colossal chonky robot in a blue cape ringed with gold stars stomping down an avenue for a
"Le Chonk" model launch. Brands are suggested only by colour and shape (no real logos, no readable fake text); at
most one short physical number (<= 4 characters, e.g. "722", "0") when it renders cleanly. Software shows up as giant
floating screens / app panels (never "windows", which render as building windows); AI assistants appear as a small
symbol-shaped character in the brand colour (e.g. a faceless coral starburst sparkle, not a creature) acting with
Pip, in a stylised workspace rather than a fantasy landscape. Pip's motion avoids "looks at"-type verbs so the eyes
stay closed arcs. Story shots have no band or stage, and
Pip wears body-only styling (nothing on the head or across the face screen). Establishing = the
situation; payoff = the result or punchline.

**Chorus shots** stay genre performance on the shared hero set, shot as cinema.

**Every shot** has `shot_type`, `lens` (anamorphic 2.39 feel inside 9:16, shallow depth of field, rack focus),
motivated `lighting`, `atmosphere`, ONE `camera` move and a `motion` beat sheet (`0-3 s / 3-7 s / 7-10 s`) used as the
image_to_video prompt. The image_edit still is composed as a movie frame with a filmic grade; Pip's core look
(stubby legs and round feet, visible chest heart, closed arc eyes, bunny ears) is restated in both steps.

**Edit.** During a story's lines the cut uses that shot (lyric line -> `line_refs`); repeats of the same shot are
cut-ins/cut-outs (1.14x / 1.0x) to a later moment of the clip. Verse holds are 3-5 s, whips only when the story
changes, letterbox bars (96 px) only on verse/bridge shots (captions sit inside), fisheye only in choruses.

## What it does (mascot style)
1. **Plan** (`plan_gen.py` + `cine.py`): one headless `grok -p` text call (grok-4.7, `--effort low`,
   `--json-schema`, all tools disabled, about 2-3 min) writes `shots.json`. If the planner fails twice, a built-in template plan is used.
2. **Lyric timings and vocal check** start in the background at the same time: demucs vocal stem, vocal check, then
   faster-whisper, sung-line selection, stable-ts alignment of lyrics.txt and whisper-checked repair. This uses
   `tools/lib` read-only on a *copy* of the day files. `align/sync_report.json` gives the share of words within 0.3 s.
   Caption words are the lyrics.txt tokens, so brand names are spelled exactly as written.
3. **Generate**: per shot, one headless run (`--always-approve`, absolute `--prompt-file`, web, shell, image_gen and
   reference_to_video disabled) doing exactly one `image_edit` from `assets/pip_ref_9x16.png` and one `image_to_video`
   (10 s, 720p). Clip paths are read from the streaming-json tool results and copied to `work_grok/clips/clipNN.mp4`
   (plus a keyframe). Logs go to `gen_logs/shotNN_tryK_HHMMSS.ndjson`.
4. **Edit** (`assemble.py`):
   - Beat and downbeat grid from librosa. If librosa locks to half time (it gets about 89 BPM on 172 BPM pop-punk),
     the grid is doubled using the BPM in style.txt.
   - Forced cuts at section starts and at the end card; look-specific cut lengths and effects.
   - Each cut takes the highest-motion window of the best clip for that moment (the story's clip during its lines,
     chorus clips in choruses), spreading use across clips.
   - Letterbox bands are cropped, and the frame is upscaled with lanczos to 1080x1920.
5. **Overlay** (`captions.py`, ASS): lyric captions, the story topic pill at the top, a title card, the end card
   ("Made with Suno" pill and "Sources on X" card with each story's @handle) and the `@jxwalker` footer.
6. **Render and verify**: final encode with the untouched song audio, then checks (1080x1920, H.264 High yuv420p, AAC,
   duration within 0.15 s of the song, faststart, under 512 MB), review frames in `work_grok/frames/`, then the chat copy.

## Tests without generating anything (mascot style; for cine-real see "Testing without spending" above)
```bash
# planner only (one cheap text call), auto look
grok_video.sh /home/box/suno-daily/2026-10-05 --style mascot --plan-only --work /workspace/grok-test/edm_test/plan \
  --out /workspace/grok-test/edm_test/plan/unused.mp4
# edit/assemble on existing clips
grok_video.sh /home/box/suno-daily/2026-10-05 --style mascot --skip-gen --look edm --clips-from /workspace/grok-test/edm_test/clips \
  --work /workspace/grok-test/edm_test/work --out /workspace/grok-test/edm_test/video_edm_test.mp4
```

## Known limits
* Grok clips are 720p/24 fps (upscaled) and 6 or 10 s long. On-model drift happens (open eyes, longer legs, garbled
  background lettering), and there's no automatic quality filter, so skim `work_grok/frames/` and `clips/*-keyframe.jpg`.
* Lines with no whisper evidence are spread evenly (see the `timing` column in `align/timings.tsv`).
* Big-room drops are taken to be the choruses (the sung hooks). A purely instrumental drop with no lyrics gets no
  build-up treatment.

### Special folders: cast_refs, Messenger copy, gore ban, --audio (9 Oct 2026)
- `cast_refs.json` (non-daily folders only): letters -> {name, role, description, images}; cast portraits are made by
  image-edit from the real photos (consented, private). Daily folders ignore it and keep the no-real-people rule.
- Every non-daily video also gets `*_messenger.mp4` (H.264 720x1280, AAC 128k, faststart, < 24 MB, bitrate fitted).
- Joyful profile: no blood, red liquid, organs or medical gore; an organ in the lyrics is only a cute sparkly plush
  heart / VIP-badge character or an abstract glowing heart (director, doctor, script tone block, look + every clip prompt).
- `--audio FILE` uses another audio file instead of `<day>/audio.mp3` (re-aligns automatically).
- Non-daily: planned DROP scenes are placed in a line's instrumental tail (>= 1.2 s) when the timeline has no
  separate instrumental segment (`drops: placed ...` in the log).

### Tone `playful` (9 Oct 2026, 22:19)
- Between edgy and joyful; the automatic pick for personal/happy songs (Opus chooses only edgy|playful; `joyful` only via
  `tone.txt`). Prompts `prompts/opus_{director,doctor}_playful.txt`; look `sunlit-portra` (35mm, warm Portra, real-world
  colour, one red accent). Mixed expressions (laughing <= ~30%), varied light, no pastel/candy/glitter overload, same gore ban.
- Messenger copy cap is now 18 MB (MESSENGER_MAX_BYTES) for special folders.

## Narrative mode (13 Oct 2026, test; not yet the daily default)
the owner: "random words thrown up on the screen ... a musical narrative with visual storytelling". Song and film are
written together by Opus: `python narrative.py write <day> [--out DIR]` picks ONE main story from stories.md, writes a
treatment (protagonist/want/obstacle/turn/payoff, 3-4 locations, escalating chorus motif, final image, sourced facts),
then lyrics.txt / style.txt / title.txt (lyrics_lint clean, identical chorus, title in chorus; one repair call) and
storyboard_draft.md + treatment.json/.md. When `<day>/treatment.json` exists, grok_video's slopcore Opus planner uses
prompts/opus_director_narrative.txt + opus_doctor_narrative.txt (treatment as the script, <=66 shots), story cards
and word slams/subtitles are off, and the type is: title card in the hook, the chorus hook line (same style every
repeat), diegetic text from beats' "onscreen" (spell-checked against the day's own words; misspelt ones dropped), credits.
Looks, Pip, judge/reroll, fallbacks and the 7.5 % cap are unchanged. `NARRATIVE_OFF=1` ignores treatment.json.
Karaoke: tools/build_video.sh now exits 0 (KARAOKE_SKIPPED) for plain YYYY-MM-DD folders unless `--karaoke`.

## Headline mode (13 Oct 2026, the owner-approved plan; test)
`python headline.py write <day> [--out DIR]` -> lyrics.txt/style.txt/title.txt + headline.json/.md, tags.json
`sources` = sung stories' handles only. Structure: hook (headline gag + title) / Verse 1 main story literal / identical
chorus with wordplay / Verse 2 2-3 secondary stories / bridge with Suno meta-tag surprise / final chorus one-word
callback / outro punchline. Opus ranks stories, writes 3 hook options, self-scores lyrics (clarity, wordplay,
catchiness >= 8; up to 2 rewrites), ticker lines verified against stories.md. `<day>/headline.json` takes precedence over
treatment.json (narrative mode kept, unused): prompts/opus_*_headline.txt, no story cards/slams; type = title (0-3 s),
one headline card on the main story's first line, chorus hook line as sung, bottom news ticker per story span (switches
on the line where the story changes). `HEADLINE_OFF=1` ignores it. Also 13 Oct: cast lists pruned to letters named in
the prompt (slop_opus.fix_cast); hold-cap splits borrow neighbouring lines' shots; judge prompt is mode-aware and adds
a sound-off test in headline mode. Dry run: 2026-10-13-headline/dryrun/.

## Claudia mode (19 Oct 2026, the owner-approved; default in headline mode)
Modelled on @anabology's Claudia pipeline (claudia.gallery/wiki/pipeline). Code: `claudia.py`, wired in
`slop_real.prepare_claudia` / `generate_media` / `edit_and_render_claudia`, plus a likeness line in `judge.realism_gate`.
Off switch: `GV_CLAUDIA=0` (back to the 14-18 Oct headline pipeline). Rollback: every touched file has a
`.bak-20261019-claudia` copy.
1. **Pacing:** `claudia.scenes()` = one scene per verse couplet (4-8 s), one per chorus/bridge line (1-2 quick shots),
   hook 1-2, outro tail 1; 25-40 shots total; every shot is a moving clip (3-6 s, set per shot).
2. **One lead:** the prompt book fixes cast A's reference sheet (name, age, face, hair, build, wardrobe, palette) + at
   most B, C. `castA` is rendered as a plain reference-sheet portrait, Opus approves it (`lead_approval.json`, one
   reroll) before any batch; stills are image_edit from it and every clip with A passes it as a reference image
   (reference-to-video). The realism gate rejects off-model lead stills.
3. **Prompt book:** ONE Opus call writes every paid prompt (`prompts/claudia_book.txt`): first-frame prompt, timestamped
   motion/blocking, camera, lens, light, type zone per scene; an Opus producer review (`prompts/claudia_review.txt`)
   applies fixes before any spend. Output: `work/prompt_book.md` + `.json`. After the clips, Opus picks each clip's
   usable in/out window from 0.5 s frame strips (`work/windows.json`); the edit plays only that window, at 1x.
4. **Typography:** `claudia.build_ass` (libass, code, free): lyric lines in the scene's negative-space zone, Inter Tight
   with Instrument Serif italic accents (hook words, numbers), each word revealed on its sung onset; a slim synced
   "via @handle" tag bottom-left replaces the scrolling ticker; a serif headline card before the first sung line; the
   existing end card (MADE WITH SUNO + handles) is copied unchanged.
5. **Look:** `clean-film` (soft motivated light, no flash, no VHS/datestamp, no handheld shake on stills), then
   `claudia.grade()` applies a soft-film 3D LUT (`work/claudia_soft_film.cube`) in ffmpeg.
Budget: unchanged 7.5 % cap (live meter); the estimate uses the mean planned clip length.
Test without spending: `grok_video.sh <day> --style slopcore --plan-only --skip-gen --work <abs path>`.

## Cine vocab (19 Oct 2026, from the owner's "reference -> language -> prompt -> polish" list)
- `prompts/cine_vocab.md`: 60 named shot types / lenses / lights / camera moves with Grok-ready phrases, plus 17 film
  reference archetypes (ARCH-*). Injected into `claudia_book.txt` via `{{VOCAB}}`.
- Book schema adds per shot `ref` (ARCH id or real film frame), `shot_type`, `move` (exactly one vocab move id).
  `claudia.cine_lint()` (deterministic, after the book and after the review) strips filler words ("cinematic, 4k,
  beautiful..."), normalises/infers the move, caps CRASH/WHIP at 2 and DOLLYZOOM at 1, flags missing ref/light/lens.
  `_plain()` drops vocab ids before text reaches Grok; the ARCH palette rides as "Colour:" only when a section has
  no palette. The review prompt rejects generic shots and shots with no named move or light.
- `GV_CINE=0` -> uses the `*.bak-20261019-cinevocab` book/review prompts and skips the lint (pre-vocab behaviour).
- `GV_POLISH=1` (default OFF) -> grade adds faint halation (highlights blurred, warmed, screened 18%) + fine temporal
  grain in the same ffmpeg pass as the LUT; ~+45 s on a 2:29 video. Off until judged on a real Claudia render.
- Fixed: `plan(reuse=True)` never reused the book (json lists vs tuples in `_key`); now compares as lists.
- Full rollback: `cd tools/grok_video && for f in claudia.py README.md prompts/claudia_book.txt prompts/claudia_review.txt; do cp -p $f.bak-20261019-cinevocab $f; done`

## Story grounding + story text (19 Oct 2026 evening, the owner: "more of the underlying story in the visuals and the text")
- `prompts/claudia_book.txt` rules 12-13: >=80% of shots depict a specific element of the story their lyric sings
  (`story`, `story_element` per shot, recorded in prompt_book.md); each secondary story gets its own identifiable scene;
  generic office/mood shots banned. Scene rows passed to Opus carry the story number of each lyric line.
- `prompts/claudia_review.txt`: STORY GROUNDING check (rewrites generic shots), sees stories.md.
- `claudia.story_grounding()` logs coverage per story; `claudia.story_text()` verifies Opus's card / secondary captions /
  hook fact word by word against stories.md (falls back to the stories.md headings, else drops). Never invents.
- `claudia.build_ass(..., story=)`: opening card = plain headline + "via @handle"; "ALSO TODAY" caption box when each
  secondary story is first sung; "THE STORY" key fact at the first chorus; placed opposite the lyric zone, <=8 words.
- Off switch: `GV_STORY_TEXT=0` (text layer only). Rollback of everything: the `.bak-20261019-story` copies.

## Default since 23 Oct 2026: no stills + energy-matched pacing
- Every scene gets a motion and becomes a Grok clip (--clips default 14). A scene with no clip falls back to an animated line_card graphic, never a still image.
- pace() splits shots on the detected beat grid: 2 beats in chorus/chant/hook/intro/outro, 3 in verse/pre, 4 in breakdown/bridge, and never holds longer than GV_KARAOKE_MAX_HOLD (2.5 s). Long clips are re-cut at offsets with alternating zoom.
- At most 2 stamps (STAMP_MAX). No story banner. Status records stills_used, max_hold and bpm.
