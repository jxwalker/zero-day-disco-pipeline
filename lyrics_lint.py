#!/usr/bin/env python3
"""Pre-Suno lyric lint. Flags meta/'AI news' lines and style words in sung lines.
Exit 0 clean, 1 violations (or 0 after --fix removes them)."""
import re, sys, shutil
META = [r"\bai\s*news\b", r"\bthe\s+news\b", r"\bnews\s+(on\s+fire|ride|tonight|today)\b",
        r"\bheadlines?\b", r"\bsing\s+it\s+with\s+me\b", r"\bsing\s+along\b", r"\bthis\s+song\b",
        r"\bthe\s+show\b", r"\btune\s+in\b", r"\bbreaking\s+news\b", r"\bnews\s*(cast|feed|flash|wire)\b"]
STYLE = [r"\bjangly\b", r"\bguitars?\b", r"\bsynths?\b", r"\bsynthesi[sz]ers?\b", r"\b808s?\b", r"\bbpm\b",
         r"\bbass\s*(drop|line)\b", r"\bdrums?\b", r"\bhi-?hats?\b", r"\breverb\b", r"\bdistortion\b",
         r"\bauto-?tune\b", r"\bfalsetto\b", r"\bindie\s+rock\b", r"\bedm\b", r"\blo-?fi\b", r"\bchiptune\b",
         r"\b(male|female)\s+(lead\s+)?vocals?\b", r"\binstrumental\b", r"\btempo\b", r"\bmix\b",
         r"\bmaster(ed|ing)\b", r"\bsidechain\b", r"\bpiano\b", r"\bchords?\b", r"\briffs?\b", r"\bstrings\b", r"\bbanger\b", r"\bgenre\b"]
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
    print("lint: clean" if not bad else f"lint: {bad} violation(s)")
    sys.exit(1 if bad else 0)
if __name__ == "__main__": main()
