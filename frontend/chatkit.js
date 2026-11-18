/* Chat: the message UI every chat shares (Agents, Workspace, Study).
   - Messages: answers in Markdown with code blocks you can copy, long answers folded, read aloud, copy, edit and resend
     your own message, ratings, suggested replies, and the model and tokens under each answer.
   - Composer: + adds a file from your computer, a Scout Drive file or Source code (a file or folder of a repository on
     the Source hub); / lists commands; @ mentions; voice input; the model menu (Auto, a model, deep thinking); this
     chat's token use, with your usage today, this week and this month behind it. The box grows with what you type,
     can be made taller by dragging its top edge (one height for every chat) or expanded for a long message, and
     counts characters as you near the limit.
   - Display: text size, spacing, bubbles or a document layout, and Enter or Ctrl+Enter to send: one setting for every chat.
   Hosts render with Chat.log and Chat.composer, then call Chat.mount (composer) and Chat.bind (actions) on the result.
   The model choice is stored as hub.auto / hub.model / hub.effort, so it's the same in every tab. */
const Chat = (() => {
  const hp = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("hub." + k)); localStorage.setItem("hub." + k, JSON.stringify(v)); } catch { return null; } };
  const cp = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("chat." + k)); localStorage.setItem("chat." + k, JSON.stringify(v)); } catch { return null; } };
  const isAdmin = () => Auth.me()?.role === "admin";
  const fmtTokens = n => !n ? "0" : n < 1000 ? `${n}` : n < 1e6 ? `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k` : `${(n / 1e6).toFixed(1)}M`;
  const md = t => Agents.md(t || "");
  const micIcon = () => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>`;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const closeOn = (pop, keep) => setTimeout(() => document.addEventListener("click", function off(e) {
    if (!pop.isConnected) return document.removeEventListener("click", off);
    if (!pop.contains(e.target) && !(keep && e.target.closest(keep))) { pop.remove(); document.removeEventListener("click", off); }
  }), 0);
  function place(pop, btn, align = "right") {
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect(), go = () => {
      const above = b.top > pop.offsetHeight + 16;
      pop.style.top = (above ? b.top + scrollY - pop.offsetHeight - 8 : b.bottom + scrollY + 8) + "px";
      const left = align === "left" ? b.left : b.right - pop.offsetWidth;
      pop.style.left = Math.max(16, Math.min(left, innerWidth - pop.offsetWidth - 16)) + "px";
    };
    go(); new ResizeObserver(go).observe(pop);
    pop.addEventListener("keydown", e => { if (e.key === "Escape") { pop.remove(); btn.focus(); } });
  }

  // ---------- models: Auto, a model, deep thinking ----------
  let models = { providers: [], default: null, efforts: ["low", "medium", "high"] }, loading = null;
  const pick = { auto: hp("auto") ?? true, model: hp("model"), effort: hp("effort") || "medium" };
  const EFFORT = { low: ["Low", "Fastest answers"], medium: ["Medium", "Balanced"], high: ["High", "Most thorough, slower"] };
  async function loadModels(refresh = false) {
    models = await api(`/api/agents/models${refresh ? "?refresh=1" : ""}`).catch(() => models);
    loading = Promise.resolve(models); syncModel();
    return models;
  }
  const ensureModels = () => loading || (loading = loadModels());
  const allModels = () => models.providers.flatMap(p => p.models);
  const modelLabel = id => allModels().find(m => m.id === id)?.label || (id || "").split(":").slice(1).join(":") || "No model";
  const modelGroups = p => {
    const free = p.models.filter(m => m.free), paid = p.models.filter(m => !m.free);
    return free.length && paid.length ? [{ ...p, label: `${p.label} · free`, models: free }, { ...p, models: paid }] : [p];
  };
  // each provider shows its company's own logo in the company's colour (styles.css .prov-b-*): Claude and Claude Code →
  // Claude's spark, OpenAI and Codex → OpenAI, GitHub Copilot (API or CLI) → GitHub, OpenRouter → OpenRouter.
  // A local server has no company, so it keeps the plain server glyph
  const BRAND_PATH = {
    claude: "M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z",
    openai: "M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z",
    github: "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
    openrouter: "M16.778 1.844v1.919q-.569-.026-1.138-.032-.708-.008-1.415.037c-1.93.126-4.023.728-6.149 2.237-2.911 2.066-2.731 1.95-4.14 2.75-.396.223-1.342.574-2.185.798-.841.225-1.753.333-1.751.333v4.229s.768.108 1.61.333c.842.224 1.789.575 2.185.799 1.41.798 1.228.683 4.14 2.75 2.126 1.509 4.22 2.11 6.148 2.236.88.058 1.716.041 2.555.005v1.918l7.222-4.168-7.222-4.17v2.176c-.86.038-1.611.065-2.278.021-1.364-.09-2.417-.357-3.979-1.465-2.244-1.593-2.866-2.027-3.68-2.508.889-.518 1.449-.906 3.822-2.59 1.56-1.109 2.614-1.377 3.978-1.466.667-.044 1.418-.017 2.278.02v2.176L24 6.014Z",
  };
  const BRAND = { anthropic: "claude", terminal: "claude", openai: "openai", codex: "openai", copilot: "github", "copilot-cli": "github", openrouter: "openrouter" };
  const providerIcon = id => {
    const p = (id || "").split(":")[0], b = BRAND[p];
    if (b) return `<span class="prov prov-${esc(p)} prov-brand prov-b-${b}" aria-hidden="true"><svg class="icon brand" viewBox="0 0 24 24"><path${b === "openrouter" ? ` fill-rule="evenodd"` : ""} d="${BRAND_PATH[b]}"/></svg></span>`;
    return `<span class="prov prov-${esc(p)}" aria-hidden="true">${icon({ local: "server" }[p] || "chip")}</span>`;
  };
  // the model a request asks for: "auto" or an id; before the list has loaded, trust the saved choice
  function chosen() {
    if (pick.auto || !pick.model) return "auto";
    return !allModels().length || allModels().some(m => m.id === pick.model) ? pick.model : "auto";
  }
  const choice = () => ({ model: chosen(), effort: pick.effort });
  function modelButton() {
    ensureModels();
    const auto = chosen() === "auto", id = auto ? models.default : pick.model;
    const label = auto ? "Auto" : modelLabel(id);
    const tip = `${auto ? `Auto${id ? `: ${modelLabel(id)}` : ""}` : modelLabel(id)} · deep thinking ${EFFORT[pick.effort][0].toLowerCase()}`;
    return `<button type="button" class="model-btn cx-model" data-model-menu aria-haspopup="true" title="${esc(tip)}">${auto ? `<span class="prov prov-auto" aria-hidden="true">${icon("zap")}</span>` : providerIcon(id)}<span>${esc(label)}</span>
      <i class="cx-effort e-${esc(pick.effort)}" aria-hidden="true"><b></b><b></b><b></b></i>${icon("down")}</button>`;
  }
  const syncModel = () => {
    $$(".model-btn").forEach(b => { b.outerHTML = modelButton(); });
    $$("[data-cx-model]").forEach(el => { el.textContent = modelLabel(el.dataset.cxModel); });  // answers drawn before the list loaded
  };
  function modelMenu(btn, view = "main") {
    document.querySelector(".model-pop")?.remove();
    const pop = document.createElement("div"); pop.className = "popover model-pop"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Model settings");
    const draw = () => {
      if (view === "models") {
        pop.innerHTML = `<button type="button" class="mp-back" data-mp="main">${icon("down")}Model</button>` + (models.providers.flatMap(modelGroups).map(p => `
          <div class="mp-group">${providerIcon(p.id + ":")}${esc(p.label)}</div>
          ${p.models.map(m => `<button type="button" class="mp-item" data-pick="${esc(m.id)}" aria-pressed="${!pick.auto && pick.model === m.id}"><span>${esc(m.label)}</span>${!pick.auto && pick.model === m.id ? icon("check") : ""}</button>`).join("")
            || `<p class="mp-note">${!p.configured ? (isAdmin() ? `Not connected. <button type="button" class="linkbtn" data-settings>Set up</button>` : "Not connected") : esc(p.error || "No models found.")}</p>`}`).join("")
          || `<p class="mp-note">No models yet.${isAdmin() ? ` <button type="button" class="linkbtn" data-settings>Connect one</button>` : ""}</p>`)
          + (isAdmin() ? `<button type="button" class="mp-refresh" data-mp="refresh">${icon("reset")}Refresh list</button>` : "");
      } else if (view === "effort") {
        pop.innerHTML = `<button type="button" class="mp-back" data-mp="main">${icon("down")}Deep thinking</button>` + models.efforts.map(e => `
          <button type="button" class="mp-item" data-effort="${e}" aria-pressed="${pick.effort === e}"><span><b>${EFFORT[e][0]}</b><small>${EFFORT[e][1]}</small></span>${pick.effort === e ? icon("check") : ""}</button>`).join("")
          + `<p class="mp-note">How hard the model thinks before answering. Models without a thinking setting ignore it.</p>`;
      } else {
        const def = models.default;
        pop.innerHTML = `
          <label class="mp-row mp-auto"><span>${icon("zap")}Auto <span class="faint" title="Uses the default model your administrator picked${def ? `: ${esc(modelLabel(def))}` : ""}">${icon("info")}</span></span>
            <span class="switch"><input type="checkbox" id="mp-auto" ${pick.auto ? "checked" : ""}><span></span></span></label>
          <div class="mi-sep"></div>
          <button type="button" class="mp-row ${pick.auto ? "on" : ""}" data-mp="models"><span>Model</span><span class="mp-val">${providerIcon(pick.auto ? def : pick.model)}${esc(pick.auto ? `Auto · ${modelLabel(def)}` : modelLabel(pick.model))}${icon("down")}</span></button>
          <button type="button" class="mp-row" data-mp="effort"><span>Deep thinking</span><span class="mp-val">${EFFORT[pick.effort][0]}${icon("down")}</span></button>
          <p class="mp-note">Used by every chat, drill and tutor. ${pick.auto ? "Auto picks the default model." : ""}</p>`;
        pop.querySelector("#mp-auto").onchange = e => {
          pick.auto = e.target.checked; hp("auto", pick.auto);
          if (!pick.auto && !allModels().some(m => m.id === pick.model)) { pick.model = models.default; hp("model", pick.model); }
          syncModel(); draw();
        };
      }
    };
    pop.onclick = async e => {
      e.stopPropagation();
      if (e.target.closest("[data-settings]")) { pop.remove(); return Agents.openSettings(); }
      const mp = e.target.closest("[data-mp]")?.dataset.mp;
      if (mp === "refresh") { pop.innerHTML = Loading.line("Refreshing models…"); await loadModels(true); view = "models"; return draw(); }
      if (mp) { view = mp; return draw(); }
      const m = e.target.closest("[data-pick]");
      if (m) { pick.model = m.dataset.pick; pick.auto = false; hp("model", pick.model); hp("auto", false); syncModel(); view = "main"; return draw(); }
      const ef = e.target.closest("[data-effort]");
      if (ef) { pick.effort = ef.dataset.effort; hp("effort", pick.effort); syncModel(); view = "main"; return draw(); }
    };
    draw();
    place(pop, btn);
    ensureModels().then(() => { if (pop.isConnected) draw(); });
    closeOn(pop, "[data-model-menu]");
  }

  // ---------- display: one setting for every chat ----------
  const DISPLAY = {
    size: ["Text size", [["s", "Small"], ["m", "Medium"], ["l", "Large"]], "m"],
    density: ["Spacing", [["compact", "Compact"], ["comfy", "Comfortable"]], "comfy"],
    style: ["Layout", [["bubbles", "Bubbles"], ["doc", "Document"]], "bubbles"],
    send: ["Send with", [["enter", "Enter"], ["mod", "Ctrl+Enter"]], "enter"],
  };
  const disp = Object.fromEntries(Object.entries(DISPLAY).map(([k, [, opts, def]]) => [k, opts.some(([v]) => v === cp(k)) ? cp(k) : def]));
  function applyDisplay() { for (const k of ["size", "density", "style"]) document.documentElement.dataset["chat" + k[0].toUpperCase() + k.slice(1)] = disp[k]; }
  applyDisplay();
  // display buttons outside a composer (chat headers) open the menu from anywhere
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-cx-display]"); if (!b || b.closest(".cx-composer")) return;
    e.stopPropagation();
    const open = document.querySelector(".cx-disp"); open ? open.remove() : displayMenu(b);
  });
  const displayButton = () => `<button type="button" class="iconbtn sm cx-disp-btn" data-cx-display title="Chat display: text size, spacing, layout" aria-label="Chat display settings" aria-haspopup="true">${icon("type")}</button>`;
  function displayMenu(btn) {
    document.querySelector(".cx-disp")?.remove();
    const pop = document.createElement("div"); pop.className = "popover cx-disp"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Chat display");
    const draw = () => {
      pop.innerHTML = `<b class="cx-pop-h">Chat display <small class="faint">every chat</small></b>` + Object.entries(DISPLAY).map(([k, [label, opts]]) => `
        <div class="cx-disp-row"><span>${label}</span><div class="seg" role="group" aria-label="${label}">${opts.map(([v, l]) => `<button type="button" data-disp="${k}" data-v="${v}" aria-pressed="${disp[k] === v}">${l}</button>`).join("")}</div></div>`).join("")
        + `<p class="mp-note">Shift+Enter adds a line${disp.send === "mod" ? "; Enter adds one too" : ""}. Drag the top edge of the message box to make it taller; double-click it to reset.</p>`;
    };
    pop.onclick = e => {
      e.stopPropagation();
      const b = e.target.closest("[data-disp]"); if (!b) return;
      disp[b.dataset.disp] = b.dataset.v; cp(b.dataset.disp, b.dataset.v); applyDisplay(); draw();
    };
    draw(); place(pop, btn); closeOn(pop, "[data-cx-display]");
  }

  // ---------- usage ----------
  const tokensOf = items => (items || []).reduce((n, i) => n + (i.kind === "assistant" && i.tokens ? i.tokens : 0), 0);
  const usageButton = tokens => `<button type="button" class="cx-usage-btn" data-cx-usage title="Token usage: this chat and yours" aria-label="Token usage: ${fmtTokens(tokens)} in this chat" aria-haspopup="true">${icon("piechart")}<span>${fmtTokens(tokens)}</span></button>`;
  const SOURCE = { chat: "Agent chats", workspace: "Workspace", study: "Study tutors", practice: "Practice drills", lab: "Study lab", team: "Project team", board: "Whiteboard AI", profile: "Profile AI review", mining: "My subnets", writing: "Writing help", tech: "Technology Research" };
  async function usageMenu(btn, tokens = 0, turns = 0) {
    document.querySelector(".cx-use")?.remove();
    const pop = document.createElement("div"); pop.className = "popover cx-use"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Token usage");
    const head = `<b class="cx-pop-h">Token usage</b>
      <div class="cx-use-chat"><span>This chat</span><b>${fmtTokens(tokens)}</b><small class="faint">${turns} answer${turns === 1 ? "" : "s"}${turns ? ` · ${fmtTokens(Math.round(tokens / turns))} each` : ""}</small></div>`;
    pop.innerHTML = head + Loading.line("Loading your usage…");
    pop.onclick = e => e.stopPropagation();
    place(pop, btn); closeOn(pop, "[data-cx-usage]");
    let u;
    try { u = await api("/api/agents/usage"); } catch (e) { pop.innerHTML = head + `<p class="mp-note">${esc(e.message)}</p>`; return; }
    const max = Math.max(1, ...u.days.map(d => d.tokens)), day = d => new Date(d + "T12:00:00Z").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    const list = (xs, name) => xs.length ? `<ul class="cx-use-list">${xs.slice(0, 5).map(x => `<li><span>${name(x)}</span><i style="--w:${Math.max(2, x.tokens / xs[0].tokens * 100)}%"></i><b>${fmtTokens(x.tokens)}</b></li>`).join("")}</ul>` : `<p class="mp-note">Nothing yet.</p>`;
    pop.innerHTML = head + `
      <div class="cx-use-tiles"><div><small>Today</small><b>${fmtTokens(u.today)}</b></div><div><small>7 days</small><b>${fmtTokens(u.week)}</b></div><div><small>30 days</small><b>${fmtTokens(u.month)}</b></div></div>
      <div class="cx-use-chart" role="img" aria-label="Tokens per day, last 14 days">${u.days.map(d => `<span data-tip="${esc(day(d.day))} · ${fmtNum(d.tokens, 0)} tokens" aria-label="${esc(day(d.day))}: ${fmtNum(d.tokens, 0)} tokens"><i style="height:${d.tokens ? Math.max(4, d.tokens / max * 100) : 0}%"></i></span>`).join("")}</div>
      <p class="cx-use-tip faint" aria-live="polite">Last 14 days · hover a day</p>
      <div class="cx-use-h">By model · 30 days</div>${list(u.by_model, x => `${providerIcon(x.id)}${esc(x.id ? modelLabel(x.id) : "Unknown")}`)}
      <div class="cx-use-h">By feature · 30 days</div>${list(u.by_source, x => esc(SOURCE[x.id] || x.id))}`;
    const tip = pop.querySelector(".cx-use-tip");
    pop.querySelector(".cx-use-chart").addEventListener("pointerover", e => { const s = e.target.closest("[data-tip]"); if (s) tip.textContent = s.dataset.tip; });
    pop.querySelector(".cx-use-chart").addEventListener("pointerleave", () => { tip.textContent = "Last 14 days · hover a day"; });
  }

  // ---------- messages ----------
  const ATT_ICON = { skill: "zap", tool: "search", file: "file", source: "code" };
  const lastOfTurn = (items, n) => { const x = items[n + 1]; return !x || x.kind === "user" || x.kind === "note"; };
  /* items: user {text, attachments}, assistant {text, model, tokens, suggestions, index, rating}, tool {name, input},
     note {text}. o: agent (avatar), busy, busyLabel, toolHtml(i), rate (show ratings), share(i, n) -> extra action HTML,
     suggest (suggested replies after the last answer), speaking (index being read aloud), empty (HTML when no items). */
  function log(items, o = {}) {
    items = items || [];
    if (!items.length && !o.busy) return o.empty || "";
    const lastAnswer = items.map((x, i) => x.kind === "assistant" ? i : -1).filter(i => i >= 0).pop();
    return items.map((i, n) => {
      if (i.kind === "user") return `<div class="msg me cx-msg" data-n="${n}"><div class="bubble">${esc(i.text)}${i.attachments?.length ? `<div class="ac-mine-atts">${i.attachments.map(x => `<span>${icon(ATT_ICON[x.kind] || "file")}${esc(x.label)}</span>`).join("")}</div>` : ""}</div>
        <div class="cx-mine-acts"><button type="button" class="iconbtn sm" data-cx="edit" data-n="${n}" title="Edit and resend" aria-label="Edit and resend">${icon("edit")}</button>
          <button type="button" class="iconbtn sm" data-cx="copy" data-n="${n}" title="Copy" aria-label="Copy">${icon("copy")}</button></div></div>`;
      if (i.kind === "assistant") {
        const last = lastOfTurn(items, n), first = !items[n - 1] || items[n - 1].kind === "user" || items[n - 1].kind === "note";
        return `<div class="msg bot cx-msg" data-n="${n}">${o.agent ? (first ? agentAvatar(o.agent, "sm") : `<span class="ac-av-gap"></span>`) : ""}<div class="bubble">${md(i.text)}</div></div>
          ${last ? `<div class="ac-acts cx-acts">
            ${"speechSynthesis" in window ? `<button type="button" class="iconbtn sm ${o.speaking === n ? "on" : ""}" data-cx="speak" data-n="${n}" title="Read aloud" aria-label="Read aloud" aria-pressed="${o.speaking === n}">${icon("speaker")}</button>` : ""}
            <button type="button" class="iconbtn sm" data-cx="copy" data-n="${n}" title="Copy" aria-label="Copy">${icon("copy")}</button>
            ${o.rate && i.index != null ? `<button type="button" class="iconbtn sm ${i.rating > 0 ? "on" : ""}" data-cx="rate" data-r="1" data-n="${n}" title="Good answer" aria-label="Good answer" aria-pressed="${i.rating > 0}">${icon("thumbup")}</button>
            <button type="button" class="iconbtn sm ${i.rating < 0 ? "on" : ""}" data-cx="rate" data-r="-1" data-n="${n}" title="Bad answer" aria-label="Bad answer" aria-pressed="${i.rating < 0}">${icon("thumbdown")}</button>` : ""}
            ${o.share ? o.share(i, n) : ""}
            <span class="ac-spacer"></span>${i.model || i.tokens ? `<span class="ac-usage">${i.model ? `${providerIcon(i.model)}<span data-cx-model="${esc(i.model)}">${esc(modelLabel(i.model))}</span>` : ""}${i.tokens ? `${i.model ? " · " : ""}${fmtTokens(i.tokens)} tokens` : ""}</span>` : ""}</div>
            ${o.suggest !== false && n === lastAnswer && !o.busy && i.suggestions?.length ? `<div class="ac-suggest">${i.suggestions.map(x => `<button type="button" class="chip ac-chip" data-cx-say="${esc(x)}">${icon("right")}${esc(x)}</button>`).join("")}</div>` : ""}` : ""}`;
      }
      if (i.kind === "tool") return `<div class="tool-chip">${o.toolHtml ? o.toolHtml(i) : `${icon("search")}${esc(Agents.toolLabel(i.name))}`}</div>`;
      return `<div class="note">${icon("info")}<span>${esc(i.text)}</span></div>`;
    }).join("") + (o.busy ? `<div class="msg bot">${o.agent ? agentAvatar(o.agent, "sm") : ""}<div class="bubble typing" role="status" aria-label="${esc(o.agent?.name || "The agent")} is working on a reply"><span class="dots"><i></i><i></i><i></i></span><span class="typing-label" aria-hidden="true">${esc(o.busyLabel || "")}</span></div></div>` : "");
  }
  // after a log is in the page: copy buttons on code, long answers folded, scrolled to the end
  function enhance(el, scroll = true) {
    if (!el) return;
    el.querySelectorAll(".bubble pre:not([data-cx-done])").forEach(pre => {
      pre.dataset.cxDone = "1";
      const b = document.createElement("button"); b.type = "button"; b.className = "cx-code-copy"; b.dataset.cxCode = ""; b.title = "Copy code"; b.setAttribute("aria-label", "Copy code");
      b.innerHTML = icon("copy") + `<span>${esc(pre.dataset.lang || "Copy")}</span>`; pre.prepend(b);
    });
    el.querySelectorAll(".msg.bot .bubble:not([data-cx-fold])").forEach(b => {
      b.dataset.cxFold = "1";
      if (b.scrollHeight > 720) { b.classList.add("cx-folded"); b.insertAdjacentHTML("beforeend", `<button type="button" class="cx-unfold" data-cx="unfold">${icon("down")}Show the whole answer</button>`); }
    });
    if (scroll) el.scrollTop = el.scrollHeight;
  }
  const bound = new WeakMap();
  let speakingEl = null;
  /* Handles the message actions inside root. o: items() (the log's items), onSay(text) (a suggested reply or the
     resend), onRate(n, r), lang (for reading aloud), onSpeak(n) (to keep the read-aloud state across renders). */
  function bind(root, o) {
    if (bound.has(root)) { bound.set(root, o); return; }
    bound.set(root, o);
    root.addEventListener("click", async e => {
      const opts = bound.get(root), t = e.target;
      const code = t.closest("[data-cx-code]");
      if (code) { const txt = code.parentElement.querySelector("code")?.textContent || ""; try { await navigator.clipboard.writeText(txt); toast("Code copied"); } catch { toast("Couldn't copy"); } return; }
      const say = t.closest("[data-cx-say]"); if (say) return opts.onSay?.(say.dataset.cxSay);
      const a = t.closest("[data-cx]"); if (!a || !root.contains(a)) return;
      const k = a.dataset.cx, n = +a.dataset.n, item = (opts.items?.() || [])[n];
      if (k === "unfold") { const b = a.closest(".bubble"); b.classList.remove("cx-folded"); a.remove(); return; }
      if (!item) return;
      if (k === "copy") { try { await navigator.clipboard.writeText(item.text); toast("Copied"); } catch { toast("Couldn't copy"); } return; }
      if (k === "edit") {
        const ta = root.querySelector(".cx-composer textarea"); if (!ta || ta.disabled) return toast("Wait for the answer first");
        ta.value = item.text; ta.dispatchEvent(new Event("input")); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
        return;
      }
      if (k === "rate") return opts.onRate?.(n, +a.dataset.r, item);
      if (k === "speak") return speak(item.text, a, opts, n);
    });
  }
  function speak(text, btn, o, n) {
    if (!("speechSynthesis" in window)) return toast("Your browser can't read aloud");
    const was = speakingEl === btn && btn.classList.contains("on");
    speechSynthesis.cancel();
    $$("[data-cx=speak].on").forEach(b => { b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); });
    speakingEl = null; o.onSpeak?.(null);
    if (was) return;
    const tmp = document.createElement("div"); tmp.innerHTML = md(text); tmp.querySelectorAll("pre").forEach(p => p.remove());
    const u = new SpeechSynthesisUtterance(tmp.textContent), v = o.voice?.();
    if (o.lang) u.lang = o.lang; if (v) { u.voice = v; u.lang = v.lang; }
    u.onend = u.onerror = () => { btn.classList.remove("on"); btn.setAttribute("aria-pressed", "false"); if (speakingEl === btn) { speakingEl = null; o.onSpeak?.(null); } };
    speakingEl = btn; btn.classList.add("on"); btn.setAttribute("aria-pressed", "true"); o.onSpeak?.(n);
    speechSynthesis.speak(u);
  }
  const quiet = () => { if ("speechSynthesis" in window) speechSynthesis.cancel(); speakingEl = null; };

  // ---------- composer ----------
  const drafts = {};  // per chat key: { text, atts }, kept while the page is open
  const MAX = 4000;  // the servers' limit on a message
  let boxH = cp("boxH") || 0;  // the height dragged on the top edge (0: grow with the text); one for every chat
  const state = key => drafts[key] || (drafts[key] = { text: "", atts: [] });
  /* o: key, placeholder, disabled, busy, compact (narrow panels), plus (true, or extra menu items [{id, icon, label}]),
     slash ([[command, description, takes text?]]), mic (true or a language), model (default true), tokens and turns
     (this chat's usage), extra (HTML for more buttons), display (the display button here rather than in the chat's header). */
  function composer(o) {
    const st = state(o.key), off = o.disabled || o.busy;
    return `<form class="composer cx-composer ${o.compact ? "compact" : ""}" data-cx-key="${esc(o.key)}" novalidate>
      <div class="ac-atts cx-atts" ${st.atts.length ? "" : "hidden"}>${attsHtml(st.atts)}</div>
      <div class="cx-vgrip" data-cx-vgrip role="separator" aria-orientation="horizontal" aria-label="Message box height (arrow keys; double-click to reset)" tabindex="0" title="Drag to resize · double-click to reset"></div>
      <div class="cx-ta"><textarea name="message" rows="1" maxlength="${MAX}" placeholder="${esc(o.placeholder || "Message…")}" ${off ? "disabled" : ""} aria-label="Message">${esc(st.text)}</textarea>
        <button type="button" class="iconbtn sm cx-expand" data-cx-expand title="Expand the message box" aria-label="Expand the message box" aria-pressed="false">${icon("expand")}</button></div>
      <div class="composer-foot cx-foot">
        <div class="ac-tools cx-tools">
          ${o.plus !== false ? `<button type="button" class="iconbtn sm cx-plus" data-cx-plus title="Add a file, a Drive file or Source code" aria-label="Add files and more" aria-haspopup="true" ${off ? "disabled" : ""}>${icon("plus")}</button>` : ""}
          ${o.slash?.length ? `<button type="button" class="iconbtn sm" data-cx-slash title="Commands (/)" aria-label="Commands" ${off ? "disabled" : ""}>/</button>` : ""}
          ${o.mic && SR ? `<button type="button" class="iconbtn sm" data-cx-mic title="Voice input${typeof o.mic === "string" ? ` (${esc(o.mic)})` : ""}" aria-label="Voice input" aria-pressed="false" ${off ? "disabled" : ""}>${micIcon()}</button>` : ""}
          ${o.extra || ""}
        </div>
        <span class="ac-spacer"></span>
        <span class="cx-count num" aria-live="polite" hidden></span>
        ${o.usage !== false ? usageButton(o.tokens || 0) : ""}
        ${o.display ? displayButton() : ""}
        ${o.model !== false ? modelButton() : ""}
        <button class="btn primary ac-send ${o.busy ? "loading" : ""}" type="submit" aria-label="Send" ${off ? "disabled" : ""}>${icon("send")}</button>
      </div></form>`;
  }
  const attsHtml = atts => atts.map((x, i) => `<span class="ac-att ${x.id === "uploading" ? "busy" : ""}" title="${esc(x.label)}">${icon(ATT_ICON[x.kind] || "file")}<span>${esc(x.label)}</span>${x.id === "uploading" ? "" : `<button type="button" data-cx-unatt="${i}" aria-label="Remove ${esc(x.label)}">${icon("close")}</button>`}</span>`).join("");
  const ctl = new WeakMap();
  /* Wires a composer from Chat.composer. o (besides composer's): onSend(text, atts) -> false/throws to keep the draft;
     onCommand(cmd, rest) -> true when handled (otherwise the text is sent); mention(q, tab) -> [{title, items:
     [{kind, id, label, ic, note}]}] for @ and the + menu's extra items; turns and tokens for the usage menu. */
  function mount(form, o) {
    if (!form) return null;
    const key = o.key, st = state(key), ta = form.querySelector("textarea");
    const c = { form, ta, o };
    ctl.set(form, c);
    // grows with the text up to 40% of the window (30% in narrow panels), never below the dragged height; expanded: 60%
    const size = () => {
      const cap = Math.max(boxH, Math.round(innerHeight * (o.compact ? .3 : .4)));
      ta.style.height = "auto";
      const full = ta.scrollHeight;
      ta.style.height = (c.big ? Math.max(cap, Math.round(innerHeight * .6)) : Math.max(boxH, Math.min(full, cap))) + "px";
      ta.parentElement.classList.toggle("long", c.big || full > 96);
      const n = ta.value.length, el = form.querySelector(".cx-count");
      el.hidden = n < MAX * .75; el.textContent = `${n.toLocaleString()} / ${MAX.toLocaleString()}`;
      el.classList.toggle("warn", n >= MAX * .9 && n < MAX); el.classList.toggle("crit", n >= MAX);
    };
    const big = on => {
      c.big = on; const b = form.querySelector("[data-cx-expand]");
      b.title = on ? "Shrink the message box (Esc)" : "Expand the message box";
      b.setAttribute("aria-pressed", on); b.setAttribute("aria-label", b.title); b.innerHTML = icon(on ? "shrink" : "expand");
      size(); ta.focus();
    };
    c.size = size;
    const draw = () => { const box = form.querySelector(".cx-atts"); box.innerHTML = attsHtml(st.atts); box.hidden = !st.atts.length; };
    c.draw = draw;
    size();
    ta.addEventListener("input", () => { st.text = ta.value; size(); typed(c); });
    ta.addEventListener("focus", size);  // a box drawn while its panel was hidden measured nothing
    ta.addEventListener("paste", e => {  // maxlength cuts a long paste without a word, so say so
      const n = e.clipboardData?.getData("text").length || 0, room = MAX - ta.value.length + (ta.selectionEnd - ta.selectionStart);
      if (n > room) toast(`A message holds up to ${MAX.toLocaleString()} characters, so the last ${(n - room).toLocaleString()} weren't pasted. Attach long text as a file with + instead.`);
    });
    ta.addEventListener("keydown", e => {
      const pop = document.querySelector(".ac-pop");
      if (pop && pop.dataset.for === key && ["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(e.key)) return popKey(e, pop);
      if (e.key === "Escape" && c.big) { e.preventDefault(); return big(false); }
      if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
      const mod = e.ctrlKey || e.metaKey;
      if (disp.send === "enter" || mod) { e.preventDefault(); form.requestSubmit(); }
    });
    form.onsubmit = async e => {
      e.preventDefault();
      const text = ta.value; if (!text.trim() || ta.disabled) return;
      rec?.stop();
      const sent = st.atts.filter(x => x.id !== "uploading");
      const m = text.trim().match(/^\/(\w+)\s*(.*)$/s);
      if (m && o.onCommand && o.slash?.some(([k]) => k === m[1].toLowerCase())) {
        st.text = ""; ta.value = ""; size();
        if (await o.onCommand(m[1].toLowerCase(), m[2])) return;
      }
      st.text = ""; st.atts = []; ta.value = ""; c.big = false; size(); draw();
      let r;
      try { r = await o.onSend(text, sent); } catch { r = false; }
      if (r === false) { st.text = text; st.atts = sent; const f = $(`.cx-composer[data-cx-key="${CSS.escape(key)}"]`); const t2 = f?.querySelector("textarea"); if (t2 && !t2.value) { t2.value = text; t2.dispatchEvent(new Event("input")); } ctl.get(f)?.draw(); }
    };
    form.addEventListener("click", e => {
      const t = e.target;
      const un = t.closest("[data-cx-unatt]"); if (un) { st.atts.splice(+un.dataset.cxUnatt, 1); draw(); return; }
      if (t.closest("[data-cx-expand]")) return big(!c.big);
      if (t.closest("[data-cx-plus]")) { e.stopPropagation(); return plusMenu(c, t.closest("[data-cx-plus]")); }
      if (t.closest("[data-cx-slash]")) { e.stopPropagation(); ta.focus(); if (!ta.value.startsWith("/")) { ta.value = "/" + ta.value; st.text = ta.value; } return slash(c, ""); }
      if (t.closest("[data-cx-mic]")) return mic(c, t.closest("[data-cx-mic]"));
      if (t.closest("[data-cx-usage]")) { e.stopPropagation(); const u = t.closest("[data-cx-usage]"); return document.querySelector(".cx-use") ? document.querySelector(".cx-use").remove() : usageMenu(u, o.tokens || 0, o.turns || 0); }
      if (t.closest("[data-cx-display]")) { e.stopPropagation(); const b = t.closest("[data-cx-display]"); return document.querySelector(".cx-disp") ? document.querySelector(".cx-disp").remove() : displayMenu(b); }
      const mm = t.closest("[data-model-menu]"); if (mm) { e.stopPropagation(); return document.querySelector(".model-pop") ? document.querySelector(".model-pop").remove() : modelMenu(mm); }
    });
    form.querySelector("[data-cx-vgrip]").addEventListener("pointerdown", e => { if (c.big) big(false); vdrag(e, ta); });
    return c;
  }
  // ---------- the message box's height: drag its top edge, arrow keys on it, double-click to reset ----------
  const resizeAll = () => $$(".cx-composer").forEach(f => ctl.get(f)?.size());
  const setBoxH = (h, save) => { boxH = h < 48 ? 0 : Math.round(Math.min(h, innerHeight * .7)); resizeAll(); if (save) cp("boxH", boxH || null); };
  function vdrag(e, ta) {
    const g = e.currentTarget, y0 = e.clientY, h0 = ta.getBoundingClientRect().height;
    e.preventDefault(); g.setPointerCapture(e.pointerId);
    document.body.classList.add("cx-vresizing");
    const move = ev => setBoxH(h0 + y0 - ev.clientY);  // the box sits at the bottom: dragging up makes it taller
    const up = () => { g.removeEventListener("pointermove", move); g.removeEventListener("pointerup", up); g.removeEventListener("pointercancel", up); document.body.classList.remove("cx-vresizing"); setBoxH(boxH, true); };
    g.addEventListener("pointermove", move); g.addEventListener("pointerup", up); g.addEventListener("pointercancel", up);
  }
  document.addEventListener("dblclick", e => { if (e.target.closest("[data-cx-vgrip]")) setBoxH(0, true); });
  document.addEventListener("keydown", e => {
    const g = e.target.closest?.("[data-cx-vgrip]"); if (!g || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const h = g.closest(".cx-composer").querySelector("textarea").getBoundingClientRect().height;
    setBoxH(h + (e.key === "ArrowUp" ? 24 : -24), true);
  });
  addEventListener("resize", resizeAll);
  function add(key, x) {
    const st = state(key);
    if (!st.atts.some(y => y.kind === x.kind && y.id === x.id)) st.atts.push(x);
    if (st.atts.length > 6) { st.atts = st.atts.slice(-6); toast("Up to six attachments on a message"); }
    ctl.get($(`.cx-composer[data-cx-key="${CSS.escape(key)}"]`))?.draw();
  }
  function setDraft(key, text) { state(key).text = text; const f = $(`.cx-composer[data-cx-key="${CSS.escape(key)}"] textarea`); if (f) { f.value = text; f.dispatchEvent(new Event("input")); } }
  function focus(key) { const f = $(`.cx-composer[data-cx-key="${CSS.escape(key)}"] textarea`); if (f && !f.disabled) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }

  // + : upload, Drive, Source, and the host's extra items (skills, tools)
  function plusMenu(c, btn) {
    document.querySelector(".cx-plus-pop")?.remove();
    const pop = document.createElement("div"); pop.className = "popover cx-plus-pop"; pop.setAttribute("role", "menu");
    const extra = Array.isArray(c.o.plus) ? c.o.plus : [];
    pop.innerHTML = `
      <label class="mi" role="menuitem"><input type="file" class="sr" data-cx-file multiple>${icon("upload")}<span><b>Upload from computer</b><small>Saved to the Shared drive, then attached</small></span></label>
      <button type="button" class="mi" role="menuitem" data-cx-pick="drive">${icon("folder")}<span><b>AXoR Drive</b><small>A file from your drive or the Shared drive</small></span></button>
      <button type="button" class="mi" role="menuitem" data-cx-pick="source">${icon("code")}<span><b>Source code</b><small>A file or folder of a repository</small></span></button>
      ${extra.length ? `<div class="mi-sep"></div>${extra.map(x => `<button type="button" class="mi" role="menuitem" data-cx-extra="${esc(x.id)}">${icon(x.icon)}<span><b>${esc(x.label)}</b>${x.note ? `<small>${esc(x.note)}</small>` : ""}</span></button>`).join("")}` : ""}`;
    pop.onclick = e => {
      e.stopPropagation();
      const p = e.target.closest("[data-cx-pick]"); if (p) { pop.remove(); return picker(p.dataset.cxPick, xs => xs.forEach(x => add(c.o.key, x))); }
      const x = e.target.closest("[data-cx-extra]"); if (x) { pop.remove(); return mention(c, "", 0, x.dataset.cxExtra); }
    };
    pop.querySelector("[data-cx-file]").onchange = e => { const fs = [...e.target.files]; pop.remove(); fs.slice(0, 6).forEach(f => upload(f, c.o.key)); };
    place(pop, btn, "left"); closeOn(pop, "[data-cx-plus]");
  }
  // files go to the Shared drive's Workspace folder (so agents can read them) and onto the message
  async function upload(file, key) {
    const chip = { kind: "file", id: "uploading", label: `Uploading ${file.name}…` };
    if (key) { state(key).atts.push(chip); ctl.get($(`.cx-composer[data-cx-key="${CSS.escape(key)}"]`))?.draw(); }
    const drop = () => { if (!key) return; const st = state(key); st.atts = st.atts.filter(x => x !== chip); ctl.get($(`.cx-composer[data-cx-key="${CSS.escape(key)}"]`))?.draw(); };
    try {
      const res = await fetch(`/api/workspace/files?${new URLSearchParams({ name: file.name })}`, { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "scout", "Content-Type": "application/octet-stream" }, body: file });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Upload failed.");
      const f = d.files.filter(x => x.mine && x.size === file.size).sort((a, b) => b.added - a.added)[0] || d.files[0];
      files = null; drop();
      const att = { kind: "file", id: f.id, label: f.name };
      if (key) add(key, att);
      toast(`${f.name} attached (also in the Shared drive)`);
      return att;
    } catch (e) { drop(); toast(e.message); return null; }
  }

  // ---------- the picker: Drive files and Source code ----------
  let files = null, repos = null;
  const loadFiles = async () => files || (files = await api("/api/workspace/files").catch(e => ({ enabled: true, error: e.message, files: [] })));
  const loadRepos = async () => repos || (repos = await api("/api/source").catch(e => ({ configured: false, error: e.message })));
  const size = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
  /* A dialog to pick Drive files or Source code (files or folders); onPick gets [{kind, id, label}]. */
  function picker(tab = "drive", onPick, { title = "Add material", note = "" } = {}) {
    let d = $("#cx-picker");
    if (!d) { d = document.createElement("dialog"); d.id = "cx-picker"; d.className = "modal cx-picker"; document.body.appendChild(d); }
    const picked = new Map(), s = { tab, q: "", repo: null, path: "", dir: null, loading: false, error: "" };
    const key = x => `${x.kind}:${x.id}`;
    const toggle = x => { picked.has(key(x)) ? picked.delete(key(x)) : picked.set(key(x), x); draw(); };
    const list = () => {
      if (s.tab === "drive") {
        if (!files) { loadFiles().then(draw); return Loading.line("Loading files…"); }
        if (!files.enabled) return `<p class="muted">AXoR Drive isn't connected on this server.</p>`;
        if (files.error) return `<p class="muted">${esc(files.error)}</p>`;
        const q = s.q.toLowerCase(), xs = files.files.filter(f => !q || f.name.toLowerCase().includes(q) || (f.path || "").toLowerCase().includes(q)).slice(0, 80);
        return xs.length ? `<ul class="cx-pick-list">${xs.map(f => { const x = { kind: "file", id: f.id, label: f.name }, on = picked.has(key(x)); return `<li><button type="button" class="cx-pick-row ${on ? "on" : ""}" data-cx-p='${esc(JSON.stringify(x))}' aria-pressed="${on}">
            <span class="cx-pick-box">${on ? icon("check") : ""}</span>${icon("file")}<span class="cx-pick-name"><b>${esc(f.name)}</b><small class="faint">${esc(f.space === "shared" ? "Shared drive" : "My drive")}${f.path ? ` · ${esc(f.path)}` : ""} · ${size(f.size)}${f.netuid != null ? ` · SN${f.netuid}` : ""}</small></span></button></li>`; }).join("")}</ul>`
          : `<p class="muted">${q ? "No files match." : "No files yet. Upload one, or add files in the Drive tab."}</p>`;
      }
      if (s.tab === "source") {
        if (!repos) { loadRepos().then(draw); return Loading.line("Loading repositories…"); }
        if (!repos.configured) return `<p class="muted">${esc(repos.error || "GitHub isn't connected.")} ${isAdmin() ? "Connect it in the Source tab." : "An administrator can connect it in the Source tab."}</p>`;
        if (!s.repo) {
          const q = s.q.toLowerCase(), xs = (repos.repos || []).filter(r => !q || r.repo.toLowerCase().includes(q) || (r.description || "").toLowerCase().includes(q));
          return xs.length ? `<ul class="cx-pick-list">${xs.map(r => `<li><button type="button" class="cx-pick-row" data-cx-repo="${esc(r.repo)}">${icon("server")}<span class="cx-pick-name"><b>${esc(r.repo)}</b><small class="faint">${esc(r.description || r.error || "")}${r.language ? ` · ${esc(r.language)}` : ""}</small></span>${icon("right")}</button></li>`).join("")}</ul>`
            : `<p class="muted">${q ? "No repositories match." : "No repositories on the Source hub yet."}</p>`;
        }
        if (s.loading) return Loading.line("Loading…");
        if (s.error) return `<p class="muted">${esc(s.error)}</p>`;
        const crumbs = [["", s.repo], ...s.path.split("/").filter(Boolean).map((p, i, a) => [a.slice(0, i + 1).join("/"), p])];
        const here = { kind: "source", id: `${s.repo}:${s.path}`, label: s.path ? `${s.repo}/${s.path}` : s.repo }, onHere = picked.has(key(here));
        const q = s.q.toLowerCase(), es = (s.dir?.entries || []).filter(e => !q || e.name.toLowerCase().includes(q));
        return `<div class="cx-crumbs"><button type="button" class="linkbtn" data-cx-repos>${icon("left")}Repositories</button>${crumbs.map(([p, l]) => `<span>/</span><button type="button" class="linkbtn" data-cx-path="${esc(p)}">${esc(l)}</button>`).join("")}
            <span class="ac-spacer"></span><button type="button" class="btn sm ${onHere ? "primary" : ""}" data-cx-p='${esc(JSON.stringify(here))}' aria-pressed="${onHere}" title="The folder's file list and README">${onHere ? icon("check") : icon("folder")}${onHere ? "Folder added" : "Add this folder"}</button></div>
          <ul class="cx-pick-list">${es.map(e => {
            if (e.type === "dir") return `<li><button type="button" class="cx-pick-row" data-cx-path="${esc(e.path)}">${icon("folder")}<span class="cx-pick-name"><b>${esc(e.name)}</b></span>${icon("right")}</button></li>`;
            const x = { kind: "source", id: `${s.repo}:${e.path}`, label: `${s.repo}/${e.path}` }, on = picked.has(key(x));
            return `<li><button type="button" class="cx-pick-row ${on ? "on" : ""}" ${e.secret ? `disabled title="Looks like a secret: not shown to agents"` : `data-cx-p='${esc(JSON.stringify(x))}'`} aria-pressed="${on}">
              <span class="cx-pick-box">${on ? icon("check") : ""}</span>${icon(e.secret ? "lock" : "file")}<span class="cx-pick-name"><b>${esc(e.name)}</b><small class="faint">${e.secret ? "secret, skipped" : size(e.size)}</small></span></button></li>`;
          }).join("") || `<li class="muted">${q ? "Nothing matches." : "Empty folder."}</li>`}</ul>`;
      }
      return `<label class="cx-drop" data-cx-drop><input type="file" class="sr" data-cx-upfile multiple>${icon("upload")}<b>Drop files here or choose them</b>
        <small class="faint">They're saved to the Shared drive (Workspace folder), so tutors and agents can read them. Text, code, Markdown and PDFs work best.</small></label>`;
    };
    const draw = () => {
      const focusQ = document.activeElement?.matches?.("#cx-pick-q");
      d.innerHTML = `<form method="dialog" class="cx-pick-form">
        <div class="cx-pick-head"><h3>${icon("plus")}${esc(title)}</h3><button type="button" class="iconbtn sm" data-cx-close aria-label="Close">${icon("close")}</button></div>
        ${note ? `<p class="muted small">${esc(note)}</p>` : ""}
        <div class="seg cx-pick-tabs" role="tablist">${[["drive", "folder", "AXoR Drive"], ["source", "code", "Source code"], ["upload", "upload", "Upload"]].map(([k, ic, l]) => `<button type="button" role="tab" data-cx-tab="${k}" aria-selected="${s.tab === k}" aria-pressed="${s.tab === k}">${icon(ic)}${l}</button>`).join("")}</div>
        ${s.tab !== "upload" ? `<input type="search" id="cx-pick-q" class="cx-pick-q" placeholder="${s.tab === "drive" ? "Search files…" : s.repo ? "Filter this folder…" : "Search repositories…"}" value="${esc(s.q)}">` : ""}
        <div class="cx-pick-body">${list()}</div>
        <div class="cx-pick-foot"><span class="faint small">${picked.size ? `${picked.size} selected: ${esc([...picked.values()].map(x => x.label.split("/").pop()).join(", "))}` : "Pick one or more"}</span>
          <span class="ac-spacer"></span><button type="button" class="btn" data-cx-close>Cancel</button><button type="button" class="btn primary" data-cx-done ${picked.size ? "" : "disabled"}>${icon("check")}Add ${picked.size || ""}</button></div></form>`;
      const q = d.querySelector("#cx-pick-q");
      if (q) { q.oninput = () => { s.q = q.value; const pos = q.selectionStart; draw(); const q2 = d.querySelector("#cx-pick-q"); q2.focus(); q2.setSelectionRange(pos, pos); }; if (focusQ) q.focus(); }
      const up = d.querySelector("[data-cx-upfile]");
      if (up) up.onchange = () => uploadMany([...up.files]);
    };
    const uploadMany = async fs => {
      d.querySelector(".cx-pick-body").innerHTML = Loading.line(`Uploading ${fs.length} file${fs.length === 1 ? "" : "s"}…`);
      for (const f of fs.slice(0, 6)) { const x = await upload(f, null); if (x) picked.set(key(x), x); }
      s.tab = "drive"; draw();
    };
    const browse = async path => {
      s.path = path; s.q = ""; s.loading = true; s.error = ""; draw();
      const [o, n] = s.repo.split("/");
      try { s.dir = await api(`/api/source/repos/${encodeURIComponent(o)}/${encodeURIComponent(n)}/contents?${new URLSearchParams({ path })}`); }
      catch (e) { s.error = e.message; }
      s.loading = false;
      if (s.dir?.type !== "dir" && !s.error) s.error = "That's a file: pick it from its folder.";
      draw();
    };
    d.onclick = e => {
      const t = e.target;
      if (t.closest("[data-cx-close]")) return d.close();
      if (t.closest("[data-cx-done]")) { d.close(); return onPick([...picked.values()]); }
      const tb = t.closest("[data-cx-tab]"); if (tb) { s.tab = tb.dataset.cxTab; s.q = ""; return draw(); }
      const p = t.closest("[data-cx-p]"); if (p) return toggle(JSON.parse(p.dataset.cxP));
      const r = t.closest("[data-cx-repo]"); if (r) { s.repo = r.dataset.cxRepo; return browse(""); }
      if (t.closest("[data-cx-repos]")) { s.repo = null; s.dir = null; s.q = ""; return draw(); }
      const pa = t.closest("[data-cx-path]"); if (pa) return browse(pa.dataset.cxPath);
    };
    d.ondragover = e => { if (s.tab === "upload") { e.preventDefault(); d.querySelector("[data-cx-drop]")?.classList.add("over"); } };
    d.ondragleave = () => d.querySelector("[data-cx-drop]")?.classList.remove("over");
    d.ondrop = e => { if (s.tab !== "upload") return; e.preventDefault(); uploadMany([...e.dataTransfer.files]); };
    draw(); d.showModal();
  }

  // ---------- @ mentions and / commands ----------
  function typed(c) {
    const ta = c.ta, before = ta.value.slice(0, ta.selectionStart);
    const at = before.match(/(^|\s)@([\w.-]*)$/), sl = before.match(/^\/(\w*)$/);
    if (at && c.o.mention) return mention(c, at[2], at[2].length + 1);
    if (sl && c.o.slash?.length) return slash(c, sl[1]);
    const pop = document.querySelector(".ac-pop"); if (pop?.dataset.for === c.o.key) pop.remove();
  }
  async function mention(c, q = "", strip = 0, tab = "all") {
    const groups = await c.o.mention(q, tab);
    const tabs = c.o.mentionTabs || [];
    const html = (tabs.length > 1 ? `<div class="ac-tabs">${[["all", "All"], ...tabs].map(([k, l]) => `<button type="button" data-tab2="${k}" aria-pressed="${tab === k}">${l}</button>`).join("")}</div>` : "")
      + groups.map(g => `<div class="ac-pop-group">${esc(g.title)}</div>${g.items.map(x => `<button type="button" class="ac-opt" data-opt='${esc(JSON.stringify({ kind: x.kind, id: x.id, label: x.label }))}'>${icon(x.ic || ATT_ICON[x.kind] || "file")}<span>${esc(x.label)}</span>${x.note ? `<small class="faint">${esc(x.note)}</small>` : ""}</button>`).join("") || `<p class="faint small ac-none">Nothing matches.</p>`}`).join("");
    popup(c, html, el => el.querySelectorAll("[data-tab2]").forEach(b => b.onclick = e => { e.stopPropagation(); mention(c, q, strip, b.dataset.tab2); }), opt => {
      if (strip) { const p = c.ta.selectionStart; c.ta.setRangeText("", p - strip, p, "end"); state(c.o.key).text = c.ta.value; }
      add(c.o.key, JSON.parse(opt)); c.ta.focus();
    });
  }
  function slash(c, q = "") {
    const list = c.o.slash.filter(([k]) => k.startsWith(q.toLowerCase()));
    if (!list.length) { const pop = document.querySelector(".ac-pop"); if (pop?.dataset.for === c.o.key) pop.remove(); return; }
    popup(c, `<div class="ac-pop-group">Commands</div>` + list.map(([k, d]) => `<button type="button" class="ac-opt" data-opt="${k}"><b>/${k}</b><small class="faint">${esc(d)}</small></button>`).join(""), null, k => {
      const arg = c.o.slash.find(([x]) => x === k)?.[2];
      c.ta.value = "/" + k + (arg ? " " : ""); state(c.o.key).text = c.ta.value; c.ta.focus();
      if (!arg) c.form.requestSubmit();
    });
  }
  function popup(c, html, setup, onPick) {
    document.querySelector(".ac-pop")?.remove();
    const pop = document.createElement("div"); pop.className = "popover ac-pop"; pop.setAttribute("role", "listbox"); pop.dataset.for = c.o.key;
    pop.innerHTML = html;
    c.form.appendChild(pop);
    pop.querySelector(".ac-opt")?.classList.add("active");
    setup?.(pop);
    pop.addEventListener("mousedown", e => e.preventDefault());  // keep the textarea focused
    pop.addEventListener("click", e => { const o = e.target.closest("[data-opt]"); if (o) { pop.remove(); onPick(o.dataset.opt); } });
    closeOn(pop, "[data-cx-slash], [data-cx-plus]");
  }
  function popKey(e, pop) {
    const opts = [...pop.querySelectorAll("[data-opt]")], i = opts.findIndex(o => o.classList.contains("active"));
    if (e.key === "Escape") { e.preventDefault(); return pop.remove(); }
    if (!opts.length) return;
    e.preventDefault();
    if (e.key === "Enter" || e.key === "Tab") return opts[Math.max(0, i)].click();
    const j = (i + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
    opts.forEach(o => o.classList.remove("active")); opts[j].classList.add("active"); opts[j].scrollIntoView({ block: "nearest" });
  }
  // the default @ list: Drive files and Source repositories
  async function defaultMention(q) {
    const f = await loadFiles(), ql = q.toLowerCase();
    return [{ title: "Drive files", items: (f.files || []).filter(x => !ql || x.name.toLowerCase().includes(ql)).slice(0, 8).map(x => ({ kind: "file", id: x.id, label: x.name, note: x.netuid != null ? `SN${x.netuid}` : "" })) }];
  }

  // ---------- voice input ----------
  let rec = null;
  function mic(c, btn) {
    if (rec) { rec.stop(); return; }
    if (!SR) return;
    const ta = c.ta, start = ta.value ? ta.value.replace(/\s*$/, " ") : "";
    rec = new SR(); rec.interimResults = true; rec.continuous = true; rec.lang = typeof c.o.mic === "string" ? c.o.mic : navigator.language || "en-US";
    rec.onresult = e => { ta.value = start + [...e.results].map(r => r[0].transcript).join(""); ta.dispatchEvent(new Event("input")); };
    rec.onerror = e => { if (e.error !== "aborted") toast(e.error === "not-allowed" ? "Microphone access was blocked" : "Voice input stopped"); };
    rec.onend = () => { rec = null; $$("[data-cx-mic]").forEach(b => { b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); }); };
    rec.start(); btn.classList.add("on"); btn.setAttribute("aria-pressed", "true");
  }
  const stopMic = () => rec?.stop();

  // ---------- a resizable side panel (Study and Workspace chats) ----------
  function resizer(host, varName, prefKey, min = 300, max = 760) {
    const w = cp(prefKey); if (w) host.style.setProperty(varName, w + "px");
    if (host.dataset.cxResize) return;
    host.dataset.cxResize = "1";
    host.addEventListener("pointerdown", e => {
      const h = e.target.closest("[data-cx-grip]"); if (!h) return;
      e.preventDefault(); h.setPointerCapture(e.pointerId);
      const panel = h.closest("[data-cx-panel]"), right = panel.getBoundingClientRect().right;
      document.body.classList.add("cx-resizing");
      const move = ev => { const v = Math.round(Math.max(min, Math.min(max, right - ev.clientX))); host.style.setProperty(varName, v + "px"); cp(prefKey, v); };
      const up = () => { h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up); h.removeEventListener("pointercancel", up); document.body.classList.remove("cx-resizing"); };
      h.addEventListener("pointermove", move); h.addEventListener("pointerup", up); h.addEventListener("pointercancel", up);
    });
    host.addEventListener("dblclick", e => { if (e.target.closest("[data-cx-grip]")) { host.style.removeProperty(varName); cp(prefKey, null); } });
    host.addEventListener("keydown", e => {
      const h = e.target.closest("[data-cx-grip]"); if (!h || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      e.preventDefault();
      const cur = h.closest("[data-cx-panel]").getBoundingClientRect().width, v = Math.round(Math.max(min, Math.min(max, cur + (e.key === "ArrowLeft" ? 24 : -24))));
      host.style.setProperty(varName, v + "px"); cp(prefKey, v);
    });
  }
  const grip = () => `<div class="cx-grip" data-cx-grip role="separator" aria-orientation="vertical" aria-label="Resize the chat (arrow keys; double-click to reset)" tabindex="0" title="Drag to resize · double-click to reset"></div>`;

  return { log, enhance, bind, composer, mount, add, setDraft, focus, upload, picker, defaultMention, stopMic, quiet,
           choice, chosen, modelButton, modelMenu, loadModels, ensureModels, models: () => models, modelLabel, modelGroups, providerIcon, syncModel,
           displayButton, displayMenu, usageButton, usageMenu, tokensOf, fmtTokens, resizer, grip, state, ATT_ICON };
})();
