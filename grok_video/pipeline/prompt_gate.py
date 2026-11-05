"""Prompt / wardrobe gate with negation-aware accessory checks and rewrite (not silent drop).

Production failure: the gate blocked singing and action shots, then silently skipped them.
Sustainable rule: incompatible prompts are rewritten up to N times; lock-string leaks are
stripped; negated bans ("no jewellery", "without chains") must PASS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from .constants import ACCESSORY_BAN, LOCK_LEAK_MARKERS, PROMPT_REWRITE_TRIES

# Light-change lint removed: stories need "dot flares / racks light up".
BANNED_LINTS = (
    (re.compile(r'\b(kitchen|cardigan|cable-knit)\b', re.I), 'cross_video_lock_leak'),
)

NEGATION_PREFIX = re.compile(
    r'\b(?:no|without|free of|free from|lacking|avoid(?:ing)?|never(?: with)?|zero|sans)\b'
    r'[\s,:-]*',
    re.I,
)
# Window after a negation that covers the banned accessory token.
NEGATION_WINDOW = 48

SING_WITHOUT_LINE = re.compile(
    r'\b(?:sings?|singing|lip[- ]?sync)\b', re.I,
)
# Quoted lyric, explicit [LINE] tag, or uppercase LINE token — not the word "line" in "singing this line".
LINE_MARKER = re.compile(r'\[LINE\]|(?<![A-Za-z])LINE(?![A-Za-z])|"[^"]{3,}"|\bsung (?:lyric|words?)\b')


@dataclass
class PromptIssue:
    code: str
    detail: str
    fatal: bool = False  # fatal = rewrite cannot fix; drop only if not story-critical


@dataclass
class PromptGateResult:
    ok: bool
    prompt: str
    issues: List[PromptIssue] = field(default_factory=list)
    rewrites: int = 0
    dropped: bool = False
    reason: str = ''

    def to_dict(self) -> dict:
        return {
            'ok': self.ok,
            'prompt': self.prompt,
            'issues': [{'code': i.code, 'detail': i.detail, 'fatal': i.fatal} for i in self.issues],
            'rewrites': self.rewrites,
            'dropped': self.dropped,
            'reason': self.reason,
        }


def _negated(text: str, start: int) -> bool:
    """True if `start` falls inside a negation window (e.g. 'no jewellery', 'without chains')."""
    window = text[max(0, start - NEGATION_WINDOW):start]
    return bool(NEGATION_PREFIX.search(window))


def accessory_violations(prompt: str) -> List[PromptIssue]:
    """Flag banned accessories unless the mention is negated."""
    issues: List[PromptIssue] = []
    low = prompt or ''
    for word in ACCESSORY_BAN:
        for m in re.finditer(rf'\b{re.escape(word)}\b', low, re.I):
            if _negated(low, m.start()):
                continue
            issues.append(PromptIssue(
                'accessory_ban',
                f"banned accessory '{m.group(0)}' without negation; "
                f"use 'no {word}' / 'without {word}' or remove it",
            ))
    return issues


def strip_lock_leaks(prompt: str) -> tuple[str, List[PromptIssue]]:
    """Remove known cross-video farm lock phrases (cardigan/kitchen leak)."""
    out = prompt or ''
    issues: List[PromptIssue] = []
    for marker in LOCK_LEAK_MARKERS:
        if marker.lower() in out.lower():
            issues.append(PromptIssue('lock_leak', f"stripped cross-video lock phrase: {marker}"))
            out = re.sub(re.escape(marker), '', out, flags=re.I)
    out = re.sub(r'\s{2,}', ' ', out).strip(' ,;.')
    return out, issues


def _strip_accessories(prompt: str) -> str:
    """Rewrite: turn positive accessory mentions into explicit negations."""
    out = prompt or ''
    for word in ACCESSORY_BAN:
        def repl(m, w=word):
            if _negated(out, m.start()):
                return m.group(0)
            return f'no {w}'
        out = re.sub(rf'\b{re.escape(word)}\b', repl, out, flags=re.I)
    return out


def _strip_sing_without_line(prompt: str) -> str:
    """If the prompt says the character sings but has no sung LINE, drop the singing wrapper."""
    if SING_WITHOUT_LINE.search(prompt or '') and not LINE_MARKER.search(prompt or ''):
        out = SING_WITHOUT_LINE.sub('performs', prompt)
        out = re.sub(r'\[SING\]', '', out, flags=re.I)
        out = re.sub(
            r'\b(?:steady )?front-facing close-up[^.;,]*,?\s*(?:eyes to lens[^.;,]*,?\s*)?(?:singing this line)?',
            'medium shot of the action',
            out,
            flags=re.I,
        )
        return re.sub(r'\s{2,}', ' ', out).strip()
    return prompt


def lint_prompt(prompt: str) -> List[PromptIssue]:
    issues: List[PromptIssue] = []
    issues.extend(accessory_violations(prompt))
    _, leak_issues = strip_lock_leaks(prompt)
    issues.extend(leak_issues)
    if SING_WITHOUT_LINE.search(prompt or '') and not LINE_MARKER.search(prompt or ''):
        issues.append(PromptIssue(
            'sing_without_line',
            'character sings but no sung LINE in the beats; strip singing wrapper',
        ))
    # Explicitly do NOT flag light changes — stories need flares / rack lights.
    return issues


def rewrite_prompt(prompt: str, issues: Sequence[PromptIssue]) -> str:
    out, _ = strip_lock_leaks(prompt)
    codes = {i.code for i in issues}
    if 'accessory_ban' in codes:
        out = _strip_accessories(out)
    if 'sing_without_line' in codes:
        out = _strip_sing_without_line(out)
    return re.sub(r'\s{2,}', ' ', out).strip(' ,;.')


def gate_prompt(prompt: str, *, max_tries: Optional[int] = None,
                story_critical: bool = False) -> PromptGateResult:
    """Validate and rewrite a single prompt. Never silently swap in another video's lock."""
    tries = PROMPT_REWRITE_TRIES if max_tries is None else max_tries
    cur = (prompt or '').strip()
    all_issues: List[PromptIssue] = []
    rewrites = 0
    for _ in range(max(1, tries)):
        issues = lint_prompt(cur)
        # lock_leak after strip_lock_leaks inside rewrite is informational on first pass
        blocking = [i for i in issues if i.code != 'lock_leak' or i.detail.startswith('banned')]
        # Recompute: lock leaks are always rewriteable
        blocking = [i for i in issues if i.code in ('accessory_ban', 'sing_without_line', 'lock_leak')]
        if not blocking:
            return PromptGateResult(ok=True, prompt=cur, issues=all_issues, rewrites=rewrites)
        all_issues.extend(blocking)
        nxt = rewrite_prompt(cur, blocking)
        rewrites += 1
        if nxt == cur:
            break
        cur = nxt
    # Still dirty after rewrites
    leftover = lint_prompt(cur)
    leftover = [i for i in leftover if i.code in ('accessory_ban', 'sing_without_line')]
    if leftover and story_critical:
        return PromptGateResult(
            ok=False, prompt=cur, issues=all_issues + leftover, rewrites=rewrites,
            dropped=False, reason='story-critical prompt still incompatible after rewrite',
        )
    if leftover:
        return PromptGateResult(
            ok=False, prompt=cur, issues=all_issues + leftover, rewrites=rewrites,
            dropped=True, reason='prompt incompatible after rewrite; do not render',
        )
    return PromptGateResult(ok=True, prompt=cur, issues=all_issues, rewrites=rewrites)


def gate_prompts(scenes: Iterable[dict], *, id_key: str = 'id',
                 prompt_key: str = 'prompt',
                 critical_tags: Sequence[str] = ('TWIST', 'PAYOFF', 'TURN')) -> dict:
    """Gate every scene prompt. Returns a report + updated scenes (mutates copies).

    Story-critical scenes (tags in prompt/id) are NEVER dropped; failure is reported so
    coverage gates can abort the run.
    """
    out_scenes = []
    report = []
    kept = dropped = critical_fail = 0
    for sc in scenes:
        sc = dict(sc)
        prompt = sc.get(prompt_key) or ''
        blob = f"{sc.get(id_key, '')} {prompt} {sc.get('tags', '')} {sc.get('role', '')}"
        critical = any(f'[{t}]' in blob.upper() or f'_{t.lower()}' in blob.lower()
                       or t.lower() in str(sc.get('tags', '')).lower()
                       for t in critical_tags)
        res = gate_prompt(prompt, story_critical=critical)
        sc[prompt_key] = res.prompt
        if res.ok:
            kept += 1
            out_scenes.append(sc)
        elif critical:
            critical_fail += 1
            sc['_gate_fail'] = res.reason
            out_scenes.append(sc)  # keep slot; coverage will abort
        else:
            dropped += 1
        report.append({'id': sc.get(id_key), 'critical': critical, **res.to_dict()})
    return {
        'scenes': out_scenes,
        'report': report,
        'kept': kept,
        'dropped': dropped,
        'critical_fail': critical_fail,
        'ok': critical_fail == 0,
    }
