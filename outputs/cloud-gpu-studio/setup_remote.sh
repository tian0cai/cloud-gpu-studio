#!/bin/bash
set -euo pipefail

mkdir -p /workspace/logs
echo 'Cloning pinned ComfyUI source...'
if [ ! -d /workspace/ComfyUI/.git ]; then
  git clone https://github.com/Comfy-Org/ComfyUI.git /workspace/ComfyUI
fi
cd /workspace/ComfyUI
git checkout a5e95e675a6cd5f082965676d3fe9e7c99832024

echo 'Downloading and verifying pinned model files in parallel with dependency installation...'
python -u /workspace/bootstrap/download_models.py \
  /workspace/bootstrap/models.lock.json /workspace/ComfyUI/models &
download_pid=$!
trap 'kill "$download_pid" 2>/dev/null || true' EXIT
echo 'Installing Python dependencies...'
# Models need the persistent workspace, but a Python environment creates many
# small files. On network-backed workspaces that can stall installation for
# tens of minutes. Keep the environment on the container's local disk when it
# has enough room, while preserving the path used by the rest of the scripts.
if [ -L /workspace/comfy-env ] && [ ! -e /workspace/comfy-env ]; then
  rm /workspace/comfy-env
fi
if [ ! -e /workspace/comfy-env ]; then
  local_free_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
  if [ "${local_free_kb:-0}" -ge 12582912 ]; then
    mkdir -p /opt/cloud-gpu-studio
    python -m venv --system-site-packages /opt/cloud-gpu-studio/comfy-env
    ln -s /opt/cloud-gpu-studio/comfy-env /workspace/comfy-env
    echo 'Python environment is on local container storage.'
  else
    python -m venv --system-site-packages /workspace/comfy-env
    echo 'Local container storage is below 12 GB; Python environment is on /workspace.'
  fi
fi
/workspace/comfy-env/bin/python -m pip install -r requirements.txt > /workspace/logs/install.log 2>&1 &
pip_pid=$!
install_started=$(date +%s)
(
  while kill -0 "$pip_pid" 2>/dev/null; do
    elapsed=$(( $(date +%s) - install_started ))
    echo "Installing Python dependencies (${elapsed}s elapsed)... $(tail -n 1 /workspace/logs/install.log 2>/dev/null | cut -c1-160)"
    sleep 20
  done
) &
heartbeat_pid=$!
if ! wait "$pip_pid"; then
  kill "$heartbeat_pid" 2>/dev/null || true
  tail -80 /workspace/logs/install.log
  exit 1
fi
kill "$heartbeat_pid" 2>/dev/null || true
wait "$heartbeat_pid" 2>/dev/null || true
echo 'PYTHON_DEPENDENCIES_READY'

gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
driver_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1 | cut -d. -f1)
if [[ "$gpu_name" =~ (H200|B200|B300) ]]; then
  if [ "$driver_major" -ge 580 ]; then
    torch_cuda=$(/workspace/comfy-env/bin/python -c 'import torch; print(torch.version.cuda or "")')
    if [[ "$torch_cuda" != 13.* ]]; then
      echo "Installing CUDA 13 PyTorch for $gpu_name; model download continues in parallel..."
      /workspace/comfy-env/bin/python -m pip install --no-cache-dir --upgrade \
        torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 \
        --index-url https://download.pytorch.org/whl/cu130 > /workspace/logs/cu130-install.log 2>&1 &
      cuda_pid=$!
      while kill -0 "$cuda_pid" 2>/dev/null; do
        echo "Installing CUDA 13 PyTorch... $(tail -n 1 /workspace/logs/cu130-install.log 2>/dev/null | cut -c1-160)"
        sleep 20
      done
      if ! wait "$cuda_pid"; then
        tail -80 /workspace/logs/cu130-install.log
        exit 1
      fi
    fi
    /workspace/comfy-env/bin/python -c 'import torch, comfy_kitchen as ck; assert torch.version.cuda.startswith("13."); assert ck.sol_attn_is_available(torch.device("cuda:0"))'
    echo 'CUDA13_ATTENTION_READY'
  else
    echo "$gpu_name driver $driver_major is below 580; Sol-Attn will use dense fallback."
  fi
fi

echo 'Waiting for model download and checksum verification...'
wait "$download_pid"
trap - EXIT
echo 'INSTALL_DOWNLOAD_READY'

echo 'Starting cloud ComfyUI...'
nohup /workspace/comfy-env/bin/python main.py --listen 127.0.0.1 --port 8188 \
  --disable-auto-launch > /workspace/logs/comfy.log 2>&1 < /dev/null &

for attempt in $(seq 1 90); do
  if curl -fsS --max-time 2 http://127.0.0.1:8188/system_stats > /dev/null; then
    echo 'CLOUD_READY'
    exit 0
  fi
  sleep 2
done
tail -100 /workspace/logs/comfy.log
exit 1
