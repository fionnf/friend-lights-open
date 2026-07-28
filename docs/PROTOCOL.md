# Protocol

Everything two lamps ever say to each other is **10 bytes**, and it means
the same thing over LoRaWAN, over WiFi, or over anything added later.

---

## Why counters instead of colours

The Things Network's Fair Use Policy allows a device to **receive ten
downlink messages per day**. That number decides the whole design.

A conventional "here is my new colour, please apply it" protocol cannot
survive it. Miss a message — and you will miss most of them — and the two
lamps disagree permanently, with no way to notice or recover.

So the lamps never exchange colours. Each lamp owns **one grow-only
counter** and only ever increments its own. The displayed colour is a
function of the **sum of every lamp's counter**. This is a G-Counter CRDT,
and it buys exactly the three properties an unreliable link needs:

| Property | What it means here |
|---|---|
| **Commutative** | Messages arriving out of order converge anyway |
| **Idempotent** | The same message over LoRa *and* WiFi is harmless |
| **Self-healing** | Each message carries an absolute total, so the next one repairs whatever the last one lost — no acks, no retries, no sequence numbers |

The third is the one that matters most: **ten touches collapse into one
message with nothing lost**, because the total already contains them. The
network's meanest constraint ends up costing nothing.

---

## Wire format

10 bytes, big-endian.

| Byte | Field | Notes |
|---|---|---|
| 0 | `version` (high nibble) \| `flags` (low nibble) | version 1 |
| 1 | `lamp_id` | 1–255; 0 is reserved |
| 2–3 | `hue_total` | uint16, wrapping G-counter |
| 4–5 | `warm_total` | uint16, wrapping G-counter |
| 6–7 | `touch_count` | uint16, wrapping G-counter |
| 8 | `brightness` | 0–255 |
| 9 | reserved | 0 |

Flags: bit 0 = lamp is on, bit 1 = touched since last send.

**Rendering the state**

```
hue     = (Σ hue_total)  mod 65536 / 65536      # wraps — hue is a circle
warmth  = triangle(Σ warm_total)                # reverses — warmth is a range
touches = (Σ touch_count) mod 65536
```

Hue wrapping is not a compromise: a wrapping counter *is* the colour
wheel. Warmth is not circular, so its counter maps through a triangle
wave — it rises, then falls, and never snaps from 1.0 to 0.0 while the
counter underneath stays monotonic and therefore still converges.

**Trailing bytes are ignored, unknown versions are rejected.** A future
format may add fields; it may not silently reinterpret these ones.

---

## Running LoRaWAN and WiFi together

This is the part people expect to be hard. It isn't, because of the CRDT.

```
   touch ──►┌──────────────┐◄── any transport
            │ SharedColour │
            └──────┬───────┘
                   │
            ┌──────▼───────┐
            │ ColourEngine │   ← slow fade, see "Slow light"
            └──────────────┘
       ▲                        ▲
  ┌────┴────┐             ┌─────┴─────┐
  │ LoRaWAN │             │   MQTT    │
  │  (TTN)  │             │  (WiFi)   │
  └─────────┘             └───────────┘
```

Both transports carry **the same 10 bytes**. The router offers every
change to every transport and each decides for itself whether its budget
allows sending. There is deliberately **no primary link, no failover, and
no handover logic** — if both are up, the friend's lamp simply hears the
same state twice, which the CRDT absorbs without noticing.

What the transports do *not* need, and what the original two-board
firmware did:

- no echo suppression (the payload names its sender)
- no sequence numbers or acks
- no reconciliation between the two networks

They are not interchangeable, though. Identical format, very different
budgets:

| | Latency | Inbound messages/day | Send policy |
|---|---|---|---|
| WiFi / MQTT | ~100 ms | unlimited | send on every change |
| LoRaWAN / TTN | 2–10 s | **10** | throttled to ~15 min |

### What actually limits how often a lamp speaks

Not its own airtime — that was the first answer here and it was wrong.

TTN allows 30 s of uplink airtime per device per day, and a 10-byte frame
at SF9 costs ~0.2 s, so about **150 uplinks/day** are available. That is
not the constraint.

The constraint is the **friend's** allowance. Every uplink the bridge
forwards becomes a downlink on their lamp, and each device may receive
only **ten downlinks a day**. Uplinking more often does not deliver more
— the surplus is discarded before it reaches them, having cost the
transmission anyway.

So the send budget is ten a day:

| | Rate | Per day |
|---|---|---|
| Heartbeat (idle) | 12 h | 2 |
| Change-driven | 3 h **average** — a token bucket | up to 8 |
| | | **10** |

The change budget is a token bucket (`LORA_BURST`, default 4), not a
fixed gap: the first few touches of a day transmit immediately, and the
bucket refills one send every three hours. Latency and budget stopped
being the same knob — a quiet day's touches arrive in seconds while the
daily total stays inside the friend's ten downlinks. The lamp boots
with two tokens, not a full bucket, so flaky power cannot mint bursts.

Where the ten comes from: TTN's Fair Use Policy for the (free) Things
Stack Sandbox — **30 seconds of uplink airtime and 10 downlink messages
per device per 24 hours**. Sources: the policy thread
["Fair Use Policy explained"](https://www.thethingsnetwork.org/forum/t/fair-use-policy-explained/1300)
on the TTN forum, and the
[duty cycle documentation](https://www.thethingsnetwork.org/docs/lorawan/duty-cycle/),
which restates both numbers. It is a policy, not a hard enforcement —
which is a reason to respect it by design, not to creep past it.

`tools/simulate.py` is what caught this: the original 15-minute /
1-hour figures produced 38 uplinks a day against a 10/day cap, with three
quarters of them silently discarded.

Uplinks are **unconfirmed**. A confirmed uplink asks for an ACK, and every
ACK is a downlink billed against the ten-per-day allowance. The CRDT does
not need delivery guarantees, so paying for acknowledgement would buy
nothing and cost the budget.

### Use Class C

The lamp is plugged into a wall, so use **Class C**: the receiver stays
open continuously and a downlink arrives when it is sent. In Class A a
downlink waits until the lamp next transmits — up to three hours.

### Where the two networks meet

TTN is a closed world: devices reach TTN's servers, and TTN exposes them
to *you* over its own MQTT endpoint. A WiFi lamp is not a TTN device, so
something has to join the two. Three options, cheapest first:

1. **TTN's MQTT as the only broker.** The WiFi lamps and the web app all
   connect to TTN's application MQTT endpoint directly. No bridge, no
   server, nothing to run. Cost: payloads arrive JSON-wrapped and
   base64-encoded rather than raw, and every WiFi→LoRa message spends one
   of the ten daily downlinks.

2. **Your own broker as the hub, TTN bridged in.** Keep an ordinary MQTT
   broker (HiveMQ's free tier is ample), and forward TTN uplinks to it
   with a webhook → a ~40-line Cloudflare Worker on the free plan.
   Downlinks go back via TTN's HTTP API. More moving parts, but the web
   app keeps its own topics for scenes and alarms, which TTN's structured
   MQTT has no home for.

3. **The web app bridges.** It is already connected to both. Zero
   infrastructure, but only while a tab is open — so it is a convenience,
   not a transport.

**Recommended: option 2.** Option 1 is tempting but forces every non-lamp
concern — scenes, alarm schedules, presence — into a topic structure
designed for devices.

---

## Zones without paying for them

The original project splits the strip into zones, each its own colour,
with sizes reshuffled on every touch. Sending that would cost a few bytes
per zone on a link that allows ten messages a day.

So zones are **derived, not transmitted**. Both lamps run the same
integer hash over the same agreed counter:

```
zone 0        = the agreed position exactly
zone i        = position + (hash(counter, i) - 0.5) x spread
zone sizes    = partitioned by hash(counter, 100 + i)
```

Same counter in, same stripes out — on both lamps, with no extra byte.
The hash uses integer ops masked to 32 bits so MicroPython and CPython
agree exactly; anything drawing on `urandom` or the clock would give the
two lamps different strips.

Zone 0 is the agreed position unmodified, so a slider on the control page
still means what it says.

## Slow light

When a lamp learns a new total, it does not jump. It fades over minutes.

This began as an aesthetic choice — colour that arrives like post rather
than like a text — and then turned out to be exactly what ten downlinks a
day requires. The constraint and the intent are the same constraint.

Rendering policy, not protocol: a lamp that jumped instantly would still
be correct, just worse.

---

## Security

The payload is unauthenticated. Anyone who can send a downlink to your
device can change your lamp's colour.

Over TTN that is bounded — a downlink requires your application's API key,
so the exposure is whoever holds it. Over MQTT on a public broker it is
whoever guesses your topic. If that matters, put the lamps on a broker
with authentication; the 6 spare bits in byte 0 and byte 9 leave room for
a short MAC if it ever needs to travel over something genuinely open.
