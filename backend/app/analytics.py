"""Analytics (AXoR 5.0, analytics.js, /api/analytics): performance, cost and intelligence across every agent system, from the
agent core's run ledger (ac_runs) and the systems that check their own work. Read-only; nothing here runs or spends tokens.

The headline is the spec's own: cost per successfully validated deliverable. A deliverable counts as validated only when
something other than the agent that made it checked it:
- a run an evaluator or verifier scored at VALID or more (ac_runs.score: Workforce verification, the Marketplace's evaluator and
  the other systems' verifiers), one per run ref; the Evolution Engine's own experiments are testing, not deliverables, so their
  tokens count and their scores don't, or
- a Mission Control mission delivered with the outcome "verified" (every acceptance criterion met, by an independent reviewer).
Tokens are every ledger run's in the period, so the number rises when work is wasted and falls when the same validated output
costs less. Dollars only where a system reports them (the Workflow's host runs, missions' own spend).

The scorecard is the spec's "how do we know AXoR reached Generation 5" table: eight measurements, each with the evidence it
rests on and "no data" when nothing has measured it yet (never a made-up score).
"""
import time

from fastapi import APIRouter, Request

import re

from . import agent_core, orchestrator, runner
from .hubs import Hubs, _j

DAY = 86400
VALID = 70  # a scored run at or above this counts as a validated deliverable


def _pct(a, b): return round(100 * a / b) if b else None


class Analytics(Hubs):
    def view(self, me, days=30, fresh=False):
        self._agents(me)
        days = days if days in (7, 30, 90) else 30
        return self.cached(f"analytics{days}", me, lambda m, out: self._view(m, out, days), fresh)

    def _period(self, uid, since, until):
        """Totals of one period from the ledger and the missions."""
        q = self.db.q
        led = {"runs": 0, "done": 0, "failed": 0, "scored": 0, "validated": 0, "tokens": 0, "usd": 0.0}
        if self._has("ac_runs"):
            r = q("""SELECT COUNT(*) runs, SUM(status='done') done, SUM(status IN ('failed','lost')) failed, COUNT(score) scored,
                            COALESCE(SUM(tokens),0) tokens, COALESCE(SUM(cost),0) usd FROM ac_runs
                     WHERE owner_id=? AND started>=? AND started<? AND status!='running' AND kind!='earlier'""", (uid, since, until), one=True)
            led.update({k: r[k] or 0 for k in ("runs", "done", "failed", "scored", "tokens", "usd")})
            led["validated"] = q("""SELECT COUNT(DISTINCT COALESCE(ref, CAST(id AS TEXT))) n FROM ac_runs WHERE owner_id=? AND started>=? AND started<?
                                    AND score>=? AND system NOT IN ('missions','evolution')""", (uid, since, until, VALID), one=True)["n"] or 0
        mis = {"total": 0, "delivered": 0, "verified": 0, "failed": 0, "recovered": 0, "usd": 0.0, "teamed": 0}
        if self._has("mx_missions"):
            r = q("""SELECT COUNT(*) total, SUM(status='delivered') delivered, SUM(status='delivered' AND outcome='verified') verified,
                            SUM(status IN ('failed','cancelled')) failed, SUM(status='delivered' AND attempts>1) recovered, COALESCE(SUM(spent),0) usd,
                            SUM(team IS NOT NULL) teamed
                     FROM mx_missions WHERE user_id=? AND COALESCE(finished, created)>=? AND COALESCE(finished, created)<?""", (uid, since, until), one=True)
            mis.update({k: r[k] or 0 for k in mis})
        validated = led["validated"] + mis["verified"]
        return {"ledger": led, "missions": mis, "validated": validated, "tokens": led["tokens"], "usd": round(led["usd"] + mis["usd"], 4),
                "per_validated": round(led["tokens"] / validated) if validated else None,
                "usd_per_validated": round((led["usd"] + mis["usd"]) / validated, 4) if validated and (led["usd"] + mis["usd"]) else None}

    def _view(self, me, out, days):
        uid, now, q = me["id"], time.time(), self.db.q
        since, prev = now - days * DAY, now - 2 * days * DAY
        cur, old = self._period(uid, since, now + 1), self._period(uid, prev, since)
        trend = None
        if cur["per_validated"] and old["per_validated"]:
            trend = round(100 * (cur["per_validated"] - old["per_validated"]) / old["per_validated"])
        out.update({"days": days, "valid": VALID, "current": cur, "previous": old, "trend": trend, "systems": [], "series": [], "agents": [], "scorecard": []})

        def systems():
            if not self._has("ac_runs"): return
            for r in q("""SELECT system, COUNT(*) runs, SUM(status='done') done, SUM(status IN ('failed','lost')) failed, COUNT(score) scored,
                                 AVG(score) avg, SUM(score>=? AND system!='evolution') valid, COALESCE(SUM(tokens),0) tokens, COALESCE(SUM(cost),0) usd,
                                 AVG(CASE WHEN finished IS NOT NULL THEN finished-started END) secs
                          FROM ac_runs WHERE owner_id=? AND started>=? AND status!='running' AND kind!='earlier' GROUP BY system ORDER BY tokens DESC""",
                       (VALID, uid, since)):
                out["systems"].append({"system": r["system"], "label": agent_core.SYSTEMS.get(r["system"], r["system"].capitalize()), "runs": r["runs"],
                                       "success": _pct(r["done"] or 0, r["runs"]), "failed": r["failed"] or 0, "scored": r["scored"] or 0,
                                       "avg_score": round(r["avg"], 1) if r["avg"] is not None else None, "validated": r["valid"] or 0,
                                       "tokens": r["tokens"], "usd": round(r["usd"], 4), "secs": round(r["secs"] or 0),
                                       "per_validated": round(r["tokens"] / r["valid"]) if r["valid"] else None})

        def series():
            days_ = {}
            if self._has("ac_runs"):
                for r in q("""SELECT CAST((started-?)/86400 AS INTEGER) d, COALESCE(SUM(tokens),0) tokens, SUM(score>=? AND system!='evolution') valid, COUNT(*) runs
                              FROM ac_runs WHERE owner_id=? AND started>=? AND status!='running' AND kind!='earlier' GROUP BY d""", (since, VALID, uid, since)):
                    days_[r["d"]] = {"tokens": r["tokens"], "validated": r["valid"] or 0, "runs": r["runs"]}
            if self._has("mx_missions"):
                for r in q("""SELECT CAST((finished-?)/86400 AS INTEGER) d, COUNT(*) n FROM mx_missions WHERE user_id=? AND finished>=? AND status='delivered'
                              AND outcome='verified' GROUP BY d""", (since, uid, since)):
                    days_.setdefault(r["d"], {"tokens": 0, "validated": 0, "runs": 0})["validated"] += r["n"]
            out["series"] = [{"day": time.strftime("%Y-%m-%d", time.localtime(since + i * DAY)), **days_.get(i, {"tokens": 0, "validated": 0, "runs": 0})}
                             for i in range(days)]

        def agents():
            if not self._has("ac_runs"): return
            names = {r["key"]: (r["name"], r["system"]) for r in q("SELECT key, name, system FROM ac_agents WHERE owner_id IN (?, 0)", (uid,))} if self._has("ac_agents") else {}
            for r in q("""SELECT agent_key, COUNT(*) runs, SUM(status='done') done, COUNT(score) scored, AVG(score) avg, SUM(score>=? AND system!='evolution') valid,
                                 COALESCE(SUM(tokens),0) tokens FROM ac_runs WHERE owner_id=? AND started>=? AND agent_key IS NOT NULL AND status!='running'
                                 AND kind!='earlier' GROUP BY agent_key ORDER BY tokens DESC LIMIT 40""", (VALID, uid, since)):
                nm, sy = names.get(r["agent_key"], (r["agent_key"], r["agent_key"].partition(":")[0]))
                out["agents"].append({"key": r["agent_key"], "name": nm, "system": sy, "runs": r["runs"], "success": _pct(r["done"] or 0, r["runs"]),
                                      "avg_score": round(r["avg"], 1) if r["avg"] is not None else None, "validated": r["valid"] or 0, "tokens": r["tokens"],
                                      "per_validated": round(r["tokens"] / r["valid"]) if r["valid"] else None})

        def scorecard():
            m, led, sc = cur["missions"], cur["ledger"], out["scorecard"]
            def row(k, name, want, value, detail, ok):
                sc.append({"k": k, "name": name, "want": want, "value": value, "detail": detail, "state": "none" if value is None else ("ok" if ok else "weak")})
            fin = m["delivered"] + m["failed"]
            row("missions", "Mission completion", "Reliable delivery against requirements", f"{_pct(m['verified'], fin)}%" if fin else None,
                f"{m['verified']} of {fin} finished missions delivered and independently verified ({m['delivered']} delivered)" if fin else "No mission finished in this period.",
                fin and m["verified"] / fin >= 0.6)
            ev = self._evo(uid, since)
            row("improvement", "Agent improvement", "Measurable benchmark improvement", f"{ev['gain']:+.1f} pts" if ev["gain"] is not None else None,
                f"{ev['promoted']} change{'s' if ev['promoted'] != 1 else ''} promoted with evidence; {ev['measured']} measured in experiments" if ev["measured"] else "No change measured in the Evolution Lab yet.",
                (ev["gain"] or 0) > 0)
            kt = self._transfer(uid, since)
            row("knowledge", "Knowledge transfer", "Reuse verified experience across projects", kt["value"], kt["detail"], kt["ok"])
            row("teams", "Team formation", "Automatically assemble appropriate specialists", f"{_pct(m['teamed'], m['total'])}%" if m["total"] else None,
                f"{m['teamed']} of {m['total']} missions ran with an assembled team" if m["total"] else "No mission in this period.", m["total"] and m["teamed"] / m["total"] >= 0.5)
            row("cost", "Cost optimization", "Improve quality within budget",
                f"{cur['per_validated']:,} tok" if cur["per_validated"] else None,
                (f"tokens per validated deliverable; {'%+d%%' % trend if trend is not None else 'no earlier period to compare'} vs the previous {days} days") if cur["per_validated"]
                else "Nothing was validated in this period, so there's no cost per deliverable.", trend is not None and trend <= 0)
            row("recovery", "Recovery", "Detect, recover and learn from failures",
                f"{_pct(m['recovered'], m['recovered'] + m['failed'])}%" if (m["recovered"] + m["failed"]) else None,
                f"{m['recovered']} missions delivered after a retry; {m['failed']} stopped" if (m["recovered"] + m["failed"]) else "No failure or retry in this period.",
                m["recovered"] >= m["failed"])
            row("evolution", "Evolution", "Safely test and promote improvements", f"{ev['promoted']}/{ev['measured']}" if ev["measured"] else None,
                f"promoted of measured; {ev['rolled_back']} rolled back; {ev['unverified_promoted']} promoted without evidence" if ev["measured"] else "No experiment yet.",
                ev["unverified_promoted"] == 0)
            gv = self._gov(uid, since)
            row("governance", "Governance", "Complete auditability and approval controls", f"{gv['audited']}%" if gv["decisions"] else None,
                f"{gv['decisions']} decisions in this period, {gv['audited']}% with an audit record; {gv['pending']} waiting for you" if gv["decisions"] else "No decision recorded in this period.",
                gv["audited"] == 100)

        def targets():  # G5-5 L5.1 (IC-11 change 6): the Owner's K-14 targets, for the Owner only (they are the organization's)
            from .missions import is_owner
            out["targets"] = self.targets(since) if is_owner(self.db, me) else None
        def rule():  # IC-11 open point (c): the page says from which date a board task's review stopped counting as a validated deliverable
            v = self.db.setting(orchestrator.REVIEWED_SINCE)
            out["reviewed_since"] = float(v) if v else None

        for label, fn in (("Systems", systems), ("Series", series), ("Agents", agents), ("Scorecard", scorecard), ("Targets", targets), ("Rule date", rule)):
            self._try(out, label, fn)

    # ---------- G5-5 L5.1 (contract IC-11, change 6): the Owner's first targets (K-14, decided 2026-11-13) ----------
    def targets(self, since):
        """M1, M2, M7, M8 and M9 across the whole server, each met, not_met or none (no data), with the ids behind it. Read-only.
        A target with nothing behind it is never met. M1, M7 and M9 are "at least one" targets and read everything on record; M2
        and M8 are "every" targets and read the page's period."""
        q, has, out = self.db.q, self._has, []
        def row(k, want, state, value, detail, ids=None):
            out.append({"k": k, "want": want, "state": state, "value": value, "detail": detail, "ids": ids or []})
        EXTERNAL = {"owner_attested_key", "owner_designated_evaluator"}  # what a competition measure's valid evidence rests on (missions._ev_chain, _ev_ingest)
        dl = q("SELECT id, understanding, verification, finished FROM mx_missions WHERE status='delivered' ORDER BY id") if has("mx_missions") else []
        for m in dl: m["u"], m["v"] = _j(m["understanding"], {}) or {}, _j(m["verification"], {}) or {}
        per = [m for m in dl if m["u"].get("persistent")]
        closed = [m["id"] for m in per if m["v"].get("rule") == 1 and m["v"].get("rests_on") and set(m["v"]["rests_on"]) <= EXTERNAL]
        row("M1", "At least one competition mission closed on measured evidence", "met" if closed else "not_met" if per else "none", len(closed) if per else None,
            f"{len(closed)} of {len(per)} delivered persistent team missions closed by rule 1 (criteria met) on external evidence only" if per
            else "No persistent team mission has been delivered.", closed)
        cur = [m for m in dl if (m["finished"] or 0) >= since]
        ind = [m["id"] for m in cur if m["v"].get("independent") is True]
        same = [m["id"] for m in cur if m["v"].get("independent") is False]
        unrec = len(cur) - len(ind) - len(same)
        row("M2", "Every delivered mission verified by someone other than the actor",
            "none" if not cur or (unrec and not same) else "not_met" if same else "met", f"{len(ind)} of {len(cur)}" if cur else None,
            (f"{len(ind)} of {len(cur)} missions delivered in this period record a verifier other than the actor" + (f"; {len(same)} were checked by the same model as the work" if same else "")
             + (f"; {unrec} don't record who verified them" if unrec else "")) if cur else "No mission was delivered in this period.", same)
        ans = [r["id"] for r in q("SELECT id FROM ev_proposals WHERE origin='mission' AND target_kind='team' AND status='answered' ORDER BY id")] \
            if has("ev_proposals") and "target_kind" in {c["name"] for c in q("PRAGMA table_info(ev_proposals)")} else []
        held, lost, waiting = {}, {}, {}  # L5.6: each mission's newest cycle record says, per answered gap, whether the measure held
        if has("io_events"):
            for r in q("""SELECT payload FROM io_events WHERE kind='mission.cycle' AND id IN (SELECT MAX(id) FROM io_events WHERE kind='mission.cycle' GROUP BY corr)"""):
                for g in ((_j(r["payload"], {}) or {}).get("proposals") or {}).get("rows") or []:
                    h = g.get("held") or {}
                    if h.get("verdict") in ("held", "not_held", "open"): {"held": held, "not_held": lost, "open": waiting}[h["verdict"]][g["id"]] = h
        on = sorted({h["rests_on"] for h in held.values()})
        row("M7", "At least one promoted improvement whose measured outcome held for 3 cycles", "met" if held else "not_met" if lost else "none", len(held) if (held or lost) else None,
            (f"{len(held)} answered gap{'s' if len(held) != 1 else ''} held for 3 measured cycles after the promotion, on {' and '.join(on)} evidence"
             + (" (technical evidence is a team's own measurement, not a competition result)" if any("technical" in x for x in on) else "") + ". " if held else
             f"{len(lost)} answered gap{'s' if len(lost) != 1 else ''} did not hold. " if lost else
             (f"{len(ans)} measured gap{'s' if len(ans) != 1 else ''} answered by a promoted change" + (f", {len(waiting)} still short of three measured cycles since" if waiting else "") + ". " if ans
              else "No measured gap has been answered by a promoted change yet. "))
            + "Read from each mission's newest cycle record.", sorted(held) or sorted(lost) or ans)
        used = q("""SELECT u.ref, r.actor, u.ts FROM ex_uses u JOIN ex_recalls r ON r.id=u.recall_id WHERE u.ref LIKE 'mxl:%' AND r.actor!='you' AND u.ts>=?""", (since,)) \
            if has("ex_uses") and has("ex_recalls") and has("mx_lessons") else []
        ids = sorted({int(x["ref"][4:]) for x in used if x["ref"][4:].isdigit()})
        wd = "withdrawn" if "withdrawn" in {c["name"] for c in q("PRAGMA table_info(mx_lessons)")} else "NULL withdrawn"
        oc = {r["id"]: r for r in q(f"SELECT id, outcome, {wd} FROM mx_lessons WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        def fine(x):  # for planners now; or a promoted trial's lesson handed out before its promotion was rolled back
            r = oc.get(int(x["ref"][4:])) or {"outcome": None, "withdrawn": None}
            return orchestrator.lesson_for_planners(r["outcome"]) or \
                (r["outcome"] == orchestrator.LESSON_TRIAL_WITHDRAWN and r["withdrawn"] is not None and (x["ts"] or 0) < r["withdrawn"])
        bad = sorted({int(x["ref"][4:]) for x in used if x["ref"][4:].isdigit() and not fine(x)})
        ok = sum(1 for x in used if x["ref"][4:].isdigit() and fine(x))
        row("M8", "100% of planner lesson uses are verified", "none" if not used else "not_met" if bad else "met", f"{_pct(ok, len(used))}%" if used else None,
            (f"{ok} of {len(used)} mission lessons handed to an engine or agent by recall in this period came from a verified mission, or from a promoted trial while its promotion stood" if used
             else "No mission lesson was handed to an engine or agent by recall in this period.")
            + " Counted from logged recalls; guidance and mission discovery select the same lessons and don't log each use.", bad)
        pairs, pos = [], []
        if has("au_versions") and has("mw_bench") and "evidence_ref" in {c["name"] for c in q("PRAGMA table_info(mw_bench)")}:
            proms = {}
            for v in q("SELECT comp_id, agent_id, version, source, ts FROM au_versions ORDER BY ts, id"):
                if re.fullmatch(r"upgrade|gate #\d+", v["source"] or ""): proms.setdefault(v["comp_id"], []).append(v)
            for comp, ps in proms.items():
                if len(ps) < 2: continue
                # measured = the job's kept result is intact and still says the row's score (runner.backed): naming a job isn't enough
                rid = "release_id" if "release_id" in {c["name"] for c in q("PRAGMA table_info(mw_bench)")} else "NULL AS release_id"
                bs = [b for b in q(f"""SELECT id, score, ts, suite_hash, evidence_ref, {rid} FROM mw_bench WHERE comp_id=? AND comparable=1 AND score IS NOT NULL
                                       AND evidence_ref LIKE 'job:%' ORDER BY ts, id""", (comp,))
                      if runner.backed(self.db, comp, b["evidence_ref"], b["score"], runner.release_measure(self.db, b["release_id"]))]  # D-034: its release's measuring job, if frozen
                for i in range(len(ps) - 1):
                    a = [b for b in bs if ps[i]["ts"] <= b["ts"] < ps[i + 1]["ts"]]
                    end = ps[i + 2]["ts"] if i + 2 < len(ps) else float("inf")
                    b = [x for x in bs if ps[i + 1]["ts"] <= x["ts"] < end and a and x["suite_hash"] == a[-1]["suite_hash"]]
                    if not (a and b): continue
                    p = {"team": comp, "from": a[-1]["score"], "to": b[-1]["score"], "bench_rows": [a[-1]["id"], b[-1]["id"]]}
                    pairs.append(p)
                    if p["to"] > p["from"]: pos.append(p)
        row("M9", "A positive measured slope for at least one team across two promoted versions", "met" if pos else "not_met" if pairs else "none",
            f"{pos[0]['from']:g} → {pos[0]['to']:g}" if pos else None,
            (f"Team {pos[0]['team']}: {pos[0]['from']:g} then {pos[0]['to']:g} on the same suite, each score read from a job's own output under consecutive promoted versions" if pos
             else f"{len(pairs)} pair{'s' if len(pairs) != 1 else ''} of consecutive promoted versions with a job-backed score under each; none rose" if pairs
             else "No team has two promoted agent versions with a job-backed benchmark score on the same suite under each."),
            [x for p in (pos or pairs) for x in p["bench_rows"]])
        return out

    def _evo(self, uid, since):
        o = {"measured": 0, "promoted": 0, "rolled_back": 0, "gain": None, "unverified_promoted": 0}
        if not self._has("ev_proposals"): return o
        rows = self.db.q("SELECT status, evidence FROM ev_proposals WHERE user_id=? AND COALESCE(tested, updated)>=?", (uid, since))
        gains = []
        for r in rows:
            e = _j(r["evidence"], None)
            if e and e.get("delta") is not None: o["measured"] += 1
            if r["status"] in ("promoted", "rolled_back"):
                o["promoted"] += 1
                if not (e and e.get("verified")): o["unverified_promoted"] += 1
                elif r["status"] == "promoted": gains.append(e["delta"])
            if r["status"] == "rolled_back": o["rolled_back"] += 1
        o["gain"] = round(sum(gains) / len(gains), 1) if gains else None
        return o

    def _transfer(self, uid, since):
        used = lessons = cited = 0
        if self._has("mx_lessons"):
            r = self.db.q("SELECT COUNT(*) n, SUM(used>0) u FROM mx_lessons WHERE user_id=?", (uid,), one=True)
            lessons, used = r["n"] or 0, r["u"] or 0
        if self._has("wf_memory"):
            cited = self.db.q("SELECT COUNT(*) n FROM wf_memory WHERE user_id=? AND status='active' AND cited>0", (uid,), one=True)["n"] or 0
        if not lessons and not cited: return {"value": None, "detail": "No lesson or memory kept yet.", "ok": False}
        return {"value": f"{_pct(used, lessons)}%" if lessons else f"{cited} cited",
                "detail": f"{used} of {lessons} mission lessons reused by a later mission; {cited} Workforce memories cited", "ok": (lessons and used / lessons >= 0.3) or cited > 0}

    def _gov(self, uid, since):
        dec = aud = pend = 0
        if self._has("ev_proposals"):
            ids = [r["id"] for r in self.db.q("SELECT id FROM ev_proposals WHERE user_id=? AND status IN ('promoted','rolled_back','rejected') AND updated>=?", (uid, since))]
            dec += len(ids)
            if ids and self._has("ev_audit"):
                have = {r["target"] for r in self.db.q("SELECT DISTINCT target FROM ev_audit WHERE user_id=? AND action IN ('proposal.promoted','proposal.rejected','proposal.rolled_back')", (uid,))}
                aud += sum(1 for i in ids if f"proposal:{i}" in have)
            pend += self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE user_id=? AND status='verified'", (uid,), one=True)["n"] or 0
        if self._has("og_requests"):
            r = self.db.q("SELECT SUM(status NOT IN ('pending')) d, SUM(status='pending') p FROM og_requests WHERE user_id=? AND COALESCE(decided, created)>=?", (uid, since), one=True)
            d = r["d"] or 0
            dec += d; aud += d  # the organization's requests are their own audit record (decided_by, decided, note)
            pend += r["p"] or 0
        if self._has("mx_requests"):
            r = self.db.q("SELECT SUM(status!='pending') d, SUM(status='pending') p FROM mx_requests WHERE user_id=? AND COALESCE(decided, created)>=?", (uid, since), one=True)
            dec += r["d"] or 0; aud += r["d"] or 0; pend += r["p"] or 0
        return {"decisions": dec, "audited": _pct(aud, dec) if dec else 100, "pending": pend}


def build(db, require, ov, co=None):
    r = APIRouter(prefix="/api/analytics")
    h = Analytics(db, ov, co)
    r.state = {"analytics": h}

    @r.get("")
    def analytics(req: Request, days: int = 30, fresh: bool = False): return h.view(require(req), days, fresh)

    return r
