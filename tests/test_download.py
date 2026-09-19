#!/usr/bin/env python3
"""End-to-end test of scripts/download_model.sh against a stub Civitai.

Serves a small fake "checkpoint" over HTTP with range support, so the resume,
skip-if-complete, checksum and --force paths all get exercised for real.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOB = bytes(range(256)) * 900          # 230400 bytes of deterministic content
SHA = hashlib.sha256(BLOB).hexdigest()
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(name)


class Stub(BaseHTTPRequestHandler):
    hits = {"download": 0, "ranged": 0}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/v1/models/"):
            body = json.dumps({"name": "Pony Diffusion V6 XL", "modelVersions": [
                {"name": "V7", "files": [{"name": "v7.safetensors", "primary": True,
                                          "type": "Model", "sizeKB": 1,
                                          "downloadUrl": f"http://{self.headers['Host']}/wrong",
                                          "hashes": {"SHA256": "00"}}]},
                {"name": "V6 XL", "files": [
                    {"name": "ponyVAE.safetensors", "type": "VAE", "sizeKB": 1,
                     "downloadUrl": f"http://{self.headers['Host']}/wrong",
                     "hashes": {"SHA256": "00"}},
                    {"name": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
                     "primary": True, "type": "Model", "sizeKB": len(BLOB) // 1024,
                     "downloadUrl": f"http://{self.headers['Host']}/blob",
                     "hashes": {"SHA256": SHA.upper()}}]},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/blob":
            Stub.hits["download"] += 1
            rng = self.headers.get("Range")
            start = 0
            if rng and rng.startswith("bytes="):
                Stub.hits["ranged"] += 1
                start = int(rng.split("=")[1].split("-")[0])
            chunk = BLOB[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(BLOB)-1}/{len(BLOB)}")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return

        self.send_error(404)


def run(tmp, port, *args, token="stub-token"):
    env = dict(os.environ)
    env["CIVITAI_API_BASE"] = f"http://127.0.0.1:{port}/api/v1"
    env["COMFY_DIR"] = str(tmp / "ComfyUI")
    env["CIVITAI_TOKEN"] = token
    return subprocess.run([str(ROOT / "scripts" / "download_model.sh"), *args],
                          capture_output=True, text=True, errors="replace",
                          env=env, timeout=120)


def main():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tmp = pathlib.Path(tempfile.mkdtemp())
    dest = tmp / "ComfyUI" / "models" / "checkpoints" / "ponyDiffusionV6XL.safetensors"
    try:
        # --- a clean download ------------------------------------------------
        p = run(tmp, port)
        check("downloads successfully", p.returncode == 0, p.stderr.strip()[-300:])
        check("writes the file to models/checkpoints/", dest.is_file())
        check("the content is exactly what the server served",
              dest.is_file() and dest.read_bytes() == BLOB)
        check("it verifies the checksum", "checksum verified" in p.stdout, p.stdout.strip()[-200:])
        check("it picks the V6 XL primary Model file, not the VAE or V7",
              "StartWithThisOne" in p.stdout, p.stdout.strip()[-300:])

        # --- a second run must not re-transfer --------------------------------
        before = Stub.hits["download"]
        p = run(tmp, port)
        check("a complete file is not downloaded again",
              p.returncode == 0 and Stub.hits["download"] == before, p.stdout.strip()[-200:])
        check("but it is still verified",
              "checksum verified" in p.stdout, p.stdout.strip()[-200:])

        # --- an interrupted download must resume, not be called complete ------
        dest.write_bytes(BLOB[:50000])
        p = run(tmp, port)
        check("a partial file resumes rather than being reported complete",
              p.returncode == 0 and "resuming" in p.stdout, p.stdout.strip()[-300:])
        check("the resume used a Range request", Stub.hits["ranged"] > 0)
        check("the resumed file is correct", dest.read_bytes() == BLOB)

        # --- corruption is caught ---------------------------------------------
        dest.write_bytes(bytes(len(BLOB)))       # right size, wrong bytes
        p = run(tmp, port)
        check("a corrupt file of the right size fails the checksum",
              p.returncode != 0 and "checksum mismatch" in p.stderr, p.stderr.strip()[-200:])

        # --- --force re-downloads ---------------------------------------------
        before = Stub.hits["download"]
        p = run(tmp, port, "--force")
        check("--force re-downloads and repairs the file",
              p.returncode == 0 and Stub.hits["download"] > before and dest.read_bytes() == BLOB,
              p.stdout.strip()[-200:])

        # --- an HTML error page is rejected, not saved as a model -------------
        p = run(tmp, port, "--url", f"http://127.0.0.1:{port}/404", "--out", "bad.safetensors")
        check("a failed direct download does not leave a bogus checkpoint",
              p.returncode != 0 and not (dest.parent / "bad.safetensors").is_file(),
              p.stderr.strip()[-200:])

        # --- missing token is refused before any network call -----------------
        p = run(tmp, port, "--out", "x.safetensors", token="")
        check("a missing CIVITAI_TOKEN is a clear error",
              p.returncode != 0 and "CIVITAI_TOKEN is not set" in p.stderr, p.stderr.strip()[:100])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        server.shutdown()

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all download tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
