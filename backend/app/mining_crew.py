"""Competition teams, the crew's side (mining_work.py runs the work): what each agent remembers, the roadmap, the team's links to the
rest of AXoR, the diagram's layout and every agent's engineer level.

- Prompt histories (mw_prompts): every run an agent makes (a task, a review, a plan) is kept as one entry: the system prompt, the
  prompt and the reply. The user reads, edits and deletes them (one, several or all, for one agent or the whole team) and writes
  new ones: a message for the agent's next run, or a task it starts now. What an agent remembers is its history: before it works it
  reads the user's messages it hasn't seen, the entries the user kept ("remember this") and its own latest replies, so editing or
  deleting an entry changes what it knows.
- The roadmap (mw_milestones): the competition from its start to its end, as milestones with dates and a status. A default one
  comes from the competition's dates (or the next two weeks); agents read the current phase and the next milestone.
- Links (mw_links): the Source repository, Drive folder, DevOps pipeline, cluster deployment, app and functions the team works
  with. The page shows each one's live state from its own hub (which keeps its own permissions); agents read the list.
- The diagram's layout (mw_layout): where the user dragged each agent on the team diagram.
- Levels: experience points from the work itself (tasks done, findings approved, reviews and plans, first-time approvals, failures),
  an engineer level from them (Intern to Distinguished) and the agent's record.
"""
import json, re, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import mining_packs
from .mining import _clip

MAX_PROMPTS = 3000      # entries kept per workspace; the oldest unkept ones go first
TEXT = 60_000           # characters kept of a system prompt, a prompt or a reply
RECALL_RECENT = 3       # an agent's own latest replies it re-reads
RECALL_KEPT = 8         # entries the user kept that it re-reads
MAX_MILESTONES = 40
LINK_KINDS = {"source": "Source repository", "drive": "Drive folder", "devops": "DevOps pipeline", "cluster": "Cluster deployment",
              "app": "App", "function": "Function"}
MAX_LINKS = 30
LEVELS = [(0, "Intern"), (100, "Junior engineer"), (300, "Engineer"), (700, "Senior engineer"), (1500, "Staff engineer"),
          (3000, "Principal engineer"), (6000, "Distinguished engineer")]
XP = {"done": 40, "note": 60, "first_time": 20, "review": 15, "plan": 25, "run": 5, "failed": -10}
RIDGES_ROADMAP = [("Read the rules and the scoring", "What Ridges scores, the agent contract, the deadlines; a summary in the notebook."),
                  ("A baseline agent", "agent.py that solves a first practice task end to end in the sandbox."),
                  ("Practice tasks and a local score", "A practice set like the competition's, and a script that scores the agent on it."),
                  ("Improve the agent", "Rounds of changes, each measured on the practice set; keep what raises the score."),
                  ("Submit and watch the leaderboard", "The user uploads the best agent; the team follows the score and plans the next round.")]
GENERAL_ROADMAP = [("Understand the competition", "Rules, scoring, the leaders and what they do."),
                   ("A first working miner", "The simplest thing that earns, tested."),
                   ("Measure", "A way to score changes before they go live."),
                   ("Improve", "Rounds of measured changes."),
                   ("Ship and watch", "The user deploys; the team follows the results.")]


class WriteIn(BaseModel):
    agents: list[int] = Field(default_factory=list, max_length=60)  # empty: every agent on the team
    text: str = Field(min_length=1, max_length=8000)
    mode: str = Field("note", pattern="^(note|task)$")  # a message for the next run, or a task it starts now
    title: str = Field("", max_length=160)
    priority: str = Field("medium", pattern="^(high|medium|low)$")
    keep: bool = False

class PromptPatch(BaseModel):
    system: str | None = Field(None, max_length=TEXT)
    prompt: str | None = Field(None, max_length=TEXT)
    reply: str | None = Field(None, max_length=TEXT)
    keep: bool | None = None

class BulkIn(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=MAX_PROMPTS)
    agents: list[int] = Field(default_factory=list, max_length=60)  # with no ids: every entry of these agents (or of everyone, with all)
    all: bool = False
    action: str = Field(pattern="^(delete|keep|forget|export)$")

class MilestoneIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    detail: str = Field("", max_length=2000)
    starts: str = Field("", max_length=10)
    due: str = Field("", max_length=10)
    status: str = Field("todo", pattern="^(todo|doing|done)$")
    agent: int | None = None

class MilestonePatch(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    detail: str | None = Field(None, max_length=2000)
    starts: str | None = Field(None, max_length=10)
    due: str | None = Field(None, max_length=10)
    status: str | None = Field(None, pattern="^(todo|doing|done)$")
    agent: int | None = None
    unassign: bool = False

class LinkIn(BaseModel):
    kind: str = Field(pattern="^(source|drive|devops|cluster|app|function)$")
    ref: str = Field(min_length=1, max_length=200)
    label: str = Field("", max_length=160)
    url: str = Field("", max_length=500)

class LayoutIn(BaseModel):
    pos: dict[str, list[float]] = Field(default_factory=dict, max_length=60)  # agent id → [x, y]; empty: back to the automatic layout


def _date(s):
    s = (s or "").strip()
    if s and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s): raise HTTPException(422, "Dates are YYYY-MM-DD.")
    return s

def _day(ts): return time.strftime("%Y-%m-%d", time.localtime(ts))

def _ts(s): return time.mktime(time.strptime(s, "%Y-%m-%d"))

def level(xp):
    i = max(i for i, (lo, _) in enumerate(LEVELS) if xp >= lo)
    lo, name = LEVELS[i]
    hi = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
    return {"n": i + 1, "name": name, "xp": xp, "floor": lo, "next": hi, "progress": 1.0 if hi is None else round((xp - lo) / (hi - lo), 3)}


class Crew:
    def __init__(self, work):
        self.w, self.db = work, work.db
        q = self.db.q
        q("""CREATE TABLE IF NOT EXISTS mw_prompts (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, agent_id INTEGER, run_id INTEGER,
             task_id INTEGER, kind TEXT, title TEXT, system TEXT, prompt TEXT, reply TEXT, tokens INTEGER DEFAULT 0, status TEXT, ts REAL,
             by_user TEXT, keep INTEGER DEFAULT 0, seen REAL, edited REAL)""")
        q("CREATE INDEX IF NOT EXISTS mw_prompts_a ON mw_prompts (comp_id, agent_id, id)")
        q("""CREATE TABLE IF NOT EXISTS mw_milestones (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT,
             starts TEXT, due TEXT, status TEXT DEFAULT 'todo', agent_id INTEGER, created REAL, updated REAL)""")
        q("""CREATE TABLE IF NOT EXISTS mw_links (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, kind TEXT, ref TEXT, label TEXT,
             url TEXT, created REAL, UNIQUE (comp_id, kind, ref))""")
        q("CREATE TABLE IF NOT EXISTS mw_layout (comp_id INTEGER PRIMARY KEY, pos TEXT, updated REAL)")
        work.crew = self

    def drop(self, wid):
        for t in ("mw_prompts", "mw_milestones", "mw_links", "mw_layout"): self.db.q(f"DELETE FROM {t} WHERE comp_id=?", (wid,))

    # ---------- what runs leave behind, and what agents read before they work ----------
    def said(self, w, a, rid, tid, kind, title, system, prompt, reply, tokens=0, status="done"):
        """Keeps one run's prompts; the user's messages the agent read in it are marked seen."""
        if not a or not a.get("id"): return
        now = time.time()
        run = self.db.q("SELECT started FROM mw_runs WHERE id=?", (rid,), one=True) if rid else None
        self.db.q("""INSERT INTO mw_prompts (comp_id, agent_id, run_id, task_id, kind, title, system, prompt, reply, tokens, status, ts)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (w["id"], a["id"], rid, tid, kind, _clip(title, 200), _clip(system, TEXT), _clip(prompt, TEXT),
                                                          _clip(reply, TEXT), tokens or 0, status, now))
        self.db.q("UPDATE mw_prompts SET seen=? WHERE comp_id=? AND agent_id=? AND kind='user' AND seen IS NULL AND ts<=?",
                  (now, w["id"], a["id"], run["started"] if run else now))
        n = self.db.q("SELECT COUNT(*) n FROM mw_prompts WHERE comp_id=?", (w["id"],), one=True)["n"]
        if n > MAX_PROMPTS:
            self.db.q("""DELETE FROM mw_prompts WHERE id IN (SELECT id FROM mw_prompts WHERE comp_id=? AND keep=0 AND kind!='user'
                         ORDER BY id LIMIT ?)""", (w["id"], n - MAX_PROMPTS))

    def recall(self, w, a):
        """The part of an agent's prompt that comes from its history, the roadmap and the team's links."""
        if not a or not a.get("id"): return ""
        q, out = self.db.q, []
        mine = q("""SELECT id, ts, prompt, keep FROM mw_prompts WHERE comp_id=? AND agent_id=? AND kind='user' AND (seen IS NULL OR keep=1)
                    ORDER BY id DESC LIMIT 12""", (w["id"], a["id"]))
        if mine:
            out.append("Messages from the user to you (newest last; follow them unless they'd break the ground rules):\n" +
                       "\n".join(f"- ({_day(m['ts'])}) {_clip(m['prompt'], 1500)}" for m in reversed(mine)))
        kept = q("""SELECT id, ts, kind, title, reply FROM mw_prompts WHERE comp_id=? AND agent_id=? AND keep=1 AND kind!='user'
                    ORDER BY id DESC LIMIT ?""", (w["id"], a["id"], RECALL_KEPT))
        recent = q("""SELECT id, ts, kind, title, reply FROM mw_prompts WHERE comp_id=? AND agent_id=? AND keep=0 AND kind!='user' AND status='done'
                      ORDER BY id DESC LIMIT ?""", (w["id"], a["id"], RECALL_RECENT))
        past = sorted(kept + recent, key=lambda p: p["id"])
        if past:
            out.append("What you remember from your earlier runs (your prompt history, as the user keeps it):\n" +
                       "\n".join(f"- ({_day(p['ts'])}, {p['kind']}) {p['title'] or ''}: {_clip(p['reply'], 700 if p in kept else 400)}" for p in past))
        road = self.roadmap(w["id"])
        if road:
            today = _day(time.time())
            now_on = next((m for m in road if m["status"] == "doing"), None) or next((m for m in road if m["status"] != "done"), None)
            nxt = next((m for m in road if m["status"] != "done" and m is not now_on), None)
            done = sum(m["status"] == "done" for m in road)
            line = f"The team's roadmap ({done} of {len(road)} milestones done, today is {today})"
            if now_on: line += f": now on “{now_on['title']}”" + (f" (due {now_on['due']})" if now_on["due"] else "") + (f": {_clip(now_on['detail'], 300)}" if now_on["detail"] else "")
            if nxt: line += f"; next “{nxt['title']}”" + (f" (due {nxt['due']})" if nxt["due"] else "")
            out.append(line + ". Work toward the current milestone first.")
        links = self.links(w["id"])
        if links:
            out.append("What the user linked to this team elsewhere in AXoR (for reference: you can't open them, ask the user if you need something from one):\n" +
                       "\n".join(f"- {LINK_KINDS[x['kind']]}: {x['label'] or x['ref']}" for x in links))
        return ("\n\n".join(out) + "\n") if out else ""

    # ---------- prompt histories ----------
    def _entry(self, me, pid):
        p = self.db.q("SELECT * FROM mw_prompts WHERE id=?", (pid,), one=True)
        if not p: raise HTTPException(404, "There's no such history entry.")
        self.w._own(me, p["comp_id"])
        return p

    def _shape(self, p, cut=1200):
        return {"id": p["id"], "agent": p["agent_id"], "run": p["run_id"], "task": p["task_id"], "kind": p["kind"], "title": p["title"] or "",
                "ts": p["ts"], "tokens": p["tokens"], "status": p["status"], "by_user": p["by_user"], "keep": bool(p["keep"]), "seen": p["seen"],
                "edited": p["edited"], **{k: (p[k] or "")[:cut] for k in ("system", "prompt", "reply")},
                "cut": any(len(p[k] or "") > cut for k in ("system", "prompt", "reply"))}

    def history(self, me, wid, agents="", kind="", query="", before=0, limit=60):
        self.w._own(me, wid)
        sql, args = "SELECT * FROM mw_prompts WHERE comp_id=?", [wid]
        ids = [int(x) for x in agents.split(",") if x.strip().isdigit()]
        if ids: sql += f" AND agent_id IN ({','.join('?' * len(ids))})"; args += ids
        if kind in ("task", "review", "plan", "user", "kept"):
            if kind == "kept": sql += " AND keep=1"
            else: sql += " AND kind=?"; args.append(kind)
        if query.strip():
            like = f"%{query.strip()[:100]}%"
            sql += " AND (title LIKE ? OR prompt LIKE ? OR reply LIKE ?)"; args += [like] * 3
        total = self.db.q(sql.replace("SELECT *", "SELECT COUNT(*) n", 1), tuple(args), one=True)["n"]
        if before: sql += " AND id<?"; args.append(before)
        rows = self.db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(200, limit))))
        return {"entries": [self._shape(p) for p in rows], "total": total, "more": len(rows) == limit}

    def entry(self, me, pid):
        return {"entry": self._shape(self._entry(me, pid), TEXT)}

    def write(self, me, wid, b: WriteIn):
        w, _ = self.w._own(me, wid)
        team = {a["id"]: a for a in self.w._agents(wid)}
        picked = [team[i] for i in dict.fromkeys(b.agents) if i in team] if b.agents else [a for a in team.values() if a["active"]]
        if not picked: raise HTTPException(422, "Pick at least one agent on this team.")
        text, now, made = b.text.strip(), time.time(), 0
        if b.mode == "task":
            off = [a["name"] for a in picked if not a["active"]]
            if off: raise HTTPException(409, f"{', '.join(off)} {'is' if len(off) == 1 else 'are'} switched off: switch them on first, or send a message instead.")
            title = (b.title.strip() or text.splitlines()[0])[:160]
            if len(title) < 2: raise HTTPException(422, "Give the task a title.")
        for a in picked:  # into the histories first: a quick agent may file its task before this returns
            self.db.q("""INSERT INTO mw_prompts (comp_id, agent_id, kind, title, prompt, reply, status, ts, by_user, keep, seen)
                         VALUES (?,?,'user',?,?,'',?,?,?,?,?)""", (wid, a["id"], "A task from you" if b.mode == "task" else "A message from you", text,
                                                                   "task" if b.mode == "task" else "waiting", now, me["username"], int(b.keep),
                                                                   now if b.mode == "task" else None))  # a task carries the text itself
        if b.mode == "task":
            from .mining_work import TaskIn
            for a in picked:
                self.w.add_task(me, wid, TaskIn(title=title, detail=text, priority=b.priority, agent=a["id"], start=w["status"] != "closed"))
                made += 1
        names =", ".join(a["name"] for a in picked[:6]) + (f" and {len(picked) - 6} more" if len(picked) > 6 else "")
        self.w._event(wid, "task" if b.mode == "task" else "team", f"{me['username']} {'gave a task to' if b.mode == 'task' else 'wrote to'} {names}: {_clip(text, 160)}")
        return {"written": len(picked), "tasks": made}

    def patch(self, me, pid, b: PromptPatch):
        p = self._entry(me, pid)
        sets = {k: getattr(b, k) for k in ("system", "prompt", "reply") if getattr(b, k) is not None}
        if b.keep is not None: sets["keep"] = int(b.keep)
        if not sets: return self.entry(me, pid)
        if any(k in sets for k in ("system", "prompt", "reply")): sets["edited"] = time.time()
        self.db.q(f"UPDATE mw_prompts SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), pid))
        return self.entry(me, pid)

    def delete(self, me, pid):
        p = self._entry(me, pid)
        self.db.q("DELETE FROM mw_prompts WHERE id=?", (pid,))
        return {"deleted": 1, "comp": p["comp_id"]}

    def bulk(self, me, wid, b: BulkIn):
        self.w._own(me, wid)
        if b.ids: where, args = f"id IN ({','.join('?' * len(b.ids))})", list(b.ids)
        elif b.agents: where, args = f"agent_id IN ({','.join('?' * len(b.agents))})", list(b.agents)
        elif b.all: where, args = "1=1", []
        else: raise HTTPException(422, "Pick the entries (or the agents) first.")
        where = f"comp_id=? AND {where}"; args = [wid, *args]
        if b.action == "export":
            rows = self.db.q(f"SELECT * FROM mw_prompts WHERE {where} ORDER BY id", tuple(args))
            names = {a["id"]: a["name"] for a in self.w._agents(wid)}
            return {"entries": [self._shape(p, TEXT) | {"agent_name": names.get(p["agent_id"], "a former teammate")} for p in rows]}
        n = self.db.q(f"SELECT COUNT(*) n FROM mw_prompts WHERE {where}", tuple(args), one=True)["n"]
        if b.action == "delete": self.db.q(f"DELETE FROM mw_prompts WHERE {where}", tuple(args))
        else: self.db.q(f"UPDATE mw_prompts SET keep=? WHERE {where}", (int(b.action == "keep"), *args))
        return {"changed": n}

    # ---------- the roadmap ----------
    def roadmap(self, wid):
        rows = self.db.q("SELECT * FROM mw_milestones WHERE comp_id=? ORDER BY CASE WHEN due='' OR due IS NULL THEN 1 ELSE 0 END, due, id", (wid,))
        return [{"id": m["id"], "title": m["title"], "detail": m["detail"] or "", "starts": m["starts"] or "", "due": m["due"] or "",
                 "status": m["status"], "agent": m["agent_id"], "updated": m["updated"]} for m in rows]

    def plan_roadmap(self, wid):
        """The roadmap for the lead's plan, every milestone by id with its status and due date (overdue ones flagged), and how to
        keep it current (PLAN milestones). "" without a roadmap."""
        road = self.roadmap(wid)
        if not road: return ""
        today = _day(time.time())
        rows = [f"- id {m['id']} [{m['status']}] {m['title']}" + (f", due {m['due']}" if m["due"] else "")
                + (" (OVERDUE)" if m["due"] and m["due"] < today and m["status"] != "done" else "") for m in road]
        return (f"\n\nThe roadmap by milestone id (today is {today}). It is only as current as you keep it: when the notebook or the "
                "board shows a milestone finished, started or moved, say so in milestones (id, status todo/doing/done, due YYYY-MM-DD "
                "or \"\" to keep it):\n" + "\n".join(rows))

    def lead_milestones(self, wid, agent, updates):
        """The lead's plan keeping the roadmap current: status and due date of this team's existing milestones only (no new ones,
        no titles, nothing deleted), each change an event on the board. Returns the changes made, as text."""
        made = []
        for u in (updates or [])[:MAX_MILESTONES]:
            try: mid = int(u.get("id"))
            except (TypeError, ValueError, AttributeError): continue
            m = self.db.q("SELECT * FROM mw_milestones WHERE id=? AND comp_id=?", (mid, wid), one=True)
            if not m: continue
            sets = {}
            st = (u.get("status") or "").strip()
            if st in ("todo", "doing", "done") and st != m["status"]: sets["status"] = st
            due = (u.get("due") or "").strip()
            if due and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) and due != (m["due"] or ""): sets["due"] = due
            if not sets: continue
            sets["updated"] = time.time()
            self.db.q(f"UPDATE mw_milestones SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), mid))
            what = " and ".join(([f"marked it {'done' if st == 'done' else 'in progress' if st == 'doing' else 'to do'}"] if "status" in sets else [])
                                + ([f"moved it from {m['due'] or 'no date'} to {sets['due']}"] if "due" in sets else []))
            text = f"{agent['name']} kept the roadmap current: “{m['title']}”: {what}"
            self.w._event(wid, "done" if sets.get("status") == "done" else "plan", text, agent["id"])
            made.append(text)
        return made

    def _milestone(self, me, mid):
        m = self.db.q("SELECT * FROM mw_milestones WHERE id=?", (mid,), one=True)
        if not m: raise HTTPException(404, "There's no such milestone.")
        self.w._own(me, m["comp_id"])
        return m

    def add_milestone(self, me, wid, b: MilestoneIn):
        self.w._own(me, wid)
        if self.db.q("SELECT COUNT(*) n FROM mw_milestones WHERE comp_id=?", (wid,), one=True)["n"] >= MAX_MILESTONES:
            raise HTTPException(409, f"A roadmap has at most {MAX_MILESTONES} milestones.")
        if b.agent is not None: self.w._agent_row(wid, b.agent)
        now = time.time()
        self.db.q("INSERT INTO mw_milestones (comp_id, title, detail, starts, due, status, agent_id, created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                  (wid, b.title.strip(), b.detail.strip(), _date(b.starts), _date(b.due), b.status, b.agent, now, now))
        return self.state(me, wid)

    def patch_milestone(self, me, mid, b: MilestonePatch):
        m = self._milestone(me, mid)
        sets = {k: getattr(b, k).strip() for k in ("title", "detail") if getattr(b, k) is not None}
        sets |= {k: _date(getattr(b, k)) for k in ("starts", "due") if getattr(b, k) is not None}
        if b.status: sets["status"] = b.status
        if b.unassign: sets["agent_id"] = None
        elif b.agent is not None: self.w._agent_row(m["comp_id"], b.agent); sets["agent_id"] = b.agent
        if sets:
            sets["updated"] = time.time()
            self.db.q(f"UPDATE mw_milestones SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), mid))
            if b.status and b.status != m["status"]:
                self.w._event(m["comp_id"], "done" if b.status == "done" else "plan", f"{me['username']} marked the milestone “{m['title']}” {'done' if b.status == 'done' else 'in progress' if b.status == 'doing' else 'to do'}")
        return self.state(me, m["comp_id"])

    def delete_milestone(self, me, mid):
        m = self._milestone(me, mid)
        self.db.q("DELETE FROM mw_milestones WHERE id=?", (mid,))
        return self.state(me, m["comp_id"])

    def seed(self, me, wid, replace=False):
        """A default roadmap, spread from the competition's start (or today) to its end (or two weeks on)."""
        w, c = self.w._own(me, wid)
        if self.db.q("SELECT 1 FROM mw_milestones WHERE comp_id=?", (wid,), one=True):
            if not replace: raise HTTPException(409, "The roadmap already has milestones.")
            self.db.q("DELETE FROM mw_milestones WHERE comp_id=?", (wid,))
        steps = RIDGES_ROADMAP if mining_packs.is_ridges(w) else GENERAL_ROADMAP
        today = _ts(_day(time.time()))
        start = _ts(w["starts"]) if w["starts"] else today
        end = _ts(w["ends"]) if w["ends"] and _ts(w["ends"]) > start else start + 14 * 86400
        span, now = (end - start) / len(steps), time.time()
        for i, (title, detail) in enumerate(steps):  # nothing is marked done: the user knows what is
            a, b = start + span * i, start + span * (i + 1)
            self.db.q("INSERT INTO mw_milestones (comp_id, title, detail, starts, due, status, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                      (wid, title, detail, _day(a), _day(b), "doing" if a <= today < b else "todo", now, now))
        self.w._event(wid, "plan", f"{me['username']} set up the roadmap: {len(steps)} milestones to {_day(end)}")
        return self.state(me, wid)

    # ---------- links ----------
    def links(self, wid):
        return [{"id": x["id"], "kind": x["kind"], "ref": x["ref"], "label": x["label"] or "", "url": x["url"] or "", "created": x["created"]}
                for x in self.db.q("SELECT * FROM mw_links WHERE comp_id=? ORDER BY kind, id", (wid,))]

    def link(self, me, wid, b: LinkIn):
        self.w._own(me, wid)
        if self.db.q("SELECT COUNT(*) n FROM mw_links WHERE comp_id=?", (wid,), one=True)["n"] >= MAX_LINKS: raise HTTPException(409, f"A team has at most {MAX_LINKS} links.")
        url = b.url.strip()
        if url and not (url.startswith("https://") or url.startswith("http://") or url.startswith("#")): raise HTTPException(422, "That isn't a link.")
        self.db.q("""INSERT INTO mw_links (comp_id, kind, ref, label, url, created) VALUES (?,?,?,?,?,?)
                     ON CONFLICT (comp_id, kind, ref) DO UPDATE SET label=excluded.label, url=excluded.url""",
                  (wid, b.kind, b.ref.strip(), b.label.strip(), url, time.time()))
        self.w._event(wid, "settings", f"{me['username']} linked the {LINK_KINDS[b.kind].lower()} {b.label.strip() or b.ref.strip()}")
        return self.state(me, wid)

    def unlink(self, me, lid):
        x = self.db.q("SELECT * FROM mw_links WHERE id=?", (lid,), one=True)
        if not x: raise HTTPException(404, "There's no such link.")
        self.w._own(me, x["comp_id"])
        self.db.q("DELETE FROM mw_links WHERE id=?", (lid,))
        return self.state(me, x["comp_id"])

    # ---------- the diagram ----------
    def layout(self, me, wid, b: LayoutIn):
        self.w._own(me, wid)
        pos = {k: [round(float(v[0]), 1), round(float(v[1]), 1)] for k, v in b.pos.items() if k.isdigit() and len(v) == 2}
        if pos: self.db.q("INSERT INTO mw_layout (comp_id, pos, updated) VALUES (?,?,?) ON CONFLICT (comp_id) DO UPDATE SET pos=excluded.pos, updated=excluded.updated",
                          (wid, json.dumps(pos), time.time()))
        else: self.db.q("DELETE FROM mw_layout WHERE comp_id=?", (wid,))
        return {"layout": pos}

    # ---------- levels ----------
    def levels(self, wid):
        q = self.db.q
        tasks = {r["agent_id"]: r for r in q("""SELECT agent_id, SUM(status='done') done, SUM(status='done' AND COALESCE(checks,0)=0) first_time,
                                                 SUM(status!='done') open FROM mw_tasks WHERE comp_id=? GROUP BY agent_id""", (wid,))}
        runs = {}
        for r in q("""SELECT agent_id, kind, status, COUNT(*) n, COALESCE(SUM(tokens),0) tokens, COALESCE(SUM(finished-started),0) secs, MAX(started) last
                      FROM mw_runs WHERE comp_id=? GROUP BY agent_id, kind, status""", (wid,)):
            runs.setdefault(r["agent_id"], []).append(r)
        notes = {r["agent_id"]: r["n"] for r in q("SELECT agent_id, COUNT(*) n FROM mw_notes WHERE comp_id=? GROUP BY agent_id", (wid,))}
        tools = {}
        for r in q("""SELECT r.agent_id, s.name, COUNT(*) n FROM mw_spans s JOIN mw_runs r ON r.id=s.run_id
                      WHERE r.comp_id=? AND s.kind='tool' AND s.error=0 GROUP BY r.agent_id, s.name ORDER BY n DESC""", (wid,)):
            tools.setdefault(r["agent_id"], []).append([r["name"], r["n"]])
        out, now = {}, time.time()
        for a in self.w._agents(wid):
            t, rs = tasks.get(a["id"]) or {}, runs.get(a["id"], [])
            cnt = lambda kind=None, status="done": sum(r["n"] for r in rs if (kind is None or r["kind"] == kind) and (status is None or r["status"] == status))
            rec = {"done": t.get("done") or 0, "first_time": t.get("first_time") or 0, "open": t.get("open") or 0, "notes": notes.get(a["id"], 0),
                   "reviews": cnt("review"), "plans": cnt("plan"), "runs": cnt(None, None), "task_runs": sum(r["n"] for r in rs if r["kind"] not in ("review", "plan") and r["status"] == "done"),
                   "failed": cnt(None, "failed"), "tokens": sum(r["tokens"] for r in rs), "hours": round(sum(r["secs"] or 0 for r in rs if r["secs"] and r["secs"] > 0) / 3600, 2),
                   "last": max((r["last"] or 0 for r in rs), default=0) or None, "days": max(0, int((now - (a["created"] or now)) // 86400)),
                   "tools": (tools.get(a["id"]) or [])[:5]}
            xp = (rec["done"] * XP["done"] + rec["notes"] * XP["note"] + rec["first_time"] * XP["first_time"] + rec["reviews"] * XP["review"] +
                  rec["plans"] * XP["plan"] + rec["task_runs"] * XP["run"] + rec["failed"] * XP["failed"])
            rec["approval"] = round(rec["first_time"] / rec["done"], 3) if rec["done"] else None
            out[a["id"]] = rec | {"level": level(max(0, xp))}
        return out

    def state(self, me, wid):
        self.w._own(me, wid)
        counts = {r["agent_id"]: r for r in self.db.q("""SELECT agent_id, COUNT(*) n, SUM(kind='user' AND seen IS NULL) waiting, SUM(keep) kept
                                                          FROM mw_prompts WHERE comp_id=? GROUP BY agent_id""", (wid,))}
        lay = self.db.q("SELECT pos FROM mw_layout WHERE comp_id=?", (wid,), one=True)
        return {"comp": wid, "levels": self.levels(wid), "roadmap": self.roadmap(wid), "links": self.links(wid), "kinds": LINK_KINDS,
                "layout": json.loads(lay["pos"]) if lay else {}, "ladder": [{"floor": lo, "name": n} for lo, n in LEVELS], "xp": XP,
                "prompts": {str(k): {"n": r["n"], "waiting": r["waiting"] or 0, "kept": r["kept"] or 0} for k, r in counts.items()},
                "prompts_total": sum(r["n"] for r in counts.values())}

    def notebook_md(self, me, wid):
        w, c = self.w._own(me, wid)
        names = {a["id"]: a["name"] for a in self.w._agents(wid)}
        notes = self.db.q("SELECT * FROM mw_notes WHERE comp_id=? ORDER BY id", (wid,))
        label = self.w._label(w)
        md = [f"# SN{c['netuid']} · {label}: the team's notebook", "", f"Exported {time.strftime('%Y-%m-%d %H:%M')}, {len(notes)} entries.", ""]
        for n in notes:
            md += [f"## {n['title']}", "", f"*{names.get(n['agent_id'], 'You')} · approved by {n['reviewer'] or '?'} · {time.strftime('%Y-%m-%d %H:%M', time.localtime(n['ts']))}*", "", n["body"] or "", ""]
        return {"name": re.sub(r"[^A-Za-z0-9._-]+", "-", f"SN{c['netuid']}-{label}-notebook").strip("-") + ".md", "text": "\n".join(md), "folder": f"SN{c['netuid']} {label}"[:80]}


def build(work, require):
    r = APIRouter(prefix="/api/mining/work")
    gate = work.m.hub.gate if work.m.hub else (lambda me: me)
    user = lambda req: gate(require(req))
    cr = Crew(work)
    r.state = {"crew": cr}

    @r.get("/comps/{wid}/crew")
    def state(wid: int, req: Request): return cr.state(user(req), wid)

    @r.get("/comps/{wid}/prompts")
    def history(wid: int, req: Request, agents: str = "", kind: str = "", q: str = "", before: int = 0, limit: int = 60):
        return cr.history(user(req), wid, agents, kind, q, before, limit)

    @r.post("/comps/{wid}/prompts")
    def write(wid: int, b: WriteIn, req: Request): return cr.write(user(req), wid, b)

    @r.post("/comps/{wid}/prompts/bulk")
    def bulk(wid: int, b: BulkIn, req: Request): return cr.bulk(user(req), wid, b)

    @r.get("/prompts/{pid}")
    def entry(pid: int, req: Request): return cr.entry(user(req), pid)

    @r.patch("/prompts/{pid}")
    def patch(pid: int, b: PromptPatch, req: Request): return cr.patch(user(req), pid, b)

    @r.delete("/prompts/{pid}")
    def delete(pid: int, req: Request): return cr.delete(user(req), pid)

    @r.post("/comps/{wid}/roadmap")
    def add_milestone(wid: int, b: MilestoneIn, req: Request): return cr.add_milestone(user(req), wid, b)

    @r.post("/comps/{wid}/roadmap/seed")
    def seed(wid: int, req: Request, replace: bool = False): return cr.seed(user(req), wid, replace)

    @r.patch("/milestones/{mid}")
    def patch_milestone(mid: int, b: MilestonePatch, req: Request): return cr.patch_milestone(user(req), mid, b)

    @r.delete("/milestones/{mid}")
    def delete_milestone(mid: int, req: Request): return cr.delete_milestone(user(req), mid)

    @r.post("/comps/{wid}/links")
    def link(wid: int, b: LinkIn, req: Request): return cr.link(user(req), wid, b)

    @r.delete("/links/{lid}")
    def unlink(lid: int, req: Request): return cr.unlink(user(req), lid)

    @r.put("/comps/{wid}/layout")
    def layout(wid: int, b: LayoutIn, req: Request): return cr.layout(user(req), wid, b)

    @r.get("/comps/{wid}/notebook.md")
    def notebook_md(wid: int, req: Request): return cr.notebook_md(user(req), wid)

    return r
