/**
 * Run bridge/worker.js on your laptop, with a stand-in for The Things
 * Network, so the whole cloud path can be exercised offline.
 *
 *   node tools/run_bridge_locally.mjs
 *   python3 tools/test_bridge.py --url http://127.0.0.1:8787 \
 *       --secret test-secret --app demo --api-key demo-key \
 *       --downlink-base http://127.0.0.1:8787/fake-ttn
 *
 * This runs the REAL worker source — the same file you paste into
 * Cloudflare — against Node's built-in fetch/Request/Response, which are
 * the same web APIs the Workers runtime provides. So a pass here means
 * the logic is right, and a failure after deploying is configuration.
 *
 * Node 18+ (uses global Request/Response/fetch).
 */
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const worker = (await import(join(HERE, "..", "bridge", "worker.js"))).default;

const PORT = Number(process.argv[2] || 8787);

const env = {
  SHARED_SECRET: process.env.SHARED_SECRET || "test-secret",
  LAMPS: process.env.LAMPS || "lamp-1,lamp-2",
};

// Everything the fake TTN was asked to deliver, so the test can assert
// on what the worker actually sent rather than just that it returned 200.
const scheduled = [];

const server = createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks);
  const url = `http://${req.headers.host}${req.url}`;

  // ── Stand-in for The Things Stack's downlink API ──
  if (req.url.startsWith("/fake-ttn/")) {
    const auth = req.headers.authorization || "";
    if (!auth.startsWith("Bearer ")) {
      res.writeHead(403).end("no bearer token");
      console.log("  fake-ttn: REJECTED (no Authorization header)");
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(body.toString());
    } catch {
      res.writeHead(400).end("bad json");
      return;
    }
    const device = req.url.split("/devices/")[1]?.split("/")[0];
    const op = req.url.endsWith("/replace") ? "replace" : "push";
    const d = parsed.downlinks?.[0];
    scheduled.push({ device, op, ...d });
    console.log(
      `  fake-ttn: ${op} -> ${device}  f_port=${d?.f_port}  ` +
        `payload=${d?.frm_payload}`
    );
    res.writeHead(200, { "content-type": "application/json" }).end("{}");
    return;
  }

  if (req.url === "/__scheduled") {
    res.writeHead(200, { "content-type": "application/json" })
       .end(JSON.stringify(scheduled, null, 2));
    return;
  }

  // ── The real worker ──
  const request = new Request(url, {
    method: req.method,
    headers: req.headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : body,
  });

  let response;
  try {
    response = await worker.fetch(request, env);
  } catch (e) {
    console.error("  worker threw:", e);
    res.writeHead(500).end(String(e));
    return;
  }

  const text = await response.text();
  console.log(`${req.method} ${req.url} -> ${response.status} ${text.trim()}`);
  res.writeHead(response.status, {
    "content-type": response.headers.get("content-type") || "text/plain",
  }).end(text);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`bridge running on http://127.0.0.1:${PORT}`);
  console.log(`  SHARED_SECRET = ${env.SHARED_SECRET}`);
  console.log(`  LAMPS         = ${env.LAMPS}`);
  console.log(`  fake TTN at    http://127.0.0.1:${PORT}/fake-ttn`);
  console.log(`  what it sent:  http://127.0.0.1:${PORT}/__scheduled\n`);
});
