"""Merge stable-ts forced alignment with faster-whisper free word timings.
 1. map stable-ts words onto the display tokens of each sung line
 2. sync check: time-gated DP alignment of lyric tokens vs whisper words (same normalised word,
    |dt| <= GATE) -> % of matched words within 0.3 s (raw stable-ts)
 3. repair: a line whose matched words disagree with whisper by a median > 0.3 s is re-timed from whisper
    (stable-ts sometimes smears a line over an instrumental gap); isolated words off by > 0.3 s with a
    confident whisper word (p >= 0.5) take the whisper time; unpaired words get a second chance; an unconfirmed
    first/last word parked far from its neighbour is pulled in; lines stable-ts lost are rescued from whisper
 4. same check on the final timings; display windows for each caption
usage: timings.py WORK_DIR DURATION"""
import sys, os, json, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
import common as C

work = sys.argv[1]; DUR = float(sys.argv[2])
GATE, TOL = 2.0, 0.3
sung = C.load_json(os.path.join(work, 'sung.json'))['lines']
segs = C.load_json(os.path.join(work, 'align.json'))['segments']
fw = [w for w in C.load_json(os.path.join(work, 'fw_words.json'))['words'] if C.norm(w['w'])]

# ---- 1. stable-ts words -> display tokens
L = []
direct = len(segs) == len(sung) and all(len([w for w in s['words'] if C.norm(w['word'])]) == len(l['tokens'])
                                         for s, l in zip(segs, sung))
flat = [w for s in segs for w in s['words'] if C.norm(w['word'])]
pos = 0
for li, l in enumerate(sung):
    ws = []
    if direct:
        src = [w for w in segs[li]['words'] if C.norm(w['word'])]
        ws = [[t, w['start'], w['end']] for t, w in zip(l['tokens'], src)]
    else:
        for t in l['tokens']:
            need = len(C.norm(t)); got = 0; s0 = None; e0 = None
            while got < need and pos < len(flat):
                w = flat[pos]; pos += 1
                s0 = w['start'] if s0 is None else s0; e0 = w['end']; got += len(C.norm(w['word']))
            if s0 is None:
                s0 = e0 = ws[-1][2] if ws else 0.0
            ws.append([t, s0, e0])
    L.append({k: l[k] for k in ('n', 'src', 'section', 'section_occ', 'kind', 'line_no', 'block', 'text')} |
             {'words': ws, 'src_timing': 'stable-ts'})
toks = [(li, wi) for li, l in enumerate(L) for wi in range(len(l['words']))]


def check(tag):
    """time-gated LCS between lyric tokens and whisper words; returns pairs + stats"""
    A = [(C.norm(L[li]['words'][wi][0]), L[li]['words'][wi][1]) for li, wi in toks]
    B = [(C.norm(w['w']), w['s']) for w in fw]
    n, m = len(A), len(B)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        a, ta = A[i]; Si, S1 = S[i], S[i + 1]
        for j in range(m - 1, -1, -1):
            best = S1[j] if S1[j] > Si[j + 1] else Si[j + 1]
            b, tb = B[j]
            if a == b and abs(ta - tb) <= GATE:
                v = S1[j + 1] + 1 - 0.2 * abs(ta - tb) / GATE
                if v > best: best = v
            Si[j] = best
    pairs = []; i = j = 0
    while i < n and j < m:
        a, ta = A[i]; b, tb = B[j]
        if a == b and abs(ta - tb) <= GATE and abs(S[i][j] - (S[i + 1][j + 1] + 1 - 0.2 * abs(ta - tb) / GATE)) < 1e-9:
            pairs.append((i, j)); i += 1; j += 1
        elif S[i + 1][j] >= S[i][j + 1]:
            i += 1
        else:
            j += 1
    d = [abs(A[i][1] - B[j][1]) for i, j in pairs]
    stats = {'lyric_words': n, 'whisper_words': m, 'matched': len(pairs),
             'coverage_pct': round(100 * len(pairs) / n, 1) if n else 0,
             'within_0.3s_pct': round(100 * sum(x <= TOL for x in d) / len(d), 1) if d else 0,
             'within_0.5s_pct': round(100 * sum(x <= 0.5 for x in d) / len(d), 1) if d else 0,
             'median_abs_s': round(st.median(d), 3) if d else None,
             'mean_abs_s': round(st.mean(d), 3) if d else None}
    print(f"[{tag}] matched {len(pairs)}/{n} lyric words ({stats['coverage_pct']}%), "
          f"within 0.3s: {stats['within_0.3s_pct']}%, within 0.5s: {stats['within_0.5s_pct']}%, median |dt| {stats['median_abs_s']}s")
    return pairs, stats


pairs, raw = check('raw stable-ts vs whisper')
# ---- 3. repair
match = {toks[i]: fw[j] for i, j in pairs}
fixed_lines, fixed_words = [], 0
for li, l in enumerate(L):
    ms = [(wi, match[(li, wi)]) for wi in range(len(l['words'])) if (li, wi) in match]
    offs = [l['words'][wi][1] - w['s'] for wi, w in ms]
    if len(ms) >= 2 and st.median([abs(o) for o in offs]) > TOL:
        med = st.median(offs)
        for wi, w in enumerate(l['words']):
            if (li, wi) in match:
                fwm = match[(li, wi)]; w[1], w[2] = fwm['s'], max(fwm['e'], fwm['s'] + 0.1)
            else:
                w[1] -= med; w[2] -= med
        l['src_timing'] = f'whisper (stable-ts off by median {med:+.2f}s)'
        fixed_lines.append(li)
    else:
        for wi, fwm in ms:
            w = l['words'][wi]
            if abs(w[1] - fwm['s']) > TOL and fwm['p'] >= 0.5:
                w[1], w[2] = fwm['s'], max(fwm['e'], fwm['s'] + 0.1); fixed_words += 1
# second chance for words the gated check could not pair: an unused whisper word with the same spelling,
# lying between the whisper times of the neighbouring matched words (keeps order), within 4 s
used = {j for _, j in pairs}; mi = sorted(pairs)
second = 0
for k, (li, wi) in enumerate(toks):
    if (li, wi) in match: continue
    prv = [j for i2, j in mi if i2 < k]; nxt = [j for i2, j in mi if i2 > k]
    lo_t = fw[prv[-1]]['s'] if prv else -1; hi_t = fw[nxt[0]]['s'] if nxt else 1e9
    w = L[li]['words'][wi]
    c = [j for j, f in enumerate(fw) if j not in used and lo_t < f['s'] < hi_t and C.norm(f['w']) == C.norm(w[0])
         and abs(f['s'] - w[1]) <= 4 and f['p'] >= 0.3]
    # keep word order inside the line: the new time must stay between the neighbouring words of this line
    ws_ = L[li]['words']
    lo_w = ws_[wi - 1][1] - TOL if wi > 0 else -1; hi_w = ws_[wi + 1][1] + TOL if wi + 1 < len(ws_) else 1e9
    c = [j for j in c if lo_w <= fw[j]['s'] <= hi_w]
    if c:
        j = min(c, key=lambda j: abs(fw[j]['s'] - w[1])); used.add(j); match[(li, wi)] = fw[j]
        mi = sorted(mi + [(k, j)])
        if abs(fw[j]['s'] - w[1]) > TOL:
            w[1], w[2] = fw[j]['s'], max(fw[j]['e'], fw[j]['s'] + 0.1); second += 1
# stable-ts often parks the first word of a line early in a break (or the last word late) with a big gap to its
# neighbour; if whisper did not confirm that word, pull it next to its neighbour
# ...but only when whisper heard something else being sung inside that gap, or whisper also has the same word
# right next to the neighbour (then that one is used: typical for echoes/ad-libs of the last word)
gapfix = 0
mine = {id(f) for f in match.values()}
def other_words(t0, t1): return [f for f in fw if t0 < f['s'] < t1 and id(f) not in mine]
def alt_word(tok, t0, t1):
    c = [f for f in fw if t0 <= f['s'] <= t1 and C.norm(f['w']) == C.norm(tok) and id(f) not in mine]
    return c[0] if c else None
for li, l in enumerate(L):
    ws = l['words']
    alt = alt_word(ws[0][0], ws[1][1] - 1.5, ws[1][1] - 0.05) if len(ws) >= 2 and ws[1][1] - ws[0][2] > 1.2 else None
    if alt:
        ws[0][1], ws[0][2] = alt['s'], min(max(alt['e'], alt['s'] + 0.1), ws[1][1] - 0.02); gapfix += 1
    elif len(ws) >= 2 and (li, 0) not in match and ws[1][1] - ws[0][2] > 1.2 and other_words(ws[0][1] - 0.05, ws[1][1] - 0.3):
        d = min(0.45, max(0.2, ws[0][2] - ws[0][1])); ws[0][1] = ws[1][1] - d - 0.05; ws[0][2] = ws[1][1] - 0.05; gapfix += 1
    k = len(ws) - 1
    alt = alt_word(ws[k][0], ws[k - 1][1], ws[k - 1][2] + 1.5) if len(ws) >= 2 and ws[k][1] - ws[k - 1][2] > 2.0 else None
    if alt:
        ws[k][1], ws[k][2] = alt['s'], max(alt['e'], alt['s'] + 0.1); gapfix += 1
    elif len(ws) >= 2 and (li, k) not in match and ws[k][1] - ws[k - 1][2] > 2.0 and other_words(ws[k - 1][2] + 0.3, ws[k][1] + 0.05):
        d = max(0.2, ws[k][2] - ws[k][1]); ws[k][1] = ws[k - 1][2] + 0.15; ws[k][2] = ws[k][1] + min(d, 0.6); gapfix += 1
# ---- 3b. runs of lines stable-ts lost (no whisper support at all, or squashed to zero length / end of file):
# re-time from whisper words inside the gap between the neighbouring good lines; leftovers go to the next
# vocal onset in the stem
def vocal_activity():
    stem = os.path.join(work, 'sep', 'htdemucs', 'audio', 'vocals.wav')
    if not os.path.exists(stem): return None
    import numpy as np, subprocess
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', stem, '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
                         capture_output=True).stdout
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    hop = 800
    db = 20 * np.log10(np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, len(a) - hop, hop)]) + 1e-6)
    thr = max(-42.0, float(np.percentile(db, 90)) - 18)
    return db > thr, hop / 16000
ACT = vocal_activity()
def onset_after(t, limit):
    if ACT is None: return None
    act, step = ACT; i = int(t / step)
    while i + 3 < len(act) and i * step < limit:
        if act[i] and act[i + 1] and act[i + 2]: return i * step
        i += 1
    return None
def active_frac(t0, t1):
    if ACT is None or t1 <= t0: return 0.0
    act, step = ACT; a, b = int(t0 / step), max(int(t0 / step) + 1, int(t1 / step))
    seg = act[a:b]; return float(seg.mean()) if len(seg) else 0.0
def lcs_pairs(A, B):
    n, m = len(A), len(B)
    S = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            S[i][j] = S[i + 1][j + 1] + 1 if A[i] == B[j] else max(S[i + 1][j], S[i][j + 1])
    out = []; i = j = 0
    while i < n and j < m:
        if A[i] == B[j]: out.append((i, j)); i += 1; j += 1
        elif S[i + 1][j] >= S[i][j + 1]: i += 1
        else: j += 1
    return out
matched_lines = {li for (li, wi) in match}
def suspect(li):
    l = L[li]; n = len(l['words'])
    d = l['words'][-1][2] - l['words'][0][1]
    squashed = d < 0.06 * n or l['words'][0][1] >= DUR - 0.3
    smeared = d > max(10.0, 4 * MED_LINE)          # e.g. one line stretched over an instrumental break
    return 'degenerate' if (squashed or smeared) else ('unsupported' if (n >= 3 and li not in matched_lines) else None)
MED_LINE = st.median([l['words'][-1][2] - l['words'][0][1] for l in L])
sus = [suspect(i) for i in range(len(L))]
rescued = []
i = 0
while i < len(L):
    if not sus[i]: i += 1; continue
    j = i
    while j + 1 < len(L) and sus[j + 1]: j += 1
    lo = L[i - 1]['words'][-1][2] if i > 0 else 0.0
    hi = L[j + 1]['words'][0][1] if j + 1 < len(L) else DUR
    run = [(li, wi) for li in range(i, j + 1) for wi in range(len(L[li]['words']))]
    cand = [w for w in fw if lo - 0.1 < w['s'] < hi]
    pr = lcs_pairs([C.norm(L[li]['words'][wi][0]) for li, wi in run], [C.norm(w['w']) for w in cand])
    degenerate = any(sus[q] == 'degenerate' for q in range(i, j + 1))
    first = L[i]['words'][0][1]
    if len(pr) >= max(2, (0.3 if degenerate else 0.5) * len(run)):
        tm = {k: cand[q] for k, q in pr}
        ks = sorted(tm)
        for k, (li, wi) in enumerate(run):
            w = L[li]['words'][wi]
            if k in tm:
                w[1], w[2] = tm[k]['s'], max(tm[k]['e'], tm[k]['s'] + 0.1)
            else:
                before = [q for q in ks if q < k]; after = [q for q in ks if q > k]
                if before and after:
                    a, b = before[-1], after[0]; ta, tb = tm[a]['s'], tm[b]['s']
                    w[1] = ta + (tb - ta) * (k - a) / (b - a); w[2] = w[1] + 0.25
                elif after:
                    w[1] = tm[after[0]]['s'] - 0.35 * (after[0] - k); w[2] = w[1] + 0.3
                else:
                    pl, pw = run[k - 1]; prev_end = L[pl]['words'][pw][2]
                    o = onset_after(prev_end + 0.15, hi)
                    w[1] = o if o is not None else prev_end + 0.4; w[2] = min(w[1] + 0.6, hi)
        for li in range(i, j + 1): L[li]['src_timing'] = 'whisper (rescued run, stable-ts lost it)'
        rescued += list(range(i, j + 1))
    elif not degenerate:
        # plausible stable-ts timing without whisper support: keep it, unless stable-ts leaves a long gap after the
        # previous line in which the vocal stem is clearly singing (unexplained vocals) -> shift the run to that onset
        o = onset_after(lo + 0.1, first)
        if o is not None and first - lo > 2.5 and first - o > 1.5 and active_frac(o, first) > 0.8:
            sh = o - first
            for li, wi in run: L[li]['words'][wi][1] += sh; L[li]['words'][wi][2] += sh
            for li in range(i, j + 1): L[li]['src_timing'] = f'stable-ts shifted {sh:+.2f}s to vocal onset (no whisper support)'
            rescued += list(range(i, j + 1))
    else:
        # degenerate and no usable whisper evidence: start at the first vocal onset after the previous line (lines
        # usually follow on directly), ~0.5 s per word, never past the next good line
        span = max(0.5 * len(run), 1.0)
        o = onset_after(lo + 0.1, hi)
        t0 = o if o is not None else min(max(lo + 0.2, L[i]['words'][0][1]), max(lo + 0.2, hi - span))
        span = max(0.3 * len(run), min(span, hi - t0 - 0.2))
        for k, (li, wi) in enumerate(run):
            w = L[li]['words'][wi]; w[1] = t0 + span * k / len(run); w[2] = w[1] + span / len(run)
        for li in range(i, j + 1): L[li]['src_timing'] = 'spread (no whisper evidence)'
        rescued += list(range(i, j + 1))
    i = j + 1
# monotonic + sane durations
prev = 0.0
for l in L:
    for w in l['words']:
        w[1] = min(w[1], DUR - 0.3); w[2] = min(w[2], DUR - 0.05)
    for k, w in enumerate(l['words']):
        w[1] = max(w[1], prev); w[2] = max(w[2], w[1] + 0.08)
        prev = w[1] + 0.02
    for k in range(len(l['words']) - 1):
        l['words'][k][2] = min(l['words'][k][2], max(l['words'][k + 1][1], l['words'][k][1] + 0.08))
    l['start'] = l['words'][0][1]; l['end'] = l['words'][-1][2]
_, final = check('final timings vs whisper')
# ---- 4. display windows
LEAD, HOLD = 0.25, 1.2
for i, l in enumerate(L):
    ds = l['start'] - LEAD
    if i: ds = max(ds, L[i - 1]['end'] - 0.05)
    l['ds'] = max(0.0, min(ds, l['start']))
for i, l in enumerate(L):
    nxt = L[i + 1]['ds'] if i + 1 < len(L) else DUR
    l['de'] = min(nxt, l['end'] + HOLD, DUR)
    l['words'] = [[t, round(s, 3), round(e, 3)] for t, s, e in l['words']]
rep = {'tolerance_s': TOL, 'gate_s': GATE, 'raw_stable_ts': raw, 'final': final,
       'lines_retimed_from_whisper': [L[i]['text'] for i in fixed_lines], 'words_snapped_to_whisper': fixed_words, 'words_second_chance': second, 'words_gap_fixed': gapfix,
       'lines_rescued': [f"{L[i]['text']} -> {L[i]['src_timing']}" for i in rescued],
       'lines': len(L), 'first_vocal': L[0]['start'], 'last_vocal_end': L[-1]['end']}
C.save_json(L, os.path.join(work, 'timings.json'))
C.save_json(rep, os.path.join(work, 'sync_report.json'))
with open(os.path.join(work, 'timings.tsv'), 'w') as f:
    f.write('n\tsection\tline\tsung_start\tsung_end\tshown_from\tshown_to\ttiming\ttext\n')
    for l in L:
        f.write(f"{l['n']}\t{l['section']}\t{l['line_no']}\t{l['start']:.2f}\t{l['end']:.2f}\t{l['ds']:.2f}\t{l['de']:.2f}\t{l['src_timing']}\t{l['text']}\n")
print(f"retimed lines: {len(fixed_lines)}, snapped words: {fixed_words}, rescued lines: {len(rescued)}")
