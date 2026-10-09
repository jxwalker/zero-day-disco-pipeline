#!/usr/bin/env python3
"""Daily X post lint (18 Oct 2026, the owner: credit Grok Bot, tag @grok so Grok replies, #slopcore; wants Elon's attention).
usage: post_lint.py <post.txt> [sources.txt]   -> "post lint: clean" (exit 0) or the problems (exit 1).
post.txt must contain 'Grok Bot', an '@grok' mention and '#slopcore',
all inside the first 280 weighted characters (above X's "Show more" fold), and the whole post must fit X's limit
(@jxwalker has Premium+: 25,000 weighted chars; override with X_POST_LIMIT). sources.txt must keep the story links
(x.com/... status URLs) and the Suno link, and fit the same limit."""
import os, re, sys
LIMIT = int(os.environ.get("X_POST_LIMIT", "25000"))
FOLD = 280
URL = re.compile(r"https?://\S+")
LIGHT = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]

def weighted(text):
    """X's twitter-text v3 weighting (approx.): URLs = 23, Latin etc. = 1, emoji/CJK = 2, emoji joiners free."""
    n, pos = 0, 0
    for m in URL.finditer(text):
        n += _w(text[pos:m.start()]) + 23; pos = m.end()
    return n + _w(text[pos:])

def _w(s):
    n, skip = 0, False
    for ch in s:
        o = ord(ch)
        if skip: skip = False; continue
        if o in (0xFE0F, 0xFE0E) or 0x1F3FB <= o <= 0x1F3FF: continue
        if o == 0x200D: skip = True; continue
        n += 1 if any(a <= o <= b for a, b in LIGHT) else 2
    return n

def head(text, k=FOLD):
    out, n = "", 0
    for ch in text:
        n += _w(ch)
        if n > k: break
        out += ch
    return out

def check_post(t):
    p = []
    if not re.search(r"(?<![\w@])@grok\b", t, re.I): p.append("missing '@grok' mention")
    if not re.search(r"\bGrok Bot\b", t): p.append("missing 'Grok Bot' credit (e.g. 'Made by Grok Bot')")
    if not re.search(r"(?<!\w)#slopcore\b", t, re.I): p.append("missing '#slopcore'")
    h = head(t)
    for k, rx in (("@grok", r"(?<![\w@])@grok\b"), ("Grok Bot", r"\bGrok Bot\b"), ("#slopcore", r"#slopcore\b")):
        if re.search(rx, t, re.I) and not re.search(rx, h, re.I):
            p.append(f"'{k}' is below the 280-char 'Show more' fold; move the Grok Bot line up")
    w = weighted(t)
    if w > LIMIT: p.append(f"post too long: {w} weighted chars > {LIMIT}")
    return w, p

def check_sources(t):
    p = []
    if not re.search(r"https?://(x|twitter)\.com/\w+/status/\d+", t): p.append("sources reply has no story links")
    if not re.search(r"https?://suno\.com/song/", t): p.append("sources reply is missing the Suno link")
    w = weighted(t)
    if w > LIMIT: p.append(f"sources reply too long: {w} > {LIMIT}")
    return w, p

def main(argv):
    if len(argv) < 2: print(__doc__); return 2
    t = open(argv[1], encoding="utf-8").read().strip()
    w, p = check_post(t)
    msg = f"post: {w} weighted chars (limit {LIMIT}, fold {FOLD})"
    if len(argv) > 2:
        sw, sp = check_sources(open(argv[2], encoding="utf-8").read().strip()); p += sp
        msg += f"; sources: {sw}"
    print(msg)
    for x in p: print(" -", x)
    print("post lint: clean" if not p else f"post lint: {len(p)} problem(s)")
    return 1 if p else 0

if __name__ == "__main__": sys.exit(main(sys.argv))
