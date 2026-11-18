"""The Lab's onboarding projects: real repositories to join, build and ship, the way new engineers start on a team.

Each project is a small Python library modeled on a public open-source AI project or engineering practice (Hugging Face
tokenizers, Google's SRE book, EleutherAI's lm-evaluation-harness). It has:
- files: the starting repo (README, ONBOARDING.md, Makefile, pyproject.toml, the package, smoke tests, .gitignore);
- tickets: what a new teammate picks up, in order, from a good first issue to the 0.1.0 release (added by
  _common.release). Each has acceptance tests, written into tests/ when the ticket is opened and run by the Lab's CI
  from the copy kept here (editing them doesn't pass a ticket), hints, and the reference solution with its patch.
The Lab (frontend/lab.js) seeds a project into ~/projects/<id> and runs the checks in the browser (lab_shell.py), as it
does for lab tasks; nothing a learner runs reaches the server. tools/check_lab_projects.py proves that every ticket's
tests fail on the code it starts from and pass with its solution.
"""
import ast, difflib

from . import _common, evalkit, gateway, minitok


def _checks(tests):
    """The test functions of a test file, with the first line of their docstrings: the ticket's acceptance criteria."""
    return [{"name": f.name, "doc": (ast.get_docstring(f) or "").split("\n")[0]}
            for f in ast.parse(tests).body if isinstance(f, ast.FunctionDef) and f.name.startswith("test")]


def _patch(before, after):
    """The reference pull request: a unified diff of the files a solution changes."""
    out = []
    for path in sorted(after):
        a = before.get(path)
        out += difflib.unified_diff((a or "").splitlines(True), after[path].splitlines(True),
                                    f"a/{path}" if a is not None else "/dev/null", f"b/{path}")
    return "".join(out)


def _prepare(p):
    tickets, ids = p["tickets"], [t["id"] for t in p["tickets"]]
    agenda = "\n".join(f"{i}. **{t['id']}** · {t['kind']}: {t['title']}" for i, t in enumerate(tickets, 1))
    agenda += f"\n{len(tickets) + 1}. **{ids[0].split('-')[0]}-{len(tickets) + 1}** · release: cut 0.1.0"
    def state(done):
        files = {path: _common.render(f, done).strip("\n") + "\n" for path, f in p["files"].items()}
        files["ONBOARDING.md"] = files["ONBOARDING.md"].replace("{tickets}", agenda)
        files["tests/test_smoke.py"] = p["smoke"].strip("\n") + "\n"
        return files
    out = []
    for i, t in enumerate(tickets):
        before, after = state(set(ids[:i])), state(set(ids[:i + 1]))
        out.append({**t, "solution": {path: text for path, text in after.items() if text != before[path]}, "commands": []})
    final = state(set(ids))
    out.append(_common.release(p, final, len(tickets) + 1))
    start = state(set())
    for i, t in enumerate(out):
        before = {path: text for path, text in start.items()}
        for prev in out[:i]: before.update(prev["solution"])
        t.update(tests=t["tests"].strip("\n") + "\n", body=t["body"].strip(), checks=_checks(t["tests"]), patch=_patch(before, t["solution"]))
    return {**{k: v for k, v in p.items() if k not in ("files", "tickets", "smoke")},
            "files": start, "smoke": start["tests/test_smoke.py"], "tickets": out, "onboarding": start["ONBOARDING.md"]}


PROJECTS = [_prepare(m.PROJECT) for m in (minitok, gateway, evalkit)]
BY_ID = {p["id"]: p for p in PROJECTS}
_TICKET = ("id", "kind", "title", "estimate", "topic", "touch", "test_path", "tests", "checks", "body", "hints", "patch")


def catalog():
    """What the Projects tab lists: each project without its files."""
    return [{k: p[k] for k in ("id", "name", "title", "like", "org", "blurb", "level", "hours", "skills", "topics")}
            | {"tickets": [{k: t[k] for k in ("id", "kind", "title")} for t in p["tickets"]]} for p in PROJECTS]


def get(pid):
    """A project as the page needs it: the starting files, the onboarding doc, the smoke tests and the tickets. The
    reference solutions travel as patches, shown once a learner has run CI; the solution files stay here."""
    p = BY_ID.get(pid)
    if not p: return None
    return {**{k: p[k] for k in ("id", "name", "title", "like", "org", "blurb", "level", "hours", "skills", "topics", "package",
                                  "onboarding", "smoke")},
            "files": [{"path": k, "content": v} for k, v in p["files"].items()],
            "tickets": [{k: t[k] for k in _TICKET} for t in p["tickets"]]}
