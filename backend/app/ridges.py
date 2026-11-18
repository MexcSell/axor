"""Ridges (SN62) competitions, read from ridges.ai's public competitions page.

Ridges documents no JSON API for its competitions, so this reads what the page itself renders from: the page streams its data
to the browser as Next.js "flight" chunks (self.__next_f.push([1, "…"])), and each competition is an object with a setId. A
redesign of the site can break this; callers treat any failure as "couldn't read Ridges" and keep what they have.
"""
import json, os, re, time, urllib.request
from datetime import datetime

URL = os.getenv("RIDGES_URL", "https://www.ridges.ai").rstrip("/")
CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')

class RidgesError(Exception):
    """Ridges couldn't be read; the message is safe to show."""

def _day(s):
    """'Oct 29, 2026, 7:53 PM' (or an ISO time) as YYYY-MM-DD, else ''."""
    s = (s or "").strip()
    for f in ("%b %d, %Y, %I:%M %p", "%b %d, %Y"):
        try: return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError: pass
    m = re.match(r"\$?D?(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""

def parse(page):
    """Every competition object on the page: [{number, name, state, starts, ends, description, share, accepting, processable,
    emitting, link}], newest first."""
    text = "".join(json.loads(m.group(1)) for m in CHUNK.finditer(page))
    found, dec = {}, json.JSONDecoder()
    for m in re.finditer(r'\{"setId":', text):
        try: o, _ = dec.raw_decode(text, m.start())
        except ValueError: continue
        if not isinstance(o.get("setId"), int) or not o.get("name"): continue
        state = str(o.get("state") or o.get("laneState") or "").lower()
        found[o["setId"]] = {"number": o["setId"], "name": str(o["name"])[:80], "state": state,
                             "starts": _day(o.get("startedAt")), "ends": _day(o.get("endedAt")),
                             "description": str(o.get("description") or "")[:2000],
                             "share": float(o["emissionWeight"]) if isinstance(o.get("emissionWeight"), (int, float)) else None,
                             "accepting": bool(o.get("accepting")), "processable": bool(o.get("processable")),
                             "emitting": bool(o.get("emissionActive")), "link": f"{URL}/agents/{o['setId']}"}
    return sorted(found.values(), key=lambda c: -c["number"])

def status(c):
    """A workspace status for a Ridges competition: upcoming, active or closed."""
    if c["state"] in ("upcoming", "scheduled", "pending"): return "upcoming"
    if c["state"] in ("open", "active", "live") or c["accepting"] or c["emitting"]: return "active"
    return "closed"

def competitions(timeout=20):
    req = urllib.request.Request(f"{URL}/competitions", headers={"User-Agent": "AXoR My subnets (+competition import)", "Accept": "text/html"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: page = r.read(4_000_000).decode("utf-8", "replace")
    except (OSError, ValueError) as e:
        raise RidgesError(f"Couldn't read {URL}/competitions: {getattr(e, 'reason', e)}.") from None
    out = parse(page)
    if not out: raise RidgesError(f"{URL}/competitions answered ({time.time() - t0:.1f} s) but listed no competitions: the page may have changed.")
    return out
