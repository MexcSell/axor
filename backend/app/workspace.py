"""Workspace: each user's shortlist of subnets they're working on, plus the agents they work with.

- Subnets: add, remove, and open a mining brief for each one: the task, what miners do, a budget
  (hardware, inference/API, registration, expected earnings), ways to keep costs low, how to become
  a top miner, and the current state of competition (earners, concentration, top payees).
- Agents: add any custom agent you can use, select one, chat with it about the open subnet, remove it.
  Chats go through the agent hub (same access rules and credits); the subnet is passed as the focus.
- Notes: sticky notes pinned to one subnet or kept general (shown with every subnet). Text is light markdown
  (checklists, bold, highlight...) rendered by the page; any color, a size, and an optional PDCA stage.
  Daily notes are one per user per day; a new one carries over the previous day's unchecked items.
- Files: the files panel shows Scout Drive (the separate file server, see drive.py): the Shared drive plus the
  user's own My drive. Uploads from the workspace go to the Shared drive's Workspace folder, tagged with the
  subnet; deleting moves a file to the drive's trash. Downloads are served as attachments. Files from the old
  built-in file hub are moved into the drive on start-up.
- Briefs are computed from the live snapshot and knowledge.json on every request: nothing is cached.
"""
import logging, re, statistics, time
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .drive import DriveError
from .recommend import HW_RANK, PLAYBOOK, economics

MAX_SUBNETS = 30
MAX_AGENTS = 12
MAX_NOTES = 300
NOTE_COLORS = ("yellow", "pink", "blue", "green", "violet")
PDCA = ("plan", "do", "check", "act")
DAILY_KEEP = 30  # daily notes sent with the board; older days are fetched one at a time
WS_FOLDER = ["Workspace"]  # the Shared drive folder workspace uploads go to
log = logging.getLogger("workspace")
# fields where validators score uptime: preemptible machines lose more than they save
UPTIME_FIELDS = {"Compute", "Inference", "Infrastructure", "Inference Optimisation"}
# typical monthly spend on paid model / data APIs (USD), beyond the server itself
API_TIER = (30, 200, "LLM API credits (Claude, OpenAI or similar) to produce answers")
API_FIELD = {
    "LLM & Agents": (0, 60, "Optional LLM API calls for evaluation runs, synthetic data or agent tooling"),
    "Data & Scraping": (20, 150, "Proxies and data-source API access (X, Reddit, web scraping)"),
    "Finance & DeFi": (0, 100, "Market data feeds"),
    "Forecasting": (0, 50, "Weather or market data feeds"),
}
API_NONE = (0, 0, "None needed: the miner runs its own code or models")

def _mid(lo, hi):
    return None if lo is None else (lo + hi) / 2

def _series_stats(values):
    v = [x for x in values or [] if x is not None]
    return (min(v), statistics.median(v), max(v)) if len(v) >= 3 else None

def brief(r, tiers, usd, hardware=None, own=False):
    """Everything a miner needs to decide on and plan for one subnet."""
    usd = usd or 0
    hw = HW_RANK.get(hardware) if hardware else None
    eco = economics(r, tiers, usd, hw, own)
    t = tiers.get(r["tier"], tiers["unknown"])
    lo, hi = eco["rent"]
    if r["tier"] == "api":  # the tier's rent already bundles API credits: split it into server + API
        lo, hi = tiers["cpu"]["rent_low"], tiers["cpu"]["rent_high"]
        api_lo, api_hi, api_what = API_TIER
    else:
        api_lo, api_hi, api_what = API_FIELD.get(r["field"], API_NONE)
    owned = own and eco["fits_hw"] and lo is not None
    server_typ = None if lo is None else _mid(lo, hi) * (0.25 if owned else 1)
    api_typ = _mid(api_lo, api_hi)
    monthly = None if server_typ is None else server_typ + api_typ
    reg_usd = r["reg_cost"] * usd if usd else None
    gross = eco["realistic"] * 30 * usd if usd else None
    net = None if gross is None or monthly is None else gross - monthly
    daily_net = None if net is None else net / 30
    budget = {
        "profile": {"hardware": hardware, "own": bool(own), "fits": eco["fits_hw"]},
        "hardware": {"tier": r["tier"], "label": t["label"], "spec": t["hardware"], "needs": r["hardware"],
                     "low": lo, "high": hi, "typical": server_typ, "owned": owned},
        "inference": {"low": api_lo, "high": api_hi, "typical": api_typ, "what": api_what},
        "registration": {"tao": r["reg_cost"], "usd": reg_usd},
        "capital_at_risk": r["tier"] == "capital",
        "monthly": {"low": None if lo is None else (lo * (0.25 if owned else 1)) + api_lo, "typical": monthly,
                    "high": None if hi is None else hi * (0.25 if owned else 1) + api_hi},
        "first_month": None if monthly is None or reg_usd is None else monthly + reg_usd,
        "earnings": {"top_day": r["top_miner"], "second_day": r["second_miner"], "median_day": r["median_miner"],
                     "realistic_day": eco["realistic"], "earn_chance": round(eco["p_earn"], 3),
                     "gross_month_usd": gross},
        "net_month_usd": net,
        "first_month_net_usd": None if net is None or reg_usd is None else net - reg_usd,
        "break_even_days": round(reg_usd / daily_net, 1) if reg_usd and daily_net and daily_net > 0 else None,
    }
    return {"netuid": r["netuid"], "name": r["name"], "field": r["field"], "risk": r["risk_level"],
            "task": r["task"], "description": r["description"], "miner_role": r["miner_role"], "conditions": r["conditions"],
            "hardware": r["hardware"], "software": r["software"], "links": r["links"], "flags": r["flags"],
            "budget": budget, "low_cost": _low_cost(r, budget, usd), "top_miner": _how_to_top(r, usd),
            "competition": _competition(r)}

def _money(tao, usd):
    return f"{tao:.3f} τ" + (f" (${tao * usd:,.0f})" if usd else "")

def _low_cost(r, b, usd):
    tips, hw, api = [], b["hardware"], b["inference"]
    if hw["owned"]:
        tips.append("Your own hardware covers this tier, so running cost is mostly power and bandwidth (about a quarter of the rental price).")
    elif hw["low"] is None:
        tips.append("Hardware needs aren't published: ask in the subnet's Discord or read the miner code before renting anything, and start on the smallest machine that runs it.")
    elif hw["high"] > 15:
        tips.append(f"Start at the low end: about ${hw['low']:,}/month for {hw['spec']}. Upgrade only once you earn.")
    if r["tier"].startswith("gpu") and not hw["owned"]:
        if r["field"] in UPTIME_FIELDS:
            tips.append("Rent on-demand machines, not spot or interruptible ones: validators score uptime, so preemptions cost more than they save. "
                        "Compare the hourly price of the exact GPU on RunPod, Vast.ai (verified hosts), Lambda and TensorDock.")
        else:
            tips.append("Develop and benchmark on cheap spot or interruptible GPUs (Vast.ai, RunPod community cloud), and move to an always-on machine only when your miner scores well.")
    if api["high"]:
        tips.append("Cap API spend: draft with a cheaper model and use the strongest one only where scores depend on it, cache repeated prompts, "
                    f"and set a hard monthly limit with your provider (budget ${api['low']:,}-{api['high']:,}/month).")
    st = _series_stats((r.get("series") or {}).get("reg_cost"))
    if st and r["reg_cost"]:
        lo7, med7, _ = st
        if r["reg_cost"] > med7 * 1.1:
            tips.append(f"Registration costs {r['reg_cost']:.4f} τ now against a 7-day median of {med7:.4f} τ. It rises with demand; "
                        f"waiting for a dip could save about {_money(r['reg_cost'] - med7, usd)}.")
        elif r["reg_cost"] <= lo7 * 1.05:
            tips.append(f"Registration is near its 7-day low ({lo7:.4f} τ): a good time to register once your miner is ready.")
    tips.append(f"Build and test locally against the validator code (or on testnet) before you register: the {r['immunity_hours']:.0f}h immunity "
                "clock starts at registration, and every day of rent before your miner is competitive is lost.")
    if r["top_share"] > 0.6:
        tips.append(f"The top miner takes {r['top_share'] * 100:.0f}% of rewards, so only the best submission earns. Don't pay for several UIDs until one of them earns.")
    else:
        tips.append(f"Start with one UID and add more only once it earns steadily: each extra UID burns another {_money(r['reg_cost'], usd)}.")
    if b["net_month_usd"] is not None and b["net_month_usd"] < 0:
        tips.append(f"At current prices a typical newcomer grosses about ${b['earnings']['gross_month_usd'] or 0:,.0f}/month, less than the typical "
                    f"${b['monthly']['typical']:,.0f}/month cost. It only pays if you can beat the median miner, or with the low-cost setup above.")
    if b["capital_at_risk"]:
        tips.append("This subnet needs trading capital, collateral or stake: start with the minimum and treat it as money you can lose.")
    return tips

def _how_to_top(r, usd):
    pay = r.get("top_payees") or []
    out = [f"The top miner earns {_money(r['top_miner'], usd)}/day, #2 {_money(r['second_miner'], usd)}/day and the median earner {_money(r['median_miner'], usd)}/day."]
    out.append(PLAYBOOK.get(r["field"], "Study the validator code to learn exactly how scores are computed, then optimise for that metric."))
    if pay:
        n = min(10, len(pay))
        out.append(f"Score target: the leader holds {pay[0]['incentive'] * 100:.1f}% of miner incentive; the #{n} paid miner holds "
                   f"{pay[n - 1]['incentive'] * 100:.2f}%. Beat that to join the top {n}.")
        new = sum(1 for p in pay if p["immune"])
        out.append(f"{new} of the top {len(pay)} paid miners are still in their immunity period: newcomers can break in quickly." if new
                   else f"None of the top {len(pay)} paid miners registered recently: the leaders are established, so expect a ramp-up period.")
    if r["links"].get("github"):
        out.append(f"Read the validator code ({r['links']['github']}): the scoring function is the real spec. Re-check it after every release.")
    if r["conditions"]:
        out.append(f"Subnet rules: {r['conditions']}")
    out.append(f"Stay online through every {r['emission_cycle_min']:.0f}-minute epoch and watch the leaderboard daily. New UIDs are immune for "
               f"{r['immunity_hours']:.0f}h: score above the weakest miners before that ends or you'll be deregistered.")
    return out

def _competition(r):
    pay = r.get("top_payees") or []
    total = r["miner_pool_day"] / (1 - r["owner_burn_share"]) if r["owner_burn_share"] < 1 else 0
    share = lambda k: sum(p["tao_day"] for p in pay[:k]) / total if total else 0
    cold = {}
    for p in pay: cold[p["coldkey"]] = cold.get(p["coldkey"], 0) + 1
    biggest = max(cold.values()) if cold else 0
    miners = max(0, r["num_uids"] - r["validators"])
    if not r["earning_miners"]: level, text = "No earners", "No miner earns right now."
    elif r["top_share"] > 0.6: level, text = "Winner-take-all", f"One miner takes {r['top_share'] * 100:.0f}% of rewards."
    elif share(10) > 0.8: level, text = "Concentrated", f"The top 10 take {share(10) * 100:.0f}% of rewards."
    elif r["earning_miners"] >= 0.5 * max(1, miners): level, text = "Broad", f"{r['earning_miners']} of {miners} miners earn: rewards are widely spread."
    else: level, text = "Competitive", f"{r['earning_miners']} of {miners} miners earn; the rest score zero."
    st = _series_stats((r.get("series") or {}).get("reg_cost"))
    reg = (r.get("series") or {}).get("reg_cost") or []
    reg = [x for x in reg if x]
    return {
        "level": level, "summary": text,
        "registered": r["num_uids"], "max": r["max_uids"], "validators": r["validators"], "miners": miners,
        "earning": r["earning_miners"], "earning_share": r["earning_miners"] / miners if miners else 0,
        "open_slots": r["open_slots"], "prunable": r["prunable_uids"], "uid_available": r["uid_available"],
        "registration_allowed": r["registration_allowed"], "regs_this_interval": r.get("regs_this_interval"),
        "reg_rate_limit": r.get("reg_rate_limit"),
        "top_share": r["top_share"], "top3_share": share(3), "top10_share": share(10), "owner_burn_share": r["owner_burn_share"],
        "operators": len(cold), "biggest_operator_uids": biggest,
        "new_in_top": sum(1 for p in pay if p["immune"]),
        "reg_cost_7d": {"low": st[0], "median": st[1], "high": st[2]} if st else None,
        "reg_cost_change_7d": reg[-1] / reg[0] - 1 if len(reg) >= 2 else None,
        "emission_change_7d": r.get("emission_change_7d"), "price_change_7d": r.get("price_change_7d"),
        "immunity_hours": r["immunity_hours"], "cycle_min": r["emission_cycle_min"],
        "top_payees": pay,
    }

class SubnetIn(BaseModel):
    netuid: int

class AgentRef(BaseModel):
    agent_id: int

class AttachIn(BaseModel):
    kind: str  # skill, tool, file (Scout Drive) or source (owner/name:path on the Source hub)
    id: str

class WsChatIn(BaseModel):
    agent_id: int
    netuid: int
    message: str
    model: str | None = None
    effort: str = "medium"
    attachments: list[AttachIn] = []

class NoteIn(BaseModel):
    text: str = Field("", max_length=4000)
    color: str = "yellow"
    netuid: int | None = None
    stage: str | None = None
    w: int | None = None
    h: int | None = None

class NotePatch(BaseModel):
    """Only the fields sent are changed; send null for netuid, stage, w or h to clear them."""
    text: str | None = Field(None, max_length=4000)
    color: str | None = None
    pinned: bool | None = None
    netuid: int | None = None
    stage: str | None = None
    w: int | None = None
    h: int | None = None

def _color(c):
    if c in NOTE_COLORS or re.fullmatch(r"#[0-9a-fA-F]{6}", c or ""): return c.lower()
    raise HTTPException(400, "Unknown note color.")

def _stage(s):
    if s in (None, ""): return None
    if s not in PDCA: raise HTTPException(400, "Stage must be plan, do, check or act.")
    return s

def _size(v, lo, hi):
    return None if v is None else max(lo, min(hi, int(v)))

class Workspace:
    def __init__(self, db, data, tiers, hub, drive=None, legacy_dir=None):
        self.db, self.data, self.tiers, self.hub, self.drive = db, data, tiers, hub, drive
        self.legacy_dir = Path(legacy_dir) if legacy_dir else None  # the old built-in file hub, emptied into the drive
        db.q("CREATE TABLE IF NOT EXISTS workspace_subnets (user_id INTEGER, netuid INTEGER, added REAL, PRIMARY KEY (user_id, netuid))")
        db.q("""CREATE TABLE IF NOT EXISTS workspace_agents (
                  user_id INTEGER, agent_id INTEGER, added REAL, selected INTEGER DEFAULT 0, PRIMARY KEY (user_id, agent_id))""")
        db.q("""CREATE TABLE IF NOT EXISTS workspace_chats (
                  user_id INTEGER, agent_id INTEGER, netuid INTEGER, conversation_id TEXT, PRIMARY KEY (user_id, agent_id, netuid))""")
        db.q("""CREATE TABLE IF NOT EXISTS workspace_notes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, text TEXT, color TEXT,
                  pinned INTEGER DEFAULT 0, created REAL, updated REAL)""")
        have = {c["name"] for c in db.q("PRAGMA table_info(workspace_notes)")}
        for col, typ in (("kind", "TEXT DEFAULT 'note'"), ("day", "TEXT"), ("stage", "TEXT"), ("w", "INTEGER"), ("h", "INTEGER")):
            if col not in have: db.q(f"ALTER TABLE workspace_notes ADD COLUMN {col} {typ}")
        db.q("CREATE UNIQUE INDEX IF NOT EXISTS workspace_daily ON workspace_notes (user_id, day) WHERE kind='daily'")
        # the old built-in file hub: only read to move its files into the drive
        db.q("""CREATE TABLE IF NOT EXISTS workspace_files (
                  id TEXT PRIMARY KEY, user_id INTEGER, netuid INTEGER, name TEXT, size INTEGER, added REAL)""")

    def _subnet(self, netuid):
        r = next((x for x in self.data()["subnets"] if x["netuid"] == netuid), None)
        if not r: raise HTTPException(404, f"No subnet SN{netuid} in the current data.")
        return r

    def agents_on(self, me):
        if not self.hub: return False
        try: self.hub.gate(me); return True
        except HTTPException: return False

    def _agents(self, me):
        """Workspace agents the user can still use (deleted or unshared ones drop out), selected first."""
        if not self.agents_on(me): return []
        names = self.hub._names()
        out = []
        for w in self.db.q("SELECT agent_id, selected FROM workspace_agents WHERE user_id=? ORDER BY added", (me["id"],)):
            try: a = self.hub._usable(w["agent_id"], me)
            except HTTPException:
                self.db.q("DELETE FROM workspace_agents WHERE user_id=? AND agent_id=?", (me["id"], w["agent_id"]))
                continue
            out.append({**self.hub._public(a, me, names), "selected": bool(w["selected"])})
        if out and not any(a["selected"] for a in out):
            out[0]["selected"] = True
        return out

    def view(self, me):
        rows = self.db.q("SELECT netuid, added FROM workspace_subnets WHERE user_id=? ORDER BY added", (me["id"],))
        return {"subnets": rows, "agents": self._agents(me), "agents_enabled": self.agents_on(me),
                "limits": {"subnets": MAX_SUBNETS, "agents": MAX_AGENTS}}

    def add_subnet(self, me, netuid):
        self._subnet(netuid)
        n = self.db.q("SELECT COUNT(*) n FROM workspace_subnets WHERE user_id=?", (me["id"],), one=True)["n"]
        if n >= MAX_SUBNETS: raise HTTPException(400, f"Your workspace holds up to {MAX_SUBNETS} subnets. Remove one first.")
        self.db.q("INSERT OR IGNORE INTO workspace_subnets VALUES (?,?,?)", (me["id"], netuid, time.time()))
        return self.view(me)

    def remove_subnet(self, me, netuid):
        self.db.q("DELETE FROM workspace_subnets WHERE user_id=? AND netuid=?", (me["id"], netuid))
        self.db.q("DELETE FROM workspace_chats WHERE user_id=? AND netuid=?", (me["id"], netuid))
        return self.view(me)

    def brief(self, me, netuid, hardware=None, own=False):
        st = self.data()
        return brief(self._subnet(netuid), self.tiers, st["tao_usd"], hardware if hardware in HW_RANK else None, own)

    def _gate(self, me):
        if not self.hub: raise HTTPException(404, "Agents aren't available on this server.")
        self.hub.gate(me)

    def add_agent(self, me, aid):
        self._gate(me); self.hub._usable(aid, me)
        n = self.db.q("SELECT COUNT(*) n FROM workspace_agents WHERE user_id=?", (me["id"],), one=True)["n"]
        if n >= MAX_AGENTS: raise HTTPException(400, f"Your workspace holds up to {MAX_AGENTS} agents. Remove one first.")
        first = not self.db.q("SELECT 1 FROM workspace_agents WHERE user_id=?", (me["id"],), one=True)
        self.db.q("INSERT OR IGNORE INTO workspace_agents VALUES (?,?,?,?)", (me["id"], aid, time.time(), int(first)))
        return self.view(me)

    def add_team(self, me):
        """Creates the project team (or reuses it) and adds every member that fits; the engineering manager is selected."""
        self._gate(me)
        ids, made = self.hub.create_team(me)
        have = {r["agent_id"] for r in self.db.q("SELECT agent_id FROM workspace_agents WHERE user_id=?", (me["id"],))}
        added = skipped = 0
        for aid in ids:
            if aid in have: continue
            if len(have) >= MAX_AGENTS: skipped += 1; continue
            self.db.q("INSERT OR IGNORE INTO workspace_agents VALUES (?,?,?,0)", (me["id"], aid, time.time()))
            have.add(aid); added += 1
        self.db.q("UPDATE workspace_agents SET selected=(agent_id=?) WHERE user_id=?", (ids[0], me["id"]))
        return {**self.view(me), "team": {"created": made, "added": added, "skipped": skipped}}

    def remove_agent(self, me, aid):
        self._gate(me)
        self.db.q("DELETE FROM workspace_agents WHERE user_id=? AND agent_id=?", (me["id"], aid))
        self.db.q("DELETE FROM workspace_chats WHERE user_id=? AND agent_id=?", (me["id"], aid))
        return self.view(me)

    def select_agent(self, me, aid):
        self._gate(me)
        if not self.db.q("SELECT 1 FROM workspace_agents WHERE user_id=? AND agent_id=?", (me["id"], aid), one=True):
            raise HTTPException(404, "That agent isn't in your workspace.")
        self.db.q("UPDATE workspace_agents SET selected=(agent_id=?) WHERE user_id=?", (aid, me["id"]))
        return self.view(me)

    def _conv(self, me, aid, netuid):
        r = self.db.q("SELECT conversation_id FROM workspace_chats WHERE user_id=? AND agent_id=? AND netuid=?", (me["id"], aid, netuid), one=True)
        return r and r["conversation_id"]

    def chat_view(self, me, aid, netuid):
        self._gate(me)
        cid = self._conv(me, aid, netuid)
        if not cid: return {"id": None, "items": []}
        try: return self.hub.view(me, aid, cid)
        except HTTPException:  # the conversation went away with its agent
            self.db.q("DELETE FROM workspace_chats WHERE user_id=? AND agent_id=? AND netuid=?", (me["id"], aid, netuid))
            return {"id": None, "items": []}

    def chat(self, me, c: WsChatIn):
        self._gate(me)
        if not self.db.q("SELECT 1 FROM workspace_agents WHERE user_id=? AND agent_id=?", (me["id"], c.agent_id), one=True):
            raise HTTPException(400, "Add the agent to your workspace first.")
        r = self._subnet(c.netuid)
        out = self.hub.chat(me, c.agent_id, self._conv(me, c.agent_id, c.netuid), c.message, c.model, c.effort,
                            focus={"netuid": r["netuid"], "name": r["name"]}, attachments=c.attachments)
        if out.get("id"):
            self.db.q("INSERT OR REPLACE INTO workspace_chats VALUES (?,?,?,?)", (me["id"], c.agent_id, c.netuid, out["id"]))
        return out

    def new_chat(self, me, aid, netuid):
        self._gate(me)
        self.db.q("DELETE FROM workspace_chats WHERE user_id=? AND agent_id=? AND netuid=?", (me["id"], aid, netuid))
        return {"id": None, "items": []}

    # ---------- notes ----------
    _COLS = "id, kind, day, netuid, text, color, pinned, stage, w, h, created, updated"

    def notes(self, me):
        """The user's notes (the page filters by subnet), pinned first, then most recently edited,
        plus their latest daily notes, newest day first."""
        rows = self.db.q(f"SELECT {self._COLS} FROM workspace_notes WHERE user_id=? AND kind='note' ORDER BY pinned DESC, updated DESC", (me["id"],))
        daily = self.db.q(f"SELECT {self._COLS} FROM workspace_notes WHERE user_id=? AND kind='daily' ORDER BY day DESC LIMIT ?", (me["id"], DAILY_KEEP))
        fix = lambda xs: [{**r, "pinned": bool(r["pinned"])} for r in xs]
        return {"notes": fix(rows), "daily": fix(daily), "limit": MAX_NOTES}

    def _note(self, me, nid):
        r = self.db.q("SELECT id, kind FROM workspace_notes WHERE id=? AND user_id=?", (nid, me["id"]), one=True)
        if not r: raise HTTPException(404, "That note doesn't exist.")
        return r

    def add_note(self, me, n: NoteIn):
        if n.netuid is not None: self._subnet(n.netuid)
        c = self.db.q("SELECT COUNT(*) n FROM workspace_notes WHERE user_id=? AND kind='note'", (me["id"],), one=True)["n"]
        if c >= MAX_NOTES: raise HTTPException(400, f"You can keep up to {MAX_NOTES} notes. Delete some first.")
        now = time.time()
        self.db.q("INSERT INTO workspace_notes (user_id, kind, netuid, text, color, pinned, stage, w, h, created, updated) VALUES (?,'note',?,?,?,0,?,?,?,?,?)",
                  (me["id"], n.netuid, n.text, _color(n.color), _stage(n.stage), _size(n.w, 160, 900), _size(n.h, 120, 1200), now, now))
        return self.notes(me)

    def daily(self, me, day, create=False):
        """The daily note for a day (YYYY-MM-DD, the user's local date). With create, a missing one is made,
        starting with the unchecked items of the most recent earlier day."""
        try: date.fromisoformat(day)
        except ValueError: raise HTTPException(400, "Day must be YYYY-MM-DD.")
        q = lambda: self.db.q(f"SELECT {self._COLS} FROM workspace_notes WHERE user_id=? AND kind='daily' AND day=?", (me["id"], day), one=True)
        r = q()
        if not r and create:
            prev = self.db.q("SELECT day, text FROM workspace_notes WHERE user_id=? AND kind='daily' AND day<? ORDER BY day DESC LIMIT 1", (me["id"], day), one=True)
            todo = [l.strip() for l in (prev["text"] if prev else "").splitlines() if re.match(r"\s*[-*] \[ \]\s*\S", l)]
            text = (f"## Carried over from {prev['day']}\n" + "\n".join(todo) + "\n\n" if todo else "") + "## Today\n- [ ] "
            now = time.time()
            self.db.q("INSERT OR IGNORE INTO workspace_notes (user_id, kind, day, netuid, text, color, pinned, created, updated) VALUES (?,'daily',?,NULL,?,'yellow',0,?,?)",
                      (me["id"], day, text, now, now))
            r = q()
        return {"note": r and {**r, "pinned": bool(r["pinned"])}}

    def update_note(self, me, nid, p: NotePatch):
        daily = self._note(me, nid)["kind"] == "daily"
        sent = p.model_fields_set
        sets = {}
        if p.text is not None: sets["text"] = p.text
        if p.color is not None: sets["color"] = _color(p.color)
        if p.pinned is not None: sets["pinned"] = int(p.pinned)
        if not daily:  # a daily note has no subnet, stage or board size
            if "netuid" in sent:
                if p.netuid is not None: self._subnet(p.netuid)
                sets["netuid"] = p.netuid
            if "stage" in sent: sets["stage"] = _stage(p.stage)
            if "w" in sent: sets["w"] = _size(p.w, 160, 900)
            if "h" in sent: sets["h"] = _size(p.h, 120, 1200)
        if sets:
            # only a text edit counts as "edited": pinning or recoloring shouldn't reorder the board
            if "text" in sets: sets["updated"] = time.time()
            self.db.q(f"UPDATE workspace_notes SET {', '.join(f'{k}=?' for k in sets)} WHERE id=? AND user_id=?", (*sets.values(), nid, me["id"]))
        return self.notes(me)

    def delete_note(self, me, nid):
        self._note(me, nid)
        self.db.q("DELETE FROM workspace_notes WHERE id=? AND user_id=?", (nid, me["id"]))
        return self.notes(me)

    # ---------- files: kept in Scout Drive (drive/ and drive.py) ----------
    def _drive(self):
        if not self.drive or not self.drive.enabled: raise HTTPException(404, "File storage isn't available on this server.")
        return self.drive

    def _call(self, *a, **k):
        try: return self._drive().call(*a, **k)
        except DriveError as e: raise HTTPException(e.status, str(e))

    def files(self, me):
        """Every drive file the user can read: the Shared drive and their own My drive."""
        if not self.drive or not self.drive.enabled: return {"enabled": False, "files": []}
        try: items, u = self.drive.call("GET", "/v1/files", me), self.drive.call("GET", "/v1/usage", me)
        except DriveError as e: return {"enabled": True, "error": str(e), "files": []}
        out = [{"id": x["id"], "netuid": x["netuid"], "name": x["name"], "size": x["size"], "added": x["updated"], "mine": x["mine"],
                "can_delete": x["can_modify"], "uploader": x["owner"] or "deleted user", "space": x["space"], "path": x["path"]} for x in items]
        return {"enabled": True, "files": out, "used": u["used"], "total": sum(x["size"] for x in out if x["space"] == "shared"),
                "quota": u["quota"], "max_file": u["max_file"]}

    def _folder(self, me):
        return self._call("POST", "/v1/folders/ensure", me, body={"space": "shared", "path": WS_FOLDER})["id"]

    async def upload(self, me, req: Request, name, netuid):
        """Workspace uploads land in the Shared drive's Workspace folder, tagged with the subnet."""
        if netuid is not None: self._subnet(netuid)
        try: await self._drive().upload(me, req, {"space": "shared", "name": name, "parent": self._folder(me), "netuid": netuid})
        except DriveError as e: raise HTTPException(e.status, str(e))
        return self.files(me)

    def download(self, me, fid):
        try: return self._drive().stream(f"/v1/nodes/{fid}/content", me, {"download": "true"})
        except DriveError as e: raise HTTPException(e.status, str(e))

    def read_text(self, me, fid):
        """A drive file for an agent to read: (name, text or None if it has no text, size)."""
        if not re.fullmatch(r"[0-9a-f]{32}", fid or ""): raise HTTPException(404, "That file doesn't exist.")
        try: return self._drive().text(me, fid)
        except DriveError as e: raise HTTPException(e.status, str(e))

    def delete_file(self, me, fid):
        if not re.fullmatch(r"[0-9a-f]{32}", fid or ""): raise HTTPException(404, "That file doesn't exist.")
        self._call("POST", f"/v1/nodes/{fid}/trash", me)
        return self.files(me)

    def migrate(self):
        """Move the old file hub (DATA_DIR/workspace_files) into the drive's Shared drive, waiting for the drive to
        come up. Each file keeps its uploader, subnet tag and date; it's removed here once the drive has it."""
        if not (self.drive and self.drive.enabled and self.legacy_dir): return
        rows = self.db.q("SELECT f.*, u.username, u.role FROM workspace_files f LEFT JOIN users u ON u.id = f.user_id ORDER BY f.added")
        if not rows: return
        for _ in range(60):  # ten minutes
            try: self.drive.call("GET", "/v1/usage", {"id": rows[0]["user_id"], "username": "migration"}); break
            except DriveError: time.sleep(10)
        else:
            log.warning("drive unreachable: %d old workspace files stay in %s until the next start", len(rows), self.legacy_dir); return
        moved = 0
        for f in rows:
            me = {"id": f["user_id"], "username": f["username"] or "deleted user", "role": f["role"]}
            path = self.legacy_dir / str(f["user_id"]) / f["id"]
            try:
                if path.is_file():
                    folder = self.drive.call("POST", "/v1/folders/ensure", me, body={"space": "shared", "path": WS_FOLDER})["id"]
                    with open(path, "rb") as fh:
                        self.drive.call("PUT", "/v1/files", me, {"space": "shared", "name": f["name"], "parent": folder, "netuid": f["netuid"]}, None,
                                        {"Content-Length": str(path.stat().st_size), "Content-Type": "application/octet-stream",
                                         "X-Drive-Import-Id": f["id"], "X-Drive-Import-Created": str(f["added"])}, fh, 600)
                    moved += 1
                self.db.q("DELETE FROM workspace_files WHERE id=?", (f["id"],))
                path.unlink(missing_ok=True)
            except DriveError as e:
                log.warning("couldn't move %s into the drive: %s", f["name"], e)
        log.info("moved %d of %d workspace files into Scout Drive", moved, len(rows))

def build(db, require, data, tiers, hub=None, ready=None, drive=None, legacy_dir=None):
    r = APIRouter(prefix="/api/workspace")
    ws = Workspace(db, data, tiers, hub, drive, legacy_dir)
    r.state = {"ws": ws}

    @r.get("")
    def view(req: Request):
        return ws.view(require(req))

    @r.post("/subnets")
    def add_subnet(s: SubnetIn, req: Request):
        return ws.add_subnet(require(req), s.netuid)

    @r.delete("/subnets/{netuid}")
    def remove_subnet(netuid: int, req: Request):
        return ws.remove_subnet(require(req), netuid)

    @r.get("/subnets/{netuid}/brief")
    def subnet_brief(netuid: int, req: Request, hardware: str | None = None, own: bool = False):
        return ws.brief(require(req), netuid, hardware, own)

    @r.post("/agents")
    def add_agent(a: AgentRef, req: Request):
        return ws.add_agent(require(req), a.agent_id)

    @r.post("/team")
    def add_team(req: Request):
        return ws.add_team(require(req))

    @r.delete("/agents/{aid}")
    def remove_agent(aid: int, req: Request):
        return ws.remove_agent(require(req), aid)

    @r.put("/agents/selected")
    def select_agent(a: AgentRef, req: Request):
        return ws.select_agent(require(req), a.agent_id)

    @r.get("/chat")
    def chat_view(agent_id: int, netuid: int, req: Request):
        return ws.chat_view(require(req), agent_id, netuid)

    @r.post("/chat")
    def chat(c: WsChatIn, req: Request):
        me = require(req)
        if ready: ready(c.model)
        return ws.chat(me, c)

    @r.delete("/chat")
    def new_chat(agent_id: int, netuid: int, req: Request):
        return ws.new_chat(require(req), agent_id, netuid)

    @r.get("/notes")
    def notes(req: Request):
        return ws.notes(require(req))

    @r.post("/notes")
    def add_note(n: NoteIn, req: Request):
        return ws.add_note(require(req), n)

    @r.get("/notes/daily")
    def daily(day: str, req: Request, create: bool = False):
        return ws.daily(require(req), day, create)

    @r.patch("/notes/{nid}")
    def update_note(nid: int, p: NotePatch, req: Request):
        return ws.update_note(require(req), nid, p)

    @r.delete("/notes/{nid}")
    def delete_note(nid: int, req: Request):
        return ws.delete_note(require(req), nid)

    @r.get("/files")
    def files(req: Request):
        return ws.files(require(req))

    @r.post("/files")
    async def upload(req: Request, name: str, netuid: int | None = None):
        """The raw request body is the file (no multipart); it's passed on to the drive."""
        return await ws.upload(require(req), req, name, netuid)

    @r.get("/files/{fid}")
    def download(fid: str, req: Request):
        if not re.fullmatch(r"[0-9a-f]{32}", fid): raise HTTPException(404, "That file doesn't exist.")
        return ws.download(require(req), fid)

    @r.delete("/files/{fid}")
    def delete_file(fid: str, req: Request):
        return ws.delete_file(require(req), fid)

    return r
