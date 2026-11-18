/* Subnet Explorer, table views (the 11-07 evaluation: "too much information at once; offer presets"): a View menu beside
   Columns that shows the columns for one question at a time. A view only sets which columns show (the same hidden-column
   set the Columns popover edits, so the choice is remembered the same way); every column stays one click away under
   Columns; "Standard columns" is the table as it always opened, "All columns" shows every one. Loaded after app.js (COLS, S, renderTable, store). */
(() => {
  const VIEWS = [
    ["opportunity", "Opportunity", "Emission, earning miners, open UIDs", ["emission_day", "earning_miners", "num_uids", "uid_available", "top_miner", "reg_cost", "risk"]],
    ["profit", "Profitability", "Gross earnings against what it costs to mine", ["top_miner", "second_miner", "top_epoch", "payout_epoch", "reg_cost", "rent", "need"]],
    ["tech", "Technical", "Task, hardware and requirements", ["task", "miner_role", "need", "conditions", "rent", "links", "field"]],
    ["risk", "Risk", "Risk flags, price movement, activity", ["risk", "trend", "volume", "validators", "created_date", "description"]],
    ["competition", "Competition", "How hard it is to earn", ["num_uids", "earning_miners", "top_miner", "second_miner", "top_epoch", "uid_available"]],
  ];
  if (typeof COLS === "undefined" || typeof S === "undefined" || !document.getElementById("cols-btn")) return;
  const free = COLS.filter(c => !c.lock).map(c => c.key);
  const same = keys => free.every(k => S.hidden.has(k) === !keys.includes(k));
  const STD = ["description", "validators", "volume", "top_epoch"];  // app.js's default hidden columns
  const sameHidden = h => free.every(k => S.hidden.has(k) === h.includes(k));
  const current = () => same(free) ? "all" : sameHidden(STD) ? "standard" : (VIEWS.find(v => same(v[3]))?.[0] || "custom");

  const sel = document.createElement("select");
  sel.id = "f-view"; sel.setAttribute("aria-label", "Table view");
  sel.title = "Show the columns for one question at a time; Columns still adds or removes any column";
  const paint = () => {
    const cur = current();
    sel.innerHTML = `<option value="standard">Standard columns</option><option value="all">All columns</option>${VIEWS.map(([k, l, about]) => `<option value="${k}" title="${about}">View: ${l}</option>`).join("")}${cur === "custom" ? `<option value="custom">Custom columns</option>` : ""}`;
    sel.value = cur;
  };
  sel.onchange = () => {
    const v = VIEWS.find(x => x[0] === sel.value);
    if (!["all", "standard"].includes(sel.value) && !v) return;
    S.hidden = new Set(v ? free.filter(k => !v[3].includes(k)) : sel.value === "standard" ? STD : []);
    store.set("hiddenCols", [...S.hidden]);
    renderTable(); paint();
  };
  document.getElementById("cols-btn").before(sel);
  paint();
  // the Columns popover changes the set by hand: show "Custom columns" (or the view it now matches)
  document.addEventListener("change", e => { if (e.target.closest?.("#colpop")) paint(); });
})();
