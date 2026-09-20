# Using it from your phone

Your phone does not run the model — it just talks to the machine with the GPU,
which has to stay on and running ComfyUI.

There are two things to sort out: a usable interface, and a network path.

## The interface

ComfyUI's node graph works on a phone in the sense that it loads. Dragging
wires between nodes on a 6-inch touchscreen is miserable, and it is easy to
knock a node loose without noticing.

So this repo ships a small page built for a phone instead — a prompt box,
rating and shape buttons, and a Generate button:

```bash
./scripts/run.sh                    # terminal 1: ComfyUI on :8188
python3 scripts/serve_mobile.py     # terminal 2: the phone UI on :8189
```

It prints the address to open. On your phone, browse to
`http://<your-machine-ip>:8189`.

It loads `workflows/pony_v6_txt2img_api.json`, so it inherits whatever
checkpoint, sampler and step count the workflow is set to — change those with
`scripts/make_workflow.py` and the page follows.

Use **Add to Home Screen** in your phone's browser menu and it opens like an
app, without the address bar.

If you would rather have the full node graph anyway, skip the extra server and
start ComfyUI with `./scripts/run.sh --listen 0.0.0.0`, then open
`http://<your-machine-ip>:8188`. Read the security section first.

## Finding your machine's address

`serve_mobile.py` prints its best guess on startup. Otherwise:

```bash
ip addr | grep 'inet '          # Linux
ipconfig getifaddr en0          # macOS (Wi-Fi)
ipconfig                        # Windows - look for IPv4 Address
```

You want the private address — something starting `192.168.`, `10.`, or
`172.16.`–`172.31.`. Both devices must be on the same network; "guest" Wi-Fi
usually blocks devices from seeing each other.

If the page will not load, the host firewall is the usual cause:

```bash
sudo ufw allow 8189/tcp                                   # Linux, ufw
# macOS: System Settings > Network > Firewall > Options, allow python
# Windows: allow the port for "Private" networks only, never "Public"
netsh advfirewall firewall add rule name="ComfyUI mobile" dir=in action=allow protocol=TCP localport=8189
```

## Security: read this before exposing anything

**ComfyUI has no authentication.** There is no password option — the flags are
only `--listen`, `--port`, TLS, and CORS. Anyone who can reach the port can
queue jobs, browse your generated images, read the model list, upload files,
and run custom nodes, which execute arbitrary Python.

So:

- **Never port-forward 8188 or 8189 to the internet**, and do not put either in
  your router's DMZ. Open ComfyUI instances get found and used by strangers.
- On a shared or untrusted network, prefer the mobile server over exposing
  ComfyUI, and give it a token:

  ```bash
  python3 scripts/serve_mobile.py --token "$(head -c 12 /dev/urandom | base64)"
  ```

  It prints a URL ending in `?key=…`; open that once on your phone and the page
  remembers it. `serve_mobile.py` forwards only four endpoints — queue, poll,
  fetch image, cancel — so even without a token it exposes far less than
  ComfyUI does. Uploads, the model list and user data return 404.

A token over plain HTTP is visible to anyone sniffing the network. It stops a
housemate or a compromised smart bulb from using your GPU; it is not a VPN.

## Away from home

Do not solve this with port forwarding. Use a private network instead.

**Tailscale** is the least painful option, and free for personal use. Install
it on both the GPU machine and the phone, sign both into the same account, and
the phone can reach the machine's Tailscale address from anywhere as if it were
on the same LAN — no ports opened, traffic encrypted.

```bash
# on the GPU machine
tailscale up
tailscale ip -4          # e.g. 100.x.y.z
```

Then open `http://100.x.y.z:8189` on the phone. Bind to the Tailscale address
specifically if you would rather not listen on your LAN at all:

```bash
python3 scripts/serve_mobile.py --listen 100.x.y.z
```

**Cloudflare Tunnel** also works and gives you an HTTPS URL, but that URL is
reachable by anyone who has it, so only use it with `--token` set, and prefer
putting Cloudflare Access in front.

**SSH tunnel** works if you already have SSH to the machine, though phone SSH
clients make it fiddly:

```bash
ssh -L 8189:127.0.0.1:8189 you@your-machine
```

## Generation is still slow

The phone is a remote control. A 1024×1024 image at 30 steps takes whatever it
takes on your GPU — a few seconds on a 4090, a minute or more on an 8 GB card.
The page polls every 1.5s and shows elapsed time.

Locking the phone or switching apps does not cancel anything. The job keeps
running and the image is waiting in `ComfyUI/output/` (and in the page) when
you come back.
