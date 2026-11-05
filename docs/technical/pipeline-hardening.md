# Pipeline hardening (postmortem 2026-11-05 + Watch Me coherence)

Sustainable, public-repo versions of the Pull-the-Plug production fixes, plus the
story-coherence recovery that stops shipping narratively broken cuts. No private
assets, prompts, secrets, logs, host paths, or machine-specific config.

## Package

`grok_video/pipeline/` — modular gates used by `karaoke.py` and the service facade:

| Module | Responsibility |
|---|---|
| `prompt_gate.py` | Negation-aware accessory lint ("no jewellery" passes); rewrite up to 3×; strip cross-video lock leaks; never silent-drop story-critical |
| `screen_policy.py` | Robots/cast/blank terminals do not die via `other_problem`; garbled gen-text still fails |
| `plan_fix.py` | **Mouths-closed story default**; strip all SING unless `GV_SING=1`; when opted in, SING only on dedicated HERO shots |
| `timeline_policy.py` | Scene-order timeline; `GV_CLIP_MAX_USES` default 2; pin only when `plan_fp` matches |
| `coverage.py` | Abort (exit 8) if coverage &lt; 90% **or structural required climax ids missing/rejected** |
| `story_model.py` | Lean scene-state (before/action/after), role/allegiance/prop locks, consequence edges, art bible, ≤28 scene cap |
| `narrative_gate.py` | Storyboard hard gate + Watch Me narrative checklist before generate / GATE |
| `graphics_lint.py` | Picture-first overlays; black-void gfx ≤1.5s; gfx_share ≤10%; SING max-uses=1 |
| `failures.py` | Typed job failures (`coverage\|narrative\|storyboard\|art\|consequence\|gfx\|sing\|gate\|budget\|plan`) |
| `identity.py` | Per-character ref routing; singing instructions only on sing shots; duplicate-lead QC |
| `overlays.py` / `term_composite.py` | Model no-text; post-prod story/UI/terminal overlays ON; beat-driven cut helpers |
| `lipsync.py` | Never pin &lt; 0.25; cutaway instead; ±80/160 ms offset search; SING ≥ 720p |
| `renderer.py` | Grok-primary plan with cache reuse, local b-roll fallback, budget guard |
| `watchdog.py` | Progress events + actionable error hints |
| `service.py` | `PopVideoRequest` / `PopVideoJob` — image + song idea → gated job (SaaS-ready, no UI) |
| `creative_contract.py` | Adaptable story craft: visual premise, optional world contrast, character anchors, performance-on-accent, shot variety, location transformations, code-built graphics plan (never model text) |

## Story coherence (Watch Me recovery)

Lyric timing stays for **captions**; it must **not** own narrative structure.

```
brief (1 premise)
  → scene_state_storyboard (≤28 beats, locks, consequence edges)
  → art_bible_validate
  → storyboard_review HARD gate
  → generate (Grok) with cast/prop refs
  → coverage + REQUIRED structural payoff abort (incl. rejected climax)
  → edit: picture-first; overlays on plates; SING≤1 or mouths-closed mode
  → narrative_QA → GATE → finished MP4 or typed fail
```

### Structural required shots (not keyword hunting)

Required climax/twist/payoff ids come from, in order:

1. `plan.required_shots` / `plan.climax_ids`
2. scenes with `structural_role` in `{twist,payoff,climax,reveal,turn,final_payoff,bookend}`
3. legacy TWIST/PAYOFF/TURN/CLIMAX tags (compat)
4. optional `plan.climax_tail_n` (last N scene ids)

`[OVERSEER]` alone is **not** auto-critical — mark those climax beats as structural ids.
Rejected required clips (`clip_rejected` ∩ required set) hard-abort; never assemble a hole.

### Performance default

- Story mode: mouths closed, `GV_SING` unset/`0` → strip SING, no faux-singing.
- Reliable singing: `GV_SING=1` or `PopVideoRequest.extras['sing_enabled']=True`.
- SING sources may appear at most once (`GV_SING_MAX_USES=1`); no "SING reuse (no spare)".

### Graphics

- **Infrastructure** (endcard, karaoke/lyrics captions) is allowed and excluded from narrative `gfx_share`.
- **Narrative slides** (bignum / story / long headline voids) on black without a live plate
  and &gt; `GV_MAX_BLACK_GFX_S` (default 1.5s) → typed `gfx` failure.
- Narrative `gfx_share` &gt; `GV_MAX_GFX_SHARE` (default 10%) → typed `gfx` failure.
- `graphics_plan` is linted **before generation** (`assert_plan_graphics`).

### Consequence edges

- `requires_next` must be **authored**. `ensure_scene_states(infer_edges=False)` is the default;
  acceptance paths never auto-wire edges. Missing edges → typed `consequence` failure.

### Storyboard / resume

- A present, passing storyboard review is required on every generate **and** resume path.
- Reviewer exceptions abort (no swallow). Existing `plan.json` does **not** bypass gates.

## Creative contract (quality benchmark lessons)

Craft lessons are encoded as an **adaptable** `creative_contract` on the plan — not a
rigid clone of any one video.

- **Simple jobs** (one world): pass with premise + anchors + `graphics_plan.model_renders_text=false`.
- **Dual-world jobs**: contrast checks unlock only when `worlds` has 2+ entries.
- **Location arcs**: optional; when present, require ≥2 visible states and a real `payoff_scene`.
- **Graphics**: HUD / kinetic / terminal / captions are always edit-composited.

Mode: `GV_CREATIVE_CONTRACT_MODE=adaptive|strict|advisory` (default `adaptive`).
Karaoke logs warnings by default; set `GV_CREATIVE_CONTRACT_ABORT=1` to hard-fail.

## Defaults (override via env)

- `GV_NEWS_TEXT=1`, `GV_NO_GFX=0`, `GV_TERM_COMPOSITE=1` — overlays on; model still forbidden from rendering text
- `GV_CLIP_MAX_USES=2`
- `GV_MIN_CLIP_COVERAGE=0.90`
- `GV_LS_MIN_SCORE=0.25`, `GV_SING_MIN_H=720`
- `GV_SING=0` — mouths-closed story default; set `1` to opt into singing
- `GV_SING_MAX_USES=1`
- `GV_MAX_SCENES=28`, `GV_ALLOW_LARGE_PLAN=0`
- `GV_STORYBOARD_MIN_SCORE=7` — below this or "must not go to camera" → abort before generate
- `GV_MAX_BLACK_GFX_S=1.5`, `GV_MAX_GFX_SHARE=0.10`
- `GV_FARM_RES=1280x720`, `GV_MASTER_CRF=17`
- `GV_COVERAGE_GATE=1` — karaoke exits **8** on coverage / twist / typed story failures
- Do **not** set a global `GV_FARM_LOCK` kitchen/cardigan string; optional per-scene short lock only

## Service-facing contract

```python
from pipeline.service import PopVideoRequest, PopVideoJob
req = PopVideoRequest(job_id='...', image_path='lead.png', song_idea='...', work_dir='work_jobs/...')
result = PopVideoJob(req).run(dry_run=True, available_clips={...})
# result.ok → gates_passed / finished_mp4
# not result.ok → result.failure_kind in {coverage,narrative,storyboard,art,consequence,gfx,sing,...}
```

Long-term SaaS shape: user uploads an image + song idea → this job contract → pop video
**or** a typed actionable failure. This change hardens the pipeline only; it does not add UI.

## Tests

```bash
python3 -m unittest discover -s test/unit -v
```

Dry-run acceptance coverage (`test/unit/test_story_coherence.py`):

- missing climax aborts; rejected climax aborts
- bad storyboard review aborts before generation
- invalid consequence edge / art style / prop scale fails
- Watch Me–like plan passes with zero SING
- duplicate SING fails; excessive graphics fails
- result is gates_passed/finished **or** typed failure

## Explicit non-goals

- No production deploys, no posting, no private benchmark binaries in-repo
- No secrets / host paths / personal prompts committed
- No new paid APIs; no SaaS UI; PopVideoJob facade preserved
- No huge FSM — lean scene-state + structural ids achieve the outcomes
