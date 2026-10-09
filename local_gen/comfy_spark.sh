#!/bin/bash
# Trial ComfyUI on the Spark host (DGX Spark). Usage: comfy_spark.sh start|stop|status|logs
# Runs in Docker (NGC PyTorch 26.03, CUDA 13.2, sm_121) with --restart no, bound to the tailnet IP only.
IMG=nvcr.io/nvidia/pytorch:26.03-py3
NAME=comfyui-trial
BIND=${COMFY_BIND:-127.0.0.1}
case "$1" in
 setup)
  docker run --rm --gpus all -v /opt/comfyui:/opt/comfyui -w /opt/comfyui $IMG bash -lc '
   set -e
   [ -x venv/bin/python ] || python -m venv --system-site-packages venv
   grep -viE "^(torch|torchvision|torchaudio)([<>=~ ]|$)" ComfyUI/requirements.txt > /tmp/req.txt
   venv/bin/pip install -q -r /tmp/req.txt
   venv/bin/python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"'
  ;;
 start)
  docker rm -f $NAME >/dev/null 2>&1
  docker run -d --name $NAME --restart no --gpus all --ipc host --ulimit memlock=-1 --ulimit stack=67108864 \
   --network host -v /opt/comfyui:/opt/comfyui -w /opt/comfyui/ComfyUI \
   -e PYTHONUNBUFFERED=1 $IMG \
   /opt/comfyui/venv/bin/python main.py --listen $BIND --port 8188 \
   --output-directory /opt/comfyui/output --input-directory /opt/comfyui/input --extra-model-paths-config /opt/comfyui/extra_model_paths.yaml $COMFY_ARGS
  ;;
 stop) docker rm -f $NAME ;;
 status) docker ps --filter name=$NAME; curl -s -m 5 http://$BIND:8188/system_stats | head -c 600; echo ;;
 logs) docker logs --tail ${2:-50} $NAME ;;
 *) echo "usage: $0 setup|start|stop|status|logs"; exit 1;;
esac
