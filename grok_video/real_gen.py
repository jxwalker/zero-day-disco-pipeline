"""Batched Grok Imagine media generation for the cine-real style (see README "cine-real").

One headless `grok` session runs a small batch of media calls one at a time (image_gen stills, an image_edit Pip cameo,
image_to_video hero clips). Several sessions run side by side with staggered starts so the media API never sees more
than about 2 requests per second. Items that come back throttled are re-queued after a cool-down; a quota / plan
message stops all spending. Uses the signed-in Grok subscription; never an API key, never prints tokens."""
import difflib, json, os, random, re, shutil, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
import common_gv as G
from plan_gen import classify

TOOL_FOR = {'gen': 'image_gen', 'edit': 'image_edit', 'i2v': 'image_to_video', 'r2v': 'reference_to_video'}
ALL_OFF = ('web_search,web_fetch,Agent,run_terminal_command,write,search_replace,read_file,list_dir,'
           'grep,todo_write,monitor,workflow,use_tool,search_tool')


def batch_prompt(items):
    lines = []
    for k, it in enumerate(items, 1):
        if it['kind'] == 'gen':
            args = {'prompt': it['prompt'], 'aspect_ratio': it.get('aspect', '9:16')}
        elif it['kind'] == 'edit':
            args = {'prompt': it['prompt'], 'image': it['images']}
        elif it['kind'] == 'r2v':
            args = {'prompt': it['prompt'], 'first_frame': it['first_frame'], 'aspect_ratio': it.get('aspect', '9:16'),
                    'duration': it.get('duration', 4), 'resolution_name': it.get('resolution', '720p')}
            if it.get('images'):
                args['images'] = it['images']
            if it.get('last_frame'):
                args['last_frame'] = it['last_frame']
        else:
            args = {'image': it['image'], 'prompt': it['prompt'], 'duration': it.get('duration', 6),
                    'resolution_name': it.get('resolution', '720p')}
        lines.append(f"ITEM {k}: call {TOOL_FOR[it['kind']]} with exactly these arguments (JSON):\n{json.dumps(args, ensure_ascii=False)}")
    return ("You are a media generation runner. Do exactly what is listed below and nothing else.\n"
            "- Make the calls ONE AT A TIME, in order: wait for each result before making the next call. Never make two\n"
            "  calls in the same turn.\n"
            "- Copy every argument VERBATIM (do not rewrite, shorten or 'improve' any prompt).\n"
            "- Do not use any other tool. Do not read files. If a call fails, do NOT retry it; note the error and move on.\n"
            "- When all items are done, reply with one line per item: `ITEM k: <saved path>` or `ITEM k: FAILED <error>`.\n\n"
            + '\n\n'.join(lines))


def parse_log(logf):
    """[(tool, rawInput, path or None, error text)] in call order, plus all text."""
    calls, order, texts = {}, [], []
    for line in open(logf, errors='ignore'):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get('type')
        if t == 'tool_call':
            calls[d['toolCallId']] = {'tool': d.get('toolName'), 'input': d.get('rawInput') or {}, 'path': None, 'err': ''}
            order.append(d['toolCallId'])
        elif t == 'tool_call_update' and d.get('toolCallId') in calls:
            c = calls[d['toolCallId']]
            ro = d.get('rawOutput') if isinstance(d.get('rawOutput'), dict) else None
            if ro and ro.get('path'):
                c['path'] = ro['path']
            if d.get('status') == 'failed':
                c['err'] = (json.dumps(d.get('rawOutput')) + json.dumps(d.get('content')))[:600]
        elif t in ('text', 'error'):
            texts.append(str(d.get('data') or d.get('message') or ''))
    return [calls[k] for k in order], ''.join(texts)


def same_source(inp, job):
    """A video call belongs to a job only if it started from that job's own still (prompts can be near-identical)."""
    for k in ('first_frame', 'image'):
        if job.get(k) and job['kind'] in ('r2v', 'i2v') and inp.get(k) and os.path.abspath(str(inp.get(k))) != os.path.abspath(str(job[k])):
            return False
    return True


def salvage(work, jobs):
    """Resume: recover results of earlier sessions (e.g. an interrupted run) from gen_logs, matching each saved media
    call to a still-missing job by tool and prompt text. Returns the number recovered."""
    ldir = os.path.join(work, 'gen_logs')
    missing = [j for j in jobs if not os.path.exists(j['out'])]
    if not missing or not os.path.isdir(ldir):
        return 0
    got = 0
    used = set()
    for f in sorted(os.listdir(ldir)):
        if not f.endswith('.ndjson'):
            continue
        calls, _ = parse_log(os.path.join(ldir, f))
        for c in calls:
            if not c['path'] or not os.path.exists(c['path']) or c['path'] in used:
                continue
            cp = (c['input'].get('prompt') or '')[:260]
            for j in missing:
                if os.path.exists(j['out']) or TOOL_FOR[j['kind']] != c['tool']:
                    continue
                if not same_source(c['input'], j):
                    continue
                if difflib.SequenceMatcher(None, cp, j['prompt'][:260]).ratio() > 0.92:
                    used.add(c['path'])
                    os.makedirs(os.path.dirname(j['out']), exist_ok=True)
                    shutil.copyfile(c['path'], j['out'])
                    got += 1
                    break
    return got


class Batcher:
    """jobs: dicts with id, kind ('gen'|'edit'|'i2v'), prompt, out (absolute file path), optional images / image /
    duration. budget: {'gen': n, 'edit': n, 'i2v': n} maximum media calls of each kind this run."""

    def __init__(self, work, budget, batch_size=6, max_parallel=3, start_gap=8.0, timeout=420, tag='media', deadline=None):
        self.deadline = deadline        # epoch seconds: no new sessions after this, running ones are cut short
        self.work, self.budget, self.batch_size = work, dict(budget), batch_size
        self.max_parallel, self.start_gap, self.timeout, self.tag = max_parallel, start_gap, timeout, tag
        self.ldir = os.path.join(work, 'gen_logs'); os.makedirs(self.ldir, exist_ok=True)
        self.lock = threading.Lock()
        self.used = {k: 0 for k in TOOL_FOR}
        self.next_start = 0.0
        self.abort = None
        self.throttle_events = 0
        self.tries = {}
        self.results = {}
        self.n = 0

    def _wait_turn(self):
        while True:
            with self.lock:
                now = time.time()
                if now >= self.next_start:
                    self.next_start = now + self.start_gap
                    return
                wait = self.next_start - now
            time.sleep(min(wait, 3))

    def _reserve(self, items):
        with self.lock:
            ok = []
            for it in items:
                if self.abort or self.used[it['kind']] >= self.budget.get(it['kind'], 0):
                    continue
                self.used[it['kind']] += 1
                ok.append(it)
            return ok

    def _left(self):
        return None if not self.deadline else self.deadline - time.time()

    def _run_batch(self, items):
        self._wait_turn()
        left = self._left()
        if left is not None and left < 60:
            return []
        items = self._reserve(items)
        if not items:
            return []
        with self.lock:
            self.n += 1; n = self.n
        pf = os.path.join(self.work, 'prompts', f"{self.tag}_batch{n:03d}.txt")
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        open(pf, 'w').write(batch_prompt(items))
        logf = os.path.join(self.ldir, f"{self.tag}_batch{n:03d}_{time.strftime('%H%M%S')}.ndjson")
        cmd = [G.GROK, '--prompt-file', os.path.abspath(pf), '--output-format', 'streaming-json', '--always-approve',
               '-m', 'grok-4.7', '--effort', 'low', '--max-turns', str(len(items) + 3),
               '--disallowed-tools', ALL_OFF, '--cwd', os.path.abspath(self.work)]
        t0 = time.time()
        try:
            with open(logf, 'w') as out, open(logf + '.err', 'w') as er:
                tmo = self.timeout if left is None else max(60, min(self.timeout, left))
                rc = subprocess.run(cmd, stdout=out, stderr=er, timeout=tmo).returncode
        except subprocess.TimeoutExpired:
            rc = -9
        calls, text = parse_log(logf)
        alltext = text + G.read(logf + '.err')
        # match calls to items: same tool, best prompt match first (global greedy, so a skipped item can never take a
        # neighbour's picture just because it comes earlier in the list; prompts share the long look suffix)
        def sim(c, it):
            if not same_source(c['input'], it):
                return 0.0
            cp, ip = (c['input'].get('prompt') or '').strip(), it['prompt'].strip()
            if cp == ip:
                return 2.0
            return difflib.SequenceMatcher(None, cp[:300], ip[:300]).ratio()
        pairs = sorted(((sim(calls[ci], it), ii, ci) for ii, it in enumerate(items) for ci in range(len(calls))
                        if calls[ci]['tool'] == TOOL_FOR[it['kind']]), reverse=True)
        match, used_c = {}, set()
        for sc, ii, ci in pairs:
            if sc <= 0.6 or ii in match or ci in used_c:
                continue
            match[ii] = ci; used_c.add(ci)
        failed = []
        for ii, it in enumerate(items):
            c = calls[match[ii]] if ii in match else None
            if c and c['path'] and os.path.exists(c['path']):
                os.makedirs(os.path.dirname(it['out']), exist_ok=True)
                shutil.copyfile(c['path'], it['out'])
                self.results[it['id']] = {'ok': True, 'src': c['path']}
            else:
                err = (c or {}).get('err') or ('not called' if c is None else 'no path')
                failed.append((it, err, c is not None))
        nfail = len(failed)
        G.log(f"{self.tag} batch {n}: {len(items)-nfail}/{len(items)} ok in {time.time()-t0:.0f}s (rc={rc})")
        retry = []
        for it, err, called in failed:
            kind = classify(err + (alltext if not called else ''))
            k = it['id']
            self.tries[k] = self.tries.get(k, 0) + 1
            if not called:
                with self.lock:
                    self.used[it['kind']] -= 1     # never made: refund
            if kind == 'quota':
                with self.lock:
                    self.abort = self.abort or f"fatal Grok response: {err[:200]}"
            elif kind == 'throttle' or not called:
                with self.lock:
                    if called:
                        self.used[it['kind']] -= 1     # a throttled call generated nothing
                    self.throttle_events += 1
                    self.next_start = max(self.next_start, time.time() + 20 + random.random() * 10)
                if self.tries[k] <= 3:
                    retry.append(it)
            elif self.tries[k] <= 1:
                retry.append(it)                        # one reroll for a real failure
            self.results[k] = {'ok': False, 'err': err[:300]}
        return retry

    def run(self, jobs):
        t0 = time.time()
        got = salvage(self.work, jobs)
        if got:
            G.log(f"{self.tag}: recovered {got} results from earlier session logs")
        todo = [j for j in jobs if not (os.path.exists(j['out']) and os.path.getsize(j['out']) > 1000)]
        G.log(f"{self.tag}: {len(todo)} to make ({len(jobs)-len(todo)} cached), batches of {self.batch_size}, "
              f"{self.max_parallel} sessions at a time, budget {self.budget}")
        rounds = 0
        while todo and not self.abort and rounds < 4 and (self._left() is None or self._left() > 60):
            rounds += 1
            batches = [todo[i:i + self.batch_size] for i in range(0, len(todo), self.batch_size)]
            with ThreadPoolExecutor(self.max_parallel) as ex:
                retry = [it for r in ex.map(self._run_batch, batches) for it in r]
            todo = [j for j in retry if not os.path.exists(j['out'])]
            if todo:
                G.log(f"{self.tag}: {len(todo)} to retry (round {rounds + 1})")
        if self._left() is not None and self._left() <= 60 and todo:
            G.log(f"{self.tag}: time budget reached, {len(todo)} items not made")
        made = sum(1 for j in jobs if os.path.exists(j['out']))
        return {'wall_s': round(time.time() - t0, 1), 'made': made, 'wanted': len(jobs), 'used': dict(self.used),
                'budget': self.budget, 'abort': self.abort, 'throttle_events': self.throttle_events,
                'failed': {k: v for k, v in self.results.items() if not v.get('ok')}}
