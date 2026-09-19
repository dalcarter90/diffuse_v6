#!/usr/bin/env python3
"""Generate an image from the command line against a running ComfyUI server.

Start the server first (scripts/run.sh), then:

    python3 scripts/generate.py "a red fox in autumn leaves, forest, sunlight"

The score tag prefix Pony V6 needs is added for you unless the prompt already
has it. Uses only the standard library, so it needs no virtualenv.
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "workflows" / "pony_v6_txt2img_api.json"
SCORE_PREFIX = "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up"


def post_json(server, path, payload):
    req = urllib.request.Request(
        f"{server}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def get_json(server, path):
    with urllib.request.urlopen(f"{server}{path}") as resp:
        return json.load(resp)


def find(graph, class_type):
    return [k for k, v in graph.items() if v["class_type"] == class_type]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", help="what to draw (the score tags are prepended for you)")
    ap.add_argument("--negative", default=None, help="override the negative prompt")
    ap.add_argument("--seed", type=int, default=None, help="default: derived from the clock")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--ckpt", default=None, help="checkpoint filename to load")
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--timeout", type=int, default=900, help="seconds to wait (default 900)")
    args = ap.parse_args()

    graph = json.loads(WORKFLOW.read_text())

    # The positive encoder is the one whose text carries the score prefix.
    encoders = find(graph, "CLIPTextEncode")
    pos_id = next((k for k in encoders if "score_9" in graph[k]["inputs"]["text"]), encoders[0])
    neg_id = next(k for k in encoders if k != pos_id)

    prompt = args.prompt
    if "score_9" not in prompt:
        prompt = f"{SCORE_PREFIX}, {prompt}"
    graph[pos_id]["inputs"]["text"] = prompt
    if args.negative is not None:
        graph[neg_id]["inputs"]["text"] = args.negative

    ks = find(graph, "KSampler")[0]
    graph[ks]["inputs"]["seed"] = args.seed if args.seed is not None else int(time.time() * 1000) % (2**63)
    if args.steps is not None:
        graph[ks]["inputs"]["steps"] = args.steps
    if args.cfg is not None:
        graph[ks]["inputs"]["cfg"] = args.cfg

    latent = find(graph, "EmptyLatentImage")[0]
    if args.width is not None:
        graph[latent]["inputs"]["width"] = args.width
    if args.height is not None:
        graph[latent]["inputs"]["height"] = args.height

    if args.ckpt is not None:
        graph[find(graph, "CheckpointLoaderSimple")[0]]["inputs"]["ckpt_name"] = args.ckpt

    server = args.server.rstrip("/")
    try:
        queued = post_json(server, "/prompt", {"prompt": graph})
    except urllib.error.URLError as exc:
        sys.exit(f"cannot reach ComfyUI at {server}: {exc}\nIs scripts/run.sh running?")
    except urllib.error.HTTPError as exc:
        sys.exit(f"ComfyUI rejected the workflow ({exc.code}):\n{exc.read().decode()}")

    prompt_id = queued["prompt_id"]
    print(f"queued {prompt_id}; seed {graph[ks]['inputs']['seed']}")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        history = get_json(server, f"/history/{prompt_id}")
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            images = [img for node in outputs.values() for img in node.get("images", [])]
            if not images:
                sys.exit("the run finished but produced no images; check the server log")
            for img in images:
                sub = f"{img['subfolder']}/" if img.get("subfolder") else ""
                print(f"  {sub}{img['filename']}")
            print("saved in ComfyUI's output/ directory")
            return
        time.sleep(2)

    sys.exit(f"timed out after {args.timeout}s waiting for the image")


if __name__ == "__main__":
    main()
