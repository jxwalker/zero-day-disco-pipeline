"""Decide which lyric lines are actually sung, in which order (Suno often repeats lines that the written
lyrics.txt lists once). Display wording always comes from lyrics.txt; this only picks the sequence.
Candidates:
  A) lyrics.txt as written
  B) the lyrics embedded in the mp3 by Suno (the lyrics it actually generated from), each line mapped
     back onto its lyrics.txt line
  H) hybrid: A with each individual difference to B switched on only if it improves the whisper match
  C) explicit override: tags.json "sung_lines": [lyrics.txt line indexes, 0-based]
C wins if given; otherwise the candidate whose words best match the free faster-whisper transcript.
usage: choose_script.py WORK_DIR AUDIO TAGS_JSON"""
import sys, os, json, difflib
sys.path.insert(0, os.path.dirname(__file__))
import common as C

work, audio, tagsp = sys.argv[1:4]
lines = C.load_json(os.path.join(work, 'lines.json'))
tags = C.load_json(tagsp, {}) or {}
fw = C.load_json(os.path.join(work, 'fw_words.json'))
hyp = [C.norm(w['w']) for w in fw['words'] if C.norm(w['w'])]


def toks(ix):
    return [C.norm(t) for i in ix for t in lines[i]['tokens'] if C.norm(t)]


def score(ix):
    cand = toks(ix)
    prev = [0] * (len(hyp) + 1)          # true LCS length (difflib blocks are not optimal)
    for a in cand:
        cur = [0]
        for j, b in enumerate(hyp):
            cur.append(prev[j] + 1 if a == b else (prev[j + 1] if prev[j + 1] > cur[j] else cur[j]))
        prev = cur
    M = prev[-1]
    return 2 * M / (len(cand) + len(hyp)), M, len(cand)


def map_embedded(text):
    emb = C.parse_lyrics(text)
    ntok = [[C.norm(t) for t in l['tokens'] if C.norm(t)] for l in lines]
    out, last, last_sid, prev_esid = [], -1, None, None
    unmapped = []
    for e in emb:
        et = [C.norm(t) for t in e['tokens'] if C.norm(t)]
        rs = [difflib.SequenceMatcher(None, et, nt, autojunk=False).ratio() for nt in ntok]
        best = max(rs) if rs else 0
        if best < 0.75:
            unmapped.append(e['text']); continue
        ok = [i for i, r in enumerate(rs) if r >= best - 0.05]
        new_sec = e['sid'] != prev_esid
        pick = None
        if not new_sec and last_sid is not None:
            same = [i for i in ok if lines[i]['sid'] == last_sid]
            nxt = [i for i in same if i > last]
            pick = nxt[0] if nxt else (max(same, key=lambda i: (i <= last, i)) if same else None)
        if pick is None:
            nxt = [i for i in ok if i > last]
            pick = nxt[0] if nxt else min(ok, key=lambda i: abs(i - last))
        out.append(pick); last = pick; last_sid = lines[pick]['sid']; prev_esid = e['sid']
    return out, unmapped


A = list(range(len(lines)))
cands = {'A_lyrics_txt': A}
emb = C.embedded_lyrics(audio)
unmapped = []
if emb:
    b, unmapped = map_embedded(emb)
    if b and b != A:
        cands['B_mp3_embedded'] = b
        # hybrid: every place where B differs from A (a repeated/extra/missing chunk) is toggled on its own
        ops = [o for o in difflib.SequenceMatcher(None, A, b, autojunk=False).get_opcodes() if o[0] != 'equal']
        def build(mask):
            out, prev = [], 0
            for (tag, i1, i2, j1, j2), on in zip(ops, mask):
                out += A[prev:i1] + (b[j1:j2] if on else A[i1:i2]); prev = i2
            return out + A[prev:]
        if len(ops) <= 8:
            masks = [[(k >> q) & 1 for q in range(len(ops))] for k in range(2 ** len(ops))]
            best = max(masks, key=lambda mk: (round(score(build(mk))[0], 6), -sum(mk)))
        else:
            best = [0] * len(ops)
            for q in range(len(ops)):
                t = best[:]; t[q] = 1
                if score(build(t))[0] > score(build(best))[0] + 1e-6: best = t
        hyb = build(best)
        for (tag, i1, i2, j1, j2), on in zip(ops, best):
            print(f"  diff {tag} lyrics[{i1}:{i2}] -> embedded[{j1}:{j2}] "
                  f"({' / '.join(lines[i]['text'] for i in b[j1:j2]) or '-'}): {'TAKE' if on else 'skip'}")
        if hyb not in cands.values():
            cands['H_hybrid'] = hyb
report = {}
for k, ix in cands.items():
    d, M, n = score(ix)
    report[k] = {'dice': round(d, 4), 'matched_words': M, 'lyric_words': n, 'lines': len(ix)}
    print(f"{k}: dice={d:.3f} matched={M}/{n} (whisper words {len(hyp)}) lines={len(ix)}")
if tags.get('sung_lines'):
    choice = 'C_override'; seq = [int(i) for i in tags['sung_lines']]
else:
    choice = max(cands, key=lambda k: (report[k]['dice'], k == 'A_lyrics_txt'))
    # prefer the written lyrics unless the alternative is clearly better
    if choice != 'A_lyrics_txt' and report[choice]['dice'] - report['A_lyrics_txt']['dice'] < 0.01:
        choice = 'A_lyrics_txt'
    seq = cands[choice]
print('chosen:', choice)
if unmapped:
    print('embedded lines not in lyrics.txt (not displayed):', unmapped)
sung = []
blk = -1; prev = None
for n, i in enumerate(seq):
    l = dict(lines[i]); l['src'] = i; l['n'] = n
    if l['sid'] != prev:
        blk += 1; prev = l['sid']
    l['block'] = blk
    sung.append(l)
C.save_json({'choice': choice, 'candidates': report, 'unmapped_embedded': unmapped, 'lines': sung},
            os.path.join(work, 'sung.json'))
open(os.path.join(work, 'lyrics_sung.txt'), 'w').write('\n'.join(l['text'] for l in sung) + '\n')
