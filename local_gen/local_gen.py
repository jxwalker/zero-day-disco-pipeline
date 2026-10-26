#!/usr/bin/env python3
"""local_gen.py - trial client: render one image-to-video shot on the Spark's ComfyUI (Wan 2.2 I2V A14B FP8),
with an honest Grok fallback. NOT wired into grok_video.sh.

  local_gen.py --image still.jpg --prompt "..." --out clip.mp4 [--mode fast|full] [--w 720 --h 1280 --frames 81]
               [--fallback grok|none] [--server http://$SPARK_HOST:8188]

Exit codes: 0 = local render ok; 10 = local failed, Grok fallback produced the clip; 1 = failed.
Prints one JSON line with backend, wall time, resolution, fps and (if local) the error that caused a fallback.
"""
import argparse, json, os, subprocess, sys, time, uuid, urllib.request, urllib.parse, urllib.error

SERVER = os.environ.get("LOCAL_GEN_SERVER", "http://localhost:8188")
NEG = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
       "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走, VHS, tape, scan lines, CRT, camcorder")

# 24 Oct 2026: LTX-Video 2B 0.9.8 distilled "draft" mode for b-roll (~30 s/clip). QC lives in clip_qc.py.
NEG_LTX = ("low quality, worst quality, deformed, distorted, extra fingers, fused fingers, warped hands, melting objects, "
           "text, letters, mirrored text, upside-down text, watermark, tongue out, open mouth, grimace, pouting, duck face, "
           "face morphing, identity change, extreme close-up, zoom, crash zoom, fast camera, motion blur, jittery, shaky, VHS, tape, scan lines, CRT, camcorder, interlacing, horizontal lines, video noise")
LTX_MOTION = (" Camera: locked-off tripod with at most a very slow, subtle drift; no zoom, no push-in beyond 5 percent, "
              "framing at the end is the same as the start. The subject moves calmly and naturally; hands and objects stay solid.")

def gentle(prompt):
    """Anti-overshoot: strip aggressive camera words and pin the camera (LTX overshoots push-ins)."""
    import re
    p = re.sub(r"\b(PUSH(?:ES|ING)?\s*(?:in|IN)?|push(?:es|ing)?[- ]in|crash zoom|zoom(?:s|ing)? in|whip(?: pan)?|WHIP|RACK|rack(?:s)? focus|"
               r"ARC|arc(?:s)? round|TRACK(?:S)? in|dolly in|HANDHELD|jolting)\b", "", prompt)
    return re.sub(r"\s+", " ", p).strip() + LTX_MOTION

def workflow_ltx(image_name, prompt, w, h, frames, fps, seed, prefix):
    return {
     "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltxv-2b-0.9.8-distilled.safetensors"}},
     "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "ltxv", "device": "default"}},
     "3": {"class_type": "LoadImage", "inputs": {"image": image_name}},
     "4": {"class_type": "CLIPTextEncode", "inputs": {"text": gentle(prompt), "clip": ["2", 0]}},
     "5": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG_LTX, "clip": ["2", 0]}},
     "6": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["4", 0], "negative": ["5", 0], "vae": ["1", 2], "image": ["3", 0],
            "width": w, "height": h, "length": frames, "batch_size": 1, "strength": 1.0}},
     "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["6", 0], "negative": ["6", 1], "frame_rate": float(fps)}},
     "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["6", 2],
            "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
     "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
     "10": {"class_type": "CreateVideo", "inputs": {"images": ["9", 0], "fps": float(fps)}},
     "11": {"class_type": "SaveVideo", "inputs": {"video": ["10", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}}}

def workflow(image_name, prompt, w, h, frames, fps, mode, seed, prefix):
    if mode == "draft":
        return workflow_ltx(image_name, prompt, w, h, frames, fps, seed, prefix)
    fast = mode == "fast"
    steps, cfg, split = (4, 1.0, 2) if fast else (20, 3.5, 10)
    g = {
      "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
      "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
      "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
      "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
      "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
      "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["3", 0]}},
      "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["3", 0]}},
      "8": {"class_type": "WanImageToVideo", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "vae": ["4", 0],
             "start_image": ["5", 0], "width": w, "height": h, "length": frames, "batch_size": 1}},
    }
    hi, lo = ["1", 0], ["2", 0]
    if fast:
        g["20"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": hi, "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "strength_model": 1.0}}
        g["21"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": lo, "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "strength_model": 1.0}}
        hi, lo = ["20", 0], ["21", 0]
    g["9"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": hi, "shift": 8.0}}
    g["10"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": lo, "shift": 8.0}}
    g["11"] = {"class_type": "KSamplerAdvanced", "inputs": {"model": ["9", 0], "add_noise": "enable", "noise_seed": seed,
               "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "positive": ["8", 0], "negative": ["8", 1],
               "latent_image": ["8", 2], "start_at_step": 0, "end_at_step": split, "return_with_leftover_noise": "enable"}}
    g["12"] = {"class_type": "KSamplerAdvanced", "inputs": {"model": ["10", 0], "add_noise": "disable", "noise_seed": seed,
               "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "positive": ["8", 0], "negative": ["8", 1],
               "latent_image": ["11", 0], "start_at_step": split, "end_at_step": 10000, "return_with_leftover_noise": "disable"}}
    g["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}}
    g["14"] = {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": float(fps)}}
    g["15"] = {"class_type": "SaveVideo", "inputs": {"video": ["14", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}}
    return g

def _req(server, path, data=None, ctype=None, timeout=60):
    r = urllib.request.Request(server + path, data=data, headers={"Content-Type": ctype} if ctype else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} on {path}: {e.read()[:400].decode('utf-8', 'replace')}") from None

def upload(server, path):
    b = uuid.uuid4().hex
    name = f"lg_{uuid.uuid4().hex[:8]}_{os.path.basename(path)}"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    return json.loads(_req(server, "/upload/image", body, f"multipart/form-data; boundary={b}"))["name"]

def render_local(a):
    _req(a.server, "/system_stats", timeout=10)  # reachability
    img = upload(a.server, a.image)
    prefix = f"local_gen/{uuid.uuid4().hex[:10]}"
    g = workflow(img, a.prompt, a.w, a.h, a.frames, a.fps, a.mode, a.seed, prefix)
    pid = json.loads(_req(a.server, "/prompt", json.dumps({"prompt": g, "client_id": "local_gen"}).encode(), "application/json"))["prompt_id"]
    t0 = time.time()
    while True:
        if time.time() - t0 > a.timeout:
            try: _req(a.server, "/interrupt", b"{}", "application/json")
            except Exception: pass
            raise TimeoutError(f"no result after {a.timeout}s")
        try:
            h = json.loads(_req(a.server, f"/history/{pid}", timeout=30))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:   # tailnet blips: keep polling
            sys.stderr.write(f"local_gen: poll error {e!r}, retrying\n"); time.sleep(15); continue
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError(f"comfy error: {msgs[-1][1].get('exception_message','?') if msgs else st}")
            for out in h[pid].get("outputs", {}).values():
                for key in ("images", "videos", "gifs"):
                    for f in out.get(key, []):
                        if f.get("filename", "").endswith(".mp4"):
                            q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
                            for k in range(5):
                                try:
                                    data = _req(a.server, f"/view?{q}", timeout=300); break
                                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                                    if k == 4: raise
                                    time.sleep(15)
                            open(a.out, "wb").write(data)
                            return
            if st.get("completed"):
                raise RuntimeError("finished without an mp4 output")
        time.sleep(5)

def render_grok(a):
    """Fallback: one Grok image_to_video call through the grok CLI, the same runner style grok_video.sh uses.
    Only used when explicitly allowed (--fallback grok); costs Grok quota."""
    secs = max(1, min(15, round(a.frames / a.fps)))
    item = {"prompt": a.prompt, "first_frame": os.path.abspath(a.image), "aspect_ratio": "9:16" if a.h > a.w else "16:9",
            "duration": secs, "resolution_name": "720p"}
    task = ("You are a media generation runner. Call reference_to_video ONCE with exactly these arguments (JSON), "
            "do not retry, then reply with one line `ITEM 1: <saved path>` or `ITEM 1: FAILED <error>`.\n" + json.dumps(item))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "grok_video"))
    from real_gen import ALL_OFF                     # same tool lock-down the daily runner uses (read-only import)
    grok = os.environ.get("GROK_BIN", "/home/box/.grok/bin/grok")
    import tempfile, re
    pf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False); pf.write(task); pf.close()
    cmd = [grok, "--prompt-file", pf.name, "--output-format", "streaming-json", "--always-approve", "-m", "grok-4.7",
           "--effort", "low", "--max-turns", "4", "--disallowed-tools", ALL_OFF, "--cwd", os.path.dirname(os.path.abspath(a.out))]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    paths = re.findall(r'"path":"(/[^"]+?\.mp4)"', r.stdout.replace('\\/', '/'))
    m = paths and re.match(r"(.*)", paths[-1])
    if not m or not os.path.exists(m.group(1)):
        raise RuntimeError("grok fallback failed: " + (r.stderr[-300:] or r.stdout[-300:]))
    subprocess.run(["cp", m.group(1), a.out], check=True)

def probe(path):
    try:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                            "-of", "json", path], capture_output=True, text=True).stdout
        j = json.loads(o); s = j["streams"][0]
        return {"res": f"{s['width']}x{s['height']}", "fps": s["r_frame_rate"], "dur": float(j["format"]["duration"])}
    except Exception:
        return {}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True); p.add_argument("--prompt", required=True); p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=["fast", "full", "draft"], default="fast")
    p.add_argument("--w", type=int, default=720); p.add_argument("--h", type=int, default=1280)
    p.add_argument("--frames", type=int, default=81); p.add_argument("--fps", type=int, default=16)
    p.add_argument("--seed", type=int, default=42); p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--fallback", choices=["grok", "none"], default="none")
    p.add_argument("--server", default=SERVER)
    a = p.parse_args()
    if a.mode == "draft":     # LTX defaults: 736x1280, 121 frames @ 24 fps (~5 s)
        a.w, a.h, a.fps = (736 if a.w == 720 else a.w), a.h, (24 if a.fps == 16 else a.fps)
        a.frames = 121 if a.frames == 81 else a.frames
    t0 = time.time(); res = {"out": a.out, "mode": a.mode}
    try:
        render_local(a); res.update(backend="local-ltxv-2b-0.9.8" if a.mode == "draft" else "local-wan2.2-i2v-a14b", ok=True)
    except Exception as e:
        res.update(local_error=str(e)[:300])
        if a.fallback != "grok":
            res.update(ok=False, wall_s=round(time.time() - t0, 1)); print(json.dumps(res)); sys.exit(1)
        try:
            render_grok(a); res.update(backend="grok-fallback", ok=True)
        except Exception as e2:
            res.update(ok=False, grok_error=str(e2)[:300], wall_s=round(time.time() - t0, 1)); print(json.dumps(res)); sys.exit(1)
    res.update(wall_s=round(time.time() - t0, 1), **probe(a.out)); print(json.dumps(res))
    sys.exit(0 if res["backend"].startswith("local") else 10)

if __name__ == "__main__":
    main()
