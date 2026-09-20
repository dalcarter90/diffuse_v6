# diffuse_v6

Scripted setup for running **Pony Diffusion V6 XL** on **ComfyUI**, plus a
text-to-image workflow with the settings the model actually expects.

Run these on the machine with your GPU.

```bash
git clone <this repo> && cd diffuse_v6

./scripts/install_comfyui.sh       # ComfyUI + a venv + the right PyTorch build
export CIVITAI_TOKEN=...           # from civitai.com/user/account -> API Keys
./scripts/download_model.sh        # ~6.5 GB, resumable, checksum-verified
./scripts/run.sh                   # http://127.0.0.1:8188
```

Then open <http://127.0.0.1:8188>, drag `workflows/pony_v6_txt2img.json` onto
the page, and hit Run.

## Requirements

- Python 3.10 or newer (ComfyUI 0.36 requires it)
- git, curl
- About **20 GB** of disk: ~6.5 GB model, ~3 GB PyTorch, plus room for output
- A GPU with **8 GB VRAM or more** for comfortable SDXL generation. 6 GB works
  with `./scripts/run.sh --lowvram`. CPU-only runs but takes minutes per image.

`install_comfyui.sh` detects your accelerator and installs the matching PyTorch
wheels — NVIDIA (CUDA), AMD (ROCm, Linux), Intel (XPU), Apple silicon (MPS), or
CPU. Override with `--backend nvidia|rocm|xpu|mps|cpu` if the guess is wrong.

## What each script does

| Script | Purpose |
| ------ | ------- |
| `scripts/install_comfyui.sh` | Clones ComfyUI into `./ComfyUI`, creates `.venv`, installs PyTorch for your hardware and ComfyUI's requirements, then prints the device torch can see. Re-runnable. |
| `scripts/download_model.sh` | Resolves the current Pony V6 XL file through the Civitai API, downloads it into `ComfyUI/models/checkpoints/ponyDiffusionV6XL.safetensors`, and verifies the SHA256. Resumes if interrupted. |
| `scripts/run.sh` | Starts the server. Extra arguments pass through to ComfyUI (`--lowvram`, `--listen 0.0.0.0`, `--port 8189`, `--fp32-vae`, …). |
| `scripts/generate.py` | Generates from the command line against the running server. Standard library only. |
| `scripts/make_workflow.py` | Regenerates the two workflow files, e.g. after renaming the checkpoint (`--ckpt`) or changing the rating band (`--rating`). |
| `scripts/resolve_civitai.py` | Picks the right file out of a Civitai API response. Used by the downloader. |

Set `COMFY_DIR` to install ComfyUI somewhere other than `./ComfyUI` — useful if
you already have one, or want the model on a different disk:

```bash
COMFY_DIR=/mnt/ai/ComfyUI ./scripts/install_comfyui.sh
COMFY_DIR=/mnt/ai/ComfyUI ./scripts/download_model.sh
```

## Generating from the command line

With the server running in another terminal:

```bash
python3 scripts/generate.py "a red fox in autumn leaves, forest, morning light"
python3 scripts/generate.py "cyberpunk street at night, neon" --width 1216 --height 832 --seed 7
```

The score tag prefix Pony V6 needs is prepended automatically. Images land in
`ComfyUI/output/`.

## The workflow

`workflows/pony_v6_txt2img.json` is the one to open in the browser.
`workflows/pony_v6_txt2img_api.json` is the same graph in the flat API format
that `/prompt` accepts.

It is a plain SDXL text-to-image graph with the Pony-specific bits set
correctly: **CLIP skip 2** (`CLIPSetLastLayer` at `-2`), the **score tag
prefix** in the positive prompt, **`rating_explicit`** with `rating_safe`
negated, **1024×1024** latents, CFG 7 and 30 steps of `euler_ancestral`.

Those settings are not arbitrary and the model is noticeably worse without
them — **[docs/prompting.md](docs/prompting.md)** explains the score tags,
rating and source tags, valid SDXL resolutions, and why artist tags don't work
on this model.

## Downloading without a Civitai token

Civitai requires an API key for model downloads. If you would rather not create
one, point the script at any mirror you trust:

```bash
./scripts/download_model.sh --url 'https://example.com/ponyDiffusionV6XL.safetensors'
```

Or download by hand and drop the file at
`ComfyUI/models/checkpoints/ponyDiffusionV6XL.safetensors`. The workflow
expects that exact filename; if yours differs, either rename it or run
`python3 scripts/make_workflow.py --ckpt yourfile.safetensors`.

## Tests

```bash
./tests/run_all.sh
```

These check the parts that can be checked without a GPU or the weights:

- the workflow JSON is validated against the node definitions in your ComfyUI
  checkout — class names, input names, sampler and scheduler names (skipped if
  you have not installed ComfyUI yet)
- `download_model.sh` is run end to end against a stub Civitai server, covering
  resume-after-interruption, skip-if-complete, `--force`, and checksum rejection
- the Civitai response parser is exercised against fixtures, error cases included
- `generate.py` is driven against a stub ComfyUI server

## Troubleshooting

**`CIVITAI_TOKEN is not set`** — create a key at
<https://civitai.com/user/account> under "API Keys", then
`export CIVITAI_TOKEN=...`.

**Checksum mismatch** — the download was truncated. Re-run with `--force`.

**`Torch not compiled with CUDA enabled`** — the wrong wheels got installed.
Re-run `./scripts/install_comfyui.sh --backend nvidia`.

**Out of memory** — `./scripts/run.sh --lowvram`, or `--novram` if that is not
enough. Also check you are generating at 1024×1024 and not larger.

**Black images** — `./scripts/run.sh --fp32-vae`.

**The workflow can't find the checkpoint** — the filename in the
`CheckpointLoaderSimple` node must match the file in
`ComfyUI/models/checkpoints/`. Click the node's dropdown to pick the file you
actually have.

## Note on the model

Pony Diffusion V6 XL is a general-purpose model whose training data includes
explicit content. The bundled workflow asks for `rating_explicit`. Switch bands
by regenerating it:

```bash
python3 scripts/make_workflow.py --rating safe          # or questionable, explicit
```

See [docs/prompting.md](docs/prompting.md) for how the rating tags work, and
the model's licence terms on its Civitai page for what you may do with the
output.
