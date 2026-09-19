#!/usr/bin/env python3
"""Drive scripts/generate.py against a stub ComfyUI server.

Checks the client builds a valid /prompt payload and reports the images the
server returns - without needing a GPU, a model, or a real ComfyUI.
"""

import json
import subprocess
import sys
import threading
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
received = {}
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(name)


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        received["prompt"] = json.loads(self.rfile.read(length))["prompt"]
        self._send({"prompt_id": "stub-1", "number": 1})

    def do_GET(self):
        self._send({"stub-1": {"outputs": {"9": {"images": [
            {"filename": "PonyV6XL_00001_.png", "subfolder": "", "type": "output"}]}}}})


def main():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate.py"),
         "a red fox in autumn leaves", "--server", url,
         "--seed", "42", "--steps", "12", "--cfg", "6.5", "--width", "832", "--height", "1216"],
        capture_output=True, text=True, timeout=60)

    check("generate.py exits cleanly", proc.returncode == 0, proc.stderr.strip())
    check("it reports the returned image", "PonyV6XL_00001_.png" in proc.stdout, proc.stdout.strip())

    graph = received.get("prompt")
    check("it POSTed a workflow graph", isinstance(graph, dict) and bool(graph))
    if not graph:
        return 1

    encoders = [v for v in graph.values() if v["class_type"] == "CLIPTextEncode"]
    pos = next(v for v in encoders if "score_9" in v["inputs"]["text"])
    check("the score prefix is prepended to a bare prompt",
          pos["inputs"]["text"].startswith("score_9, score_8_up") and
          "a red fox in autumn leaves" in pos["inputs"]["text"], pos["inputs"]["text"][:80])
    check("the prefix is not doubled up",
          pos["inputs"]["text"].count("score_9") == 1)

    ks = next(v for v in graph.values() if v["class_type"] == "KSampler")
    check("--seed/--steps/--cfg reach the sampler",
          (ks["inputs"]["seed"], ks["inputs"]["steps"], ks["inputs"]["cfg"]) == (42, 12, 6.5),
          str(ks["inputs"]))
    check("control_after_generate is not sent to the API",
          "control_after_generate" not in ks["inputs"], str(list(ks["inputs"])))

    latent = next(v for v in graph.values() if v["class_type"] == "EmptyLatentImage")
    check("--width/--height reach the latent",
          (latent["inputs"]["width"], latent["inputs"]["height"]) == (832, 1216), str(latent["inputs"]))

    # A prompt that already carries the tags must not get a second copy.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate.py"),
                    "score_9, score_8_up, a cat", "--server", url],
                   capture_output=True, text=True, timeout=60)
    pos2 = next(v for v in received["prompt"].values()
                if v["class_type"] == "CLIPTextEncode" and "score_9" in v["inputs"]["text"])
    check("an existing score prefix is left alone",
          pos2["inputs"]["text"] == "score_9, score_8_up, a cat", pos2["inputs"]["text"])

    # Unreachable server must fail with a clear message, not a traceback.
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate.py"), "x",
                          "--server", "http://127.0.0.1:1"], capture_output=True, text=True, timeout=60)
    check("a down server gives a readable error",
          bad.returncode != 0 and "cannot reach ComfyUI" in bad.stderr and "Traceback" not in bad.stderr,
          bad.stderr.strip()[:120])

    server.shutdown()
    print()
    print("FAILED: " + ", ".join(failures) if failures else "all generate.py tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
