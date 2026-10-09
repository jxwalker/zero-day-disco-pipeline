#!/usr/bin/env python3
"""Lyric density metrics + limits (17 Oct 2026: 'Sleeping On The Job' felt rushed).
Imported by lyrics_lint.py; run directly for a report:  lyric_metrics.py <lyrics.txt> [style.txt]"""
import os, re, sys

def syllables(word):
    w = word.lower().strip(".,!?;:'\"-()")
    if not w: return 0
    if w.isdigit(): return max(1, len(w))            # numbers should be words anyway
    w = re.sub(r"[^a-z]", "", w)
    if not w: return 0
    if len(w) <= 3: return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))

def words(line):
    return [t for t in re.split(r"[\s/]+", line.replace("—", " ").replace("–", " ")) if re.search(r"[A-Za-z0-9]", t)]

def parse(text):
    """[(section_tag, [lines], spoken)] ignoring tag-only lines inside sections; stops at [End]."""
    secs, cur = [], None
    for ln in text.splitlines():
        s = ln.strip()
        if s.lower() == "[end]": break
        if not s: continue
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            base = inner.split(":")[0].strip().lower()
            if re.match(r"(intro|verse|pre-?chorus|chorus|final chorus|post-?chorus|bridge|outro|hook|interlude)\b", base) and ":" not in inner or \
               re.match(r"(verse|chorus|final chorus|bridge|outro)\b", base):
                cur = [base, [], False]; secs.append(cur)
            elif cur is not None and re.search(r"spoken", inner, re.I):
                cur[2] = True
            continue
        if cur is None:
            cur = ["intro", [], False]; secs.append(cur)
        cur[1].append(s)
    return [tuple(c) for c in secs]

def tempo(style):
    s = style.lower()
    m = re.search(r"(\d{2,3})\s*bpm", s); bpm = int(m.group(1)) if m else None
    compound = bool(re.search(r"\b(6/8|12/8|9/8|3/4|waltz|triplet)", s))
    if compound or (bpm and bpm < 100) or re.search(r"\b(ballad|slow)\b", s): band = "slow"
    elif bpm and bpm >= 120 or re.search(r"\b(uptempo|up-tempo|fast|punk)\b", s): band = "uptempo"
    else: band = "mid"
    return bpm, compound, band

# hard limits per band (lint fails over these)
LIMITS = {
    "slow":    {"syl_max": 8,  "words_line_max": 7,  "total_words_max": 150},
    "mid":     {"syl_max": 9,  "words_line_max": 8,  "total_words_max": 165},
    "uptempo": {"syl_max": 10, "words_line_max": 9,  "total_words_max": 180},
}
COMMON = {"verse_lines_max": 4, "chorus_lines_max": 4, "final_chorus_lines_max": 5, "bridge_lines_max": 4,
          "intro_lines_max": 1, "outro_lines_max": 1, "spoken_words_line_max": 12, "song_secs": 150}

def measure(text, style=""):
    bpm, compound, band = tempo(style)
    secs = parse(text)
    rows = []
    for tag, lines, spoken in secs:
        for l in lines:
            w = words(l)
            rows.append({"sec": tag, "line": l, "spoken": spoken or tag == "outro", "words": len(w),
                         "syl": sum(syllables(x) for x in w)})
    sung = [r for r in rows if not r["spoken"]]
    tot = sum(r["words"] for r in rows)
    return {"bpm": bpm, "compound": compound, "band": band, "sections": secs, "rows": rows,
            "total_words": tot, "sung_lines": len(sung),
            "avg_words_line": round(sum(r["words"] for r in sung) / max(1, len(sung)), 1),
            "avg_syl_line": round(sum(r["syl"] for r in sung) / max(1, len(sung)), 1),
            "max_syl_line": max([r["syl"] for r in sung] or [0]),
            "words_per_sec": round(tot / COMMON["song_secs"], 2)}

def problems(text, style=""):
    m = measure(text, style); L = dict(LIMITS[m["band"]], **COMMON); p = []
    if m["total_words"] > L["total_words_max"]:
        p.append(f"too many words: {m['total_words']} > {L['total_words_max']} for a {m['band']} song (cut whole lines, not just small words)")
    for r in m["rows"]:
        if r["spoken"]:
            if r["words"] > L["spoken_words_line_max"]:
                p.append(f"spoken line too long ({r['words']} words > {L['spoken_words_line_max']}): {r['line']}")
        elif r["syl"] > L["syl_max"] or r["words"] > L["words_line_max"]:
            p.append(f"line too long ({r['syl']} syllables/{r['words']} words; max {L['syl_max']}/{L['words_line_max']}): {r['line']}")
    choruses = []
    for tag, lines, _ in m["sections"]:
        key = ("final_chorus" if tag.startswith("final") else "verse" if tag.startswith("verse") else
               "chorus" if "chorus" in tag else tag.split()[0])
        lim = L.get(f"{key}_lines_max")
        if lim and len(lines) > lim:
            p.append(f"[{tag}] has {len(lines)} lines (max {lim})")
        if key == "chorus": choruses.append(lines)
    if choruses:
        bi = lambda l: set(zip(*[re.sub(r"[^a-z ]", "", l.lower()).split()[i:] for i in range(2)]))
        sets = [bi(l) for l in choruses[0]]
        rep = any(sets[i] & sets[j] for i in range(len(sets)) for j in range(i + 1, len(sets)))
        if not rep:
            p.append("chorus needs a repeated hook (the same hook phrase sung on at least two chorus lines)")
    return m, p

if __name__ == "__main__":
    t = open(sys.argv[1]).read()
    sp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "style.txt")
    st = open(sp).read() if os.path.exists(sp) else ""
    m, p = problems(t, st)
    print({k: v for k, v in m.items() if k not in ("rows", "sections")})
    for x in p: print(" -", x)
