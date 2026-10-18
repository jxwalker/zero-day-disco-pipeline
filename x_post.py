#!/usr/bin/env python3
"""Post to X (@jxwalker) via the X API with OAuth 1.0a user keys.

Usage:
  x_post.py --verify
      Read-only check: prints the signed-in account. Posts nothing.
  x_post.py --text-file post.txt [--video video.mp4] [--reply-file sources.txt]
      Uploads the video (chunked), posts the text with it, then posts the
      reply under it. Prints JSON: {"url": ..., "id": ..., "reply_url": ...}.
      Runs post_lint.py first (Grok Bot / @grok / #slopcore above the fold, length, sources
      links) and refuses to post if it fails; --skip-lint only for non-daily posts the owner OKs.
  x_post.py --delete ID [ID ...]
      Deletes the given posts on the signed-in account (only with the owner's OK).

Credentials: env vars X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN,
X_ACCESS_TOKEN_SECRET, falling back to $PIPELINE_SECRETS_FILE.
Never print them.
"""
import argparse, base64, hashlib, hmac, json, os, secrets, sys, time, urllib.parse
import requests

NAMES = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
API = "https://api.x.com"
CHUNK = 4 * 1024 * 1024


def load_creds():
    c = {n: os.environ.get(n) for n in NAMES}
    if not all(c.values()):
        try:
            card = json.load(open(os.environ.get("PIPELINE_SECRETS_FILE", "secrets.json"))).get("card", {})
            for n in NAMES:
                c[n] = c[n] or card.get(n)
        except Exception:
            pass
    missing = [n for n in NAMES if not c.get(n)]
    if missing:
        sys.exit(f"missing credentials: {', '.join(missing)}")
    return c


def q(s):
    return urllib.parse.quote(str(s), safe="~")


def auth_header(c, method, url, params=None):
    """OAuth 1.0a header. params = query/form-encoded params only (not JSON/multipart)."""
    oauth = {
        "oauth_consumer_key": c["X_API_KEY"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": c["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    allp = {**(params or {}), **oauth}
    pstr = \
        "&".join(f"{k}={v}" for k, v in sorted((q(k), q(v)) for k, v in allp.items()))
    base = "&".join([method.upper(), q(url.split("?")[0]), q(pstr)])
    key = f"{q(c['X_API_SECRET'])}&{q(c['X_ACCESS_TOKEN_SECRET'])}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(oauth.items()))


def call(c, method, url, params=None, json_body=None, data=None, files=None, sign_data=False):
    sign = dict(params or {})
    if sign_data and data:
        sign.update(data)
    h = {"Authorization": auth_header(c, method, url, sign)}
    r = requests.request(method, url, params=params, json=json_body, data=data, files=files, headers=h, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {r.status_code}: {r.text[:500]}")
    return r.json() if r.text.strip() else {}


def verify(c):
    d = call(c, "GET", f"{API}/2/users/me")["data"]
    print(json.dumps({"ok": True, "username": d["username"], "id": d["id"], "name": d.get("name")}))


def upload_video_v2(c, path):
    size = os.path.getsize(path)
    init = call(c, "POST", f"{API}/2/media/upload/initialize",
                json_body={"media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"})
    mid = init["data"]["id"]
    with open(path, "rb") as f:
        i = 0
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            call(c, "POST", f"{API}/2/media/upload/{mid}/append",
                 data={"segment_index": str(i)}, files={"media": ("blob", chunk, "application/octet-stream")})
            i += 1
    fin = call(c, "POST", f"{API}/2/media/upload/{mid}/finalize").get("data", {})
    info = fin.get("processing_info")
    while info and info.get("state") in ("pending", "in_progress"):
        time.sleep(max(1, int(info.get("check_after_secs", 3))))
        st = call(c, "GET", f"{API}/2/media/upload", params={"command": "STATUS", "media_id": mid}).get("data", {})
        info = st.get("processing_info")
    if info and info.get("state") == "failed":
        raise RuntimeError(f"video processing failed: {info}")
    return mid


def upload_video_v11(c, path):
    U = "https://upload.twitter.com/1.1/media/upload.json"
    size = os.path.getsize(path)
    init = call(c, "POST", U, data={"command": "INIT", "total_bytes": str(size), "media_type": "video/mp4",
                                    "media_category": "tweet_video"}, sign_data=True)
    mid = init["media_id_string"]
    with open(path, "rb") as f:
        i = 0
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            call(c, "POST", U, data={"command": "APPEND", "media_id": mid, "segment_index": str(i)},
                 files={"media": ("blob", chunk, "application/octet-stream")})
            i += 1
    fin = call(c, "POST", U, data={"command": "FINALIZE", "media_id": mid}, sign_data=True)
    info = fin.get("processing_info")
    while info and info.get("state") in ("pending", "in_progress"):
        time.sleep(max(1, int(info.get("check_after_secs", 3))))
        info = call(c, "GET", U, params={"command": "STATUS", "media_id": mid}).get("processing_info")
    if info and info.get("state") == "failed":
        raise RuntimeError(f"video processing failed: {info}")
    return mid


def upload_video(c, path):
    try:
        return upload_video_v2(c, path)
    except Exception as e:
        print(f"v2 upload failed, trying v1.1: {e}", file=sys.stderr)
        return upload_video_v11(c, path)


def post(c, text, media_id=None, reply_to=None):
    body = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [str(media_id)]}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    return call(c, "POST", f"{API}/2/tweets", json_body=body)["data"]["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--text-file")
    ap.add_argument("--video")
    ap.add_argument("--reply-file")
    ap.add_argument("--in-reply-to", metavar="TWEET_ID", help="post the main post as a reply to this post id")
    ap.add_argument("--skip-lint", action="store_true", help="skip post_lint.py (non-daily posts only)")
    ap.add_argument("--delete", nargs="+", metavar="TWEET_ID", help="delete these post ids (own account only)")
    a = ap.parse_args()
    c = load_creds()
    if a.verify:
        return verify(c)
    if a.delete:
        res = {}
        for tid in a.delete:
            res[tid] = call(c, "DELETE", f"{API}/2/tweets/{tid}").get("data", {}).get("deleted")
        print(json.dumps({"deleted": res}))
        return
    if not a.text_file:
        ap.error("--text-file required")
    text = open(a.text_file).read().strip()
    if not a.skip_lint:   # 18 Oct 2026: daily post must credit Grok Bot, tag @grok, carry #slopcore, fit the limit
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import post_lint as PL
        _, probs = PL.check_post(text)
        if a.reply_file:
            probs += PL.check_sources(open(a.reply_file).read().strip())[1]
        if probs:
            print(json.dumps({"error": "post_lint failed, nothing posted", "problems": probs}))
            sys.exit(3)
    mid = upload_video(c, a.video) if a.video else None
    tid = post(c, text, media_id=mid, reply_to=a.in_reply_to)
    me = call(c, "GET", f"{API}/2/users/me")["data"]["username"]
    out = {"id": tid, "url": f"https://x.com/{me}/status/{tid}"}
    if a.reply_file:
        rtext = open(a.reply_file).read().strip()
        rid = post(c, rtext, reply_to=tid)
        out.update(reply_id=rid, reply_url=f"https://x.com/{me}/status/{rid}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
