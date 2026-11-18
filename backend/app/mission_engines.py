"""Mission OS: which engine fits a goal, from how the owner's earlier missions like it went (missions.py asks it at UNDERSTAND).

- Similar missions: the owner's delivered missions whose goal and title share enough words with this one (Jaccard over the
  stemmed words missions.py uses for discovery, at least SIMILAR), the NEAREST closest.
- Track record per engine over them: how many ran there, how they came out (verified 100, partial 50, failed 0; unverified
  ones don't count), shrunk towards PRIOR so two missions don't make a verdict, and what they cost and took on average.
- The record goes into the understanding prompt as evidence. And in code: when the engine the model picked has clearly done
  worse on similar goals than another engine that's available (both with at least MIN_RUNS missions, a gap of at least GAP
  points), the mission runs on the other one and says why. A forced engine or a team the user picked is never switched, and
  nothing is switched to or from a Competition team: that belongs to the goal, not to a track record.
"""

SCORE = {"verified": 100, "partial": 50, "failed": 0}
SIMILAR, NEAREST = 0.15, 12
PRIOR, PRIOR_WEIGHT = 50, 2
MIN_RUNS, GAP = 3, 35
NO_SWITCH = {"mining"}


def _jaccard(a, b): return len(a & b) / len(a | b) if a and b else 0.0


def record(rows, want, words):
    """{"similar": n, "engines": {engine: {n, verified, partial, failed, score, usd, minutes}}} over the delivered missions in
    `rows` (dicts with goal, title, engine, outcome, own_usd, child_usd, started, finished) most like the words `want`."""
    near = sorted(((_jaccard(want, words(f"{r.get('title') or ''} {r.get('goal') or ''}")), r) for r in rows), key=lambda x: -x[0])
    near = [r for s, r in near if s >= SIMILAR][:NEAREST]
    out = {}
    for r in near:
        if r.get("outcome") not in SCORE or not r.get("engine"): continue
        e = out.setdefault(r["engine"], {"n": 0, "verified": 0, "partial": 0, "failed": 0, "sum": 0, "usd": 0.0, "secs": 0.0})
        e["n"] += 1; e[r["outcome"]] += 1; e["sum"] += SCORE[r["outcome"]]
        e["usd"] += (r.get("own_usd") or 0) + (r.get("child_usd") or 0)
        if r.get("started") and r.get("finished"): e["secs"] += r["finished"] - r["started"]
    for e in out.values():
        e["score"] = round((PRIOR * PRIOR_WEIGHT + e.pop("sum")) / (PRIOR_WEIGHT + e["n"]))
        e["usd"] = round(e["usd"] / e["n"], 3)
        e["minutes"] = round(e.pop("secs") / e["n"] / 60, 1)
    return {"similar": len(near), "engines": out}


def lines(rec, labels):
    """The record as prompt lines, or "" when there's none."""
    if not rec["engines"]: return ""
    out = [f"- {labels.get(k, k)} ({k}): {e['n']} similar mission(s): {e['verified']} verified, {e['partial']} partial, {e['failed']} failed; "
           f"score {e['score']}/100, about ${e['usd']:.2f} and {e['minutes']:.0f} min each" for k, e in sorted(rec["engines"].items(), key=lambda x: -x[1]["score"])]
    return ("\n<track_record>\nHow your earlier missions most like this one went, by engine (weigh it, with the goal itself, when you pick the engine):\n"
            + "\n".join(out) + "\n</track_record>")


def advise(rec, pick, available, fixed=False):
    """(engine, why or None): `pick`, or a clearly better engine for goals like this one from the record."""
    if fixed or pick in NO_SWITCH: return pick, None
    eng = rec["engines"]
    mine = eng.get(pick)
    if not mine or mine["n"] < MIN_RUNS: return pick, None
    best = max(((k, e) for k, e in eng.items() if k != pick and k not in NO_SWITCH and available.get(k) and e["n"] >= MIN_RUNS),
               key=lambda x: x[1]["score"], default=None)
    if not best or best[1]["score"] - mine["score"] < GAP: return pick, None
    k, e = best
    return k, (f"on {rec['similar']} similar earlier missions, {k} scored {e['score']}/100 over {e['n']} "
               f"and {pick} {mine['score']}/100 over {mine['n']}")
