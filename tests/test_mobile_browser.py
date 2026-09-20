"""Drive mobile/index.html in a real browser against a stub ComfyUI.

Needs playwright and a Chromium build; skips cleanly if either is missing:

    pip install playwright && playwright install chromium

Set CHROMIUM_PATH to use a Chromium you already have.
"""
import json, os, pathlib, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_mobile import Comfy, free_port, wait_up, start_proxy
from http.server import ThreadingHTTPServer
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP browser checks: playwright is not installed")
    print("     pip install playwright && playwright install chromium")
    sys.exit(0)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def chromium_path():
    """An explicit binary if one is configured, else playwright's own download."""
    explicit = os.environ.get("CHROMIUM_PATH")
    if explicit:
        return explicit
    for base in sorted(pathlib.Path("/opt/pw-browsers").glob("chromium-*"), reverse=True):
        candidate = base / "chrome-linux" / "chrome"
        if candidate.is_file():
            return str(candidate)
    return None            # let playwright pick its bundled browser
comfy = ThreadingHTTPServer(("127.0.0.1", 0), Comfy)
threading.Thread(target=comfy.serve_forever, daemon=True).start()
port = free_port()
proc = start_proxy(port, f"http://127.0.0.1:{comfy.server_address[1]}")
base = f"http://127.0.0.1:{port}"

posted = {}
fails = []
def check(n, c, d=""):
    print(("PASS " if c else "FAIL ") + n + (f"  <- {d}" if not c and d else ""))
    if not c: fails.append(n)

try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=chromium_path())
        page = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True,
                          has_touch=True, device_scale_factor=3)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: posted.update(
            {"graph": json.loads(r.post_data)["prompt"]}) if r.url.endswith("/prompt") and r.post_data else None)

        page.goto(base, wait_until="networkidle")
        check("page loads with no JS errors", not errors, str(errors[:3]))
        check("no horizontal overflow at 390px wide",
              page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
              page.evaluate("document.documentElement.scrollWidth + ' vs ' + window.innerWidth"))
        check("negative prompt was seeded from the workflow",
              "worst quality" in page.input_value("#negative"))
        check("explicit is preselected",
              page.get_attribute('[data-v="explicit"]', "aria-pressed") == "true")

        # Generate with defaults.
        page.fill("#prompt", "a red fox in autumn leaves")
        page.click("#go")
        page.wait_for_selector("#out img", timeout=20000)
        check("an image is rendered", page.locator("#out img").count() == 1)
        check("status shows the seed", "seed" in page.text_content("#status"),
              page.text_content("#status"))

        g = posted.get("graph", {})
        enc = [n for n in g.values() if n["class_type"] == "CLIPTextEncode"]
        pos = [n for n in enc if "score_9" in n["inputs"]["text"]][0]
        neg = [n for n in enc if "score_9" not in n["inputs"]["text"]][0]
        check("score prefix prepended", pos["inputs"]["text"].startswith("score_9, score_8_up"))
        check("explicit rating in positive", "rating_explicit" in pos["inputs"]["text"])
        check("opposing rating in negative", "rating_safe" in neg["inputs"]["text"])
        check("no rating tag on both sides", "rating_explicit" not in neg["inputs"]["text"])
        check("subject present", "a red fox in autumn leaves" in pos["inputs"]["text"])
        check("source tag applied", "source_anime" in pos["inputs"]["text"])
        ks = [n for n in g.values() if n["class_type"] == "KSampler"][0]
        check("seed randomised (non-zero)", ks["inputs"]["seed"] != 0, str(ks["inputs"]["seed"]))

        # Switch rating to safe and shape to portrait.
        page.click('[data-v="safe"]')
        page.click('[data-w="832"]')
        page.click("#go")
        page.wait_for_timeout(2500)
        g = posted["graph"]
        enc = [n for n in g.values() if n["class_type"] == "CLIPTextEncode"]
        pos = [n for n in enc if "score_9" in n["inputs"]["text"]][0]
        neg = [n for n in enc if "score_9" not in n["inputs"]["text"]][0]
        lat = [n for n in g.values() if n["class_type"] == "EmptyLatentImage"][0]
        check("switching to safe updates the positive", "rating_safe" in pos["inputs"]["text"])
        check("switching to safe flips the negative",
              "rating_explicit" in neg["inputs"]["text"] and "rating_safe" not in neg["inputs"]["text"],
              neg["inputs"]["text"][:70])
        check("portrait shape applied",
              (lat["inputs"]["width"], lat["inputs"]["height"]) == (832, 1216), str(lat["inputs"]))

        # Empty prompt must be refused client-side.
        page.fill("#prompt", "")
        page.click("#go")
        page.wait_for_timeout(500)
        check("empty prompt is refused", "Type a prompt" in page.text_content("#status"),
              page.text_content("#status"))

        b.close()
finally:
    proc.kill(); comfy.shutdown(); comfy.server_close()

print()
print("FAILED: " + ", ".join(fails) if fails else "all browser checks passed")
sys.exit(1 if fails else 0)
