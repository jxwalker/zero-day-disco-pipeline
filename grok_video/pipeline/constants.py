"""Named knobs for pipeline hardening. Override via environment variables at call sites."""
import os

# Prompt / wardrobe
PROMPT_REWRITE_TRIES = int(os.environ.get('GV_PROMPT_REWRITE_TRIES', '3'))
MIN_CLIP_COVERAGE = float(os.environ.get('GV_MIN_CLIP_COVERAGE', '0.90'))
# Timeline
CLIP_MAX_USES = int(os.environ.get('GV_CLIP_MAX_USES', '2'))
# Lip-sync
LIPSYNC_MIN_SCORE = float(os.environ.get('GV_LS_MIN_SCORE', '0.25'))
LIPSYNC_OFFSETS_MS = (0, -80, 80, -160, 160)
SING_MIN_HEIGHT = int(os.environ.get('GV_SING_MIN_H', '720'))
# Render
FARM_RES_DEFAULT = os.environ.get('GV_FARM_RES', '1280x720')
MASTER_CRF = int(os.environ.get('GV_MASTER_CRF', '17'))
# Gates
GATE_ABORT_SCORE = int(os.environ.get('GV_GATE_ABORT_SCORE', '80'))
GATE_EXIT_CODE = 8
# Overlays (model never renders text; post-production overlays are ON by default)
NEWS_TEXT_DEFAULT = os.environ.get('GV_NEWS_TEXT', '1') != '0'
NO_GFX_DEFAULT = os.environ.get('GV_NO_GFX', '0') == '1'
TERM_COMPOSITE_DEFAULT = os.environ.get('GV_TERM_COMPOSITE', '1') != '0'

# Cross-video lock strings that must never leak into another day's prompts
LOCK_LEAK_MARKERS = (
    'cream cable-knit cardigan',
    'same kitchen',
    'same woman',
    'fridge',
    'cable-knit',
)

# Story-critical tags that must produce a clip or abort
CRITICAL_TAGS = ('TWIST', 'PAYOFF', 'TURN')

# Accessories banned unless explicitly negated in the prompt
ACCESSORY_BAN = (
    'jewellery', 'jewelry', 'necklace', 'bracelet', 'earring', 'earrings',
    'chains', 'chain', 'choker', 'pendant', 'bangle', 'ring', 'rings',
)
