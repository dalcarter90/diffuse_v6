#!/usr/bin/env bash
# Run every check that works without a GPU or the model weights.
#
# The workflow schema checks need a ComfyUI checkout; they are skipped if there
# is none. Set COMFYUI_DIR to point at one somewhere other than ./ComfyUI.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

status=0

echo "== shell script syntax =="
for f in scripts/*.sh tests/*.sh; do
  if bash -n "$f"; then echo "PASS $f"; else echo "FAIL $f"; status=1; fi
done

echo
echo "== workflows are regenerated deterministically =="
# make_workflow.py must reproduce exactly what is committed.
before="$(cat workflows/pony_v6_txt2img.json workflows/pony_v6_txt2img_api.json)"
python3 scripts/make_workflow.py >/dev/null
after="$(cat workflows/pony_v6_txt2img.json workflows/pony_v6_txt2img_api.json)"
if [ "$before" = "$after" ]; then
  echo "PASS committed workflows match scripts/make_workflow.py output"
else
  echo "FAIL workflows/ is stale - re-run python3 scripts/make_workflow.py and commit"
  status=1
fi

echo
echo "== civitai response parser =="
python3 tests/test_resolve_civitai.py || status=1

echo
echo "== workflow graph =="
python3 tests/test_workflow.py || status=1

echo
echo "== download_model.sh (against a stub civitai) =="
python3 tests/test_download.py || status=1

echo
echo "== generate.py =="
python3 tests/test_generate.py || status=1

echo
if [ "$status" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$status"
