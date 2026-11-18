"""LangGraph for stateful agent reasoning (5.1: the spec's "LangGraph for stateful agent reasoning", next to Temporal).

Off unless AGENT_GRAPH=langgraph. Then Mission Control's direct engine ("AXoR directly") stops being one model call and runs
this graph instead:

    draft ──► review ──► (meets the criteria, or MAX_ROUNDS revisions done, or the budget ran short) ──► END
                 ▲            │ otherwise
                 └── revise ◄─┘

State: the brief, the acceptance criteria, the current draft, the reviewer's gaps, the round, every review. Each node is one
of the mission's own structured calls (missions._ask): budget-checked before, charged after, one agent_core ledger run each,
on the model the router picks for the mission, so nothing about cost, routing or the ledger changes. A review or a revision
the budget can't cover ends the graph with the draft it has (the mission's verify step still judges it independently).

The graph is compiled once per process; it keeps no checkpoint of its own (Temporal is the durable layer: a stage that dies
re-runs from its start). langgraph is in requirements.txt from 5.1; without it, the direct engine runs its single call.
"""
import logging, os

log = logging.getLogger("agent_graph")

ENABLED = os.getenv("AGENT_GRAPH", "").lower() == "langgraph"
MAX_ROUNDS = int(os.getenv("AGENT_GRAPH_ROUNDS", "2"))
REVIEW_TOKENS = 8000

REVIEW = {"type": "object", "additionalProperties": False, "required": ["meets", "gaps"], "properties": {
    "meets": {"type": "boolean", "description": "True when the draft meets every acceptance criterion."},
    "gaps": {"type": "array", "items": {"type": "string"}, "description": "Each criterion the draft misses or only half meets, and what's missing."}}}


def installed():
    try:
        import langgraph  # noqa: F401
        return True
    except ImportError:
        return False


def status():
    return {"enabled": ENABLED, "installed": installed(), "max_rounds": MAX_ROUNDS,
            "error": "langgraph isn't installed in this image" if ENABLED and not installed() else None}


def build(ask_draft, ask_review, ask_revise, stop=(Exception,), max_rounds=MAX_ROUNDS):
    """The compiled graph. ask_* are the model calls: draft(state) -> out dict, review(state) -> {meets, gaps},
    revise(state) -> out dict. An exception in `stop` from review/revise ends the run with the current draft."""
    from typing import TypedDict
    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        out: dict
        meets: bool
        gaps: list
        rounds: int
        reviews: list
        stopped: str

    def draft(st):
        return {"out": ask_draft(st), "rounds": 0, "reviews": []}

    def review(st):
        try: r = ask_review(st)
        except stop as e: return {"stopped": str(getattr(e, "why", e)), "meets": False}
        gaps = [str(g) for g in (r.get("gaps") or [])][:10]
        return {"meets": bool(r.get("meets")) and not gaps, "gaps": gaps,
                "reviews": (st.get("reviews") or []) + [{"round": st.get("rounds", 0), "meets": bool(r.get("meets")), "gaps": gaps}]}

    def revise(st):
        try: out = ask_revise(st)
        except stop as e: return {"stopped": str(getattr(e, "why", e))}
        return {"out": out, "rounds": st.get("rounds", 0) + 1}

    def after_review(st):
        if st.get("stopped") or st.get("meets") or st.get("rounds", 0) >= max_rounds: return END
        return "revise"

    def after_revise(st):
        return END if st.get("stopped") else "review"

    g = StateGraph(S)
    g.add_node("draft", draft)
    g.add_node("review", review)
    g.add_node("revise", revise)
    g.add_edge(START, "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", after_review, ["revise", END])
    g.add_conditional_edges("revise", after_revise, ["review", END])
    return g.compile()


def direct(missions, m, prompt, schema, tokens):
    """Mission Control's direct engine as a graph: (out, model) like missions._ask, out with the review trail in `graph`."""
    from .missions import Pause
    used = {"model": None}
    crit = (m.get("understanding") or {}).get("criteria") or []

    def call(name, schema_, text, n, effort):
        out, model = missions._ask(m, "execute", schema_, name, text, tokens=n, effort=effort)
        used["model"] = model
        return out

    def ask_draft(st):
        return call("deliverable", schema, prompt, tokens, "high")

    def ask_review(st):
        d = st["out"]
        text = ("Review this draft against the acceptance criteria. Name only real gaps, each with what's missing.\n\nAcceptance criteria:\n"
                + "\n".join(f"- {c}" for c in crit) + f"\n\n<draft>\n{str(d.get('deliverable') or '')[:40000]}\n</draft>")
        return call("review", REVIEW, text, REVIEW_TOKENS, "medium")

    def ask_revise(st):
        d = st["out"]
        text = (prompt + f"\n\nYour previous draft:\n<draft>\n{str(d.get('deliverable') or '')[:40000]}\n</draft>\n\nA reviewer found these gaps:\n"
                + "\n".join(f"- {g}" for g in st.get("gaps") or []) + "\n\nWrite the complete improved deliverable.")
        return call("revision", schema, text, tokens, "high")

    final = build(ask_draft, ask_review, ask_revise, stop=(Pause,)).invoke({"rounds": 0})
    out = dict(final.get("out") or {})
    out["graph"] = {"engine": "langgraph", "rounds": final.get("rounds", 0), "meets": bool(final.get("meets")),
                    "reviews": final.get("reviews") or [], "stopped": final.get("stopped")}
    if final.get("stopped"):
        out["limits"] = list(out.get("limits") or []) + [f"Review stopped early: {final['stopped']}"]
    elif not final.get("meets") and final.get("gaps"):
        out["limits"] = list(out.get("limits") or []) + [f"Reviewer's open gap: {g}" for g in final["gaps"][:4]]
    missions._event(m["id"], "execute", "stage", f"LangGraph: {out['graph']['rounds']} revision(s), "
                    + ("meets the criteria by its own review" if out["graph"]["meets"] else "gaps left for verification"))
    return out, used["model"]
