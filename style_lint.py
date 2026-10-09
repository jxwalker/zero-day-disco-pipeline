#!/usr/bin/env python3
"""style.txt lint (16 Oct 2026, the owner: 'Cap in Hand' was "auto tuned garbage").
usage: style_lint.py <style.txt> [--fix]   -> prints "style lint: clean" (exit 0) or the problems (exit 1).
Rules: must ask for natural raw human lead vocals with no autotune/vocoder/pitch correction; must not contain 'jingle'.
--fix strips jingle phrases and appends the vocal clause, then re-checks."""
import re, sys
VOCAL = "natural raw human lead vocals, no autotune, no vocoder, no pitch correction"
EXCLUDE = "autotune, vocoder, jingle"          # Suno Custom > More Options > Exclude styles
BANNED = re.compile(r"[^,.;]*\bjingles?\b[^,.;]*[,.;]?\s*", re.I)

def problems(s):
    p = []
    if not re.search(r"\bno auto-?tune\b", s, re.I): p.append("missing 'no autotune'")
    if not re.search(r"\bno vocoder\b", s, re.I): p.append("missing 'no vocoder'")
    if not re.search(r"\b(natural|raw|human)\b[^,]*vocal", s, re.I): p.append("missing natural/raw human vocal wording")
    if re.search(r"jingle", s, re.I): p.append("contains 'jingle' (banned style)")
    return p

def fix(s):
    s = BANNED.sub('', s).strip(' ,;.\n')
    if problems(s + ', x'):  # vocal clause missing
        s = (s + ', ' if s else '') + VOCAL
    return s.strip()

if __name__ == '__main__':
    path = sys.argv[1]; s = open(path).read().strip()
    if '--fix' in sys.argv:
        s = fix(s); open(path, 'w').write(s + '\n')
    p = problems(s)
    print('style lint: clean' if not p else 'style lint: ' + '; '.join(p))
    sys.exit(1 if p else 0)
