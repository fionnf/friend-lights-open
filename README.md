# Friend Lights Open

Two lamps in two homes, sharing one colour. Touch yours, and your
friend's drifts toward it over the next hour.

Built for the awkward case: **neither home has WiFi.** The lamps reach
each other over [The Things Network](https://www.thethingsnetwork.org) — a
free, community-run LoRaWAN network — by borrowing the internet
connection of whoever hosts the nearest gateway. No router, no SIM, no
hotspot, no monthly bill. About **€35 a lamp**, once.

> **Status:** complete and loadable, **not yet tested on real hardware.**
> Everything runs green against stubbed MicroPython, including a smoke
> test that executes `main()`. Nothing has yet met a real Wio-E5 or a
> real gateway. Descended from
> [linked_friend_lights](https://github.com/fionnf/linked_friend_lights).

---

## Contents

- [The idea](#the-idea)
- [How it actually works](#how-it-actually-works)
- [What you need](#what-you-need)
- [Never used TTN? start here](#3-set-up-the-things-network)
- [1. Build the lamp](#1-build-the-lamp)
- [2. Flash MicroPython](#2-flash-micropython)
- [3. Set up The Things Network](#3-set-up-the-things-network)
- [4. Deploy the bridge](#4-deploy-the-bridge)
- [5. Configure and load](#5-configure-and-load)
- [Test it all before the hardware arrives](#test-it-all-before-the-hardware-arrives)
- [Reading what happened](#reading-what-happened)
- [6. First light](#6-first-light)
- [Using the lamp](#using-the-lamp)
- [Living with ten messages a day](#living-with-ten-messages-a-day)
- [Adding WiFi later](#adding-wifi-later)
- [Troubleshooting](#troubleshooting)
- [Flashing in depth](docs/FLASHING.md)
- [Tests](#tests)
- [Not built yet](#not-built-yet)

---

## The idea

A lamp on a network that delivers **ten messages a day**, out of order,
with losses, and no acknowledgements. That sounds like a problem. It
turned out to be the design.

The lamps never send each other colours. Each owns a **grow-only counter**
and only ever increments its own; the colour you see is a function of the
sum. That makes updates commutative, idempotent and self-healing — a lost
message is repaired by the next one, and ten touches collapse into a
single message with nothing lost.

Which means the colour is not a mirror of your friend's lamp. It is a
**joint artifact** neither of you fully controls, and you can see their
influence in it. Both of you push; the light is where you ended up.

And it arrives *slowly* — over a minute or two, not instantly. That began
as an aesthetic choice, and then turned out to be exactly what ten
downlinks a day requires. Colour that arrives like post rather than like
a text.

---

## How it actually works

```
   your lamp                                          their lamp
       │                                                   ▲
       │ uplink (10 bytes)                       downlink  │
       ▼                                                   │
  ┌─────────┐      ┌──────────────┐      ┌────────────┐    │
  │ someone │─────►│     TTN      │─────►│   bridge   │────┘
  │ else's  │      │   network    │      │ (worker)   │
  │ gateway │      │    server    │◄─────│            │
  └─────────┘      └──────────────┘      └────────────┘
```

Three things worth understanding before you start:

**Your lamp has no idea gateways exist.** It transmits into the air. Any
gateway in earshot hears it and forwards it over *its owner's* internet.
No pairing, no association, nothing to configure. That is why neither of
you needs internet at home.

**TTN does not route device-to-device.** This trips everyone up. Putting
both lamps in one application does *not* make one lamp's uplink reach the
other — uplinks go up to the network server and stop. You need a small
piece of glue that turns lamp A's uplink into lamp B's downlink. That is
[the bridge](#4-deploy-the-bridge), and it's about forty lines running
free on Cloudflare.

**Reading is free, writing is rationed.** TTN's Fair Use Policy allows
30 s of uplink airtime and **ten downlinks per device per day**. Your lamp
can *talk* freely and can only *listen* ten times. Everything about the
design follows from that one number.

---

## What you need

| Part | ~Cost | Notes |
|---|---|---|
| [Seeed XIAO ESP32S3](https://www.seeedstudio.com/XIAO-ESP32S3-p-5627.html) | €13 | WiFi + BLE + native capacitive touch |
| [Seeed Grove Wio-E5](https://www.seeedstudio.com/Grove-LoRa-E5-STM32WLE5JC-p-4867.html) | €14 | LoRaWAN stack runs **on the module** |
| SK6812 RGBW strip | €5 | WS2812 works too, without the white channel |
| 5 V supply | — | USB is fine for a short strip |
| 330 Ω resistor | — | In series on the LED data line |

**Get the Wio-E5, not the Wio-SX1262.** The SX1262 is a bare modem, and
MicroPython has no LoRaWAN stack worth betting a project on — you'd be
rewriting everything in C++. The E5 carries a complete, certified stack
in its own firmware and is driven by AT strings over UART. That single
choice is why this project is 1,500 lines of Python instead of a C++ port.

### Before you order: check coverage

Look up **both** addresses on the [TTN map](https://www.thethingsnetwork.org/map),
then cross-check with **TTN Mapper**, which shows *measured* coverage
rather than claimed gateway locations. If either end has no gateway, none
of this works and no antenna will fix it.

### Two free accounts

Both free, neither wants a card:

- **[The Things Network](https://console.cloud.thethings.network)** — the radio network
- **[Cloudflare](https://dash.cloudflare.com)** — runs the 40-line bridge that connects the two lamps

### Values you'll collect along the way

Keep a scratch file. By the end of setup you'll have:

| From | What |
|---|---|
| TTN, lamp 1 | DevEUI, JoinEUI, AppKey |
| TTN, lamp 2 | DevEUI, JoinEUI, AppKey |
| Cloudflare | your worker URL |
| you | a shared secret you invent |

Only the six TTN values go on the lamps. The rest stays in the browser.

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

More on antennas and placement in [docs/HARDWARE.md](docs/HARDWARE.md) —
the short version is that putting the lamp near a window is worth about
ten times more than any antenna you can buy.

---

## 2. Flash MicroPython

Full walkthrough with per-OS port hunting and every failure mode:
**[docs/FLASHING.md](docs/FLASHING.md)**. The short version:

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
   [`bridge/worker.js`](bridge/worker.js) from this repo, copy the whole
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

```bash
python3 tools/make_config.py --lamp 1
```

It asks for the values you copied from TTN, checks them, and writes
`firmware/config.lamp1.py` (gitignored — keys never enter the repo). Run
it again with `--lamp 2` for the other one.

The reason it exists rather than "edit this file": three of the ways to
get these six values wrong produce a lamp that **joins the network
perfectly and then does nothing**, with no error anywhere saying why.

| Mistake | What you'd see |
|---|---|
| Both lamps sharing a **DevEUI** | They fight over one session; neither stays joined |
| Lamps with **different JoinEUIs** | One never joins at all |
| Both lamps sharing a **`LAMP_ID`** | Both join fine, then ignore each other forever — the CRDT treats a message bearing your own id as an echo of yourself and drops it |

So it cross-checks each lamp against the other and refuses to write a
file that would produce any of those.

To load it:

```bash
./tools/deploy.sh --lamp 1 /dev/ttyACM0
```

That runs the whole test suite first and refuses to deploy if anything
fails — see [Tests](#tests) for why that guard matters here.

> Prefer to edit by hand? `cp firmware/config.example.py
> firmware/config.py`, fill it in, and run `./tools/deploy.sh` with no
> `--lamp`. You lose the cross-checks.

---

## Test it all before the hardware arrives

Everything except the radio can be proven with a laptop. Do this while
you wait for parts — the cloud half is where the fiddly configuration
lives, and finding a wrong webhook now is much cheaper than debugging it
next to a lamp that "just doesn't work".

### The real test: simulate an uplink in TTN

This is the one that matters, because it exercises your **actual**
webhook, with TTN sending the real headers.

1. Open **lamp-1** in the TTN console → **Messaging** → **Simulate
   uplink**.
2. Set **FPort** to `8`.
3. Paste this payload — a genuine 10-byte frame, lamp 1, one touch:

   ```
   130110000AAA0001B200
   ```
4. **Send uplink**.

Then open **lamp-2** → **Messaging**. A downlink should be queued.

That is the whole chain — device → TTN → webhook → your worker → back
into TTN — proven without a single piece of hardware. If the downlink
appears, the only thing left untested is the radio itself.

More payloads, if you want to see the colour move between sends:

| Payload | Meaning |
|---|---|
| `130110000AAA0001B200` | lamp 1, 1 touch |
| `130120000AAA0002B200` | lamp 1, 2 touches (hue further round) |
| `130210000AAA0001B200` | lamp 2, 1 touch |

### Reading what happened

Two places tell you everything, and between them they say which half is
at fault.

**TTN → your device → Live data.** Watch both lamps:

| Event | Means |
|---|---|
| `Accept join-request` | on the network — coverage is fine |
| `Forward uplink data message` | the uplink reached TTN |
| `Receive downlink data message` on the **other** lamp | the bridge fired — it all works |

An uplink with no matching downlink on the peer is **always the bridge**,
never the radio.

**Cloudflare → your worker → Logs.** TTN discards webhook response
bodies, so the worker's log lines are the only record of what it decided:

| Log line | Means |
|---|---|
| `uplink from lamp-1: ...` then `scheduled -> lamp-2` | working |
| `REJECTED: bad or missing x-shared-secret` | the webhook header does not match the worker secret — or someone found your URL |
| `ERROR: TTN sent no downlink headers` | no Downlink API key on the webhook |
| `FAILED -> lamp-2: HTTP 403` | the API key lacks *Write downlink application traffic* |
| `FAILED -> lamp-2: HTTP 404` | wrong app, webhook or device id |
| only `ignored:` lines | the webhook has event types other than **Uplink message** enabled |
| `-> (no peers)` | the sender is the only name in `LAMPS` |

### Test the worker on its own

Checks it is deployed, and — importantly — that it **rejects strangers**.
The worker URL is public, so if the secret check fails, anyone who finds
it can drive your lamps and spend the daily downlink budget.

```bash
python3 tools/test_bridge.py     --url https://your-worker.workers.dev     --secret YOUR_SECRET
```

Add TTN credentials to make it schedule a real downlink too:

```bash
python3 tools/test_bridge.py     --url https://your-worker.workers.dev     --secret YOUR_SECRET     --app friend-lights --api-key NNSXS....
```

### Run the whole bridge offline

No accounts, no internet, no deploy — runs the real `worker.js` against a
stand-in for TTN, so you can change the bridge and check it before
pasting into Cloudflare.

```bash
node tools/run_bridge_locally.mjs
python3 tools/test_bridge.py --url http://127.0.0.1:8787     --secret test-secret --app demo --api-key demo-key     --downlink-base http://127.0.0.1:8787/fake-ttn
```

### Watch two lamps for a week

```bash
python3 tools/simulate.py                       # a day
python3 tools/simulate.py --hours 168 --loss 0.6
python3 tools/simulate.py --arrival-fade 5      # what a mirror feels like
```

Runs the real colour engine and CRDT against a network with TTN's
constraints, drawing both strips in your terminal. This is how to decide
whether the lamp should feel like post or like a notification, which is
much easier here than by waiting three hours next to a real one.

---

## 6. First light

```bash
mpremote connect /dev/ttyACM0 repl
```

Tap **R** on the board. You want:

```
[boot] friend-lights-open 2026-07-27.1 — lamp 1 (Zurich)
[lorawan] joining...
[lorawan] joined
```

The strip breathes warm white while it joins — this can take a minute —
then settles.

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

## Using the lamp

**Tap** the pad — nudges the colour. **Hold 1 second** — power on/off.
**Hold 5 seconds** — opens the setup portal.

All three fire when you *lift your finger*, not when the timer passes, so
a long press does exactly one thing.

### The setup portal

Hold the pad for five seconds and the lamp raises **its own WiFi
network**, called `lamp-1-setup`. Join it from any phone and a page opens
by itself — colour, brightness, power, and the TTN keys.

Two things make this worth having:

**It is free.** Controlling the lamp from a metre away has no business
spending one of its ten daily messages. Everything you do here is instant
and unmetered; your friend's lamp picks the change up next time this one
transmits.

**It replaces editing `config.py` over USB.** Give a friend a lamp, they
hold the pad, join the network, paste their DevEUI and AppKey from their
own TTN account, and hit save. No laptop, no cable, no Python.

It works on **every phone**, which is why it is an access point and not
Bluetooth — Web Bluetooth does not exist on iOS in any browser, including
Chrome and Firefox there, because they are all WebKit underneath.

The network is open, shuts itself off after **five minutes**, and only
exists while someone is standing next to the lamp holding the pad. Values
entered there are validated on the lamp, not in the browser, and saved to
`provision.json` — which takes priority over `config.py`, so a
provisioned lamp keeps its settings through any firmware update.

> Your phone will warn that this network has no internet. That's correct
> — the lamp isn't a router. Stay connected anyway.


---

## Living with ten messages a day

This is the part to explain to whoever you give the second lamp to.

| | Budget |
|---|---|
| Uplink airtime | 30 s/day ≈ 150 messages — *not* the limit |
| **Downlinks** | **10/day** ← the real limit |
| Payload | 10 bytes |
| Latency | 2–10 s, plus the deliberate slow fade |

The catch is that these are *your friend's* ten. Every message you send
becomes a downlink on their lamp, so however freely your lamp could
transmit, it must not send more than they can receive.

So the lamp sends at most **ten times a day**: a heartbeat every 12 hours
so an idle pair still converges, and up to eight change-driven messages,
throttled to one every three hours.

Touch it twenty times in an evening and your friend does not get twenty
messages. They get one, containing all twenty, and their lamp pulses to
say so. Nothing is lost; it just travels together.

**This is the product, not a limitation.** If you want a mirror instead,
drop `ARRIVAL_FADE_MS` and `LORA_MIN_INTERVAL_MS` in `config.py` — but
you'll hit the ten-downlink ceiling by mid-morning and spend the rest of
the day disconnected.

---

## Adding WiFi later

If a home does get internet, set `WIFI_ENABLED = True` and fill in
`MQTT_*`. This does **not** replace LoRa — both transports run at once,
carrying identical 10-byte payloads.

No handover logic, no primary link, no failover. If both are up, the
friend's lamp simply hears the same state twice, and the CRDT absorbs the
duplicate without noticing. That is the entire payoff of paying the
CRDT's design cost up front.

A **phone hotspot** counts, and works on iPhone and Android alike. Details
in [docs/PROTOCOL.md](docs/PROTOCOL.md#running-lorawan-and-wifi-together).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no response — check wiring and baud rate` | TX/RX not crossed | XIAO TX → E5 RX, XIAO RX → E5 TX |
| `join failed` | No gateway hearing you | Move to a window; check the [TTN map](https://www.thethingsnetwork.org/map) |
| Joins, uplinks visible in TTN, other lamp never changes | **The bridge isn't running** | The single most common failure. Cloudflare → your worker → **Logs** |
| Bridge returns 500 "missing downlink headers" | No Downlink API key on the webhook | Create one under **Application → API keys** with *Write downlink application traffic*, then paste it into the webhook |
| Can't find the API key you made | TTN shows it once, at creation | Delete it and make a new one; there is no way to view it again |
| Bridge returns 403 | Shared secret mismatch | The `x-shared-secret` header must match the worker secret |
| Downlinks queue in TTN but never arrive | Device is Class A | Set **Class C** in Network layer settings |
| Both lamps ignore each other's touches | Same `LAMP_ID` | They must differ |
| Colour jumps backwards after a reboot | Counters weren't persisted | Should not happen — please open an issue |
| Strip lights white, wrong colours | `LED_ORDER` | SK6812 is `GRBW`, WS2812 is `GRB` |
| Touch never fires / fires constantly | Threshold | Print `TouchPad.read()` and set `TOUCH_THRESHOLD` between resting and touched |
| Portal network doesn't appear | Held for under 5 s, or `PORTAL_ENABLED = False` | Keep holding; the strip keeps rendering throughout |
| Joined the portal, no page opened | Phone suppressed the captive-portal prompt | Open a browser and go to `192.168.4.1` |
| Portal vanished | 5-minute idle timeout | Hold the pad again |
| Colour changes feel far too slow | Working as intended | See [above](#living-with-ten-messages-a-day) |

---

## Tests

```bash
python3 tests/test_codec.py         # wire format, and rejecting junk
python3 tests/test_shared_state.py  # CRDT convergence
python3 tests/test_portal.py        # portal routing, and rejecting junk
python3 tests/test_regressions.py   # one case per bug that was shipped
python3 tests/test_firmware.py      # actually runs main() against stubs
```

No dependencies, no test runner. `tools/deploy.sh` runs all three and
refuses to load anything if they fail.

`test_shared_state.py` is the one that matters: each case is a specific
way the network will misbehave — reordering, duplication, heavy loss,
simultaneous edits, reboots — and asserts the lamps still agree anyway.

`test_regressions.py` holds one case per bug that actually shipped —
nothing goes in it speculatively. Every test in it failed before its fix.

`test_firmware.py` **executes** `main()` rather than compiling it. On the
original project a bad push could be fixed over the air. Here it cannot:
ten bytes a message is not a firmware channel, so **a LoRa-only lamp has
no over-the-air recovery** and a boot loop means USB, or the post. Run the
tests before loading anything onto a lamp you're about to give away.

---

## Layout

```
firmware/
├── main.py                 # the loop
├── config.example.py       # copy to config.py; never committed
└── lamp/
    ├── shared_state.py     # the CRDT — the heart of the project
    ├── codec.py            # the 10-byte wire format
    ├── engine.py           # slow arrival, breathing, pulses
    ├── palette.py          # hue -> RGBW
    ├── driver.py           # SK6812/WS2812 via ESP32 RMT
    ├── touch.py            # native ESP32-S3 capacitive touch
    ├── portal.py           # SoftAP + captive portal, non-blocking
    ├── www/index.html      # the local control page
    └── net/
        ├── transport.py    # one interface, several radios
        ├── lorawan_e5.py   # Wio-E5 over AT commands
        └── mqtt_wifi.py    # the same 10 bytes over WiFi
bridge/worker.js            # uplink -> the other lamp's downlink
docs/   PROTOCOL.md  HARDWARE.md
tools/  deploy.sh
tests/
```

---

## Not built yet

- **Remote viewer.** A static page subscribed read-only to TTN's MQTT.
  Reading is unmetered, so showing both lamps live costs nothing.
- **Alarms.** Sunrise/sunset, as in the original project. The clock needs
  a source first — LoRaWAN `DeviceTimeReq`, or the local app.

---

## Licence

MIT — see [LICENSE](LICENSE). Build one, change it, give it to a friend.
