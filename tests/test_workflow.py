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


def structural_checks(label, ui, api):
    """Checks that must hold for any generated workflow pair."""
    check(f"{label}: UI and API describe the same nodes",
          {n["id"] for n in ui["nodes"]} == {int(k) for k in api})

    ui_ids = {n["id"] for n in ui["nodes"]}
    bad_links = [l for l in ui["links"] if l[1] not in ui_ids or l[3] not in ui_ids]
    check(f"{label}: every UI link points at nodes that exist", not bad_links, str(bad_links))

    link_ids = [l[0] for l in ui["links"]]
    check(f"{label}: UI link ids are unique", len(link_ids) == len(set(link_ids)))

    declared = [i["link"] for n in ui["nodes"] for i in n["inputs"]]
    check(f"{label}: every node input resolves to a link", set(declared) <= set(link_ids))

    slot_ok = True
    for n in ui["nodes"]:
        for slot, inp in enumerate(n["inputs"]):
            link = next(l for l in ui["links"] if l[0] == inp["link"])
            if link[3] != n["id"] or link[4] != slot:
                slot_ok = False
    check(f"{label}: link table target slots match input positions", slot_ok)

    out_ok = True
    for n in ui["nodes"]:
        for out in n["outputs"]:
            expected = [l[0] for l in ui["links"]
                        if l[1] == n["id"] and l[2] == out["slot_index"]]
            if (out["links"] or []) != expected:
                out_ok = False
    check(f"{label}: output link lists match the link table", out_ok)

    ref_ok = all(v[0] in api for node in api.values()
                 for v in node["inputs"].values() if isinstance(v, list))
    check(f"{label}: API node references resolve", ref_ok)
    check(f"{label}: has a SaveImage output node",
          any(n["class_type"] == "SaveImage" for n in api.values()))

    latent = next(n for n in api.values() if n["class_type"] == "EmptyLatentImage")
    check(f"{label}: latent is SDXL-native 1024x1024",
          (latent["inputs"]["width"], latent["inputs"]["height"]) == (1024, 1024))


def schema_checks(label, api, nodes_py, samplers, schedulers):
    """Validate every node against the real ComfyUI definitions."""
    for _node_id, node in sorted(api.items(), key=lambda kv: int(kv[0])):
        cls = node["class_type"]
        required, optional = input_spec(nodes_py, cls)
        if required is None:
            check(f"{label}: {cls} exists in ComfyUI", False, "class not found in nodes.py")
            continue
        allowed = set(required) | set(optional)
        given = set(node["inputs"])
        check(f"{label}: {cls} inputs are all real", given <= allowed,
              f"unknown: {sorted(given - allowed)}")
        check(f"{label}: {cls} required inputs present", set(required) <= given,
              f"missing: {sorted(set(required) - given)}")

    ks = next(n for n in api.values() if n["class_type"] == "KSampler")
    check(f"{label}: sampler_name is one ComfyUI offers",
          ks["inputs"]["sampler_name"] in samplers, ks["inputs"]["sampler_name"])
    check(f"{label}: scheduler is one ComfyUI offers",
          ks["inputs"]["scheduler"] in schedulers, ks["inputs"]["scheduler"])


def load(basename):
    ui = json.loads((ROOT / "workflows" / f"{basename}.json").read_text())
    api = json.loads((ROOT / "workflows" / f"{basename}_api.json").read_text())
    return ui, api


def encoders(api):
    enc = [n for n in api.values() if n["class_type"] == "CLIPTextEncode"]
    pos = min(enc, key=lambda n: 0 if "score_9" in n["inputs"]["text"] else 1)
    neg = next(n for n in enc if n is not pos)
    return pos, neg


def main():
    pony_ui, pony_api = load("pony_v6_txt2img")
    sdxl_ui, sdxl_api = load("sdxl_txt2img")

    structural_checks("pony", pony_ui, pony_api)
    structural_checks("sdxl", sdxl_ui, sdxl_api)

    # --- checks against the real ComfyUI source ------------------------------

    nodes_py = COMFY / "nodes.py"
    if not nodes_py.is_file():
        print(f"\nSKIP schema checks: no ComfyUI checkout at {COMFY}")
        print("     (set COMFYUI_DIR, or run scripts/install_comfyui.sh first)")
    else:
        samplers = literal_list(COMFY / "comfy" / "samplers.py", "KSAMPLER_NAMES") or []
        tree = ast.parse((COMFY / "comfy" / "samplers.py").read_text())
        schedulers = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "SCHEDULER_HANDLERS" for t in n.targets):
                schedulers = [k.value for k in n.value.keys if isinstance(k, ast.Constant)]
        schema_checks("pony", pony_api, nodes_py, samplers, schedulers)
        schema_checks("sdxl", sdxl_api, nodes_py, samplers, schedulers)

    # --- Pony-specific settings ----------------------------------------------

    clip_skip = next(n for n in pony_api.values() if n["class_type"] == "CLIPSetLastLayer")
    check("pony: CLIP skip is 2 (stop_at_clip_layer -2), as Pony V6 expects",
          clip_skip["inputs"]["stop_at_clip_layer"] == -2)

    pos, neg = encoders(pony_api)
    check("pony: positive prompt carries the score_9 tag prefix",
          pos["inputs"]["text"].startswith("score_9, score_8_up, score_7_up"))

    ratings = {"rating_safe", "rating_questionable", "rating_explicit"}
    in_pos = {r for r in ratings if r in pos["inputs"]["text"]}
    in_neg = {r for r in ratings if r in neg["inputs"]["text"]}
    check("pony: exactly one rating tag is requested", len(in_pos) == 1, str(in_pos))
    check("pony: no rating tag is in both prompts", not (in_pos & in_neg), str(in_pos & in_neg))
    check("pony: the negative prompt opposes the requested rating",
          bool(in_neg) and not (in_pos & in_neg), f"positive={in_pos} negative={in_neg}")
    print(f"     (pony workflow is set to {in_pos.pop() if in_pos else '?'})")

    # --- non-Pony SDXL must NOT carry Pony's vocabulary -----------------------
    #
    # Score/rating/source tags mean nothing to a stock SDXL finetune; they waste
    # prompt budget and can steer output worse. CLIP skip differs too.

    sdxl_clip = next(n for n in sdxl_api.values() if n["class_type"] == "CLIPSetLastLayer")
    check("sdxl: CLIP skip is -1, not Pony's -2",
          sdxl_clip["inputs"]["stop_at_clip_layer"] == -1,
          str(sdxl_clip["inputs"]["stop_at_clip_layer"]))

    sdxl_pos, sdxl_neg = encoders(sdxl_api)
    both = sdxl_pos["inputs"]["text"] + " " + sdxl_neg["inputs"]["text"]
    for tag in ("score_9", "score_8_up", "score_4_up", "score_6,", "rating_", "source_"):
        check(f"sdxl: prompts contain no {tag.rstrip(',')} tag", tag not in both,
              f"found {tag!r}")

    sdxl_ks = next(n for n in sdxl_api.values() if n["class_type"] == "KSampler")
    check("sdxl: CFG is lower than Pony's, as photoreal models prefer",
          sdxl_ks["inputs"]["cfg"] < 7.0, str(sdxl_ks["inputs"]["cfg"]))

    check("the two workflows load different checkpoints",
          next(n for n in pony_api.values() if n["class_type"] == "CheckpointLoaderSimple")["inputs"]["ckpt_name"]
          != next(n for n in sdxl_api.values() if n["class_type"] == "CheckpointLoaderSimple")["inputs"]["ckpt_name"])

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all workflow tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
