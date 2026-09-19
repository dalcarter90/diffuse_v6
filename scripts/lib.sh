#!/usr/bin/env bash
# Shared helpers for the diffuse_v6 setup scripts.

set -euo pipefail

# --- paths -------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Where ComfyUI is installed. Override with COMFY_DIR to keep it outside the repo.
COMFY_DIR="${COMFY_DIR:-$REPO_ROOT/ComfyUI}"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-$COMFY_DIR/models/checkpoints}"

# --- logging -----------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  _c_blue=$'\033[34m'; _c_yellow=$'\033[33m'; _c_red=$'\033[31m'
  _c_green=$'\033[32m'; _c_off=$'\033[0m'
else
  _c_blue=''; _c_yellow=''; _c_red=''; _c_green=''; _c_off=''
fi

info()  { printf '%s==>%s %s\n' "$_c_blue"   "$_c_off" "$*"; }
ok()    { printf '%s ok%s %s\n' "$_c_green"  "$_c_off" "$*"; }
warn()  { printf '%swarn%s %s\n' "$_c_yellow" "$_c_off" "$*" >&2; }
die()   { printf '%serr%s %s\n'  "$_c_red"    "$_c_off" "$*" >&2; exit 1; }

have()  { command -v "$1" >/dev/null 2>&1; }

# --- python ------------------------------------------------------------------

# ComfyUI 0.36 requires Python >= 3.10. Find an interpreter that satisfies that.
find_python() {
  local candidate
  for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3 python; do
    [ -n "$candidate" ] || continue
    have "$candidate" || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

# --- accelerator detection ---------------------------------------------------

# Echoes one of: nvidia | rocm | xpu | mps | cpu
detect_backend() {
  if [ -n "${COMFY_BACKEND:-}" ]; then
    printf '%s' "$COMFY_BACKEND"
    return 0
  fi

  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  if [ "$os" = "Darwin" ]; then
    # Apple silicon gets Metal (MPS); Intel Macs have no supported GPU path.
    if [ "$arch" = "arm64" ]; then printf 'mps'; else printf 'cpu'; fi
    return 0
  fi

  if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
    printf 'nvidia'; return 0
  fi
  if have rocminfo || [ -d /opt/rocm ]; then
    printf 'rocm'; return 0
  fi
  if have xpu-smi; then
    printf 'xpu'; return 0
  fi
  if have clinfo && clinfo 2>/dev/null | grep -qi 'Intel.*Graphics'; then
    printf 'xpu'; return 0
  fi

  printf 'cpu'
}

# The pip arguments that install torch for a given backend. Kept in one place so
# install_comfyui.sh and the docs cannot drift apart.
# Sources: ComfyUI README (manual install section), ComfyUI 0.36.0.
torch_pip_args() {
  case "$1" in
    nvidia) printf -- '--extra-index-url https://download.pytorch.org/whl/cu130' ;;
    rocm)   printf -- '--index-url https://download.pytorch.org/whl/rocm7.2' ;;
    xpu)    printf -- '--index-url https://download.pytorch.org/whl/xpu' ;;
    mps)    printf '' ;;  # default PyPI wheels carry Metal support
    cpu)    printf -- '--index-url https://download.pytorch.org/whl/cpu' ;;
    *)      die "unknown backend: $1" ;;
  esac
}

# --- hashing -----------------------------------------------------------------

sha256_of() {
  if have sha256sum; then sha256sum "$1" | cut -d' ' -f1
  elif have shasum;   then shasum -a 256 "$1" | cut -d' ' -f1
  else die "need sha256sum or shasum to verify downloads"
  fi
}
