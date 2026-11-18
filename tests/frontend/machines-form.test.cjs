const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../frontend/machines.js"), "utf8");
const catalog = {
  os: {
    ubuntu: { family: "linux", title: "Ubuntu", min_ram: 2, ram: 4, disk: 32 },
    kali: { family: "linux", title: "Kali Linux", min_ram: 2, ram: 4, disk: 32 },
    custom: { family: "linux", title: "Custom Linux", min_ram: 1, ram: 2, disk: 32 },
    win11: { family: "windows", title: "Windows 11", min_ram: 4, ram: 8, disk: 64 },
  },
  languages: { en: "English", de: "German" },
  limits: { cores: 16, ram: 64, disk: 500 },
};

async function submission(machine, values) {
  let submit, request;
  const captured = new Error("request captured");
  const form = { elements: {} };
  const el = { classList: { add() {} }, addEventListener() {} };
  const ctx = vm.createContext({
    $: () => el, icon: () => "", esc: s => String(s ?? ""), setTimeout() {},
    Admin: { withSudo: fn => fn() },
    Auth: { modal(html, callback) {
      // Populate inputs from the real markup, as the browser does.
      for (const match of html.matchAll(/<input\b[^>]*\bname="([^"]+)"[^>]*>/g)) {
        form.elements[match[1]] = { value: match[0].match(/\bvalue="([^"]*)"/)?.[1] ?? "" };
      }
      for (const name of ["os", "language"]) {
        const options = html.match(new RegExp(`<select name="${name}"[^>]*>([\\s\\S]*?)</select>`))?.[1];
        if (options) form.elements[name] = { value: options.match(/<option value="([^"]+)" selected/)?.[1] ?? "" };
      }
      submit = callback;
      return form;
    } },
    api: async (url, options) => {
      if (url === "/api/platform/sudo") return {};
      request = JSON.parse(JSON.stringify({ url, ...options }));
      throw captured; // Stop before the successful response reloads the page.
    },
  });
  vm.runInContext(source.replace("return { open, close };", "return { testForm(x, data) { d = data; return form(x); } };") + "\nthis.subject = Machines;", ctx);
  await ctx.subject.testForm(machine, catalog);
  for (const [name, value] of Object.entries(values)) form.elements[name].value = String(value);
  await assert.rejects(submit(form), e => e === captured);
  return request;
}

test("editing Kali with null installation settings sends valid resource changes", async () => {
  const machine = { name: "dev-kali", settings: { os: "kali", cores: 2, ram: 4, disk: 32, url: null, username: null, language: null } };
  const request = await submission(machine, { cores: 4, ram: 8 });
  assert.deepEqual(request, { url: "/api/machines/dev-kali", method: "PUT", body: { name: "dev-kali", os: "kali", cores: 4, ram: 8, disk: 32 } });
});

test("editing Windows leaves its installed account and language to the server", async () => {
  const machine = { name: "dev-win", settings: { os: "win11", cores: 2, ram: 8, disk: 64, url: null, username: "alice", language: "de" } };
  const request = await submission(machine, { cores: 4, ram: 16 });
  assert.deepEqual(request.body, { name: "dev-win", os: "win11", cores: 4, ram: 16, disk: 64 });
});

test("creating a custom Linux machine sends its image URL", async () => {
  const request = await submission(null, { name: "dev-custom", os: "custom", url: " https://example.org/linux.iso " });
  assert.equal(request.method, "POST");
  assert.equal(request.body.url, "https://example.org/linux.iso");
  assert.equal(request.body.os, "custom");
});

test("creating Windows still sends its installation credentials and language", async () => {
  const request = await submission(null, { name: "dev-win", os: "win11", ram: 8, disk: 64, username: " alice ", password: "test-only-password", language: "de" });
  assert.equal(request.method, "POST");
  assert.equal(request.body.username, "alice");
  assert.equal(request.body.password, "test-only-password");
  assert.equal(request.body.language, "de");
});
