"""Scripted model for Long tasks (infiagent.py), on top of fake_claude (AGENT_CLIENT_FACTORY=fake_infiagent:factory).

It drives a literature-review run the way the paper's long-horizon test does: the Alpha hands "note every document in
docs/" to the data collection agent, then "write review.md" to the writer, then finishes. The collector asks the reader
about one document, appends a note about it to notes.md, and moves to the next. It knows which documents are done only
from its thinking record and the action window, so with a small thinking interval the run crosses several window resets
and still has to cover every document exactly once: the mechanism under test.

FAKE_SLOW (seconds) sleeps before each agent step, for pause, cancel and restart tests."""
import itertools, json, os, re, time

import fake_claude
from fake_claude import Resp

_ids = itertools.count(1)

def _text(kw):
    m = kw["messages"][-1]["content"]
    return m if isinstance(m, str) else "\n".join(b.get("text", "") for b in m if b.get("type") == "text")

def _system(kw):
    s = kw.get("system")
    return s[0]["text"] if isinstance(s, list) else s or ""

def _tag(text, name):
    m = re.search(rf"<{name}[^>]*>\n?(.*?)\n?</{name}>", text, re.S)
    return m.group(1) if m else ""

def _json(obj): return Resp([{"type": "text", "text": json.dumps(obj)}], "end_turn")

def _call(name, inp): return Resp([{"type": "tool_use", "id": f"toolu_ia{next(_ids)}", "name": name, "input": inp}], "tool_use")

def _covered(text):
    """Documents noted so far: the record's pinned "covered:" line plus notes appended in the window."""
    got = set()
    for line in re.findall(r"^covered: (.*)$", text, re.M):
        got.update(x.strip() for x in line.split(",") if x.strip())
    got.update(re.findall(r'"content":"- (docs/[^:"]+):', text))
    return got

def _think(kw):
    p = _text(kw)
    docs = sorted(re.findall(r"^(docs/\S+) \(", _tag(p, "workspace"), re.M))
    covered = sorted(_covered(_tag(p, "current_progress_thinking") + _tag(p, "recent_actions")))
    task = _tag(p, "current_task")
    todo = [{"item": f"Note {d}", "status": "done" if d in covered else "waiting"} for d in docs] if "docs/" in task else [{"item": _clip(task), "status": "ongoing"}]
    left = [d for d in docs if d not in covered]
    return {"todo_list": todo, "file_descriptions": [{"path": "notes.md", "purpose": "One note per document", "when": "Before noting the next document"}],
            "persistent_state": f"docs: {', '.join(docs)}\ncovered: {', '.join(covered)}",
            "next_steps": [f"answer_from_documents on {d}, then append_file notes.md" for d in left[:3]] or ["final_output"]}

def _clip(s, n=80): return s if len(s) <= n else s[:n - 1] + "…"

def _alpha(p):
    tree, window = _tag(p, "agent_call_tree"), _tag(p, "action_window")
    done = lambda role: re.search(rf"· {role} done", tree) or f'tool="{role}"' in window and '"status":"done"' in window.split(f'tool="{role}"')[-1]
    if not done("data_collection_agent"):
        return _call("data_collection_agent", {"task": "Read every document in docs/ with answer_from_documents and append one note per document to notes.md, "
                                                       "as '- docs/<name>: <what it says>'."})
    if not done("material_to_document_agent"):
        return _call("material_to_document_agent", {"task": "Write review.md from notes.md: one entry per document."})
    return _call("final_output", {"result": "Review written: review.md covers every document.", "files": ["review.md", "notes.md"]})

def _collector(p):
    record, window = _tag(p, "thinking_record"), _tag(p, "action_window")
    docs = [x.strip() for x in (re.search(r"^docs: (.*)$", record, re.M) or [None, ""])[1].split(",") if x.strip()]
    covered = _covered(record + window)
    acts = re.findall(r'<action n="\d+" tool="([^"]+)">\n<input>(.*?)</input>\n<result[^>]*>(.*?)</result>', window, re.S)
    if acts and acts[-1][0] == "answer_from_documents":
        doc = json.loads(acts[-1][1])["paths"][0]
        if doc not in covered:
            answer = re.search(r'"answer":"([^"]*)"', acts[-1][2])
            return _call("append_file", {"path": "notes.md", "content": f"- {doc}: the document reports that {answer.group(1) if answer else 'nothing was found'}"})
    left = [d for d in docs if d not in covered]
    if left: return _call("answer_from_documents", {"question": "What is this document's main finding?", "paths": [left[0]]})
    return _call("final_output", {"result": f"Noted {len(covered)} documents in notes.md.", "files": ["notes.md"]})

def _writer(p):
    window = _tag(p, "action_window")
    if 'tool="read_file"' not in window and 'tool="write_file"' not in window:
        return _call("read_file", {"path": "notes.md", "offset": 0})
    if 'tool="write_file"' not in window:
        notes = re.search(r'"content":"(.*?)","(?:next_offset|end)', window, re.S)
        body = (notes.group(1) if notes else "").replace("\\n", "\n").replace("- docs/", "## docs/").replace(": the document", "\nThe document")
        return _call("write_file", {"path": "review.md", "content": "# Review\n\n" + body})
    return _call("final_output", {"result": "review.md is written.", "files": ["review.md"]})

class Messages:
    def create(self, **kw):
        system = _system(kw)
        fmt = (kw.get("output_config") or {}).get("format")
        if fmt and system.startswith("You are a context-management specialist"):
            return _json(_think(kw))
        if fmt and system.startswith("You are a document reader"):
            words = re.sub(r"<[^>]+>", " ", _tag(_text(kw), "document")).split()
            return _json({"relevant": True, "answer": " ".join(words[:12]) or "nothing"})
        if fmt and system.startswith("You merge partial answers"):
            return _json({"answer": " / ".join(_tag(x, "part") for x in re.findall(r"<part>.*?</part>", _text(kw), re.S))})
        if "AXoR InfiAgent" in system and kw.get("tools"):
            if os.getenv("FAKE_SLOW"): time.sleep(float(os.getenv("FAKE_SLOW")))
            p = _text(kw)
            if system.startswith("You are Alpha"): return _alpha(p)
            if system.startswith("You are Data collection"): return _collector(p)
            if system.startswith("You are Writer"): return _writer(p)
            return _call("final_output", {"result": "Nothing to do here.", "files": []})
        return fake_claude.Messages().create(**kw)

class Beta:
    messages = Messages()

class Client:
    beta = Beta()

def factory():
    return Client()
