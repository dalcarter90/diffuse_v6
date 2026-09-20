#!/usr/bin/env python3
"""Test scripts/serve_mobile.py against a stub ComfyUI.

Covers the proxy allowlist (what must and must not reach ComfyUI), token
enforcement, and the error shown when ComfyUI is not running.
"""

import json
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(name)


class Comfy(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Comfy.seen.append(("GET", self.path))
        if self.path.startswith("/history/"):
            return self._send(200, json.dumps({"abc": {"outputs": {"9": {"images": [
                {"filename": "PonyV6XL_00001_.png", "subfolder": "", "type": "output"}]}}}}).encode(),
                "application/json")
        if self.path.startswith("/view"):
            return self._send(200, PNG, "image/png")
        return self._send(404, b"{}", "application/json")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        Comfy.seen.append(("POST", self.path))
        if self.path == "/prompt":
            try:
                json.loads(body)["prompt"]
            except Exception:
                return self._send(400, json.dumps({"error": {"message": "bad graph"}}).encode(),
                                  "application/json")
            return self._send(200, json.dumps({"prompt_id": "abc"}).encode(), "application/json")
        if self.path == "/interrupt":
            return self._send(200, b"{}", "application/json")
        return self._send(404, b"{}", "application/json")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url, token=None, method="GET", data=None):
    req = urllib.request.Request(url, method=method, data=data)
    if token:
        req.add_header("X-Token", token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def wait_up(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_proxy(port, comfy_url, token=None):
    cmd = [sys.executable, str(ROOT / "scripts" / "serve_mobile.py"),
           "--port", str(port), "--listen", "127.0.0.1", "--comfy", comfy_url]
    if token:
        cmd += ["--token", token]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_up(port):
        proc.kill()
        raise RuntimeError("proxy did not start")
    return proc


def main():
    comfy = ThreadingHTTPServer(("127.0.0.1", 0), Comfy)
    comfy_port = comfy.server_address[1]
    threading.Thread(target=comfy.serve_forever, daemon=True).start()
    comfy_url = f"http://127.0.0.1:{comfy_port}"

    port = free_port()
    proc = start_proxy(port, comfy_url)
    base = f"http://127.0.0.1:{port}"
    try:
        # --- the page and the workflow ---------------------------------------
        code, body, ctype = get(f"{base}/")
        check("serves the mobile page at /", code == 200 and b"<!DOCTYPE html>" in body)
        check("the page is sent as HTML", "text/html" in ctype, ctype)
        check("the page has a mobile viewport", b'name="viewport"' in body)

        code, body, _ = get(f"{base}/workflow.json")
        check("serves the API workflow", code == 200 and b"CheckpointLoaderSimple" in body)

        # --- the four proxied endpoints --------------------------------------
        graph = json.loads((ROOT / "workflows" / "pony_v6_txt2img_api.json").read_text())
        code, body, _ = get(f"{base}/prompt", method="POST",
                            data=json.dumps({"prompt": graph}).encode())
        check("forwards POST /prompt", code == 200 and json.loads(body)["prompt_id"] == "abc",
              body[:120].decode(errors="replace"))

        code, body, _ = get(f"{base}/history/abc")
        check("forwards GET /history/<id>", code == 200 and b"PonyV6XL_00001_" in body)

        code, body, ctype = get(f"{base}/view?filename=a.png&subfolder=&type=output")
        check("forwards GET /view and returns the image bytes", code == 200 and body == PNG)
        check("the image keeps its content type", ctype == "image/png", ctype)

        code, _, _ = get(f"{base}/interrupt", method="POST", data=b"")
        check("forwards POST /interrupt", code == 200)

        # --- everything else must be blocked ---------------------------------
        before = len(Comfy.seen)
        blocked = ["/object_info", "/queue", "/system_stats", "/userdata/x",
                   "/view_metadata/checkpoints", "/viewport", "/../etc/passwd",
                   "/history", "/models/checkpoints"]
        codes = {p: get(f"{base}{p}")[0] for p in blocked}
        check("unlisted GET endpoints are refused",
              all(c == 404 for c in codes.values()),
              str({p: c for p, c in codes.items() if c != 404}))
        check("view_metadata is not reachable via the /view allowance",
              codes["/view_metadata/checkpoints"] == 404)
        check("blocked requests never reach ComfyUI", len(Comfy.seen) == before,
              str(Comfy.seen[before:]))

        up_code = get(f"{base}/upload/image", method="POST", data=b"{}")[0]
        check("upload endpoints are refused", up_code == 404, str(up_code))

    finally:
        proc.kill()

    # --- token enforcement ----------------------------------------------------
    port = free_port()
    proc = start_proxy(port, comfy_url, token="s3cret")
    base = f"http://127.0.0.1:{port}"
    try:
        check("the page itself loads without a token (it carries the ?key= link)",
              get(f"{base}/")[0] == 200)
        check("the API is refused without a token", get(f"{base}/workflow.json")[0] == 401)
        check("a wrong token is refused", get(f"{base}/workflow.json", token="nope")[0] == 401)
        check("the right token is accepted", get(f"{base}/workflow.json", token="s3cret")[0] == 200)
        check("?key= is accepted for image loads",
              get(f"{base}/view?filename=a.png&key=s3cret")[0] == 200)
        check("a wrong ?key= is refused",
              get(f"{base}/view?filename=a.png&key=nope")[0] == 401)
        check("POST /prompt is refused without a token",
              get(f"{base}/prompt", method="POST", data=b'{"prompt":{}}')[0] == 401)
    finally:
        proc.kill()

    # --- ComfyUI unreachable --------------------------------------------------
    port, dead = free_port(), free_port()
    proc = start_proxy(port, f"http://127.0.0.1:{dead}")
    try:
        code, body, _ = get(f"http://127.0.0.1:{port}/prompt", method="POST", data=b'{"prompt":{}}')
        check("a down ComfyUI gives 502 with a useful message",
              code == 502 and b"cannot reach ComfyUI" in body and b"run.sh" in body,
              body[:160].decode(errors="replace"))
    finally:
        proc.kill()

    comfy.shutdown()
    comfy.server_close()

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all mobile server tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
