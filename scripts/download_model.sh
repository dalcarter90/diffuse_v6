#!/usr/bin/env bash
# Download Pony Diffusion V6 XL into ComfyUI's checkpoints folder.
#
#   export CIVITAI_TOKEN=...          # from https://civitai.com/user/account
#   ./scripts/download_model.sh
#
# Options:
#   --version-id <id>   pin a specific Civitai model version instead of resolving
#   --url <url>         download this URL directly (skips the Civitai API)
#   --out <filename>    output filename (default: ponyDiffusionV6XL.safetensors)
#   --force             re-download even if the file already exists
#
# The download resumes if interrupted, and the SHA256 is checked against the
# hash Civitai reports for the file.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# Pony Diffusion V6 XL on Civitai. The script resolves the current version
# through the API rather than hardcoding a version id, so it keeps working
# when the author publishes a new file.
CIVITAI_MODEL_ID="${CIVITAI_MODEL_ID:-257749}"
# Prefer the version whose name looks like the V6 XL release; fall back to the
# newest version the API lists.
VERSION_NAME_MATCH="${VERSION_NAME_MATCH:-V6 XL}"
# Overridable so the test suite can point at a stub server.
CIVITAI_API_BASE="${CIVITAI_API_BASE:-https://civitai.com/api/v1}"

OUT_NAME="ponyDiffusionV6XL.safetensors"
VERSION_ID=""
DIRECT_URL=""
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --version-id) VERSION_ID="${2:?}"; shift 2 ;;
    --url)        DIRECT_URL="${2:?}"; shift 2 ;;
    --out)        OUT_NAME="${2:?}"; shift 2 ;;
    --force)      FORCE=1; shift ;;
    -h|--help)    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

have curl || die "curl is required"
DEST="$CHECKPOINT_DIR/$OUT_NAME"

if [ "$FORCE" -eq 1 ] && [ -e "$DEST" ]; then
  info "--force: discarding the existing $OUT_NAME"
  rm -f "$DEST"
fi

# Whether the file already on disk is complete can only be judged against the
# size Civitai reports, so that decision is deferred until after we resolve it.
# With --url there is no metadata to compare against.
if [ -s "$DEST" ] && [ -n "$DIRECT_URL" ]; then
  ok "already present: $DEST ($(du -h "$DEST" | cut -f1))"
  echo "Re-download with --force."
  exit 0
fi

# --- resolve the download URL ------------------------------------------------

EXPECTED_SHA=""
EXPECTED_KB=""

if [ -n "$DIRECT_URL" ]; then
  URL="$DIRECT_URL"
  info "using the URL you supplied"
else
  [ -n "${CIVITAI_TOKEN:-}" ] || die "CIVITAI_TOKEN is not set.
Civitai requires an API key for model downloads. Create one at
  https://civitai.com/user/account  (\"API Keys\" section)
then re-run:
  export CIVITAI_TOKEN=your_key_here
Alternatively pass a direct link with --url, or point --url at a mirror."

  if [ -n "$VERSION_ID" ]; then
    API="$CIVITAI_API_BASE/model-versions/$VERSION_ID"
  else
    API="$CIVITAI_API_BASE/models/$CIVITAI_MODEL_ID"
  fi

  info "resolving the download from $API"
  META="$(curl -fsSL -H "Authorization: Bearer $CIVITAI_TOKEN" "$API")" \
    || die "could not reach the Civitai API. Check your network and token."

  PY_BIN="$(find_python)" || die "need Python 3.10+ to parse the API response"
  # Emits: URL<TAB>SHA256<TAB>sizeKB<TAB>reportedName
  RESOLVED="$(printf '%s' "$META" \
    | "$PY_BIN" "$REPO_ROOT/scripts/resolve_civitai.py" "$VERSION_NAME_MATCH")" \
    || die "could not work out which file to download from the Civitai response"

  IFS=$'\t' read -r URL EXPECTED_SHA EXPECTED_KB REPORTED_NAME <<<"$RESOLVED"
  info "resolved: ${REPORTED_NAME:-?} ($(awk -v kb="${EXPECTED_KB:-0}" 'BEGIN{printf "%.1f GB", kb/1048576}'))"
fi

# --- download ----------------------------------------------------------------

mkdir -p "$CHECKPOINT_DIR"

# A file that is already the advertised size needs no transfer - just verify it.
# Anything smaller is a partial download that curl -C - can resume.
NEED_DOWNLOAD=1
if [ -s "$DEST" ] && [ -n "$EXPECTED_KB" ]; then
  HAVE_BYTES="$(wc -c < "$DEST" | tr -d ' ')"
  WANT_BYTES=$((EXPECTED_KB * 1024))
  if [ "$HAVE_BYTES" -ge "$((WANT_BYTES - 1024))" ]; then
    NEED_DOWNLOAD=0
    info "$OUT_NAME is already the expected size; verifying it"
  else
    info "resuming: $HAVE_BYTES of ~$WANT_BYTES bytes already downloaded"
  fi
fi

if [ "$NEED_DOWNLOAD" -eq 1 ]; then
  info "downloading to $DEST"
  info "this is a ~6.5 GB file; it resumes if interrupted"

  # The ${AUTH[@]+...} form is needed for bash 3.2 (still the /bin/bash on
  # macOS), where expanding an empty array under `set -u` is an error.
  AUTH=()
  if [ -n "${CIVITAI_TOKEN:-}" ]; then
    AUTH=(-H "Authorization: Bearer $CIVITAI_TOKEN")
  fi

  curl -L --fail --retry 5 --retry-delay 3 --retry-connrefused \
       -C - ${AUTH[@]+"${AUTH[@]}"} -o "$DEST" "$URL" \
    || die "download failed. If Civitai returned an auth error, check CIVITAI_TOKEN."
fi

# Catch a truncated transfer, or an error page saved under the model's name.
ACTUAL_BYTES="$(wc -c < "$DEST" | tr -d ' ')"
if [ -n "$EXPECTED_KB" ]; then
  if [ "$ACTUAL_BYTES" -lt "$((EXPECTED_KB * 1024 - 1024))" ]; then
    die "download incomplete: got $ACTUAL_BYTES of ~$((EXPECTED_KB * 1024)) bytes.
Re-run the script to resume from where it stopped."
  fi
elif [ "$ACTUAL_BYTES" -lt 1000000 ]; then
  # No size was advertised (--url), so fall back to "a checkpoint is never tiny".
  warn "the download is only $ACTUAL_BYTES bytes; it begins:"
  head -c 200 "$DEST" | tr -cd '[:print:][:space:]' >&2; echo >&2
  die "that looks like an error page rather than the model."
fi

# --- verify ------------------------------------------------------------------

if [ -n "$EXPECTED_SHA" ]; then
  info "verifying SHA256 (takes a moment over 6.5 GB)"
  ACTUAL_SHA="$(sha256_of "$DEST")"
  if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    die "checksum mismatch!
  expected $EXPECTED_SHA
  got      $ACTUAL_SHA
The file is corrupt or incomplete. Re-run with --force."
  fi
  ok "checksum verified"
else
  warn "no checksum published for this file; skipping verification"
fi

ok "model ready: $DEST ($(du -h "$DEST" | cut -f1))"
echo
echo "The workflow in workflows/ expects the filename '$OUT_NAME'."
echo "Next: ./scripts/run.sh"
