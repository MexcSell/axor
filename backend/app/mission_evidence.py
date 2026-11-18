"""Mission Operations, the two evidence views the 11-11 assessment still asked for (mounted by mission_ops.mount, /api/control/ops…).

1. Competitors as sources of evidence (§4.3), per competition, as a seven-step process whose state comes from records:
   discover (leading and unsuccessful competitors) → collect (their submissions, runs, versions) → identify techniques (what
   moved a competitor's score, what only the leaders solve, what breaks submissions) → hypothesis (why it would work for us,
   written by a person or an agent) → reproduce in isolation (a task on the team's board: its sandbox, its own candidate) →
   evaluate on the same validation dataset (a benchmark result that task filed on the frozen suite, against the frozen
   reference) → adopt only on a measured improvement.
   Steps 1–3 read the competitor harvest (mining_rivals: Ridges competitions); a technique can also be written by hand for any
   competition. The one table, mo_techniques, keeps what a person decided: the hypothesis, the reproduction task and the verdict.
   adopt() refuses without a candidate result on the same suite that beats the baseline: copying a successful competitor proves
   nothing about our miner. Learn from them, never copy (mining_rivals.NOTE).

2. Knowledge visibility (gap 7): a search that ran is not knowledge that was used. Six questions, each from records: what
   sources exist, which are indexed, which agents may read what, what was actually retrieved, whether it was used in a decision
   (cited in an answer, recalled into a task's context), and how the work that used it went (an association, not proof).
   Searches that found nothing the actor may read are listed per actor with what would fix it.
"""
import json, re, time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

DAY = 86400
WEEK = 7 * DAY
STATUS = ("hypothesis", "reproducing", "evaluated", "adopted", "rejected")
STEPS = (("discover", "Discover", "Leading and unsuccessful competitors"), ("collect", "Collect", "Their submissions, results and versions"),
         ("identify", "Identify techniques", "What moved a score, what only leaders solve, what breaks submissions"),
         ("hypothesis", "Form hypotheses", "Why a technique would work for our miner"), ("reproduce", "Reproduce in isolation", "A sandbox task on its own candidate"),
         ("evaluate", "Evaluate on the same dataset", "The frozen suite, against the frozen reference"), ("adopt", "Adopt on measured improvement", "Only what beats the baseline"))
NOTE = "Learn from competitors, never copy: a competitor's code is theirs, and a technique that works for them proves nothing about your miner until it is measured."


def ensure_schema(db):
    db.q("""CREATE TABLE IF NOT EXISTS mo_techniques (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mission TEXT, source TEXT, source_ref TEXT,
            title TEXT, observation TEXT, hypothesis TEXT, status TEXT, task_id INTEGER, baseline REAL, candidate REAL, suite TEXT, decided_by TEXT,
            note TEXT, created REAL, updated REAL)""")
    db.q("CREATE INDEX IF NOT EXISTS mo_techniques_m ON mo_techniques (user_id, mission)")


def _j(s, d=None):
    if isinstance(s, (dict, list)): return s
    try: return json.loads(s) if s else d
    except (TypeError, ValueError): return d


def _clip(s, n): s = str(s or ""); return s if len(s) <= n else s[:n - 1] + "…"
def _s(n, w, s="s"): return f"{n} {w}{'' if n == 1 else s}"
def _pct(a, b): return round(100 * a / b) if b else None


# ---------------------------------------------------------------- 1. competitors as evidence
def _comp(ch, me, ref):
    m = re.fullmatch(r"comp:(\d+)", ref or "")
    w = ch._comps(me["id"]).get(int(m.group(1))) if m else None
    if not w: raise HTTPException(404, "There's no such competition of yours.")
    return w


def _harvest(ch, wid):
    """The competitor harvest's summary for a team, or None (not a Ridges competition, or nothing read yet)."""
    if not ch._has("rv_state"): return None, None
    st = ch.db.q("SELECT last_at, ok, error, summary FROM rv_state WHERE comp_id=?", (wid,), one=True)
    return (_j(st["summary"], None) if st else None), st


def observed(summary):
    """Candidate techniques the harvest shows, each with the evidence it rests on. Nothing here is a claim that it works for us."""
    out = []
    if not summary: return out
    for j in (summary.get("jumps") or [])[:6]:
        out.append({"source": "jump", "ref": f"jump:{j.get('from_id')}:{j.get('to_id')}", "kind": "What moved a competitor's score",
                    "title": f"{j['name']}: the change from v{j['from']} to v{j['to']}",
                    "observation": f"Score {j['before']} → {j['after']} (+{j['delta']})" + (f", {j['lines_changed']} lines changed" if j.get("lines_changed") is not None else "")
                                   + ". The diff of the largest gains is in the team's files under data/rivals/."})
    for p in (summary.get("lead_only") or [])[:5]:
        out.append({"source": "lead_only", "ref": f"problem:{p['problem']}", "kind": "What only the leaders solve",
                    "title": f"Solve “{_clip(p['problem'], 70)}” the way the leaders do",
                    "observation": f"Solved by {', '.join(p.get('leaders') or []) or 'leaders'}; only {round((p.get('rate') or 0) * 100)}% of the field solves it."})
    for p in (summary.get("misses") or [])[:4]:
        out.append({"source": "miss", "ref": f"miss:{p['problem']}", "kind": "What the leaders solve and your agent misses",
                    "title": f"Close the gap on “{_clip(p['problem'], 70)}”", "observation": f"Solved by {', '.join(p.get('leaders') or [])}; your best agent doesn't."})
    for f in (summary.get("failures") or [])[:4]:
        if f.get("side") == "platform": continue
        out.append({"source": "failure", "ref": f"failure:{_clip(f['error'], 60)}", "kind": "What breaks submissions (unsuccessful competitors)",
                    "title": f"Guard against “{_clip(f['error'], 70)}”", "observation": f"{_s(f['runs'], 'run')} of {_s(f['agents'], 'agent')} in the field failed this way."})
    for j in (summary.get("drops") or [])[:2]:
        out.append({"source": "drop", "ref": f"drop:{j.get('from_id')}:{j.get('to_id')}", "kind": "What made a competitor worse",
                    "title": f"Avoid {j['name']}'s change from v{j['from']} to v{j['to']}", "observation": f"Score {j['before']} → {j['after']} ({j['delta']})."})
    return out


def _measure(ch, w, t):
    """(baseline, candidate, suite, why not) for a technique: the result its reproduction task filed on the frozen suite, against
    the frozen reference (else the frozen candidate's latest comparable result)."""
    q, has = ch.db.q, ch._has
    if not (has("mw_release") and has("mw_bench")): return None, None, None, "Release & benchmarks isn't on this server."
    rel = q("SELECT * FROM mw_release WHERE comp_id=? AND current=1 ORDER BY id DESC LIMIT 1", (w["id"],), one=True)
    if not rel: return None, None, None, "No candidate and suite are frozen: without one there is no same dataset to compare on."
    base = rel.get("reference_score")
    if base is None:
        b = q("SELECT score FROM mw_bench WHERE comp_id=? AND release_id=? AND comparable=1 ORDER BY id DESC LIMIT 1", (w["id"], rel["id"]), one=True)
        base = b["score"] if b else None
    suite = f"{rel.get('suite') or 'suite'} ({rel.get('suite_tasks') or '?'} tasks)"
    if not t.get("task_id"): return base, None, suite, "Not reproduced yet."
    c = q("SELECT score, suite_hash FROM mw_bench WHERE comp_id=? AND task_id=? AND suite_hash=? ORDER BY id DESC LIMIT 1", (w["id"], t["task_id"], rel.get("suite_hash")), one=True)
    if not c:
        other = q("SELECT COUNT(*) AS n FROM mw_bench WHERE comp_id=? AND task_id=?", (w["id"], t["task_id"]), one=True)["n"]
        return base, None, suite, ("Its task filed a result on another suite: not the same dataset, so it doesn't count." if other else
                                   "Its task hasn't filed a benchmark result on the frozen suite yet.")
    if base is None: return None, c["score"], suite, "The frozen candidate has no reference score and no comparable result: nothing to compare against."
    return base, c["score"], suite, ""


def _technique(ch, w, r):
    t = dict(r)
    base, cand, suite, why = _measure(ch, w, t)
    if t["status"] in ("adopted", "rejected"):  # the figures the decision was made on stay
        base, cand, suite = (t["baseline"] if t["baseline"] is not None else base), (t["candidate"] if t["candidate"] is not None else cand), t["suite"] or suite
    task = ch.db.q("SELECT * FROM mw_tasks WHERE id=?", (t["task_id"],), one=True) if t.get("task_id") and ch._has("mw_tasks") else None  # *: older boards lack hold
    status = t["status"]
    if status == "reproducing" and cand is not None: status = "evaluated"
    delta = round(cand - base, 4) if cand is not None and base is not None else None
    return {"id": t["id"], "source": t["source"], "source_ref": t["source_ref"], "title": t["title"], "observation": t["observation"], "hypothesis": t["hypothesis"],
            "status": status, "task": {"id": task["id"], "title": task["title"], "status": task["status"], "gave_up": task.get("hold") == "failed"} if task else None,
            "task_gone": bool(t.get("task_id")) and not task, "baseline": base, "candidate": cand, "delta": delta, "suite": suite, "why_not": why,
            "can_adopt": status == "evaluated" and delta is not None and delta > 0, "decided_by": t["decided_by"], "note": t["note"], "created": t["created"], "updated": t["updated"]}


def competitors(ch, me, ref):
    """The competition's competitive-intelligence process: where each of the seven steps stands, what the harvest observed,
    and every technique with its hypothesis, reproduction and measured verdict."""
    w = _comp(ch, me, ref)
    summary, st = _harvest(ch, w["id"])
    rows = ch.db.q("SELECT * FROM mo_techniques WHERE user_id=? AND mission=? ORDER BY id DESC", (me["id"], ref))
    techs = [_technique(ch, w, r) for r in rows]
    taken = {t["source_ref"] for t in techs if t["source_ref"]}
    obs = [dict(o, taken=o["ref"] in taken) for o in observed(summary)]
    n = lambda s: sum(1 for t in techs if t["status"] == s)
    s = summary or {}
    failed = sum(v for k, v in (s.get("status") or {}).items() if re.search(r"fail|reject|disqual|error|didn", str(k), re.I))
    figs = {"discover": (s.get("agents") or 0, f"{s.get('agents') or 0} competitors in the field" + (f", {_s(len(s.get('leaders') or []), 'leader')}, {failed} that didn't qualify or failed" if s else "")),
            "collect": ((s.get("runs") or 0) + (s.get("versions") or 0), f"{s.get('runs') or 0} evaluation runs, {s.get('versions') or 0} earlier versions, {s.get('code') or 0} with source read" if s else "Nothing collected"),
            "identify": (len(obs), f"{_s(len(obs), 'candidate technique')} observed" if obs else "No technique observed yet"),
            "hypothesis": (len(techs), f"{_s(len(techs), 'hypothesis', 'es')} written" if techs else "No hypothesis written yet"),
            "reproduce": (sum(1 for t in techs if t["task"] or t["status"] in ("evaluated", "adopted")), f"{n('reproducing')} being reproduced on the team's board"),
            "evaluate": (sum(1 for t in techs if t["candidate"] is not None), f"{sum(1 for t in techs if t['candidate'] is not None)} measured on the frozen suite"),
            "adopt": (n("adopted"), f"{n('adopted')} adopted on a measured gain, {n('rejected')} rejected")}
    steps, reached = [], True
    for i, (k, label, what) in enumerate(STEPS):
        done = figs[k][0] > 0
        steps.append({"n": i + 1, "key": k, "label": label, "what": what, "count": figs[k][0], "detail": figs[k][1],
                      "state": "done" if done else "next" if reached else "todo"})
        reached = reached and done
    nxt = next((x for x in steps if x["state"] == "next"), None)
    advice = {"discover": "Nothing has been read about the field. For a Ridges competition the harvest runs by itself (Competition teams → Files & sandbox → data/rivals/); for another, write what you observed as a technique by hand.",
              "collect": "Competitors are known but their runs and versions aren't collected yet: wait for the harvest's next pass, or run it from the team's page.",
              "identify": "The field is collected but no technique stands out yet: more versions and runs are needed, or add one you noticed yourself.",
              "hypothesis": "Pick an observed technique and write why it would work for your miner: an observation is not yet a reason.",
              "reproduce": "Send a hypothesis to the team's board: it is rebuilt in the sandbox as its own candidate, never copied from the competitor's code.",
              "evaluate": "The reproduction must file a benchmark result on the frozen suite: only the same dataset can be compared with the reference.",
              "adopt": "Adopt what beat the baseline; reject what didn't. A technique that works for a competitor proves nothing until it is measured here."}
    hs = None
    if st: hs = {"last": st["last_at"], "ok": bool(st["ok"]), "error": st["error"]}
    return {"ref": ref, "title": ch._label(w), "note": NOTE, "harvest": hs, "harvested": bool(summary), "steps": steps,
            "next": {"step": nxt["label"], "text": advice[nxt["key"]]} if nxt else {"step": "", "text": "Every step has evidence. Keep watching the field: a new leader version is a new observation."},
            "leaders": (s.get("leaders") or [])[:5], "observed": obs, "techniques": techs,
            "counts": {"observed": len(obs), "hypothesis": n("hypothesis"), "reproducing": n("reproducing"), "evaluated": n("evaluated"), "adopted": n("adopted"), "rejected": n("rejected")}}


class TechniqueIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    observation: str = Field("", max_length=2000)
    hypothesis: str = Field(min_length=10, max_length=2000)
    source: str = Field("manual", max_length=20)
    source_ref: str = Field("", max_length=200)


def add_technique(ch, me, ref, b: TechniqueIn):
    _comp(ch, me, ref)
    if b.source_ref and ch.db.q("SELECT 1 FROM mo_techniques WHERE user_id=? AND mission=? AND source_ref=?", (me["id"], ref, b.source_ref), one=True):
        raise HTTPException(409, "A hypothesis for this observation exists already.")
    now = time.time()
    ch.db.q("""INSERT INTO mo_techniques (user_id, mission, source, source_ref, title, observation, hypothesis, status, created, updated) VALUES (?,?,?,?,?,?,?,'hypothesis',?,?)""",
            (me["id"], ref, b.source or "manual", b.source_ref or None, b.title.strip(), b.observation.strip(), b.hypothesis.strip(), now, now))
    ch._audit(me["id"], me["username"], "ops.technique.add", ref, _clip(b.title, 120))
    return competitors(ch, me, ref)


def _own(ch, me, ref, tid):
    w = _comp(ch, me, ref)
    t = ch.db.q("SELECT * FROM mo_techniques WHERE id=? AND user_id=? AND mission=?", (tid, me["id"], ref), one=True)
    if not t: raise HTTPException(404, "There's no such technique.")
    return w, t


def reproduce(ch, me, ref, tid):
    """Puts the reproduction on the team's board: built in the sandbox as its own candidate, measured on the frozen suite."""
    w, t = _own(ch, me, ref, tid)
    if t["status"] in ("adopted", "rejected"): raise HTTPException(409, "It's decided already.")
    if t["task_id"] and ch.db.q("SELECT 1 FROM mw_tasks WHERE id=?", (t["task_id"],), one=True): raise HTTPException(409, "Its reproduction is on the team's board already.")
    from .mining_work import TaskIn
    detail = (f"Reproduce a technique observed in the field, in isolation, and measure it.\n\nTechnique: {t['title']}\nObserved: {t['observation'] or 'written by hand'}\n"
              f"Hypothesis: {t['hypothesis']}\n\nDo: build it in the sandbox as its own candidate (write your own code: learn from a competitor, never copy theirs), "
              "run it on the frozen benchmark suite with the same settings as the frozen candidate, and file the result with the benchmark tool "
              "(the suite's name and task ids exactly as frozen).\nDone when: a benchmark result on the frozen suite is filed by this task, with what changed and the score. "
              "Do not merge or submit it: adoption is decided on the measured result.")
    new = [ch.w._add_task(me, w["id"], TaskIn(title=_clip(f"Reproduce and measure: {t['title']}", 160), detail=detail, priority="medium",
                                              mission=ref if re.fullmatch(r"(mx|comp):\d+", ref or "") else None))]
    ch.db.q("UPDATE mo_techniques SET task_id=?, status='reproducing', updated=? WHERE id=?", (new[0], time.time(), tid))
    ch._audit(me["id"], me["username"], "ops.technique.reproduce", ref, f"#{tid} → board task {new[0]}")
    return competitors(ch, me, ref)


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(adopt|reject)$")
    note: str = Field("", max_length=1000)


def decide(ch, me, ref, tid, b: DecideIn):
    """Adopt only on a measured improvement on the same dataset; reject any time, with what was learned."""
    w, t = _own(ch, me, ref, tid)
    if t["status"] in ("adopted", "rejected"): raise HTTPException(409, "It's decided already.")
    base, cand, suite, why = _measure(ch, w, dict(t))
    if b.decision == "adopt":
        if cand is None or base is None: raise HTTPException(409, f"Not measured yet: {why} A technique is adopted only on a result on the same validation dataset.")
        if cand <= base: raise HTTPException(409, f"It scored {cand:g} against a baseline of {base:g} on {suite}: no measured improvement, so it can't be adopted. Reject it, or change the hypothesis.")
    ch.db.q("UPDATE mo_techniques SET status=?, baseline=?, candidate=?, suite=?, decided_by=?, note=?, updated=? WHERE id=?",
            ("adopted" if b.decision == "adopt" else "rejected", base, cand, suite, me["username"], b.note.strip() or None, time.time(), tid))
    ch._audit(me["id"], me["username"], f"ops.technique.{b.decision}", ref, f"#{tid} {_clip(t['title'], 80)}: {base} → {cand} on {suite}")
    return competitors(ch, me, ref)


def summary_line(ch, uid, wid):
    """For the console's competition card and queue: techniques measured better and waiting for a decision."""
    if not ch._has("mo_techniques"): return None
    r = ch.db.q("""SELECT COUNT(*) AS n, SUM(CASE WHEN status='adopted' THEN 1 ELSE 0 END) AS adopted, SUM(CASE WHEN status='reproducing' THEN 1 ELSE 0 END) AS repro
                   FROM mo_techniques WHERE user_id=? AND mission=?""", (uid, f"comp:{wid}"), one=True)
    return {"techniques": r["n"] or 0, "adopted": r["adopted"] or 0, "reproducing": r["repro"] or 0}


# ---------------------------------------------------------------- 2. knowledge visibility
def knowledge(ch, me, now=None):
    """Six questions about knowledge, each from records. A search that ran is not knowledge that was used."""
    uid, q, has, now = me["id"], ch.db.q, ch._has, now or time.time()
    wk = now - WEEK
    n = lambda sql, args=(): (q(sql, args, one=True) or {}).get("n") or 0
    # 1. what sources exist
    sources = []
    def src(label, count, note, view): sources.append({"label": label, "n": count, "note": note, "view": view})
    items = indexed = passages = 0
    by_reach = {}
    if has("kb_items"):
        items = n("SELECT COUNT(*) AS n FROM kb_items WHERE user_id=? AND status='kept'", (uid,))
        by_reach = {r["reach"] or "page": r["n"] for r in q("SELECT reach, COUNT(*) AS n FROM kb_items WHERE user_id=? AND status='kept' GROUP BY reach", (uid,))}
        src("Knowledge Hub records", items, "documents, notes, links, decisions", "knowledge")
    if has("kb_sources"): src("Imported sources", n("SELECT COUNT(*) AS n FROM kb_sources WHERE user_id=?", (uid,)), "files and connectors the records came from", "knowledge")
    if has("mk_items"): src("Team lessons", n("SELECT COUNT(*) AS n FROM mk_items WHERE user_id=? AND lesson IS NOT NULL AND lesson!=''", (uid,)), "what competition teams learned from approved work", "teams")
    if has("mx_lessons"): src("Mission lessons", n("SELECT COUNT(*) AS n FROM mx_lessons WHERE user_id=?", (uid,)), "kept and failed approaches from missions", "learning")
    if has("wf_memory"): src("Workforce memories", n("SELECT COUNT(*) AS n FROM wf_memory WHERE user_id=? AND status='active'", (uid,)), "what Workforce agents keep between missions", "workforce")
    comps = [w for w in ch._comps(uid).values() if (w["status"] or "active") != "closed"]
    if comps and has("rv_state"):
        ids = [w["id"] for w in comps]
        src("Competitor harvests", n(f"SELECT COUNT(*) AS n FROM rv_state WHERE comp_id IN ({','.join('?' * len(ids))}) AND summary IS NOT NULL", ids), "teams with the field read into data/rivals/", "teams")
    # 2. which are indexed (searchable): records with passages of their current version
    if has("kb_chunks") and has("kb_items"):
        indexed = n("""SELECT COUNT(*) AS n FROM kb_items i WHERE i.user_id=? AND i.status='kept' AND EXISTS (SELECT 1 FROM kb_chunks c WHERE c.item_id=i.id AND c.ver=i.version)""", (uid,))
        passages = n("SELECT COUNT(*) AS n FROM kb_chunks c JOIN kb_items i ON i.id=c.item_id AND c.ver=i.version WHERE i.user_id=? AND i.status='kept'", (uid,))
    vectors = n("SELECT COUNT(*) AS n FROM kb_chunk_vecs WHERE user_id=?", (uid,)) if has("kb_chunk_vecs") else 0
    index = {"records": items, "indexed": indexed, "pct": _pct(indexed, items), "passages": passages, "vectors": vectors,
             "note": ("Nothing to index yet" if not items else f"{items - indexed} records have no passages of their current version: searches can't find them" if indexed < items
                      else "Every record is searchable") + ("" if vectors or not passages else "; no vectors, so searches match words, not meaning")}
    # 3. who may read what
    reach = [{"key": k, "label": {"page": "Private (only you)", "agents": "Shared with your agents", "teams": "Shared with your agents and teams"}.get(k, k), "n": v} for k, v in sorted(by_reach.items())]
    grants = q("SELECT scope, actor, by_user, created FROM kb_grants WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)) if has("kb_grants") else []
    readable_agents = by_reach.get("agents", 0) + by_reach.get("teams", 0)
    access = {"reach": reach, "grants": grants, "readable_by_agents": readable_agents, "readable_by_teams": by_reach.get("teams", 0),
              "note": ("No record is shared with agents: every agent search comes back empty until you share some (a record's Visibility)." if items and not readable_agents else
                       "No record is shared with competition teams: team agents find nothing." if items and comps and not by_reach.get("teams") else "")}
    # 4. what was actually retrieved, 5. whether it was used
    actors, retrieval = [], {"searches": 0, "found": 0, "empty_scope": 0, "no_match": 0, "cited": 0}
    if has("kb_queries"):
        r = q("""SELECT COUNT(*) AS n, SUM(CASE WHEN results>0 THEN 1 ELSE 0 END) AS found, SUM(CASE WHEN COALESCE(candidates,0)=0 THEN 1 ELSE 0 END) AS empty,
                        SUM(CASE WHEN COALESCE(candidates,0)>0 AND COALESCE(results,0)=0 THEN 1 ELSE 0 END) AS miss,
                        SUM(CASE WHEN cited IS NOT NULL AND cited NOT IN ('', '[]') THEN 1 ELSE 0 END) AS cited FROM kb_queries WHERE user_id=? AND ts>?""", (uid, wk), one=True) or {}
        retrieval = {"searches": r.get("n") or 0, "found": r.get("found") or 0, "empty_scope": r.get("empty") or 0, "no_match": r.get("miss") or 0, "cited": r.get("cited") or 0}
        for a in q("""SELECT actor, MAX(label) AS label, COUNT(*) AS n, SUM(CASE WHEN results>0 THEN 1 ELSE 0 END) AS found,
                             SUM(CASE WHEN COALESCE(candidates,0)=0 THEN 1 ELSE 0 END) AS empty FROM kb_queries WHERE user_id=? AND ts>?
                      GROUP BY actor ORDER BY SUM(CASE WHEN COALESCE(candidates,0)=0 THEN 1 ELSE 0 END) DESC, COUNT(*) DESC LIMIT 12""", (uid, wk)):
            actor, empty = a["actor"] or "you", a["empty"] or 0
            fix = ""
            if empty:
                team = str(actor).startswith("teams:")
                fix = ("There are no Knowledge Hub records yet: add or import some first (Knowledge), then share them with agents." if not items else
                       "Nothing is shared with teams: set a record's Visibility to “your agents and teams”, or grant this team a company scope (Knowledge → Access)." if team and not by_reach.get("teams")
                       else "Nothing is shared with agents: share records with your agents, or grant this agent a scope." if not team and actor != "you" and not readable_agents
                       else "It searched a scope with nothing indexed in it: check what it may read (Knowledge → Access) and that those records have passages.")
            actors.append({"actor": actor, "label": a["label"] or actor, "searches": a["n"], "found": a["found"] or 0, "empty_scope": empty, "fix": fix})
    recalls = {"recalls": 0, "found": 0, "used": 0, "success": 0, "partial": 0, "failure": 0, "open": 0}
    if has("ex_recalls"):
        r = q("SELECT COUNT(*) AS n, SUM(CASE WHEN found>0 THEN 1 ELSE 0 END) AS found FROM ex_recalls WHERE user_id=? AND ts>?", (uid, wk), one=True) or {}
        recalls.update(recalls=r.get("n") or 0, found=r.get("found") or 0)
    # 6. how the work that used it went
    if has("ex_uses"):
        for r in q("SELECT COALESCE(outcome, 'open') AS o, COUNT(*) AS n FROM ex_uses WHERE user_id=? AND ts>? GROUP BY COALESCE(outcome, 'open')", (uid, wk)):
            if r["o"] in recalls: recalls[r["o"]] = r["n"]
        recalls["used"] = n("SELECT COUNT(*) AS n FROM ex_uses WHERE user_id=? AND ts>? AND context IS NOT NULL", (uid, wk))
    rated = {"useful": 0, "not_useful": 0}
    if has("kb_uses"):
        r = q("SELECT SUM(CASE WHEN useful=1 THEN 1 ELSE 0 END) AS g, SUM(CASE WHEN useful=0 THEN 1 ELSE 0 END) AS b FROM kb_uses WHERE user_id=? AND ts>?", (uid, wk), one=True) or {}
        rated = {"useful": r.get("g") or 0, "not_useful": r.get("b") or 0}
    settled = recalls["success"] + recalls["partial"] + recalls["failure"]
    S = retrieval["searches"]
    questions = [
        {"key": "sources", "q": "What sources exist?", "a": f"{sum(s['n'] for s in sources):,} records across {_s(sum(1 for s in sources if s['n']), 'source')}" if sources else "No knowledge system on this server",
         "state": "ok" if any(s["n"] for s in sources) else "none"},
        {"key": "indexed", "q": "Which are indexed?", "a": f"{indexed} of {items} Knowledge Hub records are searchable ({passages:,} passages)" if items else "Nothing to index yet",
         "state": "none" if not items else "ok" if indexed == items else "warn"},
        {"key": "access", "q": "Which agents may read them?", "a": (f"{readable_agents} of {items} records are shared with agents, {by_reach.get('teams', 0)} of them with teams; {_s(len(grants), 'scope grant')}" if items else "No record to share yet"),
         "state": "none" if not items else "warn" if access["note"] else "ok"},
        {"key": "retrieved", "q": "What was actually retrieved?", "a": (f"{retrieval['found']} of {S} searches this week returned something; {retrieval['empty_scope']} found nothing the searcher may read, {retrieval['no_match']} found no match" if S else "No search this week"),
         "state": "none" if not S else "warn" if retrieval["empty_scope"] > S * 0.3 else "ok"},
        {"key": "used", "q": "Did it influence a decision?", "a": (f"{_s(retrieval['cited'], 'answer')} cited what they retrieved; {_s(recalls['used'], 'experience')} recalled into a task's or mission's context" if S or recalls["recalls"] else "Nothing was retrieved, so nothing could be used"),
         "state": "none" if not (S or recalls["recalls"]) else "ok" if retrieval["cited"] or recalls["used"] else "warn"},
        {"key": "outcome", "q": "Did that work go better?", "a": (f"Work that used a recalled experience: {recalls['success']} succeeded, {recalls['partial']} partly, {recalls['failure']} failed, {recalls['open']} still open"
                                                                   + (f"; people rated {rated['useful']} retrieved records useful, {rated['not_useful']} not" if rated["useful"] or rated["not_useful"] else "") if settled or recalls["open"] or rated["useful"] or rated["not_useful"]
                                                                   else "No outcome on record yet for work that used retrieved knowledge"),
         "state": "none" if not (settled or recalls["open"]) else "ok" if settled else "warn"}]
    return {"at": now, "since": wk, "questions": questions, "sources": sources, "index": index, "access": access, "retrieval": retrieval, "actors": actors, "recalls": recalls, "rated": rated,
            "caveat": "The outcome is an association, not proof: work that recalled an experience and succeeded did not necessarily succeed because of it.",
            "summary": (f"{retrieval['found']} of {S} searches found something" + (f", {retrieval['empty_scope']} had nothing they may read" if retrieval["empty_scope"] else "") if S else f"{items} records, no search this week")}


# ---------------------------------------------------------------- routes
def mount(r, ch, user):
    ensure_schema(ch.db)

    @r.get("/ops/knowledge")
    def knowledge_(req: Request): return knowledge(ch, user(req))

    @r.get("/ops/missions/{ref}/competitors")
    def competitors_(ref: str, req: Request): return competitors(ch, user(req), ref)

    @r.post("/ops/missions/{ref}/techniques")
    def add_(ref: str, b: TechniqueIn, req: Request): return add_technique(ch, user(req), ref, b)

    @r.post("/ops/missions/{ref}/techniques/{tid}/reproduce")
    def reproduce_(ref: str, tid: int, req: Request): return reproduce(ch, user(req), ref, tid)

    @r.post("/ops/missions/{ref}/techniques/{tid}/decide")
    def decide_(ref: str, tid: int, b: DecideIn, req: Request): return decide(ch, user(req), ref, tid, b)
