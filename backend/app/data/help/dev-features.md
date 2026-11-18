---
title: Build a feature
section: dev
order: 3
icon: wrench
summary: Adding a page end to end, from the API module to the sidebar, with Tech Daily as the worked example.
---
A page in AXoR is a backend module that builds an API router and a front-end module that renders it. Tech Daily (`backend/app/techboard.py`, `frontend/tech.js`, `frontend/tech.css`) is a compact example to follow.

## 1. The API module

Create `backend/app/<name>.py` with the logic in a class and a `build()` that returns a router:

```python
from fastapi import APIRouter, HTTPException, Request

class Things:
    def __init__(self, db):
        self.db = db
        db.q("CREATE TABLE IF NOT EXISTS things (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, ts REAL)")

def build(db, require, admin, ip):
    r = APIRouter(prefix="/api/things")
    things = Things(db)
    r.state = {"things": things}     # what other modules or start-up need

    @r.get("")
    def mine(req: Request):
        """Your things, newest first."""         # the first line shows in the API reference
        me = require(req)
        return db.q("SELECT * FROM things WHERE user_id=? ORDER BY ts DESC", (me["id"],))

    @r.post("/reset")
    def reset(req: Request):
        """Empty the table (admins)."""
        me = admin(req)
        db.q("DELETE FROM things")
        db.log("things.reset", me["username"], "", ip(req))
        return {"ok": True}

    return r
```

- **Check access in every handler:** `require(req)` for anyone signed in, `admin(req)` for administrators, `sudo(req)` for changes that should need a fresh confirmation. The API reference reads these calls to label each endpoint.
- **Audit** changes others should be able to trace with `db.log(action, actor, target, ip, detail)`.
- **Errors** are `HTTPException(status, "A sentence a person can act on.")`: the front end shows the message as it is.
- **Secrets** go in `secretbox.SecretBox`, never in plain tables or responses.
- **Outside calls:** set timeouts and read limits, and refuse private addresses for URLs that come from data (Tech Daily's `fetch()` checks every redirect too).

## 2. Wire it into the app

In `backend/app/main.py`, import the module, include its router, and start background work, if any, in `_start()`:

```python
from . import things
app.include_router(things.build(auth_db, require_user, admin_router.state["admin"], auth_router.state["ip"]))
```

Admin helpers come from `admin_router.state` (`"admin"`, `"sudo"`), the client's IP from `auth_router.state["ip"]`.

## 3. The front-end module

Create `frontend/<name>.js`:

```js
/* Things: what the page shows and how it behaves, in a sentence or two. */
const Things = (() => {
  let data = null, wired = false;
  async function open() {
    wire();
    $("#things").innerHTML = Loading.line("Loading…");
    try { data = await api("/api/things"); } catch (e) { $("#things").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    $("#things").innerHTML = data.map(t => `<button type="button" class="chip" data-thing="${t.id}">${esc(t.name)}</button>`).join("")
      || `<div class="empty">Nothing yet.</div>`;
  }
  function wire() {
    if (wired) return; wired = true;
    $("#things").addEventListener("click", e => { const b = e.target.closest("[data-thing]"); if (b) UI.toast(`Thing ${b.dataset.thing}`); });
  }
  return { open };
})();
```

- **Escape everything** that came from a person or another site with `esc()`. Build HTML as strings; never insert unescaped text.
- **No inline handlers** (`onclick="…"`) and no `eval`: the Content-Security-Policy blocks them. Wire events by delegation on the page's root, once.
- **Use `api()`** for every call: it adds the CSRF header, shows progress and turns errors into messages.
- **Confirm** destructive actions with `UI.confirm({title, body, ok, run})`.

## 4. Put it on the page

- `frontend/index.html`: a sidebar button (`<button data-view="things" title="Things"><span data-icon="…"></span><span class="lbl">Things</span></button>`), a section (`<section class="view" id="view-things" hidden><div id="things"></div></section>`) and the script tag before `app.js`. Add a stylesheet link if you have one.
- `frontend/app.js`: `if (v === "things") Things.open();` in `setView`, and the view's name in `init()`'s list of linkable views.
- `frontend/icons.js`: add an icon if none fits (24×24, 2px stroke).
- `backend/app/pages.py`: describe the page so Assist knows it.
- Writing help (`writer.js`) works in any `<textarea>` or text `<input>` inside `main`, an open dialog or the Assist panel. Give a field (or a container) `data-writer="off"` when it holds identifiers, code or anything private that its id, label or placeholder doesn't already make obvious (fields named like password, key, token, seed, address, search, code, url…, fields with `spellcheck="false"` and text that looks like code are skipped on their own).
- `frontend/guide-pages.js`: the page's tour (an intro, tips, its help doc, what its tabs and main buttons do, and steps on elements it always has) and any value suggestions for its fields (`GuideFields`). A page without an entry still gets a tour from the Guide button, built from its tabs, buttons and search, but no first-visit offer.

## 5. Style it

Use the tokens from `styles.css` (`--bg`, `--surface`, `--surface-2`, `--line`, `--text`, `--text-2`, `--text-3`, `--accent`, `--good`, `--warn`, `--crit`), so the page works in light and dark themes and with any accent color. Your own colors need a dark-theme value in both places `styles.css` defines them: `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`. Respect `prefers-reduced-motion`, and check the page at phone width (below 900px the sidebar becomes a slide-out menu).

## 6. Using a model

```python
self.hub.gate(me)                        # the agents access setting and the user's limits
used = [0]
out = self.hub.llm.structured(model, SYSTEM, prompt, SCHEMA, "things",
                              on_usage=lambda n: used.__setitem__(0, used[0] + n))
self.hub.log_usage(me, "things", used[0], None, self.hub.model_of(model))
```

`structured()` returns JSON matching your schema on every provider. Keep schemas strict-mode friendly: `"additionalProperties": false` and every property listed in `required`. Then add a branch to `tests/fake_claude.py` for your system prompt.

## 7. Document it

- Add or update a Markdown file in `backend/app/data/help/` with its front matter (`title`, `section`, `order`, `audience`, `icon`, `summary`). Help re-reads changed files without a restart.
- New routes appear in the [API reference](#help/api-reference) by themselves; a docstring on each handler gives them a summary.
- Update `README.md`'s features, configuration and API tables.

## Checklist

- [ ] Every handler checks access; changes that matter are audited.
- [ ] Every value in HTML goes through `esc()`; no inline handlers.
- [ ] Outside requests have timeouts and size limits, and data-supplied URLs can't reach private addresses.
- [ ] The page works signed in and out (if it's public), in both themes, and at phone width.
- [ ] Background threads catch their own errors and log them.
