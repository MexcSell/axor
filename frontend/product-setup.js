/* "Your product" in My subnets (Settings and the New campaign dialog): make the repository, the DevOps pipeline or the app
   right there instead of in Source, DevOps or Platform first. Names start from the product name. Administrators only, behind a
   fresh sudo, as on those pages: each one makes something on GitHub, the AXoR Runner or the cluster.
   The repository goes through RepoNew (repo-new.js); a pipeline through /api/devops/pipelines, built only from Source hub
   repositories; an app through /api/platform/apps. What's made fills the form's fields. In Settings (a form with data-cid) it is
   also linked to the campaign at once, product fields only, and the new state goes out as a "ps:linked" event for mining.js. */
const ProductSetup = (() => {
  const KIND = { devops: ["pipeline", "rocket"], app: ["app", "apps"] };
  const slug = (s, fb) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^[^a-z]+|-+$/g, "").slice(0, 30).replace(/-+$/, "") || fb;
  const field = (f, n) => f.elements[n];
  // the name, or the next free <name>-2, -3…
  const free = (base, taken) => { if (!taken.has(base)) return base; const root = base.replace(/-\d+$/, "").slice(0, 26); let n = 2; while (taken.has(`${root}-${n}`)) n++; return `${root}-${n}`; };
  function names(f) {
    const n = field(f, "netuid")?.value || f.dataset.netuid || "";
    const fb = n ? `sn${n}-miner` : "my-miner", product = slug(field(f, "product_name")?.value, fb);
    return { base: slug(field(f, "runs_name")?.value, "") || product, repo: product, product: field(f, "product_name")?.value.trim() || "", netuid: n };
  }
  const describe = nm => nm.product ? `${nm.product}, a miner${nm.netuid ? ` for SN${nm.netuid}` : ""}` : "";
  function dlg() {
    let d = document.getElementById("ps-dlg");
    if (!d) { d = document.createElement("dialog"); d.id = "ps-dlg"; d.className = "modal ps-dlg"; document.body.append(d); }
    return d;
  }
  // a dialog that shows a problem and a Close button
  function stop(d, title, msg) {
    d.innerHTML = `<div class="hq-dlg-in"><h3>${title}</h3><p class="mh-err small">${icon("alert")}${esc(msg)}</p>
      <div class="row end"><button type="button" class="btn primary" data-psx>Close</button></div></div>`;
    d.querySelector("[data-psx]").onclick = () => d.close();
    return new Promise(res => { d.onclose = () => res(null); });
  }
  // the form's submit runs make(form) → the result, or throws to show its message
  function run(d, make) {
    const f = d.querySelector("form"), msg = f.querySelector(".err");
    return new Promise(res => {
      let out = null;
      d.onclose = () => res(out);
      d.querySelector("[data-psx]").onclick = () => d.close();
      f.onsubmit = async e => {
        e.preventDefault();
        const btn = f.querySelector("[type=submit]");
        btn.classList.add("loading"); btn.disabled = true; msg.textContent = "";
        try { out = await make(f); d.close(); }
        catch (x) { if (x.message !== "cancelled") msg.textContent = x.message; }
        finally { btn.classList.remove("loading"); btn.disabled = false; }
      };
      f.querySelector("input:not([readonly])")?.focus();
    });
  }

  async function pipeline(f) {
    const d = dlg(), t = `${icon("rocket")}New DevOps pipeline`;
    try { await Admin.withSudo(() => api("/api/devops/sudo", { method: "POST" })); } catch (e) { if (e.message !== "cancelled") toast(e.message, { kind: "error" }); return null; }
    d.innerHTML = `<div class="hq-dlg-in">${Loading.line("Reading DevOps…")}</div>`;
    d.showModal();
    let o;
    try { o = await api("/api/devops"); } catch (e) { return stop(d, t, e.message); }
    if (!o.enabled) return stop(d, t, "DevOps isn't set up on this server: it needs the AXoR Runner (RUNNER_URL).");
    if (!o.github) return stop(d, t, "Connect GitHub in the Source view first: pipelines build from Source hub repositories.");
    const nm = names(f), want = (field(f, "repo")?.value || "").trim().replace(/^https:\/\/github\.com\//, "").replace(/\/+$/, "");
    const repos = [...o.repos], listed = repos.find(r => r.toLowerCase() === want.toLowerCase());
    const used = new Set(o.pipelines.map(x => x.host_port)), [lo, hi] = o.runner.ports || [9200, 9299];
    const free = (() => { for (let n = lo; n <= hi; n++) if (!used.has(n)) return n; return lo; })();
    const app = free(nm.base, new Set(o.pipelines.map(x => x.app)));
    d.innerHTML = `<form class="hq-dlg-in ps-form" autocomplete="off"><h3>${t}</h3>
      <label class="in"><span>Name</span><input name="app" value="${esc(app)}" required maxlength="30" pattern="[a-z][a-z0-9\\-]{0,29}" autocapitalize="none" spellcheck="false">
        <small class="faint">Lowercase letters, digits and dashes. Its container is <code>axor-&lt;name&gt;</code>.</small></label>
      <div class="ps-two"><label class="in"><span>Repository</span><select name="repo">${repos.map(r => `<option ${r === listed ? "selected" : ""}>${esc(r)}</option>`).join("")}<option value="__new">+ New private repository…</option></select></label>
        <label class="in"><span>Branch</span><input name="branch" value="main" required maxlength="250" autocapitalize="none" spellcheck="false"></label></div>
      ${want && !listed ? `<p class="faint small">${icon("info")}<code>${esc(want)}</code> isn't in the Source hub, and pipelines only build from its repositories. Add it in the Source view, or pick or make one here.</p>` : ""}
      <label class="in"><span>Dockerfile <small class="faint">(path in the repository)</small></span><input name="dockerfile" value="Dockerfile" required autocapitalize="none" spellcheck="false"></label>
      <label class="chk"><input type="checkbox" name="deploys" checked> Run it on this server after each build <small class="faint">(otherwise CI only: build and test)</small></label>
      <div class="ps-two ps-deploy"><label class="in"><span>The miner listens on port</span><input name="port" type="number" min="1" max="65535" value="8000"></label>
        <label class="in"><span>Published on host port <small class="faint">(${lo}–${hi})</small></span><input name="host_port" type="number" min="${lo}" max="${hi}" value="${free}"></label></div>
      <label class="chk"><input type="checkbox" name="now"> Build it now <small class="faint">(the repository needs its Dockerfile first)</small></label>
      <p class="faint small">Tests, health checks, memory, variables and secrets are in DevOps, under the pipeline's Settings.</p>
      <p class="err small" role="alert"></p>
      <div class="row end"><button type="button" class="btn" data-psx>Cancel</button><button type="submit" class="btn primary">${icon("plus")}Create pipeline</button></div></form>`;
    const el = d.querySelector("form").elements;
    if (!repos.length) el.repo.value = "__new";
    const branch = async () => {
      const [ow, n] = el.repo.value.split("/"); if (!n) return;
      const bs = await api(`/api/source/repos/${encodeURIComponent(ow)}/${encodeURIComponent(n)}/branches`).catch(() => []);
      const def = (Array.isArray(bs) ? bs : bs.branches || []).find(b => b.default);
      if (def && !el.branch.dataset.typed) el.branch.value = def.name;
    };
    el.branch.oninput = () => el.branch.dataset.typed = 1;
    el.deploys.onchange = () => { const x = d.querySelector(".ps-deploy"); x.hidden = !el.deploys.checked; x.querySelectorAll("input").forEach(i => i.disabled = !el.deploys.checked); };
    el.repo.onchange = async () => {
      if (el.repo.value !== "__new") { el.repo.dataset.prev = el.repo.value; return branch(); }
      const r = await RepoNew.open({ name: nm.repo, description: describe(nm) });
      if (!r) { el.repo.value = el.repo.dataset.prev || el.repo.options[0].value; return; }
      const x = document.createElement("option"); x.value = x.textContent = r.repo;
      el.repo.insertBefore(x, el.repo.querySelector('option[value="__new"]')); el.repo.value = el.repo.dataset.prev = r.repo;
      if (!el.branch.dataset.typed) el.branch.value = r.default_branch;
    };
    el.repo.dataset.prev = el.repo.value;
    branch();
    return run(d, async g => {
      const e = g.elements, dep = e.deploys.checked;
      if (e.repo.value === "__new") throw new Error("Pick the repository it builds from.");
      const body = { app: e.app.value.trim(), repo: e.repo.value, branch: e.branch.value.trim(), dockerfile: e.dockerfile.value.trim() || "Dockerfile",
        port: dep ? +e.port.value || null : null, host_port: dep ? +e.host_port.value || null : null };
      const p = await Admin.withSudo(() => api("/api/devops/pipelines", { method: "POST", body }));
      let ran = false;
      if (e.now.checked) {
        try { await Admin.withSudo(() => api(`/api/devops/pipelines/${p.id}/run`, { method: "POST", body: {} })); ran = true; }
        catch (x) { toast(`Made ${p.app}, but its first run didn't start: ${x.message}`, { kind: "error" }); }
      }
      toast(ran ? `Made ${p.app} and started its first build` : `Made ${p.app}: press Run in DevOps to build it`, { kind: "success" });
      return { kind: "devops", name: p.app, repo: body.repo };
    });
  }

  async function app(f) {
    const d = dlg(), t = `${icon("apps")}New app`;
    try { await Admin.withSudo(() => api("/api/platform/sudo", { method: "POST" })); } catch (e) { if (e.message !== "cancelled") toast(e.message, { kind: "error" }); return null; }
    d.innerHTML = `<div class="hq-dlg-in">${Loading.line("Reading the platform's apps…")}</div>`;
    d.showModal();
    let o;
    try { o = await api("/api/platform/apps"); } catch (e) { return stop(d, t, e.message); }
    const nm = names(f), taken = new Set((o.items || []).map(i => i.name));
    const name = free(nm.base, taken);
    d.innerHTML = `<form class="hq-dlg-in ps-form" autocomplete="off"><h3>${t}</h3>
      <label class="in"><span>Name</span><input name="name" value="${esc(name)}" required maxlength="30" pattern="[a-z][a-z0-9\\-]{0,29}" autocapitalize="none" spellcheck="false"></label>
      <label class="in"><span>Container image</span><input name="image" required maxlength="300" placeholder="ghcr.io/my-org/my-miner:1.0" autocapitalize="none" spellcheck="false">
        <small class="faint">The miner's image, as it is pulled: a registry the cluster can reach, with a tag.</small></label>
      <div class="ps-two"><label class="in"><span>The miner listens on port</span><input name="port" type="number" min="1" max="65535" value="8080"></label>
        <label class="in"><span>Memory (MB)</span><input name="memory" type="number" min="32" max="16384" value="512"></label></div>
      <label class="chk"><input type="checkbox" name="public"> Reachable from the web <small class="faint">(at its own address under the platform's domain)</small></label>
      <p class="faint small">Replicas, autoscaling, domains, variables, secrets and a volume are in Platform, under the app.</p>
      <p class="err small" role="alert"></p>
      <div class="row end"><button type="button" class="btn" data-psx>Cancel</button><button type="submit" class="btn primary">${icon("plus")}Create app</button></div></form>`;
    return run(d, async g => {
      const e = g.elements;
      const body = { name: e.name.value.trim(), image: e.image.value.trim(), port: +e.port.value || 8080, memory: +e.memory.value || 512, public: e.public.checked };
      const r = await Admin.withSudo(() => api("/api/platform/apps", { method: "POST", body }));
      toast(`Made ${r?.name || body.name}: the cluster is starting it`, { kind: "success" });
      return { kind: "app", name: r?.name || body.name };
    });
  }

  async function repo(f) {
    const nm = names(f);
    const r = await RepoNew.open({ name: nm.repo, description: describe(nm) });
    return r && { repo: r.repo };
  }

  // fill the form's fields with what was made (a pipeline's repository becomes the product's); in Settings, link it to the campaign now
  async function apply(f, r) {
    const b = {};
    if (r.repo) b.repo = field(f, "repo").value = r.repo;
    if (r.kind) { b.runs_kind = field(f, "runs_kind").value = r.kind; b.runs_name = field(f, "runs_name").value = r.name; sync(f); }
    if (!f.dataset.cid) return;
    try {
      const st = await api(`/api/mining/campaigns/${f.dataset.cid}`, { method: "PATCH", body: b });
      f.dispatchEvent(new CustomEvent("ps:linked", { bubbles: true, detail: st }));
      toast(r.kind ? `Linked: the team watches ${r.name}` : `Linked ${r.repo} to this campaign`);
    } catch (e) { toast(`Made it, but linking failed: ${e.message}. Press Save to try again.`, { kind: "error" }); }
  }

  // the "Create the pipeline / app" button follows "Where it runs"
  function sync(f) {
    const k = field(f, "runs_kind")?.value, b = f.querySelector("[data-ps=runs]");
    if (!b) return;
    b.closest(".ps-acts").hidden = !KIND[k];
    if (KIND[k]) b.innerHTML = `${icon(KIND[k][1])}Create the ${KIND[k][0]}`;
  }
  // the pipeline or app name suggests the ones there are, read when the field is first used
  const seen = {};
  async function suggest(input) {
    const f = input.form, k = field(f, "runs_kind")?.value;
    if (!KIND[k]) return;
    if (!input.list) { const l = document.createElement("datalist"); l.id = `ps-names-${Math.random().toString(36).slice(2, 8)}`; input.after(l); input.setAttribute("list", l.id); }
    if (!seen[k]) seen[k] = (k === "devops" ? api("/api/devops").then(o => o.pipelines.map(p => p.app)) : api("/api/platform/apps").then(o => (o.items || []).map(i => i.name))).catch(() => []);
    input.list.innerHTML = (await seen[k]).map(n => `<option value="${esc(n)}">`).join("");
  }

  document.addEventListener("click", async e => {
    const b = e.target.closest("[data-ps]"); if (!b || !b.form?.elements.product_name) return;
    const f = b.form, k = b.dataset.ps === "repo" ? "repo" : field(f, "runs_kind").value;
    b.disabled = true;
    try {
      const r = await (k === "repo" ? repo(f) : k === "devops" ? pipeline(f) : k === "app" ? app(f) : null);
      if (r) { if (k !== "repo") delete seen[k]; await apply(f, r); }
    } finally { b.disabled = false; }
  });
  const ours = t => t.form?.elements.product_name && t.form.querySelector("[data-ps]");
  document.addEventListener("change", e => { if (e.target.name === "runs_kind" && ours(e.target)) sync(e.target.form); });
  document.addEventListener("focusin", e => { if (e.target.name === "runs_name" && ours(e.target)) suggest(e.target); });
  return { pipeline, app, repo };
})();
