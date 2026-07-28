# Setup

Start to finish. Roughly an hour for the first lamp, twenty minutes for
the second.

> **The short way:** steps 2, 5 and 6 — everything that happens over
> the USB cable — are one rerunnable command:
>
> ```bash
> python3 tools/install.py
> ```
>
> Or do those steps by clicking, in **[Thonny](https://thonny.org)**:
> run `python3 tools/prepare_upload.py`, then upload the folder it
> builds. **[docs/FLASHING.md](FLASHING.md)** walks through both.
>
> Either way you still do step 1 (hands), step 3 (the TTN console) and
> step 4 (Cloudflare) yourself; the wizard asks for the values step 3
> gives you. The pages below remain the reference for what is
> happening, and for doing it by hand.

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
- **[Cloudflare](https://dash.cloudflare.com)** — runs the bridge

### Values you'll collect

Keep a scratch file:

| From | What |
|---|---|
| TTN, lamp 1 | DevAddr, NwkSKey, AppSKey |
| TTN, lamp 2 | DevAddr, NwkSKey, AppSKey |
| Cloudflare | your worker URL |
| you | a shared secret you invent |

Only the six TTN values go on the lamps.

> Using a **Wio-E5** instead? It collects DevEUI, JoinEUI and AppKey
> rather than those three — every screen that differs is called out as
> you reach it.

---

## 1. Build the lamp

**The radio needs no wiring.** The Wio-SX1262 has a board-to-board
connector on its underside that mates with the XIAO's. Line the two up
and press until they click. Nothing to solder, nothing to get backwards,
and the firmware works out for itself which pins it landed on.

Then the parts that do need a soldering iron:

```
XIAO GPIO2 ──[330Ω]── DIN   SK6812 strip
XIAO 5V    ──────────  VCC
XIAO GND   ──────────  GND

XIAO GPIO4  ──────────  copper pad / foil    (touch, optional)
```

Data flows DIN → DOUT, so connect to the **DIN** end of the strip. If
yours is wired from the far end, set `REVERSE_LEDS = True`.

The touch pad needs **no external resistor** — the ESP32-S3 has hardware
touch channels. Bare copper, foil, or a screw head all work. Set
`TOUCH_PINS = []` if you don't want one.

> **Wio-E5 instead?** That one is four wires to a UART, and TX/RX cross
> over:
>
> ```
> XIAO TX (GPIO43) ──►  RX    Wio-E5      ← they cross over
> XIAO RX (GPIO44) ◄──  TX
> XIAO 3V3         ──►  VCC
> XIAO GND         ──►  GND
> ```

⚠️ **Screw the antenna on before powering anything.** Transmitting into
an open connector can damage the radio.

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

**The radio needs no flashing of its own** — the SX1262 has no processor
in it, and the LoRaWAN stack runs on the XIAO alongside everything else.
(A Wio-E5 needs none either: it arrives with AT firmware already on it.)

Once the **firmware** is on (step 5), you can check the radio at any
time — it needs the lamp's own modules, so it will not run before then:

```bash
mpremote connect /dev/ttyACM0 run tools/radio_check.py
```

It probes both ways the module can be attached, reports which answered,
and stops at the first thing that is actually wrong. Attach the antenna
first, because it transmits.

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
> **ABP** — *activation by personalisation.* The lamp is handed its
> session up front rather than negotiating one, so there is no join step
> at all: it can transmit the moment it powers on. Three values, which
> you'll copy out of the console: **DevAddr** (the lamp's address on the
> network), **NwkSKey** and **AppSKey** (the two secrets). This is what
> the SX1262 uses, because catching a join reply means listening in a
> window that opens 5 s after transmitting and lasts milliseconds —
> which MicroPython's garbage collector can pause straight through.
>
> **OTAA** — the alternative, where the lamp joins by proving who it is:
> **DevEUI**, **JoinEUI** and **AppKey**. Only for the Wio-E5, whose own
> firmware handles the timing.
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

> These three are not preferences. `SF9 for RX2` in particular is what
> the firmware listens on — pick a different plan and the lamp will
> transmit fine and never hear a thing.

Click **Show advanced activation, LoRaWAN class and cluster settings**:

**Activation mode** → `Activation by personalization (ABP)`

**Additional LoRaWAN class capabilities** → tick **Class C (Continuous)**

> **Don't skip Class C.** Your lamp is plugged into a wall, so it can
> keep listening all the time. In the default Class A it only listens for
> a couple of seconds right after it transmits — so a message from your
> friend would sit in a queue for up to three hours. Same 10-a-day budget
> either way; Class C just means they arrive when they're sent.

Leave **Resets frame counters** switched **off**. The lamp keeps count
across power cuts by itself, and turning this on would let anyone replay
an old message at your lamp.

Then:

| Field | What to do |
|---|---|
| DevEUI | click **Generate** — ABP doesn't use it, but the console asks |
| Device address (DevAddr) | click **Generate** ← **copy it** |
| NwkSKey | click **Generate** ← **copy it** |
| AppSKey | click **Generate** ← **copy it** |
| End device ID | `lamp-1` ← **write this down** |

Click **Register end device**.

**📋 Copy those three now** — DevAddr, NwkSKey and AppSKey. They go into
`.env` in step 5. You can always come back for them: they are on the
device page under **General settings → Session information**, the two
keys behind an eye icon.

> **Using a Wio-E5?** Set **Activation mode** to
> `Over the air activation (OTAA)` instead, and the fields become
> JoinEUI, DevEUI and AppKey. Type `0011223344556677` for the JoinEUI
> and **Generate** the other two. The console offers sixteen zeros and
> TTN's docs say that is fine — usually it is, but some stacks read an
> all-zero JoinEUI as "not configured yet" and refuse to join with no
> error that says so. Inventing a value costs nothing. It is an
> identifier, not a secret, and it must be identical on both lamps.

### 3d. Register the second lamp

Same application, same steps, **same frequency plan and versions**.

What differs, and what must not:

| | |
|---|---|
| **End device ID** | `lamp-2` — must differ |
| **DevAddr** | Generate again — must differ, it is the lamp's address |
| **NwkSKey**, **AppSKey** | Generate again — must differ, they are that lamp's session |
| everything else | identical: same plan, same versions, same Class C |

Two lamps sharing a session fight over it and neither stays connected.
`tools/apply_env.py` refuses to write configs where they match, so a
copy-paste slip is caught before it reaches a board.

### ✅ Checkpoint

You should now have, under one application, two end devices called
`lamp-1` and `lamp-2`, both showing **Class C** and **ABP**, and six
values written down — a DevAddr, NwkSKey and AppSKey for each.

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
LORA_RADIO     = SX1262               # E5 if that is the module you have

LAMP1_DEV_ADDR = 260B....             # Session information, on the
LAMP1_NWK_SKEY = ................     #   TTN device page — the two
LAMP1_APP_SKEY = ................     #   keys are behind an eye icon
LAMP2_DEV_ADDR = 260B....             # lamp 2's own three, all different
LAMP2_NWK_SKEY = ................
LAMP2_APP_SKEY = ................

NUM_LEDS      = 10                    # however many you soldered
NUM_GROUPS    = 3                     # colour zones; 1 for a flat colour
```

> With `LORA_RADIO = E5` it wants `LAMP1_DEV_EUI`, `LAMP1_APP_KEY`, the
> same two for lamp 2, and one shared `JOIN_EUI` instead. Those lines
> are already in `.env.example`; leave whichever set you don't need
> blank.

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
| Both lamps sharing a **DevAddr** or session key | They fight over one session; neither stays connected |
| Both lamps sharing a **`LAMP_ID`** | Both connect fine, then ignore each other forever — the CRDT drops a message bearing your own id as an echo of itself |
| *(E5)* lamps with **different JoinEUIs** | One never joins at all |

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
[sx1262] found on the B2B kit pinout — NSS 41, RST 42, BUSY 40, DIO1 39
[lorawan] radio up, listening on 869.525 MHz SF9, fcnt 0
```

That first line is the firmware finding the radio for itself. It probes
both ways the module can be attached, so a line saying `header module`
instead is fine — it just means yours is on the header.

There is no "joining" step: ABP hands the lamp its session up front, so
it is ready the moment it powers on. The strip breathes warm white
through startup, then settles.

If instead you get:

```
[lora] no SX1262 answered — header module pinout: SPI returned 0000...
```

neither pinout replied, which means the connector rather than a setting.
Nothing in `config.py` can cause both to fail. Press the boards together
until they click, and run `radio_check.py` for a pin-by-pin report.

> **Wio-E5?** You'll see `[lorawan] joining...` then `joined` instead,
> and it can take a minute.

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

An ABP lamp says nothing until it transmits — no join to watch. Touch
the pad — the first few touches of a day go out within seconds — and
you'll see:

| What you see | What it means |
|---|---|
| `Forward uplink data message` | Your touch reached TTN. Radio and coverage are fine. |
| `Schedule downlink for transmission` **on the other lamp** | The bridge fired. Everything works. |

(With a Wio-E5 there's a green `Accept join-request` first.)

**If you see the uplink but no downlink on the other lamp, the bridge is
the problem** — not your wiring, not your radio. Check the worker (step
4) and its logs under **Workers → your worker → Logs**.

Do the same for lamp 2, and the two are linked.

### The very first sync

A brand-new lamp starts at counter zero, so until it hears from its
friend both lamps will look the same dull warm white. Touch one — the
first touches of a day travel in seconds — and the other starts
drifting. Only a busy day's later touches wait for the budget; see
[the README](../README.md#living-with-ten-messages-a-day).

---

---

Stuck? → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
Want to test before the hardware arrives? → [TESTING.md](TESTING.md)
