"""Recursive language models (RLM): answering a question over data too large for a model's context, after Prime Intellect's
RLM environment (primeintellect.ai/blog/rlm), itself after Zhang & Khattab's "Recursive Language Models".

- The data never enters the root model's context. It sits in a Python REPL as `context` (a string, or {path: text} for
  files); the root model sees the question, the data's shape, and what its code prints (cut to OUT_CHARS per cell).
- The root model works through one tool, python(code). In the REPL, llm_query(prompt) and llm_batch(prompts) send work to a
  sub-model (in parallel for a batch), so the root can map a question over chunks and combine the answers in code.
- The answer lives in the REPL: answer = {"content": "", "ready": False}. The model refines answer["content"] as it goes
  and the run ends once a cell leaves answer["ready"] True (or the turns run out: then the latest content, marked unfinished).
- Depth 1, as in the blog: sub-calls are plain model calls. A nested RLM would need a second sandbox pod while this one
  holds a slot, so llm_query never recurses.

The REPL runs in a sandbox pod (sandbox.py), never in AXoR: rlm_files/repl.py pulls the context and each cell from the sandbox
proxy (the only thing the pod can reach) and posts back the output. Sub-calls go through the proxy's chat completions to
OpenRouter, so the run's dollar cap covers them; the root model is any provider AXoR has (Providers.completer).
"""
import json, logging, os, threading, time
from pathlib import Path

from .llm import LLMError
from .sandbox import SandboxError

log = logging.getLogger("rlm")
REPL = Path(__file__).parent / "rlm_files" / "repl.py"
SUB_MODEL = os.getenv("RLM_SUB_MODEL", "openai/gpt-5-mini")
OUT_CHARS = 8192            # REPL output the root model sees per cell (the blog's default)
CELL_TIMEOUT = 120          # seconds per cell (the blog's default)
MAX_TURNS = 24
PARALLEL = 8                # llm_batch calls at once
CHUNK = 200_000             # characters a sub-call reads well (the paper's advice for its sub-models)
MAX_CONTEXT = 30_000_000    # characters
START_WAIT = 420            # a sandbox slot, then the pod (the first image pull takes a while)
SUB_TIMEOUT = 300           # seconds per sub-call
POLL = 25                   # seconds a REPL's request for the next cell is held open

PYTHON_TOOL = {"name": "python",
               "description": "Runs Python in your REPL session (variables persist between calls) and returns what it printed. "
                              "The value of a final expression is shown, like a notebook.",
               "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"], "additionalProperties": False}}

SYSTEM = """You answer a question about data too large to read at once. The data is not in this conversation: it is in a Python REPL, \
as the variable `context`. You work by running code there with the python tool; the session keeps its variables between calls.

In the REPL:
- `context`: {shape}
- `llm_query(prompt) -> str`: asks a sub-model ({sub}) and returns its answer. It sees only the prompt you give it, so put the \
text it needs in the prompt; it handles up to about {chunk:,} characters well.
- `llm_batch(prompts) -> list[str]`: llm_query on many prompts in parallel ({parallel} at a time), answers in order. One \
llm_batch is much faster than a loop of llm_query.
- `answer`: {{"content": "", "ready": False}}. Write your answer to answer["content"], and improve it as you learn more. When \
it is complete and checked, set answer["ready"] = True: the run ends after that cell and answer["content"] is what's returned.
- Python 3.12 with its standard library (re, json, collections, ...). No internet, no pip.

How to work:
- Look before you read: len(context), the file names, a few hundred characters of a part, its structure. Search with re or \
str.find rather than printing whole parts.
- Each cell's output is cut to {out:,} characters (head and tail kept), so print summaries and slices, not the data.
- For questions over the whole data (find every..., count, classify, summarize each part), split it into chunks, send them \
through llm_batch with a precise instruction, then combine the answers in Python. Keep intermediate results in variables.
- Check what you can in code (counts, exact quotes, that a function or line exists) before setting ready.
- A cell may run {cell} s; you have {turns} turns.

The answer is for the person who asked: lead with it, then the specifics that back it (file paths, line numbers, figures, \
short quotes). Say what you couldn't establish rather than guessing."""

class RLMError(Exception):
    """The run couldn't start or broke down; the message is safe to show."""

def shape(context):
    """The context as the root model is told about it: kind and sizes, never the content."""
    if isinstance(context, str):
        return f"a string of {len(context):,} characters."
    sizes = sorted(((p, len(t)) for p, t in context.items()), key=lambda x: x[0])
    lines = [f"a dict of {len(sizes)} files, {{path: text}}, {sum(n for _, n in sizes):,} characters in all."]
    lines += [f"    {p} ({n:,})" for p, n in sizes[:60]]
    if len(sizes) > 60: lines.append(f"    … and {len(sizes) - 60} more (list(context) has them all)")
    return "\n".join(lines)

class Session:
    """The REPL's side of the conversation, served through the sandbox proxy's hook: one cell at a time."""
    def __init__(self, context, sub_model):
        self.cfg = {"context": context, "sub_model": sub_model, "out_chars": OUT_CHARS, "cell_timeout": CELL_TIMEOUT, "parallel": PARALLEL,
                    "sub_timeout": SUB_TIMEOUT}
        self.cv = threading.Condition()
        self.cell, self.results, self.seq = None, {}, 0
        self.ready = self.stopped = False
        self.ended = None  # the sandbox's result once the pod is gone

    def hook(self, method, path, body):
        if path == "/rlm/context" and method == "GET":
            with self.cv: self.ready = True; self.cv.notify_all()
            return 200, self.cfg
        if path == "/rlm/cell" and method == "GET":
            with self.cv:
                self.cv.wait_for(lambda: self.stopped or self.cell, timeout=POLL)
                if self.stopped: return 200, {"stop": True}
                if not self.cell: return 200, {"wait": True}
                cell, self.cell = self.cell, None
                return 200, cell
        if path == "/rlm/result" and method == "POST":
            with self.cv: self.results[body.get("id")] = body; self.cv.notify_all()
            return 200, {"ok": True}
        return 404, {"error": {"message": f"No such endpoint: {path}", "code": 404}}

    def wait_ready(self, deadline, cancelled):
        with self.cv:
            while not self.ready:
                if self.ended or cancelled() or time.time() > deadline: return False
                self.cv.wait(2)
        return True

    def run(self, code, cancelled):
        """Sends one cell and waits for its result (or for the pod to end)."""
        with self.cv:
            self.seq += 1
            cid, self.cell = self.seq, {"id": self.seq, "code": code}
            grace = max(CELL_TIMEOUT, SUB_TIMEOUT) + 60  # the cell's own limit, a sub-call in flight finishing, the round trips
            deadline = time.time() + grace
            while cid not in self.results:
                if cancelled(): raise RLMError("Stopped before it finished.")
                if self.ended:
                    raise RLMError("The REPL stopped: " + (self.ended.get("error") or self.ended.get("status") or "the pod ended") +
                                   (f"\n{self.ended.get('output', '')[-1500:]}" if self.ended.get("output") else ""))
                if time.time() > deadline: raise RLMError(f"The REPL didn't answer within {grace} s.")
                self.cv.wait(2)
            return self.results.pop(cid)

    def stop(self):
        with self.cv: self.stopped = True; self.cv.notify_all()

    def end(self, result):
        with self.cv: self.ended = result; self.cv.notify_all()

def _observation(r, turns_left):
    parts = [r.get("output") or ""]
    if r.get("error"): parts.append(r["error"])
    out = "\n".join(p.rstrip() for p in parts if p).strip() or "(no output)"
    a = r.get("answer") or {}
    meta = f"[{r.get('seconds', 0)} s of {CELL_TIMEOUT} s" + (f"; {r['sub_calls']} sub-call(s), {r.get('sub_tokens', 0):,} tokens" if r.get("sub_calls") else "") + \
           f"; answer: {len(a.get('content') or ''):,} characters, ready={a.get('ready') is True}; {turns_left} turn(s) left]"
    if turns_left == 1: meta += "\nLast turn: put your best answer in answer[\"content\"] and set answer[\"ready\"] = True now."
    return f"{out}\n{meta}"

def run(sbx, complete, question, context, *, sub_model=None, max_turns=MAX_TURNS, timeout=900, budget=1.0, label="RLM",
        cancelled=lambda: False, on_step=None, started=lambda pod: None):
    """Answers question over context (a string or {path: text}). complete(system, tools, messages) is the root model
    (Providers.completer). Blocks until done; returns {status, answer, ready, turns, steps, tokens, sub_calls, sub_tokens,
    cost, seconds, pod, error}. status: done (answer ready), unfinished (turns ran out), cancelled or error. on_step(step)
    sees each turn as it ends."""
    if isinstance(context, dict):
        context = {str(k): str(v) for k, v in context.items()}
        if len(context) == 1: context = next(iter(context.values()))
    size = len(context) if isinstance(context, str) else sum(len(v) for v in context.values())
    if not size: raise RLMError("There's no data to answer over.")
    if size > MAX_CONTEXT: raise RLMError(f"The data comes to {size:,} characters; an RLM run takes at most {MAX_CONTEXT:,}.")
    ok, why = sbx.ready()
    if not ok: raise RLMError(why)
    if not sbx.proxy.key_fn(): raise RLMError("The RLM's sub-model calls go through OpenRouter, and no OpenRouter key is connected (Agents → Models).")
    sub = sub_model or SUB_MODEL
    sess, t0, box = Session(context, sub), time.time(), {}
    stop = lambda: cancelled() or sess.stopped

    def pod():
        try: box["r"] = sbx.run({"repl.py": REPL.read_text()}, "python3 repl.py", (), timeout, budget, label=label, cancelled=stop,
                                started=started, hook=sess.hook)
        except SandboxError as e: box["r"] = {"status": "error", "error": str(e), "output": "", "cost": 0.0, "calls": 0}
        except Exception as e:  # noqa: BLE001 - reported as the run's error
            log.exception("rlm pod")
            box["r"] = {"status": "error", "error": f"The sandbox failed: {e}", "output": "", "cost": 0.0, "calls": 0}
        sess.end(box["r"])
    th = threading.Thread(target=pod, daemon=True, name="rlm-pod")
    th.start()

    steps, tokens, sub_calls, sub_tokens, answer, status, error = [], 0, 0, 0, {"content": "", "ready": False}, "error", ""
    try:
        if not sess.wait_ready(time.time() + START_WAIT, cancelled):
            if cancelled(): raise RLMError("Stopped before it finished.")
            r = sess.ended or {}
            raise RLMError("The REPL didn't start: " + (r.get("error") or r.get("status") or f"no pod within {START_WAIT} s") +
                           (f"\n{r.get('output', '')[-1500:]}" if r.get("output") else ""))
        system = SYSTEM.format(shape=shape(context), sub=sub, chunk=CHUNK, parallel=PARALLEL, out=OUT_CHARS, cell=CELL_TIMEOUT, turns=max_turns)
        messages = [{"role": "user", "content": [{"type": "text", "text": f"Question: {question}\n\nThe data (`context`): {shape(context)}\n\n"
                                                                         "Start by looking at it in the REPL."}]}]
        nudged = prose = False
        for turn in range(1, max_turns + 1):
            if cancelled(): raise RLMError("Stopped before it finished.")
            ts = time.time()
            content, stop_reason, n = complete(system, [PYTHON_TOOL], messages)
            tokens += n or 0
            messages.append({"role": "assistant", "content": content or [{"type": "text", "text": "(no answer)"}]})
            text = " ".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            calls = [b for b in content if b.get("type") == "tool_use"]
            step = {"turn": turn, "text": text, "cells": [], "seconds": 0.0}
            if not calls:
                if nudged or not text:  # it answered in prose twice: take the latest answer it wrote, else the prose
                    answer = {"content": answer["content"] or text, "ready": False}
                    prose = True
                    step["seconds"] = round(time.time() - ts, 1); steps.append(step)
                    if on_step: on_step(step)
                    break
                nudged = True
                messages.append({"role": "user", "content": [{"type": "text", "text": "Work in the REPL with the python tool. The run ends only "
                                 "when a cell sets answer[\"ready\"] = True; write your answer to answer[\"content\"] first."}]})
                step["seconds"] = round(time.time() - ts, 1); steps.append(step)
                if on_step: on_step(step)
                continue
            results = []
            for b in calls:
                code = (b.get("input") or {}).get("code") or ""
                if b.get("name") != "python" or not code.strip():
                    results.append({"type": "tool_result", "tool_use_id": b["id"], "content": "Call python with the code to run.", "is_error": True})
                    continue
                if answer["ready"]:  # an earlier call in this turn finished the run
                    results.append({"type": "tool_result", "tool_use_id": b["id"], "content": "Not run: the answer is ready."})
                    continue
                r = sess.run(code, cancelled)
                answer = r.get("answer") or answer
                sub_calls += r.get("sub_calls") or 0; sub_tokens += r.get("sub_tokens") or 0
                obs = _observation(r, max_turns - turn)
                step["cells"].append({"code": code, "output": obs, "error": bool(r.get("error")), "seconds": r.get("seconds"),
                                      "sub_calls": r.get("sub_calls") or 0})
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": obs, "is_error": bool(r.get("error"))})
            messages.append({"role": "user", "content": results})
            step["seconds"] = round(time.time() - ts, 1); steps.append(step)
            if on_step: on_step(step)
            if answer.get("ready"): break
        status = "done" if answer.get("ready") or (prose and answer["content"]) else "unfinished"
    except (RLMError, LLMError) as e:
        status, error = ("cancelled" if cancelled() else "error"), str(e)
    finally:
        sess.stop()
        th.join(timeout=60)
    r = box.get("r") or {}
    if status == "unfinished" and not error: error = f"The {max_turns} turns ran out before the answer was marked ready."
    return {"status": status, "answer": answer.get("content") or "", "ready": answer.get("ready") is True, "turns": len(steps), "steps": steps,
            "tokens": tokens, "sub_model": sub, "sub_calls": sub_calls, "sub_tokens": sub_tokens, "cost": r.get("cost") or 0.0,
            "seconds": round(time.time() - t0, 1), "pod": r.get("pod"), "error": error, "pod_output": r.get("output") or ""}

def transcript(question, res, root=""):
    """The run as readable text: for a sandbox run's output, or a log."""
    head = [f"RLM · {question}", f"root {root or 'model'} · sub {res['sub_model']} · {res['turns']} turn(s) · {res['sub_calls']} sub-call(s) · "
            f"{res['cost']:.3f} USD of sub-calls · {res['seconds']} s · {res['status']}"]
    if res.get("error"): head.append(f"error: {res['error']}")
    out = ["\n".join(head)]
    for s in res["steps"]:
        out.append(f"── turn {s['turn']} ({s['seconds']} s) ──" + (f"\n{s['text']}" if s["text"] else ""))
        for c in s["cells"]:
            out.append(">>> " + c["code"].rstrip().replace("\n", "\n... ") + "\n" + c["output"])
    out.append(f"── answer ({'ready' if res['ready'] else 'not marked ready'}) ──\n{res['answer'] or '(none)'}")
    return "\n\n".join(out)
