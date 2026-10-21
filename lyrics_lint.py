#!/usr/bin/env python3
"""Pre-Suno lyric lint. Flags meta/'AI news' lines and style words in sung lines, and (17 Oct) lyric density over
the BPM/metre limits in lyric_metrics.py, and (21 Oct) the viral-hit format (--no-viral skips; title from title.txt or --title=) (reads style.txt beside lyrics.txt, or --style=PATH; --no-density skips).
Exit 0 clean, 1 violations (or 0 after --fix removes them)."""
import os, re, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lyric_metrics as LM   # 17 Oct: density limits
META = [r"\bai\s*news\b", r"\bthe\s+news\b", r"\bnews\s+(on\s+fire|ride|tonight|today)\b",
        r"\bheadlines?\b", r"\bsing\s+it\s+with\s+me\b", r"\bsing\s+along\b", r"\bthis\s+song\b",
        r"\bthe\s+show\b", r"\btune\s+in\b", r"\bbreaking\s+news\b", r"\bnews\s*(cast|feed|flash|wire)\b"]
STYLE = [r"\bjangly\b", r"\bguitars?\b", r"\bsynths?\b", r"\bsynthesi[sz]ers?\b", r"\b808s?\b", r"\bbpm\b",
         r"\bbass\s*(drop|line)\b", r"\bdrums?\b", r"\bhi-?hats?\b", r"\breverb\b", r"\bdistortion\b",
         r"\bauto-?tune\b", r"\bfalsetto\b", r"\bindie\s+rock\b", r"\bedm\b", r"\blo-?fi\b", r"\bchiptune\b",
         r"\b(male|female)\s+(lead\s+)?vocals?\b", r"\binstrumental\b", r"\btempo\b", r"\bmix\b",
         r"\bmaster(ed|ing)\b", r"\bsidechain\b", r"\bpiano\b", r"\bchords?\b", r"\briffs?\b", r"\bstrings\b", r"\bbanger\b", r"\bgenre\b"]
# 21 Oct 2026 (the owner: "make sure we always follow the viral hit format"). --no-viral skips.
REQ = {"pre-chorus": r"pre-?chorus", "post-chorus": r"post-?chorus", "breakdown": r"breakdown", "final chorus": r"final chorus"}
def viral(text, title=""):
    p, secs, cur = [], [], None
    for ln in text.splitlines():
        s = ln.strip()
        if s.lower() == "[end]": break
        if not s: continue
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            base = re.split(r":|\s+-\s+|,", inner)[0].strip().lower()
            if re.match(r"(intro|verse|pre-?chorus|chorus|final chorus|post-?chorus|bridge|breakdown|outro|hook|interlude)\b", base):
                cur = {"tag": inner, "base": base, "lines": []}; secs.append(cur)
            elif cur is None:
                cur = {"tag": inner, "base": base, "lines": []}; secs.append(cur)
            continue
        if cur is None:
            cur = {"tag": "", "base": "", "lines": []}; secs.append(cur)
        cur["lines"].append(s)
    if not secs: return ["no sections"]
    f = secs[0]
    if "instrumental" in f["tag"].lower() or not f["lines"] or not re.match(r"(intro|hook|chorus)", f["base"]):
        p.append("first section must be a sung chant hook ([Intro - chant] with the hook line), no instrumental intro")
    if re.search(r"\[[^\]]*instrumental intro[^\]]*\]", text, re.I):
        p.append("no [Instrumental Intro] tags")
    before, found = 0, False
    for x in secs:
        if re.fullmatch(r"chorus", x["base"]): found = True; break
        before += len(x["lines"])
    if not found: p.append("no [Chorus] section")
    elif before > 7:
        p.append(f"first chorus too late: {before} sung lines before it (max 7 = 1 hook + 4 verse + 2 pre-chorus, ~25 s)")
    for x in secs:
        if not re.search(r"\s-\s*\S|,", x["tag"]):
            p.append(f"section [{x['tag'] or 'untagged'}] has no energy tag (e.g. [Chorus - full energy])")
    for name, rx in REQ.items():
        if not any(re.fullmatch(rx, x["base"]) for x in secs): p.append(f"missing [{name.title()} - ...] section")
    if title:
        t = re.sub(r"[^a-z ]", "", title.lower()).strip()
        for name, rx in (("chorus", r"chorus"), ("post-chorus", r"post-?chorus"), ("outro", r"outro")):
            body = " ".join(" ".join(x["lines"]) for x in secs if re.fullmatch(rx, x["base"]))
            if t and t not in re.sub(r"[^a-z ]", "", body.lower()):
                p.append(f"title phrase '{title}' not sung in the {name}")
    return p

def check(line):
    l = line.lower(); hits = []
    for p in META:
        if re.search(p, l): hits.append(("meta", p))
    for p in STYLE:
        if re.search(p, l): hits.append(("style", p))
    return hits
def main():
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    path, fix = sys.argv[1], "--fix" in sys.argv
    lines = open(path, encoding="utf-8").read().split("\n")
    out, bad, ended = [], 0, False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.lower() == "[end]": ended = True
        if ended or not s or (s.startswith("[") and s.endswith("]")):
            out.append(ln); continue
        h = check(s)
        if h:
            bad += 1
            print(f"{path}:{i}: {', '.join(sorted({k for k,_ in h}))}: {s}")
            if fix: continue
        out.append(ln)
    if fix and bad:
        shutil.copy(path, path + ".prelint")
        open(path, "w", encoding="utf-8").write("\n".join(out))
        print(f"removed {bad} line(s); backup {path}.prelint — check meter/empty sections")
        sys.exit(0)
    # 17 Oct 2026 (the owner: 'Sleeping On The Job' too wordy/rushed): hard density limits scaled by BPM/metre in style.txt
    if "--no-density" not in sys.argv:
        sp = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--style=")),
                  os.path.join(os.path.dirname(os.path.abspath(path)), "style.txt"))
        style = open(sp, encoding="utf-8").read() if os.path.exists(sp) else ""
        m, dp = LM.problems("\n".join(out), style)
        L = dict(LM.LIMITS[m["band"]], **LM.COMMON)
        print(f"density: {m['band']} (bpm={m['bpm']}, compound={m['compound']}) total_words={m['total_words']}/{L['total_words_max']} "
              f"avg_syl_line={m['avg_syl_line']} max_syl_line={m['max_syl_line']}/{L['syl_max']} words_per_sec={m['words_per_sec']}")
        for x in dp: print(f"{path}: density: {x}")
        bad += len(dp)
        if dp: print("TRIM: cut whole lines and filler words; keep each story plain and literal but in fewer words; "
                     "verses 4 lines, chorus 4 short lines with a repeated hook.")
    if "--no-viral" not in sys.argv:
        tp = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--title=")),
                  os.path.join(os.path.dirname(os.path.abspath(path)), "title.txt"))
        title = open(tp, encoding="utf-8").read().strip() if os.path.exists(tp) else ""
        vp = viral("\n".join(out), title)
        for x in vp: print(f"{path}: viral: {x}")
        bad += len(vp)
    print("lint: clean" if not bad else f"lint: {bad} violation(s)")
    sys.exit(1 if bad else 0)
if __name__ == "__main__": main()
