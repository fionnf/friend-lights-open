# Setup

Start to finish. Roughly an hour for the first lamp, twenty minutes for
the second.

If you have never used The Things Network, don't skip the box in step 3 —
five minutes there makes every later screen make sense.

| Step | You'll need |
|---|---|
| [1. Build the lamp](#1-build-the-lamp) | soldering iron |
| [2. Flash MicroPython](#2-flash-micropython) | USB-C data cable |
| [3. Set up The Things Network](#3-set-up-the-things-network) | free account |
| [4. Deploy the bridge](#4-deploy-the-bridge) | free Cloudflare account |
| [5. Configure and load](#5-configure-and-load) | the keys from step 3 |
| [6. First light](#6-first-light) | — |

Before any of it, check **both** addresses on the
[TTN map](https://www.thethingsnetwork.org/map), and cross-check with
**TTN Mapper**, which shows measured rather than claimed coverage. If
either end has no gateway in range, none of this works and no antenna
will fix it.

### Two free accounts

Neither wants a card:

- **[The Things Network](https://console.cloud.thethings.network)** — the radio network
- **[Cloudflare](https://dash.cloudflare.com)** — runs the 40-line bridge

### Values you'll collect

Keep a scratch file:

| From | What |
|---|---|
| TTN, lamp 1 | DevEUI, JoinEUI, AppKey |
| TTN, lamp 2 | DevEUI, JoinEUI, AppKey |
| Cloudflare | your worker URL |
| you | a shared secret you invent |

Only the six TTN values go on the lamps.

---

## 1. Build the lamp

```
XIAO GPIO2 ──[330Ω]── DIN   SK6812 strip
XIAO 5V    ──────────  VCC
XIAO GND   ──────────  GND

XIAO TX (GPIO43) ──►  RX    Wio-E5      ← they cross over
XIAO RX (GPIO44) ◄──  TX
XIAO 3V3         ──►  VCC
XIAO GND         ──►  GND

XIAO GPIO4  ──────────  copper pad / foil    (touch, optional)
```

Data flows DIN → DOUT, so connect to the **DIN** end of the strip. If
yours is wired from the far end, set `REVERSE_LEDS = True`.

The touch pad needs **no external resistor** — the ESP32-S3 has hardware
touch channels. Bare copper, foil, or a screw head all work. Set
`TOUCH_PINS = []` if you don't want one.

⚠️ **Never power the Wio-E5 without its antenna attached.** Transmitting
into an open connector can damage the radio.

More on antennas and placement in [docs/HARDWARE.md](HARDWARE.md) —
the short version is that putting the lamp near a window is worth about
ten times more than any antenna you can buy.

---

---

## 2. Flash MicroPython

Full walkthrough with per-OS port hunting and every failure mode:
**[docs/FLASHING.md](FLASHING.md)**. The short version:

```bash
pip install esptool mpremote
```

Enter bootloader mode — hold **B** (BOOT), tap **R** (RESET), release
**B**. The port number often changes when you do this, so re-check it.

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 921600 \
           write_flash -z 0 ESP32_GENERIC_S3-*.bin
```

Grab the image from
[micropython.org](https://micropython.org/download/ESP32_GENERIC_S3/).
Note `-z 0` — the S3 image goes at offset **0**, not `0x1000` like the
older ESP32. Tap **R**, then confirm:

```bash
mpremote connect /dev/ttyACM0 exec "import sys; print(sys.implementation)"
```

> If no serial port appears at all, suspect **the cable** before anything
> else. Plenty of USB-C cables are charge-only.

The **Wio-E5 needs no flashing** — its LoRaWAN AT firmware is already on
it, which is the whole reason for choosing it over a bare SX1262.

---

---

## 3. Set up The Things Network

**Never used TTN before? Read this box first — it's five minutes and the
rest will make sense.**

> **Gateway** — someone else's box on a rooftop, listening for LoRa
> radio. You don't own one, you don't configure one, and your lamp
> doesn't know which one it's using. It just shouts, and whichever
> gateway hears it forwards the message over *its owner's* internet.
> That's the trick that means your home doesn't need internet.
>
> **Application** — a folder in your TTN account. Both lamps live in one.
>
> **End device** — one lamp. You'll register two.
>
> **Uplink** — lamp → network. Cheap; you get ~150/day.
> **Downlink** — network → lamp. **Only 10 a day.** This is the limit that
> matters.
>
> **OTAA** — how a lamp proves who it is when it joins, using three
> secrets you'll copy out of the console:
> **DevEUI** (the lamp's serial number), **JoinEUI** (which server to
> join — all zeros is fine), and **AppKey** (the actual secret).
>
> **It is free.** No card, no trial. The plan is called *Sandbox*.

### 3a. Make an account

Go to **[console.cloud.thethings.network](https://console.cloud.thethings.network)**
and sign up.

You'll be asked to choose a **cluster** — a regional server. Pick
**Europe 1 (eu1)** if you're in Europe. This must be the *same* cluster
for both lamps, so whatever you pick, write it down.

### 3b. Create one application

Click **Applications → + Create application**.

| Field | What to put |
|---|---|
| Application ID | `friend-lights` |
| Name | anything, or leave blank |

Everything else can stay as it is. Click **Create application**.

> Both lamps go in this one application. Not because TTN will pass
> messages between them — it won't, that's what
> [step 4](#4-deploy-the-bridge) is for — but so they share one webhook
> and one API key.

### 3c. Register the first lamp

Inside your application: **End devices → + Register end device**.

Choose **Enter end device specifics manually** (the tab at the top —
*not* the device repository).

Now fill in, in order:

**Frequency plan** → `Europe 863-870 MHz (SF9 for RX2 - recommended)`

**LoRaWAN version** → `LoRaWAN Specification 1.0.3`

**Regional Parameters version** → `RP001 Regional Parameters 1.0.3 revision A`

> These three must match what the Wio-E5 module expects. They are not
> preferences — get one wrong and the lamp will transmit but never join.

Click **Show advanced activation, LoRaWAN class and cluster settings**:

**Activation mode** → `Over the air activation (OTAA)`

**Additional LoRaWAN class capabilities** → tick **Class C (Continuous)**

> **Don't skip Class C.** Your lamp is plugged into a wall, so it can
> keep listening all the time. In the default Class A it only listens for
> a couple of seconds right after it transmits — so a message from your
> friend would sit in a queue for up to 15 minutes. Same 10-a-day budget
> either way; Class C just means they arrive when they're sent.

Then:

| Field | What to do |
|---|---|
| JoinEUI (AppEUI) | type `0011223344556677` → **Confirm** (see the note below) |
| DevEUI | click **Generate** |
| AppKey | click **Generate** |
| End device ID | `lamp-1` ← **write this down** |

Click **Register end device**.

> **Why not sixteen zeros?** The console offers all-zeros and TTN's docs
> say it is fine. Usually it is. But some LoRaWAN stacks read an all-zero
> JoinEUI as "not configured yet" and refuse to join, with no error that
> says so — you just watch a lamp transmit forever and never connect.
> Inventing a value costs nothing and removes the possibility. Any 16 hex
> characters will do; it is an identifier, not a secret.

**📋 Copy these three now** — DevEUI, JoinEUI and AppKey. They go into
`config.py` in step 5. You can always come back: the device page shows
DevEUI and JoinEUI, and AppKey is under **General settings → Join
settings** behind an eye icon.

### 3d. Register the second lamp

Same application, same steps, **same frequency plan and versions**.

What differs, and what must not:

| | |
|---|---|
| **End device ID** | `lamp-2` — must differ |
| **DevEUI** | Generate again — must differ, it identifies the device |
| **AppKey** | Generate again — must differ, it is that lamp's secret |
| **JoinEUI** | **the same** `0011223344556677` — it identifies the join server, not the lamp |

### ✅ Checkpoint

You should now have, under one application, two end devices called
`lamp-1` and `lamp-2`, both showing **Class C** and **OTAA**, and six
values written down (a DevEUI and AppKey for each, plus the zeros
JoinEUI).

Both will say *"Never seen"* — that's expected, they haven't been
switched on yet.

---

---

## 4. Deploy the bridge

**Why this exists:** TTN takes your lamp's message and stops there. It
will not pass it to the other lamp — not even though they're in the same
application. Something has to catch each message and send it on. This is
that something, and without it your lamps will join the network happily
and never hear each other.

It's about forty lines and runs free forever. **No terminal, no Node, no
install** — it's all in the browser.

### 4a. Create the worker

1. Sign up at **[dash.cloudflare.com](https://dash.cloudflare.com)** (free,
   no card).
2. In the sidebar: **Compute (Workers) → Create → Start with Hello World
   → Deploy**.
3. Name it `friend-lights-bridge`.
4. Once deployed, click **Edit code**.
5. Delete everything in the editor. Open
   [`bridge/worker.js`](../bridge/worker.js) from this repo, copy the whole
   file, paste it in.
6. Click **Deploy**.

**📋 Copy your worker's URL** — something like
`https://friend-lights-bridge.yourname.workers.dev`.

### 4b. Give it a password

The worker URL is public, so without this anyone who finds it could drive
your lamps and burn the daily message budget.

Invent a long random string — mash the keyboard, 20+ characters. Call it
your **shared secret**.

In the worker: **Settings → Variables and Secrets → + Add**

| | |
|---|---|
| Type | **Secret** |
| Name | `SHARED_SECRET` |
| Value | your random string |

**Deploy** again.

> If you named your devices anything other than `lamp-1` and `lamp-2`,
> add a second variable here — Type **Text**, Name `LAMPS`, Value
> `your-id-1,your-id-2`.

### 4c. Make the downlink API key

**Do this before creating the webhook.** The webhook asks for a key, and
the key is only shown once — so make it first and have it on the
clipboard.

In your **application** (not a device): left menu → **API keys** →
**+ Add API key**.

| Field | Value |
|---|---|
| Name | `bridge-downlink` |
| Rights | choose **Grant individual rights**, then tick **Write downlink application traffic** |

Click **Create API key**.

> ⚠️ **Copy it now.** The Things Stack shows an API key exactly once. Leave
> the page without copying and it is gone forever — you can delete it and
> make a new one, but you cannot see that one again.

"Write downlink application traffic" is the only right the bridge needs.
Don't grant more: this key lives in a webhook config and its whole job is
to send one downlink per uplink.

### 4d. Point TTN at it

Still in your **application**: **Integrations → Webhooks → + Add webhook
→ Custom webhook**.

| Field | What to put |
|---|---|
| Webhook ID | `bridge` |
| Webhook format | **JSON** |
| Base URL | your worker URL from 4a |
| Downlink API key | paste the key from 4c |

Scroll to **Enabled event types**. Tick **Uplink message** and *nothing
else* — the others would just wake the worker for no reason.

Scroll to **Additional headers** and add one:

| Key | Value |
|---|---|
| `x-shared-secret` | your secret from 4b |

Click **Add webhook**.

> **The Downlink API key is the step people miss.** Without it TTN never
> sends the `X-Downlink-Apikey` header, the worker has no credentials to
> reply with, and the bridge answers every uplink with a 500 — so the
> lamps join fine and simply never hear each other.

### ✅ Checkpoint

Visit your worker URL in a browser. You should see:

```
friend-lights bridge
```

That means it's alive. It won't do anything else until a lamp sends
something.

---

## 5. Configure and load

Everything secret goes in one file, which git never sees.

```bash
cp .env.example .env
```

Fill in the six values you collected in step 3, plus how long your strip
is:

```
LAMP1_DEV_EUI = 70B3D57ED0......      # from the TTN device page
LAMP1_APP_KEY = ................      # Join settings, behind the eye
LAMP2_DEV_EUI = 70B3D57ED0......
LAMP2_APP_KEY = ................
JOIN_EUI      = 0011223344556677      # the SAME value on both lamps

NUM_LEDS      = 10                    # however many you soldered
NUM_GROUPS    = 3                     # colour zones; 1 for a flat colour
```

Then:

```bash
python3 tools/apply_env.py
```

That writes `firmware/config.lamp1.py` and `config.lamp2.py`. Both, and
`.env` itself, are gitignored — **there is no file you have to remember
not to commit.**

### Why it is generated rather than hand-edited

Three of the ways to get these six values wrong produce a lamp that
**joins the network perfectly and then does nothing**, with no error
anywhere saying why:

| Mistake | What you would see |
|---|---|
| Both lamps sharing a **DevEUI** | They fight over one session; neither stays joined |
| Lamps with **different JoinEUIs** | One never joins at all |
| Both lamps sharing a **`LAMP_ID`** | Both join fine, then ignore each other forever — the CRDT drops a message bearing your own id as an echo of itself |

None of those is visible by reading a config file, and all three are what
you get by copying one lamp's file and editing it — which is exactly what
anyone would do. So `apply_env.py` refuses to write anything that would
cause them, along with a missing key or a password WPA2 would silently
ignore.

### Load it

```bash
./tools/deploy.sh --lamp 1 /dev/ttyACM0
```

That runs the whole test suite first and refuses to deploy if anything
fails — see [the automated tests](TESTING.md#the-automated-tests) for why
that guard matters here.

Repeat with `--lamp 2` for the other board.

> Prefer to edit by hand? `firmware/config.example.py` is a fully
> commented template — copy it to `firmware/config.py`, fill it in, and
> run `./tools/deploy.sh` with no `--lamp`. You lose the cross-checks.

---

## 6. First light

```bash
mpremote connect /dev/ttyACM0 repl
```

Tap **R** on the board. You want:

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1 
[lorawan] joining...
[lorawan] joined
```

The strip breathes warm white while it joins — this can take a minute —
then settles.

### Reach it from your phone

The control network is up from boot, before LoRaWAN has even joined:

| | |
|---|---|
| Network | `deLENIghted-1` — set by `PORTAL_SSID` |
| Password | `lightupleni` |
| Page | opens by itself, or **http://192.168.4.1** |

That page is also the quickest way to confirm the board is alive and the
strip is wired correctly, without waiting on the radio at all.

### Watch it work in TTN

This is the tool that tells you what's actually happening, so it's worth
learning now. Open your device in TTN and click **Live data**.

When the lamp joins you'll see a green **Accept join-request**. Then
touch the pad and within 15 minutes you'll see:

| What you see | What it means |
|---|---|
| `Accept join-request` | The lamp is on the network. Coverage is fine. |
| `Forward uplink data message` | Your touch reached TTN. Radio works. |
| `Schedule downlink for transmission` **on the other lamp** | The bridge fired. Everything works. |

**If you see the uplink but no downlink on the other lamp, the bridge is
the problem** — not your wiring, not your radio. Check the worker (step
4) and its logs under **Workers → your worker → Logs**.

Do the same for lamp 2, and the two are linked.

### The very first sync

A brand-new lamp starts at counter zero, so until it hears from its
friend both lamps will look the same dull warm white. Touch one. Within
15 minutes the other starts drifting. Nothing is broken in the meantime.

---

---

Stuck? → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
Want to test before the hardware arrives? → [TESTING.md](TESTING.md)
