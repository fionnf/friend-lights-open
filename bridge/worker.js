/**
 * bridge/worker.js — the piece that makes two lamps into one lamp.
 *
 * The Things Network does NOT route one device's uplink to another
 * device, not even inside a single application. Uplinks go up to the
 * network server and stop there. Something has to turn lamp A's uplink
 * into lamp B's downlink, and this is that something.
 *
 * It is stateless, so it runs on Cloudflare's free tier forever: TTN
 * POSTs an uplink here, and this POSTs a downlink back to TTN for every
 * other lamp in the group. About forty lines, no server, no bill.
 *
 * ── Why "replace" and not "push" ────────────────────────────────────
 * TTN queues downlinks for a device. If a lamp is unreachable while five
 * uplinks arrive from its friend, `push` would queue five downlinks and
 * spend five of that lamp's ten daily allowance delivering four
 * superseded messages.
 *
 * Because the payload carries absolute counters rather than deltas, the
 * newest message contains everything the older ones did. So `replace`
 * collapses the whole backlog to one. This is the CRDT paying for itself
 * a second time, on a part of the system that isn't even on the device.
 *
 * ── Deploy ──────────────────────────────────────────────────────────
 *   npm create cloudflare@latest friend-lights-bridge
 *   # replace src/index.js with this file
 *   npx wrangler secret put SHARED_SECRET
 *   npx wrangler deploy
 *
 * Then in the TTN console: Integrations → Webhooks → Add webhook →
 * Custom webhook.
 *   Base URL:          https://<your-worker>.workers.dev
 *   Downlink API key:  create one with "write downlink" rights
 *   Enabled messages:  Uplink message  (only that one)
 *   Additional headers: x-shared-secret: <the same secret>
 */

// Lamps in the group. A lamp never receives its own state back — its own
// counter is authoritative and an echo could only roll it backwards.
// Override with a LAMPS environment variable: "lamp-zurich,lamp-cork".
const DEFAULT_LAMPS = ["lamp-1", "lamp-2"];

const FPORT = 8;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("friend-lights bridge\n", { status: 200 });
    }

    // The webhook URL is public, so anything on the internet can POST
    // here. Without this check, a stranger could drive both lamps and
    // burn the daily downlink budget.
    if (env.SHARED_SECRET) {
      const presented = request.headers.get("x-shared-secret");
      if (presented !== env.SHARED_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const sender = body?.end_device_ids?.device_id;
    const payload = body?.uplink_message?.frm_payload;
    if (!sender || !payload) {
      // Join accepts and status events land here too. Not an error —
      // just nothing to forward.
      return new Response("ignored", { status: 200 });
    }

    // TTN fills these in for us, so no URL or key is hardcoded. The URL
    // it gives is scoped to the SENDING device, so swap in each peer.
    const replaceUrl = request.headers.get("x-downlink-replace");
    const apiKey = request.headers.get("x-downlink-apikey");
    if (!replaceUrl || !apiKey) {
      return new Response(
        "webhook is missing downlink headers — set a Downlink API key " +
          "on the webhook in the TTN console",
        { status: 500 }
      );
    }

    const lamps = (env.LAMPS ? env.LAMPS.split(",") : DEFAULT_LAMPS)
      .map((s) => s.trim())
      .filter((id) => id && id !== sender);

    const results = await Promise.all(
      lamps.map(async (peer) => {
        // .../devices/<sender>/down/replace -> .../devices/<peer>/down/replace
        const url = replaceUrl.replace(
          `/devices/${sender}/`,
          `/devices/${peer}/`
        );
        const res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${apiKey}`,
          },
          body: JSON.stringify({
            downlinks: [
              {
                f_port: FPORT,
                frm_payload: payload, // already base64; forwarded verbatim
                priority: "NORMAL",
              },
            ],
          }),
        });
        return `${peer}:${res.status}`;
      })
    );

    return new Response(`${sender} -> ${results.join(" ") || "(no peers)"}\n`, {
      status: 200,
    });
  },
};
