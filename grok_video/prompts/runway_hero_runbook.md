# Runway hero shots
Runway is only reachable through the `user-Runway` MCP, so the agent running the routine does this step.
1. After the first karaoke build, `<work>/grok/hero_jobs.json` lists 2-4 hero shots (chorus opening, final-chorus drop,
   final payoff, scroll-stopper), each with model (kling-4 = high-energy performance, wan3 = prop/screen), prompt,
   still and est_credits. Budget: GV_HERO_BUDGET (default 300 credits/day). Skip any job that would exceed it.
2. Generate each job with the reference-frame pattern below. Mark status done/failed and the credits used in
   hero_jobs.json (checkpoint after every job).
3. Any failure, refusal or timeout: leave the Grok clip (fallback is automatic). Never retry the same model more than once.
4. Re-render: `karaoke.py <day> --skip-gen` (plan.json and clips are reused).

## House style and hosts
- House style is fixed: Acid Deadpan for verses/pre/breakdown, Glitch Tape for chorus drops. Hero prompts must keep
  that look. Every video also needs 1-2 short moving Pip cameo shots, made from assets/pip_ref_9x16.png.
- Local generation runs on the DGX Spark (LTX for b-roll, Wan 2.2 for local heroes) through headless ComfyUI over
  Tailscale. No command runs on the owner's machines without his OK.
- Never upload stills to any public host. Runway start frames come from Runway's own generate_image task.

## Reference-frame pattern (default)
Claudia pattern: make a reference frame first, then animate it. No uploads.
Fallback chain per job (`path_order`): runway_frame -> runway_text -> grok.
1. runway_frame: `generate_image` model=job.frame_model (nano-banana-2.1), ratio 9:16, imageSize 1K, thinkingLevel minimal,
   promptText=job.frame_prompt (~4 credits, ~15 s). For Pip cameo jobs pass assets/pip_ref_9x16.png only if a Runway-hosted
   URL exists; otherwise describe Pip in text. Check the frame with Read (tongue-out, flipped text, off-style -> regenerate once).
   Then `generate_video` model=job.model, startFrame.taskId=<image task id>, promptText=job.prompt, ratio 9:16,
   resolution 720p, duration 5 (wan3: generateAudio false; kling-4: omit generateAudio). Poll `get_task` every 60-120 s,
   curl the artifact URL to job.out, then `python storyboard.py hero-apply <gdir> <id> <file.mp4>`.
2. runway_text: if the frame step fails or is refused, `generate_video` text-only with frame_prompt + job.prompt.
3. grok: any further failure keeps the Grok clip (automatic). Never retry the same model more than once.
Keep GV_HERO_BUDGET (300/day, frame cost included in est_credits). GV_HERO=0 disables.

## Shot sheets, clip QC and local tiers
Tiers in karaoke.generate (GV_LOCAL=1 default, `local_clips`): premium = hero_jobs (Runway, this runbook);
hero = the 2 most-used other scenes (GV_WAN_HEROES) -> Wan 2.2 on the Spark; b-roll = LTX 2B 0.9.8 distilled draft
(3 s, 73 frames, anti-overshoot prompt via local_gen.gentle) -> clip_qc -> one LTX re-roll (new seed) -> Wan 2.2 -> Grok.
ComfyUI on the Spark is started and always stopped by the pipeline. Failures + reasons: <gdir>/local_qc_log.jsonl.
1. Shot sheet BEFORE any credit: `storyboard.hero_sheets` (run automatically after hero_plan; GV_SHEETS=0 disables) writes
   <gdir>/shot_sheets/<id>.json from prompts/runway_shot.txt (set in metres with prop positions, character/wardrobe hex,
   timed blocking, lens mm/height/distance/move speed/start+end framing, key/fill/practicals with K, hex palette, stock,
   constants, negatives). Opus reviews it (0-10; any vague word like cool/cinematic/nice caps it at 5), up to 3 rounds.
   ONLY run jobs with `spec_ok: true` (score >= 7, GV_SHEET_MIN). Use job.frame_prompt for nano-banana and job.prompt (motion only)
   for generate_video. `spec_rejected` jobs: spend nothing; the Grok clip stays.
2. After download, before hero-apply: `python ../local_gen/clip_qc.py qc <clip.mp4> --prompt "<job.prompt>" --image <still>`.
   ok=false -> do not apply; log the reasons in hero_jobs.json (one paid retry max, only if budget allows).

- B-roll QC (`--tier broll`) allows fuzzy text on small/out-of-focus screens; hero and Runway QC stay strict.

## Strict QC
`clip_qc.py qc` runs `local_gen/strict_qc.py`: frames every 0.25 s on timestamped contact sheets, reject rules for
prop rigidity, wardrobe vs spec (any clothing graphic fails), hand-prop interactions, physics; reviewer A = Opus,
reviewer B = Grok 4.7 (independent), BOTH must pass on hero/prop shots; fail closed. Pass `--wardrobe` or set GV_WARDROBE.
