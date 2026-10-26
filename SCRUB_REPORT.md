# Scrub report — public release prep (2026-10-26)

Source: `/home/box/suno-daily/tools` (read-only copy). Secret values are never shown here.

## Excluded entirely
- Day folders (`20??-??-??*`), `grok_video/work_live/` (runtime status), `__pycache__/`, venvs
- Media: all mp4/png/jpg/wav/mp3, incl. `grok_video/assets/pip_ref_9x16.png` (Pip mascot reference image)
- `build_video_invocations.log` and all `*.log`
- `tiktok_backlog.tsv` (post backlog / schedule data)
- 257 backup files (`*.bak*`, `grok_video.bak_20261012_judge/`, `grok_video/bak-20261014-norobot/`) — used only to rebuild git history, not shipped as files

## Replaced (counts in the final tree; the same rules were applied to every historical commit)
| category | count | files | replacement |
|---|---|---|---|
| Tailscale IP of the Spark host (100.x) | 10 | local_gen/README.md, local_gen/local_gen.py, local_gen/comfy_spark.sh, grok_video/karaoke.py, grok_video/prompts/runway_hero_runbook.md | `$SPARK_HOST` / `$SPARK_SSH` in docs; `localhost:8188`, `127.0.0.1`, `os.environ['SPARK_SSH']` in code |
| SSH key path + user@host | 4 | local_gen/README.md, grok_video/karaoke.py | `$SPARK_SSH_KEY` (code reads `SPARK_SSH_KEY`, default `~/.ssh/id_ed25519`) |
| Hostnames (Spark host name) | 2 | local_gen/README.md, local_gen/comfy_spark.sh | "the Spark host" |
| Local secrets-file path | 3 | x_post.py, README (now docs/OPERATIONS.md) | `PIPELINE_SECRETS_FILE` env var |
| Private company reference | 2 | grok_video/prompts/claudia_book.txt, karaoke_plan.txt | removed from the banned-props list |
| Owner's first name in comments/prompts | 138 | 43 files (rules notes like "James: …") | "the owner" |
| Family / friend names (Emma, Clare, Josh, Julian) | 0 | — | none found |
| Phone numbers, personal emails, LAN 192.168.x, banking | 0 | — | none found |
| API keys / tokens / passwords | 0 values present | — | code only reads env var names (X_*, POSTIZ_API_KEY) |

## Scans
- gitleaks 8.21.2 over the full git history (65 commits): **no leaks found**.
- rg sweep of `git log -p --all` for emails, 100.x / 192.168.x IPs, ssh key names, `/home/<user>`, drive links, token prefixes (sk-/xai-/ghp_/tskey), names, phone, bank/address: clean except the items under "Needs a call".
- All `.py` files compile; shell scripts pass `bash -n`.

## Needs James's call
1. **@jxwalker** handle remains (X handle in post/footer defaults and docs). It's public, and the repo would sit on the same account. Keep?
2. **`/home/box/...` paths** (57 mentions in history: default paths for venvs, grok CLI, pipeline root). Generic box user, nothing personal; left so scripts keep working. Could parameterise later.
3. **Owner rule history in comments** (e.g. quotes like "auto tuned garbage", "Max plan", "make sure we always follow the viral hit format", a Messenger size note). Names are gone but the quotes remain. Fine to publish?
4. **`cast_refs` feature** (code + docs for consented private real-person videos): no photos included, only the code path. Keep or strip?
5. **Licence**: MIT placeholder, copyright "James Walker". Confirm.
6. **Author identity**: `James Walker <4061653+jxwalker@users.noreply.github.com>` (GitHub user `jxwalker`, id 4061653, assumed to be his). Confirm.
7. **History accuracy**: backup mtimes were reset by a 23 Oct folder copy, so same-day commit order and times are approximate; 4 undated lib backups are dated 2026-10-09 ("undated-…"). Files without a backup appear from the first commit.
8. **Repo name**: suggested `zero-day-disco-pipeline`.

## Tree and size
```
LYRICS_RULES.md
build_video.sh
docs/OPERATIONS.md
grok_video/README.md
grok_video/assemble.py
grok_video/captions.py
grok_video/cine.py
grok_video/cine_real.py
grok_video/claudia.py
grok_video/common_gv.py
grok_video/design.py
grok_video/grok_video.py
grok_video/grok_video.sh
grok_video/headline.py
grok_video/judge.py
grok_video/karaoke.py
grok_video/kgfx.py
grok_video/kgfx2.py
grok_video/kgfx_base.py
grok_video/klyrics.py
grok_video/looks.py
grok_video/margin_check.py
grok_video/narrative.py
grok_video/plan_gen.py
grok_video/prompts/cine_vocab.md
grok_video/prompts/claudia_book.txt
grok_video/prompts/claudia_review.txt
grok_video/prompts/headline_writer.txt
grok_video/prompts/karaoke_plan.txt
grok_video/prompts/narrative_writer.txt
grok_video/prompts/opus_director_headline.txt
grok_video/prompts/opus_director_joyful.txt
grok_video/prompts/opus_director_narrative.txt
grok_video/prompts/opus_director_playful.txt
grok_video/prompts/opus_director_v5.txt
grok_video/prompts/opus_doctor_headline.txt
grok_video/prompts/opus_doctor_joyful.txt
grok_video/prompts/opus_doctor_narrative.txt
grok_video/prompts/opus_doctor_playful.txt
grok_video/prompts/opus_doctor_v5.txt
grok_video/prompts/runway_hero_runbook.md
grok_video/prompts/runway_shot.txt
grok_video/real_gen.py
grok_video/real_gen_usage.py
grok_video/real_plan.py
grok_video/real_render.py
grok_video/slop_opus.py
grok_video/slop_plan.py
grok_video/slop_real.py
grok_video/slop_script.py
grok_video/songcraft.py
grok_video/story_cards.py
grok_video/storyboard.py
grok_video/tone.py
headline_day.sh
lib/align.py
lib/choose_script.py
lib/common.py
lib/make_ass.py
lib/make_assets.py
lib/prepare.py
lib/render.sh
lib/timings.py
lib/transcribe.py
lib/verify.py
local_gen/README.md
local_gen/clip_qc.py
local_gen/comfy_spark.sh
local_gen/compare.sh
local_gen/extra_model_paths.yaml
local_gen/local_gen.py
local_gen/strict_qc.py
lyric_metrics.py
lyrics_lint.py
post_lint.py
postiz_upload.sh
style_lint.py
tags.example.json
tiktok_post.md
x_post.py
x_source_reply.py
```

Working tree (excl .git): 1.3M, 88 tracked files. .git: 4.7M. Commits: 66.
