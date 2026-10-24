# Runway hero shots (24 Oct 2026, optional, agent-run)
Runway is only reachable through the `user-Runway` MCP, so the agent running the routine does this step.
1. After the first karaoke build, `<work>/grok/hero_jobs.json` lists 2-4 hero shots (chorus opening, final-chorus drop,
   final payoff, scroll-stopper), each with model (kling-4 = high-energy performance, wan3 = prop/screen), prompt,
   still and est_credits. Budget: GV_HERO_BUDGET (default 300 credits/day). Skip any job that would exceed it.
2. For each job: `init_upload` the still -> curl PUT -> `complete_upload` -> `generate_video` with model, startFrame.url,
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
