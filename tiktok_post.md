# TikTok + YouTube Shorts via Postiz (status 2026-10-21 17:40 BST)

Integrations: TikTok = cmvib9c1p0kguoh0yo4m9qal2 (tiktok-business), YouTube = cmvib71jb0kewoh0y361dzh2u (youtube)
MCP namespace: user-Postiz. It has no local-file upload tool.

## 1. Prepare file
ffmpeg -i <day>/video_karaoke.mp4 -c:v libx264 -preset slow -b:v 5000k -maxrate 7000k -bufsize 10000k \
  -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart <day>/video_karaoke_tiktok.mp4   (~64 MB for 2:19)

## 2. Get it into Postiz  (WORKING since 2026-10-21)
PATH=$(tools/postiz_upload.sh <day>/video_karaoke_tiktok.mp4)   # POST https://api.postiz.com/public/v1/upload, header Authorization: $POSTIZ_API_KEY (raw key, never print)
Returns https://uploads.postiz.com/<id>.mp4, status ready. Use directly as the attachment for TikTok AND YouTube.
Old notes below:
uploadFromUrlTool needs a PUBLIC https URL. Options:
 a) Postiz public API: POST https://api.postiz.com/public/v1/upload (multipart, Authorization: <API key>)
    or `postiz upload <file>` CLI. Needs a Postiz API key (Settings > Developers > Public API) stored
    as an env var on the box. RECOMMENDED.
 b) Cloudflare R2 public bucket. The MCP can only create/list buckets, not upload objects;
    needs wrangler or an S3 token.
 c) Anonymous hosts: auto-review blocks them. A one-off approved litterbox upload returned HTTP 500, then an empty response.
Then: uploadFromUrlTool {url, adjust:true} -> poll mediaStatusTool until "ready" -> use returned path.

## 3. TikTok post (integrationSchedulePostTool)
type "now", date = current UTC ISO. Content as <p> lines, no links, max 2200 chars.
settings: content_posting_method=DIRECT_POST, privacy_level=PUBLIC_TO_EVERYONE (no-op for video on Business API),
 video_made_with_ai=true, duet=true, stitch=true, comment=true, autoAddMusic=no,
 brand_content_toggle=false, brand_organic_toggle=false, title (<=90 chars). Do NOT set music (track is original Suno).
The TikTok app must have verified the media domain; Postiz-hosted paths satisfy this.
Then check state/error with postsListTool (window: today 00:00 to tomorrow UTC).

## 4. YouTube Shorts (same media path)
settings: title "<Song> | AI news song #Shorts" (<=100), type=public, selfDeclaredMadeForKids=no, tags [{value,label}].
Postiz has NO altered/synthetic-content field; set it by hand in YouTube Studio if needed.
Description: hook + Made by Grok Bot + 'Inspired by Claudia by anabology (claudia.gallery)' + hashtags + Suno link (links OK). Must be <=3 min and vertical.

## Caption template
<p>"<hook>" <emoji> <one-line story></p><p><Song title></p><p>Made by Grok Bot</p><p>Inspired by Claudia by anabology (claudia.gallery)</p>
<p>#slopcore #AInews #aimusic #suno #grok #<topic></p>

## Backlog
tools/tiktok_backlog.tsv. Post 1/day, separate from the daily post. Nothing has been posted yet.

## First run 2026-10-21 17:34 BST
TikTok post cmvic1n6i0d7ypg0ybfrjf0tv, YouTube post cmvic1nfk0d7zpg0y5707sq7u (one integrationSchedulePostTool call, two socialPost items).
Queued, then poll postsListTool for state PUBLISHED or ERROR.

## Backlog run 2026-10-21
All 11 include=yes rows were scheduled to TikTok at 12:30 and 20:00 London time, 22-27 Oct (BST until 25 Oct = 11:30/19:00Z, then GMT).
Encode and upload script: suno-daily/tiktok_backlog/run.sh (the MP4s are in tiktok_backlog/). The TSV has tiktok_status/scheduled_utc/postiz_id columns.
5pm routine: skip rows where tiktok_status=scheduled.
