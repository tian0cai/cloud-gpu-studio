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
python -m venv --system-site-packages /workspace/comfy-env
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
