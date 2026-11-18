// AXoR Functions runtime for Node.js: serves the function in /code/index.js over HTTP on PORT.
// The handler (module.exports[FN_HANDLER], may be async) gets the request as an object (method, path, query,
// headers, body, json, client, context) and returns the response: a string (text/plain), a Buffer, an object or
// array (JSON), or { statusCode, headers, body }. Calls longer than FN_TIMEOUT seconds get 504, thrown errors 500
// with the stack in the logs. Each call logs one JSON line ({"axor": "call", …}) the Functions page counts.
// GET /__axor/health is answered here, for the readiness check.
"use strict";
const http = require("http"), crypto = require("crypto");
const NAME = process.env.FN_NAME || "function", HANDLER = process.env.FN_HANDLER || "handler";
const TIMEOUT = Number(process.env.FN_TIMEOUT || 30), PORT = Number(process.env.PORT || 8080), MAX_BODY = 6 * 1024 * 1024;

const mod = require("/code/index.js");
const fn = typeof mod === "function" ? mod : mod[HANDLER];
if (typeof fn !== "function") { console.error(`index.js exports no function named ${HANDLER}.`); process.exit(1); }

function response(r) {
  let status = 200, headers = {}, body = r;
  if (r && typeof r === "object" && !Buffer.isBuffer(r) && "body" in r && ("statusCode" in r || "status" in r)) {
    status = r.statusCode ?? r.status; headers = r.headers || {}; body = r.body;
  }
  headers = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k, String(v)]));
  const has = k => Object.keys(headers).some(h => h.toLowerCase() === k);
  if (body == null) body = Buffer.alloc(0);
  else if (Buffer.isBuffer(body)) { if (!has("content-type")) headers["Content-Type"] = "application/octet-stream"; }
  else if (typeof body === "string") { if (!has("content-type")) headers["Content-Type"] = "text/plain; charset=utf-8"; body = Buffer.from(body); }
  else { if (!has("content-type")) headers["Content-Type"] = "application/json"; body = Buffer.from(JSON.stringify(body)); }
  return [Number(status), headers, body];
}

http.createServer((req, res) => {
  const u = new URL(req.url, "http://fn");
  const send = (status, headers, body) => {
    res.writeHead(status, { ...headers, "Content-Length": body.length });
    res.end(req.method === "HEAD" ? undefined : body);
  };
  if (u.pathname === "/__axor/health") return send(200, { "Content-Type": "text/plain" }, Buffer.from("ok"));
  const chunks = []; let size = 0, over = false;
  req.on("data", c => { size += c.length; if (size > MAX_BODY) over = true; else chunks.push(c); });
  req.on("end", async () => {
    if (over) return send(413, { "Content-Type": "text/plain" }, Buffer.from("Request body too large (6 MB at most)."));
    const body = Buffer.concat(chunks).toString("utf8"), id = req.headers["x-request-id"] || crypto.randomBytes(8).toString("hex");
    let json = null;
    if (body && (req.headers["content-type"] || "").includes("json")) try { json = JSON.parse(body); } catch { }
    const query = {};
    for (const [k, v] of u.searchParams) query[k] = k in query ? [].concat(query[k], v) : v;
    const event = { method: req.method, path: u.pathname, query, headers: req.headers, body, json,
      client: String(req.headers["x-forwarded-for"] || req.socket.remoteAddress).split(",")[0].trim(),
      context: { function: NAME, request_id: id, timeout: TIMEOUT } };
    const t0 = process.hrtime.bigint();
    let out;
    try {
      const r = await Promise.race([Promise.resolve().then(() => fn(event)),
        new Promise((_, no) => setTimeout(() => no(Object.assign(new Error(`${NAME} took longer than ${TIMEOUT}s.`), { timeout: true })), TIMEOUT * 1000))]);
      out = response(r);
    } catch (e) {
      if (!e?.timeout) console.error(e?.stack || String(e));
      out = [e?.timeout ? 504 : 500, { "Content-Type": "text/plain" }, Buffer.from(e?.timeout ? e.message : `${e?.name || "Error"}: ${e?.message || e}`)];
    }
    const ms = Math.round(Number(process.hrtime.bigint() - t0) / 1e5) / 10;
    out[1]["X-Request-Id"] = id;
    send(...out);
    console.log(JSON.stringify({ axor: "call", id, method: req.method, path: u.pathname, status: out[0], ms }));
  });
}).listen(PORT, "0.0.0.0", () => console.log(JSON.stringify({ axor: "start", function: NAME, handler: HANDLER, port: PORT })));
