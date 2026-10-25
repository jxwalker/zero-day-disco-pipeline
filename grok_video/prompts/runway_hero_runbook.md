# Runway hero shots (24 Oct 2026, optional, agent-run)
Runway is only reachable through the `user-Runway` MCP, so the agent running the routine does this step.
1. After the first karaoke build, `<work>/grok/hero_jobs.json` lists 2-4 hero shots (chorus opening, final-chorus drop,
   final payoff, scroll-stopper), each with model (kling-4 = high-energy performance, wan3 = prop/screen), prompt,
   still and est_credits. Budget: GV_HERO_BUDGET (default 300 credits/day). Skip any job that would exceed it.
2. (SUPERSEDED by the 24 Oct relay update below; uploads 403 from the box.) Old flow: `init_upload` -> curl PUT -> `complete_upload` -> `generate_video` with model, startFrame.url,
   promptText, ratio 9:16, resolution 720p, duration 5 (kling-4: no generateAudio; wan3: generateAudio false) ->
   `get_task` every 60-120 s -> download -> `python storyboard.py hero-apply <gdir> <id> <file.mp4>`.
   Mark status done/failed and the credits used in hero_jobs.json (checkpoint after every job).
3. Any failure, refusal or timeout: leave the Grok clip (fallback is automatic). Never retry the same model more than once.
4. Re-render: `karaoke.py <day> --skip-gen` (plan.json and clips are reused).

## 24 Oct 2026 update: house style, DGX Spark, Runway uploads
- House style is fixed: Acid Deadpan for verses/pre/breakdown, Glitch Tape for chorus drops. Hero prompts must keep
  that look. Every video also needs 1-2 short moving Pip cameo shots, made from assets/pip_ref_9x16.png.
- the owner's DGX is a **DGX Spark**. Published timings: LTX-2.3 fp8 720p 5 s is about 82 s warm / 180 s cold (44.7 GB).
  Wan 2.2 14B fp8 640x640 5 s is about 565 s warm; fp16 81 frames is about 370 s warm; general reports say 15-25 min.
  On a 3090: Wan 5B takes 12-15 min, HunyuanVideo 1.5 fp8 15-18 min (GGUF Q4 about 4 min), LTX 1.5-3 min.
  Plan: Wan 2.2 A14B on the Spark for heroes, LTX-2.3 on the 3090s for b-roll, through headless ComfyUI over Tailscale.
  No command may run on the owner's machines without his OK.
- Runway upload 403: the box's AWS network path goes through a VPC endpoint whose policy blocks the presigned S3 PUT.
  It is not headers, credits or the plan. Fixes:
  (a) relay the PUT through the DGX. PENDING THE OWNER'S OK. Not set up.
  (b) fallback that works today: text-to-video, or generate_image, then use that taskId as the start frame for
      image_to_video. No upload is needed.
  Do not upload stills to any public host.

## 24 Oct 2026 relay update: reference-frame pattern (DEFAULT, tested end to end)
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
DGX Spark relay (option a) is APPROVED by the owner but NOT usable from the box right now: the box has no ssh client and no
tailnet route ($SPARK_HOST:22 times out). tools/runway_relay.sh was not created. Revisit only if the box gets tailnet access.
Test 24 Oct: frame eafe361e (nano-banana-2.1) -> wan3 480p 4 s i2v task 592ab7e5; clip runway_test/wan3_frame_relaytest.mp4.

## 24 Oct 2026 evening: shot sheets + clip QC + local tiers (the owner: "runway needs very very good prompting",
## "be much more of a movie producer... exact descriptions"; LTX "fast and good just prone to mistakes")
Tiers in karaoke.generate (GV_LOCAL=1 default, `local_clips`): premium = hero_jobs (Runway, this runbook);
hero = the 2 most-used other scenes (GV_WAN_HEROES) -> Wan 2.2 on the Spark; b-roll = LTX 2B 0.9.8 distilled draft
(3 s, 73 frames, anti-overshoot prompt via local_gen.gentle) -> clip_qc -> one LTX re-roll (new seed) -> Wan 2.2 -> Grok.
ComfyUI on the Spark is started and always stopped by the pipeline. Failures + reasons: <gdir>/local_qc_log.jsonl.
1. Shot sheet BEFORE any credit: `storyboard.hero_sheets` (run automatically after hero_plan; GV_SHEETS=0 disables) writes
   <gdir>/shot_sheets/<id>.json from prompts/runway_shot.txt (set in metres with prop positions, character/wardrobe hex,
   timed blocking, lens mm/height/distance/move speed/start+end framing, key/fill/practicals with K, hex palette, stock,
   constants, negatives). Opus reviews it (0-10; any vague word like cool/cinematic/nice caps it at 5), up to 3 rounds.
   ONLY run jobs with `spec_ok: true` (score >= 7, GV_SHEET_MIN; lowered from 8 by the owner 24 Oct). Use job.frame_prompt for nano-banana and job.prompt (motion only)
   for generate_video. `spec_rejected` jobs: spend nothing; the Grok clip stays.
2. After download, before hero-apply: `python ../local_gen/clip_qc.py qc <clip.mp4> --prompt "<job.prompt>" --image <still>`.
   ok=false -> do not apply; log the reasons in hero_jobs.json (one paid retry max, only if budget allows).

- 24 Oct loosen: b-roll QC (`--tier broll`) allows fuzzy text on small/out-of-focus screens; hero and Runway QC stay strict.

## 25 Oct 2026: strict QC (the owner: wrench shirt + floppy wrench)
`clip_qc.py qc` now runs `local_gen/strict_qc.py`: frames every 0.25 s on timestamped contact sheets, reject rules for
prop rigidity, wardrobe vs spec (any clothing graphic fails), hand-prop interactions, physics; reviewer A = Opus,
reviewer B = Grok 4.7 (independent), BOTH must pass on hero/prop shots; fail closed. Pass `--wardrobe` or set GV_WARDROBE.
