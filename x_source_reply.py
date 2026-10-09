#!/usr/bin/env python3
"""Second daily post (18 Oct 2026, the owner approved ONE extra post per day): after the daily post, reply to the MAIN
story's source post with the same video, a short human line and a link to our post.

usage:
  x_source_reply.py <day_dir> [--video FILE] [--text-file FILE] [--post-url URL] [--source-id ID] [--dry-run]

- Main source post: first x.com/<handle>/status/<id> link under the main story (headline.json "main_story") in
  stories.md. Override with --source-id.
- Text: <day>/post/source_reply.txt (default "Turned this into a song 🎶 {POST_URL}"). {POST_URL} is replaced with our
  daily post's URL; if the text has no {POST_URL} and no x.com link, the URL is appended. Our post URL comes from
  --post-url, else the latest "- post: https://x.com/..." line in <day>/log.md.
- Video: --video, else <day>/video_cine_real_v4.mp4 (else the newest video*.mp4 that isn't a *_chat* copy).
- Order: 1) reply with the video. 2) On a 403 or reply-restriction error: quote-post (quote_tweet_id) with the video,
  tagging @author. 3) X API v2 does not allow media together with quote_tweet_id; if X rejects that, post the video with
  "@author <line> <their post URL> <our post URL>" (mode "quote_link"; X shows their post as a link).
  The video is uploaded ONCE; the media_id is cached in <day>/post/source_media.json and reused for ~20 h.
- Refuses to run if <day>/post/source_reply_result.json (or <day>/source_reply_result.json) exists.
  Writes {"mode": "reply"|"quote"|"quote_link", "url", "id", "source_id", "source_url", ...} there on success.
"""
import argparse, glob, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_post as XP
import post_lint as PL

STATUS = re.compile(r"https?://(?:x|twitter)\.com/(\w+)/status/(\d+)")
RESTRICT = re.compile(r"not allowed to reply|reply to this conversation is not allowed|reply.{0,40}(restricted|not permitted|"
                      r"limited)|who can reply|reply_settings|mentioned (by|in)", re.I)
MEDIA_TTL = 20 * 3600


def main_source(day):
    h = XP.json.load(open(os.path.join(day, "headline.json"))) if os.path.exists(os.path.join(day, "headline.json")) else {}
    n = h.get("main_story")
    txt = open(os.path.join(day, "stories.md"), encoding="utf-8").read()
    secs = re.split(r"(?m)^##\s+", txt)
    pick = None
    for s in secs:
        m = re.match(r"(\d+)\.", s)
        if m and n is not None and int(m.group(1)) == int(n):
            pick = s; break
    if pick is None:                      # no headline.json: first story
        pick = next((s for s in secs if re.match(r"\d+\.", s)), txt)
    m = STATUS.search(pick)
    if not m:
        raise SystemExit(f"no x.com status link for main story {n} in stories.md")
    return {"story": n, "title": pick.splitlines()[0].strip(), "handle": m.group(1), "id": m.group(2),
            "url": f"https://x.com/{m.group(1)}/status/{m.group(2)}"}


def our_post_url(day, override):
    if override: return override
    lp = os.path.join(day, "log.md")
    urls = re.findall(r"-\s*post:\s*(https://x\.com/\w+/status/\d+)", open(lp).read()) if os.path.exists(lp) else []
    if not urls:
        raise SystemExit("our daily post URL not found (no '- post: https://x.com/...' in log.md); pass --post-url")
    return urls[-1]


def pick_video(day, v):
    if v: return v
    p = os.path.join(day, "video_cine_real_v4.mp4")
    if os.path.exists(p): return p
    c = sorted((f for f in glob.glob(os.path.join(day, "video*.mp4")) if "chat" not in os.path.basename(f)),
               key=os.path.getmtime)
    if not c: raise SystemExit("no video found; pass --video")
    return c[-1]


def texts(day, tf, post_url, src):
    path = tf or os.path.join(day, "post", "source_reply.txt")
    base = open(path, encoding="utf-8").read().strip() if os.path.exists(path) else "Turned this into a song 🎶 {POST_URL}"
    line = base.replace("{POST_URL}", "").strip()
    reply = base.replace("{POST_URL}", post_url) if "{POST_URL}" in base else \
        (base if STATUS.search(base) else f"{base} {post_url}")
    quote = f"@{src['handle']} {line} {post_url}"
    quote_link = f"@{src['handle']} {line} {src['url']} {post_url}"
    return path if os.path.exists(path) else None, reply.strip(), quote.strip(), quote_link.strip()


def media_id(c, day, video):
    cache = os.path.join(day, "post", "source_media.json")
    d = XP.json.load(open(cache)) if os.path.exists(cache) else {}
    if d.get("video") == os.path.abspath(video) and time.time() - d.get("t", 0) < MEDIA_TTL and d.get("media_id"):
        return d["media_id"], True
    mid = XP.upload_video(c, video)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump({"media_id": str(mid), "video": os.path.abspath(video), "t": time.time()}, open(cache, "w"))
    return str(mid), False


def create(c, body):
    return XP.call(c, "POST", f"{XP.API}/2/tweets", json_body=body)["data"]["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day"); ap.add_argument("--video"); ap.add_argument("--text-file")
    ap.add_argument("--post-url"); ap.add_argument("--source-id"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    day = os.path.abspath(a.day)
    res_path = os.path.join(day, "post", "source_reply_result.json")
    for p in (res_path, os.path.join(day, "source_reply_result.json")):
        if os.path.exists(p):
            print(json.dumps({"status": "skipped", "reason": "already done", "result_file": p,
                              "result": json.load(open(p))})); return 0
    src = main_source(day)
    if a.source_id:
        src.update(id=a.source_id, url=f"https://x.com/{src['handle']}/status/{a.source_id}")
    post_url = our_post_url(day, a.post_url)
    video = pick_video(day, a.video)
    tfile, reply, quote, quote_link = texts(day, a.text_file, post_url, src)
    plan = {"source": src, "our_post": post_url, "video": video, "video_mb": round(os.path.getsize(video) / 1e6, 1),
            "text_file": tfile or "(default text; write post/source_reply.txt)",
            "reply_text": reply, "quote_text": quote, "quote_link_text": quote_link,
            "weighted": {"reply": PL.weighted(reply), "quote": PL.weighted(quote), "quote_link": PL.weighted(quote_link)},
            "steps": ["upload video once (cache post/source_media.json)",
                      f"reply to {src['id']} with media", "on 403/reply restriction: quote_tweet_id + media",
                      "if X rejects media+quote: media post with their URL + @author (quote_link)"],
            "result_file": res_path}
    if a.dry_run:
        print(json.dumps({"status": "dry_run", **plan}, indent=1, ensure_ascii=False)); return 0
    c = XP.load_creds()
    mid, cached = media_id(c, day, video)
    out = {"source_id": src["id"], "source_url": src["url"], "source_handle": src["handle"], "our_post": post_url,
           "media_id": mid, "media_reused": cached, "errors": []}
    mode, tid = None, None
    try:
        tid = create(c, {"text": reply, "media": {"media_ids": [mid]}, "reply": {"in_reply_to_tweet_id": src["id"]}})
        mode = "reply"
    except RuntimeError as e:
        msg = str(e); out["errors"].append(f"reply: {msg[:300]}")
        if not (" failed 403" in msg or RESTRICT.search(msg)):
            print(json.dumps({"status": "failed", **out})); return 1
        try:
            tid = create(c, {"text": quote, "quote_tweet_id": src["id"], "media": {"media_ids": [mid]}}); mode = "quote"
        except RuntimeError as e2:
            out["errors"].append(f"quote: {str(e2)[:300]}")
            try:
                tid = create(c, {"text": quote_link, "media": {"media_ids": [mid]}}); mode = "quote_link"
            except RuntimeError as e3:
                out["errors"].append(f"quote_link: {str(e3)[:300]}")
                print(json.dumps({"status": "failed", **out})); return 1
    me = XP.call(c, "GET", f"{XP.API}/2/users/me")["data"]["username"]
    out.update(status="ok", mode=mode, id=tid, url=f"https://x.com/{me}/status/{tid}",
               text={"reply": reply, "quote": quote, "quote_link": quote_link}[mode],
               posted_at=time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    os.makedirs(os.path.dirname(res_path), exist_ok=True)
    json.dump(out, open(res_path, "w"), indent=1, ensure_ascii=False)
    with open(os.path.join(day, "log.md"), "a") as f:
        f.write(f"- source {mode}: {out['url']} (to {src['url']})\n")
    print(json.dumps(out, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())
