"""The agent core: what every agent system in AXoR shares, under the pages and processes each one keeps.

AXoR grew about ten agent systems (your agents and the built-in ones, Agent HQ, the PDCA project team, Workforce, the Company,
Mission OS, Long tasks, Competition teams with their Workflow, Director, Portfolio and Upgrade Factory). Each keeps its own
process and its own tables. The core gives them one registry, one run ledger and one budget:

- Registry (ac_agents): every agent of every system under one key, "<system>:<id>" (the keys Agent Operations uses), with
  its owner, name, role, where it works and its status. A mirror: each system keeps creating and changing agents in its own
  tables, and sync() reads them with one owner-agnostic query per system (on start, then every SYNC seconds).
- Run ledger (ac_runs): one row per run of any system, as it happens: who owns it, which agent, what kind, its status, the
  tokens of every model call made during it and, for the Workflow's runs on the host, the dollars they cost. `ref` is the
  run's key in its own system ("wf:12", "mw:5", "co:3", "hq:9", …), which is also the key of its trace in Agent Operations.
  An engine opens a run with begin() on the thread that does the work and closes it with end(); every model call on that
  thread in between (llm.py) adds its tokens to it. A model call outside any run (a chat) is written as its own finished row
  by the agent hub's log_usage. record() writes a run that runs elsewhere (the workbench) without touching the thread.
- Budget: an owner's daily token limit over every system (ac_budget, off unless set). Before each model call in a run, the
  core says whether the owner's runs today already used it up; llm.py then refuses the call, as any provider error. Agent HQ
  (owner 0) has its own hourly budget and is never gated here.
  G5 (2026-11-09, orchestrator.py): scoped hard limits (ac_limits) on top, checked at the same gateway: global, system, mission
  (by correlation id, so a mission's child engine counts), team, agent and task contract, a token total or a daily one, and a
  per-call limit (each call's output is capped at it; one call over it stops the run). Off unless set; refusals say "token
  budget", which Autoloop and Mission Control class as a budget stop, and are kept in ac_limit_hits. begin() resolves each run's
  corr/team/contract once through the resolvers orchestrator.py registers.
- Model router (model_router.py): an owner's model pool and router weights (ac_pool), edited on the Workforce's Settings page,
  route every system's "auto" work. route() picks the pool model with the best S for the system and kind of work, from this
  ledger's runs of the last ROUTE_DAYS days (cost, time, failures, and the scores evaluators and verifiers give runs with
  score()). A model the user or the agent picked is never re-routed, and without a pool "auto" is the default model as before.
  Every decision is kept with the run it chose the model for (ac_runs.decision: source picked/routed/fallback/no_pool, the
  reason, the weights and the top candidates). route() writes it onto the run open on its thread for that owner, if any
  (systems that route inside the run); else it waits up to PENDING seconds, keyed (owner, system, kind, model), for the
  begin() of that run, on whatever thread (systems that route, then hand the work to a pool). A decision nothing claims is
  dropped, so one made for a check or a preview isn't kept.

Nothing here changes how a system works; a failure in the core is logged and never stops a run.
"""
import json, logging, os, re, threading, time
from datetime import date, timedelta

from . import bus, model_router

log = logging.getLogger("scout.agent_core")
SYNC, CAP_CACHE, BACKFILL, KEEP = 300, 30, 30, 120  # seconds, seconds, days, days
ROUTE_DAYS = 30  # the runs the router learns from
PENDING = 90     # seconds a routing decision waits on its thread for the run it was made for
SYSTEMS = {"hub": "Your agents", "builtin": "Built-in", "hq": "Agent HQ", "team": "Project team", "workforce": "Workforce",
           "company": "Company", "missions": "Mission OS", "longtask": "Long tasks", "teams": "Competition teams", "workflow": "Workflow",
           "evolution": "Evolution Lab", "other": "Other"}
# llm_usage sources (agent_hub.log_usage) → the system a chat's tokens belong to
SOURCES = {"chat": "hub", "workspace": "hub", "study": "hub", "practice": "hub", "test": "hub", "profile": "hub", "company": "company",
           "workforce": "workforce", "mining": "teams", "upgrade": "teams", "team": "team", "hq": "hq", "infiagent": "longtask"}
DONE = ("done", "failed", "cancelled", "stopped", "lost")
# scoped limits (ac_limits): what a limit is on; a run falls under the ones that match it (see Core._matching)
SCOPES = {"global": "Global", "system": "System", "mission": "Mission", "team": "Team", "agent": "Agent", "contract": "Task contract"}

_local = threading.local()
_resolvers = []  # fn(system, ref) -> {"corr", "team", "contract"}: orchestrator.py registers the ones that read each system's tables
BOOT = __import__("uuid").uuid4().hex[:16]  # this process: a hold's holder
_leases, _llock, _lthread = {}, threading.Lock(), [None]  # hold id → database: holds this process keeps in flight (renewed)
_buckets = {}  # name → fn(run) -> [budget dicts]: a system's own token budget reservations count against (register_bucket)
_guards = {}  # name → fn(run) -> why the run may not make another model call, or None: a system's own budget, checked at the gateway (mining_work: the team's)
_core = None
_waiting, _plock = {}, threading.Lock()  # (owner, system, kind, model) → (routing decision, when): see _pending


def _today(): return time.mktime(date.today().timetuple())
def _month(): return time.mktime(date.today().replace(day=1).timetuple())  # a monthly limit's window: since the 1st, local time


class Core:
    def __init__(self, db, hub=None):
        self.db, self.hub = db, hub
        q = db.q
        q("""CREATE TABLE IF NOT EXISTS ac_agents (key TEXT PRIMARY KEY, system TEXT, local_id TEXT, owner_id INTEGER, name TEXT, role TEXT,
             place TEXT, status TEXT, seen REAL, created REAL)""")
        q("CREATE INDEX IF NOT EXISTS ac_agents_o ON ac_agents (owner_id, system)")
        q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT, owner_id INTEGER, agent_key TEXT, kind TEXT,
             ref TEXT, title TEXT, status TEXT, tokens INTEGER DEFAULT 0, reported INTEGER, cost REAL, model TEXT, error TEXT,
             started REAL, finished REAL)""")
        q("CREATE INDEX IF NOT EXISTS ac_runs_o ON ac_runs (owner_id, started)")
        q("CREATE INDEX IF NOT EXISTS ac_runs_r ON ac_runs (ref)")
        q("CREATE INDEX IF NOT EXISTS ac_runs_s ON ac_runs (status)")
        q("CREATE TABLE IF NOT EXISTS ac_budget (owner_id INTEGER PRIMARY KEY, daily_tokens INTEGER, updated REAL, by_user TEXT)")
        bc = {r["name"] for r in q("PRAGMA table_info(ac_budget)")}  # alerts: the owner's default warn-at share and whether a crossing pushes
        if "warn_pct" not in bc: q("ALTER TABLE ac_budget ADD COLUMN warn_pct INTEGER")
        if "notify" not in bc: q("ALTER TABLE ac_budget ADD COLUMN notify INTEGER DEFAULT 1")
        if "unlimited" not in bc:  # the owner chose to run without a daily cap, knowingly (when, and who): no budget is never a silent default
            q("ALTER TABLE ac_budget ADD COLUMN unlimited REAL")
            q("ALTER TABLE ac_budget ADD COLUMN unlimited_by TEXT")
        if "score" not in {r["name"] for r in q("PRAGMA table_info(ac_runs)")}:
            q("ALTER TABLE ac_runs ADD COLUMN score REAL")  # 0-100, from an evaluator or a verifier, after the run ended
        if "decision" not in {r["name"] for r in q("PRAGMA table_info(ac_runs)")}:
            q("ALTER TABLE ac_runs ADD COLUMN decision TEXT")  # JSON: why the run's model was chosen (compact_decision)
        q("CREATE TABLE IF NOT EXISTS ac_pool (owner_id INTEGER PRIMARY KEY, pool TEXT, weights TEXT, updated REAL, by_user TEXT)")
        # G5 (orchestrator.py): what a run belongs to, resolved once at begin(): its correlation id (the mission or task it
        # serves, "mx:4" for every run of mission 4's child engine too), its team and its task contract; scoped hard limits on them
        cols = {r["name"] for r in q("PRAGMA table_info(ac_runs)")}
        for c in ("corr", "team", "contract", "login", "login_kind", "metering"):  # login, login_kind: D-019; metering: D-021
            if c not in cols: q(f"ALTER TABLE ac_runs ADD COLUMN {c} TEXT")
        q("CREATE INDEX IF NOT EXISTS ac_runs_c ON ac_runs (corr)")
        q("""CREATE TABLE IF NOT EXISTS ac_limits (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, scope TEXT, key TEXT, label TEXT,
             tokens INTEGER, period TEXT, per_call INTEGER, origin TEXT, updated REAL, by_user TEXT, UNIQUE (owner_id, scope, key))""")
        q("""CREATE TABLE IF NOT EXISTS ac_limit_hits (id INTEGER PRIMARY KEY AUTOINCREMENT, limit_id INTEGER, owner_id INTEGER, run_id INTEGER,
             corr TEXT, kind TEXT, spent INTEGER, ts REAL, UNIQUE (limit_id, run_id, kind))""")
        q("CREATE INDEX IF NOT EXISTS ac_limit_hits_o ON ac_limit_hits (owner_id, ts)")
        lc = {r["name"] for r in q("PRAGMA table_info(ac_limits)")}
        if "warn_pct" not in lc: q("ALTER TABLE ac_limits ADD COLUMN warn_pct INTEGER")      # this limit's own warn-at share (else the owner's)
        if "mode" not in lc: q("ALTER TABLE ac_limits ADD COLUMN mode TEXT DEFAULT 'stop'")  # stop: a hard stop; alert: only alerts at the limit
        # a threshold crossed, once per limit (or the daily cap), period and level: what the Command Center and the push report
        q("""CREATE TABLE IF NOT EXISTS ac_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, ref TEXT, label TEXT, period TEXT, level TEXT,
             spent INTEGER, tokens INTEGER, ts REAL, UNIQUE (owner_id, ref, period, level))""")
        q("CREATE INDEX IF NOT EXISTS ac_alerts_o ON ac_alerts (owner_id, ts)")
        # a run still open was cut off by the restart (each system marks its own rows the same way); not the Workflow's, which run
        # on the host and go on through a restart: bench.tick closes them with their real outcome
        # D-025: a Codex run cut off by the restart never got its usage (Codex reports it only at the end): unknown, never 0. Milestone
        # 2: a Claude Code run too (its usage comes at each message's end, so the message in flight is lost; whether one was can't be
        # told). API-key runs lose at most the one call in flight and are not marked (residual, ARCHITECTURAL_GAP_REGISTER G-43)
        if "metering" in {r["name"] for r in q("PRAGMA table_info(ac_runs)")}:
            q("""UPDATE ac_runs SET metering='unmetered' WHERE status='running' AND system!='workflow' AND metering IS NULL
                 AND (model LIKE 'codex:%' OR login LIKE '%codex%' OR model LIKE 'terminal:%' OR login LIKE '%terminal%')""")
        # G5-2.2 Milestone 3: budget reservations. A model call under a stopping limit holds its estimate before it goes out (admit),
        # inside a transaction that checks spent + held + estimate against every limit over it; the call's reported use settles
        # it exactly once (settle). state: held (in flight, counted against limits), settled (actual known), released (the call
        # failed with an answer: nothing used), merged (folded into a later reservation of the same Codex session), charged (the
        # outcome is unknown and the call's bound is known: the bound is charged), unmetered (unknown and unbounded: D-025).
        q("""CREATE TABLE IF NOT EXISTS ac_reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, run_id INTEGER, rkey TEXT UNIQUE,
             model TEXT, estimate INTEGER, bound INTEGER, actual INTEGER, state TEXT, created REAL, expires REAL, settled REAL, note TEXT)""")
        rc = {r["name"] for r in q("PRAGMA table_info(ac_reservations)")}
        if "reserved" not in rc:  # Milestone 4: estimate (the prediction, never changed), reserved (what is held), actual (reported)
            q("ALTER TABLE ac_reservations ADD COLUMN reserved INTEGER")
            q("UPDATE ac_reservations SET reserved=estimate WHERE reserved IS NULL")
        if "holder" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN holder TEXT")  # the process holding it (BOOT); its lease is `expires`
        if "prov_at" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN prov_at REAL")      # D-036: when it was charged provisionally (immutable: the breaker counts charges made)
        if "prov_p" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN prov_p INTEGER")     # D-036: the figure first charged (immutable)
        if "fig_id" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN fig_id INTEGER")  # D-036 A1: the row carrying the person's figure that covers this hold (its group)
        if "late_real" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN late_real INTEGER")  # D-036 A1: real usage reported after a person's figure (summed; counted as max(figure, real))
        if "prov" not in rc: q("ALTER TABLE ac_reservations ADD COLUMN prov TEXT")  # D-036: provisional (charged by the system) | corrected (a person) | real (usage came late) | estimated (a person's D-025 estimate); else NULL
        # the audit trail (orchestrator.audit writes the same table): the core writes its own rows for D-036's charges and corrections
        q("""CREATE TABLE IF NOT EXISTS io_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, ts REAL, corr TEXT, actor TEXT, action TEXT,
             ref TEXT, detail TEXT)""")
        q("CREATE INDEX IF NOT EXISTS io_audit_o ON io_audit (owner_id, id)")
        q("CREATE INDEX IF NOT EXISTS ac_reservations_s ON ac_reservations (state, owner_id)")
        q("CREATE INDEX IF NOT EXISTS ac_reservations_r ON ac_reservations (run_id)")
        q("CREATE INDEX IF NOT EXISTS ac_reservations_m ON ac_reservations (owner_id, model, state)")
        self._recover("Its process stopped renewing the hold (a restart or a crash) before the call reported its usage.")
        q("""UPDATE ac_runs SET status='lost', finished=?, error=COALESCE(error, 'Stopped by a server restart.')
             WHERE status='running' AND system!='workflow'""", (time.time(),))
        self.caps, self.lock, self.synced = {}, threading.Lock(), 0
        self.alerted = set()  # (owner, ref, period, level) alerted already: see _threshold
        self._backfill()

    def _backfill(self):
        """The first start with the core: the last BACKFILL days of llm_usage become finished rows (kind 'earlier'), so totals don't
        start from zero. llm_usage was written by most systems, not all, so the ledger is complete only from this start on."""
        q = self.db.q
        if q("SELECT 1 FROM ac_runs LIMIT 1", one=True) or not self._has("llm_usage"): return
        since = time.time() - BACKFILL * 86400
        rows = q("SELECT user_id, ts, source, agent_id, model, tokens FROM llm_usage WHERE ts>=? AND tokens>0", (since,))
        for r in rows:
            src = r["source"] or "other"
            q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, title, status, tokens, model, started, finished)
                 VALUES (?,?,?,?,NULL,?,'done',?,?,?,?)""",
              (SOURCES.get(src, "other"), r["user_id"], f"hub:{r['agent_id']}" if r["agent_id"] and src in ("chat", "workspace", "study", "test") else None,
               "earlier", f"Before the agent core ({src})", r["tokens"], r["model"], r["ts"], r["ts"]))
        if rows: log.info("agent core: %d earlier model calls from llm_usage", len(rows))

    # ---------- runs ----------
    def begin(self, system, owner_id, kind, ref=None, agent_key=None, title="", model=None, decision=None):
        """Opens a run on this thread; model calls on it count toward it until end(). A run this thread left open is closed as lost.
        decision: why its model was chosen, when the system routed it itself (Workforce); else route()'s decision left on this
        thread for this model, if any."""
        old = getattr(_local, "run", None)
        if old: self._close(old, "lost", error="Its thread went on to other work without closing it.")
        dec = compact_decision(decision) if decision else _take_pending(owner_id, system, kind, model)
        sc = _resolve(system, ref)
        rid = self.db.q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, title, status, model, decision, started, corr, team, contract)
                           VALUES (?,?,?,?,?,?,'running',?,?,?,?,?,?) RETURNING id""",
                        (system, owner_id, agent_key, kind, ref, (title or "")[:200], model, dec and json.dumps(dec), time.time(),
                         sc.get("corr"), sc.get("team"), sc.get("contract")), one=True)["id"]
        _local.run = {"id": rid, "owner": owner_id, "system": system, "agent": agent_key, "ref": ref, **sc}
        bus.publish("run.started", run=rid, system=system, owner=owner_id, agent=agent_key, ref=ref, model=model, corr=sc.get("corr"))
        return rid

    def end(self, status="done", ref=None, tokens=None, error=None, model=None, cost=None):
        """Closes this thread's run, or the open run with `ref` (a system closing it from another thread). tokens: the system's own
        count, kept as `reported`; it stands for the run's tokens only when no model call was counted (a run that ran elsewhere)."""
        cur = getattr(_local, "run", None)
        rid = None
        if ref:
            r = self.db.q("SELECT id FROM ac_runs WHERE ref=? AND status='running' ORDER BY id DESC LIMIT 1", (ref,), one=True)
            rid = r and r["id"]
        elif cur: rid = cur["id"]
        if cur and rid is not None and cur["id"] == rid: _local.run = None
        if rid: self._close(rid, status, tokens, error, model, cost)

    def _close(self, rid, status, tokens=None, error=None, model=None, cost=None):
        rid = rid["id"] if isinstance(rid, dict) else rid
        self.db.q("""UPDATE ac_runs SET status=?, finished=?, reported=COALESCE(?, reported), tokens=CASE WHEN tokens=0 AND ? IS NOT NULL THEN ? ELSE tokens END,
                     error=COALESCE(?, error), model=COALESCE(?, model), cost=COALESCE(?, cost) WHERE id=? AND status IN ('running','lost')""",
                  (status, time.time(), tokens, tokens, tokens, (error or None) and str(error)[:400], model, cost, rid))
        bus.publish("run.finished", run=rid, status=status, tokens=tokens, model=model, error=(error or None) and str(error)[:200])

    def record(self, system, owner_id, kind, ref, status="running", agent_key=None, title="", tokens=None, cost=None, error=None, model=None):
        """A run that runs elsewhere (the workbench on the host): its row, opened or updated by ref, never this thread's run."""
        r = self.db.q("SELECT id, status FROM ac_runs WHERE ref=? ORDER BY id DESC LIMIT 1", (ref,), one=True)
        if not r:
            rid = self.db.q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, title, status, model, started)
                               VALUES (?,?,?,?,?,?,'running',?,?) RETURNING id""",
                            (system, owner_id, agent_key, kind, ref, (title or "")[:200], model, time.time()), one=True)["id"]
            r = {"id": rid, "status": "running"}
        if status != "running" and r["status"] in ("running", "lost"): self._close(r["id"], status, tokens, error, model, cost)

    def model(self, model):
        """The model this thread's open run turned out to run on, when it was known only after begin()."""
        cur = getattr(_local, "run", None)
        if not (cur and model): return
        r = self.db.q("SELECT system, kind, decision FROM ac_runs WHERE id=?", (cur["id"],), one=True)
        dec = _take_pending(cur["owner"], r["system"], r["kind"], model) if r and not r["decision"] else None  # routed before its model was known (Long tasks)
        if dec: self.db.q("UPDATE ac_runs SET model=?, decision=? WHERE id=?", (model, json.dumps(dec), cur["id"]))
        else: self.db.q("UPDATE ac_runs SET model=? WHERE id=?", (model, cur["id"]))

    def add_tokens(self, run_id, tokens):
        """Tokens that reached a run after it moved on (a Codex session drained later, D-021): added to that run's own row."""
        if run_id and tokens: self.db.q("UPDATE ac_runs SET tokens=tokens+? WHERE id=?", (int(tokens), run_id))

    def provisional_on(self):
        """D-036 (Proposed, not adopted): automatic provisional charge for one timed-out CLI call. OFF unless AC_PROVISIONAL=1 or the
        Owner's app setting ac_provisional is 1/on/true. Read every time, so a change applies at once. Off = D-025 exactly."""
        if os.getenv("AC_PROVISIONAL") == "1": return True
        try: return str(self.db.setting("ac_provisional", "") or "").strip().lower() in ("1", "on", "true")
        except Exception: return False  # noqa: BLE001 - unreadable = off = D-025

    def unmetered(self, why, run_id=None, single_call=False):
        """A model call whose tokens are unknown (D-021): its run (run_id, else this thread's) says so (metering 'unmetered')
        instead of counting 0 as if nothing ran. single_call (D-036): the one Claude Code call in flight timed out or was killed:
        with the switch on and a hold to settle, call_failed charges it provisionally instead, so the run isn't marked unmetered here."""
        cur = getattr(_local, "run", None)
        rid = run_id or (cur.get("id") if cur else None)
        if cur and rid is not None and rid == cur.get("id"): cur["unmetered_now"] = True  # the call in flight: its hold becomes unmetered (call_failed)
        if (single_call and cur and rid is not None and rid == cur.get("id") and cur.get("hold") and not cur.get("unverified")
                and self.provisional_on()):
            cur["provisional_now"] = True
            log.info("agent core: run %s: a single CLI call's use is unknown; provisional charge pending: %s", rid, str(why)[:200])
            return
        if rid is not None:
            self.db.q("UPDATE ac_runs SET metering='unmetered' WHERE id=?", (rid,))  # not error: the run itself may have done well
            log.info("agent core: run %s unmetered: %s", rid, str(why)[:200])

    def login(self, ref, kind):
        """The login a model call of this thread's run ran on (D-019): "server:terminal", "named:Claude-37", "user:4:codex",
        "api:anthropic"…; kind own | server | named | api | other_user. A run that used several keeps them all (kind "mixed").
        Names and ids only: never a token."""
        cur = getattr(_local, "run", None)
        if not cur or cur.get("id") is None or not ref: return
        seen = cur.setdefault("logins", [])
        if ref in seen: return
        seen.append(ref)
        self.db.q("UPDATE ac_runs SET login=?, login_kind=? WHERE id=?", (",".join(seen)[:200], kind if len(seen) == 1 else "mixed", cur["id"]))

    def decided(self, owner_id, decision):
        """route() inside an open run of this owner: the run keeps the decision (the first one, if it routes several times)."""
        cur = getattr(_local, "run", None)
        if not cur or cur["owner"] != owner_id: return False
        self.db.q("UPDATE ac_runs SET decision=? WHERE id=? AND decision IS NULL", (json.dumps(decision), cur["id"]))
        return True

    def used(self, tokens):
        """llm.py, after each model call: its tokens go to this thread's run. A call that holds a reservation settles it with them,
        in the same transaction that counts them (exactly once); a settlement that can't be written stops the run's next calls
        (UNKNOWN) and leaves the hold to the expiry rule, never to 0."""
        cur = getattr(_local, "run", None)
        if cur and tokens and cur.get("owner") and not cur.get("unverified"): self._per_call(cur, tokens)  # first: a ledger write that fails can't skip it
        hold = cur.pop("hold", None) if cur else None
        if cur: cur.pop("unmetered_now", None); cur.pop("provisional_now", None)
        if hold:
            try: self.settle([hold], tokens or 0, cur.get("id"))
            except Exception as e:  # noqa: BLE001 - the call happened: its hold stays counted until it expires (charged or unmetered)
                log.warning("agent core: a reservation couldn't be settled: %s: %s", type(e).__name__, e)
                cur["breach"] = VERIFY_STOP
                _unlease([hold])  # the call is over: no renewal, so its lease runs out and it lapses, never released as 0
            return
        if cur and tokens and cur.get("id") is not None: self.db.q("UPDATE ac_runs SET tokens=tokens+? WHERE id=?", (int(tokens), cur["id"]))

    def _per_call(self, cur, tokens):
        """A per-call limit: one call over it stops the run's next ones (its output was capped already). Checked against the
        per-call limits over() read for this call; when they can't be read, the run stops as UNKNOWN (G5-2 Blocker A)."""
        try: pcs = cur["per_call"] if "per_call" in cur else [L for L in self._matching(cur) if L["per_call"]]
        except Exception as e:  # noqa: BLE001
            log.warning("agent core: per-call verification failed: %s", e)
            cur["breach"] = VERIFY_STOP; return
        for L in pcs:
            if L["per_call"] and tokens > L["per_call"]:
                self._hit(cur, L, int(tokens), "per_call")
                cur["breach"] = (f"A single model call used {int(tokens):,} tokens, over the per-call token budget of {L['per_call']:,} "
                                 f"({SCOPES.get(L['scope'], L['scope'])}: {L['label'] or L['key']}). This run makes no more model calls.")
                break

    def chat(self, owner_id, source, tokens, agent_key=None, model=None):
        """agent_hub.log_usage: a model call made outside any run (chats) becomes its own finished row; inside a run it's counted already."""
        if getattr(_local, "run", None) or not tokens: return
        now = time.time()
        self.db.q("""INSERT INTO ac_runs (system, owner_id, agent_key, kind, ref, title, status, tokens, model, started, finished)
                     VALUES (?,?,?,?,NULL,?,'done',?,?,?,?)""", (SOURCES.get(source, "other"), owner_id, agent_key, source, source, int(tokens), model, now, now))

    # ---------- budget ----------
    def cap(self, owner_id):
        return self._budget_row(owner_id, fresh=True)["cap"]

    def _budget_row(self, owner_id, fresh=False):
        """The owner's ac_budget row. fresh: read now (every budget decision: the cache is only for alert settings and display,
        since a cap set on another replica must apply on the next check, G5-2 Blocker B)."""
        hit = self.caps.get(owner_id)
        if hit and not fresh and time.time() - hit[0] < CAP_CACHE and isinstance(hit[1], dict): return hit[1]
        r = self.db.q("SELECT * FROM ac_budget WHERE owner_id=?", (owner_id,), one=True) or {}
        out = {"cap": r.get("daily_tokens") or None, "warn_pct": r.get("warn_pct") or WARN_PCT, "notify": r.get("notify") is None or bool(r.get("notify")),
               "unlimited": r.get("unlimited") or None, "unlimited_by": r.get("unlimited_by")}
        self.caps[owner_id] = (time.time(), out)
        return out

    def alert_settings(self, owner_id):
        b = self._budget_row(owner_id)
        return {"warn_pct": b["warn_pct"], "notify": b["notify"], "default_warn_pct": WARN_PCT, "push": bool(_notifier) and bool(_push_on())}

    def set_alert_settings(self, owner_id, warn_pct=None, notify=None, by=""):
        if warn_pct is not None and not 1 <= int(warn_pct) <= 100: raise ValueError("Warn at 1 to 100 percent of a limit.")
        self.db.q("""INSERT INTO ac_budget (owner_id, warn_pct, notify, updated, by_user) VALUES (?,?,?,?,?)
                     ON CONFLICT(owner_id) DO UPDATE SET warn_pct=COALESCE(excluded.warn_pct, ac_budget.warn_pct),
                     notify=COALESCE(excluded.notify, ac_budget.notify), updated=excluded.updated, by_user=excluded.by_user""",
                  (owner_id, int(warn_pct) if warn_pct is not None else None, None if notify is None else int(bool(notify)), time.time(), by))
        self.caps.pop(owner_id, None)
        return self.alert_settings(owner_id)

    def _threshold(self, owner_id, ref, label, spent, tokens, day, warn_pct=None, stops=True):
        """A limit's use crossed its warn-at share or the limit itself: recorded once per (ref, period, level) and pushed to the
        owner when they want pushes. Runs inside over(), on figures it computed anyway; the memo keeps it off the database."""
        if not tokens: return
        b = self._budget_row(owner_id)
        warn = warn_pct or b["warn_pct"]
        level = "limit" if spent >= tokens else "warn" if spent >= tokens * warn / 100 else None
        if not level: return
        period = date.today().strftime("%Y-%m") if day == "month" else date.today().isoformat() if day else "total"
        k = (owner_id, ref, period, level)
        if k in self.alerted: return
        self.alerted.add(k)
        try:
            if self.db.q("SELECT 1 FROM ac_alerts WHERE owner_id=? AND ref=? AND period=? AND level=?", k, one=True): return
            self.db.q("INSERT OR IGNORE INTO ac_alerts (owner_id, ref, label, period, level, spent, tokens, ts) VALUES (?,?,?,?,?,?,?,?)",
                      (owner_id, ref, label, period, level, int(spent), int(tokens), time.time()))
        except Exception as e:  # noqa: BLE001 - an alert never decides a call
            log.warning("agent core alert: %s", e); return
        if b["notify"] and _notifier:
            pct = round(100 * spent / tokens)
            title = (f"{label}: limit reached" if level == "limit" else f"{label}: {pct}% of its limit used")
            body = (f"{spent:,} of {tokens:,} tokens{' this month' if day == 'month' else ' today' if day else ''}. " +
                    ("Work under it stops before its next model call." if level == "limit" and stops else
                     "This limit only alerts: work goes on." if level == "limit" else f"It warns at {warn}%; work stops at the limit." if stops else
                     f"It warns at {warn}%; this limit only alerts."))
            threading.Thread(target=_notify, args=(owner_id, title, body, level == "limit"), daemon=True, name="ac-alert").start()

    def alerts(self, owner_id, days=7):
        return self.db.q("SELECT * FROM ac_alerts WHERE owner_id=? AND ts>? ORDER BY id DESC LIMIT 50", (owner_id, time.time() - days * 86400))

    def spent_today(self, owner_id):
        return self.db.q("SELECT COALESCE(SUM(tokens), 0) AS n FROM ac_runs WHERE owner_id=? AND started>=?", (owner_id, _today()), one=True)["n"]

    def over(self):
        """Why this thread's run may not make another model call, or None: its owner's daily limit is used up, or a scoped limit
        it falls under (global, system, mission, team, agent or task contract; ac_limits), or one of its calls broke a per-call
        limit. The words "token budget" are what Autoloop's and Mission Control's failure classes read as a budget stop (not the
        task's fault). G5-2 Blocker A: when the limits can't be read (the database, a guard that throws) the answer is the
        verification refusal (VERIFY_STOP), never None: the call doesn't go out unverified."""
        cur = getattr(_local, "run", None)
        if not cur or not cur["owner"]: return None
        if cur.get("breach"): return cur["breach"]
        if cur.get("unverified"): return VERIFY_STOP  # begin() couldn't open its ledger row: nothing can be checked or counted
        try: r = self._verdict(cur, gateway=True)
        except Exception as e:  # noqa: BLE001 - UNKNOWN: the call waits, it is never let through
            log.warning("agent core: budget verification failed at the gateway: %s: %s", type(e).__name__, e)
            cur.pop("call_cap", None)
            return VERIFY_STOP
        if not r: return None
        if r["scope"].startswith("guard:"): cur["breach"] = r["reason"]  # a system budget's refusal holds for the rest of the run
        return r["message"]

    # ---------- reservations (G5-2.2 Milestone 3) ----------
    RESERVE_FLOOR = int(os.getenv("AXOR_RESERVE_FLOOR", "2000"))   # the least a call reserves when nothing better is known
    LEASE = int(os.getenv("AXOR_RESERVE_LEASE", "600"))  # Milestone 4: a hold's lease; its process renews it while the call is in flight
    MAX_HOLD = 12 * 3600  # renewals stop after this: a session lost in a live process can't hold its budget forever (it lapses, never 0)
    STRICT = os.getenv("AXOR_RESERVE_STRICT") == "1"     # API calls reserve their full bound (bytes sent + the output cap), not the estimate

    def admit(self, estimate=None, key=None, bound=None, model=None, reserve=None):
        """The gateway with a reservation: over()'s decision, plus, when a stopping limit is over this run, a hold of the call's
        estimate taken in the same transaction as the check (spent + held + estimate against every limit, the daily cap and the
        systems' own budgets). Returns None (go, the hold is on the thread for used() or call_failed()) or the refusal text.
        estimate: tokens to hold (0: check only, the call is covered by a hold already, a Codex session's next turn); None: this
        owner's recent actual use of `model` (estimate_call). bound: the most the call can use, when known (an API call's input
        plus its output cap). key: the request's idempotency key (default: the run and the call's number in it). reserve: what to hold
        when it differs from the estimate (an API call: its input estimate plus its output cap; AXOR_RESERVE_STRICT: its bound).
        Nothing stops: exactly over(), with no write. Milestone 4: estimate, reserved and actual are kept apart."""
        cur = getattr(_local, "run", None)
        if not cur or not cur["owner"]: return None
        if cur.get("breach"): return cur["breach"]
        if cur.get("unverified"): return VERIFY_STOP
        stale = cur.pop("hold", None); cur.pop("unmetered_now", None); cur.pop("provisional_now", None)
        try:
            if stale:  # a call whose settlement never came (a path that skipped used() and call_failed()): its use is unknown, never 0
                with self.db.tx():  # (the same request again, by its key, keeps its hold: a duplicate, not a new call)
                    rows = [r for r in self.db.q("SELECT id, run_id, bound, rkey FROM ac_reservations WHERE id=? AND state='held'", (stale,))
                            if not (key and r["rkey"] == str(key)[:200])]
                    if rows:
                        log.warning("agent core: reservation %s was never settled: it lapses (charged at its bound, or unmetered)", stale)
                        self._lapse(rows, "its call never reported: the use is unknown")
            if not self._limited(cur): return self.over()
            est = max(0, int(estimate)) if estimate is not None else self.estimate_call(cur["owner"], model, bound)
            res = est if not est else (int(bound) if self.STRICT and bound else max(est, int(reserve)) if reserve else est)
            deferred, rid = [], None
            _local.deferred = deferred
            try:
                with self.db.tx():  # its own transaction: an admission refused (or UNKNOWN) never rolls a lapse back (Milestone 4)
                    self._expire_due()
                with self.db.tx():
                    r = self._verdict(cur, gateway=True, estimate=res)
                    if not r and res: rid, r = self._reserve(cur, est, key, bound, model, res)
            finally:
                _local.deferred = None
            for fn, a in deferred: self._side(fn, *a)
        except Exception as e:  # noqa: BLE001 - UNKNOWN: the call waits, it is never let through
            log.warning("agent core: budget reservation failed at the gateway: %s: %s", type(e).__name__, e)
            cur.pop("call_cap", None)
            return VERIFY_STOP
        if r:
            if isinstance(r, str): return r
            if r["scope"].startswith("guard:") and r.get("release") != "settle": cur["breach"] = r["reason"]  # a hold-made refusal passes
            return r["message"]
        if rid: cur["hold"] = rid
        return None

    def _limited(self, cur):
        """Whether anything that stops is over this run: the owner's daily cap, a stopping limit with a token total, or a system's
        own budget (register_bucket). Without one there's nothing to reserve against: no transaction, no write."""
        if self._budget_row(cur["owner"], fresh=True)["cap"]: return True
        if any(L["tokens"] and (L.get("mode") or "stop") != "alert" for L in self._matching(cur)): return True
        return any(fn(cur) for fn in list(_buckets.values()))

    def estimate_call(self, owner, model, bound=None):
        """What a call reserves: the 90th percentile of this owner's last 50 settled calls (or Codex sessions) on this model, at least
        RESERVE_FLOOR; with no history, the average of the model's metered runs (a run is often one CLI session). Never above the
        call's bound, when it has one. An estimate, not a measurement: a call can use more (settle records the overrun)."""
        rows = [r["actual"] for r in self.db.q("""SELECT actual FROM ac_reservations WHERE owner_id=? AND model=? AND state='settled' AND actual IS NOT NULL
                                                ORDER BY id DESC LIMIT 50""", (owner, model or ""))] if model else []
        if rows:
            rows.sort()
            e = rows[max(0, -(-len(rows) * 9 // 10) - 1)]
        else:
            e = self.db.q("""SELECT AVG(tokens) AS a FROM (SELECT tokens FROM ac_runs WHERE owner_id=? AND model=? AND COALESCE(metering,'')='' AND tokens>0
                             ORDER BY id DESC LIMIT 50) x""", (owner, model or ""), one=True)["a"] if model else None
        e = max(self.RESERVE_FLOOR, int(e or 0))
        return min(e, int(bound)) if bound else e

    def _reserve(self, cur, est, key, bound, model, res=None):
        """Insert the hold (inside admit's transaction). A key seen before is the same request: its hold, never a second one; one
        already settled is refused (a duplicate request isn't run twice)."""
        cur["seq"] = cur.get("seq", 0) + 1
        key = str(key or f"run:{cur['id']}:{cur['seq']}")[:200]
        ex = self.db.q("SELECT id, state FROM ac_reservations WHERE rkey=?", (key,), one=True)
        if ex:
            if ex["state"] == "held": return ex["id"], None
            return None, ("This model call's token budget reservation was settled already: a duplicate request isn't run twice.")
        now = time.time()
        rid = self.db.q("""INSERT INTO ac_reservations (owner_id, run_id, rkey, model, estimate, reserved, bound, state, created, expires, holder)
                           VALUES (?,?,?,?,?,?,?,'held',?,?,?) RETURNING id""",
                        (cur["owner"], cur["id"], key, model, int(est), int(res or est), int(bound) if bound else None, now, now + self.LEASE, BOOT),
                        one=True)["id"]
        _lease(self.db, rid)  # renewed by this process while the call is in flight (Milestone 4)
        return rid, None

    def settle(self, rids, actual, run_id=None, note=None):
        """The reported use of the calls that held `rids` (several: one Codex session's turns): recorded on the first, the others
        merged into it, and counted on the run once, in one transaction. Exactly once: only holds still held (or charged or
        unmetered by the expiry rule: a late settlement) are settled; a second settle of the same hold changes nothing. A late
        settlement of a charged hold replaces the charge with the actual. Returns the tokens counted (0 when nothing was held)."""
        rids = [int(r) for r in (rids or []) if r]
        if not rids: return 0
        actual, now = max(0, int(actual or 0)), time.time()
        with self.db.tx():
            marks = ",".join("?" * len(rids))
            rows = self.db.q(f"SELECT id, run_id, owner_id, estimate, COALESCE(reserved, estimate) AS reserved, bound, state, actual, prov FROM ac_reservations WHERE id IN ({marks}) ORDER BY id", rids)
            live = [r for r in rows if r["state"] in ("held", "charged", "unmetered")]
            if not live and self._d036_run(rows):
                return self._late_after_person(rows, actual)
            if not live:
                # a person's D-025 estimate settled this hold: real usage arriving now counts as max(estimate, real), once, never stacked
                e = next((r for r in rows if r["state"] == "settled" and r["prov"] == "estimated"), None)
                if not e: return 0
                est, add = int(e["actual"] or 0), max(0, actual - int(e["actual"] or 0))
                if not self.db.q("UPDATE ac_reservations SET actual=?, prov='estimated_real', note=? WHERE id=? AND state='settled' AND prov='estimated' RETURNING id",
                                 (max(est, actual), f"real usage came after the person's estimate: counted max({est:,}, {actual:,})", e["id"]), one=True): return 0
                if add and e["run_id"]: self.db.q("UPDATE ac_runs SET tokens=tokens+? WHERE id=?", (add, e["run_id"]))
                self._audit(e["owner_id"], "system", "metering.estimate_real", f"run:{e['run_id']}",
                            f"real usage {actual:,} came after a person's estimate of {est:,}: counted {max(est, actual):,} (+{add:,})")
                return add
            first, rest = live[0], live[1:]
            # a charged hold counted its bound; a provisional one (D-036, no bound) counted its provisional figure: a late settlement replaces it
            charged = sum((r["bound"] or (r["actual"] if r["prov"] == "provisional" else 0) or 0) for r in live if r["state"] == "charged")
            late = any(r["state"] != "held" for r in live)
            for r in rest:
                self.db.q("UPDATE ac_reservations SET state='merged', actual=0, settled=?, note=?, prov=CASE WHEN prov='provisional' THEN 'real' ELSE prov END WHERE id=? AND state IN ('held','charged','unmetered')",
                          (now, f"settled with #{first['id']}", r["id"]))   # L4: a merged 0-row is no longer an open provisional charge
            res = sum(r["reserved"] or 0 for r in live)
            over = " over its bound: the provider billed more than the bytes sent and the output cap" if first["bound"] and actual > sum(r["bound"] or 0 for r in live) else ""
            got = self.db.q("""UPDATE ac_reservations SET state='settled', actual=?, reserved=?, settled=?, note=?,
                               prov=CASE WHEN prov='provisional' THEN 'real' ELSE prov END WHERE id=? AND state IN ('held','charged','unmetered')
                               RETURNING id""", (actual, res, now,
                                                 ((note or "") + (" late: after the hold expired" if late else "") + over).strip() or None, first["id"]), one=True)
            _unlease(rids)
            if not got: return 0
            rid = run_id or first["run_id"]
            delta = actual - charged
            if rid and delta: self.db.q("UPDATE ac_runs SET tokens=MAX(0, tokens+?) WHERE id=?" if not hasattr(self.db.db, "begin") else
                                        "UPDATE ac_runs SET tokens=GREATEST(0, tokens+?) WHERE id=?", (delta, rid))
            if first["prov"] == "provisional":  # D-036: the real figure replaced the provisional one, once; the run is metered again unless another is pending
                self.db.q("""UPDATE ac_runs SET metering=NULL WHERE id=? AND metering='provisional'
                             AND NOT EXISTS (SELECT 1 FROM ac_reservations WHERE run_id=? AND prov='provisional')""", (rid, rid))
                self._audit(first["owner_id"], "system", "metering.provisional_replaced", f"run:{rid}",
                            f"the real usage of a provisionally charged call came late: {first['actual']} tokens (provisional) replaced by {actual} (reported)")
        return actual

    def defer(self):
        """The call in flight's hold, taken off the thread (a Codex session's turn: its use is reported only when the session ends).
        The caller keeps it and settles it with the session (settle), or folds it into a later call's hold (absorb)."""
        cur = getattr(_local, "run", None)
        rid = cur.pop("hold", None) if cur else None
        return rid  # still leased: the session keeps it in flight until it reports or is drained

    def absorb(self, rids):
        """Earlier holds of a Codex session, folded into the call in flight's hold: its settlement (used) settles them all with the
        session's total, in the transaction that counts it. A session's later turns hold nothing of their own (admit(0)): then the
        session's first hold becomes the call's hold, the others folded into it."""
        rids = [r for r in (rids or []) if r]
        cur = getattr(_local, "run", None)
        if not rids: return
        if not cur:
            self.settle(rids, 0, note="no run on the thread when the session reported")
            return
        if not cur.get("hold"):
            first, rest = rids[0], rids[1:]
            if rest:
                with self.db.tx():
                    marks = ",".join("?" * len(rest))
                    n = self.db.q(f"SELECT COALESCE(SUM(COALESCE(reserved, estimate)),0) AS n FROM ac_reservations WHERE id IN ({marks}) AND state='held'", rest, one=True)["n"]
                    self.db.q(f"UPDATE ac_reservations SET state='merged', actual=0, settled=?, note=? WHERE id IN ({marks}) AND state='held'",
                              (time.time(), f"settled with #{first}", *rest))
                    _unlease(rest)
                    self.db.q("UPDATE ac_reservations SET reserved=COALESCE(reserved, estimate)+? WHERE id=?", (n, first))
            cur["hold"] = first
            return
        with self.db.tx():
            marks = ",".join("?" * len(rids))
            n = self.db.q(f"SELECT COALESCE(SUM(COALESCE(reserved, estimate)),0) AS n FROM ac_reservations WHERE id IN ({marks}) AND state='held'", rids, one=True)["n"]
            self.db.q(f"UPDATE ac_reservations SET state='merged', actual=0, settled=?, note=? WHERE id IN ({marks}) AND state='held'",
                      (time.time(), f"settled with #{cur['hold']}", *rids))
            _unlease(rids)
            self.db.q("UPDATE ac_reservations SET reserved=COALESCE(reserved, estimate)+? WHERE id=?", (n, cur["hold"]))

    def unknown_outcome(self, rids, why):
        """Holds whose calls' use will never be known (a Codex session aborted or drained without usage): unmetered (D-025), never
        released as 0. The run is marked unmetered by the caller."""
        rids = [r for r in (rids or []) if r]
        if rids:
            marks = ",".join("?" * len(rids))
            self.db.q(f"UPDATE ac_reservations SET state='unmetered', settled=?, note=? WHERE id IN ({marks}) AND state='held'", (time.time(), str(why)[:200], *rids))
            _unlease(rids)

    def call_failed(self, err):
        """The call in flight raised. Its hold is released only when its use is known to be none. An API call: the provider answered
        with an error status. A CLI call (no bound): a failure before the CLI ran the model (not signed in, not installed, a usage
        limit it reported, _no_use); a CLI that reported its use on failure settled it already (used()). Anything else may have run
        and reported nothing, and is never released as 0: an API call is charged at its bound, a CLI call is unmetered (D-025).
        Milestone 4: a CLI failure that isn't a timeout (a Codex turn.failed, a crash) was released as 0 before."""
        cur = getattr(_local, "run", None)
        if not cur: return
        rid, unm, prov = cur.pop("hold", None), cur.pop("unmetered_now", None), cur.pop("provisional_now", None)
        if not rid: return
        now = time.time()
        if unm:
            if prov:  # D-036: one timed-out Claude Code call, switch on
                try:
                    if self._provisional_charge(cur, rid, err): _unlease([rid]); return
                except Exception as e:  # noqa: BLE001 - never a silent pass: back to D-025 (unmetered, held for a person)
                    log.warning("agent core: provisional charge failed, falling back to D-025: %s: %s", type(e).__name__, e)
                self.db.q("UPDATE ac_runs SET metering=CASE WHEN metering IS NULL OR metering IN ('charged','estimated','provisional') THEN 'unmetered' ELSE metering END WHERE id=?",
                          (cur.get("id"),))
            self.unknown_outcome([rid], f"the call failed with its use unknown: {str(err)[:150]}"); return
        with self.db.tx():
            r = self.db.q("SELECT bound, run_id FROM ac_reservations WHERE id=? AND state='held'", (rid,), one=True)
            if not r: return
            # an API call (it has a bound) is released only when the provider answered with an error status (nothing billed);
            # any other failure may have been billed: charged at its bound. A CLI call (no bound) is unmetered when its outcome
            # is unknown (a timeout, a lost connection); its own failure paths record what they used (as the metering reads them)
            if r["bound"] and not _answered(err):
                self.db.q("UPDATE ac_reservations SET state='charged', settled=?, note=? WHERE id=?", (now, f"use unknown ({str(err)[:120]}): charged at its bound", rid))
                self.db.q("UPDATE ac_runs SET tokens=tokens+?, metering=COALESCE(metering, 'charged') WHERE id=?", (r["bound"], r["run_id"]))
            elif not r["bound"] and not _no_use(err):
                self.db.q("UPDATE ac_reservations SET state='unmetered', settled=?, note=? WHERE id=?", (now, f"use unknown ({str(err)[:120]})", rid))
                self.db.q("UPDATE ac_runs SET metering='unmetered' WHERE id=?", (r["run_id"],))
            else:
                self.db.q("UPDATE ac_reservations SET state='released', actual=0, settled=?, note=? WHERE id=?",
                          (now, f"the call failed before using anything: {str(err)[:150]}", rid))
        _unlease([rid])

    def _lapse(self, rows, why):
        """Holds no settlement reached (a crash, an expiry): their calls' use is unknown. A hold with a bound is charged at it (the run's
        metering 'charged'); without one the run is unmetered (D-025). Never 0."""
        now = time.time()
        _unlease([r["id"] for r in rows])
        for r in rows:
            if r["bound"]:
                if self.db.q("UPDATE ac_reservations SET state='charged', settled=?, note=? WHERE id=? AND state='held' RETURNING id", (now, why, r["id"]), one=True):
                    self.db.q("UPDATE ac_runs SET tokens=tokens+?, metering=COALESCE(metering, 'charged') WHERE id=?", (r["bound"], r["run_id"]))
            elif self.db.q("UPDATE ac_reservations SET state='unmetered', settled=?, note=? WHERE id=? AND state='held' RETURNING id", (now, why, r["id"]), one=True):
                self.db.q("UPDATE ac_runs SET metering='unmetered' WHERE id=?", (r["run_id"],))

    def _expire_due(self):
        """Holds whose lease ran out: their process stopped renewing it (it died, or the database couldn't be reached to renew).
        Lapsed inside admit's transaction. A call still in flight in a live process is renewed, so its hold never lapses here."""
        rows = self.db.q("SELECT id, run_id, bound FROM ac_reservations WHERE state='held' AND expires<?", (time.time(),))
        if rows: self._lapse(rows, "no settlement before the hold expired: the call is taken as lost")

    def _recover(self, why):
        """At start-up: holds whose lease has run out lapse. Milestone 4: only those. A live hold (another process holding it, or this
        server's previous process within its last lease) stays counted until its lease ends: a start-up never releases a hold whose
        call may still be running, and other processes (the acceptance script, probes) can start a core beside a live server."""
        try:
            with self.db.tx():
                rows = self.db.q("SELECT id, run_id, bound FROM ac_reservations WHERE state='held' AND expires<?", (time.time(),))
                if rows:
                    self._lapse(rows, why)
                    log.info("agent core: %d reservation(s) whose lease ran out lapsed (charged or unmetered)", len(rows))
        except Exception as e:  # noqa: BLE001 - logged; the holds stay counted until a later start or their expiry
            log.warning("agent core: reservation recovery failed: %s", e)

    def _held(self, owner, where="1=1", args=(), since=None):
        """Tokens held by calls in flight of this owner's runs in a scope and period (counted against its limits like spent ones)."""
        day = " AND started>=?" if since is not None else ""
        return self.db.q(f"""SELECT COALESCE(SUM(COALESCE(reserved, estimate)), 0) AS n FROM ac_reservations WHERE state='held' AND owner_id=?
                              AND run_id IN (SELECT id FROM ac_runs WHERE owner_id=? AND {where}{day})""",
                         (owner, owner, *args, *((since,) if day else ())), one=True)["n"]

    def _held_where(self, where, args=()):
        """Tokens held by calls in flight of the runs matching `where` (any owner): a system budget's (register_bucket)."""
        return self.db.q(f"SELECT COALESCE(SUM(COALESCE(reserved, estimate)), 0) AS n FROM ac_reservations WHERE state='held' AND run_id IN (SELECT id FROM ac_runs WHERE {where})",
                         tuple(args), one=True)["n"]

    def reservations(self, owner_id, days=7):
        """This owner's reservations of the last days: held now, and the settled ones' estimate against actual (overruns)."""
        since = time.time() - days * 86400
        rows = self.db.q("""SELECT state, COUNT(*) AS n, COALESCE(SUM(estimate),0) AS est, COALESCE(SUM(COALESCE(reserved, estimate)),0) AS res,
                              COALESCE(SUM(actual),0) AS act,
                              COALESCE(SUM(CASE WHEN actual>COALESCE(reserved, estimate) THEN actual-COALESCE(reserved, estimate) ELSE 0 END),0) AS over,
                              SUM(CASE WHEN actual>COALESCE(reserved, estimate) THEN 1 ELSE 0 END) AS overruns,
                              SUM(CASE WHEN bound IS NOT NULL AND actual>bound THEN 1 ELSE 0 END) AS over_bound
                              FROM ac_reservations WHERE owner_id=? AND created>? GROUP BY state""", (owner_id, since))
        return {r["state"]: {k: r[k] or 0 for k in ("n", "est", "res", "act", "over", "overruns", "over_bound")} for r in rows}

    def _unmetered_in(self, owner, where="1=1", args=(), since=None):
        """Runs in a scope and period whose tokens are unknown (D-021/D-025): metering 'unmetered', not yet given an estimate."""
        day = " AND started>=?" if since is not None else ""
        return self.db.q(f"SELECT COUNT(*) AS n FROM ac_runs WHERE owner_id=? AND {where} AND metering='unmetered'{day}",
                         (owner, *args, *((since,) if day else ())), one=True)["n"]

    def _verdict(self, cur, gateway=False, estimate=0):
        """The one budget decision under over() and preflight(): None (allowed) or the refusal. Limits and the daily cap are read
        from the database every time (G5-2 Blocker B: no per-process cache decides, so a limit set or dropped on any replica
        applies on the next check everywhere). Raises when anything it needs can't be read, a system guard included: the
        callers turn that into UNKNOWN. Alerts and the hit record are side effects that never decide (their errors are logged).
        gateway: the run's own check before a model call (thresholds, hits, the guard's refusal record, the per-call cap kept for
        this call); preflight passes False and writes nothing."""
        owner = cur["owner"]
        cap = self._budget_row(owner, fresh=True)["cap"]
        if cap:
            u = self._unmetered_in(owner, since=_today())
            if u: raise UnmeteredSpend(f"{u} run(s) today have unknown token use (no usage was reported), so your daily limit can't be checked: "
                                       "the work waits until a person records an estimate for them (Budgets → Unmetered runs).")
            n = self.spent_today(owner)
            h = self._held(owner, since=_today())
            if gateway: self._side(self._threshold, owner, "cap", "Your daily token limit", n, cap, True)
            if n >= cap or n + h + estimate > cap:
                why = (f"Your agents used {n:,} of your {cap:,} tokens for today, your daily token budget" if n >= cap else
                       f"Your agents used {n:,} of your {cap:,} tokens for today and calls in flight hold {h:,}: this call's reservation of "
                       f"{estimate:,} doesn't fit in your daily token budget")
                return {"scope": "owner_daily", "key": "", "limit_id": None, "label": "Your daily token limit", "tokens": cap, "spent": n, "held": h,
                        "estimate": estimate, "period": "day", "release": "reset" if n >= cap else "settle",
                        "release_at": _today() + 86400 if n >= cap else None, "limit_updated": None,
                        "reason": why + ".",
                        "message": (why + " (Agent Operations → Budget). Agent work stops until midnight, or until you raise the limit.")}
        matched = self._matching(cur)
        if gateway:  # this call's output cap and its per-call limits, from the same read (call_cap and used() use them)
            pc = [L for L in matched if L["per_call"]]
            cur["call_cap"] = min(L["per_call"] for L in pc) if pc else None
            cur["per_call"] = [{k: L[k] for k in ("id", "scope", "key", "label", "per_call")} for L in pc]
        for L in matched:
            if not L["tokens"]: continue
            stops = (L.get("mode") or "stop") != "alert"
            if not stops and not gateway: continue  # alert-only limits never refuse
            if stops:  # D-025: unknown use in the limit's scope and period can't be checked against it: fail closed (UNKNOWN), never 0
                w, a, since = self._scope(L)
                u = self._unmetered_in(owner, w, a, since)
                if u: raise UnmeteredSpend(f"{u} run(s) under the {SCOPES.get(L['scope'], L['scope']).lower()} limit {L['label'] or L['key']} have unknown "
                                           "token use (no usage was reported), so the limit can't be checked: the work waits until a person records an estimate.")
            n = self._spent(cur, L)
            h = self._held(owner, *self._scope(L)) if stops else 0
            if gateway:
                self._side(self._threshold, owner, f"limit:{L['id']}", f"{SCOPES.get(L['scope'], L['scope'])} limit {L['label'] or L['key']}", n, L["tokens"],
                           "month" if L["period"] == "month" else L["period"] == "day", L.get("warn_pct"), stops)
            if stops and (n >= L["tokens"] or n + h + estimate > L["tokens"]):
                if gateway: self._side(self._hit, cur, L, n, "tokens")
                per = L["period"]
                nxt = _today() + 86400 if per == "day" else time.mktime((date.today().replace(day=28) + timedelta(days=4)).replace(day=1).timetuple()) if per == "month" else None
                lbl = L["label"] or L["key"]
                when = ' today' if per == 'day' else ' this month' if per == 'month' else ''
                held = "" if n >= L["tokens"] else f"; calls in flight hold {h:,} and this call's reservation of {estimate:,} doesn't fit"
                return {"scope": L["scope"], "key": L["key"], "limit_id": L["id"], "label": lbl, "tokens": L["tokens"], "spent": n, "held": h, "estimate": estimate,
                        "period": per, "release": ("reset" if per in ("day", "month") else "raise") if n >= L["tokens"] else "settle",
                        "release_at": nxt if n >= L["tokens"] else None, "limit_updated": L.get("updated"),
                        "reason": f"Over the {SCOPES.get(L['scope'], L['scope']).lower()} token budget of {lbl}: {n:,} of {L['tokens']:,} tokens"
                                  f"{when or ' in total'}{held}.",
                        "message": (f"Over the {SCOPES.get(L['scope'], L['scope']).lower()} token budget of {lbl}: {n:,} of {L['tokens']:,} tokens"
                                    f"{when}{held} (Intelligence layers → Budgets). "
                                    "This work stops before its next model call.")}
        for name, fn in list(_buckets.items()):  # a system's own token budget, with the holds of its runs' calls in flight (Milestone 3)
            for b in fn(cur) or ():
                w, a = b["runs"]
                since = b.get("since")
                u = self.db.q(f"SELECT COUNT(*) AS n FROM ac_runs WHERE ({w}) AND metering='unmetered'" + (" AND started>?" if since else ""),
                              (*a, *((since,) if since else ())), one=True)["n"]
                if u: raise UnmeteredSpend(f"{u} run(s) under {b.get('label') or name} have unknown token use (no usage was reported), so its token "
                                           "budget can't be checked: the work waits until a person records an estimate.")  # Milestone 4: buckets too
                h = self._held_where(w, a)
                # D1: work that hasn't started is refused once the budget itself is used up (start_limit, a team's 100%), and otherwise
                # exactly as the gateway would refuse its first call (spent + held + that call's reservation against the run's limit)
                spent_out = cur.get("start") and b.get("start_limit") is not None and b["spent"] >= b["start_limit"]
                if spent_out or b["spent"] >= b["limit"] or b["spent"] + h + estimate > b["limit"]:
                    why = (f"{b.get('label') or name}: {b['spent']:,} of {b['start_limit']:,} tokens used. No new work starts until older runs leave "
                           "the window or the budget is raised." if spent_out and b["spent"] < b["limit"] else b["message"](b["spent"], h, estimate))
                    if gateway: self._side(self._guard_hit, cur, why)
                    return {"scope": f"guard:{name}", "key": b.get("key") or cur.get("team") or "", "limit_id": 0, "label": b.get("label") or name,
                            "tokens": b["limit"], "spent": b["spent"], "held": h, "estimate": estimate, "period": b.get("period") or "rolling",
                            "release": "reset" if spent_out or b["spent"] >= b["limit"] else "settle", "release_at": None, "limit_updated": None, "reason": why, "message": why}
        for name, fn in list(_guards.items()):  # a system's own budget (a Competition team's 24-hour budget); one that throws is UNKNOWN
            why = fn(cur)
            if why:
                if gateway: self._side(self._guard_hit, cur, why)
                return {"scope": f"guard:{name}", "key": cur.get("team") or "", "limit_id": 0, "label": name, "tokens": None, "spent": None,
                        "period": "rolling", "release": "reset", "release_at": None, "limit_updated": None, "reason": why, "message": why}
        return None

    @staticmethod
    def _side(fn, *a):
        d = getattr(_local, "deferred", None)
        if d is not None:  # inside admit's transaction: run after it commits (a failed write there would abort it on Postgres)
            d.append((fn, a)); return
        try: fn(*a)
        except Exception as e:  # noqa: BLE001 - an alert or a record never decides a call
            log.warning("agent core budget side effect: %s", e)

    def estimate_start(self, owner, model=None):
        """What the first model call of work that hasn't started will reserve at the gateway (D1, 2026-11-14): the gateway's own
        estimate_call for the run's model. A caller that can't name the model gets the estimate of the owner's most recently settled
        model (the best guess of the same function, never a different formula); with no history, the floor. A remaining
        disagreement with the gateway is bounded by the board's release backoff (mining_work.budget_hold_info)."""
        if not model:
            last = self.db.q("""SELECT model FROM ac_reservations WHERE owner_id=? AND state='settled' AND model IS NOT NULL AND model!=''
                                ORDER BY id DESC LIMIT 1""", (owner,), one=True)
            model = last and last["model"]
        return self.estimate_call(owner, model) if model else self.RESERVE_FLOOR

    def preflight(self, owner_id, system, agent_key=None, ref=None, team=None, corr=None, contract=None, model=None, estimate=None):
        """Would work in this scope be refused a model call right now? The same decision over() makes for a run (_verdict), for
        work that hasn't started (G5-2 budget safety, Owner decision 2026-11-11): the scope comes from the caller, not this
        thread's active run. Writes nothing. Returns None (allowed) or the refusal {decision: "REFUSE", scope, key, limit_id,
        label, tokens, spent, period, release ("reset" or "raise"), release_at, limit_updated, reason}. Alert-only limits never
        refuse. Raises when the decision can't be made (the module's preflight() turns that into UNKNOWN)."""
        if not owner_id: return None
        cur = {"owner": owner_id, "system": system, "agent": agent_key, "ref": ref, "team": team, "corr": corr or ref, "contract": contract, "id": None,
               "start": True}  # D1: a system's own budget is checked at its START line (a team's: 100%, not the in-flight HARD_PCT)
        if self.db.q("SELECT 1 FROM ac_reservations WHERE state='held' AND expires<? LIMIT 1", (time.time(),), one=True):
            with self.db.tx(): self._expire_due()  # Milestone 4: a dead holder's hold lapses here too (it writes nothing else)
        # D1 (2026-11-14 staging runaway, 9,264 empty runs): preflight checked with estimate 0 while the gateway adds the first
        # call's reservation, so in the band [limit - reservation, limit) preflight said ALLOW and the gateway REFUSE, forever.
        est = max(0, int(estimate)) if estimate is not None else self.estimate_start(owner_id, model)
        r = self._verdict(cur, estimate=est)
        if not r: return None
        r.pop("message", None)
        return {**r, "decision": "REFUSE", "checked_at": time.time()}

    def per_call_caps(self, owner_id, system, agent_key=None, ref=None, team=None, corr=None, contract=None):
        """The per-call limits work in this scope falls under, as {limit id: updated}: what a per-call refusal waits on changing."""
        cur = {"owner": owner_id, "system": system, "agent": agent_key, "ref": ref, "team": team, "corr": corr or ref, "contract": contract}
        return {L["id"]: L.get("updated") for L in self._matching(cur) if L["per_call"]}

    def _guard_hit(self, cur, why):
        """A system budget's refusal on the record (limit_id 0, once per run): counted with the scoped limits' refusals."""
        try:
            self.db.q("INSERT OR IGNORE INTO ac_limit_hits (limit_id, owner_id, run_id, corr, kind, spent, ts) VALUES (0,?,?,?,?,?,?)",
                      (cur["owner"], cur["id"], cur.get("corr"), "team_budget", 0, time.time()))
        except Exception as e:  # noqa: BLE001
            log.warning("agent core guard hit: %s", e)

    # ---------- scoped limits (G5): hard, checked at the gateway before every model call ----------
    def limits(self, owner_id, fresh=True):
        """The owner's limits, read from the database every time (G5-2 Blocker B). They used to be cached per process for
        CAP_CACHE seconds and dropped only by the process that changed them, so another replica enforced a lowered or deleted
        limit up to 30 s late. One indexed read (ac_limits' UNIQUE (owner_id, scope, key)) per check. `fresh` is kept for callers."""
        return self.db.q("SELECT * FROM ac_limits WHERE owner_id=? ORDER BY scope, key", (owner_id,))

    def _matching(self, cur):
        """The owner's limits this run falls under."""
        out = []
        for L in self.limits(cur["owner"]):
            s, k = L["scope"], L["key"]
            if (s == "global" or (s == "system" and k == cur.get("system")) or (s == "agent" and k == cur.get("agent"))
                    or (s == "mission" and k == cur.get("corr")) or (s == "team" and k and k == cur.get("team"))
                    or (s == "contract" and k in (cur.get("contract"), cur.get("ref")))):
                out.append(L)
        return out

    @staticmethod
    def _scope(L):
        """(where, args, since) of a limit's runs in its period."""
        where, args = {"global": ("1=1", ()), "system": ("system=?", (L["key"],)), "agent": ("agent_key=?", (L["key"],)),
                       "mission": ("corr=?", (L["key"],)), "team": ("team=?", (L["key"],)),
                       "contract": ("(contract=? OR ref=?)", (L["key"], L["key"]))}[L["scope"]]
        return where, args, _today() if L["period"] == "day" else _month() if L["period"] == "month" else None

    def unmetered_runs(self, owner_id, days=31):
        """Runs of this owner with unknown token use, newest first: what the Budgets page lists for an estimate."""
        rows = self.db.q("""SELECT id, system, kind, ref, title, model, login, tokens, started, finished, status FROM ac_runs
                            WHERE owner_id=? AND metering='unmetered' AND started>? ORDER BY id DESC LIMIT 200""", (owner_id, time.time() - days * 86400))
        for r in rows: r["floor"] = self.estimate_floor(r["id"])
        return rows

    ESTIMATE_FLOOR = 10_000  # never below this, nor below the average of the same model's last 50 metered runs

    def _floor_for_model(self, model):
        avg = self.db.q("""SELECT AVG(tokens) AS a FROM (SELECT tokens FROM ac_runs WHERE model=? AND COALESCE(metering,'')='' AND tokens>0
                           ORDER BY id DESC LIMIT 50) x""", (model,), one=True)["a"] if model else None
        return max(self.ESTIMATE_FLOOR, int(avg or 0))

    def estimate_floor(self, run_id):
        """The least an estimate for this run may be: the average of its model's last 50 metered runs, at least ESTIMATE_FLOOR. An
        unmetered Codex run did real work: an estimate of 1 would be zero again in all but name. The model is the run's, else (a
        failed run's row can have none: W2 gap) the model of the run's latest reservation."""
        r = self.db.q("SELECT model FROM ac_runs WHERE id=?", (run_id,), one=True)
        model = (r or {}).get("model")
        if not model:
            h = self.db.q("SELECT model FROM ac_reservations WHERE run_id=? AND model IS NOT NULL AND model!='' ORDER BY id DESC LIMIT 1", (run_id,), one=True)
            model = (h or {}).get("model")
        return self._floor_for_model(model)

    # ---------- D-036 (Proposed): a provisional charge for one timed-out CLI call ----------
    PROV_MAX_PER_DAY = 3     # more than this many provisional charges for a team in 24 h: the team falls back to D-025
    PROV_MAX_SHARE = 0.10    # or provisional charges above this share of its 24 h budget
    PROV_P99_FACTOR = 2      # P = max(floor, FACTOR x p99 of the model's settled calls, the call's reservation)
    PROV_DAYS = 7

    PROV_MIN_SAMPLES = 20    # fewer real samples than this: no p99, P = max(floor, reservation)

    def provisional_figure(self, model, reserved, owner=None):
        """P for a call on `model` that held `reserved`: the greater of the model's D-025 floor, 2 x the 99th percentile of its settled
        calls (this owner's, last 7 days, real usage only; at least PROV_MIN_SAMPLES of them, else no p99) and the reservation. Never 0."""
        rows = sorted(r["actual"] for r in self.db.q("""SELECT actual FROM ac_reservations WHERE model=? AND state='settled' AND actual IS NOT NULL
                                                         AND prov IS NULL AND owner_id=? AND settled>?""", (model or "", owner, time.time() - self.PROV_DAYS * 86400)))
        p99 = rows[max(0, -(-len(rows) * 99 // 100) - 1)] if len(rows) >= self.PROV_MIN_SAMPLES else 0
        return max(self._floor_for_model(model), self.PROV_P99_FACTOR * int(p99), int(reserved or 0))

    def _team_budget(self, cur):
        """The team's 24 h budget as its system registered it (the bucket's start_limit), or None."""
        best = None
        for fn in list(_buckets.values()):
            try:
                for b in fn(cur) or ():
                    best = b.get("start_limit") or b.get("limit") or best
            except Exception: pass  # noqa: BLE001 - no budget known: only the count decides
        return best

    def _breaker(self, cur, run_id, p):
        """Why the team may not take another provisional charge (D-025 applies instead), or None. Counts the provisional charges MADE for
        the team in the last 24 h (immutable prov_at / prov_p: a late real usage or a correction doesn't reset it); the new one would be one more."""
        team = cur.get("team")
        run = self.db.q("SELECT team, owner_id FROM ac_runs WHERE id=?", (run_id,), one=True) or {}
        team = team or run.get("team")
        w = "r.team=?" if team else "r.team IS NULL AND r.owner_id=?"
        a = (team,) if team else (run.get("owner_id"),)
        row = self.db.q(f"""SELECT COUNT(*) AS n, COALESCE(SUM(v.prov_p),0) AS tok FROM ac_reservations v JOIN ac_runs r ON r.id=v.run_id
                            WHERE v.prov_at>? AND {w}""", (time.time() - 86400, *a), one=True)
        if row["n"] + 1 > self.PROV_MAX_PER_DAY:
            return f"{row['n']} provisional charges for this team in the last 24 hours already (the limit is {self.PROV_MAX_PER_DAY})"
        budget = self._team_budget({**cur, "team": team}) if team else None
        if budget and row["tok"] + p > self.PROV_MAX_SHARE * budget:
            return f"provisional charges would be {row['tok'] + p:,} tokens, over {int(self.PROV_MAX_SHARE * 100)}% of the team's 24-hour budget of {budget:,}"
        return None

    def _provisional_charge(self, cur, rid, err):
        """The one timed-out call that held `rid`: charged at P now (state charged, actual P, prov provisional), its run counted P more
        and marked 'provisional'. Once: only a hold still held is charged. False = not charged (the breaker, or nothing held): D-025."""
        with self.db.tx():
            r = self.db.q("SELECT run_id, owner_id, model, COALESCE(reserved, estimate) AS reserved FROM ac_reservations WHERE id=? AND state='held'", (rid,), one=True)
            if not r: return False
            if not r["model"]:  # L1: as estimate_floor does: the run's model
                r["model"] = (self.db.q("SELECT model FROM ac_runs WHERE id=?", (r["run_id"],), one=True) or {}).get("model")
            p = self.provisional_figure(r["model"], r["reserved"], r["owner_id"])
            why = self._breaker(cur, r["run_id"], p)
            if why:
                self._audit(r["owner_id"], "system", "metering.provisional_refused", f"run:{r['run_id']}", f"D-025 applies: {why}")
                return False
            note = f"unverified: charged {p:,} (provisional, D-036) because the call's use is unknown ({str(err)[:100]})"
            if not self.db.q("UPDATE ac_reservations SET state='charged', actual=?, prov='provisional', prov_at=?, prov_p=?, settled=?, note=? WHERE id=? AND state='held' RETURNING id",
                             (p, time.time(), p, time.time(), note, rid), one=True): return False
            self.db.q("""UPDATE ac_runs SET tokens=tokens+?, metering=CASE WHEN metering IS NULL OR metering IN ('charged','estimated','provisional') THEN 'provisional' ELSE metering END
                         WHERE id=?""", (p, r["run_id"]))
            self._audit(r["owner_id"], "system", "metering.provisional", f"run:{r['run_id']}",
                        f"{p:,} tokens charged provisionally (D-036) to reservation #{rid} of {r['model'] or 'unknown model'}: estimated, unverified")
        return True

    def _audit(self, owner, actor, action, ref="", detail="", corr=None):
        """An audit row (io_audit, as orchestrator.audit writes it). Never decides anything: a failure is logged."""
        try:
            self.db.q("INSERT INTO io_audit (owner_id, ts, corr, actor, action, ref, detail) VALUES (?,?,?,?,?,?,?)",
                      (owner, time.time(), corr, actor, action, ref, str(detail)[:600]))
        except Exception as e:  # noqa: BLE001
            log.warning("agent core audit: %s", e)

    def provisional_runs(self, owner_id, days=31):
        """Runs of this owner charged provisionally and not yet corrected: 'estimated, unverified' (D-036)."""
        rows = self.db.q("""SELECT id, system, kind, ref, title, model, login, tokens, started, finished, status FROM ac_runs
                            WHERE owner_id=? AND metering='provisional' AND started>? ORDER BY id DESC LIMIT 200""", (owner_id, time.time() - days * 86400))
        for r in rows:
            r["label"] = "estimated, unverified"
            r["provisional_tokens"] = self.db.q("SELECT COALESCE(SUM(actual),0) AS n FROM ac_reservations WHERE run_id=? AND prov='provisional'", (r["id"],), one=True)["n"]
        return rows

    def estimate(self, owner_id, run_id, tokens, by, note=""):
        """A person's estimate for an unmetered run (D-025): its tokens become the counted tokens plus the estimate, metering
        'estimated', so the budget can be checked again. Refused for a run that isn't this owner's or isn't unmetered, and below the
        floor (estimate_floor). The run's unmetered hold(s) are settled with it (the figure on the reservation, once: W2 gap). A run
        charged provisionally (D-036) is corrected instead: the person's figure replaces the provisional one (up or down, a note
        required)."""
        if not isinstance(tokens, int) or tokens < 1: raise ValueError("An estimate is a whole number of tokens, at least 1.")
        with self.db.tx():
            run = self.db.q("SELECT id, metering FROM ac_runs WHERE id=? AND owner_id=?", (run_id, owner_id), one=True)
            if run and run["metering"] != "unmetered" and self.db.q("SELECT 1 FROM ac_reservations WHERE run_id=? AND prov IN ('provisional','corrected','corrected_real')", (run_id,), one=True):
                return self._correct(owner_id, run_id, tokens, by, note)
            floor = self.estimate_floor(run_id)
            if tokens < floor: raise ValueError(f"At least {floor:,} tokens: the average of this model's metered runs (and never under {self.ESTIMATE_FLOOR:,}).")
            r = self.db.q("UPDATE ac_runs SET tokens=tokens+?, metering='estimated' WHERE id=? AND owner_id=? AND metering='unmetered' RETURNING id, tokens",
                          (tokens, run_id, owner_id), one=True)
            if not r: raise LookupError("No such unmetered run of yours.")
            held = self.db.q("SELECT id FROM ac_reservations WHERE run_id=? AND state='unmetered' ORDER BY id", (run_id,))
            now = time.time()
            for k, h in enumerate(held):
                if k == len(held) - 1:
                    self.db.q("UPDATE ac_reservations SET state='settled', actual=?, settled=?, note=?, prov='estimated' WHERE id=? AND state='unmetered'",
                              (tokens, now, f"a person's estimate (D-025) by {by}", h["id"]))
                else:
                    self.db.q("UPDATE ac_reservations SET state='merged', actual=0, settled=?, note=?, prov='estimated' WHERE id=? AND state='unmetered'",
                              (now, f"settled with the run's estimate by {by}", h["id"]))
            if held:  # A1: this figure is its own group (fig_id), so a provisional charge later on the same run can't mis-anchor it
                self.db.q(f"UPDATE ac_reservations SET fig_id=? WHERE id IN ({','.join('?' * len(held))})", (held[-1]["id"], *[h["id"] for h in held]))
            # L5: the run was charged provisionally before it went unmetered: the person's figure replaces that charge, never stacks on it
            old = self.db.q("SELECT COALESCE(SUM(actual),0) AS n FROM ac_reservations WHERE run_id=? AND owner_id=? AND prov='provisional' AND state='charged'", (run_id, owner_id), one=True)["n"]
            if old:
                pids = [x["id"] for x in self.db.q("SELECT id FROM ac_reservations WHERE run_id=? AND owner_id=? AND prov='provisional' AND state='charged' ORDER BY id", (run_id, owner_id))]
                fig = held[-1]["id"] if held else pids[-1]
                if not held:  # A1: no unmetered hold carries the figure: the latest provisional row does (late real usage then counts max(figure, real))
                    self.db.q("UPDATE ac_reservations SET state='settled', actual=?, prov='corrected', settled=?, note=? WHERE id=? AND state='charged' AND prov='provisional'",
                              (tokens, now, f"a person's estimate (D-025) by {by} replaced the provisional charge", fig))
                self.db.q("UPDATE ac_reservations SET state='merged', actual=0, prov='corrected', settled=?, note=? WHERE run_id=? AND owner_id=? AND prov='provisional' AND state='charged'",
                          (now, f"replaced by {by}'s estimate of the run", run_id, owner_id))
                group = pids + [h["id"] for h in held]   # A1: the holds this figure covers point at the row that carries it
                self.db.q(f"UPDATE ac_reservations SET fig_id=? WHERE id IN ({','.join('?' * len(group))})", (fig, *group))
                r = self.db.q("UPDATE ac_runs SET tokens=MAX(0, tokens-?) WHERE id=? RETURNING id, tokens"
                              if not hasattr(self.db.db, "begin") else "UPDATE ac_runs SET tokens=GREATEST(0, tokens-?) WHERE id=? RETURNING id, tokens", (old, run_id), one=True)
                self._audit(owner_id, by, "metering.correct", f"run:{run_id}", f"provisional {old:,} tokens replaced by a D-025 estimate of {tokens:,}")
        r["path"] = "estimate"
        return r

    PROV_CORRECT_MAX_FACTOR = 10   # A1: a correction above 10 x max(the provisional figure first charged, the floor) is refused as a likely typo

    def _d036_run(self, rows):
        """True when a run of these reservations was ever charged provisionally (D-036): its late real usage takes the max(person, real) path.
        Runs never charged provisionally keep the D-025 path unchanged (switch off: byte-identical behaviour)."""
        ids = sorted({r["run_id"] for r in rows if r["run_id"]})
        if not ids: return False
        return bool(self.db.q(f"SELECT 1 FROM ac_reservations WHERE run_id IN ({','.join('?' * len(ids))}) AND prov_at IS NOT NULL LIMIT 1", ids, one=True))

    def _late_after_person(self, rows, actual):
        """D-036 A1 (delegated decision: a person's figure is a floor, never a cap): real usage reported for holds a person's figure
        covered (a correction, or a D-025 estimate on a run D-036 touched) is counted per figure group (fig_id) as max(the figure,
        late_real), once per hold. Invariant: a group's late_real is never below the real usage that can be that group's. A report
        naming holds of several groups can't be split, so its whole figure is added to each named group's late_real: that may
        over-count, never under-count, over any later reports and re-corrections. Inside settle's transaction; returns tokens added."""
        cover = [r for r in rows if r["state"] in ("settled", "merged") and r["prov"] in ("estimated", "corrected")]
        if not cover: return 0
        ids = [r["id"] for r in cover]
        claimed = {x["id"] for x in self.db.q(f"""UPDATE ac_reservations SET prov=prov || '_real' WHERE id IN ({','.join('?' * len(ids))})
                                                AND prov IN ('estimated','corrected') RETURNING id""", ids)}
        if not claimed: return 0   # each hold's real usage counts once; only the holds that reported change label
        groups = []
        for x in self.db.q(f"SELECT id, run_id, state, fig_id FROM ac_reservations WHERE id IN ({','.join('?' * len(claimed))}) ORDER BY id", sorted(claimed)):
            g = x["fig_id"] or (x["id"] if x["state"] == "settled" else None)
            if g is None:  # a merged row written before fig_id existed: the run's latest figure row
                g = (self.db.q("""SELECT MAX(id) AS id FROM ac_reservations WHERE run_id=? AND state='settled'
                                  AND prov IN ('estimated','corrected','estimated_real','corrected_real')""", (x["run_id"],), one=True) or {}).get("id")
            if g and g not in groups: groups.append(g)
        add_all = 0
        for g in groups:
            a = self.db.q("SELECT id, run_id, owner_id, actual, COALESCE(late_real,0) AS lr FROM ac_reservations WHERE id=? AND state='settled'", (g,), one=True)
            if not a: continue
            before, lr = int(a["actual"] or 0), int(a["lr"]) + actual
            after = max(before, lr)    # = max(figure, real so far): before is max(figure, earlier real) and late_real only grows
            self.db.q("UPDATE ac_reservations SET actual=?, late_real=?, note=? WHERE id=?",
                      (after, lr, f"real usage {lr:,} reported after a person's figure" + (" (a report naming several groups counts on each)" if len(groups) > 1 else "")
                       + f": counted max({before:,}, {lr:,})", a["id"]))
            add = after - before
            if add: self.db.q("UPDATE ac_runs SET tokens=tokens+? WHERE id=?", (add, a["run_id"]))
            add_all += add
            self._audit(a["owner_id"], "system", "metering.real_after_person", f"run:{a['run_id']}",
                        f"real usage {actual:,} (group total {lr:,}) came after a person's figure: counted {after:,} (+{add:,})"
                        + (f"; the report named {len(groups)} groups and counts on each" if len(groups) > 1 else ""))
        return add_all

    def _correct(self, owner_id, run_id, tokens, by, note):
        """D-036: a person's figure for a provisionally charged run. With provisional charges open, it replaces them (their sum) and
        becomes a new figure group (fig_id: the latest of them carries the figure, the others merge into it). Otherwise it re-corrects the
        run's latest figure group (a correction, or a D-025 estimate that replaced P): the figure changes, its real usage stays. The run's
        tokens move by the difference, once; repeating it replaces again, never adds. A1 (delegated, conservative): the figure is at
        least the run's D-025 floor (estimate_floor, as a D-025 estimate) and at most PROV_CORRECT_MAX_FACTOR x max(the provisional
        figures charged for the group's calls, that floor); what is counted is never below the real usage reported for the group. Audited."""
        if not (note or "").strip(): raise ValueError("A correction needs a note: why the figure is what it is.")
        rows = self.db.q("SELECT id, actual, prov_p FROM ac_reservations WHERE run_id=? AND owner_id=? AND prov='provisional' AND state='charged' ORDER BY id DESC", (run_id, owner_id))
        if rows:
            first, old, lr, p0 = rows[0], sum(x["actual"] or 0 for x in rows), 0, sum(x["prov_p"] or 0 for x in rows)
        else:
            first = self.db.q("""SELECT id, actual, fig_id, COALESCE(late_real,0) AS lr FROM ac_reservations WHERE run_id=? AND owner_id=? AND state='settled'
                                 AND prov IN ('corrected','corrected_real','estimated','estimated_real') AND (fig_id=id OR fig_id IS NULL) ORDER BY id DESC LIMIT 1""",
                              (run_id, owner_id), one=True)
            if not first: raise LookupError("No such unmetered run of yours.")
            old, lr = int(first["actual"] or 0), int(first["lr"] or 0)
            p0 = (self.db.q("SELECT COALESCE(SUM(prov_p),0) AS n FROM ac_reservations WHERE (fig_id=? OR id=?) AND prov_at IS NOT NULL", (first["id"], first["id"]), one=True)["n"]
                  if first["fig_id"] else  # A1 G4: a group written before fig_id existed: the run's provisional figures
                  self.db.q("SELECT COALESCE(SUM(prov_p),0) AS n FROM ac_reservations WHERE run_id=? AND prov_at IS NOT NULL", (run_id,), one=True)["n"])
        floor = self.estimate_floor(run_id)
        ceil = self.PROV_CORRECT_MAX_FACTOR * max(int(p0 or 0), floor)
        if tokens < floor: raise ValueError(f"At least {floor:,} tokens: the floor a person's estimate has (the average of this model's metered runs, never under {self.ESTIMATE_FLOOR:,}).")
        if tokens > ceil: raise ValueError(f"At most {ceil:,} tokens ({self.PROV_CORRECT_MAX_FACTOR} x the provisional figure or the floor): a larger figure is likely a typo.")
        now, counted = time.time(), max(tokens, lr)   # real usage already reported for the group is never undercut
        what = f"corrected by {by} from {old:,} to {tokens:,}" + (f" (counted {counted:,}: real usage reported)" if counted != tokens else "") + f": {note[:150]}"
        # guarded: only rows still in the state read; the token delta follows only if the figure row matched (M4b)
        if rows:
            ok = self.db.q("UPDATE ac_reservations SET state='settled', actual=?, prov='corrected', fig_id=id, settled=?, note=? WHERE id=? AND state='charged' AND prov='provisional' RETURNING id",
                           (counted, now, what, first["id"]), one=True)
            for x in rows[1:] if ok else ():
                self.db.q("UPDATE ac_reservations SET state='merged', actual=0, prov='corrected', fig_id=?, settled=?, note=? WHERE id=? AND state='charged' AND prov='provisional'",
                          (first["id"], now, f"settled with #{first['id']}", x["id"]))
        else:
            ok = self.db.q("UPDATE ac_reservations SET actual=?, settled=?, note=? WHERE id=? AND state='settled' AND COALESCE(late_real,0)=? RETURNING id",
                           (counted, now, what, first["id"], lr), one=True)
        if not ok: raise LookupError("No such unmetered run of yours.")
        r = self.db.q("UPDATE ac_runs SET tokens=MAX(0, tokens+?), metering='estimated' WHERE id=? AND owner_id=? RETURNING id, tokens"
                      if not hasattr(self.db.db, "begin") else "UPDATE ac_runs SET tokens=GREATEST(0, tokens+?), metering='estimated' WHERE id=? AND owner_id=? RETURNING id, tokens",
                      (counted - old, run_id, owner_id), one=True)
        self._audit(owner_id, by, "metering.correct", f"run:{run_id}", f"provisional {old:,} tokens corrected to {tokens:,} (D-036)" + (f", counted {counted:,} (real usage reported)" if counted != tokens else "") + f": {note[:200]}")
        r["path"] = "correct"
        return r

    def _spent(self, cur, L):
        where, args, since = self._scope(L)
        day = " AND started>=?" if since is not None else ""
        return self.db.q(f"SELECT COALESCE(SUM(tokens), 0) AS n FROM ac_runs WHERE owner_id=? AND {where}{day}",
                         (cur["owner"], *args, *((since,) if day else ())), one=True)["n"]

    def _hit(self, cur, L, spent, kind):
        """A refusal on the record (once per limit, run and kind): the Budgets card and the orchestrator's audit read these."""
        try:
            self.db.q("INSERT OR IGNORE INTO ac_limit_hits (limit_id, owner_id, run_id, corr, kind, spent, ts) VALUES (?,?,?,?,?,?,?)",
                      (L["id"], cur["owner"], cur["id"], cur.get("corr"), kind, spent, time.time()))
        except Exception as e:  # noqa: BLE001 - the record never decides the refusal
            log.warning("agent core limit hit: %s", e)

    def call_cap(self):
        """The smallest per-call limit this thread's run falls under (output tokens are capped at it), or None."""
        cur = getattr(_local, "run", None)
        if not cur or not cur.get("owner"): return None
        if "call_cap" in cur: return cur["call_cap"]  # read by over() for this very call
        caps = [L["per_call"] for L in self._matching(cur) if L["per_call"]]
        return min(caps) if caps else None

    def set_limit(self, owner_id, scope, key, tokens=None, period="total", per_call=None, label="", origin="manual", by="", warn_pct=None, mode="stop"):
        if scope not in SCOPES: raise ValueError(f"Unknown scope {scope}.")
        if period not in ("day", "month", "total"): raise ValueError("The period is day, month or total.")
        if mode not in ("stop", "alert"): raise ValueError("A limit stops the work or only alerts.")
        if warn_pct is not None and not 1 <= int(warn_pct) <= 100: raise ValueError("Warn at 1 to 100 percent of the limit.")
        key = "*" if scope == "global" else str(key or "").strip()[:120]
        if not key: raise ValueError("Say what the limit is for.")
        self.db.q("""INSERT INTO ac_limits (owner_id, scope, key, label, tokens, period, per_call, origin, updated, by_user, warn_pct, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(owner_id, scope, key) DO UPDATE SET label=excluded.label, tokens=excluded.tokens, period=excluded.period,
                     per_call=excluded.per_call, origin=excluded.origin, updated=excluded.updated, by_user=excluded.by_user,
                     warn_pct=excluded.warn_pct, mode=excluded.mode""",
                  (owner_id, scope, key, (label or "")[:120], int(tokens) if tokens else None, period, int(per_call) if per_call else None, origin, time.time(), by,
                   int(warn_pct) if warn_pct else None, mode))
        return self.db.q("SELECT * FROM ac_limits WHERE owner_id=? AND scope=? AND key=?", (owner_id, scope, key), one=True)

    def drop_limit(self, owner_id, lid):
        n = self.db.q("DELETE FROM ac_limits WHERE id=? AND owner_id=? RETURNING id", (lid, owner_id))
        return bool(n)

    def limit_status(self, owner_id):
        """Every limit of the owner's with what its scope spent (today for daily ones) and the refusals it made in 7 days."""
        hits = {r["limit_id"]: r["n"] for r in self.db.q("SELECT limit_id, COUNT(*) n FROM ac_limit_hits WHERE owner_id=? AND ts>? GROUP BY limit_id",
                                                         (owner_id, time.time() - 7 * 86400))}
        out = []
        for L in self.limits(owner_id, fresh=True):
            spent = self._spent({"owner": owner_id}, L)
            warn = L.get("warn_pct") or self._budget_row(owner_id)["warn_pct"]
            used = round(100 * spent / L["tokens"]) if L["tokens"] else None
            out.append({**L, "scope_label": SCOPES.get(L["scope"], L["scope"]), "spent": spent, "blocked_7d": hits.get(L["id"], 0),
                        "used_pct": used, "warn_at": warn, "mode": L.get("mode") or "stop",
                        "level": None if used is None else "limit" if used >= 100 else "warn" if used >= warn else None})
        return out

    def policy(self, owner_id):
        """The owner's spending boundary: "capped" (a daily limit), "scoped" (only scoped limits), "unlimited" (no limit, chosen
        knowingly: when and by whom) or "unset" (no limit and no decision: the Control Hub and Intelligence layers ask for one)."""
        b = self._budget_row(owner_id)
        n = self.db.q("SELECT COUNT(*) n FROM ac_limits WHERE owner_id=? AND tokens>0", (owner_id,), one=True)["n"]
        state = "capped" if b["cap"] else "scoped" if n else "unlimited" if b["unlimited"] else "unset"
        return {"state": state, "cap": b["cap"], "limits": n, "unlimited_at": b["unlimited"], "unlimited_by": b["unlimited_by"]}

    def set_unlimited(self, owner_id, on, by):
        """Run without a daily cap, acknowledged (on), or take the acknowledgement back (off): it never sets or removes a limit."""
        self.db.q("""INSERT INTO ac_budget (owner_id, unlimited, unlimited_by, updated, by_user) VALUES (?,?,?,?,?)
                     ON CONFLICT(owner_id) DO UPDATE SET unlimited=excluded.unlimited, unlimited_by=excluded.unlimited_by, updated=excluded.updated,
                     by_user=excluded.by_user""", (owner_id, time.time() if on else None, by if on else None, time.time(), by))
        self.caps.pop(owner_id, None)
        return self.policy(owner_id)

    def coverage(self, owner_id, since):
        """How much of the spend is accounted for: tokens of finished runs with a recorded cost, with a model (priced at list price
        elsewhere), with neither (unpriceable), and finished runs that recorded no token count at all."""
        r = self.db.q("""SELECT COALESCE(SUM(tokens),0) tok, COALESCE(SUM(CASE WHEN cost IS NOT NULL THEN tokens END),0) costed,
                                COALESCE(SUM(CASE WHEN cost IS NULL AND model IS NOT NULL AND model!='' THEN tokens END),0) modeled,
                                SUM(CASE WHEN COALESCE(tokens,0)=0 THEN 1 ELSE 0 END) silent, COUNT(*) n
                         FROM ac_runs WHERE owner_id=? AND started>? AND status NOT IN ('running') AND kind!='earlier'""", (owner_id, since), one=True) or {}
        tok = r.get("tok") or 0
        priced = (r.get("costed") or 0) + (r.get("modeled") or 0)
        return {"tokens": tok, "recorded_cost": r.get("costed") or 0, "priced_by_model": r.get("modeled") or 0, "unpriced": max(0, tok - priced),
                "runs": r.get("n") or 0, "runs_without_tokens": r.get("silent") or 0, "priced_pct": round(100 * priced / tok, 1) if tok else None}

    def set_cap(self, owner_id, tokens, by):
        self.db.q("""INSERT INTO ac_budget (owner_id, daily_tokens, updated, by_user) VALUES (?,?,?,?)
                     ON CONFLICT(owner_id) DO UPDATE SET daily_tokens=excluded.daily_tokens, updated=excluded.updated, by_user=excluded.by_user""",
                  (owner_id, tokens or None, time.time(), by))
        self.caps.pop(owner_id, None)

    # ---------- model router ----------
    def pool(self, owner_id):
        """{"pool": [{model, tier, price}] as the owner set them, "weights": name}. The first read for an owner copies what the
        Workforce kept before the pool was shared (its wf_settings row), once."""
        r = self.db.q("SELECT pool, weights FROM ac_pool WHERE owner_id=?", (owner_id,), one=True)
        if r: return {"pool": json.loads(r["pool"] or "[]"), "weights": r["weights"] or "balanced"}
        pool, weights = [], "balanced"
        if self._has("wf_settings"):
            w = self.db.q("SELECT settings FROM wf_settings WHERE user_id=?", (owner_id,), one=True)
            s = json.loads(w["settings"]) if w and w["settings"] else {}
            pool, weights = s.get("pool") or [], s.get("weights") or "balanced"
        self.db.q("INSERT OR IGNORE INTO ac_pool (owner_id, pool, weights, updated, by_user) VALUES (?,?,?,?,?)",
                  (owner_id, json.dumps(pool), weights, time.time(), "copied from Workforce settings"))
        return {"pool": pool, "weights": weights}

    def set_pool(self, owner_id, pool, weights, by=""):
        self.db.q("""INSERT INTO ac_pool (owner_id, pool, weights, updated, by_user) VALUES (?,?,?,?,?)
                     ON CONFLICT(owner_id) DO UPDATE SET pool=excluded.pool, weights=excluded.weights, updated=excluded.updated, by_user=excluded.by_user""",
                  (owner_id, json.dumps(pool or []), weights or "balanced", time.time(), by))

    def score(self, ref, value, only_unscored=False, kinds=None):
        """An evaluator's or verifier's score (0-100) for the finished run(s) with `ref` (of these kinds only, when given): what
        the router learns quality from."""
        if value is None: return
        v = max(0.0, min(100.0, float(value)))
        extra = (" AND score IS NULL" if only_unscored else "") + (f" AND kind IN ({','.join('?' * len(kinds))})" if kinds else "")
        self.db.q(f"UPDATE ac_runs SET score=? WHERE ref=? AND status!='running'{extra}", (v, ref, *(kinds or ())))

    def stats(self, owner_id, system):
        """rank()'s statistics for one system's runs: per (model, kind) and per model."""
        rows = self.db.q("""SELECT model, kind AS task, COUNT(*) n, AVG(NULLIF(tokens,0)) tokens, AVG(finished-started) latency,
                                   SUM(status='failed') failed, COUNT(score) scored, COALESCE(SUM(score),0) score_sum FROM ac_runs
                            WHERE owner_id=? AND system=? AND model IS NOT NULL AND status IN ('done','failed','stopped') AND finished IS NOT NULL
                                  AND started>=? GROUP BY model, kind""", (owner_id, system, time.time() - ROUTE_DAYS * 86400))
        return model_router.stats_rows(rows)

    def route(self, llm, owner_id, system, kind, avoid=(), min_tier=None, pressure=False, stats=None):
        """(provider:model, decision) for an "auto" run, or None when there's nothing to route (no pool, or none of its
        providers connected): the caller then runs on the default model. stats: a system's own run statistics
        (model_router.stats_rows) in place of the ledger's, for a system that keeps its runs elsewhere."""
        shared = self.pool(owner_id)
        pool = model_router.effective(shared["pool"])
        live = [p for p in pool if llm.configured(p["model"].partition(":")[0])]
        if not live: return None
        notes = [f"{len(pool) - len(live)} pool model(s) skipped: their provider isn't connected"] if len(live) < len(pool) else []
        # D-038 B1: a model whose plan login (the one this owner's work would run on) waits for its usage limit is skipped, but
        # only while another live model still meets the tier rule; otherwise routing is as before and the run waits as today
        waiting = {p["model"]: u for p in live if (u := _plan_wait(p["model"], owner_id))}
        skipped = []
        if waiting:
            need = model_router.MIN_TIER.get(kind, 1) if min_tier is None else min_tier
            rest = [p for p in live if p["model"] not in waiting]
            if any(p["tier"] >= need for p in rest):
                live, skipped = rest, [{"model": m, "until": round(u)} for m, u in waiting.items()]
                notes.append("skipped while the plan waits for its usage limit: " + ", ".join(
                    f"{m} (until {time.strftime('%H:%M', time.gmtime(u))} UTC)" for m, u in waiting.items()))
            else:
                notes.append("every model that meets the tier rule waits for its plan's usage limit: routed as before")
        got = model_router.rank(live, self.stats(owner_id, system) if stats is None else stats, kind, shared["weights"], avoid=avoid, min_tier=min_tier,
                                pressure=pressure, notes=notes)
        if skipped: got[1]["skipped"] = skipped
        return got

    # ---------- registry ----------
    def _has(self, table):
        return bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,), one=True))

    def _sources(self):
        """(system, rows) for every registry, each row (local_id, owner_id, name, role, place, status)."""
        q, out = self.db.q, []
        if self._has("custom_agents"):
            out.append(("hub", [(r["id"], r["owner_id"], r["name"], r["role"], "", r["status"]) for r in q("SELECT id, owner_id, name, role, status FROM custom_agents")]))
        if self.hub is not None:
            out.append(("builtin", [(b["id"], 0, b["name"], b.get("role") or "", "AXoR", "live") for b in self.hub.builtins.values()]))
        if self._has("wf_agents"):
            out.append(("workforce", [(r["id"], r["user_id"], r["name"], r["title"] or r["role"], r["team"], r["status"])
                                      for r in q("SELECT id, user_id, name, title, role, team, status FROM wf_agents")]))
        if self._has("co_agents") and self._has("co_company"):
            out.append(("company", [(r["id"], r["user_id"], r["name"], r["title"] or r["category"], r["division"] or "", r["status"]) for r in q(
                """SELECT a.id, c.user_id, a.name, a.title, a.category, d.name AS division, a.status FROM co_agents a JOIN co_company c ON c.id=a.company_id
                   LEFT JOIN co_divisions d ON d.id=a.division_id""")]))
        if self._has("mw_agents") and self._has("mh_campaigns"):
            out.append(("teams", [(r["id"], r["user_id"], r["name"], r["title"] or r["role"], f"#{r['number'] or ''} {r['comp'] or ''}".strip(),
                                   "active" if r["active"] else "off") for r in q(
                """SELECT a.id, c.user_id, a.name, a.title, a.role, a.active, w.number, w.name AS comp FROM mw_agents a JOIN mw_comps w ON w.id=a.comp_id
                   JOIN mh_campaigns c ON c.id=w.campaign_id""")]))
        if self._has("mb_agents") and self._has("mb_flows"):
            out.append(("workflow", [(r["id"], r["user_id"], r["name"], (r["role"] or "").capitalize(), f"Workflow #{r['flow_id']}", "active" if r["on_team"] else "off")
                                     for r in q("SELECT a.id, f.user_id, a.name, a.role, a.flow_id, a.on_team FROM mb_agents a JOIN mb_flows f ON f.id=a.flow_id")]))
        try:
            from . import hq
            st = {r["id"]: r["status"] for r in q("SELECT id, status FROM hq_agents")} if self._has("hq_agents") else {}
            out.append(("hq", [(a["id"], 0, a["name"], a.get("title") or "", hq.TEAMS.get(a.get("team"), {}).get("name", "Headquarters"), st.get(a["id"]) or "on")
                               for a in hq.STAFF + hq.FIELD]))
        except Exception as e:  # noqa: BLE001 - one registry never stops the others
            log.warning("agent core: hq registry: %s", e)
        return out

    def sync(self, force=False):
        """Mirrors every system's agents into ac_agents. An agent gone from its system is kept, as status 'gone'."""
        if not force and time.time() - self.synced < SYNC: return
        with self.lock:
            now, seen = time.time(), set()
            for system, rows in self._sources():
                for local, owner, name, role, place, status in rows:
                    key = f"{system}:{local}"
                    seen.add(key)
                    self.db.q("""INSERT INTO ac_agents (key, system, local_id, owner_id, name, role, place, status, seen, created) VALUES (?,?,?,?,?,?,?,?,?,?)
                                 ON CONFLICT(key) DO UPDATE SET owner_id=excluded.owner_id, name=excluded.name, role=excluded.role, place=excluded.place,
                                 status=excluded.status, seen=excluded.seen""",
                              (key, system, str(local), owner, name, role or "", place or "", status or "", now, now))
            for r in self.db.q("SELECT key FROM ac_agents WHERE status!='gone'"):
                if r["key"] not in seen: self.db.q("UPDATE ac_agents SET status='gone', seen=? WHERE key=?", (now, r["key"]))
            self.db.q("DELETE FROM ac_runs WHERE started<? AND status!='running'", (now - KEEP * 86400,))
            self.synced = now

    # ---------- what readers get ----------
    def runs(self, owner_ids, since, statuses=None, limit=200):
        marks = ",".join("?" * len(owner_ids))
        extra = f" AND status IN ({','.join('?' * len(statuses))})" if statuses else ""
        return self.db.q(f"SELECT * FROM ac_runs WHERE owner_id IN ({marks}) AND (started>=? OR status='running'){extra} ORDER BY id DESC LIMIT ?",
                         (*owner_ids, since, *(statuses or ()), limit))

    def tokens_by_system(self, owner_ids, since):
        marks = ",".join("?" * len(owner_ids))
        return {r["system"]: r["n"] for r in self.db.q(f"SELECT system, SUM(tokens) n FROM ac_runs WHERE owner_id IN ({marks}) AND started>=? GROUP BY system",
                                                     (*owner_ids, since))}

    def agent_stats(self, owner_ids, since):
        """{agent_key: {"tokens": n, "last": ts, "running": bool, "failed": bool}} from the ledger."""
        marks, out = ",".join("?" * len(owner_ids)), {}
        for r in self.db.q(f"""SELECT agent_key, SUM(tokens) n, MAX(started) t, MAX(status='running') run, MAX(status IN ('failed','lost') AND started>=?) bad
                               FROM ac_runs WHERE owner_id IN ({marks}) AND agent_key IS NOT NULL AND (started>=? OR status='running') GROUP BY agent_key""",
                           (time.time() - 86400, *owner_ids, since)):
            out[r["agent_key"]] = {"tokens": r["n"] or 0, "last": r["t"], "running": bool(r["run"]), "failed": bool(r["bad"])}
        return out

    def outcomes(self, owner_id, since, until=None):
        """Every run started in (since, until] in exactly one state, so the parts add up to `total`: success, failed, timeout,
        cancelled (or stopped by a person), restarted (lost to a server restart), running (not finished yet) and other (a
        status this ledger doesn't know). The Command Center and the Intelligence layers count runs with this one definition."""
        cond, args = "owner_id=? AND started>?" + (" AND started<=?" if until else ""), (owner_id, since, *((until,) if until else ()))
        out = {k: 0 for k in ("success", "failed", "timeout", "cancelled", "restarted", "running", "other")}
        for r in self.db.q(f"SELECT status, COUNT(*) n FROM ac_runs WHERE {cond} AND status NOT IN ('failed','error') GROUP BY status", args):
            out[terminal_state(r["status"], "") or "other"] += r["n"]
        for r in self.db.q(f"SELECT error FROM ac_runs WHERE {cond} AND status IN ('failed','error')", args):
            out[terminal_state("failed", r["error"])] += 1
        out["total"] = sum(out.values())
        out["finished"] = out["total"] - out["running"]
        judged = out["success"] + out["failed"] + out["timeout"] + out["restarted"]  # a person's cancel is neither
        out["success_pct"] = round(100 * out["success"] / judged, 1) if judged else None
        return out

    def budget(self, owner_id):
        return {"daily_tokens": self.cap(owner_id), "today": self.spent_today(owner_id), "limits": self.limit_status(owner_id),
                "policy": self.policy(owner_id), "coverage": self.coverage(owner_id, time.time() - 86400),
                "by_system": [{"system": s, "label": SYSTEMS.get(s, s), "tokens": n} for s, n in
                              sorted(self.tokens_by_system((owner_id,), _today()).items(), key=lambda x: -(x[1] or 0)) if n]}


WARN_PCT = 80   # a limit warns from this share used, unless its owner or the limit itself says otherwise
_notifier = None  # fn(owner_id, title, body, urgent): main.py points it at the push service
_push_on = lambda: bool(_notifier)  # noqa: E731 - whether a push can go out at all (a push server is set up)


def set_notifier(fn, enabled=None):
    global _notifier, _push_on
    _notifier = fn
    _push_on = enabled or (lambda: bool(_notifier))


def _notify(owner_id, title, body, urgent):
    try: _notifier(owner_id, title, body, urgent)
    except Exception as e:  # noqa: BLE001 - a push is a courtesy; the alert is on the record
        log.warning("agent core alert push: %s", e)


TIMEOUT = re.compile(r"\btime[ds]? ?out\b|timeout|deadline exceeded|took too long", re.I)


def terminal_state(status, error):
    """A run's one final state (Core.outcomes): success, failed, timeout, cancelled, restarted; None while it runs."""
    s = (status or "").lower()
    if s == "running": return "running"
    if s == "done": return "success"
    if s in ("cancelled", "stopped"): return "cancelled"
    if s == "lost" or "server restart" in (error or "").lower(): return "restarted"
    if s in ("failed", "error"): return "timeout" if TIMEOUT.search(error or "") else "failed"
    return None


# ---------- module-level: no-ops until main.py calls init(), so a system works the same without the core ----------
def init(db, hub=None):
    global _core
    _core = Core(db, hub)
    return _core

def get(): return _core

def _safe(name, *a, **kw):
    """The ledger's calls never stop a run. Not for budget decisions: over(), preflight() and per_call_caps() below fail closed."""
    if _core is None: return None
    try: return getattr(_core, name)(*a, **kw)
    except Exception as e:  # noqa: BLE001 - the ledger never stops a run
        log.warning("agent core %s: %s", name, e)
        return None

# ---------- G5-2 Blocker A: budget decisions in three states ----------
# ALLOW: verified, nothing refuses (preflight None; over() None). REFUSE: a hard limit is reached (preflight's refusal dict;
# over()'s reason). UNKNOWN: the decision couldn't be made (the database, a guard that throws, a ledger row that couldn't be
# opened): preflight gives unknown(), over() gives VERIFY_STOP, and nothing starts or calls until a fresh check says ALLOW.
# "token budget" in the text puts it in the budget class everywhere (orchestrator.AUTOLOOP_PATTERNS, MISSION_PATTERNS,
# decide: hold, not the agent's fault, no retry). The text carries no exception text: a "connection timed out" or "usage limit"
# in it would be read as another class. The error is logged, and kept in the hold (preflight) for the user to see.
VERIFY = "The token budget couldn't be verified"
VERIFY_STOP = (VERIFY + " before this model call, so the call wasn't made. The work waits for a successful check; "
               "it is not counted against the agent (Intelligence layers → Budgets).")


def unknown(error):
    """An UNKNOWN budget decision: what a verification hold records (error, when) and shows."""
    return {"decision": "UNKNOWN", "scope": "verification", "key": "", "limit_id": None, "label": "Budget verification", "tokens": None,
            "spent": None, "period": None, "release": "verify", "release_at": None, "limit_updated": None,
            "error": f"{type(error).__name__}: {error}"[:300] if isinstance(error, BaseException) else str(error or "")[:300], "checked_at": time.time(),
            "reason": VERIFY + ": the work waits for a successful check."}


def is_unknown(r): return bool(r) and r.get("decision") == "UNKNOWN"


class UnmeteredSpend(Exception):
    """_verdict: a run in a limited scope has unknown token use (D-025). Callers turn it into UNKNOWN: the work waits, never let through."""


def budget_stop(err):
    """Whether a model call was stopped by a budget (REFUSE) or an unverifiable one (UNKNOWN), from its error text: never the
    agent's or the model's failure (G5-2). Every gateway refusal carries "token budget"."""
    return "token budget" in str(err or "")


# the same test in SQL, for run tables that keep the error text: such runs stay out of model and agent track records
NOT_BUDGET_STOP = "NOT (status='failed' AND COALESCE(error,'') LIKE '%token budget%')"


def begin(system, owner_id, kind, ref=None, agent_key=None, title="", model=None, decision=None):
    if _core is None: return None
    try: return _core.begin(system, owner_id, kind, ref=ref, agent_key=agent_key, title=title, model=model, decision=decision)
    except Exception as e:  # noqa: BLE001 - the run goes on, but unmetered work can't be verified: over() answers UNKNOWN for it
        log.warning("agent core begin: %s", e)
        if owner_id: _local.run = {"id": None, "owner": owner_id, "system": system, "agent": agent_key, "ref": ref, "unverified": True}
        return None

def end(status="done", ref=None, tokens=None, error=None, model=None, cost=None):
    st = "done" if status in ("done", "succeeded", "success", "ok", "merged") else status
    cur = getattr(_local, "run", None)
    if cur and cur.get("unverified") and (not ref or ref == cur.get("ref")): _local.run = None  # the marker a failed begin() left (closed by ref too, as the board does)
    return _safe("end", st, ref=ref, tokens=tokens, error=error, model=model, cost=cost)

def record(*a, **kw): return _safe("record", *a, **kw)
def used(tokens): return _safe("used", tokens)
def login(ref, kind): return _safe("login", ref, kind)
def unmetered(why, run_id=None, single_call=False): return _safe("unmetered", why, run_id, single_call)
def add_tokens(run_id, tokens): return _safe("add_tokens", run_id, tokens)
def model(m): return _safe("model", m)
def chat(owner_id, source, tokens, agent_key=None, model=None): return _safe("chat", owner_id, source, tokens, agent_key, model)
def over():
    """The gateway, before every model call: None (ALLOW), a refusal (REFUSE) or VERIFY_STOP (UNKNOWN). Never fails open."""
    if _core is None: return None
    try: return _core.over()
    except Exception as e:  # noqa: BLE001
        log.warning("agent core over: %s", e)
        return VERIFY_STOP

def preflight(owner_id, system, **scope):
    """Before work starts: None (ALLOW, verified), the refusal (decision REFUSE) or unknown() (decision UNKNOWN). Never fails open.
    Without the core mounted there are no limits at all (as before G5): None."""
    if _core is None: return None
    try: return _core.preflight(owner_id, system, **scope)
    except Exception as e:  # noqa: BLE001
        log.warning("agent core preflight: %s: %s", type(e).__name__, e)
        return unknown(e)

def per_call_caps(owner_id, system, **scope):
    """{limit id: updated} of the per-call limits over this scope; None when they can't be read (never {}, which would read as
    "no per-call limit" and release a per-call hold)."""
    if _core is None: return {}
    try: return _core.per_call_caps(owner_id, system, **scope)
    except Exception as e:  # noqa: BLE001
        log.warning("agent core per_call_caps: %s", e)
        return None

def admit(estimate=None, key=None, bound=None, model=None, reserve=None):
    """The gateway with a reservation (Milestone 3): None (ALLOW, the hold is on the thread), a refusal or VERIFY_STOP. Never fails open."""
    if _core is None: return None
    try: return _core.admit(estimate, key, bound, model, reserve)
    except Exception as e:  # noqa: BLE001
        log.warning("agent core admit: %s", e)
        return VERIFY_STOP

def call_failed(err): return _safe("call_failed", err)
def hold_id():
    """The reservation the model call in flight on this thread holds, or None."""
    cur = getattr(_local, "run", None)
    return cur.get("hold") if cur else None

def holding():
    """Whether the model call in flight on this thread still holds a reservation (False after used() or call_failed() settled it)."""
    cur = getattr(_local, "run", None)
    return bool(cur and cur.get("hold"))
def defer(): return _safe("defer")
def absorb(rids): return _safe("absorb", rids)
def unknown_outcome(rids, why): return _safe("unknown_outcome", rids, why)
def settle(rids, actual, run_id=None, note=None):
    """Settle holds outside the call that took them (a Codex session drained later). Raises nothing; returns the tokens counted,
    0 when nothing was held, None when the settlement couldn't be written (the holds stay to the expiry rule)."""
    return _safe("settle", rids, actual, run_id, note)


def _outcome_unknown(err):
    """Whether a failed call may have run without its use reaching AXoR: a timeout or a lost connection anywhere in the error's
    chain (an API answered with an error status is known: nothing billed)."""
    seen, e = 0, err
    while e is not None and seen < 6:
        name = type(e).__name__
        if isinstance(e, (TimeoutError, ConnectionError)) or name in ("APITimeoutError", "APIConnectionError", "ReadTimeout", "ConnectTimeout",
                                                                   "RemoteDisconnected", "IncompleteRead", "TimeoutExpired", "URLError"):
            return True
        if getattr(e, "status_code", None) or isinstance(getattr(e, "status", None), int): return False
        e, seen = e.__cause__ or e.__context__, seen + 1
    return bool(TIMEOUT.search(str(err or "")))


def _answered(err):
    """Whether a failed API call was answered by its provider with an error status (nothing billed): a status code in its chain."""
    seen, e = 0, err
    while e is not None and seen < 6:
        if getattr(e, "status_code", None) or isinstance(getattr(e, "status", None), int): return True
        e, seen = e.__cause__ or e.__context__, seen + 1
    return False


def _lease(db, rid):
    """A hold this process keeps in flight: the heartbeat renews its lease until it is settled, released, merged or lapsed."""
    with _llock:
        _leases[rid] = db
        if _lthread[0] is None or not _lthread[0].is_alive():
            _lthread[0] = threading.Thread(target=_heartbeat, daemon=True, name="ac-leases"); _lthread[0].start()


def _unlease(rids):
    with _llock:
        for r in rids or (): _leases.pop(r, None)


def renew_leases():
    """Push every in-flight hold's lease LEASE seconds ahead (one statement per database). A renewal that fails is logged: the lease
    then runs out, and the hold lapses (charged or unmetered), never released as 0."""
    by = {}
    with _llock:
        for rid, db in _leases.items(): by.setdefault(id(db), (db, []))[1].append(rid)
    n = 0
    for db, rids in by.values():
        try:
            marks = ",".join("?" * len(rids))
            got = db.q(f"UPDATE ac_reservations SET expires=? WHERE state='held' AND created>? AND id IN ({marks}) RETURNING id",
                       (time.time() + Core.LEASE, time.time() - Core.MAX_HOLD, *rids))  # a hold older than MAX_HOLD is no longer renewed: it lapses
            n += len(got)
            gone = set(rids) - {r["id"] for r in got}
            if gone: _unlease(gone)  # settled, lapsed or removed elsewhere: nothing left to renew
        except Exception as e:  # noqa: BLE001
            log.warning("agent core: lease renewal failed (%d hold(s)): %s", len(rids), e)
    return n


_tick = threading.Event()  # never set: the heartbeat waits on it, not on time.sleep, so nothing patching time.sleep (tests) touches it


def _heartbeat():
    last = time.time()
    while True:
        _tick.wait(0.5)
        with _llock:
            if not _leases: _lthread[0] = None; return
        if time.time() - last >= max(0.5, Core.LEASE / 5):  # read each time: a lease length changed at run time applies at once
            renew_leases(); last = time.time()


_NO_USE = re.compile(r"isn't signed in|not signed in|not logged in|isn't installed|couldn't start|rejected the server's|sign in again|"
                     r"doesn't work any more|usage limit|rate limit|isn't connected|switched off in Agents", re.I)


def _no_use(err):
    """A CLI call that failed before the model ran (sign-in, installation, a usage or rate limit the CLI reported up front)."""
    return type(err).__name__ == "QuotaError" or bool(_NO_USE.search(str(err or "")))


def call_cap(): return _safe("call_cap")
def pool(owner_id): return _safe("pool", owner_id)  # None without the core


def register_bucket(name, fn):
    """fn(run) -> [{"limit", "spent", "runs": (where over ac_runs, args), "message": fn(spent, held, estimate) -> text with "token
    budget", "label", "key"}]: a system's own token budget over this run, which reservations count calls in flight against
    (Milestone 3: a Competition team's 24-hour budget, a Company project's budget). Empty when none applies."""
    _buckets[name] = fn


def register_guard(name, fn):
    """fn(run) -> a refusal text (with the words "token budget") or None, asked before every model call of a run (over()).
    One per name: a system built again (tests, a reload) replaces its own."""
    _guards[name] = fn


def register_resolver(fn):
    """fn(system, ref) -> dict with any of corr, team, contract: what a run with this ref belongs to (orchestrator.py).
    One per function, as register_guard is one per name: a system built again (tests, a reload) replaces its own resolver, so this
    list never keeps an earlier instance (and its database connection) alive, and runs never ask a system that was replaced
    (PX-R13: on Postgres every test's Orchestrator stayed here and held a connection until the server ran out)."""
    key = getattr(fn, "__func__", fn)
    for i, f in enumerate(_resolvers):
        if getattr(f, "__func__", f) is key:
            _resolvers[i] = fn  # in its place: the order resolvers answer in doesn't change (never more than one per function)
            return
    _resolvers.append(fn)


def _resolve(system, ref):
    """A run's correlation id (the ref itself unless a resolver knows better), team and contract. Never raises."""
    out = {"corr": ref, "team": None, "contract": None}
    for fn in list(_resolvers):
        try:
            got = fn(system, ref) or {}
            out.update({k: v for k, v in got.items() if v and k in out})
        except Exception as e:  # noqa: BLE001 - a resolver never stops a run
            log.warning("agent core resolver: %s", e)
    return out
def set_pool(owner_id, pool, weights, by=""): return _safe("set_pool", owner_id, pool, weights, by)
def score(ref, value, only_unscored=False, kinds=None): return _safe("score", ref, value, only_unscored, kinds)


def _plan_wait(model, owner_id):
    """Until when the plan login that `owner_id`'s work on `model` would run on (cli_accounts.pick: their own, the server's, a
    teammate's while the server's is at its limit, or a named login) waits for its usage limit; 0 when it doesn't, when the
    model isn't on a plan (Claude Code, Codex), or when there's no login (resolve() says so later). Never picks another login."""
    p, _, m = (model or "").partition(":")
    if p not in ("terminal", "codex"): return 0.0
    try:
        from . import cli_accounts  # here, not at the top: cli_accounts imports this module
        until = (cli_accounts.pick(p, owner_id or None, m).quota or {}).get("until") or 0.0
    except Exception:  # noqa: BLE001 - routing never stops a run
        return 0.0
    return until if until > time.time() else 0.0


def route(llm, owner_id, system, kind, choice="auto", avoid=(), min_tier=None, pressure=False, stats=None):
    """The provider:model a run of `system`/`kind` goes to, and why: a model the user or agent picked runs as picked; "auto"
    goes to the owner's pool through the router, else to the default model. Raises LLMError (as llm.resolve) when no model is
    available. Returns (model, decision); decision["source"] is picked, routed, fallback (the router's pick wasn't available,
    decision["from"]) or no_pool (no pool, or none of its providers connected). The decision waits on this thread for the
    run it's for (begin/model with this model), which keeps it."""
    if choice and choice != "auto":
        p, m = llm.resolve(choice)
        return _pending((owner_id, system, kind), f"{p}:{m}", {"task": kind, "model": f"{p}:{m}", "source": "picked", "reason": "Picked for this work, so not routed.", "candidates": []})
    got = _safe("route", llm, owner_id, system, kind, avoid=avoid, min_tier=min_tier, pressure=pressure, stats=stats) if owner_id else None
    failed = None
    if got:
        try:
            llm.resolve(got[0])  # still available: a CLI plan with no login for this person says so here
            return _pending((owner_id, system, kind), got[0], {**got[1], "source": "routed"})
        except Exception as e:  # noqa: BLE001 - routing never stops a run: fall back to the default model
            log.info("agent core route: %s unavailable (%s), default model", got[0], e)
            failed = (got[0], str(e))
    p, m = llm.resolve("auto")
    if failed:
        why = f"The router picked {failed[0]}, which isn't available ({failed[1][:160]}): the default model."
        return _pending((owner_id, system, kind), f"{p}:{m}", {"task": kind, "model": f"{p}:{m}", "source": "fallback", "from": failed[0], "reason": why, "candidates": got[1].get("candidates") or []})
    has_pool = bool(owner_id and ((pool(owner_id) or {}).get("pool")))
    why = ("None of the model pool's providers is connected now: the default model." if has_pool
           else "No model pool (Workforce → Settings): the default model.")
    return _pending((owner_id, system, kind), f"{p}:{m}", {"task": kind, "model": f"{p}:{m}", "source": "no_pool", "reason": why, "candidates": []})


def compact_decision(d, top=5):
    """What a run keeps of a routing decision: its source, reason, weights and the top candidates (rounded)."""
    if not isinstance(d, dict): return None
    why = (d.get("reason") or "").lower()
    src = d.get("source") or ("routed" if d.get("candidates") else "picked" if any(w in why for w in ("picked", "pinned", "fixed")) else "no_pool")
    keep = ("model", "tier", "score", "quality", "cost", "latency", "risk", "runs", "scored")
    out = {"source": src, "task": d.get("task"), "reason": str(d.get("reason") or "")[:400],
           "candidates": [{k: c.get(k) for k in keep if k in c} for c in (d.get("candidates") or [])[:top] if isinstance(c, dict)]}
    if d.get("weights"): out["weights"] = d["weights"]
    if d.get("from"): out["from"] = d["from"]
    return out


def _pending(key, model, decision):
    """route()'s answer. Its decision goes onto the run open on this thread for this owner, else waits for that run's begin()."""
    dec = compact_decision(decision)
    if not (_core and key[0] and _safe("decided", key[0], dec)):
        now = time.time()
        with _plock:
            for k in [k for k, v in _waiting.items() if now - v[1] > PENDING]: _waiting.pop(k, None)
            if len(_waiting) < 2000: _waiting[(*key, model)] = (dec, now)
    return model, decision


def _take_pending(owner_id, system, kind, model):
    """The decision route() made for this run (same owner, system, kind and model, in the last PENDING seconds), taken once."""
    if not model: return None
    with _plock:
        for m in (model, *([k[3] for k in _waiting if k[:3] == (owner_id, system, kind) and _same_model(k[3], model)])):
            got = _waiting.pop((owner_id, system, kind, m), None)
            if got: return got[0] if time.time() - got[1] <= PENDING else None
    return None


def _same_model(a, b):
    """'anthropic:claude-x' and 'claude-x' are the same model; systems store either form."""
    return (a or "").partition(":")[2] == b or (b or "").partition(":")[2] == a


class run:
    """with agent_core.run("missions", uid, "direct", ref="mx:4"): ... (failed when it raises)."""
    def __init__(self, system, owner_id, kind, **kw): self.a, self.kw = (system, owner_id, kind), kw
    def __enter__(self): begin(*self.a, **self.kw); return self
    def __exit__(self, et, e, tb):
        end("failed" if et else "done", error=str(e)[:400] if e else None)
        return False
