#!/usr/bin/env python3
"""Pick the checkpoint file to download from a Civitai API response.

Reads the JSON body of either
  https://civitai.com/api/v1/models/<id>            (many versions), or
  https://civitai.com/api/v1/model-versions/<id>    (one version)
on stdin and prints one tab-separated line:

    downloadUrl <TAB> sha256 <TAB> sizeKB <TAB> filename

Usage: resolve_civitai.py [version-name-substring]
"""

import json
import sys


def pick_version(doc, match):
    """Prefer a version whose name contains `match`, else the first listed.

    Civitai lists versions newest-first, so the fallback is the latest release.
    """
    versions = doc.get("modelVersions") or [doc]
    if not versions:
        sys.exit("the API response listed no model versions")
    if match:
        needle = match.lower()
        for v in versions:
            if needle in (v.get("name") or "").lower():
                return v
    return versions[0]


def pick_file(version):
    """Choose the primary safetensors weight file over VAEs, configs and extras."""
    files = version.get("files") or []
    if not files:
        sys.exit("no downloadable files listed for this model version")

    def rank(f):
        name = f.get("name") or ""
        return (
            0 if f.get("primary") else 1,
            0 if f.get("type") == "Model" else 1,
            0 if name.endswith(".safetensors") else 1,
            # Prefer full precision over pruned/fp16 variants when both exist.
            0 if (f.get("metadata") or {}).get("format") == "SafeTensor" else 1,
        )

    return sorted(files, key=rank)[0]


def main():
    match = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        doc = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        sys.exit(f"the Civitai API did not return JSON: {exc}")

    version = pick_version(doc, match)
    chosen = pick_file(version)

    url = chosen.get("downloadUrl") or version.get("downloadUrl")
    if not url:
        sys.exit("the API response contained no downloadUrl")

    sha = ((chosen.get("hashes") or {}).get("SHA256") or "").lower()
    size_kb = chosen.get("sizeKB")
    name = chosen.get("name") or ""

    print("\t".join([url, sha, str(size_kb if size_kb is not None else ""), name]))


if __name__ == "__main__":
    main()
