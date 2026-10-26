# TikTok + YouTube Shorts via Postiz

Integrations: TikTok = $POSTIZ_TIKTOK_ID (tiktok-business), YouTube = $POSTIZ_YOUTUBE_ID (youtube), set in the local config
MCP namespace: user-Postiz. It has no local-file upload tool.

## 1. Prepare file
ffmpeg -i <day>/video_karaoke.mp4 -c:v libx264 -preset slow -b:v 5000k -maxrate 7000k -bufsize 10000k \
  -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart <day>/video_karaoke_tiktok.mp4   (~64 MB for 2:19)

## 2. Get it into Postiz
PATH=$(tools/postiz_upload.sh <day>/video_karaoke_tiktok.mp4)   # POST https://api.postiz.com/public/v1/upload, header Authorization: $POSTIZ_API_KEY (raw key, never print)
Returns https://uploads.postiz.com/<id>.mp4, status ready. Use directly as the attachment for TikTok AND YouTube.

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
tools/tiktok_backlog.tsv (columns include tiktok_status/scheduled_utc/postiz_id). Post 1/day, separate from the daily
post. The 5pm routine skips rows where tiktok_status=scheduled.
