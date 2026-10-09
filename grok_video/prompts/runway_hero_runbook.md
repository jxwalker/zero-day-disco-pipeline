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
