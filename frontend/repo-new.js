/* A new private GitHub repository, made through the Source hub (source.py: /api/source/config/owners and
   /config/sources/<id>/create) and added to its list. Administrators only, behind a fresh sudo: it makes something on GitHub.
   GitHub starts it with a README, so it has a default branch to branch from. Used by My subnets' "Save results to a
   repository" and by the file manager's GitHub pane. RepoNew.open() resolves to { repo, url, default_branch, repos } or null. */
const RepoNew = (() => {
  function dlg() {
    let d = document.getElementById("repo-new-dlg");
    if (!d) { d = document.createElement("dialog"); d.id = "repo-new-dlg"; d.className = "modal repo-new-dlg"; document.body.append(d); }
    return d;
  }
  async function open({ name = "", description = "" } = {}) {
    const d = dlg();
    d.innerHTML = `<div class="hq-dlg-in">${Loading.line("Asking GitHub where the token can make repositories…")}</div>`;
    d.showModal();
    let o;
    try { o = await api("/api/source/config/owners"); }
    catch (e) { d.close(); toast(e.message, { kind: "error" }); return null; }
    const opts = o.sources.flatMap(x => x.owners.map(w => ({ sid: x.id, label: x.label, ...w })));
    if (!opts.length) {
      d.innerHTML = `<div class="hq-dlg-in"><h3>${icon("repo")}New private repository</h3><p class="mh-err small">${icon("alert")}${esc(o.sources.map(x => x.error).filter(Boolean).join("; ") || "No GitHub source works right now. Check its token in the Source view.")}</p>
        <div class="row end"><button type="button" class="btn primary" data-rnx>Close</button></div></div>`;
      d.querySelector("[data-rnx]").onclick = () => d.close();
      return new Promise(res => { d.onclose = () => res(null); });
    }
    const many = new Set(opts.map(x => x.sid)).size > 1;
    d.innerHTML = `<form class="hq-dlg-in repo-new" autocomplete="off"><h3>${icon("repo")}New private repository</h3>
      <div class="repo-new-row"><label class="in"><span>Owner</span><select name="owner">${opts.map((x, i) => `<option value="${i}">${esc(x.login)}${x.kind === "org" ? " (organization)" : ""}${many ? ` · ${esc(x.label)}` : ""}</option>`).join("")}</select></label>
        <span class="repo-new-slash">/</span>
        <label class="in"><span>Name</span><input name="name" value="${esc(name)}" required maxlength="100" pattern="[A-Za-z0-9_.\\-]+" spellcheck="false" placeholder="mining-results"></label></div>
      <label class="in"><span>Description <em class="opt">optional</em></span><input name="description" value="${esc(description)}" maxlength="300"></label>
      <p class="faint small">GitHub makes it private, with a README so it has a default branch, and it joins the Source hub's list${o.full ? "" : ` (up to ${o.max_repos} repositories)`}.
        The token needs Administration read and write on that owner (fine-grained) or the repo scope (classic). A fine-grained token limited to chosen repositories can't write to the new one until you add it to the token on GitHub.</p>
      ${o.full ? `<p class="mh-err small">${icon("alert")}The Source hub already holds ${o.max_repos} repositories: remove one in the Source view first.</p>` : ""}
      <p class="err small" role="alert"></p>
      <div class="row end"><button type="button" class="btn" data-rnx>Cancel</button><button type="submit" class="btn primary" ${o.full ? "disabled" : ""}>${icon("plus")}Create repository</button></div></form>`;
    const f = d.querySelector("form"), msg = f.querySelector(".err");
    return new Promise(res => {
      let out = null;
      d.onclose = () => res(out);
      d.querySelector("[data-rnx]").onclick = () => d.close();
      f.onsubmit = async e => {
        e.preventDefault();
        const w = opts[+f.elements.owner.value], btn = f.querySelector("[type=submit]");
        btn.classList.add("loading"); btn.disabled = true; msg.textContent = "";
        try {
          out = await Admin.withSudo(() => api(`/api/source/config/sources/${encodeURIComponent(w.sid)}/create`, { method: "POST",
            body: { owner: w.login, name: f.elements.name.value.trim(), description: f.elements.description.value } }));
          toast(`Made ${out.repo} on GitHub`, { kind: "success" });
          d.close();
        } catch (x) { if (x.message !== "cancelled") msg.textContent = x.message; }
        finally { btn.classList.remove("loading"); btn.disabled = false; }
      };
      f.elements.name.focus();
    });
  }
  return { open };
})();
