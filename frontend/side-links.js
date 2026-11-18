/* Sidebar links that open a part of a page rather than a page (the 11-07 evaluation: one canonical home per capability):
   - Workspace → Connected tools → Discord & Telegram: My Knowledge → Settings & connectors, where the bots are connected
     (knowledge.js). It shows while My Knowledge may be opened. Loaded after app.js. */
(() => {
  const link = document.getElementById("nav-conn"), mk = document.getElementById("nav-myknowledge");
  if (!link || !mk) return;
  const sync = () => { if (link.hidden !== mk.hidden) link.hidden = mk.hidden; };
  new MutationObserver(sync).observe(mk, { attributes: true, attributeFilter: ["hidden"] });
  sync();
  link.addEventListener("click", () => {
    if (innerWidth <= 900) sideOpen(false);
    if (typeof Knowledge !== "undefined" && Knowledge.show) Knowledge.show("settings"); else setView("myknowledge");
  });
})();
