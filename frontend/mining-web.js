/* Competition teams, live web (mining_web.py): the team's saved web reads and watches, on the Status sub-tab (mining-status.js
   puts MiningWeb.card(v) in its grid). Each row: the name and file (data/web/<name>.json), the address, how often it refreshes,
   when it last did, how many rows it holds and what changed. Refresh now, change how often, stop or delete. Agents make them with
   web_read's save_as / every_min; nothing here is site-specific. */
const MiningWeb = (() => {
  const W = "/api/mining/work";
  let data = null, wid = null, at = 0, loading = false, failed = "", wired = false;
  const err = e => e && Auth.toast(e.message);

  function need(v) {
    if (wid !== v.comp.id) { data = null; wid = v.comp.id; at = 0; failed = ""; }
    if (loading || Date.now() - at < 15000) return;
    loading = true;
    const me = wid;
    api(`${W}/comps/${me}/web`).then(r => { if (wid === me) { data = r; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { at = Date.now(); loading = false; if (wid === me) MiningWork.rerender(); });
  }

  function card(v) {
    need(v); wire();
    const S = data?.saved || [];
    const rows = S.map(s => `<li class="mwb-row">
        <span class="mwb-main"><b>${esc(s.name)}</b> <code class="small">${esc(s.file)}</code>
          <a class="faint small mwb-url" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url)}</a>
          <span class="faint small">${s.every_min && s.on ? `every ${s.every_min} min` : "not watched"}${s.last ? ` · read ${esc(s.last)}` : ""}${s.rows != null ? ` · ${s.rows} rows` : s.kind === "text" ? " · text" : ""}${s.next ? ` · next ${esc(s.next)}` : ""}</span>
          ${s.status === "failed" ? `<span class="mh-err small">${icon("alert")}${esc(s.error || "The last read failed.")}</span>` : ""}
          ${s.change ? `<span class="small">${icon("cycle")}${esc(s.change)}</span>` : ""}</span>
        <span class="row mwb-acts">
          <button type="button" class="btn sm" data-mwb="run" data-id="${s.id}" title="Read it now">${icon("cycle")}Now</button>
          <select class="mwb-every" data-id="${s.id}" aria-label="How often">${[0, 10, 30, 60, 360, 1440].map(m => `<option value="${m}" ${(s.on ? s.every_min : 0) === m ? "selected" : ""}>${m ? (m < 60 ? `${m} min` : m < 1440 ? `${m / 60} h` : "daily") : "Not watched"}</option>`).join("")}${[0, 10, 30, 60, 360, 1440].includes(s.on ? s.every_min : 0) ? "" : `<option selected>${s.every_min} min</option>`}</select>
          <button type="button" class="btn sm mw-danger" data-mwb="del" data-id="${s.id}" title="Forget it (the file stays)">${icon("trash")}</button></span></li>`).join("");
    return `<section class="mh-card ms-card ms-wide mwb"><h3>${icon("globe")}Live web</h3>
      <p class="faint small">Agents read any public page or API live with <b>web_read</b>${v?.sandbox?.internet_on ? "" : " (the sandbox has no internet)"}. What they save lands in <code>data/web/</code>; watched ones refresh by themselves and report changes on the board.</p>
      ${failed ? `<p class="mh-err small">${esc(failed)}</p>` : !data ? `<p class="faint small">Loading…</p>` : S.length ? `<ul class="mwb-list">${rows}</ul>`
        : `<p class="faint small">Nothing saved yet. Ask an agent, e.g. “Read ridges.ai/explore/28, save the miners as ridges-top and watch it every 30 minutes.”</p>`}</section>`;
  }

  async function act(b) {
    const id = b.dataset.id, k = b.dataset.mwb;
    if (k === "del") {
      return UI.confirm({ title: "Forget this saved read?", body: "It stops refreshing; its file in data/web/ stays until you delete it.", ok: "Forget",
        run: async () => { data = await api(`${W}/web/${id}`, { method: "DELETE" }); MiningWork.rerender(); Auth.toast("Forgotten"); } }).catch(err);
    }
    b.disabled = true; b.classList.add("loading");
    try { data = await api(`${W}/web/${id}/run`, { method: "POST" }); Auth.toast("Read again"); MiningWork.rerender(); }
    catch (e) { err(e); } finally { if (b.isConnected) { b.disabled = false; b.classList.remove("loading"); } }
  }

  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => { const b = e.target.closest("[data-mwb]"); if (b) act(b); });
    document.addEventListener("change", async e => {
      const s = e.target.closest(".mwb-every"); if (!s) return;
      const m = +s.value;
      try { data = await api(`${W}/web/${s.dataset.id}`, { method: "PATCH", body: m ? { every_min: m, on: true } : { on: false } }); Auth.toast(m ? "Watching" : "Not watched"); MiningWork.rerender(); }
      catch (er) { err(er); }
    });
  }

  return { card };
})();
