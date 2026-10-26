# Zero Day Disco pipeline

A daily AI-news song and karaoke music video, made end to end by agents and posted to X, TikTok and YouTube Shorts.

> Licence: MIT (placeholder, pending owner confirmation). Inspired by *Claudia* by @anabology (claudia.gallery).

## What it does
1. **Story pick + lyrics** – `headline_day.sh` / `grok_video/headline.py` pick one main AI-news story from X, write a
   viral-hit-format song (hook first), and run it through `songcraft.py` review rounds.
2. **Lyric lint** – `lyrics_lint.py`, `lyric_metrics.py`, `style_lint.py` enforce `LYRICS_RULES.md`
   (density per BPM, hook placement, chorus variety, genre rotation).
3. **Song** – generated in Suno; the mp3 + lyrics land in a day folder (`YYYY-MM-DD/`).
4. **Alignment** – `lib/` (demucs stems + whisper alignment, timings, ASS subtitles).
5. **Video (karaoke v3)** – `grok_video/karaoke.py` plans a narrative storyboard (`storyboard.py`, prompts in
   `grok_video/prompts/`), then fills shots from three sources:
   - **Grok Imagine** stills / clips,
   - **LTX** b-roll on a local ComfyUI box (`local_gen/`),
   - **Runway** hero shots from producer-grade shot sheets that must score ≥ 7 (`prompts/runway_shot.txt`, `runway_hero_runbook.md`).
   Graphics layers: `kgfx*.py`, `klyrics.py`, `design.py` ("Acid Deadpan" house style).
6. **Strict QC** – `local_gen/strict_qc.py` + `clip_qc.py`: frames every 0.25 s, two vision reviewers, FAIL vs WARN
   severity (bent/melting props, prints on clothes, extra hands, mirrored text, eyewear glitches, wardrobe swaps), then a
   whole-cut review at 2 fps. Nothing posts unless QC passes.
7. **Posting** – `post_lint.py` → `x_post.py` (main post + video), `x_source_reply.py` (sources reply),
   `postiz_upload.sh` (TikTok / YouTube Shorts via Postiz).

Detailed operating notes: `docs/OPERATIONS.md`, `grok_video/README.md`, `local_gen/README.md`.

## Setup
- Python 3.10+, ffmpeg, `requests`; a venv with whisperx + demucs for alignment (`PY`, `DEMUCS`).
- `grok` CLI (Grok Imagine + QC reviewer) and `claude` CLI (writer/director, second reviewer).
- Optional: ComfyUI with LTX-Video on a GPU host (`local_gen/comfy_spark.sh`, `extra_model_paths.yaml`).
- Accounts: Suno, X API (OAuth 1.0a read-write), Postiz, Runway.
- `cp config.example.env config.env`, fill in, then `set -a; . ./config.env; set +a`.

Note: some scripts still assume the original layout (`/home/box/suno-daily/<day>`); set paths on the command line.

## Environment variables
Secrets: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`, `POSTIZ_API_KEY`, `PIPELINE_SECRETS_FILE`.
Hosts: `LOCAL_GEN_SERVER`, `COMFY_BIND`, `SPARK_SSH`, `SPARK_SSH_KEY`. Tools: `GROK_BIN`, `CLAUDE_BIN`, `PY`, `DEMUCS`.
QC: `QC_STEP`, `QC_CUT_FPS`, `QC_GROK_MODEL`, `QC_PAR`, `QC_LOG`. Many `GV_*` / `HL_*` feature switches are documented
inline where they are read. See `config.example.env`.

## Versioning
Semantic versions in `VERSION`, tagged `vX.Y.Z`. See `CHANGELOG.md`.
