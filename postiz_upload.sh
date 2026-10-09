#!/usr/bin/env bash
# Usage: postiz_upload.sh <file>  -> prints Postiz media path (reads POSTIZ_API_KEY from env)
set -euo pipefail
[ -n "${POSTIZ_API_KEY:-}" ] || { echo "POSTIZ_API_KEY not set" >&2; exit 1; }
f="$1"; [ -f "$f" ] || { echo "no file $f" >&2; exit 1; }
resp=$(curl -sS --fail-with-body -H "Authorization: $POSTIZ_API_KEY" -F "file=@$f" https://api.postiz.com/public/v1/upload)
echo "$resp" > /tmp/postiz_upload_last.json
python3 -c 'import json,sys; j=json.load(open("/tmp/postiz_upload_last.json")); print(j.get("path") or sys.exit("no path: "+json.dumps(j)[:300]))'
