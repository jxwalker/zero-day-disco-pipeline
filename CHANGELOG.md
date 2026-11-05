# Changelog

All notable changes are listed here. Versions follow semantic versioning and are tagged `vX.Y.Z`.

## v1.3.0
- Watch Me–class story coherence recovery on top of v1.2 hardening:
  lean scene-state model (before/action/after, role/allegiance/prop, consequence edges),
  structural `required_shots` climax abort (including QC-rejected required clips),
  storyboard review hard gate before generate, mouths-closed performance default (`GV_SING=1` opt-in),
  SING max-uses=1, art/prop bible bans (clay/cartoon/toy + plug-scale lock), ≤28 scene cap,
  picture-first graphics lint (black-void ≤1.5s, gfx_share ≤10%), narrative QA checklist,
  and typed `JobFailure` kinds so unattended jobs return finished MP4 **or** actionable failure.
- Dry-run acceptance tests in `test/unit/test_story_coherence.py`. Docs: `docs/technical/pipeline-hardening.md`.

## v1.2.0
- Pipeline hardening from the 2026-11-05 production postmortem (`grok_video/pipeline/`):
  negation-aware prompt/wardrobe gate, screen-check waivers for cast/blank terminals, scene-order timeline
  with reuse cap and plan fingerprint pins, coverage abort (exit 8) on missing TWIST/PAYOFF, per-character
  identity routing, SING-only-on-sing-shots plan fix, post-production story/UI/terminal overlays ON by
  default, lip-sync pin gate with offset search, Grok-primary render planner with cache/budget/local
  fallback, progress watchdog, and a service-facing `PopVideoJob` contract (image + song idea).
- Adaptable `creative_contract` (visual premise, optional world contrast, character styling anchors,
  performance-on-accent beats, shot variety, location transformation/payoff, code-built HUD/kinetic
  graphics plan with model-never-renders-text). Wired into `PopVideoJob`, karaoke planning, and
  storyboard direction prompts without rejecting legitimate simpler single-world videos.
- Regression tests under `test/unit/`. Technical notes: `docs/technical/pipeline-hardening.md`.

## v1.1.0
- Documentation, prompts and code comments rewritten as present-tense requirements.
- Postiz integration IDs moved to the local config (`POSTIZ_TIKTOK_ID`, `POSTIZ_YOUTUBE_ID`).
- Private values (hosts, keys, account IDs) live only in a local `config.env`; see `config.example.env`.

## v1.0.0
- First public release of the pipeline: lyrics generation and lint, karaoke video build, local and Runway clip
  generation, strict QC, and posting scripts.
