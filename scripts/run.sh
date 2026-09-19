#!/usr/bin/env bash
# Start the ComfyUI server using the virtualenv created by install_comfyui.sh.
# Any extra arguments are passed straight through to ComfyUI's main.py, e.g.
#
#   ./scripts/run.sh --listen 0.0.0.0 --port 8189
#   ./scripts/run.sh --lowvram

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

[ -d "$COMFY_DIR" ] || die "no ComfyUI at $COMFY_DIR - run ./scripts/install_comfyui.sh first"

if   [ -x "$COMFY_DIR/.venv/bin/python" ];        then VPY="$COMFY_DIR/.venv/bin/python"
elif [ -x "$COMFY_DIR/.venv/Scripts/python.exe" ]; then VPY="$COMFY_DIR/.venv/Scripts/python.exe"
else die "no virtualenv at $COMFY_DIR/.venv - run ./scripts/install_comfyui.sh first"
fi

shopt -s nullglob
CKPTS=("$CHECKPOINT_DIR"/*.safetensors "$CHECKPOINT_DIR"/*.ckpt)
shopt -u nullglob
if [ ${#CKPTS[@]} -eq 0 ]; then
  warn "no checkpoints in $CHECKPOINT_DIR - run ./scripts/download_model.sh"
  warn "ComfyUI will still start, but the workflow will not be able to load a model."
fi

info "starting ComfyUI (Ctrl-C to stop)"
cd "$COMFY_DIR"
exec "$VPY" main.py "$@"
