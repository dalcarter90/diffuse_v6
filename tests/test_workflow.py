#!/usr/bin/env python3
"""Check workflows/ against the real ComfyUI node definitions.

Point COMFYUI_DIR at a ComfyUI checkout (defaults to ./ComfyUI, where
scripts/install_comfyui.sh puts it). The node schemas are read straight out of
ComfyUI's source with `ast`, so this runs without torch or a GPU.

    python3 tests/test_workflow.py
"""

import ast
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMFY = pathlib.Path(os.environ.get("COMFYUI_DIR", ROOT / "ComfyUI"))

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(name)


def input_spec(nodes_py, class_name):
    """Return (required_names, optional_names) for a node class's INPUT_TYPES.

    Parses the literal dict the method returns; we only need the key names, so
    non-literal values (folder listings, sampler tuples) are fine to ignore.
    """
    tree = ast.parse(nodes_py.read_text())
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or cls.name != class_name:
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef) or fn.name != "INPUT_TYPES":
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                    continue
                required, optional = [], []
                for key, value in zip(node.value.keys, node.value.values):
                    if not isinstance(key, ast.Constant):
                        continue
                    if key.value not in ("required", "optional") or not isinstance(value, ast.Dict):
                        continue
                    names = [k.value for k in value.keys if isinstance(k, ast.Constant)]
                    (required if key.value == "required" else optional).extend(names)
                return required, optional
    return None, None


def literal_list(path, var_name):
    """Read a module-level list-of-strings assignment, e.g. KSAMPLER_NAMES."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return None


def main():
    ui = json.loads((ROOT / "workflows" / "pony_v6_txt2img.json").read_text())
    api = json.loads((ROOT / "workflows" / "pony_v6_txt2img_api.json").read_text())

    # --- checks that need no ComfyUI checkout --------------------------------

    check("UI and API workflows describe the same nodes",
          {n["id"] for n in ui["nodes"]} == {int(k) for k in api},
          f'{sorted(n["id"] for n in ui["nodes"])} vs {sorted(int(k) for k in api)}')

    ui_ids = {n["id"] for n in ui["nodes"]}
    bad_links = [l for l in ui["links"] if l[1] not in ui_ids or l[3] not in ui_ids]
    check("every UI link points at nodes that exist", not bad_links, str(bad_links))

    # Each declared input link id must appear exactly once in the link table.
    link_ids = [l[0] for l in ui["links"]]
    check("UI link ids are unique", len(link_ids) == len(set(link_ids)))

    declared = [i["link"] for n in ui["nodes"] for i in n["inputs"]]
    check("every node input resolves to a link", set(declared) <= set(link_ids),
          str(set(declared) - set(link_ids)))

    # Link table target slots must match the input's position on the node.
    slot_ok = True
    for n in ui["nodes"]:
        for slot, inp in enumerate(n["inputs"]):
            link = next(l for l in ui["links"] if l[0] == inp["link"])
            if link[3] != n["id"] or link[4] != slot:
                slot_ok = False
    check("link table target slots match input positions", slot_ok)

    # Output link lists must agree with the link table.
    out_ok = True
    for n in ui["nodes"]:
        for out in n["outputs"]:
            expected = [l[0] for l in ui["links"]
                        if l[1] == n["id"] and l[2] == out["slot_index"]]
            if (out["links"] or []) != expected:
                out_ok = False
    check("output link lists match the link table", out_ok)

    # API references must be to existing nodes, and the graph must terminate in SaveImage.
    ref_ok = all(v[0] in api for node in api.values()
                 for v in node["inputs"].values() if isinstance(v, list))
    check("API node references resolve", ref_ok)
    check("the graph has a SaveImage output node",
          any(n["class_type"] == "SaveImage" for n in api.values()))

    # --- checks against the real ComfyUI source ------------------------------

    nodes_py = COMFY / "nodes.py"
    if not nodes_py.is_file():
        print(f"\nSKIP schema checks: no ComfyUI checkout at {COMFY}")
        print("     (set COMFYUI_DIR, or run scripts/install_comfyui.sh first)")
    else:
        for node_id, node in sorted(api.items(), key=lambda kv: int(kv[0])):
            cls = node["class_type"]
            required, optional = input_spec(nodes_py, cls)
            if required is None:
                check(f"{cls} exists in ComfyUI", False, "class not found in nodes.py")
                continue
            allowed = set(required) | set(optional)
            given = set(node["inputs"])
            check(f"{cls}: inputs are all real", given <= allowed,
                  f"unknown: {sorted(given - allowed)}")
            check(f"{cls}: all required inputs present", set(required) <= given,
                  f"missing: {sorted(set(required) - given)}")

        samplers = literal_list(COMFY / "comfy" / "samplers.py", "KSAMPLER_NAMES") or []
        schedulers = list(literal_list(COMFY / "comfy" / "samplers.py", "SCHEDULER_HANDLERS") or [])
        if not schedulers:
            # SCHEDULER_HANDLERS holds calls, not literals; read its keys instead.
            tree = ast.parse((COMFY / "comfy" / "samplers.py").read_text())
            for n in ast.walk(tree):
                if isinstance(n, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "SCHEDULER_HANDLERS" for t in n.targets):
                    schedulers = [k.value for k in n.value.keys if isinstance(k, ast.Constant)]

        ks = next(n for n in api.values() if n["class_type"] == "KSampler")
        check("sampler_name is one ComfyUI offers", ks["inputs"]["sampler_name"] in samplers,
              f'{ks["inputs"]["sampler_name"]!r} not in {samplers[:6]}...')
        check("scheduler is one ComfyUI offers", ks["inputs"]["scheduler"] in schedulers,
              f'{ks["inputs"]["scheduler"]!r} not in {schedulers}')

    # --- Pony-specific settings ----------------------------------------------

    clip_skip = next(n for n in api.values() if n["class_type"] == "CLIPSetLastLayer")
    check("CLIP skip is 2 (stop_at_clip_layer -2), as Pony V6 expects",
          clip_skip["inputs"]["stop_at_clip_layer"] == -2)

    latent = next(n for n in api.values() if n["class_type"] == "EmptyLatentImage")
    check("latent is SDXL-native 1024x1024",
          (latent["inputs"]["width"], latent["inputs"]["height"]) == (1024, 1024))

    encoders = [n for n in api.values() if n["class_type"] == "CLIPTextEncode"]
    pos = min(encoders, key=lambda n: 0 if "score_9" in n["inputs"]["text"] else 1)
    neg = next(n for n in encoders if n is not pos)
    check("the positive prompt carries the score_9 tag prefix",
          pos["inputs"]["text"].startswith("score_9, score_8_up, score_7_up"))

    # A rating tag on both sides would have the prompts fighting each other.
    ratings = {"rating_safe", "rating_questionable", "rating_explicit"}
    in_pos = {r for r in ratings if r in pos["inputs"]["text"]}
    in_neg = {r for r in ratings if r in neg["inputs"]["text"]}
    check("exactly one rating tag is requested", len(in_pos) == 1, str(in_pos))
    check("no rating tag is in both the positive and negative prompt",
          not (in_pos & in_neg), str(in_pos & in_neg))
    check("the negative prompt opposes the requested rating",
          bool(in_neg) and not (in_pos & in_neg), f"positive={in_pos} negative={in_neg}")
    print(f"     (workflow is set to {in_pos.pop() if in_pos else '?'})")

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all workflow tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
