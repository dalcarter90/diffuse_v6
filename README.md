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
| `scripts/serve_mobile.py` | Serves a phone-friendly page on `:8189` and forwards only four endpoints to ComfyUI. See [docs/mobile.md](docs/mobile.md). |
| `scripts/generate.py` | Generates from the command line against the running server. Standard library only. |
| `scripts/make_workflow.py` | Regenerates the workflow files. `--preset pony\|sdxl`, `--ckpt` to match your filename, `--rating` for the Pony band. |
| `scripts/resolve_civitai.py` | Picks the right file out of a Civitai API response. Used by the downloader. |

Set `COMFY_DIR` to install ComfyUI somewhere other than `./ComfyUI` — useful if
you already have one, or want the model on a different disk:

```bash
COMFY_DIR=/mnt/ai/ComfyUI ./scripts/install_comfyui.sh
COMFY_DIR=/mnt/ai/ComfyUI ./scripts/download_model.sh
```

## From your phone

```bash
./scripts/run.sh                    # terminal 1
python3 scripts/serve_mobile.py     # terminal 2 — prints the address to open
```

ComfyUI's node graph is painful on a touchscreen, so this serves a small page
built for a phone instead: prompt box, rating and shape buttons, Generate.

**ComfyUI has no authentication of any kind**, so never port-forward it to the
internet. On your own Wi-Fi the command above is fine; away from home, use
Tailscale. `serve_mobile.py` exposes only queue/poll/fetch/cancel and takes a
`--token`. [docs/mobile.md](docs/mobile.md) covers finding your IP, firewalls,
Tailscale, and the security details.

## Generating from the command line

With the server running in another terminal:

```bash
python3 scripts/generate.py "a red fox in autumn leaves, forest, morning light"
python3 scripts/generate.py "cyberpunk street at night, neon" --width 1216 --height 832 --seed 7
```

The score tag prefix Pony V6 needs is prepended automatically. Images land in
`ComfyUI/output/`.

## The workflows

Two of them, because Pony and ordinary SDXL models want different settings:

| File | For | CLIP skip | Score tags | CFG |
| ---- | --- | --------- | ---------- | --- |
| `workflows/pony_v6_txt2img.json` | Pony V6 XL and its finetunes | −2 | yes | 7.0 |
| `workflows/sdxl_txt2img.json` | stock SDXL models (Juggernaut XL, RealVisXL, DreamShaper XL) | −1 | no | 5.0 |

Each has an `_api.json` twin — the same graph in the flat format `/prompt`
accepts.

**Using the wrong one degrades output without erroring.** Score tags are
vocabulary Pony was trained on; on a non-Pony model they are meaningless tokens
that consume prompt budget. CLIP skip differs too: Pony expects −2, stock SDXL
finetunes −1. Pony *derivatives* (a "Pony Realism" style merge) keep Pony's
vocabulary, so use the pony workflow for those.

The Pony one sets the model-specific bits correctly: **CLIP skip 2**
(`CLIPSetLastLayer` at `-2`), the **score tag prefix** in the positive prompt,
**`rating_explicit`** with `rating_safe` negated, **1024×1024** latents, CFG 7
and 30 steps of `euler_ancestral`.

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
`python3 scripts/make_workflow.py --preset pony --ckpt yourfile.safetensors`.

The SDXL workflow defaults to `juggernautXL.safetensors` and takes the same
treatment: `--preset sdxl --ckpt yourfile.safetensors`. Run it with no
arguments to regenerate both.

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
- `serve_mobile.py` is checked to forward the four endpoints it should and to
  refuse everything else, plus token handling
- the mobile page is driven in a real headless Chromium at phone viewport size
  (skipped if playwright is not installed)

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
