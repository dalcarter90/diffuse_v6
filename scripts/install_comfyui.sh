#!/usr/bin/env bash
# Install ComfyUI into $COMFY_DIR with a dedicated virtualenv and the right
# PyTorch build for this machine.
#
#   ./scripts/install_comfyui.sh [--backend nvidia|rocm|xpu|mps|cpu] [--ref <git-ref>]
#
# Re-running is safe: an existing checkout is updated, an existing venv reused.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

COMFY_REPO="${COMFY_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
COMFY_REF="${COMFY_REF:-}"          # empty = default branch (master)
BACKEND=""

while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="${2:?--backend needs a value}"; shift 2 ;;
    --ref)     COMFY_REF="${2:?--ref needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$BACKEND" ] || BACKEND="$(detect_backend)"

have git || die "git is required"
PY_BIN="$(find_python)" || die "need Python 3.10 or newer (ComfyUI 0.36 requires >=3.10)"
info "python:  $PY_BIN ($("$PY_BIN" -c 'import platform;print(platform.python_version())'))"
info "backend: $BACKEND"

case "$BACKEND" in
  cpu) warn "No GPU detected. ComfyUI will run, but SDXL generation on CPU takes minutes per image." ;;
  rocm) [ "$(uname -s)" = "Linux" ] || warn "The ROCm wheels used here are Linux-only; see the ComfyUI README for Windows ROCm." ;;
esac

# --- 1. source ---------------------------------------------------------------

if [ -d "$COMFY_DIR/.git" ]; then
  info "updating existing checkout at $COMFY_DIR"
  git -C "$COMFY_DIR" fetch --tags origin
  if [ -n "$COMFY_REF" ]; then git -C "$COMFY_DIR" checkout "$COMFY_REF"; else git -C "$COMFY_DIR" pull --ff-only; fi
else
  info "cloning ComfyUI into $COMFY_DIR"
  git clone "$COMFY_REPO" "$COMFY_DIR"
  [ -n "$COMFY_REF" ] && git -C "$COMFY_DIR" checkout "$COMFY_REF"
fi
ok "ComfyUI $(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$COMFY_DIR/comfyui_version.py" 2>/dev/null || echo '(version unknown)')"

# --- 2. virtualenv -----------------------------------------------------------

VENV="$COMFY_DIR/.venv"
if [ ! -x "$VENV/bin/python" ] && [ ! -x "$VENV/Scripts/python.exe" ]; then
  info "creating virtualenv at $VENV"
  "$PY_BIN" -m venv "$VENV"
fi
if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"; else VPY="$VENV/Scripts/python.exe"; fi

"$VPY" -m pip install --upgrade pip wheel >/dev/null
ok "virtualenv ready"

# --- 3. torch ----------------------------------------------------------------

# Word-splitting is what we want here: torch_pip_args returns pip flags.
# shellcheck disable=SC2046
info "installing PyTorch for '$BACKEND' (this is the large download)"
"$VPY" -m pip install torch torchvision torchaudio $(torch_pip_args "$BACKEND")

# --- 4. ComfyUI dependencies -------------------------------------------------

info "installing ComfyUI requirements"
"$VPY" -m pip install -r "$COMFY_DIR/requirements.txt"

# --- 5. verify ---------------------------------------------------------------

info "verifying the torch install can see your accelerator"
"$VPY" - <<'PY'
import torch
print(f"  torch {torch.__version__}")
if torch.cuda.is_available():
    # Also true for ROCm builds, which expose the CUDA API surface.
    print(f"  device: {torch.cuda.get_device_name(0)}  ({torch.cuda.device_count()} available)")
elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
    print("  device: Apple Metal (MPS)")
elif hasattr(torch, "xpu") and torch.xpu.is_available():
    print(f"  device: {torch.xpu.get_device_name(0)} (Intel XPU)")
else:
    print("  device: CPU only")
PY

mkdir -p "$CHECKPOINT_DIR"
ok "ComfyUI installed at $COMFY_DIR"
echo
echo "Next: ./scripts/download_model.sh    then    ./scripts/run.sh"
