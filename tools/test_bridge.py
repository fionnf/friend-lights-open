#!/usr/bin/env python3
"""
Exercise the deployed bridge without any hardware.

The bridge is the piece most likely to be wrong and the hardest to debug
once lamps are involved, because a misconfigured webhook looks exactly
like a radio problem: both lamps join fine and simply never hear each
other. This sends the bridge the same JSON The Things Stack would, with
the same headers, and tells you what it did.

  # check it is alive and rejecting strangers — needs nothing else
  python3 tools/test_bridge.py --url https://your-worker.workers.dev \\
                               --secret YOUR_SECRET

  # full path: really schedules a downlink for the other lamp
  python3 tools/test_bridge.py --url https://your-worker.workers.dev \\
                               --secret YOUR_SECRET \\
                               --app friend-lights \\
                               --api-key NNSXS.... \\
                               --from lamp-1

After the full run, open the OTHER lamp in the TTN console. Under
Messaging you should see a downlink queued. That is the entire cloud path
proven, with nothing but a laptop.
"""
import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/firmware/lamp")

try:
    import codec
except ImportError:
    codec = None

TIMEOUT = 20

passed, failed = [], []


def check(name, ok, detail=""):
    # The detail is a diagnosis of the failure, so printing it on a pass
    # reads as though something is wrong when nothing is.
    print(("  PASS  " if ok else "  FAIL  ") + name +
          (("\n          " + str(detail)) if detail and not ok else ""))
    (passed if ok else failed).append(name)


def http(url, method="GET", body=None, headers=None):
    """Returns (status, text). Never raises for HTTP error codes."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return 0, "%s: %s" % (type(e).__name__, e)


def uplink(device, payload_b64):
    """The subset of a TTN uplink the bridge actually reads."""
    return {
        "end_device_ids": {
            "device_id": device,
            "application_ids": {"application_id": "friend-lights"},
        },
        "received_at": "2026-07-27T12:00:00Z",
        "uplink_message": {
            "f_port": 8,
            "f_cnt": 1,
            "frm_payload": payload_b64,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="your worker URL")
    ap.add_argument("--secret", required=True, help="SHARED_SECRET")
    ap.add_argument("--app", help="TTN application id (enables the full test)")
    ap.add_argument("--api-key", help="downlink API key (enables the full test)")
    ap.add_argument("--webhook", default="bridge", help="webhook id")
    ap.add_argument("--from", dest="sender", default="lamp-1",
                    help="which lamp is pretending to transmit")
    ap.add_argument("--cluster", default="eu1")
    ap.add_argument("--downlink-base",
                    help="override the TTN host — point at the local "
                         "stand-in from run_bridge_locally.mjs")
    args = ap.parse_args()

    url = args.url.rstrip("/")

    # A real 10-byte frame, so this also proves the payload survives the
    # whole path rather than testing with arbitrary bytes.
    if codec:
        frame = codec.encode(1, 4096, 300, 7, brightness=0.6, on=True)
    else:
        frame = bytes([0x11, 1, 0x10, 0, 1, 0x2C, 0, 7, 153, 0])
    payload = base64.b64encode(frame).decode()
    print("payload: %s  (%s)\n" % (frame.hex(), payload))

    # ── Alive ────────────────────────────────────────────────
    print("is it deployed")
    status, text = http(url)
    check("worker responds", status == 200, "HTTP %s %s" % (status, text[:120]))
    check("it is the bridge, not a placeholder",
          "friend-lights bridge" in text,
          "got: %r — did the paste into the Cloudflare editor take?" % text[:80])

    # ── Secret ───────────────────────────────────────────────
    # The worker URL is public. If these pass, anyone who finds it can
    # drive your lamps and spend the daily downlink budget.
    print("\nis it protected")
    status, text = http(url, "POST", uplink(args.sender, payload))
    check("rejects a request with no secret", status == 403,
          "HTTP %s — the worker is OPEN to the internet" % status)

    status, text = http(url, "POST", uplink(args.sender, payload),
                        {"x-shared-secret": "definitely-not-the-secret"})
    check("rejects a wrong secret", status == 403, "HTTP %s" % status)

    hdr = {"x-shared-secret": args.secret}

    # ── Ignores what it should ───────────────────────────────
    print("\ndoes it ignore non-uplinks")
    status, text = http(url, "POST", {"end_device_ids": {"device_id": "lamp-1"},
                                      "join_accept": {"session_key_id": "x"}}, hdr)
    check("a join accept is ignored, not an error", status == 200,
          "HTTP %s %s" % (status, text[:80]))

    status, text = http(url, "POST", {"nonsense": True}, hdr)
    check("junk is ignored, not an error", status == 200,
          "HTTP %s %s" % (status, text[:80]))

    # ── Without TTN credentials it can go no further ─────────
    if not (args.app and args.api_key):
        print("\nno TTN credentials given, so stopping here.")
        print("Add --app and --api-key to prove the whole path:")
        print("  --app YOUR_APP_ID --api-key NNSXS....")
        print("Make the key under Application -> API keys with")
        print("'Write downlink application traffic'.")
        return report()

    # ── Full path ────────────────────────────────────────────
    # Hand the worker the same headers The Things Stack sends. If this
    # works, a real uplink will too.
    print("\ndoes it schedule a real downlink")
    base = args.downlink_base or (
        "https://%s.cloud.thethings.network" % args.cluster)
    path = ("/api/v3/as/applications/%s/webhooks/%s/devices/%s/down/replace"
            % (args.app, args.webhook, args.sender))
    full = dict(hdr)
    full["x-downlink-replace"] = base + path
    full["x-downlink-push"] = base + path.replace("/replace", "/push")
    full["x-downlink-apikey"] = args.api_key

    status, text = http(url, "POST", uplink(args.sender, payload), full)
    check("worker accepted the uplink", status == 200,
          "HTTP %s %s" % (status, text[:200]))

    body = text.strip()
    print("          worker said: %s" % body)

    check("it targeted at least one peer", "(no peers)" not in body,
          "the sender is the only lamp in LAMPS — set LAMPS in the worker")
    check("TTN accepted the downlink", ":200" in body,
          "a 403 means the API key lacks 'Write downlink application "
          "traffic'; a 404 means the app, webhook or device id is wrong")

    if ":200" in body:
        peer = body.split("->")[-1].split(":")[0].strip()
        print("\n  Now open device '%s' in the TTN console." % peer)
        print("  Messaging -> Downlink should show one queued.")
        print("  That is the whole cloud path working, with no hardware.")

    return report()


def report():
    print("\n%d passed, %d failed" % (len(passed), len(failed)))
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
