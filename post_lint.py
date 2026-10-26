#!/usr/bin/env python3
"""Daily X post lint.
usage: post_lint.py [--bot suno|interesting-x] <post.txt> [sources.txt]   (default --bot suno)
--bot interesting-x: generic checks only (non-empty, no secrets, valid links, length).
Suno profile (default):   -> "post lint: clean" (exit 0) or the problems (exit 1).
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

BOTS = ("suno", "interesting-x")
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(api[_-]?key|secret|password|token)\s*[:=]\s*\S{6,})", re.I)

def check_generic(t, label="post"):
    """Each bot gets its own post checks. Generic sanity checks only."""
    p = []
    if not t.strip(): p.append(f"{label} is empty")
    if SECRET.search(t): p.append(f"{label} looks like it contains a secret/credential")
    for u in URL.findall(t):
        u = u.rstrip(".,;:!?)]}'\"")
        if not re.match(r"https?://[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?(/\S*)?$", u): p.append(f"{label} has a malformed link: {u}")
    w = weighted(t)
    if w > LIMIT: p.append(f"{label} too long: {w} weighted chars > {LIMIT}")
    return w, p

def check_post(t, bot="suno"):
    if bot == "interesting-x": return check_generic(t, "post")
    if bot != "suno": raise ValueError(f"unknown bot profile {bot!r}; use one of {BOTS}")
    p = []
    if not re.search(r"(?<![\w@])@grok\b", t, re.I): p.append("missing '@grok' mention")
    if not re.search(r"\bGrok Bot\b", t): p.append("missing 'Grok Bot' credit (e.g. 'Made by Grok Bot')")
    if not re.search(r"(?<!\w)#slopcore\b", t, re.I): p.append("missing '#slopcore'")
    h = head(t)
    for k, rx in (("@grok", r"(?<![\w@])@grok\b"), ("Grok Bot", r"\bGrok Bot\b"), ("#slopcore", r"#slopcore\b")):
        if re.search(rx, t, re.I) and not re.search(rx, h, re.I):
            p.append(f"'{k}' is below the 280-char 'Show more' fold; move the Grok Bot line up")
    # credit the inspiration on every daily post
    if "@anabology" not in t: p.append("missing credit line: 'Inspired by Claudia by @anabology (claudia.gallery)'")
    w = weighted(t)
    if w > LIMIT: p.append(f"post too long: {w} weighted chars > {LIMIT}")
    return w, p

def check_sources(t, bot="suno"):
    if bot == "interesting-x": return check_generic(t, "sources reply")
    p = []
    if not re.search(r"https?://(x|twitter)\.com/\w+/status/\d+", t): p.append("sources reply has no story links")
    if not re.search(r"https?://suno\.com/song/", t): p.append("sources reply is missing the Suno link")
    w = weighted(t)
    if w > LIMIT: p.append(f"sources reply too long: {w} > {LIMIT}")
    return w, p

def main(argv):
    bot = "suno"
    if "--bot" in argv:
        i = argv.index("--bot"); bot = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2: print(__doc__); return 2
    t = open(argv[1], encoding="utf-8").read().strip()
    w, p = check_post(t, bot)
    msg = f"post: {w} weighted chars (limit {LIMIT}, fold {FOLD})"
    if len(argv) > 2:
        sw, sp = check_sources(open(argv[2], encoding="utf-8").read().strip(), bot); p += sp
        msg += f"; sources: {sw}"
    print(msg)
    for x in p: print(" -", x)
    print("post lint: clean" if not p else f"post lint: {len(p)} problem(s)")
    return 1 if p else 0

if __name__ == "__main__": sys.exit(main(sys.argv))
