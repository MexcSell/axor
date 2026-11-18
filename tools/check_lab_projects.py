"""Checks the Study Lab's onboarding projects (backend/app/lab_projects) with the Lab's own shell (frontend/lab_shell.py),
under CPython. For each project:
- the smoke tests pass on the starting files;
- each ticket's checks fail on the code the ticket starts from, and pass once its solution and commands are applied,
  with the smoke tests and every earlier ticket's checks still passing (CI's regression jobs);
- the Makefile's demo targets run (make demo, slo, eval…) with the exit codes they should have, and so does make test
  when pytest is installed.
Run it after editing a project:  python tools/check_lab_projects.py [project-id…]
"""
import asyncio, importlib.util, os, pathlib, re, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import lab_projects  # noqa: E402

DEMOS = {"minitok": [("make demo", 0)], "gateway": [("make slo", 0)], "evalkit": [("make eval", 0), ("make gate", 2)]}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def shell():
    spec = importlib.util.spec_from_file_location("lab_shell", ROOT / "frontend" / "lab_shell.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def check(sh, p, home):
    out, folder, problems = [], f"projects/{p['id']}", []
    lab = sh.Lab(lambda stream, text: out.append(text), home, "ci")
    def failing(r): return r.get("error") or [x["name"] for x in r["results"] if not x["ok"]]
    def explain(r): return r.get("error") or "; ".join(f"{x['name']}: {x['message'][:160]}" for x in r["results"] if not x["ok"])
    async def sh_run(cmd):
        out.clear()
        r = await lab.line(f"cd ~/{folder} && {cmd}")
        return r["code"], ANSI.sub("", "".join(out))

    lab.seed(folder, [{"path": k, "content": v} for k, v in p["files"].items()])
    if failing(r := await lab.check(folder, p["smoke"])): problems.append(f"smoke tests fail on the starting files: {explain(r)}")
    for i, t in enumerate(p["tickets"]):
        if [c["name"] for c in t["checks"]] != re.findall(r"^def (test\w*)", t["tests"], re.M):
            problems.append(f"{t['id']}: its checks list doesn't match its tests")
        lab.seed(folder, [{"path": t["test_path"], "content": t["tests"]}])
        if not failing(await lab.check(folder, t["tests"])): problems.append(f"{t['id']}: its checks pass before its solution")
        lab.seed(folder, [{"path": k, "content": v, "force": True} for k, v in t["solution"].items()])
        for cmd in t["commands"]:
            code, text = await sh_run(cmd)
            if code: problems.append(f"{t['id']}: `{cmd}` exited {code}:\n{text[-800:]}")
        if failing(r := await lab.check(folder, t["tests"])): problems.append(f"{t['id']}: its checks fail with its solution: {explain(r)}")
        for name, tests in [("smoke", p["smoke"])] + [(x["id"], x["tests"]) for x in p["tickets"][:i]]:
            if failing(r := await lab.check(folder, tests)): problems.append(f"{t['id']} breaks {name}: {explain(r)}")
        print(f"  {t['id']:<5} {t['kind']:<17} {len(t['checks'])} checks  {t['title']}")
    for cmd, want in DEMOS.get(p["id"], []) + ([("make test", 0)] if importlib.util.find_spec("pytest") else []):
        code, text = await sh_run(cmd)
        print(f"  {cmd:<23} exit {code}" + (f"  (expected {want})" if code != want else ""))
        if code != want: problems.append(f"`{cmd}` exited {code}, expected {want}:\n{text[-1500:]}")
    return problems


async def main(ids):
    sh, bad = shell(), 0
    for p in lab_projects.PROJECTS:
        if ids and p["id"] not in ids: continue
        print(f"{p['id']} ({len(p['files'])} files, {len(p['tickets'])} tickets)")
        with tempfile.TemporaryDirectory(prefix="lab-project-") as tmp:
            tempfile.tempdir = os.path.join(tmp, "tmp")  # where the checks' own temporary files go
            os.mkdir(tempfile.tempdir)
            try: problems = await check(sh, p, os.path.join(os.path.realpath(tmp), "home"))
            finally: tempfile.tempdir = None; os.chdir(ROOT)  # the shell works in its home
        for problem in problems:
            print(f"  FAIL {problem}"); bad += 1
    print("all projects check out" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
