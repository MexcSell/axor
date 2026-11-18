const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../frontend/auth.js"), "utf8");

function client(status, data) {
  const ctx = vm.createContext({
    UI: { begin: () => () => {} },
    fetch: async () => ({ ok: false, status, json: async () => data }),
  });
  vm.runInContext(source, ctx);
  return ctx.api;
}

test("API validation errors identify the rejected field without echoing its input", async () => {
  const data = { detail: [
    { loc: ["body", "language"], msg: "Input should be a valid string", input: null },
    { loc: ["body", "password"], msg: "String should have at most 127 characters", input: "secret-do-not-show" },
  ] };
  await assert.rejects(client(422, data)("/api/machines/dev-kali", { method: "PUT", body: {} }), e => {
    assert.equal(e.message, "language: Input should be a valid string; password: String should have at most 127 characters");
    assert.equal(e.status, 422);
    assert.equal(e.data, data);
    return true;
  });
});

test("API string errors remain intact", async () => {
  await assert.rejects(client(409, { detail: "The machine is stopping." })("/api/machines/dev-kali"), /The machine is stopping\./);
});

test("missing or malformed validation details retain the fallback message", async () => {
  for (const data of [{}, { detail: [] }, { detail: [null, { msg: {} }, { input: "secret" }] }]) {
    await assert.rejects(client(500, data)("/api/machines/dev-kali"), /Something went wrong\. Please try again\./);
  }
});
