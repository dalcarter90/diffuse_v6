#!/usr/bin/env python3
"""Serve a phone-friendly front end for a running ComfyUI.

    ./scripts/run.sh --lowvram                 # terminal 1: ComfyUI on :8188
    python3 scripts/serve_mobile.py            # terminal 2: this, on :8189

Then open http://<this-machine-ip>:8189 on your phone.

This deliberately does NOT expose ComfyUI itself. It serves the mobile page and
forwards only four endpoints - queue a job, poll it, fetch the resulting image,
cancel. Everything else returns 404, so a device on your network cannot reach
ComfyUI's file upload, model listing, or user-data endpoints through it.

ComfyUI has no authentication of any kind, so never port-forward either port to
the internet. --token adds a shared secret, which keeps other devices on your
Wi-Fi from using your GPU; it is not a substitute for a VPN. See docs/mobile.md.

Standard library only.
"""

import argparse
import json
import pathlib
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "mobile" / "index.html"
WORKFLOW = ROOT / "workflows" / "pony_v6_txt2img_api.json"

# Only these reach ComfyUI. Matched exactly, or by the /history/<id> prefix -
# a loose prefix match on "/view" would also expose /view_metadata/<folder>.
POST_PATHS = ("/prompt", "/interrupt")


def proxied_get(path):
    return path == "/view" or path.startswith("/history/")


class Handler(BaseHTTPRequestHandler):
    server_version = "diffuse_v6-mobile"
    comfy = "http://127.0.0.1:8188"
    token = None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # --- helpers -------------------------------------------------------------

    def _send(self, code, body, content_type="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The page is served from this same origin, so no CORS is needed.
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authorised(self):
        if not self.token:
            return True
        if self.headers.get("X-Token") == self.token:
            return True
        query = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(query).get("key", [None])[0] == self.token

    def _forward(self, method, path, body=None):
        """Relay one request to ComfyUI and copy the response back verbatim."""
        req = urllib.request.Request(f"{self.comfy}{path}", data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                self._send(resp.status, payload, ctype)
        except urllib.error.HTTPError as exc:
            self._send(exc.code, exc.read(), exc.headers.get("Content-Type", "text/plain"))
        except urllib.error.URLError as exc:
            self._send(502, json.dumps({
                "error": f"cannot reach ComfyUI at {self.comfy}: {exc.reason}. "
                         "Is ./scripts/run.sh running?"}))

    # --- routes --------------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/" or path == "/index.html":
            if not PAGE.is_file():
                return self._send(500, "mobile/index.html is missing", "text/plain")
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")

        if not self._authorised():
            return self._send(401, json.dumps({"error": "bad or missing token"}))

        if path == "/workflow.json":
            if not WORKFLOW.is_file():
                return self._send(500, json.dumps({
                    "error": "workflows/pony_v6_txt2img_api.json is missing; "
                             "run python3 scripts/make_workflow.py"}))
            return self._send(200, WORKFLOW.read_bytes())

        if proxied_get(path):
            return self._forward("GET", self.path)

        self._send(404, json.dumps({"error": "not proxied"}))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorised():
            return self._send(401, json.dumps({"error": "bad or missing token"}))
        if path not in POST_PATHS:
            return self._send(404, json.dumps({"error": "not proxied"}))

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        self._forward("POST", path, body)


def lan_ip():
    """Best guess at this machine's address on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packets are actually sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8189)
    ap.add_argument("--listen", default="0.0.0.0",
                    help="bind address (default 0.0.0.0, so your phone can reach it)")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188",
                    help="where ComfyUI is listening")
    ap.add_argument("--token", default=None,
                    help="require this shared secret; open the page as /?key=<token>")
    args = ap.parse_args()

    Handler.comfy = args.comfy.rstrip("/")
    Handler.token = args.token

    httpd = ThreadingHTTPServer((args.listen, args.port), Handler)
    suffix = f"/?key={args.token}" if args.token else "/"
    print(f"mobile UI   http://{lan_ip()}:{args.port}{suffix}")
    print(f"forwarding  {Handler.comfy}  (only /prompt, /history, /view, /interrupt)")
    if not args.token:
        print("note: no --token set, so anything on your network can use this. "
              "Never expose it to the internet.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
