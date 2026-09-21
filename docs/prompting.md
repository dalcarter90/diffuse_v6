# Prompting Pony Diffusion V6 XL

Pony V6 XL is an SDXL 1.0 finetune. It is not a drop-in replacement for base
SDXL — it was trained on a tagging scheme that you have to use, and it ignores
some conventions that work elsewhere. The three things that matter most:

1. **Always include the score tag prefix.** Without it, output quality drops
   sharply.
2. **Set CLIP skip to 2.** In ComfyUI that is a `CLIPSetLastLayer` node with
   `stop_at_clip_layer = -2`, which the bundled workflow already has.
3. **Prompt in tags, not sentences.** Comma-separated booru-style tags work far
   better than prose, though short natural-language phrases are tolerated.

## The score tags

Put this at the front of every positive prompt:

```
score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up
```

These are aesthetic-ranking tags from training, not a quality dial you tune.
The whole descending chain is the convention — `score_9` alone is weaker,
because `score_9` was a narrow band during training while `score_8_up` and
below widen the target.

The mirror image goes in the negative prompt:

```
score_6, score_5, score_4
```

`scripts/generate.py` prepends the positive chain for you if your prompt does
not already contain it.

## Rating tags

Pony V6 is a general-purpose model with explicit content in its training set,
so the rating tag is doing real work whichever way you point it:

| Tag                    | Effect                                   |
| ---------------------- | ---------------------------------------- |
| `rating_safe`          | keeps output tame                        |
| `rating_questionable`  | suggestive                               |
| `rating_explicit`      | explicit                                 |

The bundled workflow asks for `rating_explicit`, with `rating_safe` in the
negative prompt to keep the steer sharp. Change it either by editing the two
`CLIPTextEncode` nodes in the browser, or by regenerating the workflow:

```bash
python3 scripts/make_workflow.py --rating safe          # or questionable, explicit
```

Pairing the rating you want with its opposite in the negative prompt matters —
the same tag on both sides has the two prompts pulling against each other.

## Source tags

One of these steers the overall art style:

| Tag              | Style                                    |
| ---------------- | ---------------------------------------- |
| `source_pony`    | MLP-style cartoon                        |
| `source_furry`   | anthropomorphic animal art               |
| `source_anime`   | anime / manga                            |
| `source_cartoon` | Western cartoon                          |

Omit it and the model averages across all four, which usually looks muddier
than picking one.

## Artist tags do not work

Unlike many booru-trained models, Pony V6 obfuscated artist names during
training. `by <artist name>` will not reproduce that artist's style. Describe
the style you want with ordinary descriptive tags instead, or use a LoRA.

## Sampler settings

The defaults in `workflows/pony_v6_txt2img.json`:

| Setting     | Value            | Notes                                        |
| ----------- | ---------------- | -------------------------------------------- |
| Steps       | 30               | 25–35 is the useful range; more rarely helps |
| CFG         | 7.0              | 5–9 works; above ~10 output starts to burn   |
| Sampler     | `euler_ancestral`| "Euler a" elsewhere. `dpmpp_2m` is the other common pick |
| Scheduler   | `normal`         | pair `karras` with `dpmpp_2m`                |
| CLIP skip   | −2               | required                                     |
| Resolution  | 1024×1024        | SDXL native                                  |

### Resolutions

SDXL was trained on ~1 megapixel buckets. Staying on one avoids stretched
anatomy and duplicated subjects:

```
1024 x 1024   square
 896 x 1152   portrait        1152 x  896   landscape
 832 x 1216   tall portrait   1216 x  832   wide landscape
 768 x 1344   taller          1344 x  768   wider
```

Generate at these sizes and upscale afterwards rather than asking for 2048×2048
directly.

### VAE

The Civitai release has the VAE baked into the checkpoint, so the workflow
takes `VAE` straight from `CheckpointLoaderSimple` and no separate VAE file is
needed. If you get black or garbled images, the VAE is running in a precision
your GPU dislikes — start the server with `./scripts/run.sh --fp32-vae`.

## A worked example

```
score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up,
rating_explicit, source_anime,

1girl, solo, long silver hair, blue eyes, detailed face,
standing in a sunlit forest, dappled light, intricate detail
```

Negative:

```
score_6, score_5, score_4, rating_safe,
worst quality, low quality, lowres, bad anatomy, bad hands,
extra digits, fewer digits, jpeg artifacts, signature, watermark,
username, blurry, text
```

Reading order inside the prompt is roughly: score tags → rating → source →
subject → subject details → setting → lighting and style. The model weights
earlier tags a little more heavily, so lead with what you care about most.

## Using a non-Pony model

None of the above applies to a stock SDXL finetune such as Juggernaut XL,
RealVisXL or DreamShaper XL. Those models never saw Pony's tag vocabulary, so
`score_9`, `rating_safe` and `source_anime` are just tokens spent for nothing —
and they can pull output in odd directions.

Use `workflows/sdxl_txt2img.json` for those. Same graph, with the score tags
removed, CLIP skip at −1 instead of −2, and CFG 5 instead of 7. Prompt it in
plain descriptive language or ordinary tags:

```
photo of a man in a weathered leather jacket, short dark hair,
standing on a rain-slick city street at night, neon reflections,
shallow depth of field, detailed skin texture, natural lighting
```

The dividing line is the model's ancestry, not its subject matter. A model
finetuned *from* Pony V6 — the "Pony Realism" style merges — keeps the whole
score/rating/source vocabulary, so use the pony workflow for it. Anything
descended from base SDXL uses the sdxl workflow.

If you are unsure which you have, its model page will say what it was trained
from. Failing that: generate the same prompt both ways and keep whichever looks
better.
