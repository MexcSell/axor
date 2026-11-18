// BUG-01 / NFR-008 (docs/update_2026-11-15): a small white board saying "Updated to block N" popped up at the
// bottom centre of the classic UI on every chain refresh. It came from frontend/app.js load(); the header's live
// indicator already shows the block. This guards against it coming back.  Run: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const front = path.join(__dirname, "..", "..", "frontend");
const files = fs.readdirSync(front).filter((f) => f.endsWith(".js"));

test("no toast announces a chain block update", () => {
  for (const f of files) {
    const src = fs.readFileSync(path.join(front, f), "utf8");
    assert.ok(!/toast\([^)]*(updated?|updateable|updatable) to block/i.test(src), `${f} toasts a block update`);
  }
});
