# Pipeline hardening (postmortem 2026-11-05)

Sustainable, public-repo versions of the Pull-the-Plug production fixes. No private assets, prompts, secrets, logs, host paths, or machine-specific config.

## Package

`grok_video/pipeline/` — modular gates used by `karaoke.py` and the service facade:

| Module | Responsibility |
|---|---|
| `prompt_gate.py` | Negation-aware accessory lint ("no jewellery" passes); rewrite up to 3×; strip cross-video lock leaks; never silent-drop story-critical |
| `screen_policy.py` | Robots/cast/blank terminals do not die via `other_problem`; garbled gen-text still fails |
| `plan_fix.py` | SING wrappers only on dedicated HERO performance shots; strip from action/robot |
| `timeline_policy.py` | Scene-order timeline; `GV_CLIP_MAX_USES` default 2; pin only when `plan_fp` matches |
| `coverage.py` | Abort (exit 8) if coverage &lt; 90% or TWIST/PAYOFF/TURN clip missing |
| `identity.py` | Per-character ref routing; singing instructions only on sing shots; duplicate-lead QC |
| `overlays.py` / `term_composite.py` | Model no-text; post-prod story/UI/terminal overlays ON; beat-driven cut helpers |
| `lipsync.py` | Never pin &lt; 0.25; cutaway instead; ±80/160 ms offset search; SING ≥ 720p |
| `renderer.py` | Grok-primary plan with cache reuse, local b-roll fallback, budget guard |
| `watchdog.py` | Progress events + actionable error hints |
| `service.py` | `PopVideoRequest` / `PopVideoJob` — image + song idea → gated job (SaaS-ready, no UI) |
| `creative_contract.py` | Adaptable story craft: visual premise, optional world contrast, character anchors, performance-on-accent, shot variety, location transformations, code-built graphics plan (never model text) |

## Creative contract (quality benchmark lessons)

Craft lessons (visual premise per shot; contrasting worlds via grade/design/camera; styling anchors;
performances on musical accents; shot variety + physical interaction; recurring-location payoff;
persistent code-built HUD / kinetic type; beat-timed escalation) are encoded as an **adaptable**
`creative_contract` on the plan — not a rigid clone of any one video.

- **Simple jobs** (one world): pass with premise + anchors + `graphics_plan.model_renders_text=false`.
- **Dual-world jobs**: contrast checks unlock only when `worlds` has 2+ entries.
- **Location arcs**: optional; when present, require ≥2 visible states and a real `payoff_scene`.
- **Graphics**: HUD / kinetic / terminal / captions are always edit-composited (`overlays.py` + `term_composite.py`).

Mode: `GV_CREATIVE_CONTRACT_MODE=adaptive|strict|advisory` (default `adaptive`).
Karaoke logs warnings by default; set `GV_CREATIVE_CONTRACT_ABORT=1` to hard-fail.

## Defaults (override via env)

- `GV_NEWS_TEXT=1`, `GV_NO_GFX=0`, `GV_TERM_COMPOSITE=1` — overlays on; model still forbidden from rendering text
- `GV_CLIP_MAX_USES=2`
- `GV_MIN_CLIP_COVERAGE=0.90`
- `GV_LS_MIN_SCORE=0.25`, `GV_SING_MIN_H=720`
- `GV_FARM_RES=1280x720`, `GV_MASTER_CRF=17`
- `GV_COVERAGE_GATE=1` — karaoke exits **8** on coverage / twist failure
- Do **not** set a global `GV_FARM_LOCK` kitchen/cardigan string; optional per-scene short lock only

## Service-facing contract

```python
from pipeline.service import PopVideoRequest, PopVideoJob
req = PopVideoRequest(job_id='...', image_path='lead.png', song_idea='...', work_dir='work_jobs/...')
result = PopVideoJob(req).run(dry_run=True, available_clips={...})
```

Long-term SaaS shape: user uploads an image + song idea → this job contract → pop video. This change hardens the pipeline only; it does not add UI.

## Tests

```bash
python3 -m unittest discover -s test/unit -v
```

## Explicit non-goals

- No production deploys, no posting, no private benchmark binaries in-repo
- No secrets / host paths / personal prompts committed
- No new paid APIs; no SaaS UI; PopVideoJob facade preserved
