"""The REPL of a recursive language model (backend/app/rlm.py), run in a sandbox pod as `python3 repl.py`.

The pod can't be reached from outside, so it pulls its work from AXoR through the sandbox proxy ($SANDBOX_PROXY_URL):
GET /rlm/context once (the data, the sub-model, the limits), then GET /rlm/cell for each piece of code the root model
writes and POST /rlm/result with what it printed. Variables persist between cells. llm_query and llm_batch call the
sub-model through the proxy's chat completions, within the run's budget. Standard library only.
"""
import ast, contextlib, io, json, os, signal, sys, threading, time, traceback, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ["SANDBOX_PROXY_URL"].rstrip("/")
USE = {"calls": 0, "tokens": 0}
USE_LOCK = threading.Lock()
ANSWER_CHARS = 200_000  # the proxy takes 8 MB a request; an answer longer than this is a mistake (e.g. the whole context)

def _http(path, body=None, timeout=90):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")

def _get(path):
    for i in range(20):  # the proxy may restart under us; give it a little time
        try: return _http(path)
        except urllib.error.HTTPError as e:
            if e.code == 404: sys.exit("The run is over (the proxy no longer knows it).")
            if i == 19: raise
            time.sleep(3)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
            if i == 19: raise
            time.sleep(3)

CFG = _get("/rlm/context")

def llm_query(prompt, model=None):
    """Asks the sub-model one question; returns its answer as text (or "[llm error: ...]")."""
    body = {"model": model or CFG["sub_model"], "messages": [{"role": "user", "content": str(prompt)}]}
    try: out = _http("/api/v1/chat/completions", body, timeout=CFG.get("sub_timeout", 300))
    except urllib.error.HTTPError as e:
        if e.code == 402: return "[llm error: the run's sub-call budget is spent]"
        try: msg = (json.loads(e.read() or b"{}").get("error") or {}).get("message") or ""
        except ValueError: msg = ""
        return f"[llm error {e.code}: {msg or e.reason}]"
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        return f"[llm error: {getattr(e, 'reason', e)}]"
    with USE_LOCK:
        USE["calls"] += 1
        USE["tokens"] += int(((out.get("usage") or {}).get("total_tokens")) or 0)
    if out.get("error"): return f"[llm error: {(out['error'] or {}).get('message', out['error'])}]"
    try: return (out["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError): return "[llm error: the sub-model sent no answer]"

def llm_batch(prompts, model=None):
    """llm_query on every prompt in parallel; the answers in the same order."""
    prompts = list(prompts)
    if not prompts: return []
    pool = ThreadPoolExecutor(max_workers=max(1, min(int(CFG.get("parallel", 8)), len(prompts))))
    try: return list(pool.map(lambda p: llm_query(p, model), prompts))
    finally: pool.shutdown(wait=False, cancel_futures=True)  # a cell stopped by its time limit drops the queued prompts

class CellTimeout(BaseException):  # not Exception: a cell's `except Exception` mustn't swallow the time limit
    pass

def _alarm(*_): raise CellTimeout()

def _cut(text, n):
    if len(text) <= n: return text
    head = n * 2 // 3
    return text[:head] + f"\n… ({len(text) - n} characters cut: print less, or slice) …\n" + text[-(n - head):]

def _trace():
    """The current exception's traceback without this file's frames: the model only needs its own code's."""
    te = traceback.TracebackException(*sys.exc_info())
    te.stack = traceback.StackSummary.from_list([f for f in te.stack if os.path.basename(f.filename) != os.path.basename(__file__)])
    return "".join(te.format())

def _run(code, ns, limit):
    """Runs one cell like a notebook (the last expression's value is shown); returns (output, error)."""
    buf, err = io.StringIO(), None
    try: tree = ast.parse(code, "<cell>", "exec")
    except SyntaxError:
        return "", traceback.format_exc(limit=0)
    last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(limit)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(tree, "<cell>", "exec"), ns)
            if last is not None:
                v = eval(compile(ast.Expression(last.value), "<cell>", "eval"), ns)
                if v is not None: print(repr(v))
    except CellTimeout:
        err = f"CellTimeout: the cell ran past {limit} s and was stopped (variables set before that are kept)."
    except BaseException:  # noqa: BLE001 - SystemExit and KeyboardInterrupt in a cell end the cell, not the REPL
        err = _trace()
    finally:
        signal.alarm(0)
    return buf.getvalue(), err

def main():
    ns = {"__name__": "__main__", "context": CFG["context"], "answer": {"content": "", "ready": False},
          "llm_query": llm_query, "llm_batch": llm_batch}
    out_chars, limit = int(CFG.get("out_chars", 8192)), int(CFG.get("cell_timeout", 120))
    print(f"REPL ready: {len(CFG['context'])} {'files' if isinstance(CFG['context'], dict) else 'characters'} of context", flush=True)
    while True:
        cell = _get("/rlm/cell")
        if cell.get("stop"): break
        if cell.get("wait") or "code" not in cell: continue
        before, t0 = dict(USE), time.time()
        out, err = _run(cell["code"], ns, limit)
        ans = ns.get("answer")
        ans = ans if isinstance(ans, dict) else {"content": "" if ans is None else str(ans), "ready": False}
        res = {"id": cell["id"], "output": _cut(out, out_chars), "error": _cut(err, 4000) if err else None,
               "seconds": round(time.time() - t0, 2), "answer": {"content": _cut(str(ans.get("content") or ""), ANSWER_CHARS), "ready": ans.get("ready") is True},
               "sub_calls": USE["calls"] - before["calls"], "sub_tokens": USE["tokens"] - before["tokens"]}
        print(f"cell {cell['id']}: {res['seconds']} s, {res['sub_calls']} sub-call(s){', error' if err else ''}", flush=True)
        for i in range(2):
            try: _http("/rlm/result", res); break
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
                print(f"couldn't send the result of cell {cell['id']}: {e}", flush=True)
                time.sleep(3)
    print(f"REPL done: {USE['calls']} sub-call(s), {USE['tokens']} tokens", flush=True)

if __name__ == "__main__":
    main()
