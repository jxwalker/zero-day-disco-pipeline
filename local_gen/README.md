# local_gen (TRIAL, not wired into grok_video.sh)

Local image-to-video on the Spark host (DGX Spark, GB10, $SPARK_HOST) with ComfyUI + Wan 2.2 I2V A14B FP8 (Apache-2.0).

## On the Spark
- Everything lives in `/opt/comfyui` (owned by james):
  - `ComfyUI/` git checkout (ComfyUI 0.42.0), `venv/` (created inside the container, `--system-site-packages`, so NGC's torch is kept)
  - `models/` Wan 2.2 I2V high/low-noise 14B fp8_scaled, umt5_xxl fp8 text encoder, wan_2.1_vae, lightx2v 4-step LoRAs (~46 GB)
  - `input/`, `output/`, `logs/`, `comfy_spark.sh`, `extra_model_paths.yaml`
- Runtime: Docker image `nvcr.io/nvidia/pytorch:26.03-py3` (torch 2.11 nv26.03, CUDA 13.2, sm_121), container `comfyui-trial`,
  `--restart no` (never starts on boot), host network, ComfyUI listens on $SPARK_HOST:8188 only.
- No host packages, drivers, kernel or Tailscale settings were changed.

```
ssh -i $SPARK_SSH_KEY $SPARK_SSH /opt/comfyui/comfy_spark.sh start    # ~40 s to come up
ssh -i $SPARK_SSH_KEY $SPARK_SSH /opt/comfyui/comfy_spark.sh status
ssh -i $SPARK_SSH_KEY $SPARK_SSH /opt/comfyui/comfy_spark.sh stop     # removes the container, frees all memory
```
Full uninstall: `comfy_spark.sh stop; sudo rm -rf /opt/comfyui; docker rmi nvcr.io/nvidia/pytorch:26.03-py3`.

## On the box
- `local_gen.py --image still.jpg --prompt "..." --out clip.mp4 [--mode fast|full] [--fallback grok]`
  - fast = lightx2v 4-step LoRA, cfg 1 (~5.8 min per 720x1280 81-frame clip); full = 20 steps, cfg 3.5.
  - exit 0 local ok, 10 = Grok fallback used, 1 = failed. Prints a JSON line (backend, wall_s, res, fps).
  - `--fallback grok` makes one reference_to_video call via the grok CLI with the same tool lock-down as real_gen.py (costs Grok quota).
- `compare.sh OUT.mp4 SHEET.jpg "grok.mp4|local.mp4|label" ...` side-by-side + contact sheet.
