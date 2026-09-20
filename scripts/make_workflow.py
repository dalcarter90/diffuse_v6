#!/usr/bin/env python3
"""Generate the Pony Diffusion V6 XL text-to-image workflows for ComfyUI.

Writes two files into workflows/:

  pony_v6_txt2img.json      UI format  - open this one in the ComfyUI web page
  pony_v6_txt2img_api.json  API format - POST to /prompt, or use scripts/generate.py

Regenerate after changing the checkpoint filename or the defaults:

    python3 scripts/make_workflow.py --ckpt myPonyFile.safetensors

Node classes, input names, sampler and scheduler names below were taken from
ComfyUI 0.36.0 (nodes.py, comfy/samplers.py).
"""

import argparse
import json
import pathlib

# The score tag prefix Pony V6 was trained with. Without it the model produces
# noticeably worse output - see docs/prompting.md.
SCORE_PREFIX = "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up"

# Which rating band the workflow asks for. Pony V6 responds strongly to this
# tag, so the negative prompt gets the opposing band to keep the steer sharp.
RATINGS = ("safe", "questionable", "explicit")
OPPOSING_RATING = {
    "safe": "rating_explicit, rating_questionable",
    "questionable": "rating_safe",
    "explicit": "rating_safe",
}

DEFAULT_SUBJECT = (
    "1girl, solo, long silver hair, blue eyes, detailed face, "
    "standing in a sunlit forest, dappled light, intricate detail"
)

# score_4..6 in the negative pushes away from the low-quality end of the same
# scale the positive score tags select from.
QUALITY_NEGATIVE = (
    "worst quality, low quality, lowres, bad anatomy, bad hands, "
    "extra digits, fewer digits, jpeg artifacts, signature, watermark, "
    "username, blurry, text"
)


def positive_prompt(rating, subject=DEFAULT_SUBJECT, source="source_anime"):
    return f"{SCORE_PREFIX}, rating_{rating}, {source},\n\n{subject}"


def negative_prompt(rating):
    return f"score_6, score_5, score_4, {OPPOSING_RATING[rating]}, {QUALITY_NEGATIVE}"


class Graph:
    """Builds the two ComfyUI serialisation formats from one node list."""

    def __init__(self):
        self.nodes = []
        self.links = []          # [link_id, from_node, from_slot, to_node, to_slot, type]
        self._next_link = 1

    def add(self, node_id, class_type, pos, size, outputs, widgets=None, inputs=None):
        """inputs maps input_name -> (source_node_id, source_slot) or a literal."""
        self.nodes.append({
            "id": node_id,
            "type": class_type,
            "pos": list(pos),
            "size": list(size),
            "widgets": list(widgets or []),
            "outputs": list(outputs),     # list of output type names, in slot order
            "inputs": dict(inputs or {}),
        })
        return node_id

    def _link(self, from_node, from_slot, to_node, to_slot, type_name):
        link_id = self._next_link
        self._next_link += 1
        self.links.append([link_id, from_node, from_slot, to_node, to_slot, type_name])
        return link_id

    def _output_type(self, node_id, slot):
        for n in self.nodes:
            if n["id"] == node_id:
                return n["outputs"][slot]
        raise KeyError(f"no node {node_id}")

    def to_ui(self):
        """The format the ComfyUI web UI loads (litegraph serialisation)."""
        by_id = {n["id"]: n for n in self.nodes}
        # Build every link first so we can fill in both sides' slot bookkeeping.
        in_links = {}                       # (node_id, input_name) -> link_id
        out_links = {n["id"]: {} for n in self.nodes}   # node_id -> slot -> [link_id]

        for node in self.nodes:
            for name, src in node["inputs"].items():
                src_node, src_slot = src
                type_name = self._output_type(src_node, src_slot)
                lid = self._link(src_node, src_slot, node["id"], 0, type_name)
                in_links[(node["id"], name)] = (lid, type_name)
                out_links[src_node].setdefault(src_slot, []).append(lid)

        # Input slot indices must match the order ComfyUI lists them, which is the
        # order they were declared on the node.
        ui_nodes = []
        for order, node in enumerate(self.nodes):
            inputs = []
            for slot, (name, _src) in enumerate(node["inputs"].items()):
                lid, type_name = in_links[(node["id"], name)]
                inputs.append({"name": name, "type": type_name, "link": lid})
                # Fix up the target slot recorded in the link table.
                for link in self.links:
                    if link[0] == lid:
                        link[4] = slot

            outputs = []
            for slot, type_name in enumerate(node["outputs"]):
                links = out_links[node["id"]].get(slot, [])
                outputs.append({
                    "name": type_name,
                    "type": type_name,
                    "links": links or None,
                    "slot_index": slot,
                })

            ui_nodes.append({
                "id": node["id"],
                "type": node["type"],
                "pos": node["pos"],
                "size": node["size"],
                "flags": {},
                "order": order,
                "mode": 0,
                "inputs": inputs,
                "outputs": outputs,
                "properties": {"Node name for S&R": node["type"]},
                "widgets_values": node["widgets"],
            })

        return {
            "last_node_id": max(n["id"] for n in self.nodes),
            "last_link_id": self._next_link - 1,
            "nodes": ui_nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4,
        }

    def to_api(self, widget_names):
        """The flat format /prompt accepts: node id -> {class_type, inputs}."""
        out = {}
        for node in self.nodes:
            inputs = {}
            names = widget_names[node["type"]]
            for name, value in zip(names, node["widgets"]):
                inputs[name] = value
            for name, (src_node, src_slot) in node["inputs"].items():
                inputs[name] = [str(src_node), src_slot]
            out[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
        return out


# Widget order per node class, as ComfyUI's INPUT_TYPES declares them. The UI
# format stores widget values positionally; the API format needs their names.
# KSampler's "control_after_generate" is a UI-only widget - it picks the next
# seed after a run and is not part of the node's API inputs.
WIDGET_NAMES = {
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPSetLastLayer": ["stop_at_clip_layer"],
    "CLIPTextEncode": ["text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "VAEDecode": [],
    "SaveImage": ["filename_prefix"],
}
UI_ONLY_WIDGETS = {"KSampler": 1}   # control_after_generate sits at index 1


def build(ckpt, positive, negative, width, height, steps, cfg, sampler, scheduler, seed):
    g = Graph()

    g.add(4, "CheckpointLoaderSimple", (40, 500), (340, 100),
          outputs=["MODEL", "CLIP", "VAE"], widgets=[ckpt])

    # Pony V6 XL is trained for CLIP skip 2. -2 means "stop one layer early".
    g.add(10, "CLIPSetLastLayer", (40, 650), (340, 60),
          outputs=["CLIP"], widgets=[-2], inputs={"clip": (4, 1)})

    g.add(6, "CLIPTextEncode", (420, 200), (440, 220),
          outputs=["CONDITIONING"], widgets=[positive], inputs={"clip": (10, 0)})

    g.add(7, "CLIPTextEncode", (420, 470), (440, 220),
          outputs=["CONDITIONING"], widgets=[negative], inputs={"clip": (10, 0)})

    g.add(5, "EmptyLatentImage", (420, 740), (340, 110),
          outputs=["LATENT"], widgets=[width, height, 1])

    g.add(3, "KSampler", (900, 220), (330, 280), outputs=["LATENT"],
          widgets=[seed, "randomize", steps, cfg, sampler, scheduler, 1.0],
          inputs={"model": (4, 0), "positive": (6, 0),
                  "negative": (7, 0), "latent_image": (5, 0)})

    g.add(8, "VAEDecode", (1270, 220), (220, 60),
          outputs=["IMAGE"], widgets=[], inputs={"samples": (3, 0), "vae": (4, 2)})

    g.add(9, "SaveImage", (1270, 330), (440, 460),
          outputs=[], widgets=["PonyV6XL"], inputs={"images": (8, 0)})

    return g


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", default="ponyDiffusionV6XL.safetensors",
                    help="checkpoint filename as it appears in models/checkpoints/")
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--sampler", default="euler_ancestral")
    ap.add_argument("--scheduler", default="normal")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rating", choices=RATINGS, default="explicit",
                    help="which rating band the prompts ask for (default: explicit)")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    positive = positive_prompt(args.rating)
    negative = negative_prompt(args.rating)

    g = build(args.ckpt, positive, negative, args.width, args.height,
              args.steps, args.cfg, args.sampler, args.scheduler, args.seed)

    # The API format must not carry the UI-only widgets.
    api_graph = build(args.ckpt, positive, negative, args.width,
                      args.height, args.steps, args.cfg, args.sampler,
                      args.scheduler, args.seed)
    for node in api_graph.nodes:
        drop = UI_ONLY_WIDGETS.get(node["type"])
        if drop is not None:
            node["widgets"] = node["widgets"][:drop] + node["widgets"][drop + 1:]

    outdir = pathlib.Path(args.outdir) if args.outdir \
        else pathlib.Path(__file__).resolve().parent.parent / "workflows"
    outdir.mkdir(parents=True, exist_ok=True)

    ui_path = outdir / "pony_v6_txt2img.json"
    api_path = outdir / "pony_v6_txt2img_api.json"
    ui_path.write_text(json.dumps(g.to_ui(), indent=2) + "\n")
    api_path.write_text(json.dumps(api_graph.to_api(WIDGET_NAMES), indent=2) + "\n")
    print(f"wrote {ui_path}")
    print(f"wrote {api_path}")


if __name__ == "__main__":
    main()
