# Testing without hardware

Everything except the radio can be proven with a laptop. Worth doing
while you wait for parts: the cloud half is where the fiddly
configuration lives, and finding a wrong webhook now is much cheaper than
debugging it beside a lamp that "just doesn't work".

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

### Open the lamp's page, with no lamp

```bash
python3 tools/preview_portal.py --leds 24 --groups 4 --lamps 2
#  -> http://127.0.0.1:8080
```

Not a mock of the page — it **is** the page, served through the real
`Portal` routing, driving the real CRDT and the real colour engine at 60
fps. If a button works here it works on the lamp.

`--lamps 2` has a friend touch theirs every twenty seconds, so you can
watch colour arrive slowly instead of jumping, and see the zones
reshuffle. `--leds` and `--groups` let you try a strip length before you
solder one.

This is also the cheapest way to decide `ARRIVAL_FADE_MS`. It is the
single number that determines whether the lamp reads as post or as a
notification, and it is far easier to judge here than beside real
hardware that speaks every three hours.

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

---

## The automated tests

```bash
python3 tests/test_codec.py         # wire format, and rejecting junk
python3 tests/test_shared_state.py  # CRDT convergence
python3 tests/test_portal.py        # portal routing, and rejecting junk
python3 tests/test_lorawan.py       # crypto, against published vectors
python3 tests/test_sx1262.py        # finding the radio, either pinout
python3 tests/test_regressions.py   # one case per bug that was shipped
python3 tests/test_firmware.py      # actually runs main() against stubs
```

No dependencies, no test runner. `tools/deploy.sh` runs every one of
them and refuses to load anything if any fails.

`test_shared_state.py` is the one that matters: each case is a specific
way the network will misbehave — reordering, duplication, heavy loss,
simultaneous edits, reboots — and asserts the lamps still agree anyway.

`test_regressions.py` holds one case per bug that actually shipped —
nothing goes in it speculatively. Every test in it failed before its fix.

`test_lorawan.py` checks the crypto against RFC 4493 and FIPS-197. A
wrong message integrity code gives you a lamp that transmits perfectly
and is ignored by the network, with nothing in the TTN console to say a
frame ever arrived — so published numbers are the only way to have any
confidence before a gateway exists.

`test_sx1262.py` covers finding the radio, and then the exact bytes the
driver puts on the SPI bus — checked against the datasheet, not against
the driver's own idea of itself. The chip can't be simulated, but the
transactions can be read, and every fault in this family is silent on
hardware: a response mis-framed by one byte reads as "TX never
completes" on a radio that is transmitting perfectly, and a missing
errata write is just fewer of the friend's messages arriving. The suite
pins the response framing, the PLL frequency words, the per-band image
calibration, the inverted-IQ and PA-clamp errata fixes, the public sync
word, and the TCXO ordering.

`test_firmware.py` **executes** `main()` rather than compiling it. On the
original project a bad push could be fixed over the air. Here it cannot:
ten bytes a message is not a firmware channel, so **a LoRa-only lamp has
no over-the-air recovery** and a boot loop means USB, or the post. Run the
tests before loading anything onto a lamp you're about to give away.

---