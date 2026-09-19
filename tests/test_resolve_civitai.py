import json, subprocess, sys

R = ["python3", "scripts/resolve_civitai.py"]

def run(doc, match="V6 XL"):
    p = subprocess.run(R + [match], input=json.dumps(doc), capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  <- " + detail) if not cond and detail else ""))
    if not cond: fails.append(name)

# 1. /models/<id> shape: several versions, V6 XL is not first, extra files present.
models_doc = {
  "name": "Pony Diffusion V6 XL",
  "modelVersions": [
    {"name": "V7 alpha", "id": 999, "files": [
        {"name": "v7.safetensors", "primary": True, "type": "Model", "sizeKB": 100,
         "downloadUrl": "https://civitai.com/api/download/models/999",
         "hashes": {"SHA256": "AAAA"}}]},
    {"name": "V6 XL", "id": 290640, "files": [
        {"name": "ponyVAE.safetensors", "type": "VAE", "sizeKB": 300,
         "downloadUrl": "https://civitai.com/api/download/models/290640?type=VAE",
         "hashes": {"SHA256": "CCCC"}},
        {"name": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "primary": True,
         "type": "Model", "sizeKB": 6938040,
         "downloadUrl": "https://civitai.com/api/download/models/290640",
         "hashes": {"SHA256": "67AB2FD8EC439A89B3FEDB15CC65F54336AF163C7EB5E4F2ACC98F090A29B0B3"}},
    ]},
  ],
}
rc, out, err = run(models_doc)
url, sha, kb, name = (out.split("\t") + ["", "", "", ""])[:4]
check("selects the V6 XL version, not the newest", rc == 0 and "290640" in url, f"rc={rc} out={out!r} err={err!r}")
check("skips the VAE, picks the primary Model file", name.startswith("ponyDiffusionV6XL"), name)
check("lowercases the sha256", sha == sha.lower() and sha.startswith("67ab"), sha)
check("passes sizeKB through", kb == "6938040", kb)

# 2. /model-versions/<id> shape: a bare version object, no modelVersions key.
version_doc = {"name": "V6 XL", "id": 290640, "files": [
    {"name": "pony.safetensors", "primary": True, "type": "Model", "sizeKB": 6938040,
     "downloadUrl": "https://civitai.com/api/download/models/290640", "hashes": {"SHA256": "BBBB"}}]}
rc, out, err = run(version_doc)
check("handles a single model-version response", rc == 0 and "290640" in out, f"rc={rc} err={err!r}")

# 3. No name match -> falls back to the first (newest) version rather than failing.
rc, out, err = run(models_doc, match="nonexistent")
check("falls back to newest when the name does not match", rc == 0 and "/999" in out, out)

# 4. Missing hash is tolerated (empty field), not a crash.
nohash = {"name": "V6 XL", "files": [
    {"name": "p.safetensors", "primary": True, "type": "Model",
     "downloadUrl": "https://x/1"}]}
rc, out, err = run(nohash)
check("tolerates a missing SHA256", rc == 0 and out.split("\t")[1] == "", out)

# 5. Error paths exit non-zero with a message instead of printing garbage.
rc, out, err = run({"name": "V6 XL", "files": []})
check("errors when a version has no files", rc != 0 and err, f"rc={rc}")
p = subprocess.run(R, input="<html>403 Forbidden</html>", capture_output=True, text=True)
check("errors clearly on a non-JSON (HTML) response", p.returncode != 0 and "did not return JSON" in p.stderr, p.stderr)
rc, out, err = run({"name": "V6 XL", "files": [{"name": "p.safetensors", "primary": True, "type": "Model"}]})
check("errors when there is no downloadUrl", rc != 0 and "downloadUrl" in err, err)

print()
print("FAILED: " + ", ".join(fails) if fails else "all resolver tests passed")
sys.exit(1 if fails else 0)
